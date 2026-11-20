/*
 * Writer for Brother's XL2HB job format. See docs/FORMAT.md for the format
 * and how it was worked out.
 *
 * SPDX-License-Identifier: MIT
 */

#include "xl2hb.h"

#include <stdlib.h>
#include <string.h>

/* ---- buffer --------------------------------------------------------------- */

static void buf_reserve(xl_buf *b, size_t extra) {
  if (b->len + extra <= b->cap)
    return;
  size_t cap = b->cap ? b->cap : 4096;
  while (cap < b->len + extra)
    cap *= 2;
  uint8_t *p = realloc(b->data, cap);
  if (!p) {
    fputs("ERROR: out of memory\n", stderr);
    exit(1);
  }
  b->data = p;
  b->cap = cap;
}

void xl_buf_put(xl_buf *b, const void *p, size_t n) {
  buf_reserve(b, n);
  memcpy(b->data + b->len, p, n);
  b->len += n;
}

void xl_buf_byte(xl_buf *b, unsigned v) {
  buf_reserve(b, 1);
  b->data[b->len++] = (uint8_t)v;
}

void xl_buf_free(xl_buf *b) {
  free(b->data);
  b->data = NULL;
  b->len = b->cap = 0;
}

/* ---- line encoder (method 2, 12-pixel units) ------------------------------ */

#define UNIT_BITS 12
#define COPY_DIST 2
#define BAND_LIMIT 27000 /* a new band starts once a band holds this many bytes */

typedef struct {
  xl_buf *out;
  unsigned acc;
  unsigned nbits;
} bitw;

static void bw_put(bitw *w, unsigned value, unsigned bits) {
  while (bits--) {
    w->acc = (w->acc << 1) | ((value >> bits) & 1u);
    if (++w->nbits == 8) {
      xl_buf_byte(w->out, w->acc & 0xFFu);
      w->acc = 0;
      w->nbits = 0;
    }
  }
}

static void bw_align(bitw *w) {
  if (w->nbits)
    bw_put(w, 0, 8 - w->nbits);
}

/* Extension count: 0xFF bytes add 255 each, the last byte is below 0xFF. */
static void bw_ext(bitw *w, size_t value) {
  while (value >= 255) {
    bw_put(w, 255, 8);
    value -= 255;
  }
  bw_put(w, (unsigned)value, 8);
}

static void put_repeat(bitw *w, unsigned unit, size_t count) {
  if (count <= 7) {
    bw_put(w, 0x8u | (unsigned)(count - 1), 4);
    bw_put(w, unit, UNIT_BITS);
  } else {
    bw_put(w, 0xFu, 4);
    bw_put(w, unit, UNIT_BITS);
    bw_align(w);
    bw_ext(w, count - 8);
  }
}

static void put_literal(bitw *w, const uint16_t *units, size_t n) {
  if (n == 1) {
    put_repeat(w, units[0], 1);
    return;
  }
  if (n - 2 < 63) {
    bw_put(w, 0x40u | (unsigned)(n - 2), 8);
  } else {
    bw_put(w, 0x7Fu, 8);
    bw_ext(w, n - 65);
  }
  for (size_t i = 0; i < n; i++)
    bw_put(w, units[i], UNIT_BITS);
  bw_align(w);
}

static void put_copy(bitw *w, size_t count) {
  if (count - 1 < 63) {
    bw_put(w, (unsigned)(count - 1), 8);
  } else {
    bw_put(w, 0x3Fu, 8);
    bw_ext(w, count - 64);
  }
}

static uint16_t *g_units;
static size_t g_units_cap;

