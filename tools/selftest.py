"""Checks that need neither Brother's driver nor Rosetta: `make check`.

    python3 -I tools/selftest.py [--lines N]

The filter is built with AddressSanitizer and UndefinedBehaviorSanitizer and
without Brother's paths (see the Makefile), and runs here on made-up halftone
tiles and colour tables. That cannot show that the output looks like
Brother's (`make test` does that, with Brother's data), but it shows what
holds for any data:

* black-and-white pages come back pixel for pixel when the output is decoded,
  at 600 dpi and in Fine, Mono and colour;
* every paper size and option gives a job that parses and decodes;
* a Fine job without the Fine data prints in Normal quality;
* damaged print data and damaged data files end in an error message, never
  in a crash or a memory error;
* the C Fine encoder writes the same bytes as the Python reference
  (tools/xl2hb_fine.py), and they decode back to the line.
"""

from __future__ import annotations

import argparse
import os
import random
import signal
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import fineimage  # noqa: E402
import pxl  # noqa: E402
import rasterwrite as rw  # noqa: E402
import roundtrip  # noqa: E402
import xl2hb  # noqa: E402
import xl2hb_fine  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILTER = os.path.join(ROOT, "build", "check", "rastertohl3070cw")
FINE_LINES = os.path.join(ROOT, "build", "check", "fine_lines")
EPOCH = "1767229505"
FINE = "BRResolution=600x2400dpi"
UEL = b"\x1b%-12345X"

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    if not ok:
        failures.append(what)
        print(f"FAIL {what}")


# ---- made-up data ------------------------------------------------------------------

