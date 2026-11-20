/*
 * Careful file writing for --extract-brother-data, which runs as root.
 *
 * SPDX-License-Identifier: MIT
 */

#include "fsutil.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int fs_prepare_dir(const char *dir) {
  if (mkdir(dir, 0755) != 0 && errno != EEXIST) {
    fprintf(stderr, "cannot create %s: %s\n", dir, strerror(errno));
    return -1;
  }
  struct stat st;
  if (lstat(dir, &st) != 0) {
    fprintf(stderr, "cannot check %s: %s\n", dir, strerror(errno));
    return -1;
  }
  if (!S_ISDIR(st.st_mode)) {
    fprintf(stderr, "%s is not a directory (or is a symlink)\n", dir);
    return -1;
  }
  if (geteuid() == 0 && (st.st_uid != 0 || (st.st_mode & (S_IWGRP | S_IWOTH)))) {
    fprintf(stderr, "%s must belong to root and not be writable by others\n", dir);
    return -1;
  }
  return 0;
}

int fs_write_file(const char *dir, const char *name, const void *data, size_t len) {
  char path[1024], tmp[1024];
  int n1 = snprintf(path, sizeof path, "%s/%s", dir, name);
  int n2 = snprintf(tmp, sizeof tmp, "%s/.%s.XXXXXX", dir, name);
  if (n1 < 0 || n2 < 0 || (size_t)n1 >= sizeof path || (size_t)n2 >= sizeof tmp) {
    fprintf(stderr, "path too long: %s/%s\n", dir, name);
    return -1;
  }
  int fd = mkstemp(tmp); /* O_EXCL: never opens an existing file or symlink */
  if (fd < 0) {
    fprintf(stderr, "cannot create a file in %s: %s\n", dir, strerror(errno));
    return -1;
  }
  const unsigned char *p = data;
  size_t left = len;
  int ok = fchmod(fd, 0644) == 0;
  while (ok && left) {
    ssize_t w = write(fd, p, left);
    if (w < 0 && errno == EINTR)
      continue;
    if (w <= 0) {
      ok = 0;
      break;
    }
    p += w;
    left -= (size_t)w;
  }
  if (close(fd) != 0)
    ok = 0;
  if (ok && rename(tmp, path) != 0)
    ok = 0;
  if (!ok) {
    fprintf(stderr, "cannot write %s: %s\n", path, strerror(errno));
    unlink(tmp);
    return -1;
  }
  return 0;
}

int fs_copy_file(const char *src, const char *dir, const char *name, const char *magic, size_t magic_off) {
  /* O_NOFOLLOW: a symlink in place of the file is refused, not read as root;
   * O_NONBLOCK: a FIFO or device there cannot make the installer hang */
  int fd = open(src, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
  if (fd < 0) {
    fprintf(stderr, "cannot read %s: %s\n", src, strerror(errno));
    return -1;
  }
  struct stat st;
  if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size > (64 << 20)) {
    fprintf(stderr, "%s is not a regular file of a sensible size\n", src);
    close(fd);
    return -1;
  }
  if (geteuid() == 0 && (st.st_uid != 0 || (st.st_mode & S_IWOTH))) {
    fprintf(stderr, "%s must belong to root and not be writable by everyone\n", src);
    close(fd);
    return -1;
  }
  size_t len = (size_t)st.st_size;
  unsigned char *buf = malloc(len ? len : 1);
  size_t got = 0;
  while (buf && got < len) {
    ssize_t r = read(fd, buf + got, len - got);
    if (r < 0 && errno == EINTR)
      continue;
    if (r <= 0)
      break;
    got += (size_t)r;
  }
  close(fd);
  int rc = -1;
  size_t ml = magic ? strlen(magic) : 0;
  if (!buf || got != len)
    fprintf(stderr, "cannot read %s\n", src);
  else if (ml && (len < magic_off + ml || memcmp(buf + magic_off, magic, ml) != 0))
    fprintf(stderr, "%s is not the kind of file expected there\n", src);
  else
    rc = fs_write_file(dir, name, buf, len);
  free(buf);
  return rc;
}
