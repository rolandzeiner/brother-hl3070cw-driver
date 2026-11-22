/*
 * rastertohl3070cw: CUPS filter for the Brother HL-3070CW.
 *
 *   rastertohl3070cw job-id user title copies options [file]
 *   rastertohl3070cw --extract-brother-data [--unpacked]
 *   rastertohl3070cw --check-data
 *   rastertohl3070cw --version
 *
 * Reads CUPS raster (RGB or grey, 8 bits per channel, 600 dpi) and writes
 * Brother's XL2HB printer language. Mono output at 600 dpi is byte-identical
 * to Brother's own filter; colour uses Brother's colour tables and dither
 * tiles with an interpolation fitted to Brother's output; Fine prints the
 * same dots as Brother's filter with a close model of its compression (see
 * docs/FORMAT.md).
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
 *   cupsInteger4  BRResolution     0 600dpi, 1 600x2400dpi (Fine)
 *   cupsInteger5  BRColorMatching  0 Normal, 1 Vivid, 2 None
 *   cupsInteger6  BRGray           0 or 1 ON, 2 OFF
 *   cupsInteger7  BREnhanceBlkPrt  0 OFF, 1 ON
 *
 * Secure Print comes as the job's PIN (IPP job-password, "Print with PIN" in
 * the print dialog), which the PPD allows through *cupsJobPassword.
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
#define DRIVER_VERSION "dev" /* the Makefile sets the real one */
#endif

/* Where this driver keeps its copy of Brother's data, where its installer
 * unpacks a package of Brother's, and where that package puts the originals:
 * Brother's macOS driver, or on Linux its LPR driver for the HL-3070CW (the
 * colour tables are inside its filter program, as on macOS). Only the macOS
 * driver has ICC profiles; macOS's colour matching uses them before this
 * filter.
 *
 * These paths are fixed. The step that runs as root takes none from its
 * command line. (The self-test build has its own, see the Makefile.) */
#ifdef __APPLE__
#define DRIVER_DIR "/Library/Printers/HL3070CW-Native"
#ifndef BROTHER_DIR
#define BROTHER_DIR "/Library/Printers/Brother"
#define BROTHER_LUT "Brother LUT"
#define BROTHER_FILTER "Filter/rastertobrother3040.bundle/Contents/MacOS/rastertobrother3040"
#define BROTHER_PROFILES "Profiles"
#endif
#else
#define DRIVER_DIR "/usr/share/hl3070cw-native"
#ifndef BROTHER_DIR
#define BROTHER_DIR "/opt/brother/Printers/hl3070cw"
#define BROTHER_LUT "inf/lut"
#define BROTHER_FILTER "lpd/brhl3070cwfilter"
#endif
#endif
#define DRIVER_DATA_DIR DRIVER_DIR "/data"
/* inside a folder only root can enter: see install-linux.sh */
#define DRIVER_PACKAGE_DIR DRIVER_DIR "/unpack/package"
#define BROTHER_FILTER_PATH BROTHER_DIR "/" BROTHER_FILTER

/* The largest page the printer takes, in pixels at 600 dpi with no margins
 * taken off: 624 pt wide (DL Long Edge, the widest size) and 1152 pt long
 * (the longest custom size of Brother's driver). */
#define MAX_PAGE_WIDTH 5200
#define MAX_PAGE_HEIGHT 9600

/* Custom paper, in points, as Brother's PPD allows it (*ParamCustomPageSize;
 * its 328.32 pt arrive as 328 in the page header). */
#define CUSTOM_MIN_WIDTH 198
#define CUSTOM_MAX_WIDTH 612
#define CUSTOM_MIN_HEIGHT 328
#define CUSTOM_MAX_HEIGHT 1152

static volatile sig_atomic_t g_cancelled;

static void on_term(int sig) {
  (void)sig;
  g_cancelled = 1;
}

/* The printer data could not be written. Said once, and not for a cancelled
 * job, whose backend may be gone. Returns the filter's status. */
