/*
 * RGB -> K, C, M, Y toner levels.
 *
 * Brother's filter converts colours with 17 x 17 x 17 tables (nodes every 16
 * input steps, 255 counting as 256) and tetrahedral interpolation. Its
 * in-cell weights behave like 12-bit fixed point that is not exactly f/16;
 * the tables below were fitted to black-box measurements (docs/FORMAT.md):
 * points with one channel between nodes reproduce Brother's output exactly;
 * for other colours about 93 % come out exact and the rest one level off in
 * one plane (0.03-0.04 % of all dots).
 *
 * The tables themselves are Brother's data. They are read from the user's
 * own copy of Brother's driver and never stored in this project.
 *
 * SPDX-License-Identifier: MIT
 */

#include "color.h"
#include "fsutil.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Weights in 1/4096 of a cell for in-cell positions 0..16, by how many of
 * the three channels lie between nodes (1, 2 or 3). */
static const int weights[4][17] = {
    {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4096}, /* on a node; 16 = input 255 */
    {0, 252, 506, 773, 1024, 1281, 1531, 1793, 2048, 2303, 2565, 2815, 3072, 3323, 3590, 3844, 4096},
    {0, 252, 506, 773, 1024, 1281, 1533, 1793, 2048, 2303, 2563, 2815, 3072, 3323, 3590, 3844, 4096},
    {0, 252, 506, 773, 1024, 1281, 1534, 1793, 2048, 2303, 2562, 2815, 3072, 3323, 3590, 3844, 4096},
};

static const char *const match_names[3] = {"Match Monitor", "Vivid", "None (Table Type)"};
static const char *const match_files[3] = {"normal", "vivid", "none"};

const char *color_table_file(color_matching m, int improve_gray, int fine) {
  static char buf[64];
  snprintf(buf, sizeof buf, "table-%s-gray%s-%s.bin", fine ? "capt" : "600", improve_gray ? "on" : "off",
           match_files[m]);
  return buf;
}

static void decode_le(color_table *t, const uint8_t *p) {
  for (size_t i = 0; i < COLOR_NODES * 4; i++)
    t->v[i] = (uint16_t)(p[2 * i] | p[2 * i + 1] << 8);
}

int color_table_load(color_table *t, const char *path) {
  FILE *f = fopen(path, "rb");
  if (!f)
    return -1;
  uint8_t *buf = malloc(COLOR_TABLE_BYTES + 1);
  /* exactly COLOR_TABLE_BYTES: one byte more means a wrong file */
  int ok = buf && fread(buf, 1, COLOR_TABLE_BYTES + 1, f) == COLOR_TABLE_BYTES;
  fclose(f);
  if (ok)
    decode_le(t, buf);
  free(buf);
  return ok ? 0 : -1;
}

/* Read a whole regular file of at most 64 MB (Brother's filter has 3 MB);
 * the installer does this as root, so a symlink is refused, not followed. */
static uint8_t *read_file(const char *path, size_t *len) {
  *len = 0;
  int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
  if (fd < 0)
    return NULL;
  struct stat st;
  if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > (64 << 20)) {
    close(fd);
    errno = EINVAL;
    return NULL;
  }
  size_t n = (size_t)st.st_size, got = 0;
  uint8_t *d = malloc(n);
  while (d && got < n) {
    ssize_t r = read(fd, d + got, n - got);
    if (r < 0 && errno == EINTR)
      continue;
    if (r <= 0)
      break;
    got += (size_t)r;
  }
  close(fd);
  if (!d || got != n) {
    free(d);
    return NULL;
  }
  *len = n;
  return d;
}

/* Find "HL-30xxC <mode> ImpGray=<ON|OFF> Ver... <match>" followed by its zero
 * terminator; the table starts right after the zero. The last occurrence is
 * used (the x86_64 slice; both slices hold identical tables). */
