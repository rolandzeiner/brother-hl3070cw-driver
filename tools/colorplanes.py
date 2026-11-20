"""Decode all four planes of a colour job, using Brother's random method choice
as ground truth.

About one job in five, Brother's filter encodes every plane with method 4 and
8-pixel units (a format the decoder knows exactly). The common variant uses
other units for C and M. Decoding both variants of the same page and
comparing them checks the decoder on the unusual units.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import oracle  # noqa: E402
import pxl  # noqa: E402
import xl2hb  # noqa: E402

PLANES = "KCMY"


def table_of(job: pxl.Job) -> tuple:
    bi = [op for op in job.ops if op.name == "BeginImage"][0]
    return tuple(bi.attrs["CommentData"][7::5])


def bands(job: pxl.Job):
    """Yield (plane, start, height, band bytes) for every ReadImage."""
    for op in job.ops:
        if op.name == "ReadImage":
            yield op.attrs["CommentData"], op.attrs["StartLine"], op.attrs["BlockHeight"], op.data


def decode_planes(job: pxl.Job) -> dict[int, dict[int, bytes]]:
    planes: dict[int, dict[int, bytes]] = {p: {} for p in range(4)}
    for plane, start, height, data in bands(job):
        _, _, _, rows = xl2hb.decode_band(data)
        for i, r in enumerate(rows):
            planes[plane][start + i] = r
    return planes


def variants(raster: str, options: str, want=("common", "all8"), tries: int = 80) -> dict[str, pxl.Job]:
    """Run Brother's filter until each wanted variant has been seen."""
    found: dict[str, pxl.Job] = {}
    for _ in range(tries):
        job = pxl.parse(oracle.run(raster, options))
        t = table_of(job)
        kind = "all8" if all(v == 0x0408 for v in t) else "common" if t == (0x020C, 0x0214, 0x040A, 0x020C) else str(t)
        found.setdefault(kind, job)
        if all(k in found for k in want):
            break
    return found


def band_header(data: bytes) -> tuple[int, int, int, int]:
    _, mu, bpl, rows = struct.unpack_from(">HHHH", data, 0)
    return mu >> 8, mu & 0xFF, bpl, rows