void xl_encode_line(const uint8_t *row, size_t bpl, xl_buf *out) {
  size_t nbits = bpl * 8;
  size_t n = (nbits + UNIT_BITS - 1) / UNIT_BITS;
  if (n > g_units_cap) {
    free(g_units);
    g_units = malloc(n * sizeof *g_units);
    if (!g_units) {
      fputs("ERROR: out of memory\n", stderr);
      exit(1);
    }
    g_units_cap = n;
  }
  uint16_t *u = g_units;
  for (size_t k = 0; k < n; k++) {
    unsigned v = 0;
    for (unsigned i = 0; i < UNIT_BITS; i++) {
      size_t pos = k * UNIT_BITS + i;
      unsigned bit = pos < nbits ? (row[pos >> 3] >> (7 - (pos & 7))) & 1u : 0u;
      v = (v << 1) | bit;
    }
    u[k] = (uint16_t)v;
  }

  bitw w = {out, 0, 0};
  size_t i = 0;
  size_t lit_start = 0, lit_len = 0;
  while (i < n) {
    size_t run = 1;
    while (i + run < n && u[i + run] == u[i])
      run++;
    if (run >= 2) {
      if (lit_len)
        put_literal(&w, u + lit_start, lit_len);
      lit_len = 0;
      put_repeat(&w, u[i], run);
      i += run;
      continue;
    }
    size_t cp = 0;
    while (i + cp < n && i + cp >= COPY_DIST && u[i + cp] == u[i + cp - COPY_DIST])
      cp++;
    if (cp >= 2) {
      if (lit_len)
        put_literal(&w, u + lit_start, lit_len);
      lit_len = 0;
      put_copy(&w, cp);
      i += cp;
      continue;
    }
    if (!lit_len)
      lit_start = i;
    lit_len++;
    i++;
  }
  if (lit_len)
    put_literal(&w, u + lit_start, lit_len);
}

/* ---- PCL XL primitives (little-endian binding) ---------------------------- */

static void pxl_ubyte(FILE *f, unsigned v, unsigned attr) {
  fputc(0xC0, f);
  fputc((int)v, f);
  fputc(0xF8, f);
  fputc((int)attr, f);
}

static void pxl_u16le(FILE *f, unsigned v) {
  fputc((int)(v & 0xFF), f);
  fputc((int)((v >> 8) & 0xFF), f);
}

static void pxl_uint16(FILE *f, unsigned v, unsigned attr) {
  fputc(0xC1, f);
  pxl_u16le(f, v);
  fputc(0xF8, f);
  fputc((int)attr, f);
}

static void pxl_string(FILE *f, const char *s, unsigned attr) {
  size_t n = strlen(s);
  fputc(0xC8, f);
  fputc(0xC0, f);
  fputc((int)n, f);
  fwrite(s, 1, n, f);
  fputc(0xF8, f);
  fputc((int)attr, f);
}

enum {
  A_Orientation = 0x28, A_MediaSource = 0x26, A_MediaSize = 0x25, A_MediaType = 0x27,
  A_CustomMediaSize = 0x2F, A_CustomMediaSizeUnits = 0x30, A_SimplexPageMode = 0x34,
  A_PageOrigin = 0x2A, A_ColorMapping = 0x64, A_ColorDepth = 0x62, A_SourceWidth = 0x6C,
  A_SourceHeight = 0x6B, A_DestinationSize = 0x67, A_CommentData = 0x81, A_PageCopies = 0x31,
  A_StartLine = 0x6D, A_BlockHeight = 0x63, A_CompressMode = 0x65,
};
enum {
  OP_BeginSession = 0x41, OP_EndSession = 0x42, OP_BeginPage = 0x43, OP_EndPage = 0x44,
  OP_OpenDataSource = 0x48, OP_CloseDataSource = 0x49, OP_SetPageOrigin = 0x75,
  OP_BeginImage = 0xB0, OP_ReadImage = 0xB1, OP_EndImage = 0xB2,
};

/* Per-plane compression table sent with BeginImage: plane, 4, method << 8 | unit.
 * Planes 0..3 are K, C, M, Y; Brother's halftone cells are 12, 20, 10 and 12
 * pixels wide and the compression unit follows the cell width. */
static const unsigned plane_table[4] = {0x020C, 0x0214, 0x040A, 0x020C};

/* ---- job ------------------------------------------------------------------ */

