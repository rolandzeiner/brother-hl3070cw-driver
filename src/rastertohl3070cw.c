/*
 * rastertohl3070cw: CUPS filter for the Brother HL-3070CW.
 *
 *   rastertohl3070cw job-id user title copies options [file]
 *   rastertohl3070cw --extract-brother-data DIR
 *   rastertohl3070cw --version
 *
 * Reads CUPS raster (RGB or grey, 8 bits per channel, 600 dpi) and writes
 * Brother's XL2HB printer language. Mono output is byte-identical to Brother's
 * own filter; colour uses Brother's colour tables and dither tiles with an
 * interpolation fitted to Brother's output (see docs/FORMAT.md).
 *
 * The halftone tiles, colour tables and ICC profiles are Brother's data. They
 * are read from the driver's data folder (filled from Brother's installed
 * driver by --extract-brother-data) or straight from Brother's installation.
 *
 * Options are taken from the job's options (argv[5]) first and otherwise
 * from the page header, where this driver's PPD puts them:
 *   cupsInteger1  TonerSaveMode    0 OFF, 1 ON
 *   cupsInteger2  BRImproveOutput  0 OFF, 1 BRLessPaperCurl, 2 BRFixIntensity
 *   cupsInteger3  BRMonoColor      0 Auto, 1 FullColor, 2 Mono
 *   cupsInteger4  BRResolution     0 600dpi, 1 600x2400dpi (not supported yet: 600)
 *   cupsInteger5  BRColorMatching  0 Normal, 1 Vivid, 2 None
 *   cupsInteger6  BRGray           0 or 1 ON, 2 OFF
 *
 * SPDX-License-Identifier: MIT
 */

#include <cups/cups.h>
#include <cups/raster.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include "color.h"
#include "fsutil.h"
#include "halftone.h"
#include "xl2hb.h"

#ifndef DRIVER_VERSION
#define DRIVER_VERSION "0.2.0-dev"
#endif

/* Where this driver keeps its copy of Brother's data, and where Brother's
 * own driver package puts the originals. */
#define DRIVER_DATA_DIR "/Library/Printers/HL3070CW-Native/data"
#define BROTHER_FILTER "/Library/Printers/Brother/Filter/rastertobrother3040.bundle/Contents/MacOS/rastertobrother3040"
#define BROTHER_PROFILES_DIR "/Library/Printers/Brother/Profiles"

static volatile sig_atomic_t g_cancelled;

static void on_term(int sig) {
  (void)sig;
  g_cancelled = 1;
}

/* ---- media tables ----------------------------------------------------------- */

typedef struct {
  unsigned w, h;  /* points */
  xl_media_size size;
} size_entry;

/* PCL XL media codes and the names/custom sizes Brother's filter sends. */
static const size_entry sizes[] = {
    {612, 792, {XL_SIZE_ENUM, 0, NULL, 0, 0}},     /* Letter */
    {612, 1008, {XL_SIZE_ENUM, 1, NULL, 0, 0}},    /* Legal */
    {595, 842, {XL_SIZE_ENUM, 2, NULL, 0, 0}},     /* A4 */
    {522, 756, {XL_SIZE_ENUM, 3, NULL, 0, 0}},     /* Executive */
    {297, 684, {XL_SIZE_ENUM, 6, NULL, 0, 0}},     /* Com-10 */
    {279, 540, {XL_SIZE_ENUM, 7, NULL, 0, 0}},     /* Monarch */
    {459, 649, {XL_SIZE_ENUM, 8, NULL, 0, 0}},     /* C5 */
    {312, 624, {XL_SIZE_ENUM, 9, NULL, 0, 0}},     /* DL */
    {516, 729, {XL_SIZE_ENUM, 11, NULL, 0, 0}},    /* JIS B5 */
    {499, 709, {XL_SIZE_ENUM, 12, NULL, 0, 0}},    /* B5 (ISO) */
    {284, 419, {XL_SIZE_ENUM, 14, NULL, 0, 0}},    /* Hagaki */
    {420, 595, {XL_SIZE_ENUM, 16, NULL, 0, 0}},    /* A5 */
    {297, 420, {XL_SIZE_ENUM, 17, NULL, 0, 0}},    /* A6 */
    {216, 360, {XL_SIZE_NAME, 0, "3x5", 0, 0}},
    {595, 1148, {XL_SIZE_NAME, 0, "A4Long", 0, 0}},
    {612, 936, {XL_SIZE_NAME, 0, "Folio", 0, 0}},
    {624, 312, {XL_SIZE_NAME, 0, "DL Long Edge", 0, 0}},
    {298, 666, {XL_SIZE_NAME, 0, "Envelope #4", 0, 0}},
    {340, 666, {XL_SIZE_NAME, 0, "Envelope MAX", 0, 0}},
    {595, 420, {XL_SIZE_CUSTOM, 0, NULL, 2097, 1481}}, /* A5 long edge */
    {355, 499, {XL_SIZE_CUSTOM, 0, NULL, 1250, 1758}}, /* B6 (ISO) */
    {363, 516, {XL_SIZE_CUSTOM, 0, NULL, 1280, 1820}}, /* JIS B6 */
};

