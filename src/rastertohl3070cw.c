/*
 * rastertohl3070cw: CUPS filter for the Brother HL-3070CW.
 *
 *   rastertohl3070cw job-id user title copies options [file]
 *
 * Reads CUPS raster (RGB or grey, 8 bits per channel) and writes Brother's
 * XL2HB printer language. Step one of the project: Mono printing at 600 dpi,
 * byte-identical to Brother's own filter. Colour and the "Fine" mode follow.
 *
 * Options are taken from the job's options (argv[5]) first and otherwise
 * from the page header, where this driver's PPD puts them:
 *   cupsInteger1  TonerSaveMode    0 OFF, 1 ON
 *   cupsInteger2  BRImproveOutput  0 OFF, 1 BRLessPaperCurl, 2 BRFixIntensity
 *   cupsInteger3  BRMonoColor      0 Auto, 1 FullColor, 2 Mono
 *   cupsInteger4  BRResolution     0 600dpi, 1 600x2400dpi
 *
 * SPDX-License-Identifier: MIT
 */

#include <cups/cups.h>
#include <cups/raster.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

#include "halftone.h"
#include "xl2hb.h"

#ifndef DRIVER_VERSION
#define DRIVER_VERSION "0.1.0-dev"
#endif

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

static xl_media_size media_size_for(unsigned w, unsigned h) {
  for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; i++)
    if ((unsigned)abs((int)sizes[i].w - (int)w) <= 1 && (unsigned)abs((int)sizes[i].h - (int)h) <= 1)
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

static void resolve_options(job_options *o, int num, cups_option_t *opts, const cups_page_header2_t *h) {
  static const char *const onoff[] = {"OFF", "ON"};
  static const char *const improve[] = {"OFF", "BRLessPaperCurl", "BRFixIntensity"};
  static const char *const color[] = {"Auto", "FullColor", "Mono"};
  static const char *const res[] = {"600dpi", "600x2400dpi"};
  o->toner_save = opt_choice(cupsGetOption("TonerSaveMode", num, opts), onoff, 2, h->cupsInteger[1] == 1);
  o->improve = opt_choice(cupsGetOption("BRImproveOutput", num, opts), improve, 3,
                          h->cupsInteger[2] <= 2 ? (int)h->cupsInteger[2] : 0);
  o->color_mode = opt_choice(cupsGetOption("BRMonoColor", num, opts), color, 3,
                             h->cupsInteger[3] <= 2 ? (int)h->cupsInteger[3] : 0);
  o->fine = opt_choice(cupsGetOption("BRResolution", num, opts), res, 2, h->cupsInteger[4] == 1);
  o->input_slot = cupsGetOption("InputSlot", num, opts);
  o->media_type = cupsGetOption("MediaType", num, opts);
}

/* PJL strings are quoted; keep them to 80 bytes of printable text. */
static void clean_text(char *dst, size_t cap, const char *src) {
  size_t n = 0;
  for (const unsigned char *p = (const unsigned char *)(src ? src : ""); *p && n + 1 < cap; p++)
    dst[n++] = (*p == '"') ? '\'' : (*p < 0x20 || *p == 0x7F) ? ' ' : (char)*p;
  /* do not end in the middle of a UTF-8 sequence */
  if (src && strlen(src) >= cap) {
    while (n > 0 && ((unsigned char)dst[n - 1] & 0xC0) == 0x80)
      n--;
    if (n > 0 && ((unsigned char)dst[n - 1] & 0xC0) == 0xC0)
      n--;
  }
  dst[n] = 0;
}

/* ---- main ------------------------------------------------------------------- */

int main(int argc, char *argv[]) {
  if (argc == 2 && !strcmp(argv[1], "--version")) {
    printf("rastertohl3070cw %s\n", DRIVER_VERSION);
    return 0;
  }
  if (argc < 6 || argc > 7) {
    fputs("Usage: rastertohl3070cw job-id user title copies options [file]\n", stderr);
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
  brcd_cache cache = {0};
  uint8_t *in = NULL, *bits = NULL;
  int page = 0, status = 0, started = 0;
  job_options o;

  while (!g_cancelled && cupsRasterReadHeader2(ras, &h)) {
    page++;
    if (!started) {
      resolve_options(&o, num_opts, opts, &h);
      if (o.color_mode != 2)
        fputs("INFO: Colour is not supported yet, printing in Mono\n", stderr);
      if (o.fine)
        fputs("INFO: Fine (2400 dpi class) is not supported yet, printing at 600 dpi\n", stderr);
      job.toner_save = o.toner_save;
      job.less_paper_curl = o.improve == 1;
      job.fix_intensity = o.improve == 2;
      const char *file = o.toner_save ? BROTHER_LUT_DIR "0600-k-TS_cache08.bin" : BROTHER_LUT_DIR "0600-k_cache08.bin";
      if (brcd_load(&cache, file)) {
        status = 1;
        break;
      }
      if (xl_job_begin(&w, stdout, &job)) {
        status = 1;
        break;
      }
      started = 1;
    }

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
    free(bits);
    in = malloc(h.cupsBytesPerLine);
    bits = malloc(pg.width / 8);
    if (!in || !bits) {
      fputs("ERROR: out of memory\n", stderr);
      status = 1;
      break;
    }
    fprintf(stderr, "INFO: Printing page %d\n", page);
    if (xl_page_begin(&w, &pg)) {
      status = 1;
      break;
    }
    uint8_t *rgbrow = in;
    uint8_t *conv = NULL;
    if (grey)
      conv = malloc((size_t)h.cupsWidth * 3);
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
      if (grey) {
        for (unsigned x = 0; x < h.cupsWidth; x++) {
          uint8_t v = h.cupsColorSpace == CUPS_CSPACE_W || h.cupsColorSpace == CUPS_CSPACE_SW ? in[x] : 0;
          conv[3 * x] = conv[3 * x + 1] = conv[3 * x + 2] = v;
        }
        rgbrow = conv;
      }
      mono_row(&cache, rgbrow, h.cupsWidth, y, bits, pg.width / 8);
      if (xl_page_row(&w, y, bits)) {
        status = 1;
        break;
      }
    }
    free(conv);
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
  }
  brcd_free(&cache);
  free(in);
  free(bits);
  cupsRasterClose(ras);
  cupsFreeOptions(num_opts, opts);
  if (fd)
    close(fd);
  return status;
}
