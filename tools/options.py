"""Show how each print option changes the job Brother's filter writes.

    python3 -I tools/options.py

For every option value it prints the PJL lines and PCL XL attributes that
differ from the baseline job (image data left out).
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402

# PPD option -> {value: raster header fields the PPD's setpagedevice code sets}
MEDIA_TYPES = {"Plain": 0, "Thin": 1, "Thick": 2, "Thicker": 3, "BOND": 6, "Env": 7,
               "EnvThin": 8, "EnvThick": 9, "Recycled": 5, "Label": 11, "PostCard": 10}


def job_summary(size: str, options: str, fields: dict | None = None, pages: int = 1) -> tuple[list, list]:
    width, _ = rw.page_geometry(size)
    dot = bytearray(rw.WHITE * width)
    dot[0:3] = rw.BLACK

    def source(y: int, w: int, h: int) -> bytes:
        return bytes(dot) if y == 0 else rw.WHITE * w

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        rw.write(path, size, [source] * pages, fields=fields)
        job = pxl.parse(oracle.run(path, options))
    pjl = [ln for ln in job.pjl if "PRINTLOG ITEM = 2" not in ln]  # drop the timestamp
    ops = [(op.name, {k: v for k, v in op.attrs.items()}) for op in job.ops]
    return pjl, ops + [("trailer", {"bytes": job.trailer})]


def diff(base, other) -> list[str]:
    out = []
    bp, bo = base
    op, oo = other
    for ln in op:
        if ln not in bp:
            out.append(f"PJL + {ln.strip()}")
    for ln in bp:
        if ln not in op:
            out.append(f"PJL - {ln.strip()}")
    if len(bo) != len(oo):
        out.append(f"ops {len(bo)} -> {len(oo)}: {[n for n, _ in oo]}")
    for (bn, ba), (on, oa) in zip(bo, oo):
        for k in sorted(set(ba) | set(oa)):
            if ba.get(k) != oa.get(k):
                out.append(f"{on}.{k}: {ba.get(k)!r} -> {oa.get(k)!r}")
    return out


def main() -> None:
    base_opts = "BRMonoColor=Mono"
    base = job_summary("A6", base_opts)
    print("BASELINE (A6, Mono):")
    for ln in base[0]:
        print("   ", ln)
    for name, attrs in base[1]:
        print("   ", name, attrs)
    checks: list[tuple[str, str, str, dict]] = []
    for v in ("FullColor", "Auto"):
        checks.append((f"BRMonoColor={v}", "A6", f"BRMonoColor={v}", {}))
    for opt, vals in {
        "BRResolution": ["600x2400dpi"],
        "TonerSaveMode": ["ON"],
        "BRImproveOutput": ["BRLessPaperCurl", "BRFixIntensity"],
        "BREnhanceBlkPrt": ["ON"],
        "BRGray": ["OFF", "ON"],
        "BRColorMatching": ["Vivid", "None"],
    }.items():
        for v in vals:
            checks.append((f"{opt}={v}", "A6", f"{base_opts} {opt}={v}", {}))
    checks.append(("InputSlot=Manual", "A6", f"{base_opts} InputSlot=Manual",
                   {"ManualFeed": 1, "MediaPosition": 4}))
    for mt, code in MEDIA_TYPES.items():
        if mt != "Plain":
            checks.append((f"MediaType={mt}", "A6", f"{base_opts} MediaType={mt}", {"cupsMediaType": code}))
    for size in rw.PAGE_SIZES:
        if size != "A6":
            checks.append((f"PageSize={size}", size, f"{base_opts} PageSize={size}", {}))
    checks.append(("copies=3", "A6", f"{base_opts} copies=3", {"NumCopies": 3}))
    for label, size, opts, fields in checks:
        try:
            d = diff(base, job_summary(size, opts, fields))
        except Exception as e:  # noqa: BLE001
            d = [f"ERROR {e}"]
        print(f"\n{label}:")
        for line in d:
            print("   ", line)
    d = diff(base, job_summary("A6", base_opts, pages=2))
    print("\n2 pages:")
    for line in d:
        print("   ", line)


if __name__ == "__main__":
    main()