static unsigned absdiff(unsigned a, unsigned b) { return a > b ? a - b : b - a; }

static xl_media_size media_size_for(unsigned w, unsigned h) {
  for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; i++)
    if (absdiff(sizes[i].w, w) <= 1 && absdiff(sizes[i].h, h) <= 1)
      return sizes[i].size;
  xl_media_size s = {XL_SIZE_CUSTOM, 0, NULL, (unsigned)lround(w * 254.0 / 72.0),
                     (unsigned)lround(h * 254.0 / 72.0)};
  return s;
}

typedef struct {
  const char *ppd_name;
  unsigned code; /* cupsMediaType */
  const char *xl_name;
} media_type_entry;

static const media_type_entry media_types[] = {
    {"Plain", 0, "dRegular"},     {"Thin", 1, "dThin"},         {"Thick", 2, "dThick"},
    {"Thicker", 3, "dThick2"},    {"Recycled", 5, "dRecycled"}, {"BOND", 6, "dBond"},
    {"Env", 7, "dEnvelopes"},     {"EnvThin", 8, "dEnvthin"},   {"EnvThick", 9, "dEnvthick"},
    {"PostCard", 10, "dPostcard"}, {"Label", 11, "dLabel"},
};

static const char *media_type_for(const char *opt, unsigned code) {
  for (size_t i = 0; i < sizeof media_types / sizeof media_types[0]; i++)
    if (opt ? !strcasecmp(opt, media_types[i].ppd_name) : code == media_types[i].code)
      return media_types[i].xl_name;
  return "dRegular";
}

/* ---- options ---------------------------------------------------------------- */

typedef struct {
  int toner_save;
  int improve;    /* 0 off, 1 less paper curl, 2 fix intensity */
  int color_mode; /* 0 auto, 1 colour, 2 mono */
  int fine;
  int matching;   /* 0 normal, 1 vivid, 2 none */
  int improve_gray;
  const char *input_slot;
  const char *media_type;
} job_options;

static int opt_choice(const char *v, const char *const *names, int n, int fallback) {
  if (!v)
    return fallback;
  for (int i = 0; i < n; i++)
    if (!strcasecmp(v, names[i]))
      return i;
  return fallback;
}

static int header_int(const cups_page_header2_t *h, int i, int max) {
  return h->cupsInteger[i] <= (unsigned)max ? (int)h->cupsInteger[i] : 0;
}

static void resolve_options(job_options *o, int num, cups_option_t *opts, const cups_page_header2_t *h) {
  static const char *const onoff[] = {"OFF", "ON"};
  static const char *const improve[] = {"OFF", "BRLessPaperCurl", "BRFixIntensity"};
  static const char *const color[] = {"Auto", "FullColor", "Mono"};
  static const char *const res[] = {"600dpi", "600x2400dpi"};
  static const char *const match[] = {"Normal", "Vivid", "None"};
  o->toner_save = opt_choice(cupsGetOption("TonerSaveMode", num, opts), onoff, 2, h->cupsInteger[1] == 1);
  o->improve = opt_choice(cupsGetOption("BRImproveOutput", num, opts), improve, 3, header_int(h, 2, 2));
  o->color_mode = opt_choice(cupsGetOption("BRMonoColor", num, opts), color, 3, header_int(h, 3, 2));
  o->fine = opt_choice(cupsGetOption("BRResolution", num, opts), res, 2, h->cupsInteger[4] == 1);
  o->matching = opt_choice(cupsGetOption("BRColorMatching", num, opts), match, 3, header_int(h, 5, 2));
  o->improve_gray = opt_choice(cupsGetOption("BRGray", num, opts), onoff, 2, h->cupsInteger[6] != 2);
  o->input_slot = cupsGetOption("InputSlot", num, opts);
  o->media_type = cupsGetOption("MediaType", num, opts);
}

