"""Measure how Brother's filter maps RGB to C, M, Y, K dither levels.

Each test colour fills one 80 x 80 patch aligned to the 80-pixel tiles of the
K, C and M dither caches (the 24-pixel Y tile fits inside), so every plane of
a patch must equal exactly one tile of that plane's cache.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import colorplanes as cp  # noqa: E402
import dither  # noqa: E402
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402

PATCH = 80


def load_caches(toner_save: bool = False) -> list[dither.Cache]:
    ts = "-TS" if toner_save else ""
    return [dither.Cache(f"{dither.LUT_DIR}0600-{p}{ts}_cache08.bin") for p in "kcmy"]


def tile_index(c: dither.Cache) -> dict[bytes, list[int]]:
    idx: dict[bytes, list[int]] = {}
    for k in range(256):
        idx.setdefault(c.body[k * c.tile : (k + 1) * c.tile], []).append(k)
    return idx


def extract(rows: dict[int, bytes], x0: int, y0: int, w: int, h: int, stride: int) -> bytes:
    """Cut a w x h bit block at (x0, y0) out of decoded rows, packed like a tile."""
    out = bytearray(stride * h)
    for yy in range(h):
        r = rows.get(y0 + yy)
        if r is None:
            continue
        for xx in range(w):
            x = x0 + xx
            if (r[x >> 3] >> (7 - (x & 7))) & 1:
                out[yy * stride + (xx >> 3)] |= 0x80 >> (xx & 7)
    return bytes(out)


def measure(colours, options="BRMonoColor=FullColor", size="A6", toner_save=False):
    caches = load_caches(toner_save)
    idx = [tile_index(c) for c in caches]
    width, height = rw.page_geometry(size)
    cols, rows_n = width // PATCH, height // PATCH
    per_page = cols * rows_n
    results = []
    for start in range(0, len(colours), per_page):
        chunk = colours[start : start + per_page]

        def source(y, w, h, chunk=chunk):
            r = y // PATCH
            if r >= rows_n:
                return rw.WHITE * w
            parts = []
            for c in range(cols):
                i = r * cols + c
                parts.append(bytes(chunk[i]) * PATCH if i < len(chunk) else rw.WHITE * PATCH)
            row = b"".join(parts)
            return row + rw.WHITE * (w - len(row) // 3)

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.ras")
            rw.write(path, size, [source])
            job = pxl.parse(oracle.run(path, options))
        planes = cp.decode_planes(job)
        for i in range(len(chunk)):
            r, c = divmod(i, cols)
            x0, y0 = c * PATCH, r * PATCH
            levels = []
            for p, cache in enumerate(caches):
                # a whole tile inside the patch, aligned to the tile grid
                tx = -(-x0 // cache.w) * cache.w
                ty = -(-y0 // cache.h) * cache.h
                block = extract(planes[p], tx, ty, cache.w, cache.h, cache.stride)
                levels.append(idx[p].get(block, []))
            results.append(levels)
    return results


if __name__ == "__main__":
    import ast
    cols = [ast.literal_eval(a) for a in sys.argv[1:]] or [(0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 0, 0), (128, 128, 128)]
    for col, lv in zip(cols, measure(cols)):
        print(col, "K C M Y levels:", [l if len(l) < 4 else f"{l[0]}..{l[-1]}" for l in lv])
