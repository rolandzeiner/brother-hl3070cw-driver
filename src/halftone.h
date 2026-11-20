/*
 * Halftoning with Brother's dither tiles ("BRCD" cache files).
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef HALFTONE_H
#define HALFTONE_H

#include <stddef.h>
#include <stdint.h>

#include "color.h"

/* Where Brother's driver package installs its halftone data. (The self-test
 * build points this somewhere empty, see the Makefile.) */
#ifndef BROTHER_LUT_DIR
#define BROTHER_LUT_DIR "/Library/Printers/Brother/Brother LUT/"
#endif

/* Brother's tiles are at most 160 x 80; anything far beyond is a wrong file. */
#define BRCD_MAX_SIDE 512

typedef struct {
  unsigned w, h;     /* tile size in pixels */
  unsigned stride;   /* bytes per tile row */
  size_t tile;       /* bytes per tile */
  int fine;          /* "BRCD1": one byte per pixel (4-bit value), else 1 bit */
  uint8_t *body;     /* 256 tiles, index = toner level */
} brcd_cache;

/* Load a BRCD file. Returns 0 on success, -1 with a message on stderr. */
int brcd_load(brcd_cache *c, const char *path);
void brcd_free(brcd_cache *c);

/* Convert one RGB row (8 bits per channel, chunky) to 1-bit K pixels for
 * row y, exactly as Brother's filter does in Mono mode. out must hold
 * out_bytes bytes; pixels beyond width are left 0. */
void mono_row(const brcd_cache *c, const uint8_t *rgb, unsigned width, unsigned y, uint8_t *out,
              size_t out_bytes);

/* Convert one RGB row to 1-bit K, C, M, Y rows (out[p], out_bytes each) with
 * Brother's colour table and each plane's dither tiles. any[p] is set when
 * plane p has at least one dot. */
void color_row(const color_table *t, const brcd_cache caches[4], const uint8_t *rgb, unsigned width,
               unsigned y, uint8_t *const out[4], size_t out_bytes, int any[4]);

/* Fine (4 bits per pixel, two pixels per byte, first in the high nibble):
 * the same as mono_row and color_row with the Fine tiles ("capt-" files). */
void mono_row_fine(const brcd_cache *c, const uint8_t *rgb, unsigned width, unsigned y, uint8_t *out,
                   size_t out_bytes);
void color_row_fine(const color_table *t, const brcd_cache caches[4], const uint8_t *rgb, unsigned width,
                    unsigned y, uint8_t *const out[4], size_t out_bytes, int any[4]);

#endif
