/*
 * Test helper for `make check`: encodes random Fine lines with the driver's
 * encoder and writes line and encoding as records, which tools/selftest.py
 * decodes again and compares with the Python reference encoder.
 *
 *   fine_lines COUNT ODD OUTFILE     ODD=1: also nibble values Brother's
 *                                    tiles never make (odd ones)
 *
 * Record: u32 line length, line, u32 encoded length, encoding (native endian).
 *
 * SPDX-License-Identifier: MIT
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "../src/fine.h"

static uint64_t state = 88172645463325252ULL;

static unsigned rnd(void) { /* xorshift64: the same lines on every run */
  state ^= state << 13;
  state ^= state >> 7;
  state ^= state << 17;
  return (unsigned)(state >> 11);
}

static uint8_t pixel_pair(int odd) {
  static const uint8_t v[] = {0, 2, 4, 6, 8, 10, 12, 14, 15};
  if (odd)
    return (uint8_t)rnd();
  return (uint8_t)(v[rnd() % 9] << 4 | v[rnd() % 9]);
}

int main(int argc, char **argv) {
  if (argc != 4) {
    fputs("Usage: fine_lines COUNT ODD OUTFILE\n", stderr);
    return 2;
  }
  long count = strtol(argv[1], NULL, 10);
  int odd = argv[2][0] == '1';
  FILE *f = fopen(argv[3], "wb");
  if (!f) {
    perror(argv[3]);
    return 2;
  }
  xl_buf out = {0};
  for (long it = 0; it < count; it++) {
    /* mostly short lines, every seventh up to a full Legal width and beyond */
    uint32_t bpl = 4 * (1 + rnd() % (it % 7 == 0 ? 2600 : 400));
    uint8_t *line = malloc(bpl);
    if (!line) {
      fclose(f);
      return 2;
    }
    uint32_t i = 0;
    while (i < bpl) { /* stretches of runs, noise and repeating patterns */
      unsigned kind = rnd() % 8, len = 1 + rnd() % (rnd() % 4 ? 12 : 3000), period = 1 + rnd() % 3;
      uint8_t pat[3] = {pixel_pair(odd), pixel_pair(odd), pixel_pair(odd)};
      for (unsigned k = 0; k < len && i < bpl; k++, i++) {
        switch (kind) {
        case 0: line[i] = 0x00; break;
        case 1: line[i] = 0xFF; break;
        case 2: line[i] = pixel_pair(odd); break;
        case 3: line[i] = rnd() & 1 ? 0x00 : 0xFF; break;
        case 4: line[i] = pat[k % period]; break;
        case 5: line[i] = k % 2 ? pixel_pair(odd) : pat[0]; break;
        case 6: line[i] = k % 3 == 2 ? pixel_pair(odd) : pat[k % 3]; break;
        default: line[i] = rnd() % 5 ? 0x00 : pixel_pair(odd); break;
        }
      }
    }
    out.len = 0;
    xl_fine_encode_line(line, bpl, &out);
    uint32_t enc = (uint32_t)out.len;
    if (fwrite(&bpl, 4, 1, f) != 1 || fwrite(line, 1, bpl, f) != bpl || fwrite(&enc, 4, 1, f) != 1 ||
        fwrite(out.data, 1, enc, f) != enc) {
      perror(argv[3]);
      free(line);
      fclose(f);
      return 2;
    }
    free(line);
  }
  xl_buf_free(&out);
  return fclose(f) ? 2 : 0;
}
