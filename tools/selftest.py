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
* Secure Print holds the job with its PIN, a PIN the printer cannot take
  stops the job instead of printing it openly, and the PIN appears nowhere
  but in its PJL line; Enhance Black Printing reaches colour jobs only;
* damaged print data and damaged data files end in an error message, never
  in a crash or a memory error, and so does a paper size the printer does not
  take and printer data that cannot be written;
* --check-data says whether the copy of Brother's data is complete;
* copying Brother's data out of a package follows no symlink, takes no path
  from the command line and, as root (run this file with sudo), nothing that
  another user owns or everyone may write to;
* a cancelled job is never an error, starts no page it has no line of, and
  what it has started is sent whole;
* the C Fine encoder writes the same bytes as the Python reference
  (tools/xl2hb_fine.py), and they decode back to the line.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import random
import resource
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

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
        # a whole page each, so that only the paper size is wrong
        **{f"paper {w} x {h} pt": patched((352, w), (356, h), rows=height)
           for w, h in ((0, 0), (10000, 10000), (65536, 65536), (0xFFFFFFFF, 0xFFFFFFFF), (297, 65536 + 420),
                        (197, 500), (613, 500), (400, 327), (400, 1153))},
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


def check_custom_sizes(data: str) -> None:
    hdr = bytearray(b"3SaR" + rw.header("A6"))
    width, height = struct.unpack_from("<II", hdr, 4 + 372)
    body = b"\xff" * (width * 3 * height)
    for size in ((198, 328), (612, 1152), (283, 709)):
        struct.pack_into("<II", hdr, 4 + 352, *size)
        rc, out, err = run(data, "BRMonoColor=Mono", bytes(hdr) + body)
        check(rc == 0, f"custom paper {size}: refused: {err.strip()[:200]}")
        if rc:
            continue
        page = next(op for op in pxl.parse(out).ops if op.name == "BeginPage")
        want = tuple(int(v * 254 / 72 + 0.5) for v in size)
        check(page.attrs.get("CustomMediaSize") == want, f"custom paper {size}: sent as {page.attrs}")
    print("OK   custom paper sizes in the printer's range print")


def check_write_failure(data: str, td: str) -> None:
    """Printer data that cannot be written is an error with a message."""
    _, source = bw_page("A6", seed=11, nrows=600)
    path = os.path.join(td, "write.ras")
    rw.write(path, "A6", [source])
    env = {"HL3070CW_DATA": data, "SOURCE_DATE_EPOCH": EPOCH, "PATH": "/usr/bin:/bin"}

    def small_file() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))

    for opts in ("BRMonoColor=Mono", "BRMonoColor=FullColor " + FINE):
        args = [FILTER, "1", "u", "t", "1", opts, path]
        rd, wr = os.pipe()
        os.close(rd)
        closed = subprocess.run(args, stdout=wr, stderr=subprocess.PIPE, env=env, check=False)
        os.close(wr)
        with tempfile.TemporaryFile() as out:
            full = subprocess.run(args, stdout=out, stderr=subprocess.PIPE, env=env, check=False, preexec_fn=small_file)
        for what, res in (("closed pipe", closed), ("file size limit", full)):
            err = res.stderr.decode(errors="replace")
            check(res.returncode == 1 and err.count("ERROR: cannot write") == 1,
                  f"{what} [{opts}]: status {res.returncode}, want one error: {err.strip()[:200]}")
    print("OK   printer data that cannot be written is reported")


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


def pjl_header(out: bytes) -> list[bytes]:
    return out[: out.index(b") BROTHER XL2HB")].split(b"\n")[:-1]


