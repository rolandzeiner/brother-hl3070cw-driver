/*
 * Line encoder for Brother's "Fine" (600x2400 dpi class) mode: 4 bits per
 * pixel, tokens plus repeat headers. See docs/FORMAT.md, "Fine".
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef FINE_H
#define FINE_H

#include <stddef.h>
#include <stdint.h>

#include "xl2hb.h"

/* Encode one line of 4-bit pixels (two per byte, first pixel in the high
 * nibble, bpl bytes) and append it to out. Pixel values must be 0, 15 or
 * even, as Brother's dither tiles produce them. The tokens match Brother's
 * encoder exactly; the choice of repeat headers follows a model of it that
 * matches most lines (tools/xl2hb_fine.py is the reference). */
void xl_fine_encode_line(const uint8_t *line, size_t bpl, xl_buf *out);

#endif
