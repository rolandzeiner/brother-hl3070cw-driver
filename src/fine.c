/*
 * Fine line encoder. A C port of tools/xl2hb_fine.py (encode_line); keep the
 * two in step. The format is described in docs/FORMAT.md, "Fine".
 *
 * Stage 1 cuts the line into one-byte tokens, each standing for whole bytes
 * of the line: a run of 00 or FF bytes, or an "edge" byte with partial
 * nibbles, which can take in a few run bytes in front of it.
 * Stage 2 writes the tokens, replacing repetitions with headers: a group of
 * one to three tokens repeated, or one or two tokens interleaved with fresh
 * ones.
 *
 * SPDX-License-Identifier: MIT
 */

#include "fine.h"

#include <stdlib.h>
#include <string.h>

/* ---- stage 1: tokens ---------------------------------------------------------- */

/* 3-bit code of a partial nibble value 2, 4, ..., 14, 15; -1 for anything else */
static int qcode(unsigned v) {
  if (v == 15)
    return 7;
  if (v >= 2 && v <= 14 && !(v & 1))
    return (int)(v / 2 - 1);
  return -1;
}

typedef struct {
  uint8_t *t;
  size_t n, cap;
} tokbuf;

static void tok_put(tokbuf *b, unsigned v) {
  if (b->n == b->cap) {
    size_t cap = b->cap ? b->cap * 2 : 4096;
    uint8_t *p = realloc(b->t, cap);
    if (!p) {
      fputs("ERROR: out of memory\n", stderr);
      exit(1);
    }
    b->t = p;
    b->cap = cap;
  }
  b->t[b->n++] = (uint8_t)v;
}

/* runs of 00 / FF bytes: 0001 c kkk = k+1 bytes, full tokens first */
static void put_runs(tokbuf *b, int ff, size_t n) {
  unsigned c = ff ? 8u : 0u;
  for (; n > 8; n -= 8)
    tok_put(b, 0x10u | c | 7u);
  if (n)
    tok_put(b, 0x10u | c | (unsigned)(n - 1));
}

/* an edge byte with no run in front of it */
static void put_edge(tokbuf *b, unsigned byte) {
  unsigned h = byte >> 4, l = byte & 15;
  if (h == 15 && !(l & 1))
    tok_put(b, 0xC0u | l / 2);
  else if (l == 0 && qcode(h) >= 0)
    tok_put(b, 0xA0u | (unsigned)qcode(h));
  else if (!(h & 1) && qcode(l) >= 0)
    tok_put(b, 0x40u | (h / 2) << 3 | (unsigned)qcode(l));
  else { /* odd partial value: Brother's tiles never make one; round it down */
    unsigned even = (h & 1 && h != 15 ? h - 1 : h) << 4 | (l & 1 && l != 15 ? l - 1 : l);
    if (even == 0)
      tok_put(b, 0x10u); /* one zero byte */
    else
      put_edge(b, even);
  }
}

static void tokenize(const uint8_t *line, size_t n, tokbuf *b) {
  size_t i = 0;
  b->n = 0;
  while (i < n) {
    unsigned v = line[i];
    if (v != 0 && v != 0xFF) {
      put_edge(b, v);
      i++;
      continue;
    }
    size_t j = i;
    while (j < n && line[j] == v)
      j++;
    size_t run = j - i;
    if (j == n) {
      put_runs(b, v == 0xFF, run);
      break;
    }
    unsigned e = line[j], h = e >> 4, l = e & 15;
    size_t a;
    if (v == 0) {
      if (e == 0xFF) { /* FF after zeros is an edge only after one or two zeros */
        if (run > 2) {
          put_runs(b, 0, run);
          i = j;
        } else {
          tok_put(b, 0x20u | (unsigned)(run - 1) << 3 | 7u);
          i = j + 1;
        }
        continue;
      }
      if (l == 0 && qcode(h) >= 0) { /* (V,0) takes up to three zeros */
        a = run < 3 ? run : 3;
        put_runs(b, 0, run - a);
        tok_put(b, 0xA0u | (unsigned)a << 3 | (unsigned)qcode(h));
      } else if (h == 0 && qcode(l) >= 0) { /* (0,V) up to two */
        a = run < 2 ? run : 2;
        put_runs(b, 0, run - a);
        tok_put(b, 0x30u | (unsigned)(a - 1) << 3 | (unsigned)qcode(l));
      } else if (l == 15 && qcode(h) >= 0) { /* (V,F) up to two */
        a = run < 2 ? run : 2;
        put_runs(b, 0, run - a);
        tok_put(b, 0x20u | (unsigned)(a - 1) << 3 | (unsigned)qcode(h));
      } else {
        put_runs(b, 0, run);
        i = j;
        continue;
      }
      i = j + 1;
      continue;
    }
    /* a run of FF */
    if (e == 0) { /* FF..FF 00 only when the whole run fits */
      if (run <= 4) {
        tok_put(b, 0x80u | (unsigned)(run - 1) << 3);
        i = j + 1;
      } else {
        put_runs(b, 1, run);
        i = j;
      }
      continue;
    }
    if (h == 15 && !(l & 1)) { /* (F,e) takes up to three */
      a = run < 3 ? run : 3;
      put_runs(b, 1, run - a);
      tok_put(b, 0xC0u | (unsigned)a << 3 | l / 2);
    } else if (l == 0 && !(h & 1)) { /* (e,0) up to four */
      a = run < 4 ? run : 4;
      put_runs(b, 1, run - a);
      tok_put(b, 0x80u | (unsigned)(a - 1) << 3 | h / 2);
    } else if (l == 15 && !(h & 1)) { /* (e,F) up to four */
      a = run < 4 ? run : 4;
      put_runs(b, 1, run - a);
      tok_put(b, 0xE0u | (unsigned)(a - 1) << 3 | h / 2);
    } else {
      put_runs(b, 1, run);
      i = j;
      continue;
    }
    i = j + 1;
  }
}

