/*
 * Careful file access for --extract-brother-data, which runs as root.
 *
 * Nothing here checks a path and then opens it: every check is made on the
 * descriptor that is used afterwards.
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

#define MAX_FILE (64 << 20) /* Brother's largest file, its filter, has 3 MB */

#define DIR_FLAGS (O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
/* O_NONBLOCK: a FIFO or device in place of a file cannot make the installer hang */
#define FILE_FLAGS (O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)

/* When running as root, only what root owns and the forbidden bits do not
 * open to others is used. */
static int check_owner(int fd, const char *what, mode_t forbidden) {
  struct stat st;
  if (fstat(fd, &st) != 0) {
    fprintf(stderr, "cannot check %s: %s\n", what, strerror(errno));
    return -1;
  }
  if (geteuid() == 0 && (st.st_uid != 0 || (st.st_mode & forbidden))) {
    fprintf(stderr, "%s must belong to root and not be writable by %s\n", what,
            (forbidden & S_IWGRP) ? "others" : "everyone");
    return -1;
  }
  return 0;
}

static int open_dir_at(int parent, const char *name, mode_t forbidden) {
  int fd = openat(parent, name, DIR_FLAGS);
  if (fd < 0) {
    fprintf(stderr, "cannot open the folder %s (missing, or a symlink): %s\n", name, strerror(errno));
    return -1;
  }
  if (check_owner(fd, name, forbidden)) {
    close(fd);
    return -1;
  }
  return fd;
}

int fs_open_dir(const char *path) { return open_dir_at(AT_FDCWD, path, S_IWOTH); }

int fs_make_dir(int parent, const char *path) {
  if (mkdirat(parent, path, 0755) != 0 && errno != EEXIST) {
    fprintf(stderr, "cannot create %s: %s\n", path, strerror(errno));
    return -1;
  }
  return open_dir_at(parent, path, S_IWGRP | S_IWOTH);
}

/* Open all but the last part of rel, one level at a time. Returns the folder
 * and points *last at the last part, inside buf. */
static int walk(int root, const char *rel, char *buf, size_t cap, const char **last) {
  size_t n = strlen(rel);
  if (n == 0 || n >= cap) {
    fprintf(stderr, "unusable path: %s\n", rel);
    return -1;
  }
  memcpy(buf, rel, n + 1);
  int dir = fcntl(root, F_DUPFD_CLOEXEC, 0);
  if (dir < 0) {
    fprintf(stderr, "cannot open %s: %s\n", rel, strerror(errno));
    return -1;
  }
  char *part = buf;
  for (;;) {
    char *slash = strchr(part, '/');
    if (slash)
      *slash = 0;
    if (!*part || !strcmp(part, ".") || !strcmp(part, "..")) {
      fprintf(stderr, "unusable path: %s\n", rel);
      close(dir);
      return -1;
    }
    if (!slash) {
      *last = part;
      return dir;
    }
    int next = open_dir_at(dir, part, S_IWOTH);
    close(dir);
    if (next < 0)
      return -1;
    dir = next;
    part = slash + 1;
  }
}

int fs_open_dir_beneath(int root, const char *rel) {
  char buf[1024];
  const char *last;
  int parent = walk(root, rel, buf, sizeof buf, &last);
  if (parent < 0)
    return -1;
  int fd = open_dir_at(parent, last, S_IWOTH);
  close(parent);
  return fd;
}

/* Read all of an open file and close it. */
static uint8_t *read_open_file(int fd, const char *what, size_t *len) {
  struct stat st;
  if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > MAX_FILE) {
    fprintf(stderr, "%s is not a regular file of a sensible size\n", what);
    close(fd);
    return NULL;
  }
  if (check_owner(fd, what, S_IWOTH)) {
    close(fd);
    return NULL;
  }
  size_t n = (size_t)st.st_size, got = 0;
  uint8_t *buf = malloc(n);
  while (buf && got < n) {
    ssize_t r = read(fd, buf + got, n - got);
    if (r < 0 && errno == EINTR)
      continue;
    if (r <= 0)
      break;
    got += (size_t)r;
  }
  close(fd);
  if (!buf || got != n) {
    fprintf(stderr, "cannot read %s\n", what);
    free(buf);
    return NULL;
  }
  *len = n;
  return buf;
}

uint8_t *fs_read_file(int root, const char *rel, size_t *len) {
  char buf[1024];
  const char *last;
  *len = 0;
  int parent = walk(root, rel, buf, sizeof buf, &last);
  if (parent < 0)
    return NULL;
  int fd = openat(parent, last, FILE_FLAGS);
  int err = errno;
  close(parent);
  if (fd < 0) {
    fprintf(stderr, "cannot read %s: %s\n", rel, strerror(err));
    return NULL;
  }
  return read_open_file(fd, rel, len);
}

uint8_t *fs_read_path(const char *path, size_t *len) {
  *len = 0;
  int fd = open(path, FILE_FLAGS);
  if (fd < 0) {
    fprintf(stderr, "cannot read %s: %s\n", path, strerror(errno));
    return NULL;
  }
  return read_open_file(fd, path, len);
}

int fs_write_file(int dir, const char *name, const void *data, size_t len) {
  char tmp[256];
  if (!*name || strchr(name, '/') || !strcmp(name, ".") || !strcmp(name, "..")) {
    fprintf(stderr, "unusable file name: %s\n", name);
    return -1;
  }
  int fd = -1;
  for (unsigned i = 0; i < 100; i++) {
    int n = snprintf(tmp, sizeof tmp, ".%s.%ld.%u", name, (long)getpid(), i);
    if (n < 0 || (size_t)n >= sizeof tmp) {
      fprintf(stderr, "file name too long: %s\n", name);
      return -1;
    }
    /* O_EXCL: never opens an existing file or symlink */
    fd = openat(dir, tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd >= 0 || errno != EEXIST)
      break;
  }
  if (fd < 0) {
    fprintf(stderr, "cannot create %s: %s\n", name, strerror(errno));
    return -1;
  }
  const uint8_t *p = data;
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
  if (ok && renameat(dir, tmp, dir, name) != 0)
    ok = 0;
  if (!ok) {
    fprintf(stderr, "cannot write %s: %s\n", name, strerror(errno));
    unlinkat(dir, tmp, 0);
    return -1;
  }
  return 0;
}

int fs_copy_file(int root, const char *rel, int dir, const char *name, const char *magic, size_t magic_off) {
  size_t len;
  uint8_t *buf = fs_read_file(root, rel, &len);
  if (!buf)
    return -1;
  int rc = -1;
  size_t ml = magic ? strlen(magic) : 0;
  if (ml && (len < magic_off + ml || memcmp(buf + magic_off, magic, ml) != 0))
    fprintf(stderr, "%s is not the kind of file expected there\n", rel);
  else
    rc = fs_write_file(dir, name, buf, len);
  free(buf);
  return rc;
}
