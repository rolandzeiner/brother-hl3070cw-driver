/*
 * Mono halftoning with Brother's dither tiles ("BRCD" cache files).
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef HALFTONE_H
#define HALFTONE_H

#include <stddef.h>
#include <stdint.h>

/* Where Brother's driver package installs its halftone data. */
#define BROTHER_LUT_DIR "/Library/Printers/Brother/Brother LUT/"

typedef struct {
  unsigned w, h;     /* tile size in pixels */
  unsigned stride;   /* bytes per tile row */
  size_t tile;       /* bytes per tile */
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

#endif
