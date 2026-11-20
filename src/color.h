/*
 * RGB -> K, C, M, Y toner levels with Brother's colour tables.
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef COLOR_H
#define COLOR_H

#include <stdint.h>

#define COLOR_GRID 17
#define COLOR_NODES (COLOR_GRID * COLOR_GRID * COLOR_GRID)
#define COLOR_TABLE_BYTES (COLOR_NODES * 8)

/* 17 x 17 x 17 nodes in R, G, B order (R slowest), each C, M, Y, K. */
typedef struct {
  uint16_t v[COLOR_NODES * 4];
} color_table;

typedef enum { MATCH_NORMAL = 0, MATCH_VIVID = 1, MATCH_NONE = 2 } color_matching;

/* File name of a table inside the driver's data directory. */
const char *color_table_file(color_matching m, int improve_gray);

/* Load a raw table file (COLOR_TABLE_BYTES, little-endian u16). */
int color_table_load(color_table *t, const char *path);

/* Read a table straight out of Brother's filter binary by its name. */
int color_table_from_brother(color_table *t, const char *brother_filter, color_matching m, int improve_gray);

/* Write all twelve tables (600 dpi and CAPT) from Brother's filter binary into dir. */
int color_tables_extract(const char *brother_filter, const char *dir);

/* Toner levels 0..255 for one RGB colour: out[0..3] = K, C, M, Y. */
void color_convert(const color_table *t, const uint8_t rgb[3], uint8_t out[4]);

#endif
