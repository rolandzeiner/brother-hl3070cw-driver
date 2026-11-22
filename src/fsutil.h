/*
 * Careful file access for --extract-brother-data, which runs as root.
 *
 * Folders are handed around as open descriptors and opened one level at a
 * time without following symlinks, so a path cannot lead somewhere else
 * between a check and its use.
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef FSUTIL_H
#define FSUTIL_H

#include <stddef.h>
#include <stdint.h>

/* Open a folder at one of the driver's fixed paths. The folder itself must
 * not be a symlink; when running as root it must belong to root and not be
 * writable by everyone. Returns a descriptor, or -1 with a message. */
int fs_open_dir(const char *path);

/* Open the folder rel below root. No part of rel may be a symlink, "." or
 * "..", and each folder on the way is checked as by fs_open_dir. */
int fs_open_dir_beneath(int root, const char *rel);

/* Create (mode 0755) if missing and open a folder to write into; parent is
 * AT_FDCWD for an absolute path. Never a symlink; when running as root it
 * must belong to root and not be writable by group or others. */
int fs_make_dir(int parent, const char *path);

/* Write data to name in dir through a new file and a rename, so an existing
 * file or symlink of that name is replaced, never followed. Mode 0644. */
int fs_write_file(int dir, const char *name, const void *data, size_t len);

/* Read the regular file rel below root (at most 64 MB), opened as by
 * fs_open_dir_beneath; when running as root it must belong to root and not
 * be writable by everyone. Returns malloc'ed data, or NULL with a message. */
uint8_t *fs_read_file(int root, const char *rel, size_t *len);

/* The same for a file at one of the driver's fixed paths. */
uint8_t *fs_read_path(const char *path, size_t *len);

/* fs_read_file, then fs_write_file. If magic is given, the file must hold
 * those bytes at magic_off, so only a file of the expected kind is copied. */
int fs_copy_file(int root, const char *rel, int dir, const char *name, const char *magic, size_t magic_off);

#endif
