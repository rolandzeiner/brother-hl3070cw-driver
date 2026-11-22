"""Comparison of this driver's filter with Brother's filter.

    python3 -I tools/jobcheck.py            # all cases
    python3 -I tools/jobcheck.py --case grey --keep

Brother's filter output varies from run to run in two ways that come from
uninitialised memory in it: about one job in five uses compression method 4
throughout, and about one in twenty carries an extra "@PJL SET MANUALDPX=ON".
Both variants print the same. The check reruns Brother's filter until it
produces the common variant, then compares whole jobs. Brother's PRINTLOG
timestamp is passed to this filter through SOURCE_DATE_EPOCH.

Fine jobs (BRResolution=600x2400dpi) are compared by what they print: the job
frame and every decoded row must match; the line encoding may differ (see
tools/fineimage.py). Brother's Fine output does not vary between runs.
"""

from __future__ import annotations

import argparse
import calendar
import os
import random
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(__file__))
import oracle  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402
import roundtrip  # noqa: E402
import fineimage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OURS = os.path.join(ROOT, "build", "rastertohl3070cw")


SETTINGS = "com.brother.print.PrintSettings."


def brother_options(options: str, title: str, user: str) -> str:
    """Options as Brother's filter needs them for the same job.

    Brother's filter does not read the job PIN (job-password): its own print
    dialog extension passes Secure Print as settings of its own, with the PIN
    and the job and user name as the dialog shows them (arrays of character
    codes). Without the names it crashes."""
    out, pin = [], None
    for opt in options.split():
        if opt.startswith("job-password="):
            pin = opt.split("=", 1)[1]
        else:
            out.append(opt)
    if pin is not None:
        def array(name: str, text: str) -> list[str]:
            return [f"{SETTINGS}{name}cnt={len(text)}"] + [f"{SETTINGS}{name}..a.{i}..n.={ord(c)}"
                                                         for i, c in enumerate(text)]
        out += [f"{SETTINGS}secureprint=ON", f"{SETTINGS}password={pin}"]
        out += array("username", user) + array("jobname", title)
    return " ".join(out)


def brother_common(raster: str, options: str, title: str, user: str, tries: int = 120,
                   fake_time: int | None = None, use_ppd: str | None = None) -> bytes:
    ppd = use_ppd or (oracle.BROTHER_OWN_PPD if "job-password=" in options else None)
    options = brother_options(options, title, user)
    for attempt in range(tries):
        # a new stack layout each time: in some environments every run gives the rare variant
        out = oracle.run(raster, options, job=title, user=user, fake_time=fake_time, ppd=ppd, shift=attempt * 37)
        if b"MANUALDPX" in out:
            continue
        job = pxl.parse(out)
        bi = [op for op in job.ops if op.name == "BeginImage"]
        if bi and bi[0].attrs["CommentData"][7::5][0] not in (0x020C, 0):  # 0: Fine
            continue
        return out
    raise RuntimeError("Brother's filter never produced the common variant")


def printlog_epoch(out: bytes) -> int:
    m = re.search(rb"PRINTLOG ITEM = 2,\w+,(\d+ \w+ \d+ \d+:\d+:\d+)", out)
    if not m:
        raise ValueError("no PRINTLOG time")
    return calendar.timegm(time.strptime(m.group(1).decode(), "%d %b %Y %H:%M:%S"))


def ours(raster: str, options: str, title: str, user: str, epoch: int) -> bytes:
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
    res = subprocess.run([OURS, "1", user, title, "1", options, raster], capture_output=True, env=env, check=False)
    if res.returncode:
        raise RuntimeError(f"our filter failed: {res.stderr.decode(errors='replace')}")
    return res.stdout


