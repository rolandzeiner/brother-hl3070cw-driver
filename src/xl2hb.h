/*
 * Writer for Brother's XL2HB job format (PJL + a PCL XL subset with
 * compressed 1-bit bands). See docs/FORMAT.md.
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

/* Encode one line of 1-bit pixels (MSB first, bpl bytes) with method 2 and
 * 12-pixel units, appending the result to out. Matches Brother's encoder. */
void xl_encode_line(const uint8_t *row, size_t bpl, xl_buf *out);

/* Media description for BeginPage. */
typedef enum { XL_SIZE_ENUM, XL_SIZE_NAME, XL_SIZE_CUSTOM } xl_size_kind;

typedef struct {
  xl_size_kind kind;
  unsigned enum_value;   /* XL_SIZE_ENUM: PCL XL media size code */
  const char *name;      /* XL_SIZE_NAME: media size as a string */
  unsigned custom_w;     /* XL_SIZE_CUSTOM: width in 0.1 mm */
  unsigned custom_h;     /* XL_SIZE_CUSTOM: height in 0.1 mm */
} xl_media_size;

typedef struct {
  const char *title;     /* job name, already cleaned */
  const char *user;      /* user name, already cleaned */
  time_t when;           /* job time, written in UTC */
  int toner_save;        /* reserved: Brother keeps ECONOMODE=OFF either way */
  int less_paper_curl;   /* BRImproveOutput=BRLessPaperCurl */
  int fix_intensity;     /* BRImproveOutput=BRFixIntensity */
} xl_job;

typedef struct {
  xl_media_size size;
  int manual_feed;       /* 1: manual feed slot, 0: tray 1 */
  const char *media_type;/* Brother media type string, e.g. "dRegular" */
  unsigned width;        /* SourceWidth in pixels, multiple of 32 */
  unsigned height;       /* SourceHeight in pixels */
} xl_page;

/* Streaming job writer. All output goes to the FILE given to xl_job_begin. */
typedef struct {
  FILE *out;
  const xl_job *job;
  /* current page */
  unsigned bpl;
  /* current band */
  xl_buf band;           /* line records */
  xl_buf line;           /* scratch for one encoded line */
  unsigned band_start;
  unsigned band_rows;
  unsigned prev_len;
} xl_writer;

int xl_job_begin(xl_writer *w, FILE *out, const xl_job *job);
int xl_page_begin(xl_writer *w, const xl_page *page);
/* Add row y of the current page (bpl bytes of 1-bit K pixels). Rows must
 * come in order; blank rows may be skipped or passed in. */
int xl_page_row(xl_writer *w, unsigned y, const uint8_t *row);
int xl_page_end(xl_writer *w);
int xl_job_end(xl_writer *w);
void xl_writer_free(xl_writer *w);

#endif
