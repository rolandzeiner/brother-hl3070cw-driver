/*
 * Mono halftoning that reproduces Brother's filter bit for bit:
 *
 *   grey  = 0.299 R + 0.587 G + 0.114 B, rounded     double precision,
 *           to the nearest integer, exact halves     measured on 528 ties
 *           down                                     in both modes
 *   level = tone_curve[255 - grey]
 *   dot   = tile[level][y mod h][x mod w]            tile anchored at the
 *                                                    image origin
 *
 * The tone curve was measured by black-box tests against Brother's filter
 * (tools/measure_mono.py), at 600 dpi and in Fine, where the finer tiles
 * settle entries the 600 dpi tiles leave open. Where two levels give the
 * same tiles in every cache, the lower one is listed.
 *
 * Fine uses the same grey and curve with the "capt-" tiles: one byte per
 * pixel holding a 4-bit value, anchored at the image origin like the others.
 *
 * Build with -ffp-contract=off: a fused multiply-add rounds differently and
 * changes the result for colours that land exactly on .5.
 *
 * SPDX-License-Identifier: MIT
 */

#include "halftone.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const uint8_t tone_curve[256] = {
    0,   1,   3,   4,   5,   6,   8,   9,   10,  12,  13,  14,  16,  17,  18,  19,
    21,  22,  23,  25,  26,  27,  29,  30,  31,  32,  33,  34,  35,  35,  36,  37,
    38,  39,  40,  41,  42,  43,  44,  44,  45,  46,  47,  48,  49,  49,  50,  51,
    52,  53,  53,  54,  55,  56,  57,  57,  58,  59,  60,  60,  61,  62,  63,  63,
    64,  65,  65,  66,  67,  67,  68,  69,  69,  70,  70,  71,  72,  72,  73,  73,
    74,  75,  75,  76,  76,  77,  77,  78,  78,  79,  79,  80,  80,  81,  81,  81,
    82,  82,  83,  83,  83,  84,  84,  84,  84,  85,  85,  85,  85,  86,  86,  86,
    86,  87,  87,  87,  88,  88,  89,  89,  90,  90,  91,  92,  92,  93,  93,  94,
    94,  95,  96,  96,  97,  97,  98,  99,  99,  100, 101, 102, 102, 103, 104, 104,
    105, 106, 107, 108, 108, 109, 110, 111, 112, 112, 113, 114, 115, 116, 117, 118,
    119, 120, 121, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 132, 133, 134,
    135, 136, 137, 138, 139, 140, 142, 143, 144, 145, 146, 147, 149, 150, 151, 152,
    154, 155, 156, 157, 159, 160, 161, 163, 164, 165, 167, 168, 170, 171, 172, 174,
    175, 177, 178, 180, 181, 183, 184, 186, 187, 189, 190, 192, 193, 195, 196, 198,
    200, 201, 203, 205, 206, 208, 210, 211, 213, 215, 216, 218, 220, 222, 223, 225,
    227, 229, 230, 232, 234, 236, 238, 240, 242, 243, 245, 247, 249, 251, 253, 255,
};

int brcd_load(brcd_cache *c, const char *path) {
  memset(c, 0, sizeof *c);
  FILE *f = fopen(path, "rb");
  if (!f) {
    fprintf(stderr, "ERROR: cannot open halftone file %s (is Brother's driver package installed?)\n", path);
    return -1;
  }
  uint8_t hdr[10];
  if (fread(hdr, 1, sizeof hdr, f) != sizeof hdr || memcmp(hdr, "BRCD", 4) != 0 || (hdr[4] != '0' && hdr[4] != '1')) {
    fprintf(stderr, "ERROR: %s is not a Brother dither cache file\n", path);
    fclose(f);
    return -1;
  }
  c->w = hdr[6] | (unsigned)hdr[7] << 8;
  c->h = hdr[8] | (unsigned)hdr[9] << 8;
  if (!c->w || !c->h || c->w > BRCD_MAX_SIDE || c->h > BRCD_MAX_SIDE) {
    fprintf(stderr, "ERROR: %s: bad tile size %ux%u\n", path, c->w, c->h);
    fclose(f);
    return -1;
  }
  c->fine = hdr[4] == '1';
  if (c->fine && c->w % 8) {
    fprintf(stderr, "ERROR: %s: bad tile width %u\n", path, c->w);
    fclose(f);
    return -1;
  }
  c->stride = (c->w + 7) / 8;
  c->tile = (size_t)c->stride * c->h;
  c->body = malloc(256 * c->tile);
  if (!c->body || fread(c->body, 1, 256 * c->tile, f) != 256 * c->tile) {
    fprintf(stderr, "ERROR: %s is truncated\n", path);
    free(c->body);
    c->body = NULL;
    fclose(f);
    return -1;
  }
  fclose(f);
  return 0;
}

void brcd_free(brcd_cache *c) {
  free(c->body);
  c->body = NULL;
}

