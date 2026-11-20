"""Feed a synthetic page through Brother's filter and show what comes out.

    python3 -I tools/probe.py 'pixels=[(0,0)]'
    python3 -I tools/probe.py 'rows={10: bits}' --options BRMonoColor=Mono

The spec is a Python dict literal with optional keys:
  pixels: list of (x, y) black pixels
  rects:  list of (x, y, w, h) black rectangles
  rgb:    list of (x, y, w, h, (r, g, b)) coloured rectangles
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402


def page_from_spec(spec: dict):
    paint: dict[int, list[tuple[int, int, bytes]]] = {}
    for x, y in spec.get("pixels", []):
        paint.setdefault(y, []).append((x, 1, rw.BLACK))
    for x, y, w, h in spec.get("rects", []):
        for yy in range(y, y + h):
            paint.setdefault(yy, []).append((x, w, rw.BLACK))
    for x, y, w, h, rgb in spec.get("rgb", []):
        for yy in range(y, y + h):
            paint.setdefault(yy, []).append((x, w, bytes(rgb)))

    def source(y: int, width: int, height: int) -> bytes:
        if y not in paint:
            return rw.WHITE * width
        row = bytearray(rw.WHITE * width)
        for x, w, ink in paint[y]:
            row[3 * x : 3 * (x + w)] = ink * w
        return bytes(row)

    return source


def run_spec(spec: dict, options: str = "BRMonoColor=Mono", size: str = "A6") -> pxl.Job:
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        rw.write(path, size, [page_from_spec(spec)])
        return pxl.parse(oracle.run(path, options))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--options", default="BRMonoColor=Mono")
    ap.add_argument("--size", default="A6")
    ap.add_argument("--bytes", type=int, default=64)
    a = ap.parse_args()
    job = run_spec(ast.literal_eval(a.spec), a.options, a.size)
    for op in job.ops:
        if op.name in ("BeginPage", "BeginImage"):
            print(op.name, op.attrs)
    for start, height, mode, data in job.images():
        print(f"ReadImage start={start} height={height} mode={mode} len={len(data)}")
        print("   ", data[: a.bytes].hex(" "))


if __name__ == "__main__":
    main()