/* ---- Brother data ------------------------------------------------------------- */

static const char *data_dir(void) {
  const char *d = getenv("HL3070CW_DATA");
  return d && *d ? d : DRIVER_DATA_DIR;
}

/* snprintf into a buffer, failing instead of silently cutting the path */
static int path_join(char *buf, size_t cap, const char *dir, const char *sep, const char *name) {
  int n = snprintf(buf, cap, "%s%s%s", dir, sep, name);
  if (n < 0 || (size_t)n >= cap) {
    fprintf(stderr, "ERROR: path too long: %s%s%s\n", dir, sep, name);
    return -1;
  }
  return 0;
}

static int load_cache(brcd_cache *c, char plane, int toner_save) {
  char name[64], path[1024];
  snprintf(name, sizeof name, "0600-%c%s_cache08.bin", plane, toner_save ? "-TS" : "");
  if (path_join(path, sizeof path, data_dir(), "/", name))
    return -1;
  if (access(path, R_OK) != 0 && path_join(path, sizeof path, BROTHER_LUT_DIR, "", name))
    return -1;
  return brcd_load(c, path);
}

static int load_table(color_table *t, int matching, int improve_gray) {
  char path[1024];
  if (path_join(path, sizeof path, data_dir(), "/", color_table_file((color_matching)matching, improve_gray)))
    return -1;
  if (color_table_load(t, path) == 0)
    return 0;
  if (access(path, F_OK) == 0)
    fprintf(stderr, "WARNING: %s is damaged, reading the table from Brother's driver instead\n", path);
  if (color_table_from_brother(t, BROTHER_FILTER, (color_matching)matching, improve_gray) == 0)
    return 0;
  fprintf(stderr, "ERROR: Brother's colour tables not found (in %s or Brother's driver). "
                  "Install Brother's HL-3070CW driver, or use the PostScript version of this driver\n",
          data_dir());
  return -1;
}

/* Copy what the driver needs out of Brother's installed driver package.
 * Runs as root from the installer: see src/fsutil.c for the safeguards. */
static int extract_brother_data(const char *dir) {
  umask(022); /* the files must stay readable for CUPS (_lp) */
  char sub[1024], path[1024];
  if (fs_prepare_dir(dir) || path_join(sub, sizeof sub, dir, "/", "profiles") || fs_prepare_dir(sub))
    return 1;
  int failed = 0;
  static const char planes[] = "kcmy";
  for (int p = 0; p < 4; p++)
    for (int ts = 0; ts < 2; ts++) {
      char name[64];
      snprintf(name, sizeof name, "0600-%c%s_cache08.bin", planes[p], ts ? "-TS" : "");
      if (path_join(path, sizeof path, BROTHER_LUT_DIR, "", name) || fs_copy_file(path, dir, name))
        failed = 1;
    }
  if (color_tables_extract(BROTHER_FILTER, dir))
    failed = 1;
  /* ICC profiles for macOS's colour matching (named in the PPD) */
  static const char *const profiles[] = {"broch08_PL_NM.icm", "broch08_PL_NM_IG_ON.icm", "broch08_PL_Fi.icm",
                                         "broch08_PL_Fi_IG_ON.icm"};
  for (size_t i = 0; i < sizeof profiles / sizeof profiles[0]; i++)
    if (path_join(path, sizeof path, BROTHER_PROFILES_DIR, "/", profiles[i]) || fs_copy_file(path, sub, profiles[i]))
      failed = 1;
  if (!failed)
    printf("Brother's data copied to %s\n", dir);
  return failed;
}

/* PJL strings are quoted; keep them to 80 bytes of printable text. */
static void clean_text(char *dst, size_t cap, const char *src) {
  size_t n = 0;
  const unsigned char *p = (const unsigned char *)(src ? src : "");
  for (; *p && n + 1 < cap; p++)
    dst[n++] = (*p == '"') ? '\'' : (*p < 0x20 || *p == 0x7F) ? ' ' : (char)*p;
  if (*p && n > 0) {
    /* cut off: drop the last character only if it was split */
    size_t i = n - 1;
    while (i > 0 && ((unsigned char)dst[i] & 0xC0) == 0x80)
      i--;
    unsigned lead = (unsigned char)dst[i];
    size_t len = lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : lead >= 0xC0 ? 2 : 1;
    if (i + len > n)
      n = i;
  }
  dst[n] = 0;
}

/* ---- main ------------------------------------------------------------------- */

