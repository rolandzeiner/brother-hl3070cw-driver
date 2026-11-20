"""What a Fine job prints: the job without its band encoding.

Fine output is compared by image, not by bytes: the line encoding is a model
of Brother's (docs/FORMAT.md, "Fine") and matches most lines, but not all,
while the decoded dots must match exactly.
"""

from __future__ import annotations

import hashlib
import struct

import pxl
import xl2hb_fine

FINE = "BRResolution=600x2400dpi"


def is_fine(options: str) -> bool:
    return FINE in options


def bands(raw: bytes):
    """Yield (page, plane, first row, [(bpl, encoded line)]) for every band of a Fine job."""
    page = -1
    for op in pxl.parse(raw).ops:
        if op.name == "BeginImage":
            page += 1
        if op.name != "ReadImage":
            continue
        d = op.data
        magic, mu, bpl, n, total = struct.unpack_from(">HHHHI", d, 0)
        if magic != 12 or mu != 0 or total != len(d) or sum(d) & 0xFF:
            raise ValueError(f"bad Fine band header {magic} {mu:#x} {total}/{len(d)}")
        p, prev, lines = 12, 0, []
        for _ in range(n):
            back, ln = struct.unpack_from(">HH", d, p)
            if back != prev:
                raise ValueError("broken back link")
            lines.append((bpl, d[p + 4:p + 4 + ln]))
            p += 4 + ((ln + 3) & ~3)
            prev = ln
        if struct.unpack_from(">HH", d, p) != (prev, 0) or p + 5 != len(d):
            raise ValueError("bad band trailer")
        yield page, op.attrs["CommentData"], op.attrs["StartLine"], lines


def image(raw: bytes) -> dict:
    """{(page, plane, row): decoded line} for every non-blank row."""
    img = {}
    for page, plane, start, lines in bands(raw):
        for k, (bpl, data) in enumerate(lines):
            img[(page, plane, start + k)] = xl2hb_fine.decode_line(data, bpl)
    return img


def encoded_lines(raw: bytes) -> dict:
    return {(page, plane, start + k): data
            for page, plane, start, lines in bands(raw) for k, (bpl, data) in enumerate(lines)}


def frame(raw: bytes) -> list:
    """Everything in the job except the band data."""
    job = pxl.parse(raw)
    return [job.pjl, [(op.name, sorted(op.attrs.items())) for op in job.ops if op.name != "ReadImage"],
            job.trailer]


def digest(raw: bytes) -> str:
    """SHA-256 over the job frame and every decoded row: equal digests print alike."""
    h = hashlib.sha256(repr(frame(raw)).encode())
    img = image(raw)
    for key in sorted(img):
        h.update(repr(key).encode())
        h.update(img[key])
    return h.hexdigest()
