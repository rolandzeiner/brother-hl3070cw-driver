"""Run Brother's own (Intel-only) filter as the reference implementation.

Needs the Brother HL-3070CW macOS driver installed and Rosetta 2. This is the
one piece of the toolchain that stops working once Rosetta is gone, which is why
its outputs are kept as fixtures under tests/fixtures/.
"""

from __future__ import annotations

import os
import subprocess

BROTHER_FILTER = (
    "/Library/Printers/Brother/Filter/rastertobrother3040.bundle/Contents/MacOS/rastertobrother3040"
)
BROTHER_PPD_CANDIDATES = (
    "/etc/cups/ppd/Brother_HL_3070CW_series.ppd",
    "/Library/Printers/PPDs/Contents/Resources/Brother HL-3070CW series CUPS.gz",
)


def brother_ppd() -> str:
    for p in BROTHER_PPD_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Brother HL-3070CW PPD not found; install Brother's driver first")


FAKETIME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "faketime.dylib")


# Brother's own PPD. Its filter does Secure Print only with it (it reads *BRSecureCode there).
BROTHER_OWN_PPD = "/Library/Printers/PPDs/Contents/Resources/Brother HL-3070CW series CUPS.gz"


def run(raster_path: str, options: str = "", job: str = "t", user: str = "rz", fake_time: int | None = None,
        ppd: str | None = None) -> bytes:
    """Return the printer data Brother's filter produces for a raster file.

    fake_time pins the job timestamp (needs build/faketime.dylib, see tools/faketime.c).
    """
    env = dict(os.environ, PPD=ppd or brother_ppd())
    if fake_time is not None:
        if not os.path.exists(FAKETIME):
            raise FileNotFoundError("build/faketime.dylib missing: make faketime")
        env.update(DYLD_INSERT_LIBRARIES=FAKETIME, FAKE_TIME=str(fake_time))
    with open(raster_path, "rb") as f:
        res = subprocess.run(
            [BROTHER_FILTER, "1", user, job, "1", options],
            stdin=f,
            capture_output=True,
            env=env,
            check=False,
        )
    if res.returncode != 0:
        raise RuntimeError(f"Brother filter failed ({res.returncode}): {res.stderr.decode(errors='replace')}")
    return res.stdout