static int write_failed(void) {
  static int said;
  int err = errno;
  if (!g_cancelled && !said) {
    fprintf(stderr, "ERROR: cannot write the printer data: %s\n", strerror(err));
    said = 1;
  }
  return 1;
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

/* Points to tenths of a millimetre as Brother's filter counts them: down to
 * whole 1/120 inch, then down to whole tenths. */
static unsigned custom_tenths(unsigned points) { return points * 120 / 72 * 254 / 120; }

/* The paper for a page of w x h points: one of the printer's sizes, or a
 * custom size in its range. -1 for anything else. */
static int media_size_for(unsigned w, unsigned h, xl_media_size *out) {
  for (size_t i = 0; i < sizeof sizes / sizeof sizes[0]; i++)
    if (absdiff(sizes[i].w, w) <= 1 && absdiff(sizes[i].h, h) <= 1) {
      *out = sizes[i].size;
      return 0;
    }
  if (w < CUSTOM_MIN_WIDTH || w > CUSTOM_MAX_WIDTH || h < CUSTOM_MIN_HEIGHT || h > CUSTOM_MAX_HEIGHT)
    return -1;
  xl_media_size s = {XL_SIZE_CUSTOM, 0, NULL, custom_tenths(w), custom_tenths(h)};
  *out = s;
  return 0;
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
  int enhance_black;
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
  o->enhance_black = opt_choice(cupsGetOption("BREnhanceBlkPrt", num, opts), onoff, 2, h->cupsInteger[7] == 1);
  o->input_slot = cupsGetOption("InputSlot", num, opts);
  o->media_type = cupsGetOption("MediaType", num, opts);
}

/* Secure Print: the PIN of the job, if it has one, into key (5 bytes).
 * Returns 0 with key empty (no PIN), 0 with the PIN, or -1 when the job asks
 * for a PIN this printer cannot take. Such a job is not printed at all:
 * printing it without the PIN would put a confidential page in the output
 * tray. (Brother's filter does print it then, without the PIN.) */
static int secure_print_key(int num, cups_option_t *opts, char key[5]) {
  key[0] = 0;
  const char *pin = cupsGetOption("job-password", num, opts);
  if (!pin)
    return 0;
  const char *enc = cupsGetOption("job-password-encryption", num, opts);
  if (enc && strcasecmp(enc, "none") != 0) {
    fputs("ERROR: Secure Print: the PIN arrived encrypted, but the printer needs the digits. "
          "The job was not printed.\n",
          stderr);
    return -1;
  }
  /* the printer's panel takes digits only, and exactly four */
  if (strlen(pin) != 4 || strspn(pin, "0123456789") != 4) {
    fputs("ERROR: Secure Print: the PIN must be 4 digits. The job was not printed.\n", stderr);
    return -1;
  }
  memcpy(key, pin, 5);
  return 0;
}

/* ---- Brother data ------------------------------------------------------------- */

static const char *data_dir(void) {
#ifdef HL3070CW_TEST_HOOKS
  /* the self-test build only (make check): made-up data instead of Brother's */
  const char *d = getenv("HL3070CW_DATA");
  if (d && *d)
    return d;
#endif
  return DRIVER_DATA_DIR;
}

static const char *package_dir(void) {
#ifdef HL3070CW_TEST_HOOKS
  const char *d = getenv("HL3070CW_PACKAGE");
  if (d && *d)
    return d;
#endif
  return DRIVER_PACKAGE_DIR;
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

/* Path of a plane's dither file: this driver's copy, else Brother's own. */
static int tile_path(char *path, size_t cap, char plane, int toner_save, int fine) {
  char name[64];
  snprintf(name, sizeof name, "%s-%c%s_cache08.bin", fine ? "capt" : "0600", plane, toner_save ? "-TS" : "");
  if (path_join(path, cap, data_dir(), "/", name))
    return -1;
  if (access(path, R_OK) != 0 && path_join(path, cap, BROTHER_DIR "/" BROTHER_LUT, "/", name))
    return -1;
  return 0;
}

static int load_cache(brcd_cache *c, char plane, int toner_save, int fine) {
  char path[1024];
  if (tile_path(path, sizeof path, plane, toner_save, fine))
    return -1;
  if (brcd_load(c, path))
    return -1;
  if (c->fine != fine) {
    fprintf(stderr, "ERROR: %s is not a %s dither file\n", path, fine ? "Fine" : "600 dpi");
    brcd_free(c);
    return -1;
  }
  return 0;
}

static int load_table(color_table *t, int matching, int improve_gray, int fine) {
  char path[1024];
  if (path_join(path, sizeof path, data_dir(), "/", color_table_file((color_matching)matching, improve_gray, fine)))
    return -1;
  if (color_table_load(t, path) == 0)
    return 0;
  if (access(path, F_OK) == 0)
    fprintf(stderr, "WARNING: %s is damaged, reading the table from Brother's driver instead\n", path);
  if (color_table_from_brother(t, BROTHER_FILTER_PATH, (color_matching)matching, improve_gray, fine) == 0)
    return 0;
  fprintf(stderr, "ERROR: Brother's colour tables not found (in %s or Brother's driver). "
                  "Install Brother's HL-3070CW driver, or use the PostScript version of this driver\n",
          data_dir());
  return -1;
}

/* Whether the Fine dither files and colour table for this job are there. An
 * installation made before Fine was supported has none, and gets them only
 * when the installer runs again while Brother's driver is installed. */
static int have_fine_data(int toner_save, int colour, int matching, int improve_gray) {
  static const char planes[] = "kcmy";
  char path[1024];
  for (int p = 0; p < (colour ? 4 : 1); p++)
    if (tile_path(path, sizeof path, planes[p], toner_save, 1) || access(path, R_OK) != 0)
      return 0;
  if (!colour)
    return 1;
  if (path_join(path, sizeof path, data_dir(), "/", color_table_file((color_matching)matching, improve_gray, 1)))
    return 0;
  return access(path, R_OK) == 0 || access(BROTHER_FILTER_PATH, R_OK) == 0;
}

#ifdef BROTHER_PROFILES
/* for macOS's colour matching (named in the PPD): Normal, then Fine */
#define NORMAL_PROFILES 2
static const char *const profiles[] = {"broch08_PL_NM.icm", "broch08_PL_NM_IG_ON.icm", "broch08_PL_Fi.icm",
                                       "broch08_PL_Fi_IG_ON.icm"};
#endif

/* --check-data, for the installers: whether the driver's copy of Brother's
 * data has everything the native driver needs (Fine's files are extra, as in
 * copy_brother_files). Reads the driver's folder only, says nothing when it
 * is just not there. */
static int data_complete(void) {
  static const char planes[] = "kcmy";
  char path[1024];
  for (int p = 0; p < 4; p++)
    for (int ts = 0; ts < 2; ts++) {
      char name[64];
      snprintf(name, sizeof name, "0600-%c%s_cache08.bin", planes[p], ts ? "-TS" : "");
      brcd_cache c;
      if (path_join(path, sizeof path, data_dir(), "/", name) || access(path, R_OK) != 0 || brcd_load(&c, path))
        return 0;
      int fine = c.fine;
      brcd_free(&c);
      if (fine)
        return 0;
    }
#ifdef BROTHER_PROFILES
  for (size_t i = 0; i < NORMAL_PROFILES; i++)
    if (path_join(path, sizeof path, data_dir(), "/profiles/", profiles[i]) || access(path, R_OK) != 0)
      return 0;
#endif
  color_table *t = malloc(sizeof *t);
  int ok = t != NULL;
  for (int m = 0; ok && m < 3; m++)
    for (int g = 0; ok && g < 2; g++)
      ok = path_join(path, sizeof path, data_dir(), "/", color_table_file((color_matching)m, g, 0)) == 0 &&
           color_table_load(t, path) == 0;
  free(t);
  return ok;
}

/* The folder of Brother's driver: the installed one, or the same folder in
 * the package the installer unpacked. A package's content is not trusted:
 * below the package folder no symlink is followed, not even one that points
 * back inside it. */
static int open_brother_dir(int unpacked) {
  if (!unpacked)
    return fs_open_dir(BROTHER_DIR);
  int package = fs_open_dir(package_dir());
  if (package < 0)
    return -1;
  int fd = fs_open_dir_beneath(package, &BROTHER_DIR[1]); /* without the leading slash */
  close(package);
  return fd;
}

/* Copy what the driver needs from the folder from into the folder to. */
static int copy_brother_files(int from, int to) {
  /* The 600 dpi files are needed; without the Fine ones the driver still
   * works and prints Fine jobs in Normal quality. */
  int failed = 0, fine_missing = 0;
  char path[1024];
  static const char planes[] = "kcmy";
  for (int fine = 0; fine < 2; fine++)
    for (int p = 0; p < 4; p++)
      for (int ts = 0; ts < 2; ts++) {
        char name[64];
        snprintf(name, sizeof name, "%s-%c%s_cache08.bin", fine ? "capt" : "0600", planes[p], ts ? "-TS" : "");
        if (path_join(path, sizeof path, BROTHER_LUT, "/", name) || fs_copy_file(from, path, to, name, "BRCD", 0)) {
          if (fine)
            fine_missing = 1;
          else
            failed = 1;
        }
      }
  if (color_tables_extract(from, BROTHER_FILTER, to))
    failed = 1;
#ifdef BROTHER_PROFILES
  int sub = fs_make_dir(to, "profiles");
  if (sub < 0)
    return 1;
  for (size_t i = 0; i < sizeof profiles / sizeof profiles[0]; i++)
    if (path_join(path, sizeof path, BROTHER_PROFILES, "/", profiles[i]) ||
        fs_copy_file(from, path, sub, profiles[i], "acsp", 36)) { /* the ICC profile signature */
      if (i >= NORMAL_PROFILES)
        fine_missing = 1;
      else
        failed = 1;
    }
  close(sub);
#endif
  if (!failed && fine_missing)
    fputs("Some files for Fine quality were not found; Fine will print in Normal quality\n", stderr);
  return failed;
}

/* Runs as root from the installers: see src/fsutil.h for the safeguards. */
static int extract_brother_data(int unpacked) {
  umask(022); /* the files must stay readable for CUPS (lp) */
  int from = open_brother_dir(unpacked);
  if (from < 0)
    return 1;
  int to = fs_make_dir(AT_FDCWD, data_dir());
  if (to < 0) {
    close(from);
    return 1;
  }
  int failed = copy_brother_files(from, to);
  close(from);
  close(to);
  if (!failed)
    printf("Brother's data copied to %s\n", data_dir());
  return failed;
}

/* PJL strings are quoted; keep them to 80 bytes of printable text. */
static void clean_text(char *dst, size_t cap, const char *src) {
  size_t n = 0, len_src = src ? strlen(src) : 0;
  for (; n < len_src && n + 1 < cap; n++) {
    unsigned char c = (unsigned char)src[n];
    dst[n] = (c == '"') ? '\'' : (c < 0x20 || c == 0x7F) ? ' ' : (char)c;
  }
  if (n < len_src && n > 0) {
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
  if (argc == 2 && !strcmp(argv[1], "--check-data"))
    return data_complete() ? 0 : 1;
  if (argc >= 2 && !strcmp(argv[1], "--extract-brother-data")) {
    if (argc == 2)
      return extract_brother_data(0);
    if (argc == 3 && !strcmp(argv[2], "--unpacked"))
      return extract_brother_data(1);
    fputs("Usage: rastertohl3070cw --extract-brother-data [--unpacked]\n", stderr);
    return 1;
  }
  if (argc < 6 || argc > 7) {
    fputs("Usage: rastertohl3070cw job-id user title copies options [file]\n"
          "       rastertohl3070cw --extract-brother-data [--unpacked]\n"
          "       rastertohl3070cw --check-data\n",
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
  /* On a cancel the backend goes on sending what it gets, so what has been
   * started must be written whole: an interrupted write would lose part of it. */
  sa.sa_flags = SA_RESTART;
  sigaction(SIGTERM, &sa, NULL);
  signal(SIGPIPE, SIG_IGN);
  signal(SIGXFSZ, SIG_IGN); /* at a file size limit: an error from write(), not a silent death */

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
  char hold_key[5];
  int status = secure_print_key(num_opts, opts, hold_key) ? 1 : 0;
  job.hold_key = hold_key[0] ? hold_key : NULL;

  static char outbuf[1 << 16];
  setvbuf(stdout, outbuf, _IOFBF, sizeof outbuf);

  cups_raster_t *ras = cupsRasterOpen(fd, CUPS_RASTER_READ);
  cups_page_header2_t h;
  xl_writer w;
  brcd_cache cache[4];
  memset(cache, 0, sizeof cache);
  color_table *table = NULL;
  uint8_t *in = NULL, *conv = NULL, *bits[4] = {NULL, NULL, NULL, NULL};
  int page = 0, started = 0, colour = 0;
  job_options o;
  memset(&o, 0, sizeof o);

  while (!status && !g_cancelled && cupsRasterReadHeader2(ras, &h)) {
    if (g_cancelled) /* while waiting for the header */
      break;
    page++;

    /* The page header is untrusted input: check format and geometry before
     * anything is allocated or written. libcups does not tie the bytes per
     * line to the width. A page larger than the printer can print is refused:
     * nothing useful would come out, and what the printer's firmware does
     * with such a page is unknown. */
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
    if (h.cupsWidth == 0 || h.cupsHeight == 0 ||
        (uint64_t)h.cupsBytesPerLine != (uint64_t)h.cupsWidth * (bpp / 8)) {
      fprintf(stderr, "ERROR: bad raster geometry: %u x %u pixels, %u bytes per line\n", h.cupsWidth,
              h.cupsHeight, h.cupsBytesPerLine);
      status = 1;
      break;
    }
    if (h.cupsWidth > MAX_PAGE_WIDTH || h.cupsHeight > MAX_PAGE_HEIGHT) {
      fprintf(stderr, "ERROR: the page is larger than the printer can print: %u x %u pixels, at most %d x %d\n",
              h.cupsWidth, h.cupsHeight, MAX_PAGE_WIDTH, MAX_PAGE_HEIGHT);
      status = 1;
      break;
    }

    xl_media_size paper;
    if (media_size_for(h.PageSize[0], h.PageSize[1], &paper)) {
      fprintf(stderr, "ERROR: the printer does not take paper of %u x %u points\n", h.PageSize[0], h.PageSize[1]);
      status = 1;
      break;
    }

    if (!started) {
      resolve_options(&o, num_opts, opts, &h);
      colour = o.color_mode != 2;
      if (o.fine && !have_fine_data(o.toner_save, colour, o.matching, o.improve_gray)) {
        fputs("WARNING: The data for Fine quality is not installed, printing in Normal quality. "
              "Run the driver's installer again while Brother's driver is installed.\n",
              stderr);
        o.fine = 0;
      }
      job.fine = o.fine;
      job.render = o.color_mode == 2 ? XL_MONO : o.color_mode == 1 ? XL_COLOR : XL_AUTO;
      job.improve_gray = o.improve_gray;
      job.less_paper_curl = o.improve == 1;
      job.fix_intensity = o.improve == 2;
      job.enhance_black = o.enhance_black;
      if (load_cache(&cache[0], 'k', o.toner_save, o.fine)) {
        status = 1;
        break;
      }
      if (colour) {
        table = malloc(sizeof *table);
        if (!table || load_cache(&cache[1], 'c', o.toner_save, o.fine) ||
            load_cache(&cache[2], 'm', o.toner_save, o.fine) || load_cache(&cache[3], 'y', o.toner_save, o.fine) ||
            load_table(table, o.matching, o.improve_gray, o.fine)) {
          status = 1;
          break;
        }
      }
    }

    xl_page pg;
    memset(&pg, 0, sizeof pg);
    pg.size = paper;
    pg.manual_feed = o.input_slot ? !strcasecmp(o.input_slot, "Manual")
                                  : (h.ManualFeed || h.MediaPosition == 4);
    pg.media_type = media_type_for(o.media_type, h.cupsMediaType);
    /* rounded up to whole 32-bit words: 32 pixels, or 8 at 4 bits per pixel */
    pg.width = o.fine ? (h.cupsWidth + 7) & ~7u : (h.cupsWidth + 31) & ~31u;
    size_t bpl = o.fine ? pg.width / 2 : pg.width / 8;
    unsigned height = h.cupsHeight;
    if (h.ImagingBoundingBox[3] > h.ImagingBoundingBox[1]) {
      unsigned bbox_h = (h.ImagingBoundingBox[3] - h.ImagingBoundingBox[1]) * h.HWResolution[1] / 72;
      if (bbox_h && bbox_h < height)
        height = bbox_h;
    }
    pg.height = height;

    free(in);
    free(conv);
    conv = NULL;
    for (int p = 0; p < 4; p++) {
      free(bits[p]);
      bits[p] = malloc(bpl);
    }
    in = malloc(h.cupsBytesPerLine);
    if (grey)
      conv = malloc((size_t)h.cupsWidth * 3);
    if (!in || !bits[0] || !bits[1] || !bits[2] || !bits[3] || (grey && !conv)) {
      fputs("ERROR: out of memory\n", stderr);
      status = 1;
      break;
    }
    int page_begun = 0;
    for (unsigned y = 0; y < h.cupsHeight; y++) {
      if (g_cancelled)
        break;
      if (cupsRasterReadPixels(ras, in, h.cupsBytesPerLine) < h.cupsBytesPerLine) {
        if (!g_cancelled) { /* a cancelled job ends like this without being an error */
          fprintf(stderr, "ERROR: raster data ends early on page %d\n", page);
          status = 1;
        }
        break;
      }
      if (!page_begun) {
        /* Only now, with the first line here: the printer ejects every page
         * that is started, and the rasterizer can take seconds to get this
         * far. A job cancelled in that time must not give a blank sheet. */
        if (g_cancelled)
          break;
        if (!started) {
          if (xl_job_begin(&w, stdout, &job)) {
            status = write_failed();
            break;
          }
          started = 1;
        }
        fprintf(stderr, "INFO: Printing page %d\n", page);
        if (xl_page_begin(&w, &pg)) {
          status = write_failed();
          break;
        }
        page_begun = 1;
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
        if (o.fine)
          color_row_fine(table, cache, rgbrow, h.cupsWidth, y, bits, bpl, any);
        else
          color_row(table, cache, rgbrow, h.cupsWidth, y, bits, bpl, any);
        for (int p = 0; p < 4; p++)
          rows[p] = any[p] ? bits[p] : NULL;
      } else {
        if (o.fine)
          mono_row_fine(&cache[0], rgbrow, h.cupsWidth, y, bits[0], bpl);
        else
          mono_row(&cache[0], rgbrow, h.cupsWidth, y, bits[0], bpl);
        rows[0] = bits[0];
      }
      if (xl_page_row(&w, y, rows)) {
        status = write_failed();
        break;
      }
    }
    if (page_begun) {
      if (xl_page_end(&w))
        status = write_failed();
      fprintf(stderr, "PAGE: %d 1\n", page);
    }
    if (status)
      break;
  }

  if (started) {
    if (xl_job_end(&w))
      status = write_failed();
    xl_writer_free(&w);
  } else if (!status && !g_cancelled) {
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
  /* a cancel is not a failure, also when the backend was gone before the job's end */
  return g_cancelled ? 0 : status;
}