def check_secure_print(data: str, td: str) -> None:
    _, source = bw_page("A6", seed=10, nrows=8)
    path = os.path.join(td, "secure.ras")
    rw.write(path, "A6", [source])
    held = [b"@PJL SET COLLATE=OFF", b"@PJL COPIES=1", b"@PJL SET HOLD=STORE", b"@PJL SET HOLDTYPE=PRIVATE"]
    for opts in ("BRMonoColor=Mono", "BRMonoColor=FullColor " + FINE):
        plain = run(data, opts, path)
        rc, out, err = run(data, opts + " job-password=0815 job-password-encryption=none", path)
        check(rc == 0, f"Secure Print [{opts}]: filter failed: {err.strip()}")
        if rc:
            continue
        lines = pjl_header(out)
        check(lines[1:6] == held + [b"@PJL SET HOLDKEY=0815"], f"Secure Print [{opts}]: hold lines wrong: {lines[1:6]}")
        check(b"@PJL SET HOLD=OFF" not in lines, f"Secure Print [{opts}]: HOLD=OFF as well")
        check(out.count(b"0815") == 1 and "0815" not in err, f"Secure Print [{opts}]: the PIN appears elsewhere")
        # apart from the hold lines, the job is the one without a PIN
        check(out.replace(b"\n".join(held + [b"@PJL SET HOLDKEY=0815"]), b"@PJL SET HOLD=OFF", 1) == plain[1],
              f"Secure Print [{opts}]: more changed than the hold lines")
    bad = {"3 digits": "123", "5 digits": "12345", "letters": "abcd", "empty": "", "spaces": "12\\ 4",
           "sign": "+123", "non-ASCII digits": "١٢٣٤"}
    for name, pin in bad.items():
        rc, out, err = run(data, f"BRMonoColor=Mono job-password={pin}", path)
        check(rc == 1 and not out and "ERROR: Secure Print" in err, f"PIN {name}: printed or no error (status {rc})")
        check(not pin or pin not in err, f"PIN {name}: the PIN is in the error message")
    rc, out, err = run(data, "BRMonoColor=Mono job-password=1234 job-password-encryption=sha2-256", path)
    check(rc == 1 and not out and "encrypted" in err, f"hashed PIN: printed or no error (status {rc})")
    print(f"OK   Secure Print holds the job with its PIN; {len(bad) + 1} unusable PINs stop the job")

    for opts, want in (("BRMonoColor=FullColor BREnhanceBlkPrt=ON", 1), ("BRMonoColor=Auto BREnhanceBlkPrt=ON BRGray=OFF", 1),
                       ("BRMonoColor=FullColor BREnhanceBlkPrt=ON " + FINE, 1), ("BRMonoColor=Mono BREnhanceBlkPrt=ON", 0),
                       ("BRMonoColor=FullColor", 0)):
        rc, out, err = run(data, opts, path)
        lines = pjl_header(out) if rc == 0 else []
        got = lines.count(b"@PJL SET UCRGCRFORIMAGE=ON")
        check(rc == 0 and got == want, f"Enhance Black [{opts}]: {got} lines, want {want}")
        if got:
            i = lines.index(b"@PJL SET UCRGCRFORIMAGE=ON")
            check(lines[i + 1] == b"@PJL SET RESOLUTION=600" and lines[i - 1].startswith((b"@PJL SET APTMODE", b"@PJL SET IMPROVEGRAY")),
                  f"Enhance Black [{opts}]: line in the wrong place")
    print("OK   Enhance Black Printing reaches colour jobs only, before RESOLUTION")


def unread(fd: int) -> int:
    """Bytes waiting in a pipe."""
    return struct.unpack("i", fcntl.ioctl(fd, termios.FIONREAD, b"\0" * 4))[0]


def cancel_at(data: str, options: str, before: bytes, after: bytes):
    """(exit status, output, messages) of a job that gets SIGTERM once the filter has read `before`.

    `after` is what the rasterizer still delivers before the pipe closes."""
    env = {"HL3070CW_DATA": data, "SOURCE_DATE_EPOCH": EPOCH, "PATH": "/usr/bin:/bin"}
    rd, wr = os.pipe()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        p = subprocess.Popen([FILTER, "1", "u", "t", "1", options], stdin=rd, stdout=out, stderr=err, env=env)
        with os.fdopen(wr, "wb", buffering=0) as pipe:
            pipe.write(before)
            deadline = time.monotonic() + 30
            while unread(rd) and p.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)  # all of it read: the signal handler is in place
            p.send_signal(signal.SIGTERM)
            pipe.write(after)  # rd is still open here, so this cannot fail if the filter is gone
        os.close(rd)
        p.wait(timeout=60)
        out.seek(0)
        err.seek(0)
        return p.returncode, out.read(), err.read().decode(errors="replace")


