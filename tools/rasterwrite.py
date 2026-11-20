"""Write CUPS raster v3 (uncompressed, native little-endian) files for test pages.

Only what the reverse-engineering experiments need: RGB, 8 bits per channel,
chunky order, 600 dpi, one or more pages of the same size.
"""

from __future__ import annotations

import struct
from typing import Callable, Iterable

# Page sizes in points (width, height) and the PPD name the Brother filter expects.
PAGE_SIZES = {
    # name in the Brother PPD: (width, height) in points
    "A4": (595, 842), "Letter": (612, 792), "Legal": (612, 1008), "Executive": (522, 756),
    "A5": (420, 595), "A5Rotated": (595, 420), "A6": (297, 420), "ISOB5": (499, 709),
    "ISOB6": (355, 499), "B5": (516, 729), "B6": (363, 516), "EnvDL": (312, 624),
    "EnvC5": (459, 649), "Env10": (297, 684), "EnvMonarch": (279, 540), "3x5": (216, 360),
    "210x405mm": (595, 1148), "FanFoldGermanLegal": (612, 936), "EnvPRC5Rotated": (624, 312),
    "Postcard": (284, 419), "EnvYou4": (298, 666), "EnvChou3": (340, 666),
}

# Header fields the Brother PPD sets through setpagedevice: name -> (offset, kind)
FIELDS = {
    "MediaType": (128, "str"),
    "ManualFeed": (320, "u32"),
    "MediaPosition": (324, "u32"),
    "NumCopies": (340, "u32"),
    "Collate": (264, "u32"),
    "cupsMediaType": (380, "u32"),
}

MARGIN_PT = 12  # 4.23 mm, what the Brother PPD declares for every size

Row = bytes
RowSource = Callable[[int, int, int], Row]  # (y, width, height) -> RGB row bytes


def page_geometry(size: str, dpi: int = 600) -> tuple[int, int]:
    """Pixel width and height of the imageable area, as cgpdftoraster produces it."""
    w_pt, h_pt = PAGE_SIZES[size]
    width = round((w_pt - 2 * MARGIN_PT) * dpi / 72)
    height = round((h_pt - 2 * MARGIN_PT) * dpi / 72)
    return width, height


def header(size: str, dpi: int = 600, ydpi: int | None = None, fields: dict | None = None) -> bytes:
    ydpi = ydpi or dpi
    w_pt, h_pt = PAGE_SIZES[size]
    width = round((w_pt - 2 * MARGIN_PT) * dpi / 72)
    height = round((h_pt - 2 * MARGIN_PT) * ydpi / 72)
    h = bytearray(1796)
    struct.pack_into("<II", h, 276, dpi, ydpi)  # HWResolution
    struct.pack_into("<4I", h, 284, MARGIN_PT, MARGIN_PT, w_pt - MARGIN_PT, h_pt - MARGIN_PT)
    struct.pack_into("<II", h, 312, MARGIN_PT, MARGIN_PT)  # Margins
    struct.pack_into("<I", h, 324, 1)  # MediaPosition
    struct.pack_into("<I", h, 340, 1)  # NumCopies
    struct.pack_into("<II", h, 352, w_pt, h_pt)  # PageSize
    struct.pack_into("<II", h, 372, width, height)  # cupsWidth, cupsHeight
    struct.pack_into("<IIII", h, 384, 8, 24, width * 3, 0)  # bpc, bpp, bpl, order
    struct.pack_into("<I", h, 400, 1)  # cupsColorSpace = RGB
    struct.pack_into("<I", h, 420, 3)  # cupsNumColors
    struct.pack_into("<ff", h, 428, float(w_pt), float(h_pt))  # cupsPageSize
    struct.pack_into(
        "<4f", h, 436, float(MARGIN_PT), float(MARGIN_PT), float(w_pt - MARGIN_PT), float(h_pt - MARGIN_PT)
    )
    struct.pack_into("<I", h, 452, 1)  # cupsInteger[0], set by the Brother PPD
    h[1732 : 1732 + len(size)] = size.encode()  # cupsPageSizeName
    for name, value in (fields or {}).items():
        off, kind = FIELDS[name]
        if kind == "u32":
            struct.pack_into("<I", h, off, int(value))
        else:
            h[off : off + 64] = value.encode().ljust(64, b"\0")
    return bytes(h)


def write(
    path: str,
    size: str,
    pages: Iterable[RowSource],
    dpi: int = 600,
    ydpi: int | None = None,
    fields: dict | None = None,
) -> None:
    hdr = header(size, dpi, ydpi, fields)
    width, height = struct.unpack_from("<II", hdr, 372)
    with open(path, "wb") as f:
        f.write(b"3SaR")
        for source in pages:
            f.write(hdr)
            for y in range(height):
                row = source(y, width, height)
                if len(row) != width * 3:
                    raise ValueError(f"row {y}: {len(row)} bytes, want {width * 3}")
                f.write(row)


# --- helpers for building rows -------------------------------------------------

WHITE = b"\xff\xff\xff"
BLACK = b"\x00\x00\x00"


def blank(width: int) -> bytes:
    return WHITE * width


def from_bits(bits: bytes | bytearray, width: int, ink: bytes = BLACK) -> bytes:
    """RGB row from a 1-bit row (MSB first, 1 = ink)."""
    row = bytearray(WHITE * width)
    for x in range(width):
        if bits[x >> 3] & (0x80 >> (x & 7)):
            row[3 * x : 3 * x + 3] = ink
    return bytes(row)