static const uint8_t *find_table(const uint8_t *d, size_t len, const char *mode, int improve_gray,
                                 const char *match) {
  char head[64];
  snprintf(head, sizeof head, "HL-30xxC %s ImpGray=%s Ver", mode, improve_gray ? "ON" : "OFF");
  size_t hl = strlen(head), ml = strlen(match);
  const uint8_t *found = NULL;
  for (size_t i = 0; i + hl < len; i++) {
    if (d[i] != 'H' || memcmp(d + i, head, hl) != 0)
      continue;
    const uint8_t *end = memchr(d + i, 0, len - i < 200 ? len - i : 200);
    if (!end || (size_t)(end - (d + i)) < hl + ml)
      continue;
    if (memcmp(end - ml, match, ml) != 0)
      continue;
    if ((size_t)(end + 1 - d) + COLOR_TABLE_BYTES > len)
      continue;
    found = end + 1;
  }
  return found;
}

int color_table_from_brother(color_table *t, const char *brother_filter, color_matching m, int improve_gray,
                             int fine) {
  size_t len;
  uint8_t *d = read_file(brother_filter, &len);
  if (!d)
    return -1;
  const uint8_t *p = find_table(d, len, fine ? "CAPT" : "600dpi", improve_gray, match_names[m]);
  if (p)
    decode_le(t, p);
  free(d);
  return p ? 0 : -1;
}

int color_tables_extract(const char *brother_filter, const char *dir) {
  size_t len;
  uint8_t *d = read_file(brother_filter, &len);
  if (!d) {
    fprintf(stderr, "cannot read %s: %s\n", brother_filter, strerror(errno));
    return -1;
  }
  int written = 0;
  static const char *const modes[2] = {"600dpi", "CAPT"};
  for (int mode = 0; mode < 2; mode++)
    for (int m = 0; m < 3; m++)
      for (int g = 0; g < 2; g++) {
        const uint8_t *p = find_table(d, len, modes[mode], g, match_names[m]);
        if (!p) {
          fprintf(stderr, "table %s ImpGray=%s %s not found\n", modes[mode], g ? "ON" : "OFF", match_names[m]);
          continue;
        }
        char name[64];
        snprintf(name, sizeof name, "table-%s-gray%s-%s.bin", mode ? "capt" : "600", g ? "on" : "off",
                 match_files[m]);
        if (fs_write_file(dir, name, p, COLOR_TABLE_BYTES)) {
          free(d);
          return -1;
        }
        written++;
      }
  free(d);
  return written == 12 ? 0 : -1;
}

void color_convert(const color_table *t, const uint8_t rgb[3], uint8_t out[4]) {
  int k[3], f[3];
  int between = 0;
  for (int i = 0; i < 3; i++) {
    if (rgb[i] == 255) {
      k[i] = 15;
      f[i] = 16;
    } else {
      k[i] = rgb[i] >> 4;
      f[i] = rgb[i] & 15;
    }
    between += f[i] != 0 && f[i] != 16;
  }
  /* axes by falling fraction (Kuhn split of the cell) */
  int o[3] = {0, 1, 2};
  if (f[o[0]] < f[o[1]]) { int x = o[0]; o[0] = o[1]; o[1] = x; }
  if (f[o[1]] < f[o[2]]) { int x = o[1]; o[1] = o[2]; o[2] = x; }
  if (f[o[0]] < f[o[1]]) { int x = o[0]; o[0] = o[1]; o[1] = x; }

  const int *w = weights[between];
  int node[3] = {k[0], k[1], k[2]};
  const uint16_t *n0 = t->v + ((node[0] * COLOR_GRID + node[1]) * COLOR_GRID + node[2]) * 4;
  long acc[4];
  for (int p = 0; p < 4; p++)
    acc[p] = (long)n0[p] * 4096;
  for (int j = 0; j < 3; j++) {
    int ax = o[j];
    if (f[ax] == 0)
      break; /* the rest are 0 too */
    node[ax]++;
    const uint16_t *n1 = t->v + ((node[0] * COLOR_GRID + node[1]) * COLOR_GRID + node[2]) * 4;
    for (int p = 0; p < 4; p++)
      acc[p] += (long)(n1[p] - n0[p]) * w[f[ax]];
    n0 = n1;
  }
  /* table order C, M, Y, K -> out K, C, M, Y */
  static const int to_out[4] = {1, 2, 3, 0};
  for (int p = 0; p < 4; p++) {
    long v = (acc[p] + 2048) >> 12;
    out[to_out[p]] = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
  }
}
