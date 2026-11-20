"""Compare this driver's Fine output with Brother's filter.

    python3 -I tools/finecheck.py            # all cases
    python3 -I tools/finecheck.py --case grey --real

For every case it reports whether the whole job is byte-identical, whether
the printed image is identical (all four planes decoded and compared row by
row), and how many band lines are encoded exactly like Brother's. The line
encoding is a model of Brother's (docs/FORMAT.md, "Fine"), so the image must
always match and the bytes mostly do. Needs Brother's driver and Rosetta 2.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import jobcheck  # noqa: E402
import oracle  # noqa: E402
import rasterwrite as rw  # noqa: E402
from fineimage import FINE, encoded_lines, frame, image  # noqa: E402


def cases():
    rng = random.Random(21)
    yield "dot A6", "A6", [jobcheck.page_dot("A6")], "BRMonoColor=Mono", {}
    yield "random b/w A6", "A6", [jobcheck.page_random_bw("A6")], "BRMonoColor=Mono", {}
    yield "all greys A6", "A6", [jobcheck.page_patches("A6", [(g, g, g) for g in range(256)])], "BRMonoColor=Mono", {}
    yield "random colours in Mono", "A6", [jobcheck.page_patches("A6", [tuple(rng.randrange(256) for _ in range(3)) for _ in range(1500)])], "BRMonoColor=Mono", {}
    yield "gradient A6", "A6", [jobcheck.page_gradient("A6")], "BRMonoColor=Mono", {}
    yield "toner save greys", "A6", [jobcheck.page_patches("A6", [(g, g, g) for g in range(256)])], "BRMonoColor=Mono TonerSaveMode=ON", {}
    yield "A4 random b/w", "A4", [jobcheck.page_random_bw("A4", seed=2, nrows=200)], "BRMonoColor=Mono PageSize=A4", {}
    yield "Legal dot", "Legal", [jobcheck.page_dot("Legal")], "BRMonoColor=Mono PageSize=Legal", {}
    yield "3 pages", "A6", [jobcheck.page_dot("A6"), jobcheck.page_random_bw("A6", seed=3, nrows=50), jobcheck.page_dot("A6")], "BRMonoColor=Mono", {}
    crng = random.Random(8)
    def edge_colours(n):
        out = []
        while len(out) < n:
            ch = crng.randrange(3)
            c = [255 if k == 16 else 16 * k for k in (crng.randrange(17) for _ in range(3))]
            c[ch] = crng.randrange(256)
            if not (c[0] == c[1] == c[2]):
                out.append(tuple(c))
        return out
    yield "colour edge colours", "A6", [jobcheck.page_patches("A6", edge_colours(1100))], "BRMonoColor=FullColor", {}
    yield "colour Vivid, Improve Gray off", "A6", [jobcheck.page_patches("A6", edge_colours(400))], "BRMonoColor=FullColor BRColorMatching=Vivid BRGray=OFF", {}
    yield "colour None", "A6", [jobcheck.page_patches("A6", edge_colours(400))], "BRMonoColor=FullColor BRColorMatching=None", {}
    yield "colour Toner Save", "A6", [jobcheck.page_patches("A6", edge_colours(400))], "BRMonoColor=FullColor TonerSaveMode=ON", {}
    yield "colour greys", "A6", [jobcheck.page_patches("A6", [(g, g, g) for g in range(256)])], "BRMonoColor=FullColor", {}
    yield "colour Auto, random colours", "A6", [jobcheck.page_patches("A6", [tuple(crng.randrange(256) for _ in range(3)) for _ in range(800)])], "BRMonoColor=Auto", {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="only cases whose name contains this")
    ap.add_argument("--real", action="store_true", help="also real documents rendered by macOS")
    ap.add_argument("--keep", help="directory to keep both outputs in")
    a = ap.parse_args()
    if not os.path.exists(jobcheck.OURS):
        print("build the filter first: make", file=sys.stderr)
        return 2
    bad_image = 0
    total_lines = same_lines = 0
    with tempfile.TemporaryDirectory() as td:
        todo = list(cases())
        if a.real and not a.case:
            for size in ("A4", "Letter"):
                todo.append((f"real text document {size}", size, None, "BRMonoColor=Mono", {}))
        for name, size, pages, options, fields in todo:
            if a.case and a.case not in name:
                continue
            path = os.path.join(td, "in.ras")
            if pages is None:
                path = jobcheck.real_document(size, td)
            else:
                rw.write(path, size, pages, fields=fields)
            opts = f"{options} {FINE}"
            b = oracle.run(path, opts, job="t", user="rz")
            o = jobcheck.ours(path, opts, "t", "rz", jobcheck.printlog_epoch(b))
            if a.keep:
                os.makedirs(a.keep, exist_ok=True)
                slug = "".join(ch if ch.isalnum() else "-" for ch in name)
                open(os.path.join(a.keep, slug + ".brother.prn"), "wb").write(b)
                open(os.path.join(a.keep, slug + ".ours.prn"), "wb").write(o)
            frame_ok = frame(b) == frame(o)
            ib, io = image(b), image(o)
            blank = bytes(len(next(iter(ib.values()), b"")))
            img_ok = all(ib.get(k, blank) == io.get(k, blank) for k in set(ib) | set(io)) and frame_ok
            lb, lo = encoded_lines(b), encoded_lines(o)
            n = len(lb)
            same = sum(1 for k, v in lb.items() if lo.get(k) == v)
            total_lines += n
            same_lines += same
            bad_image += not img_ok
            state = "IDENTICAL" if b == o else ("image ok " if img_ok else "IMAGE DIFF")
            pct = f"{100 * same / n:5.1f} %" if n else "   -   "
            print(f"{state:10s} {name:34s} lines encoded alike {pct} ({same}/{n})")
    print(f"\n{'all images identical' if not bad_image else f'{bad_image} case(s) with image differences'}; "
          f"{same_lines}/{total_lines} lines encoded like Brother's "
          f"({100 * same_lines / max(total_lines, 1):.1f} %)")
    return 1 if bad_image else 0


if __name__ == "__main__":
    sys.exit(main())