int xl_job_begin(xl_writer *w, FILE *out, const xl_job *job) {
  memset(w, 0, sizeof *w);
  w->out = out;
  w->job = job;

  static const char *days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
  static const char *months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  struct tm tm;
  gmtime_r(&job->when, &tm);

  fprintf(out, "\033%%-12345X@PJL \n");
  fprintf(out, "@PJL SET HOLD=OFF\n");
  fprintf(out, "@PJL SET JOBNAME=\"%s\"\n", job->title);
  fprintf(out, "@PJL SET USERNAME=\"%s\"\n", job->user);
  fprintf(out, "@PJL JOB NAME=\"%s\"\n", job->title);
  fprintf(out, "@PJL PRINTLOG ITEM = 1,PRINTER\n");
  /* Brother pads none of the numbers: "Thu,1 Jan 2026 1:5:5" */
  fprintf(out, "@PJL PRINTLOG ITEM = 2,%s,%d %s %d %d:%d:%d\n", days[tm.tm_wday], tm.tm_mday,
          months[tm.tm_mon], tm.tm_year + 1900, tm.tm_hour, tm.tm_min, tm.tm_sec);
  fprintf(out, "@PJL PRINTLOG ITEM = 3,%s\n", job->user);
  fprintf(out, "@PJL PRINTLOG ITEM = 4,Macintosh\n");
  fprintf(out, "@PJL SET STRINGCODESET=HPROMAN8\n");
  fprintf(out, "@PJL SET LOGINUSER=\"%s\"\n", job->user);
  fprintf(out, "@PJL SET ECONOMODE=OFF\n");
  fprintf(out, "@PJL SET RENDERMODE=GRAYSCALE\n");
  fprintf(out, "@PJL SET COLORADAPT=OFF\n");
  fprintf(out, "@PJL SET LESSPAPERCURL=%s\n", job->less_paper_curl ? "ON" : "OFF");
  fprintf(out, "@PJL SET FIXINTENSITYUP=%s\n", job->fix_intensity ? "ON" : "OFF");
  fprintf(out, "@PJL SET APTMODE=OFF\n");
  fprintf(out, "@PJL SET RESOLUTION=600\n");
  fprintf(out, "@PJL ENTER LANGUAGE=XL2HB\n");
  fprintf(out, ") BROTHER XL2HB;1;0\n");

  /* BeginSession: Measure=eInch, UnitsPerMeasure=600x600 */
  pxl_ubyte(out, 0, 0x86);
  fputc(0xD1, out);
  pxl_u16le(out, 600);
  pxl_u16le(out, 600);
  fputc(0xF8, out);
  fputc(0x89, out);
  fputc(OP_BeginSession, out);
  /* OpenDataSource: SourceType=eDefaultDataSource, DataOrg=eBinaryLowByteFirst */
  pxl_ubyte(out, 0, 0x88);
  pxl_ubyte(out, 1, 0x82);
  fputc(OP_OpenDataSource, out);
  return ferror(out) ? -1 : 0;
}

int xl_page_begin(xl_writer *w, const xl_page *page) {
  FILE *f = w->out;
  pxl_ubyte(f, 0, A_Orientation);
  if (page->manual_feed)
    pxl_ubyte(f, 2, A_MediaSource);
  else
    pxl_uint16(f, 1001, A_MediaSource);
  switch (page->size.kind) {
  case XL_SIZE_ENUM:
    pxl_ubyte(f, page->size.enum_value, A_MediaSize);
    break;
  case XL_SIZE_NAME:
    pxl_string(f, page->size.name, A_MediaSize);
    break;
  case XL_SIZE_CUSTOM:
    fputc(0xD1, f);
    pxl_u16le(f, page->size.custom_w);
    pxl_u16le(f, page->size.custom_h);
    fputc(0xF8, f);
    fputc(A_CustomMediaSize, f);
    pxl_ubyte(f, 2, A_CustomMediaSizeUnits);
    break;
  }
  pxl_string(f, page->media_type, A_MediaType);
  pxl_ubyte(f, 0, A_SimplexPageMode);
  fputc(OP_BeginPage, f);

  /* SetPageOrigin 100,100: the 12 pt margin at 600 dpi */
  static const uint8_t origin[] = {0xD3, 0x64, 0x00, 0x64, 0x00, 0xF8, A_PageOrigin, OP_SetPageOrigin};
  fwrite(origin, 1, sizeof origin, f);

  pxl_ubyte(f, 0, A_ColorMapping);
  pxl_ubyte(f, 0, A_ColorDepth);
  pxl_uint16(f, page->width, A_SourceWidth);
  pxl_uint16(f, page->height, A_SourceHeight);
  fputc(0xD1, f);
  pxl_u16le(f, page->width);
  pxl_u16le(f, page->height);
  fputc(0xF8, f);
  fputc(A_DestinationSize, f);
  /* CommentData: 0, 3, colour flag, then per plane 1, 5, plane, 4, method/unit */
  fputc(0xC9, f);
  fputc(0xC1, f);
  pxl_u16le(f, 23);
  pxl_u16le(f, 0);
  pxl_u16le(f, 3);
  pxl_u16le(f, 0); /* 0 = mono job */
  for (unsigned p = 0; p < 4; p++) {
    pxl_u16le(f, 1);
    pxl_u16le(f, 5);
    pxl_u16le(f, p);
    pxl_u16le(f, 4);
    pxl_u16le(f, plane_table[p]);
  }
  fputc(0xF8, f);
  fputc(A_CommentData, f);
  pxl_uint16(f, 1, A_PageCopies);
  fputc(OP_BeginImage, f);

  w->bpl = page->width / 8;
  w->band.len = 0;
  w->band_rows = 0;
  w->prev_len = 0;
  return ferror(f) ? -1 : 0;
}

