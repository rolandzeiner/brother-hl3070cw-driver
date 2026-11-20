"""Parse the PJL + PCL XL ("XL2HB") job stream the HL-3070CW expects.

PCL XL is HP's documented binary page description language (little-endian
binding). Brother wraps its host-based raster in a small subset of it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

OPS = {
    0x41: "BeginSession", 0x42: "EndSession", 0x43: "BeginPage", 0x44: "EndPage",
    0x46: "VendorUnique", 0x47: "Comment", 0x48: "OpenDataSource", 0x49: "CloseDataSource",
    0x57: "SetDefaultGS", 0x60: "PopGS", 0x61: "PushGS", 0x6a: "SetColorSpace",
    0x75: "SetPageOrigin", 0xb0: "BeginImage", 0xb1: "ReadImage", 0xb2: "EndImage",
}
ATTRS = {
    0x03: "ColorSpace", 0x25: "MediaSize", 0x26: "MediaSource", 0x27: "MediaType",
    0x28: "Orientation", 0x2a: "PageOrigin", 0x2f: "CustomMediaSize", 0x30: "CustomMediaSizeUnits",
    0x31: "PageCopies", 0x34: "SimplexPageMode", 0x35: "DuplexPageMode", 0x36: "DuplexPageSide",
    0x62: "ColorDepth", 0x63: "BlockHeight", 0x64: "ColorMapping", 0x65: "CompressMode",
    0x67: "DestinationSize", 0x6b: "SourceHeight", 0x6c: "SourceWidth", 0x6d: "StartLine",
    0x81: "CommentData", 0x82: "DataOrg", 0x86: "Measure", 0x88: "SourceType",
    0x89: "UnitsPerMeasure", 0x8f: "ErrorReport",
}
_SCALAR = {0xC0: "<B", 0xC1: "<H", 0xC2: "<I", 0xC3: "<h", 0xC4: "<i", 0xC5: "<f"}
_XY = {0xD0: "<BB", 0xD1: "<HH", 0xD2: "<II", 0xD3: "<hh", 0xD4: "<ii", 0xD5: "<ff"}
_BOX = {0xE0: "<4B", 0xE1: "<4H", 0xE2: "<4I", 0xE3: "<4h", 0xE4: "<4i", 0xE5: "<4f"}
_ARR = {0xC8: "B", 0xC9: "H", 0xCA: "I", 0xCB: "h", 0xCC: "i", 0xCD: "f"}


@dataclass
class Op:
    name: str
    code: int
    attrs: dict = field(default_factory=dict)
    data: bytes | None = None
    raw_attr_types: dict = field(default_factory=dict)  # attr name -> PCL XL type tag


@dataclass
class Job:
    pjl: list[str]
    stream_header: str
    ops: list[Op]
    trailer: bytes

    def images(self):
        """Yield (StartLine, BlockHeight, CompressMode, payload) for every ReadImage."""
        for op in self.ops:
            if op.name == "ReadImage":
                yield op.attrs["StartLine"], op.attrs["BlockHeight"], op.attrs["CompressMode"], op.data


def parse(d: bytes) -> Job:
    hdr = d.find(b") BROTHER")
    if hdr < 0:
        raise ValueError("no XL2HB stream header")
    pjl = [ln for ln in d[:hdr].decode("latin-1").splitlines() if ln.strip()]
    p = d.index(b"\n", hdr) + 1
    stream_header = d[hdr : p - 1].decode("latin-1")
    ops: list[Op] = []
    stack: list = []
    while p < len(d):
        b = d[p]
        if b in _SCALAR:
            fmt = _SCALAR[b]
            stack.append((b, struct.unpack_from(fmt, d, p + 1)[0]))
            p += 1 + struct.calcsize(fmt)
        elif b in _XY or b in _BOX:
            fmt = _XY.get(b) or _BOX[b]
            stack.append((b, struct.unpack_from(fmt, d, p + 1)))
            p += 1 + struct.calcsize(fmt)
        elif b in _ARR:
            lfmt = _SCALAR[d[p + 1]]
            n = struct.unpack_from(lfmt, d, p + 2)[0]
            q = p + 2 + struct.calcsize(lfmt)
            efmt = "<" + _ARR[b] * n
            val = struct.unpack_from(efmt, d, q)
            stack.append((b, bytes(val) if b == 0xC8 else val))
            p = q + struct.calcsize(efmt)
        elif b == 0xF8:
            a = d[p + 1]
            tag, val = stack.pop()
            stack.append(("attr", ATTRS.get(a, f"attr_0x{a:02x}"), tag, val))
            p += 2
        elif b in (0xFA, 0xFB):
            n = struct.unpack_from("<I", d, p + 1)[0] if b == 0xFA else d[p + 1]
            q = p + (5 if b == 0xFA else 2)
            ops[-1].data = (ops[-1].data or b"") + d[q : q + n]
            p = q + n
        elif b == 0x1B:
            return Job(pjl, stream_header, ops, d[p:])
        else:
            op = Op(OPS.get(b, f"op_0x{b:02x}"), b)
            for item in stack:
                if item[0] == "attr":
                    _, name, tag, val = item
                    op.attrs[name] = val
                    op.raw_attr_types[name] = tag
            ops.append(op)
            stack = []
            p += 1
    raise ValueError("stream ended without UEL")