static unsigned mono_level(const uint8_t *rgb) {
  if (rgb[0] == 255 && rgb[1] == 255 && rgb[2] == 255)
    return 0; /* white: no toner, the common case */
  double v = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
  long grey = (long)ceil(v - 0.5); /* nearest, exact halves down */
  if (grey < 0)
    grey = 0;
  if (grey > 255)
    grey = 255;
  return tone_curve[255 - grey];
}

void mono_row(const brcd_cache *c, const uint8_t *rgb, unsigned width, unsigned y, uint8_t *out,
              size_t out_bytes) {
  memset(out, 0, out_bytes);
  const uint8_t *tile_row = c->body + (size_t)(y % c->h) * c->stride;
  unsigned tx = 0;
  for (unsigned x = 0; x < width; x++, rgb += 3) {
    unsigned level = mono_level(rgb);
    if (level && (((unsigned)tile_row[level * c->tile + (tx >> 3)] >> (7 - (tx & 7))) & 1u))
      out[x >> 3] |= (uint8_t)(0x80u >> (x & 7));
    if (++tx == c->w)
      tx = 0;
  }
}

void color_row(const color_table *t, const brcd_cache caches[4], const uint8_t *rgb, unsigned width,
               unsigned y, uint8_t *const out[4], size_t out_bytes, int any[4]) {
  const uint8_t *rows[4];
  unsigned tx[4];
  for (int p = 0; p < 4; p++) {
    memset(out[p], 0, out_bytes);
    any[p] = 0;
    rows[p] = caches[p].body + (size_t)(y % caches[p].h) * caches[p].stride;
    tx[p] = 0;
  }
  uint8_t last_rgb[3] = {255, 255, 255};
  uint8_t lv[4] = {0, 0, 0, 0}; /* white: no toner */
  for (unsigned x = 0; x < width; x++, rgb += 3) {
    if (rgb[0] != last_rgb[0] || rgb[1] != last_rgb[1] || rgb[2] != last_rgb[2]) {
      if (rgb[0] == 255 && rgb[1] == 255 && rgb[2] == 255)
        memset(lv, 0, sizeof lv);
      else
        color_convert(t, rgb, lv);
      memcpy(last_rgb, rgb, 3);
    }
    for (int p = 0; p < 4; p++) {
      unsigned px = tx[p];
      if (lv[p] && (((unsigned)rows[p][lv[p] * caches[p].tile + (px >> 3)] >> (7 - (px & 7))) & 1u)) {
        out[p][x >> 3] |= (uint8_t)(0x80u >> (x & 7));
        any[p] = 1;
      }
      if (++tx[p] == caches[p].w)
        tx[p] = 0;
    }
  }
}

/* ---- Fine --------------------------------------------------------------------- */

/* In a Fine tile every byte is one pixel; its low nibble is the toner value. */
static inline unsigned fine_pixel(const brcd_cache *c, const uint8_t *tile_row, unsigned level, unsigned tx) {
  return tile_row[level * c->tile + tx] & 15u;
}

void mono_row_fine(const brcd_cache *c, const uint8_t *rgb, unsigned width, unsigned y, uint8_t *out,
                   size_t out_bytes) {
  memset(out, 0, out_bytes);
  const uint8_t *tile_row = c->body + (size_t)(y % c->h) * c->stride;
  unsigned tx = 0;
  for (unsigned x = 0; x < width; x++, rgb += 3) {
    unsigned level = mono_level(rgb);
    if (level)
      out[x >> 1] |= (uint8_t)(fine_pixel(c, tile_row, level, tx) << ((x & 1) ? 0 : 4));
    if (++tx == c->stride)
      tx = 0;
  }
}

void color_row_fine(const color_table *t, const brcd_cache caches[4], const uint8_t *rgb, unsigned width,
                    unsigned y, uint8_t *const out[4], size_t out_bytes, int any[4]) {
  const uint8_t *rows[4];
  unsigned tx[4];
  for (int p = 0; p < 4; p++) {
    memset(out[p], 0, out_bytes);
    any[p] = 0;
    rows[p] = caches[p].body + (size_t)(y % caches[p].h) * caches[p].stride;
    tx[p] = 0;
  }
  uint8_t last_rgb[3] = {255, 255, 255};
  uint8_t lv[4] = {0, 0, 0, 0};
  for (unsigned x = 0; x < width; x++, rgb += 3) {
    if (rgb[0] != last_rgb[0] || rgb[1] != last_rgb[1] || rgb[2] != last_rgb[2]) {
      if (rgb[0] == 255 && rgb[1] == 255 && rgb[2] == 255)
        memset(lv, 0, sizeof lv);
      else
        color_convert(t, rgb, lv);
      memcpy(last_rgb, rgb, 3);
    }
    for (int p = 0; p < 4; p++) {
      if (lv[p]) {
        unsigned v = fine_pixel(&caches[p], rows[p], lv[p], tx[p]);
        if (v) {
          out[p][x >> 1] |= (uint8_t)(v << ((x & 1) ? 0 : 4));
          any[p] = 1;
        }
      }
      if (++tx[p] == caches[p].stride)
        tx[p] = 0;
    }
  }
}