def first_difference(a: bytes, b: bytes) -> str:
    n = min(len(a), len(b))
    i = next((k for k in range(n) if a[k] != b[k]), n)
    return (f"lengths brother {len(a)} / ours {len(b)}, first difference at byte {i}\n"
            f"      brother: {a[max(0, i - 16):i + 24].hex(' ')}\n"
            f"      ours:    {b[max(0, i - 16):i + 24].hex(' ')}")


# ---- test pages -----------------------------------------------------------------

def page_dot(size):
    w, _ = rw.page_geometry(size)
    row = bytearray(rw.WHITE * w)
    row[0:3] = rw.BLACK
    return lambda y, ww, h: bytes(row) if y == 0 else rw.WHITE * ww


def page_random_bw(size, seed=1, nrows=300):
    rng = random.Random(seed)
    w, _ = rw.page_geometry(size)
    rows = roundtrip.random_rows(rng, w, nrows)
    top = 40
    return lambda y, ww, h: roundtrip.rgb_row(rows[y - top], ww) if top <= y < top + nrows else rw.WHITE * ww


def page_patches(size, colours):
    w, hgt = rw.page_geometry(size)
    t = 40  # deliberately not the tile size, so patches straddle tiles
    cols = w // t

    def src(y, ww, h):
        r = y // t
        parts = []
        for c in range(cols):
            i = r * cols + c
            parts.append(bytes(colours[i]) * t if i < len(colours) else rw.WHITE * t)
        row = b"".join(parts)
        return row + rw.WHITE * (ww - len(row) // 3)

    return src


def page_gradient(size):
    def src(y, ww, h):
        return b"".join(bytes(((x * 255) // ww, (y * 255) // h, ((x + y) * 255) // (ww + h))) for x in range(ww))
    return src


def real_document(size: str, td: str) -> str:
    """Render a real text document through macOS's own PDF-to-raster filter."""
    txt = os.path.join(td, "doc.txt")
    with open(txt, "w") as f:
        for i in range(120):
            f.write(f"Line {i:3d}: The quick brown fox jumps over the lazy dog. äöü ß € 0123456789\n")
    ras = os.path.join(td, "doc.ras")
    with open(ras, "wb") as f:
        subprocess.run(["cupsfilter", "-p", oracle.brother_ppd(), "-m", "application/vnd.cups-raster",
                        "-o", f"PageSize={size}", "-o", "BRMonoColor=Mono", txt], stdout=f,
                       stderr=subprocess.DEVNULL, check=True)
    return ras


def cases():
    rng = random.Random(5)
    yield "dot A6", "A6", [page_dot("A6")], "BRMonoColor=Mono", {}
    yield "random b/w A6", "A6", [page_random_bw("A6")], "BRMonoColor=Mono", {}
    yield "random b/w A4", "A4", [page_random_bw("A4", seed=2, nrows=200)], "BRMonoColor=Mono", {}
    yield "all greys A6", "A6", [page_patches("A6", [(g, g, g) for g in range(256)])], "BRMonoColor=Mono", {}
    yield "random colours A6", "A6", [page_patches("A6", [tuple(rng.randrange(256) for _ in range(3)) for _ in range(1500)])], "BRMonoColor=Mono", {}
    yield "gradient A6", "A6", [page_gradient("A6")], "BRMonoColor=Mono", {}
    yield "toner save greys", "A6", [page_patches("A6", [(g, g, g) for g in range(256)])], "BRMonoColor=Mono TonerSaveMode=ON", {}
    yield "less paper curl", "A6", [page_dot("A6")], "BRMonoColor=Mono BRImproveOutput=BRLessPaperCurl", {}
    yield "fix intensity", "A6", [page_dot("A6")], "BRMonoColor=Mono BRImproveOutput=BRFixIntensity", {}
    yield "manual feed", "A6", [page_dot("A6")], "BRMonoColor=Mono InputSlot=Manual", {"ManualFeed": 1, "MediaPosition": 4}
    for mt, code in (("Thin", 1), ("Thicker", 3), ("Env", 7), ("Label", 11)):
        yield f"media {mt}", "A6", [page_dot("A6")], f"BRMonoColor=Mono MediaType={mt}", {"cupsMediaType": code}
    for size in rw.PAGE_SIZES:
        yield f"size {size}", size, [page_dot(size)], f"BRMonoColor=Mono PageSize={size}", {}
    yield "3 pages", "A6", [page_dot("A6"), page_random_bw("A6", seed=3, nrows=50), page_dot("A6")], "BRMonoColor=Mono", {}
    yield "title and user", "A6", [page_dot("A6")], "BRMonoColor=Mono", {"_title": "Quarterly report 2026 (final).pdf", "_user": "roland"}
    # colour: colours on the edges of Brother's colour-table cells, where the
    # fitted interpolation is exact (see tools/colorcheck.py for the rest)
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

    yield "colour edge colours", "A6", [page_patches("A6", edge_colours(1100))], "BRMonoColor=FullColor", {}
    yield "colour Vivid", "A6", [page_patches("A6", edge_colours(400))], "BRMonoColor=FullColor BRColorMatching=Vivid", {}
    yield "colour None, Improve Gray off", "A6", [page_patches("A6", edge_colours(400))], "BRMonoColor=FullColor BRColorMatching=None BRGray=OFF", {}
    yield "colour Toner Save", "A6", [page_patches("A6", edge_colours(400))], "BRMonoColor=FullColor TonerSaveMode=ON", {}
    yield "colour Auto", "A6", [page_patches("A6", edge_colours(400))], "BRMonoColor=Auto", {}
    yield "colour greys", "A6", [page_patches("A6", [(g, g, g) for g in range(256)])], "BRMonoColor=FullColor", {}
    yield "colour black content", "A6", [page_random_bw("A6", seed=4)], "BRMonoColor=FullColor", {}
    yield "colour 2 pages A4", "A4", [page_patches("A4", edge_colours(300)), page_random_bw("A4", seed=5, nrows=80)], "BRMonoColor=FullColor PageSize=A4", {}
    # Fine (2400 dpi class): compared by image, see same_output()
    F = fineimage.FINE
    yield "fine dot", "A6", [page_dot("A6")], f"BRMonoColor=Mono {F}", {}
    yield "fine random b/w A6", "A6", [page_random_bw("A6", seed=6)], f"BRMonoColor=Mono {F}", {}
    yield "fine all greys", "A6", [page_patches("A6", [(g, g, g) for g in range(256)])], f"BRMonoColor=Mono {F}", {}
    yield "fine random colours in Mono", "A6", [page_patches("A6", [tuple(rng.randrange(256) for _ in range(3)) for _ in range(1500)])], f"BRMonoColor=Mono {F}", {}
    yield "fine toner save greys", "A6", [page_patches("A6", [(g, g, g) for g in range(256)])], f"BRMonoColor=Mono TonerSaveMode=ON {F}", {}
    yield "fine 2 pages Letter", "Letter", [page_dot("Letter"), page_random_bw("Letter", seed=7, nrows=120)], f"BRMonoColor=Mono PageSize=Letter {F}", {}
    yield "fine colour edge colours", "A6", [page_patches("A6", edge_colours(800))], f"BRMonoColor=FullColor {F}", {}
    yield "fine colour Vivid, Improve Gray off", "A6", [page_patches("A6", edge_colours(400))], f"BRMonoColor=FullColor BRColorMatching=Vivid BRGray=OFF {F}", {}
    yield "fine colour None, Toner Save", "A6", [page_patches("A6", edge_colours(400))], f"BRMonoColor=FullColor BRColorMatching=None TonerSaveMode=ON {F}", {}
    yield "fine colour Auto, greys", "A6", [page_patches("A6", [(g, g, g) for g in range(256)])], f"BRMonoColor=Auto {F}", {}
    # added in 0.4.1, after all others so the inputs above stay the same
    yield "enhance black colour", "A6", [page_patches("A6", edge_colours(300))], "BRMonoColor=FullColor BREnhanceBlkPrt=ON", {}
    yield "enhance black Auto, Improve Gray off", "A6", [page_patches("A6", edge_colours(200))], "BRMonoColor=Auto BREnhanceBlkPrt=ON BRGray=OFF", {}
    yield "enhance black in Mono", "A6", [page_dot("A6")], "BRMonoColor=Mono BREnhanceBlkPrt=ON", {}
    yield "fine colour enhance black", "A6", [page_patches("A6", edge_colours(200))], f"BRMonoColor=FullColor BREnhanceBlkPrt=ON {F}", {}
    yield "secure print Mono", "A6", [page_dot("A6")], "BRMonoColor=Mono job-password=1234", {"_title": "Payslips November.pdf", "_user": "roland"}
    yield "secure print colour, enhance black", "A6", [page_patches("A6", edge_colours(200))], "BRMonoColor=Auto BREnhanceBlkPrt=ON job-password=0042", {}
    yield "secure print Fine", "A6", [page_random_bw("A6", seed=9, nrows=60)], f"BRMonoColor=Mono job-password=9870 {F}", {}
    # added for 0.5.2: custom paper
    for size in rw.CUSTOM_SIZES:
        yield f"custom paper {size[7:]}", size, [page_dot(size)], f"BRMonoColor=Mono PageSize={size}", {}


def same_output(options: str, brother: bytes, ours: bytes) -> tuple[bool, str]:
    """(match, how): bytes for 600 dpi, the printed image for Fine."""
    if brother == ours:
        return True, "bytes"
    if fineimage.is_fine(options):
        return fineimage.digest(brother) == fineimage.digest(ours), "image"
    return False, "bytes"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="only cases whose name contains this")
    ap.add_argument("--keep", action="store_true", help="keep both outputs in the scratch dir")
    ap.add_argument("--real", action="store_true", help="also check real documents rendered by macOS")
    a = ap.parse_args()
    if not os.path.exists(OURS):
        print("build the filter first: make", file=sys.stderr)
        return 2
    failed = 0
    total = 0
    with tempfile.TemporaryDirectory() as td:
        todo = list(cases())
        for name, size, pages, options, fields in todo:
            if a.case and a.case not in name:
                continue
            total += 1
            fields = dict(fields)
            title = fields.pop("_title", "t")
            user = fields.pop("_user", "rz")
            path = os.path.join(td, "in.ras")
            rw.write(path, size, pages, fields=fields)
            b = brother_common(path, options, title, user)
            o = ours(path, options, title, user, printlog_epoch(b))
            ok, how = same_output(options, b, o)
            failed += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {name}  ({len(b)} bytes, same {how})")
            if not ok:
                print("     " + first_difference(b, o))
            if a.keep:
                open(os.path.join(td, f"{name}.brother.prn"), "wb").write(b)
                open(os.path.join(td, f"{name}.ours.prn"), "wb").write(o)
        if a.real and not a.case:
            for size, opts in (("A4", "BRMonoColor=Mono"), ("Letter", "BRMonoColor=Mono"), ("A5", "BRMonoColor=Mono"),
                               ("A4", f"BRMonoColor=Mono {fineimage.FINE}")):
                total += 1
                path = real_document(size, td)
                b = brother_common(path, opts, "doc.txt", "rz")
                o = ours(path, opts, "doc.txt", "rz", printlog_epoch(b))
                ok, how = same_output(opts, b, o)
                failed += not ok
                fine = " Fine" if fineimage.is_fine(opts) else ""
                print(f"{'OK  ' if ok else 'FAIL'} real text document {size}{fine}  ({len(b)} bytes, same {how})")
                if not ok:
                    print("     " + first_difference(b, o))
    print(f"\n{total - failed} of {total} jobs identical (Fine: same image)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