def check_cancel_before_page(data: str) -> None:
    """Cancelled before a page's first line: that page is not started, so no blank sheet comes out."""
    hdr = b"3SaR" + rw.header("A6")
    width, height = struct.unpack_from("<II", hdr, 4 + 372)
    row = b"\xff" * (width * 3)
    first = hdr + row * height
    cases = {  # read before the cancel, arriving after it, pages to print
        "before the header": (hdr[:1], b"", 0),
        "before the header, which still arrives": (hdr[:1], hdr[1:] + row, 0),
        "inside the header": (hdr[:900], b"", 0),
        "inside the header, the rest still arrives": (hdr[:900], hdr[900:] + row, 0),
        "inside the header, which is damaged": (hdr[:100], b"\xee" * (len(hdr) - 100), 0),
        "before the first line": (hdr, b"", 0),
        "before the first line, which still arrives": (hdr, row, 0),
        "before the second header": (first, b"", 1),
        "before the second page's first line": (first + hdr[4:], b"", 1),
        "before the second page's first line, which still arrives": (first + hdr[4:], row, 1),
    }
    for opts in ("BRMonoColor=Mono", "BRMonoColor=FullColor " + FINE):
        for name, (before, after, pages) in cases.items():
            rc, out, err = cancel_at(data, opts, before, after)
            what = f"cancel {name} [{opts}]"
            check(rc == 0 and "ERROR:" not in err and "Sanitizer" not in err, f"{what}: status {rc}: {err.strip()[:200]}")
            check(err.count("PAGE:") == pages, f"{what}: {err.count('PAGE:')} pages counted, want {pages}")
            if not pages:
                check(not out, f"{what}: {len(out)} bytes went to the printer")
                continue
            check(out.endswith(UEL), f"{what}: job not closed")
            try:
                begun = [op.name for op in pxl.parse(out).ops].count("BeginPage")
                check(begun == pages, f"{what}: {begun} pages sent, want {pages}")
            except (ValueError, LookupError, struct.error) as e:
                check(False, f"{what}: output does not parse: {e}")
    print(f"OK   {len(cases)} ways to cancel before a page starts print nothing of it")


def check_cancel_blocked(data: str) -> None:
    """Cancelled while the printer is slower than the filter, which then waits in write()."""
    hdr = b"3SaR" + rw.header("A6")
    width, _ = rw.page_geometry("A6")
    rng = random.Random(15)
    raster = hdr + bytes(rng.randrange(256) for _ in range(width * 3)) * 1500
    env = {"HL3070CW_DATA": data, "SOURCE_DATE_EPOCH": EPOCH, "PATH": "/usr/bin:/bin"}
    for opts in ("BRMonoColor=Mono", "BRMonoColor=FullColor " + FINE):
        for gone in (False, True):
            what = f"cancel with {'the backend gone' if gone else 'the output blocked'} [{opts}]"
            with tempfile.TemporaryFile() as err:
                p = subprocess.Popen([FILTER, "1", "u", "t", "1", opts], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=err, env=env)

                def feed(proc=p):
                    try:
                        with proc.stdin:
                            proc.stdin.write(raster)
                    except BrokenPipeError:  # the filter stopped reading: that is the cancel
                        pass

                feeder = threading.Thread(target=feed)
                feeder.start()
                last, since, deadline = 0, time.monotonic(), time.monotonic() + 30
                while time.monotonic() < deadline:  # until the pipe is full and stays that way
                    n, now = unread(p.stdout.fileno()), time.monotonic()
                    if n != last:
                        last, since = n, now
                    elif n and now - since > 1:
                        break
                    time.sleep(0.05)
                p.send_signal(signal.SIGTERM)
                time.sleep(0.2)
                out = b""
                if not gone:
                    out = p.stdout.read()
                p.stdout.close()
                p.wait(timeout=60)
                feeder.join()
                err.seek(0)
                text = err.read().decode(errors="replace")
            check(last > 0, f"{what}: the output never filled the pipe")
            check(p.returncode == 0 and "ERROR:" not in text and "Sanitizer" not in text,
                  f"{what}: status {p.returncode}: {text.strip()[:200]}")
            if gone:
                continue
            try:
                pxl.parse(out)
                check(out.endswith(UEL) and len(planes(out, FINE in opts)) > 0, f"{what}: job not closed")
            except (ValueError, LookupError, struct.error, xl2hb.FormatError, xl2hb_fine.DecodeError) as e:
                check(False, f"{what}: output is cut or does not decode: {e}")
    print("OK   a cancel while the output is blocked cuts nothing off")


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
    check(p.returncode == 0 and "Sanitizer" not in text, f"cancel: status {p.returncode}: {text[:300]}")
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
        res = subprocess.run([FILTER, "--extract-brother-data"], capture_output=True, check=False,
                             env={**env, "HL3070CW_DATA": os.path.join(td, "data")})
        check(res.returncode == 1 and b"Sanitizer" not in res.stderr, "--extract-brother-data without Brother's driver")
    print("OK   command line")


