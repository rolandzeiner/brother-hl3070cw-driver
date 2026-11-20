"""Reference outputs of Brother's filter, kept so the driver can be checked
byte for byte after Rosetta 2 (and with it Brother's filter) is gone.

    python3 -I tools/fixtures.py check     # compare build/rastertohl3070cw with the fixtures
    python3 -I tools/fixtures.py make      # regenerate them (needs Brother's driver + Rosetta)

Inputs are generated from the case list in tools/jobcheck.py with fixed
seeds, so only Brother's outputs are stored (gzip, tests/fixtures/).
"""

from __future__ import annotations

import gzip
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import jobcheck  # noqa: E402
import rasterwrite as rw  # noqa: E402

FIXTURES = os.path.join(jobcheck.ROOT, "tests", "fixtures")
EPOCH = 1767229505  # Thu 1 Jan 2026 01:05:05 UTC: single-digit fields test the unpadded date
SKIP = ("gradient",)  # large and covered by the other grey cases


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fixture_cases():
    for name, size, pages, options, fields in jobcheck.cases():
        if any(s in name for s in SKIP):
            continue
        fields = dict(fields)
        title = fields.pop("_title", "t")
        user = fields.pop("_user", "rz")
        yield name, size, pages, options, fields, title, user


def make() -> int:
    os.makedirs(FIXTURES, exist_ok=True)
    total = 0
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        for name, size, pages, options, fields, title, user in fixture_cases():
            rw.write(path, size, pages, fields=fields)
            out = jobcheck.brother_common(path, options, title, user, fake_time=EPOCH)
            dst = os.path.join(FIXTURES, slug(name) + ".prn.gz")
            with gzip.GzipFile(dst, "wb", mtime=0) as f:
                f.write(out)
            total += os.path.getsize(dst)
            print(f"wrote {dst} ({len(out)} bytes)")
    print(f"total {total} bytes compressed")
    return 0


def check() -> int:
    failed = n = 0
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        for name, size, pages, options, fields, title, user in fixture_cases():
            src = os.path.join(FIXTURES, slug(name) + ".prn.gz")
            if not os.path.exists(src):
                print(f"MISSING {name}")
                failed += 1
                continue
            n += 1
            rw.write(path, size, pages, fields=fields)
            want = gzip.open(src).read()
            got = jobcheck.ours(path, options, title, user, EPOCH)
            ok = want == got
            failed += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {name}")
            if not ok:
                print("     " + jobcheck.first_difference(want, got))
    print(f"\n{n - failed} of {n} fixtures byte-identical")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit({"make": make, "check": check}.get(sys.argv[1] if len(sys.argv) > 1 else "check", check)())
