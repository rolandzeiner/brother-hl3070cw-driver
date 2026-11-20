"""Check the decoder against Brother's filter on random black/white pages.

    python3 -I tools/roundtrip.py --pages 20 --seed 1

Every page is pure black and white, so in Mono mode the K plane must equal
the input bitmap exactly. Any difference is a decoder (format) error.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402
import xl2hb  # noqa: E402

_RGB = [b"".join(rw.BLACK if (b >> (7 - i)) & 1 else rw.WHITE for i in range(8)) for b in range(256)]


def rgb_row(bits: bytes, width: int) -> bytes:
    return b"".join(_RGB[b] for b in bits)[: width * 3]


def random_rows(rng: random.Random, width: int, nrows: int) -> list[bytes]:
    nbytes = (width + 7) // 8
    rows: list[bytes] = []
    for y in range(nrows):
        kind = rng.choice(["noise", "sparse", "dense", "dup", "dupedit", "period", "blank", "runs"])
        if kind == "dup" and rows:
            row = bytearray(rows[-1])
        elif kind == "dupedit" and rows:
            row = bytearray(rows[-1])
            for _ in range(rng.randint(1, 6)):
                row[rng.randrange(nbytes)] = rng.randrange(256)
        elif kind == "noise":
            row = bytearray(rng.randrange(256) for _ in range(nbytes))
        elif kind == "sparse":
            row = bytearray(nbytes)
            for _ in range(rng.randint(1, 30)):
                x = rng.randrange(width)
                row[x >> 3] |= 0x80 >> (x & 7)
        elif kind == "dense":
            row = bytearray(rng.choice([0xFF, 0xFF, 0xFE, 0x7F, 0xEF]) for _ in range(nbytes))
        elif kind == "period":
            p = rng.choice([3, 4, 6, 8, 10, 12, 20, 24, 5, 7])
            pat = [rng.random() < 0.5 for _ in range(p)]
            row = bytearray(nbytes)
            for x in range(width):
                if pat[x % p]:
                    row[x >> 3] |= 0x80 >> (x & 7)
        elif kind == "runs":
            row = bytearray(nbytes)
            x = 0
            while x < width:
                n = rng.randint(1, 400)
                if rng.random() < 0.5:
                    for xx in range(x, min(width, x + n)):
                        row[xx >> 3] |= 0x80 >> (xx & 7)
                x += n
        else:
            row = bytearray(nbytes)
        # clear bits beyond the page width
        if width % 8:
            row[-1] &= (0xFF << (8 - width % 8)) & 0xFF
        rows.append(bytes(row))
    return rows


def check_page(rows: list[bytes], top: int, size: str, options: str) -> tuple[int, int, list[str]]:
    width, height = rw.page_geometry(size)
    content = {top + i: r for i, r in enumerate(rows)}

    def source(y: int, w: int, h: int) -> bytes:
        return rgb_row(content[y], w) if y in content else rw.WHITE * w

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        rw.write(path, size, [source])
        job = pxl.parse(oracle.run(path, options))
    got: dict[int, bytes] = {}
    methods = []
    errors: list[str] = []
    for start, height_, mode, data in job.images():
        try:
            method, unit, bpl, brows = xl2hb.decode_band(data)
        except (xl2hb.FormatError, IndexError) as e:
            errors.append(f"band at {start}: {type(e).__name__}: {e}")
            continue
        methods.append((method, unit))
        for i, r in enumerate(brows):
            got[start + i] = r
    bad = 0
    nbytes = (width + 7) // 8
    for y in range(height):
        want = content.get(y, bytes(nbytes))
        have = got.get(y, bytes(nbytes))[:nbytes]
        tail = got.get(y, b"")[nbytes:]
        if have != want or any(tail):
            bad += 1
            if len(errors) < 5:
                errors.append(f"row {y} differs")
    return len(got), bad, errors + [f"methods {sorted(set(methods))}"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--rows", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--size", default="A6")
    ap.add_argument("--options", default="BRMonoColor=Mono")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    width, _ = rw.page_geometry(a.size)
    total_bad = 0
    for page in range(a.pages):
        rows = random_rows(rng, width, a.rows)
        top = rng.randrange(0, 200)
        decoded, bad, notes = check_page(rows, top, a.size, a.options)
        total_bad += bad
        print(f"page {page}: rows decoded {decoded}, rows wrong {bad}  " + " | ".join(notes))
    print("ALL OK" if total_bad == 0 else f"FAILED: {total_bad} wrong rows")
    sys.exit(1 if total_bad else 0)


if __name__ == "__main__":
    main()