static void put_u16be(xl_buf *b, unsigned v) {
  xl_buf_byte(b, (v >> 8) & 0xFF);
  xl_buf_byte(b, v & 0xFF);
}

static int flush_band(xl_writer *w) {
  if (!w->band_rows)
    return 0;
  FILE *f = w->out;
  size_t total = 12 + w->band.len + 4 + 1;
  uint8_t hdr[12] = {
      0x00, 0x04, (uint8_t)(plane_table[0] >> 8), (uint8_t)(plane_table[0] & 0xFF),
      (uint8_t)(w->bpl >> 8), (uint8_t)(w->bpl & 0xFF),
      (uint8_t)(w->band_rows >> 8), (uint8_t)(w->band_rows & 0xFF),
      (uint8_t)(total >> 24), (uint8_t)(total >> 16), (uint8_t)(total >> 8), (uint8_t)total,
  };
  uint8_t trailer[4] = {(uint8_t)(w->prev_len >> 8), (uint8_t)(w->prev_len & 0xFF), 0, 0};
  unsigned sum = 0;
  for (size_t i = 0; i < sizeof hdr; i++)
    sum += hdr[i];
  for (size_t i = 0; i < w->band.len; i++)
    sum += w->band.data[i];
  for (size_t i = 0; i < sizeof trailer; i++)
    sum += trailer[i];
  uint8_t check = (uint8_t)(0x100 - (sum & 0xFF));

  pxl_uint16(f, w->band_start, A_StartLine);
  pxl_uint16(f, w->band_rows, A_BlockHeight);
  pxl_ubyte(f, 1, A_CompressMode);
  pxl_uint16(f, 0, A_CommentData); /* plane 0 = K */
  fputc(OP_ReadImage, f);
  if (total < 256) {
    fputc(0xFB, f);
    fputc((int)total, f);
  } else {
    fputc(0xFA, f);
    pxl_u16le(f, total & 0xFFFF);
    pxl_u16le(f, (total >> 16) & 0xFFFF);
  }
  fwrite(hdr, 1, sizeof hdr, f);
  fwrite(w->band.data, 1, w->band.len, f);
  fwrite(trailer, 1, sizeof trailer, f);
  fputc(check, f);

  w->band.len = 0;
  w->band_rows = 0;
  w->prev_len = 0;
  return ferror(f) ? -1 : 0;
}

int xl_page_row(xl_writer *w, unsigned y, const uint8_t *row) {
  int blank = 1;
  for (unsigned i = 0; i < w->bpl; i++) {
    if (row[i]) {
      blank = 0;
      break;
    }
  }
  /* A band is a run of consecutive non-blank rows. */
  if (w->band_rows && (blank || y != w->band_start + w->band_rows))
    if (flush_band(w))
      return -1;
  if (blank)
    return 0;
  if (w->band_rows && 12 + w->band.len >= BAND_LIMIT)
    if (flush_band(w))
      return -1;
  if (!w->band_rows)
    w->band_start = y;

  w->line.len = 0;
  xl_encode_line(row, w->bpl, &w->line);
  size_t len = w->line.len;
  put_u16be(&w->band, w->prev_len);
  put_u16be(&w->band, (unsigned)len);
  xl_buf_put(&w->band, w->line.data, len);
  while (len & 3) {
    xl_buf_byte(&w->band, 0);
    len++;
  }
  w->prev_len = (unsigned)w->line.len;
  w->band_rows++;
  return 0;
}

int xl_page_end(xl_writer *w) {
  if (flush_band(w))
    return -1;
  FILE *f = w->out;
  fputc(OP_EndImage, f);
  pxl_uint16(f, 1, A_PageCopies);
  fputc(OP_EndPage, f);
  return ferror(f) ? -1 : 0;
}

int xl_job_end(xl_writer *w) {
  FILE *f = w->out;
  fputc(OP_CloseDataSource, f);
  fputc(OP_EndSession, f);
  fprintf(f, "\033%%-12345X@PJL EOJ NAME=\"%s\"\n\033%%-12345X", w->job->title);
  fflush(f);
  return ferror(f) ? -1 : 0;
}

void xl_writer_free(xl_writer *w) {
  xl_buf_free(&w->band);
  xl_buf_free(&w->line);
}