def make_data(path: str, fine: bool = True) -> None:
    """Tiles and tables in Brother's file formats with made-up content.

    A tile's dot is set when the level reaches a random threshold, so level
    255 is solid and level 0 empty, as with any real halftone."""
    os.makedirs(path, exist_ok=True)
    rng = random.Random(3070)
    for ts in ("", "-TS"):
        for plane, (w, h), (fw, fh) in (("k", (80, 80), (12, 12)), ("c", (80, 80), (20, 20)),
                                        ("m", (80, 80), (20, 20)), ("y", (24, 24), (12, 12))):
            thr = [[rng.randint(1, 255) for _ in range(w)] for _ in range(h)]
            body = bytearray()
            for level in range(256):
                for row in thr:
                    bits = bytearray((w + 7) // 8)
                    for x, t in enumerate(row):
                        if t <= level:
                            bits[x >> 3] |= 0x80 >> (x & 7)
                    body += bits
            with open(os.path.join(path, f"0600-{plane}{ts}_cache08.bin"), "wb") as f:
                f.write(b"BRCD0\0" + struct.pack("<HH", w, h) + body)
            if not fine:
                continue
            thr = [[rng.randint(1, 255) for _ in range(fw)] for _ in range(fh)]
            body = bytearray()
            for level in range(256):
                for row in thr:  # one byte per pixel: 0, an even value, or 15
                    body += bytes(0 if level < t else 15 if level == 255 or level - t >= 48
                                  else 2 * (1 + (level - t) // 8) for t in row)
            with open(os.path.join(path, f"capt-{plane}{ts}_cache08.bin"), "wb") as f:
                f.write(b"BRCD1\0" + struct.pack("<HH", fw * 8, fh) + body)
    node = [min(255, 16 * i) for i in range(17)]
    table = bytearray()
    for r in node:
        for g in node:
            for b in node:
                c, m, y = 255 - r, 255 - g, 255 - b
                table += struct.pack("<4H", c, m, y, min(c, m, y) // 2)
    for mode in ("600", "capt") if fine else ("600",):
        for gray in ("on", "off"):
            for match in ("normal", "vivid", "none"):
                with open(os.path.join(path, f"table-{mode}-gray{gray}-{match}.bin"), "wb") as f:
                    f.write(table)


# ---- running the filter ------------------------------------------------------------

def run(data: str, options: str, raster: str | bytes, title: str = "t", user: str = "u"):
    """(exit status, output, messages); the raster is a path, or bytes for stdin."""
    env = {"HL3070CW_DATA": data, "SOURCE_DATE_EPOCH": EPOCH, "PATH": "/usr/bin:/bin"}
    args = [FILTER, "1", user, title, "1", options]
    if isinstance(raster, str):
        res = subprocess.run(args + [raster], capture_output=True, env=env, check=False)
    else:
        res = subprocess.run(args, input=raster, capture_output=True, env=env, check=False)
    err = res.stderr.decode(errors="replace")
    if "Sanitizer" in err or "runtime error" in err or res.returncode not in (0, 1):
        failures.append(f"sanitizer report or crash: {options!r}")
        print(f"FAIL memory error or crash (status {res.returncode}) with {options!r}:\n{err[:2000]}")
    return res.returncode, res.stdout, err


def planes(raw: bytes, fine: bool) -> dict:
    """{(page, plane, row): decoded line}; raises when a band is damaged."""
    if fine:
        return fineimage.image(raw)
    out, page = {}, -1
    for op in pxl.parse(raw).ops:
        if op.name == "BeginImage":
            page += 1
        if op.name == "ReadImage":
            _, _, _, rows = xl2hb.decode_band(op.data)
            for i, row in enumerate(rows):
                out[(page, op.attrs["CommentData"], op.attrs["StartLine"] + i)] = row
    return out


def bw_page(size: str, seed: int, nrows: int = 120, top: int = 30):
    width, _ = rw.page_geometry(size)
    rows = roundtrip.random_rows(random.Random(seed), width, nrows)
    content = {top + i: r for i, r in enumerate(rows)}
    return content, (lambda y, w, h: roundtrip.rgb_row(content[y], w) if y in content else rw.WHITE * w)


def expected_line(bits: bytes, width: int, fine: bool) -> bytes:
    """A black-and-white row as the printer gets it: 1 bit, or 0 / 15 in 4 bits."""
    if not fine:
        return bits + bytes(((width + 31) // 32 * 32) // 8 - len(bits))
    px = [15 if bits[x >> 3] >> (7 - (x & 7)) & 1 else 0 for x in range(width)]
    px += [0] * ((width + 7) // 8 * 8 - width)
    return bytes(px[i] << 4 | px[i + 1] for i in range(0, len(px), 2))


# ---- the checks --------------------------------------------------------------------

def check_round_trips(data: str, td: str) -> None:
    n = 0
    for size in ("A6", "Postcard"):  # 2275 and 2167 pixels wide: neither a multiple of 32
        width, _ = rw.page_geometry(size)
        content, source = bw_page(size, seed=len(size))
        path = os.path.join(td, "bw.ras")
        rw.write(path, size, [source])
        for options in ("BRMonoColor=Mono", "BRMonoColor=Mono TonerSaveMode=ON", "BRMonoColor=FullColor",
                        "BRMonoColor=Auto BRColorMatching=Vivid BRGray=OFF"):
            for fine in (False, True):
                opts = options + (" " + FINE if fine else "")
                rc, out, err = run(data, opts, path)
                check(rc == 0, f"{size} [{opts}]: filter failed: {err.strip()}")
                if rc:
                    continue
                n += 1
                try:
                    got = planes(out, fine)
                except (ValueError, IndexError, xl2hb.FormatError, xl2hb_fine.DecodeError) as e:
                    check(False, f"{size} [{opts}]: output does not decode: {e}")
                    continue
                mono = "BRMonoColor=Mono" in options
                # black is solid K in Mono; with the made-up table solid C, M and Y in colour
                for plane in ((0,) if mono else (1, 2, 3)):
                    rows = {y: line for (_, p, y), line in got.items() if p == plane}
                    want = {y: expected_line(bits, width, fine) for y, bits in content.items() if any(bits)}
                    check(rows == want, f"{size} [{opts}]: plane {plane} is not the page that went in")
    print(f"OK   {n} black-and-white pages decode to what went in")


def check_all_sizes(data: str, td: str) -> None:
    n = 0
    for size in rw.PAGE_SIZES:
        width, height = rw.page_geometry(size)
        rng = random.Random(size)
        noise = bytes(rng.randrange(256) for _ in range(width * 3))

        def source(y, w, h, noise=noise):  # h - 1 can lie past the imageable area and is dropped then
            return noise if y in (0, h // 2, h - 2) else rw.WHITE * w

        path = os.path.join(td, "size.ras")
        rw.write(path, size, [source, source])
        for opts in ("BRMonoColor=Mono InputSlot=Manual MediaType=Thick", "BRMonoColor=FullColor " + FINE,
                     "BRMonoColor=Mono BRImproveOutput=BRFixIntensity " + FINE):
            rc, out, err = run(data, opts, path)
            check(rc == 0, f"{size} [{opts}]: filter failed: {err.strip()}")
            if rc:
                continue
            n += 1
            try:
                job = pxl.parse(out)
                got = planes(out, FINE in opts)
            except (ValueError, IndexError, xl2hb.FormatError, xl2hb_fine.DecodeError) as e:
                check(False, f"{size} [{opts}]: output does not decode: {e}")
                continue
            names = [op.name for op in job.ops]
            check(names.count("BeginPage") == 2 and names.count("EndPage") == 2, f"{size} [{opts}]: not 2 pages")
            check({y for (_, _, y) in got} == {0, height // 2, height - 2}, f"{size} [{opts}]: wrong rows printed")
            check(out.endswith(UEL), f"{size} [{opts}]: job not closed")
    print(f"OK   {n} jobs over all {len(rw.PAGE_SIZES)} paper sizes parse and decode")


def grey_raster(size: str, rows: dict[int, bytes]) -> bytes:
    """An 8-bit grey raster (sGray) of one page; rows maps y to grey bytes."""
    hdr = bytearray(rw.header(size))
    width, height = struct.unpack_from("<II", hdr, 372)
    struct.pack_into("<IIII", hdr, 384, 8, 8, width, 0)
    struct.pack_into("<I", hdr, 400, 18)  # cupsColorSpace = sGray
    struct.pack_into("<I", hdr, 420, 1)
    return b"3SaR" + bytes(hdr) + b"".join(rows.get(y, b"\xff" * width) for y in range(height))


def check_grey_input(data: str, td: str) -> None:
    size = "A6"
    width, height = rw.page_geometry(size)
    rng = random.Random(8)
    grey = {y: bytes(rng.randrange(256) for _ in range(width)) for y in range(10, 60)}
    path = os.path.join(td, "rgb.ras")
    rw.write(path, size, [lambda y, w, h: bytes(v for g in grey[y] for v in (g, g, g)) if y in grey else rw.WHITE * w])
    for opts in ("BRMonoColor=Mono", "BRMonoColor=FullColor " + FINE):
        a = run(data, opts, path)
        b = run(data, opts, grey_raster(size, grey))
        check(a[0] == 0 and b[0] == 0 and a[1] == b[1], f"grey raster [{opts}]: differs from the same page in RGB")
    print("OK   a grey raster prints like the same page in RGB")


def check_fine_fallback(td: str) -> None:
    data = os.path.join(td, "data-no-fine")
    make_data(data, fine=False)
    _, source = bw_page("A6", seed=5)
    path = os.path.join(td, "fallback.ras")
    rw.write(path, "A6", [source])
    for options in ("BRMonoColor=Mono", "BRMonoColor=FullColor"):
        normal = run(data, options, path)
        fine = run(data, options + " " + FINE, path)
        check(fine[0] == 0 and fine[1] == normal[1], f"Fine without Fine data [{options}]: not the Normal job")
        check("WARNING:" in fine[2] and "Fine" in fine[2], f"Fine without Fine data [{options}]: no warning")
        check("WARNING:" not in normal[2], f"Normal job [{options}]: unexpected warning")
    print("OK   a Fine job without the Fine data prints in Normal quality, with a warning")


def check_bad_input(data: str, td: str) -> None:
    good = bytearray(b"3SaR" + rw.header("A6"))
    width, height = struct.unpack_from("<II", good, 4 + 372)

    def patched(*fields: tuple[int, int], rows: int = 4) -> bytes:
        hdr = bytearray(good)
        for off, value in fields:
            struct.pack_into("<I", hdr, 4 + off, value)
        return bytes(hdr) + b"\xff" * (width * 3 * rows)

    cases = {
        "empty input": b"",
        "not a raster": b"%PDF-1.4 this is not a raster\n" * 200,
        "header cut short": bytes(good[:900]),
        "pixels cut short": patched(),
        "zero width": patched((372, 0), (392, 0)),
        "zero height": patched((376, 0)),
        "wider than the printer": patched((372, 5201), (392, 5201 * 3)),
        "longer than the printer": patched((376, 9601)),
        "huge page": patched((372, 0xFFFFFFF0), (376, 0xFFFFFFF0), (392, 0xFFFFFFF0)),
        "bytes per line not matching the width": patched((392, width)),
        "300 dpi": patched((276, 300), (280, 300)),
        "16 bits per colour": patched((384, 16), (388, 48), (392, width * 6)),
        "CMYK": patched((388, 32), (392, width * 4), (400, 6)),
        "banded colour order": patched((396, 1)),
    }
    for name, raster in cases.items():
        for opts in ("BRMonoColor=Mono", "BRMonoColor=FullColor " + FINE):
            rc, out, err = run(data, opts, raster)
            check(rc == 1 and "ERROR:" in err, f"{name} [{opts}]: status {rc}, want an error message")
            check(not out or out.endswith(UEL), f"{name} [{opts}]: output left open")
    print(f"OK   {len(cases)} kinds of damaged print data end in an error message")

    # damaged data files
    _, source = bw_page("A6", seed=6, nrows=10)
    path = os.path.join(td, "ok.ras")
    rw.write(path, "A6", [source])
    damage = {
        "wrong signature": lambda d: b"XXXX" + d[4:],
        "cut short": lambda d: d[: len(d) // 2],
        "empty": lambda d: b"",
        "huge tile": lambda d: d[:6] + struct.pack("<HH", 60000, 60000) + d[10:],
        "zero size": lambda d: d[:6] + struct.pack("<HH", 0, 0) + d[10:],
        "the other resolution's format": lambda d: d[:4] + (b"1" if d[4:5] == b"0" else b"0") + d[5:],
    }
    n = 0
    for name, hurt in damage.items():
        for victim, opts in (("0600-k_cache08.bin", "BRMonoColor=Mono"), ("capt-m_cache08.bin", "BRMonoColor=FullColor " + FINE),
                             ("table-600-grayon-normal.bin", "BRMonoColor=FullColor")):
            if victim.startswith("table") and name not in ("cut short", "empty"):
                continue  # a table has no header to damage
            bad = os.path.join(td, "data-bad")
            make_data(bad)
            with open(os.path.join(bad, victim), "rb") as f:
                d = f.read()
            with open(os.path.join(bad, victim), "wb") as f:
                f.write(hurt(d))
            rc, out, err = run(bad, opts, path)
            check(rc == 1 and "ERROR:" in err and not out, f"{victim} {name}: status {rc}, want an error and no output")
            n += 1
    print(f"OK   {n} damaged data files end in an error message")


def check_job_text(data: str, td: str) -> None:
    _, source = bw_page("A6", seed=7, nrows=4)
    path = os.path.join(td, "text.ras")
    rw.write(path, "A6", [source])
    for title in ('say "hi"', "line\nbreak\r\x1b%-12345X@PJL DEFAULT COPIES=99", "ü" * 200, "x" * 5000, "", "\x7f\x01\xff"):
        rc, out, err = run(data, "BRMonoColor=Mono", path, title=title, user=title)
        check(rc == 0, f"title {title[:20]!r}: filter failed: {err.strip()}")
        if rc:
            continue
        head = out[: out.index(b") BROTHER XL2HB")]
        lines = head.split(b"\n")[:-1]
        check(lines[0] == UEL + b"@PJL " and all(ln.startswith(b"@PJL ") for ln in lines[1:]),
              f"title {title[:20]!r}: something other than PJL commands in the job header")
        check(not any(c < 0x20 or c == 0x7F for ln in lines[1:] for c in ln), f"title {title[:20]!r}: control character")
        names = [ln for ln in lines if ln.startswith(b"@PJL SET JOBNAME=")]
        check(len(names) == 1 and len(names[0]) <= len(b'@PJL SET JOBNAME=""') + 80 and names[0].count(b'"') == 2,
              f"title {title[:20]!r}: job name not one quoted string of at most 80 bytes")
        check(sum(ln.startswith(b"@PJL ENTER LANGUAGE") for ln in lines) == 1, f"title {title[:20]!r}: PJL injected")
    print("OK   job title and user name cannot break out of the job header")


def check_cancel(data: str) -> None:
    """Cancelling: cupsd sends SIGTERM and the raster stops; the job must be closed properly."""
    hdr = b"3SaR" + rw.header("A6")
    width, _ = rw.page_geometry("A6")
    env = {"HL3070CW_DATA": data, "SOURCE_DATE_EPOCH": EPOCH, "PATH": "/usr/bin:/bin"}
    p = subprocess.Popen([FILTER, "1", "u", "t", "1", "BRMonoColor=Mono " + FINE], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    p.stdin.write(hdr + b"\x00" * (width * 3 * 400))
    p.stdin.flush()
    while not p.stderr.readline().startswith(b"INFO: Printing"):  # running, signal handler in place
        if p.poll() is not None:
            break
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=60)
    text = err.decode(errors="replace")
    check(p.returncode in (0, 1) and "Sanitizer" not in text, f"cancel: status {p.returncode}: {text[:300]}")
    check(out.endswith(UEL) and b"@PJL EOJ" in out[-200:], "cancel: job not closed")
    check("ERROR:" not in text, f"cancel: reported as an error: {text.strip()[:200]}")
    try:
        fineimage.image(out)
    except (ValueError, IndexError, xl2hb_fine.DecodeError) as e:
        check(False, f"cancel: output does not decode: {e}")
    print("OK   a cancelled job is closed properly")


def check_usage() -> None:
    env = {"PATH": "/usr/bin:/bin"}
    res = subprocess.run([FILTER, "--version"], capture_output=True, env=env, check=False)
    check(res.returncode == 0 and res.stdout.startswith(b"rastertohl3070cw "), "--version")
    res = subprocess.run([FILTER], capture_output=True, env=env, check=False)
    check(res.returncode == 1 and b"Usage:" in res.stderr, "no arguments: want the usage text")
    res = subprocess.run([FILTER, "1", "u", "t", "1", "", "/nonexistent.ras"], capture_output=True, env=env, check=False)
    check(res.returncode == 1 and b"ERROR:" in res.stderr, "missing file: want an error")
    with tempfile.TemporaryDirectory() as td:
        # Brother's driver is "not installed" in this build: copying its data must fail cleanly
        res = subprocess.run([FILTER, "--extract-brother-data", os.path.join(td, "data")], capture_output=True, env=env,
                             check=False)
        check(res.returncode == 1 and b"Sanitizer" not in res.stderr, "--extract-brother-data without Brother's driver")
    print("OK   command line")


def even(v: int) -> int:
    return v - 1 if v & 1 and v != 15 else v


def check_fine_encoder(td: str, count: int) -> None:
    total = 0
    for odd in (0, 1):
        path = os.path.join(td, f"lines{odd}.bin")
        res = subprocess.run([FINE_LINES, str(count), str(odd), path], capture_output=True, check=False)
        check(res.returncode == 0, f"fine_lines failed: {res.stderr.decode(errors='replace')[:500]}")
        if res.returncode:
            return
        with open(path, "rb") as f:
            d = f.read()
        i = bad = 0
        while i < len(d):
            (n,) = struct.unpack_from("<I", d, i)
            line = d[i + 4 : i + 4 + n]
            i += 4 + n
            (m,) = struct.unpack_from("<I", d, i)
            enc = d[i + 4 : i + 4 + m]
            i += 4 + m
            total += 1
            # Odd values (Brother's tiles make none) are rounded down. The C encoder does that
            # token by token, so such a line must decode, but need not match the reference.
            want = bytes(even(b >> 4) << 4 | even(b & 15) for b in line) if odd else line
            try:
                ok = xl2hb_fine.decode_line(enc, n) == want and (odd or xl2hb_fine.encode_line(line) == enc)
            except xl2hb_fine.DecodeError:
                ok = False
            bad += not ok
            check(m <= n + 16, f"Fine line of {n} bytes grew to {m}")
        check(bad == 0, f"Fine encoder: {bad} lines differ from the Python reference or do not decode (odd={odd})")
    print(f"OK   {total} random Fine lines decode back; the C encoder writes what the Python reference writes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=1500, help="random Fine lines per run of the encoder check")
    a = ap.parse_args()
    for exe in (FILTER, FINE_LINES):
        if not os.path.exists(exe):
            print(f"{exe} missing: run `make check`", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory() as td:
        data = os.path.join(td, "data")
        make_data(data)
        check_usage()
        check_round_trips(data, td)
        check_all_sizes(data, td)
        check_grey_input(data, td)
        check_fine_fallback(td)
        check_bad_input(data, td)
        check_job_text(data, td)
        check_cancel(data)
        check_fine_encoder(td, a.lines)
    if failures:
        print(f"\n{len(failures)} checks failed")
        return 1
    print("\nAll checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
