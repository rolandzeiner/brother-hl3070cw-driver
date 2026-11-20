/*
 * Writer for Brother's XL2HB job format (PJL + a PCL XL subset with
 * compressed bands of 1-bit pixels, or 4-bit pixels in Fine). See
 * docs/FORMAT.md.
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef XL2HB_H
#define XL2HB_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

/* Growable byte buffer. */
typedef struct {
  uint8_t *data;
  size_t len;
  size_t cap;
} xl_buf;

void xl_buf_free(xl_buf *b);
void xl_buf_put(xl_buf *b, const void *p, size_t n);
void xl_buf_byte(xl_buf *b, unsigned v);

/* Planes in the order Brother numbers them. */
enum { PLANE_K = 0, PLANE_C = 1, PLANE_M = 2, PLANE_Y = 3, PLANES = 4 };

/* Encode one line of 1-bit pixels (MSB first, bpl bytes) with the given
 * compression method (2 or 4) and unit width in pixels, appending to out.
 * Matches Brother's encoder. */
void xl_encode_line(const uint8_t *row, size_t bpl, int method, int unit, xl_buf *out);

/* Media description for BeginPage. */
typedef enum { XL_SIZE_ENUM, XL_SIZE_NAME, XL_SIZE_CUSTOM } xl_size_kind;

typedef struct {
  xl_size_kind kind;
  unsigned enum_value;   /* XL_SIZE_ENUM: PCL XL media size code */
  const char *name;      /* XL_SIZE_NAME: media size as a string */
  unsigned custom_w;     /* XL_SIZE_CUSTOM: width in 0.1 mm */
  unsigned custom_h;     /* XL_SIZE_CUSTOM: height in 0.1 mm */
} xl_media_size;

typedef enum { XL_MONO = 0, XL_COLOR = 1, XL_AUTO = 2 } xl_render;

typedef struct {
  const char *title;     /* job name, already cleaned */
  const char *user;      /* user name, already cleaned */
  time_t when;           /* job time, written in UTC */
  xl_render render;      /* Mono, colour, or colour with printer-side auto detection */
  int improve_gray;      /* colour jobs: BRGray=ON */
  int less_paper_curl;   /* BRImproveOutput=BRLessPaperCurl */
  int fix_intensity;     /* BRImproveOutput=BRFixIntensity */
  int fine;              /* BRResolution=600x2400dpi: 4-bit pixels, Fine bands */
} xl_job;

typedef struct {
  xl_media_size size;
  int manual_feed;       /* 1: manual feed slot, 0: tray 1 */
  const char *media_type;/* Brother media type string, e.g. "dRegular" */
  unsigned width;        /* SourceWidth in pixels: a multiple of 32, of 8 in Fine */
  unsigned height;       /* SourceHeight in pixels */
} xl_page;

typedef struct {
  xl_buf band;           /* line records */
  unsigned start;
  unsigned rows;
  unsigned prev_len;
} xl_plane_state;

/* Streaming job writer. All output goes to the FILE given to xl_job_begin. */
typedef struct {
  FILE *out;
  const xl_job *job;
  unsigned bpl;
  xl_plane_state plane[PLANES];
  xl_buf line;           /* scratch for one encoded line */
} xl_writer;

int xl_job_begin(xl_writer *w, FILE *out, const xl_job *job);
int xl_page_begin(xl_writer *w, const xl_page *page);
/* Add row y of the current page: rows[p] holds bpl bytes of pixels for plane
 * p (1 bit, or 4 bits in Fine, first pixel in the high bits), or NULL when the
 * plane is blank in this row. Rows must come in order; every row of the page
 * should be passed. */
int xl_page_row(xl_writer *w, unsigned y, const uint8_t *const rows[PLANES]);
int xl_page_end(xl_writer *w);
int xl_job_end(xl_writer *w);
void xl_writer_free(xl_writer *w);

#endif