/* ---- stage 2: headers ----------------------------------------------------------- */

enum { R1, R2, R3, I11, I12, I21, KINDS };

static const struct {
  uint8_t header, fixed, fresh, offset;
} shape[KINDS] = {
    {0x03, 1, 0, 6}, {0x07, 2, 0, 5}, {0x0F, 3, 0, 3}, /* repeat 1, 2, 3 tokens */
    {0x09, 1, 1, 4}, {0x0B, 1, 2, 4}, {0x0D, 2, 1, 3}, /* 1 or 2 fixed + fresh tokens */
};

#define MAX_COUNT 1024 /* Brother never repeats more than this in one header */

static const int order_full[] = {R3, R2, I11, I21, I12};  /* covering >= 12 tokens */
static const int order_short[] = {R3, R2, I21, I11, I12}; /* shorter ones, taken at */
static const size_t min_short[KINDS] = {0, 5, 3, 4, 4, 3};  /* these counts; below */
static const size_t near_miss[KINDS] = {0, 2, 2, 3, 0, 2};  /* these, 0: never */

/* periods of a kind that fit at token i */
static size_t count(const uint8_t *t, size_t n, size_t i, int k) {
  size_t fixed = shape[k].fixed, p = fixed + shape[k].fresh, c = 0;
  if (k == R2 && i + 1 < n && t[i] == t[i + 1])
    return 0; /* two equal tokens are a run, never a pair */
  while (c < MAX_COUNT && i + (c + 1) * p <= n && memcmp(t + i + c * p, t + i, fixed) == 0)
    c++;
  return c;
}

static size_t covered(int k, size_t c) { return c * (shape[k].fixed + shape[k].fresh); }

static long savings(int k, size_t c) {
  size_t nn = c - shape[k].offset;
  size_t ext = nn < 255 ? 0 : 1 + (nn - 255) / 255;
  return (long)covered(k, c) - (long)(2 + ext + shape[k].fixed + c * shape[k].fresh);
}

typedef struct {
  int kind; /* -1: none */
  size_t c;
} cand;

static cand best_full(const uint8_t *t, size_t n, size_t i) {
  cand r = {-1, 0};
  if (i >= n)
    return r;
  for (size_t j = 0; j < sizeof order_full / sizeof order_full[0]; j++) {
    size_t c = count(t, n, i, order_full[j]);
    if (covered(order_full[j], c) >= 12) {
      r.kind = order_full[j];
      r.c = c;
      return r;
    }
  }
  return r;
}

static size_t emit(xl_buf *out, const uint8_t *t, size_t i, cand b) {
  size_t fixed = shape[b.kind].fixed, fresh = shape[b.kind].fresh, nn = b.c - shape[b.kind].offset;
  xl_buf_byte(out, shape[b.kind].header);
  if (nn < 255) {
    xl_buf_byte(out, (unsigned)nn);
  } else {
    xl_buf_byte(out, 255);
    for (nn -= 255; nn >= 255; nn -= 255)
      xl_buf_byte(out, 255);
    xl_buf_byte(out, (unsigned)nn);
  }
  xl_buf_put(out, t + i, fixed);
  if (fresh)
    for (size_t k = 0; k < b.c; k++)
      xl_buf_put(out, t + i + k * (fixed + fresh) + fixed, fresh);
  return i + covered(b.kind, b.c);
}

static void encode_tokens(const uint8_t *t, size_t n, xl_buf *out) {
  size_t i = 0;
  while (i < n) {
    size_t r = count(t, n, i, R1);
    if (r >= 12) { /* long runs always */
      cand b = {R1, r};
      i = emit(out, t, i, b);
      continue;
    }
    cand b = best_full(t, n, i);
    if (b.kind >= 0) { /* anything covering 12 tokens, looking two tokens further for I12 */
      if (b.kind == I12) {
        cand nb = best_full(t, n, i + 2);
        if (nb.kind >= 0 && savings(nb.kind, nb.c) >= savings(b.kind, b.c)) {
          xl_buf_put(out, t + i, 2);
          i += 2;
          b = nb;
        }
      }
      i = emit(out, t, i, b);
      continue;
    }
    if (r >= 6) { /* a run of 6 to 11 tokens: thirds or literals */
      cand c3 = {R3, count(t, n, i, R3)};
      if (c3.c >= min_short[R3]) {
        i = emit(out, t, i, c3);
        continue;
      }
    }
    /* the first kind that fits decides: a header, or its tokens as literals */
    size_t span = 0;
    int taken = 0;
    for (size_t j = 0; j < sizeof order_short / sizeof order_short[0]; j++) {
      int k = order_short[j];
      size_t c = count(t, n, i, k);
      if (r < 6 && c >= min_short[k]) {
        if (i + 2 < n && count(t, n, i + 2, R1) >= 3)
          break; /* a run two tokens on wins */
        cand h = {k, c};
        i = emit(out, t, i, h);
        taken = 1;
        break;
      }
      if (near_miss[k] && c >= near_miss[k]) {
        span = covered(k, c);
        break;
      }
    }
    if (taken)
      continue;
    if (!span)
      span = r >= 3 ? r : 1;
    if (span > n - i)
      span = n - i;
    xl_buf_put(out, t + i, span);
    i += span;
  }
}

static tokbuf g_tokens;

void xl_fine_encode_line(const uint8_t *line, size_t bpl, xl_buf *out) {
  tokenize(line, bpl, &g_tokens);
  encode_tokens(g_tokens.t, g_tokens.n, out);
}
