"""Compare the reference encoder with Brother's own line encodings.

Brother's output is decoded to units, re-encoded with tools/xl2hb_enc.py and
compared byte for byte. Only method-2 jobs count (Brother picks method 4 for
about one job in five, at random).

    python3 -I tools/enccheck.py --pages 10 --seed 1
"""

from __future__ import annotations

import argparse
import os
import random
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402
import roundtrip  # noqa: E402
import xl2hb  # noqa: E402
import xl2hb_enc  # noqa: E402


def lines_of(data: bytes):
    p = 12
    for _ in range(struct.unpack_from(">H", data, 6)[0]):
        _, ln = struct.unpack_from(">HH", data, p)
        p += 4
        yield data[p : p + ln]
        p += (ln + 3) & ~3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--rows", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--show", type=int, default=6)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    width, _ = rw.page_geometry("A6")
    same = diff = skipped = 0
    shown = 0
    for _ in range(a.pages):
        rows = roundtrip.random_rows(rng, width, a.rows)
        content = dict(enumerate(rows))

        def source(y, w, h, content=content):
            return roundtrip.rgb_row(content[y], w) if y in content else rw.WHITE * w

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.ras")
            rw.write(path, "A6", [source])
            job = pxl.parse(oracle.run(path, "BRMonoColor=Mono"))
        for start, h, mode, data in job.images():
            method, unit, bpl, brows, traces = xl2hb.decode_band(data, trace=True)
            if method != 2:
                skipped += 1
                continue
            for i, line in enumerate(lines_of(data)):
                units = xl2hb.bits_to_units(brows[i], unit, bpl * 8)
                mine = xl2hb_enc.encode_line(units, unit)
                if mine == line:
                    same += 1
                else:
                    diff += 1
                    if shown < a.show:
                        shown += 1
                        k = next(j for j in range(min(len(mine), len(line))) if mine[j] != line[j]) if any(
                            mine[j] != line[j] for j in range(min(len(mine), len(line)))) else min(len(mine), len(line))
                        print(f"row {start + i}: brother {len(line)} B, mine {len(mine)} B, first diff at byte {k}")
                        print("   brother:", line[max(0, k - 6) : k + 10].hex(" "))
                        print("   mine:   ", mine[max(0, k - 6) : k + 10].hex(" "))
                        print("   brother trace:", [(t[0], t[1]) for t in traces[i]][:30])
    print(f"lines identical {same}, different {diff}, method-4 bands skipped {skipped}")


if __name__ == "__main__":
    main()
