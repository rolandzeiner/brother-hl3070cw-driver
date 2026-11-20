/*
 * Careful file writing for --extract-brother-data, which runs as root.
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef FSUTIL_H
#define FSUTIL_H

#include <stddef.h>

/* Create dir (mode 0755) if missing and check it is a real directory, not a
 * symlink; when running as root it must also belong to root and not be
 * writable by group or others. Returns 0 or -1 with a message on stderr. */
int fs_prepare_dir(const char *dir);

/* Write data to dir/name through a temporary file and rename(), so an
 * existing file or symlink at that name is replaced, never followed.
 * The file gets mode 0644. Returns 0 or -1 with a message on stderr. */
int fs_write_file(const char *dir, const char *name, const void *data, size_t len);

/* Copy a regular file (at most 64 MB) to dir/name with fs_write_file. The
 * source is never followed through a symlink; when running as root it must
 * belong to root and not be writable by everyone. If magic is given, the
 * file must hold those bytes at magic_off, so only a file of the expected
 * kind is copied. */
int fs_copy_file(const char *src, const char *dir, const char *name, const char *magic, size_t magic_off);

#endif
