"""Find the RGB -> CMYK colour tables inside Brother's filter binary.

The tables are data, read from the user's own copy of Brother's driver
(never stored in this repository). Each one sits right after a name such as
"HL-30xxC 600dpi ImpGray=ON Ver1.01 (2011/03/29) Match Monitor" and its
terminating zero: 17 x 17 x 17 nodes in R, G, B order (R slowest), every
node four little-endian u16 values C, M, Y, K (0..255).
"""

from __future__ import annotations

import re
import struct

BROTHER_FILTER = (
    "/Library/Printers/Brother/Filter/rastertobrother3040.bundle/Contents/MacOS/rastertobrother3040"
)
GRID = 17
NODES = GRID ** 3
NAME_RE = re.compile(rb"HL-30xxC [^\x00]{10,80}\(20\d\d/\d\d/\d\d\)[^\x00]*")


class Table:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self.v = struct.unpack("<%dH" % (NODES * 4), data)

    def node(self, r: int, g: int, b: int) -> tuple[int, int, int, int]:
        """(C, M, Y, K) at grid node r, g, b (0..16)."""
        i = (r * GRID * GRID + g * GRID + b) * 4
        return self.v[i], self.v[i + 1], self.v[i + 2], self.v[i + 3]


def load(path: str = BROTHER_FILTER, arch_offset_min: int = 0) -> list[Table]:
    """All HL-30xxC tables in file order (both slices of the universal binary)."""
    d = open(path, "rb").read()
    out = []
    for m in NAME_RE.finditer(d):
        if m.start() < arch_offset_min:
            continue
        start = m.end() + 1  # after the terminating zero
        data = d[start : start + NODES * 8]
        if len(data) != NODES * 8:
            continue
        t = Table(m.group().decode("latin-1"), data)
        if t.node(16, 16, 16)[:3] == (0, 0, 0) or "None" in t.name:
            out.append(t)
    return out
