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

/* ---- line encoder --------------------------------------------------------- */

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

typedef struct {
  unsigned unit;     /* unit width in bits */
  unsigned rep_bits; /* bits of the repeat count */
  size_t copy_dist;  /* back-reference distance in units */
} enc_params;

/* Repeat: 1 + count bits + unit; method 2 uses a 3-bit count, method 4 makes
 * command plus unit exactly 16 bits. */
static void put_repeat(bitw *w, const enc_params *e, unsigned unit, size_t count) {
  size_t max = (1u << e->rep_bits) - 1;
  if (count <= max) {
    bw_put(w, 1, 1);
    bw_put(w, (unsigned)(count - 1), e->rep_bits);
    bw_put(w, unit, e->unit);
  } else {
    bw_put(w, 1, 1);
    bw_put(w, (unsigned)max, e->rep_bits);
    bw_put(w, unit, e->unit);
    bw_align(w);
    bw_ext(w, count - max - 1);
  }
  bw_align(w);
}

static void put_literal(bitw *w, const enc_params *e, const uint32_t *units, size_t n) {
  if (n == 1) {
    put_repeat(w, e, units[0], 1);
    return;
  }
  if (n - 2 < 63) {
    bw_put(w, 0x40u | (unsigned)(n - 2), 8);
  } else {
    bw_put(w, 0x7Fu, 8);
    bw_ext(w, n - 65);
  }
  for (size_t i = 0; i < n; i++)
    bw_put(w, units[i], e->unit);
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

static uint32_t *g_units;
static size_t g_units_cap;

void xl_encode_line(const uint8_t *row, size_t bpl, int method, int unit, xl_buf *out) {
  enc_params e = {(unsigned)unit, method == 2 ? 3u : (unsigned)(15 - unit), method == 2 ? 2u : 4u};
  size_t nbits = bpl * 8;
  size_t n = (nbits + e.unit - 1) / e.unit;
  if (n > g_units_cap) {
    free(g_units);
    g_units = malloc(n * sizeof *g_units);
    if (!g_units) {
      fputs("ERROR: out of memory\n", stderr);
      exit(1);
    }
    g_units_cap = n;
  }
  uint32_t *u = g_units;
  for (size_t k = 0; k < n; k++) {
    uint32_t v = 0;
    for (unsigned b = 0; b < e.unit; b++) {
      size_t pos = k * e.unit + b;
      unsigned bit = pos < nbits ? (row[pos >> 3] >> (7 - (pos & 7))) & 1u : 0u;
      v = (v << 1) | bit;
    }
    u[k] = v;
  }

  bitw w = {out, 0, 0};
  size_t i = 0;
  size_t lit_start = 0, lit_len = 0;
  /* Brother's priorities: method 2 takes a run of equal units before a
   * back-reference, method 4 the other way round. A back-reference may reach
   * before the line start, where units count as 0, but the first unit of a
   * line is never a back-reference. */
  int copy_first = method == 4;
  while (i < n) {
    size_t cp = 0;
    while (i > 0 && i + cp < n && u[i + cp] == (i + cp >= e.copy_dist ? u[i + cp - e.copy_dist] : 0))
      cp++;
    size_t run = 1;
    while (i + run < n && u[i + run] == u[i])
      run++;
    int take_copy = cp >= 2 && (copy_first || run < 2);
    if (take_copy || run >= 2) {
      if (lit_len)
        put_literal(&w, &e, u + lit_start, lit_len);
      lit_len = 0;
      if (take_copy) {
        put_copy(&w, cp);
        i += cp;
      } else {
        put_repeat(&w, &e, u[i], run);
        i += run;
      }
      continue;
    }
    if (!lit_len)
      lit_start = i;
    lit_len++;
    i++;
  }
  if (lit_len)
    put_literal(&w, &e, u + lit_start, lit_len);
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
  time_t when = job->when;
  if (!gmtime_r(&when, &tm)) { /* out-of-range SOURCE_DATE_EPOCH */
    when = time(NULL);
    if (!gmtime_r(&when, &tm))
      memset(&tm, 0, sizeof tm);
  }

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
  fprintf(out, "@PJL SET RENDERMODE=%s\n", job->render == XL_MONO ? "GRAYSCALE" : "COLOR");
  fprintf(out, "@PJL SET COLORADAPT=%s\n", job->render == XL_AUTO ? "ON" : "OFF");
  fprintf(out, "@PJL SET LESSPAPERCURL=%s\n", job->less_paper_curl ? "ON" : "OFF");
  fprintf(out, "@PJL SET FIXINTENSITYUP=%s\n", job->fix_intensity ? "ON" : "OFF");
  fprintf(out, "@PJL SET APTMODE=OFF\n");
  if (job->render != XL_MONO && job->improve_gray)
    fprintf(out, "@PJL SET IMPROVEGRAY=ON\n");
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
  pxl_u16le(f, w->job->render == XL_MONO ? 0 : 1);
  for (unsigned p = 0; p < PLANES; p++) {
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
  for (int p = 0; p < PLANES; p++) {
    w->plane[p].band.len = 0;
    w->plane[p].rows = 0;
    w->plane[p].prev_len = 0;
  }
  return ferror(f) ? -1 : 0;
}

static void put_u16be(xl_buf *b, unsigned v) {
  xl_buf_byte(b, (v >> 8) & 0xFF);
  xl_buf_byte(b, v & 0xFF);
}

static int flush_band(xl_writer *w, int p) {
  xl_plane_state *ps = &w->plane[p];
  if (!ps->rows)
    return 0;
  FILE *f = w->out;
  size_t total = 12 + ps->band.len + 4 + 1;
  uint8_t hdr[12] = {
      0x00, 0x04, (uint8_t)(plane_table[p] >> 8), (uint8_t)(plane_table[p] & 0xFF),
      (uint8_t)(w->bpl >> 8), (uint8_t)(w->bpl & 0xFF),
      (uint8_t)(ps->rows >> 8), (uint8_t)(ps->rows & 0xFF),
      (uint8_t)(total >> 24), (uint8_t)(total >> 16), (uint8_t)(total >> 8), (uint8_t)total,
  };
  uint8_t trailer[4] = {(uint8_t)(ps->prev_len >> 8), (uint8_t)(ps->prev_len & 0xFF), 0, 0};
  unsigned sum = 0;
  for (size_t i = 0; i < sizeof hdr; i++)
    sum += hdr[i];
  for (size_t i = 0; i < ps->band.len; i++)
    sum += ps->band.data[i];
  for (size_t i = 0; i < sizeof trailer; i++)
    sum += trailer[i];
  uint8_t check = (uint8_t)(0x100 - (sum & 0xFF));

  pxl_uint16(f, ps->start, A_StartLine);
  pxl_uint16(f, ps->rows, A_BlockHeight);
  pxl_ubyte(f, 1, A_CompressMode);
  pxl_uint16(f, (unsigned)p, A_CommentData);
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
  fwrite(ps->band.data, 1, ps->band.len, f);
  fwrite(trailer, 1, sizeof trailer, f);
  fputc(check, f);

  ps->band.len = 0;
  ps->rows = 0;
  ps->prev_len = 0;
  return ferror(f) ? -1 : 0;
}

/* Brother handles the planes in the order of its colour tables: C, M, Y, K. */
static const int plane_order[PLANES] = {PLANE_C, PLANE_M, PLANE_Y, PLANE_K};

/* Brother writes a band as soon as it ends: at the plane's first blank row
 * or when it is full. */
int xl_page_row(xl_writer *w, unsigned y, const uint8_t *const rows[PLANES]) {
  for (int i = 0; i < PLANES; i++) {
    int p = plane_order[i];
    xl_plane_state *ps = &w->plane[p];
    const uint8_t *row = rows[p];
    int blank = 1;
    if (row)
      for (unsigned b = 0; b < w->bpl; b++)
        if (row[b]) {
          blank = 0;
          break;
        }
    if (ps->rows && (blank || y != ps->start + ps->rows))
      if (flush_band(w, p))
        return -1;
    if (blank)
      continue;
    if (ps->rows && 12 + ps->band.len >= BAND_LIMIT)
      if (flush_band(w, p))
        return -1;
    if (!ps->rows)
      ps->start = y;

    w->line.len = 0;
    xl_encode_line(row, w->bpl, plane_table[p] >> 8, plane_table[p] & 0xFF, &w->line);
    size_t len = w->line.len;
    put_u16be(&ps->band, ps->prev_len);
    put_u16be(&ps->band, (unsigned)len);
    xl_buf_put(&ps->band, w->line.data, len);
    while (len & 3) {
      xl_buf_byte(&ps->band, 0);
      len++;
    }
    ps->prev_len = (unsigned)w->line.len;
    ps->rows++;
  }
  return 0;
}

int xl_page_end(xl_writer *w) {
  for (int i = 0; i < PLANES; i++)
    if (flush_band(w, plane_order[i]))
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
  for (int p = 0; p < PLANES; p++)
    xl_buf_free(&w->plane[p].band);
  xl_buf_free(&w->line);
}