def brother_tables() -> bytes:
    """A stand-in for Brother's filter program: just its named colour tables."""
    out = bytearray(b"\x7fELF")
    for mode in ("600dpi", "CAPT"):
        for gray in ("ON", "OFF"):
            for match in ("Match Monitor", "Vivid", "None (Table Type)"):
                name = f"HL-30xxC {mode} ImpGray={gray} Ver1 {match}".encode()
                out += b"junk" + name + b"\0" + bytes([sum(name) & 255]) * (17 ** 3 * 8)
    return bytes(out)


def make_package(data: str, root: str) -> str:
    """An unpacked package of Brother's, made up; returns Brother's folder in it."""
    top = os.path.join(root, "nonexistent")  # BROTHER_DIR of the check build
    for sub in ("inf/lut", "lpd", "profiles"):
        os.makedirs(os.path.join(top, sub))
    for name in os.listdir(data):
        if name.endswith("_cache08.bin"):
            shutil.copyfile(os.path.join(data, name), os.path.join(top, "inf/lut", name))
    with open(os.path.join(top, "lpd/filter"), "wb") as f:
        f.write(brother_tables())
    for name in ("NM", "NM_IG_ON", "Fi", "Fi_IG_ON"):
        with open(os.path.join(top, "profiles", f"broch08_PL_{name}.icm"), "wb") as f:
            f.write(bytes(36) + b"acsp" + name.encode())
    for at, dirs, files in os.walk(root):  # whatever the umask
        os.chmod(at, 0o755)
        for name in files:
            os.chmod(os.path.join(at, name), 0o644)
    return top


