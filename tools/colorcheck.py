"""Compare this driver's colour output with Brother's filter.

    python3 -I tools/colorcheck.py

Pages whose colours lie on the edges of Brother's colour-table cells must
come out byte-identical. For other colours the interpolation is fitted, so
the check reports how many dots differ per plane.
"""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import colorplanes as cp  # noqa: E402
import jobcheck  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402


def node(k: int) -> int:
    return 255 if k == 16 else 16 * k


def edge_colours(rng: random.Random, n: int) -> list[tuple[int, int, int]]:
    out = []
    while len(out) < n:
        ch = rng.randrange(3)
        c = [node(rng.randrange(17)) for _ in range(3)]
        c[ch] = rng.randrange(256)
        if not (c[0] == c[1] == c[2]):
            out.append(tuple(c))
    return out


def plane_diff(a: bytes, b: bytes) -> list[int]:
    pa, pb = cp.decode_planes(pxl.parse(a)), cp.decode_planes(pxl.parse(b))
    diffs = []
    for p in range(4):
        n = 0
        for y in set(pa[p]) | set(pb[p]):
            ra, rb = pa[p].get(y, b""), pb[p].get(y, b"")
            m = max(len(ra), len(rb))
            ra, rb = ra.ljust(m, b"\0"), rb.ljust(m, b"\0")
            n += sum(bin(x ^ z).count("1") for x, z in zip(ra, rb))
        diffs.append(n)
    return diffs


def cases():
    rng = random.Random(8)
    W, H = rw.page_geometry("A6")
    yield "edge colours", jobcheck.page_patches("A6", edge_colours(rng, 1100)), "BRMonoColor=FullColor", True
    yield "edge colours, Vivid", jobcheck.page_patches("A6", edge_colours(rng, 600)), "BRMonoColor=FullColor BRColorMatching=Vivid", True
    yield "edge colours, None, Improve Gray off", jobcheck.page_patches("A6", edge_colours(rng, 600)), "BRMonoColor=FullColor BRColorMatching=None BRGray=OFF", True
    yield "edge colours, Toner Save", jobcheck.page_patches("A6", edge_colours(rng, 600)), "BRMonoColor=FullColor TonerSaveMode=ON", True
    yield "edge colours, Auto", jobcheck.page_patches("A6", edge_colours(rng, 600)), "BRMonoColor=Auto", True
    yield "black text-like page", jobcheck.page_random_bw("A6", seed=4), "BRMonoColor=FullColor", True
    yield "greys", jobcheck.page_patches("A6", [(g, g, g) for g in range(256)]), "BRMonoColor=FullColor", False
    yield "random colours", jobcheck.page_patches("A6", [tuple(rng.randrange(256) for _ in range(3)) for _ in range(1500)]), "BRMonoColor=FullColor", False
    yield "gradient", jobcheck.page_gradient("A6"), "BRMonoColor=FullColor", False


def main() -> int:
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        for name, page, options, exact in cases():
            rw.write(path, "A6", [page])
            b = jobcheck.brother_common(path, options, "t", "rz")
            o = jobcheck.ours(path, options, "t", "rz", jobcheck.printlog_epoch(b))
            same = b == o
            if same:
                print(f"OK    {name}: byte-identical ({len(b)} bytes)")
                continue
            d = plane_diff(b, o)
            total = sum(d)
            if exact:
                failed += 1
                print(f"FAIL  {name}: differs; dots differing K/C/M/Y {d}")
                print("      " + jobcheck.first_difference(b, o))
            else:
                ink = sum(sum(bin(x).count('1') for r in pl.values() for x in r) for pl in cp.decode_planes(pxl.parse(b)).values())
                print(f"INFO  {name}: dots differing K/C/M/Y {d} = {total} of {ink} dots ({100 * total / max(ink, 1):.2f} %)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
