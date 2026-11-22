"""Compare what Brother's filter writes for the HL-3070CW's siblings with the fixtures.

    python3 -I tools/siblings.py        # needs Brother's driver and Rosetta 2

Runs every fixture case through Brother's filter with each sibling's own PPD
and compares with tests/fixtures.sha256. All the same means: these checksums
are the siblings' fixtures too, and stay usable after Rosetta is gone.
"""

from __future__ import annotations

import gzip
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
import fixtures  # noqa: E402
import genppd  # noqa: E402
import jobcheck  # noqa: E402
import oracle  # noqa: E402
import rasterwrite as rw  # noqa: E402

PPDS = "/Library/Printers/PPDs/Contents/Resources"


def main() -> int:
    with open(fixtures.SUMS) as f:
        sums = {name: digest for digest, name in (line.split() for line in f)}
    with tempfile.TemporaryDirectory() as td:
        cases = []
        for i, (name, size, pages, options, fields, title, user) in enumerate(fixtures.fixture_cases()):
            path = os.path.join(td, f"{i}.ras")
            rw.write(path, size, pages, fields=fields)
            cases.append((name, options, title, user, path))
        failed = 0
        for model in genppd.SIBLINGS:
            ppd = os.path.join(td, "sibling.ppd")
            with gzip.open(os.path.join(PPDS, f"Brother {model} CUPS.gz")) as src, open(ppd, "wb") as dst:
                dst.write(src.read())

            def differs(case) -> str | None:
                name, options, title, user, path = case
                out = jobcheck.brother_common(path, options, title, user, fake_time=fixtures.EPOCH, use_ppd=ppd)
                return None if fixtures.checksum(options, out) == sums[fixtures.slug(name)] else name

            with ThreadPoolExecutor(8) as pool:
                bad = [name for name in pool.map(differs, cases) if name]
            failed += bool(bad)
            print(f"{'OK  ' if not bad else 'FAIL'} {model}: {len(cases) - len(bad)} of {len(cases)} as the HL-3070CW {bad[:5]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