def check_extract(data: str, td: str) -> None:
    tile, capt = "0600-k_cache08.bin", "capt-k_cache08.bin"

    def extract(change=None, args=("--unpacked",)):
        case = tempfile.mkdtemp(dir=td, prefix="extract-")
        root, dest = os.path.join(case, "package"), os.path.join(case, "data")
        top = make_package(data, root)
        if change:
            change(case, root, top, dest)
        env = {"HL3070CW_PACKAGE": root, "HL3070CW_DATA": dest, "PATH": "/usr/bin:/bin"}
        res = subprocess.run([FILTER, "--extract-brother-data", *args], capture_output=True, env=env, check=False,
                             timeout=30)
        err = res.stderr.decode(errors="replace")
        check("Sanitizer" not in err and res.returncode in (0, 1), f"extract: crash: {err[:300]}")
        return res.returncode, err, case, top, dest

    def linked(rel):
        """Put a symlink, pointing back inside the package, in place of rel."""
        def change(case, root, top, dest):
            path = os.path.join(top, rel) if rel else top
            os.rename(path, path + ".real")
            os.symlink(os.path.basename(path) + ".real", path)
        return change

    rc, err, case, top, dest = extract()
    check(rc == 0, f"extract: failed: {err[:300]}")
    if rc:
        return
    names = [n for n in os.listdir(os.path.join(top, "inf/lut"))]
    for name in names:
        with open(os.path.join(top, "inf/lut", name), "rb") as a, open(os.path.join(dest, name), "rb") as b:
            check(a.read() == b.read(), f"extract: {name} differs")
        check(os.stat(os.path.join(dest, name)).st_mode & 0o777 == 0o644, f"extract: {name}: wrong mode")
    made = os.listdir(dest)
    check(len(made) == 16 + 12 + 1 and not any(n.startswith(".") for n in made), f"extract: unexpected files: {made}")
    check(len(os.listdir(os.path.join(dest, "profiles"))) == 4, "extract: profiles missing")

    def complete() -> bool:
        res = subprocess.run([FILTER, "--check-data"], capture_output=True, check=False,
                             env={"HL3070CW_DATA": dest, "PATH": "/usr/bin:/bin"})
        return res.returncode == 0

    check(complete(), "check-data: a fresh copy is not taken as complete")
    needed = [n for n in os.listdir(dest) if n.startswith(("0600-", "table-600-"))]
    needed += ["profiles/broch08_PL_NM.icm", "profiles/broch08_PL_NM_IG_ON.icm"]
    for name in needed:
        path = os.path.join(dest, name)
        with open(path, "rb") as f:
            good = f.read()
        os.remove(path)
        check(not complete(), f"check-data: complete without {name}")
        with open(path, "wb") as f:
            f.write(good if name.startswith("profiles/") else good[:-1])
        if not name.startswith("profiles/"):
            check(not complete(), f"check-data: complete with {name} cut short")
        with open(path, "wb") as f:
            f.write(good)
    check(complete(), "check-data: the restored copy is not taken as complete")
    for name in ("capt-k_cache08.bin", "table-capt-grayon-normal.bin", "profiles/broch08_PL_Fi.icm"):
        os.remove(os.path.join(dest, name))
    check(complete(), "check-data: an installation without Fine is not taken as complete")

    def fifo(case, root, top, dest):
        os.remove(os.path.join(top, "lpd/filter"))
        os.mkfifo(os.path.join(top, "lpd/filter"))

    def huge(case, root, top, dest):
        os.truncate(os.path.join(top, "lpd/filter"), (64 << 20) + 1)

    def other_kind(case, root, top, dest):
        with open(os.path.join(top, "inf/lut", tile), "r+b") as f:
            f.write(b"root:")

    def package_link(case, root, top, dest):
        os.rename(root, root + ".real")
        os.symlink(root + ".real", root)

    def dest_link(case, root, top, dest):
        os.mkdir(os.path.join(case, "elsewhere"))
        os.symlink(os.path.join(case, "elsewhere"), dest)

    def profiles_link(case, root, top, dest):
        os.mkdir(os.path.join(case, "elsewhere"))
        os.mkdir(dest, 0o755)
        os.symlink(os.path.join(case, "elsewhere"), os.path.join(dest, "profiles"))

    refused = {
        **{f"symlink for {rel or 'the top folder'}": linked(rel)
           for rel in ("", "inf", "inf/lut", f"inf/lut/{tile}", "lpd", "lpd/filter", "profiles")},
        "FIFO for a file": fifo, "file too large": huge, "another kind of file": other_kind,
        "package folder a symlink": package_link, "data folder a symlink": dest_link,
        "profiles folder a symlink": profiles_link,
    }
    for name, change in refused.items():
        rc, err, case, top, dest = extract(change)
        check(rc == 1 and err, f"extract, {name}: status {rc}, want it refused")
        away = os.path.join(case, "elsewhere")
        check(not os.path.exists(away) or not os.listdir(away), f"extract, {name}: wrote through the symlink")

    def planted(case, root, top, dest):
        os.mkdir(dest, 0o755)
        with open(os.path.join(case, "victim"), "w") as f:
            f.write("untouched")
        os.symlink(os.path.join(case, "victim"), os.path.join(dest, tile))

    rc, err, case, top, dest = extract(planted)
    with open(os.path.join(case, "victim")) as f:
        check(rc == 0 and f.read() == "untouched" and not os.path.islink(os.path.join(dest, tile)),
              "extract: a symlink at a file's destination was followed")

    rc, err, case, top, dest = extract(linked(f"inf/lut/{capt}"))
    check(rc == 0 and "Fine" in err and not os.path.exists(os.path.join(dest, capt)), "extract: Fine file link followed")

    for args in (("/tmp/data",), ("/tmp/data", "/"), ("--unpacked", "/"), ("",)):
        rc, err, case, top, dest = extract(args=args)
        check(rc == 1 and "Usage:" in err and not os.path.exists(dest), f"extract: took the arguments {args}")
    print(f"OK   copying Brother's data: {len(refused)} kinds of trickery refused, no paths from the command line")

    if os.geteuid() != 0:
        return

    def given_away(rel):
        return lambda case, root, top, dest: os.chown(os.path.join(top, rel) if rel else root, 1234, 1234)

    def opened_up(rel):
        return lambda case, root, top, dest: os.chmod(os.path.join(top, rel) if rel else root, 0o777)

    def loose_dest(case, root, top, dest):
        os.mkdir(dest)
        os.chmod(dest, 0o775)

    parts = ("", "inf", "inf/lut", f"inf/lut/{tile}", "lpd", "lpd/filter")
    unsafe = {
        **{f"{rel or 'package folder'} of another user": given_away(rel) for rel in parts},
        **{f"{rel or 'package folder'} writable by everyone": opened_up(rel) for rel in parts},
        "data folder writable by its group": loose_dest,
    }
    for name, change in unsafe.items():
        rc, err, case, top, dest = extract(change)
        check(rc == 1 and "must belong to root" in err, f"extract as root, {name}: status {rc}, want it refused")
    print(f"OK   as root: {len(unsafe)} unsafe owners and modes refused")


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
        check_extract(data, td)
        check_round_trips(data, td)
        check_all_sizes(data, td)
        check_grey_input(data, td)
        check_fine_fallback(td)
        check_bad_input(data, td)
        check_custom_sizes(data)
        check_write_failure(data, td)
        check_job_text(data, td)
        check_secure_print(data, td)
        check_cancel(data)
        check_cancel_before_page(data)
        check_cancel_blocked(data)
        check_fine_encoder(td, a.lines)
    if failures:
        print(f"\n{len(failures)} checks failed")
        return 1
    print("\nAll checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
