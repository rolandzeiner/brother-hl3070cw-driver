"""Measure how Brother's filter maps RGB to K-plane dither levels in Mono mode.

Each test colour fills one 80 x 80 patch aligned to the dither tile, so the
decoded patch must equal exactly one tile of the dither cache.

    python3 -I tools/measure_mono.py grey       # tone curve for grey 0..255
    python3 -I tools/measure_mono.py channels   # pure R, G, B ramps
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import dither  # noqa: E402
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402
import xl2hb  # noqa: E402

TILE = 80


def measure(colours: list[tuple[int, int, int]], cache_name: str = "0600-k_cache08.bin",
            options: str = "BRMonoColor=Mono", size: str = "A6") -> list[list[int]]:
    cache = dither.Cache(dither.LUT_DIR + cache_name)
    tiles: dict[bytes, list[int]] = {}
    for k in range(256):
        tiles.setdefault(cache.body[k * cache.tile : (k + 1) * cache.tile], []).append(k)
    width, height = rw.page_geometry(size)
    cols, rows = width // TILE, height // TILE
    per_page = cols * rows
    results: list[list[int]] = []
    for start in range(0, len(colours), per_page):
        chunk = colours[start : start + per_page]

        def source(y: int, w: int, h: int, chunk=chunk) -> bytes:
            r = y // TILE
            if r >= rows:
                return rw.WHITE * w
            parts = []
            for c in range(cols):
                i = r * cols + c
                parts.append(bytes(chunk[i]) * TILE if i < len(chunk) else rw.WHITE * TILE)
            row = b"".join(parts)
            return row + rw.WHITE * (w - len(row) // 3)

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.ras")
            rw.write(path, size, [source])
            job = pxl.parse(oracle.run(path, options))
        img: dict[int, bytes] = {}
        bpl = 0
        for s, h, m, d in job.images():
            _, _, bpl, brows = xl2hb.decode_band(d)
            for i, r in enumerate(brows):
                img[s + i] = r
        blank = bytes(bpl or width // 8 + 1)
        for i in range(len(chunk)):
            r, c = divmod(i, cols)
            patch = b"".join(
                img.get(r * TILE + y, blank)[c * cache.stride : (c + 1) * cache.stride] for y in range(TILE)
            )
            results.append(tiles.get(patch, []))
    return results


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "grey"
    if what == "grey":
        res = measure([(g, g, g) for g in range(256)])
        for g, ks in enumerate(res):
            print(g, ks)
    elif what == "channels":
        cols = [(v, 255, 255) for v in range(256)] + [(255, v, 255) for v in range(256)] + [(255, 255, v) for v in range(256)]
        res = measure(cols)
        for (r, g, b), ks in zip(cols, res):
            print(r, g, b, ks)


if __name__ == "__main__":
    main()
