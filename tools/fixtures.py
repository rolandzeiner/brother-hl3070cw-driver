"""Checksums of Brother's filter output, kept so the driver can be checked
byte for byte after Rosetta 2 (and with it Brother's filter) is gone.

    python3 -I tools/fixtures.py check     # compare build/rastertohl3070cw with the checksums
    python3 -I tools/fixtures.py make      # regenerate them (needs Brother's driver + Rosetta)

Inputs are generated from the case list in tools/jobcheck.py with fixed
seeds. The repository stores only SHA-256 checksums of Brother's output
(tests/fixtures.sha256): the outputs themselves contain Brother's halftone
patterns and are not redistributed. `make` also keeps the full outputs in
tests/fixtures-local/ (ignored by git), which `check` uses to show where a
difference starts.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import jobcheck  # noqa: E402
import rasterwrite as rw  # noqa: E402

SUMS = os.path.join(jobcheck.ROOT, "tests", "fixtures.sha256")
LOCAL = os.path.join(jobcheck.ROOT, "tests", "fixtures-local")
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
    os.makedirs(LOCAL, exist_ok=True)
    lines = []
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        for name, size, pages, options, fields, title, user in fixture_cases():
            rw.write(path, size, pages, fields=fields)
            out = jobcheck.brother_common(path, options, title, user, fake_time=EPOCH)
            lines.append(f"{hashlib.sha256(out).hexdigest()}  {slug(name)}")
            with gzip.GzipFile(os.path.join(LOCAL, slug(name) + ".prn.gz"), "wb", mtime=0) as f:
                f.write(out)
            print(f"{slug(name)}: {len(out)} bytes")
    with open(SUMS, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {SUMS} ({len(lines)} checksums)")
    return 0


def check() -> int:
    sums = {}
    for line in open(SUMS):
        digest, name = line.split()
        sums[name] = digest
    failed = n = 0
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        for name, size, pages, options, fields, title, user in fixture_cases():
            key = slug(name)
            if key not in sums:
                print(f"MISSING {name}")
                failed += 1
                continue
            n += 1
            rw.write(path, size, pages, fields=fields)
            got = jobcheck.ours(path, options, title, user, EPOCH)
            ok = hashlib.sha256(got).hexdigest() == sums[key]
            failed += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {name}")
            local = os.path.join(LOCAL, key + ".prn.gz")
            if not ok and os.path.exists(local):
                print("     " + jobcheck.first_difference(gzip.open(local).read(), got))
    print(f"\n{n - failed} of {n} fixtures byte-identical")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit({"make": make, "check": check}.get(sys.argv[1] if len(sys.argv) > 1 else "check", check)())