int main(int argc, char *argv[]) {
  if (argc == 2 && !strcmp(argv[1], "--version")) {
    printf("rastertohl3070cw %s\n", DRIVER_VERSION);
    return 0;
  }
  if (argc == 3 && !strcmp(argv[1], "--extract-brother-data"))
    return extract_brother_data(argv[2]);
  if (argc < 6 || argc > 7) {
    fputs("Usage: rastertohl3070cw job-id user title copies options [file]\n"
          "       rastertohl3070cw --extract-brother-data DIR\n",
          stderr);
    return 1;
  }
  int fd = 0;
  if (argc == 7 && (fd = open(argv[6], O_RDONLY)) < 0) {
    fprintf(stderr, "ERROR: cannot open %s: %s\n", argv[6], strerror(errno));
    return 1;
  }

  struct sigaction sa;
  memset(&sa, 0, sizeof sa);
  sa.sa_handler = on_term;
  sigaction(SIGTERM, &sa, NULL);
  signal(SIGPIPE, SIG_IGN);

  cups_option_t *opts = NULL;
  int num_opts = cupsParseOptions(argv[5], 0, &opts);

  char title[81], user[81];
  clean_text(title, sizeof title, argv[3]);
  clean_text(user, sizeof user, argv[2]);

  xl_job job;
  memset(&job, 0, sizeof job);
  job.title = title;
  job.user = user;
  const char *sde = getenv("SOURCE_DATE_EPOCH"); /* reproducible output for tests */
  job.when = sde ? (time_t)strtoll(sde, NULL, 10) : time(NULL);

  static char outbuf[1 << 16];
  setvbuf(stdout, outbuf, _IOFBF, sizeof outbuf);

  cups_raster_t *ras = cupsRasterOpen(fd, CUPS_RASTER_READ);
  cups_page_header2_t h;
  xl_writer w;
  brcd_cache cache[4];
  memset(cache, 0, sizeof cache);
  color_table *table = NULL;
  uint8_t *in = NULL, *conv = NULL, *bits[4] = {NULL, NULL, NULL, NULL};
  int page = 0, status = 0, started = 0, colour = 0;
  job_options o;

  while (!g_cancelled && cupsRasterReadHeader2(ras, &h)) {
    page++;

    /* The page header is untrusted input: check format and geometry before
     * anything is allocated or written. libcups does not tie the bytes per
     * line to the width. The PCL XL fields hold 16 bits, so a page is at most
     * 65504 pixels wide (65535 after rounding to 32) and 65536 rows high
     * (the last row past the imageable area is dropped). */
    unsigned bpp = h.cupsBitsPerPixel;
    int rgb = h.cupsBitsPerColor == 8 && bpp == 24 && h.cupsColorOrder == CUPS_ORDER_CHUNKED &&
              (h.cupsColorSpace == CUPS_CSPACE_RGB || h.cupsColorSpace == CUPS_CSPACE_SRGB ||
               h.cupsColorSpace == CUPS_CSPACE_ADOBERGB);
    int grey = h.cupsBitsPerColor == 8 && bpp == 8 &&
               (h.cupsColorSpace == CUPS_CSPACE_W || h.cupsColorSpace == CUPS_CSPACE_SW);
    if (!rgb && !grey) {
      fprintf(stderr, "ERROR: unsupported raster: colour space %u, %u bits per colour, %u bits per pixel\n",
              h.cupsColorSpace, h.cupsBitsPerColor, bpp);
      status = 1;
      break;
    }
    if (h.HWResolution[0] != 600 || h.HWResolution[1] != 600) {
      fprintf(stderr, "ERROR: unsupported resolution %ux%u, need 600x600\n", h.HWResolution[0], h.HWResolution[1]);
      status = 1;
      break;
    }
    if (h.cupsWidth == 0 || h.cupsWidth > 65504 || h.cupsHeight == 0 || h.cupsHeight > 65536 ||
        (uint64_t)h.cupsBytesPerLine != (uint64_t)h.cupsWidth * (bpp / 8)) {
      fprintf(stderr, "ERROR: bad raster geometry: %u x %u pixels, %u bytes per line\n", h.cupsWidth,
              h.cupsHeight, h.cupsBytesPerLine);
      status = 1;
      break;
    }

    if (!started) {
      resolve_options(&o, num_opts, opts, &h);
      if (o.fine)
        fputs("INFO: Fine (2400 dpi class) is not supported yet, printing at 600 dpi\n", stderr);
      colour = o.color_mode != 2;
      job.render = o.color_mode == 2 ? XL_MONO : o.color_mode == 1 ? XL_COLOR : XL_AUTO;
      job.improve_gray = o.improve_gray;
      job.less_paper_curl = o.improve == 1;
      job.fix_intensity = o.improve == 2;
      if (load_cache(&cache[0], 'k', o.toner_save)) {
        status = 1;
        break;
      }
      if (colour) {
        table = malloc(sizeof *table);
        if (!table || load_cache(&cache[1], 'c', o.toner_save) || load_cache(&cache[2], 'm', o.toner_save) ||
            load_cache(&cache[3], 'y', o.toner_save) || load_table(table, o.matching, o.improve_gray)) {
          status = 1;
          break;
        }
      }
      if (xl_job_begin(&w, stdout, &job)) {
        status = 1;
        break;
      }
      started = 1;
    }

    xl_page pg;
    memset(&pg, 0, sizeof pg);
    pg.size = media_size_for(h.PageSize[0], h.PageSize[1]);
    pg.manual_feed = o.input_slot ? !strcasecmp(o.input_slot, "Manual")
                                  : (h.ManualFeed || h.MediaPosition == 4);
    pg.media_type = media_type_for(o.media_type, h.cupsMediaType);
    pg.width = (h.cupsWidth + 31) & ~31u;
    unsigned height = h.cupsHeight;
    if (h.ImagingBoundingBox[3] > h.ImagingBoundingBox[1]) {
      unsigned bbox_h = (h.ImagingBoundingBox[3] - h.ImagingBoundingBox[1]) * h.HWResolution[1] / 72;
      if (bbox_h && bbox_h < height)
        height = bbox_h;
    }
    pg.height = height;
    if (pg.width > 65535 || pg.height > 65535) {
      fputs("ERROR: page too large\n", stderr);
      status = 1;
      break;
    }

    free(in);
    free(conv);
    conv = NULL;
    for (int p = 0; p < 4; p++) {
      free(bits[p]);
      bits[p] = malloc(pg.width / 8);
    }
    in = malloc(h.cupsBytesPerLine);
    if (grey)
      conv = malloc((size_t)h.cupsWidth * 3);
    if (!in || !bits[0] || !bits[1] || !bits[2] || !bits[3] || (grey && !conv)) {
      fputs("ERROR: out of memory\n", stderr);
      status = 1;
      break;
    }
    fprintf(stderr, "INFO: Printing page %d\n", page);
    if (xl_page_begin(&w, &pg)) {
      status = 1;
      break;
    }
    for (unsigned y = 0; y < h.cupsHeight; y++) {
      if (g_cancelled)
        break;
      if (cupsRasterReadPixels(ras, in, h.cupsBytesPerLine) < h.cupsBytesPerLine) {
        fprintf(stderr, "ERROR: raster data ends early on page %d\n", page);
        status = 1;
        break;
      }
      if (y >= height)
        continue;
      const uint8_t *rgbrow = in;
      if (grey) {
        for (unsigned x = 0; x < h.cupsWidth; x++)
          conv[3 * x] = conv[3 * x + 1] = conv[3 * x + 2] = in[x];
        rgbrow = conv;
      }
      const uint8_t *rows[4] = {NULL, NULL, NULL, NULL};
      if (colour) {
        int any[4];
        color_row(table, cache, rgbrow, h.cupsWidth, y, bits, pg.width / 8, any);
        for (int p = 0; p < 4; p++)
          rows[p] = any[p] ? bits[p] : NULL;
      } else {
        mono_row(&cache[0], rgbrow, h.cupsWidth, y, bits[0], pg.width / 8);
        rows[0] = bits[0];
      }
      if (xl_page_row(&w, y, rows)) {
        status = 1;
        break;
      }
    }
    if (xl_page_end(&w))
      status = 1;
    fprintf(stderr, "PAGE: %d 1\n", page);
    if (status)
      break;
  }

  if (started) {
    if (xl_job_end(&w))
      status = 1;
    xl_writer_free(&w);
  } else if (!status) {
    fputs("ERROR: no pages in the job\n", stderr);
    status = 1;
  }
  for (int p = 0; p < 4; p++) {
    brcd_free(&cache[p]);
    free(bits[p]);
  }
  free(table);
  free(in);
  free(conv);
  cupsRasterClose(ras);
  cupsFreeOptions(num_opts, opts);
  if (fd)
    close(fd);
  return status;
}
