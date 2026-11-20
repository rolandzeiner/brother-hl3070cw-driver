/*
 * Fixes the clock of Brother's filter for reproducible test output:
 *   DYLD_INSERT_LIBRARIES=build/faketime.dylib FAKE_TIME=<epoch> rastertobrother3040 ...
 * Build: clang -arch x86_64 -dynamiclib -o build/faketime.dylib tools/faketime.c
 *
 * SPDX-License-Identifier: MIT
 */
#include <stdlib.h>
#include <sys/time.h>
#include <time.h>

static time_t fake(void) {
  const char *e = getenv("FAKE_TIME");
  return e ? (time_t)strtoll(e, NULL, 10) : 0;
}

static time_t my_time(time_t *t) {
  time_t v = fake();
  if (t)
    *t = v;
  return v;
}

static int my_gettimeofday(struct timeval *tv, void *tz) {
  (void)tz;
  if (tv) {
    tv->tv_sec = fake();
    tv->tv_usec = 0;
  }
  return 0;
}

__attribute__((used)) static const struct {
  const void *replacement;
  const void *replacee;
} interposers[] __attribute__((section("__DATA,__interpose"))) = {
    {(const void *)my_time, (const void *)time},
    {(const void *)my_gettimeofday, (const void *)gettimeofday},
};
