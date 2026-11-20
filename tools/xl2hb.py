"""Decoder for the band format inside Brother XL2HB ReadImage blocks.

Working hypothesis, refined against Brother's filter (see docs/FORMAT.md):

Band:
  u16 BE  0x0004
  u16 BE  method << 8 | unit      unit = pixels per compression unit
  u16 BE  bytes per line (whole image width / 8)
  u16 BE  rows in the band
  u32 BE  total band length, header and checksum included
  rows x  [u16 BE length of the previous line or 0] [u16 BE length] [data, padded to 4]
  u16 BE  length of the last line, u16 BE 0
  u8      checksum: all band bytes sum to 0 mod 256

Line data, method 2 (units packed as bit fields) and method 4 (units in whole bytes):
  1rrr.. + unit           repeat unit (r+1) times; r = max adds an extension byte
  01rr.. + units          literal units
  00rr..                  copy units from the line above
"""

from __future__ import annotations

import struct


class BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0  # bit position

    def read(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ext(self) -> int:
        """Extension count: bytes are added up while they are 0xFF."""
        total = 0
        while True:
            b = self.read(8)
            total += b
            if b != 0xFF:
                return total

    def align(self) -> None:
        self.pos = (self.pos + 7) & ~7

    def done(self) -> bool:
        return self.pos >= len(self.data) * 8


class FormatError(Exception):
    pass


# "00rrrrrr" repeats the units found this many units back in the same line
# (units before the line start read as 0): 2 in method 2, 4 in method 4,
# measured on all planes (units 8, 10, 12 and 20).
COPY_DISTANCE = {(2, 12): 2, (2, 20): 2, (4, 8): 4, (4, 10): 4}


def units_to_bits(units: list[int], unit: int, width_bits: int) -> bytes:
    """Concatenate unit-wide bit fields MSB first, cut to width_bits, pack to bytes."""
    out = bytearray((width_bits + 7) // 8)
    pos = 0
    for u in units:
        for i in range(unit - 1, -1, -1):
            if pos >= width_bits:
                return bytes(out)
            if (u >> i) & 1:
                out[pos >> 3] |= 0x80 >> (pos & 7)
            pos += 1
    return bytes(out)


def bits_to_units(row: bytes, unit: int, width_bits: int) -> list[int]:
    n = -(-width_bits // unit)
    units = []
    for k in range(n):
        v = 0
        for i in range(unit):
            pos = k * unit + i
            bit = (row[pos >> 3] >> (7 - (pos & 7))) & 1 if pos < width_bits else 0
            v = (v << 1) | bit
        units.append(v)
    return units


def rep_bits_for(method: int, unit: int) -> int:
    """Bits of the repeat count: a nibble command in method 2, and in method 4
    whatever makes command plus unit exactly 16 bits."""
    if method == 2:
        return 3
    if method == 4:
        return 15 - unit
    raise FormatError(f"unknown method {method}")


def decode_line(data: bytes, method: int, unit: int, nunits: int, prev: list[int], trace: list | None = None,
                copy_distance: int | None = None) -> list[int]:
    out: list[int] = []
    rep_bits = rep_bits_for(method, unit)
    rep_max = (1 << rep_bits) - 1
    dist = copy_distance if copy_distance is not None else COPY_DISTANCE.get((method, unit))
    br = BitReader(data)
    while len(out) < nunits:
        if br.done():
            raise FormatError(f"line ended after {len(out)} of {nunits} units")
        top = br.read(1)
        if top:  # repeat
            r = br.read(rep_bits)
            u = br.read(unit)
            if r == rep_max:
                br.align()
                count = rep_max + 1 + br.ext()
            else:
                count = r + 1
            br.align()
            if trace is not None:
                trace.append(("rep", count, u))
            out.extend([u] * count)
        else:  # literal and copy are whole bytes in both methods: 0 L rrrrrr
            lit = br.read(1)
            r = br.read(6)
            if lit:
                count = r + 2
                if r == 63:
                    count += br.ext()
                units = [br.read(unit) for _ in range(count)]
                br.align()
                if trace is not None:
                    trace.append(("lit", count, units))
                out.extend(units)
            else:
                count = r + 1
                if r == 63:
                    count += br.ext()
                if trace is not None:
                    trace.append(("copy", count))
                if dist is None:
                    raise FormatError(f"copy distance for method {method} unit {unit} unknown")
                for _ in range(count):
                    src = len(out) - dist
                    out.append(out[src] if src >= 0 else 0)
    if len(out) != nunits:
        raise FormatError(f"line decoded to {len(out)} units, want {nunits}")
    return out


def decode_band(data: bytes, trace: bool = False, copy_distance: int | None = None):
    """Return (method, unit, bytes_per_line, rows as 1-bit bytes)."""
    if sum(data) & 0xFF:
        raise FormatError("checksum mismatch")
    magic, mu, bpl, nrows, total = struct.unpack_from(">HHHHI", data, 0)
    if magic != 4 or total != len(data):
        raise FormatError(f"bad band header magic={magic} total={total} len={len(data)}")
    method, unit = mu >> 8, mu & 0xFF
    width_bits = bpl * 8
    nunits = -(-width_bits // unit)
    p = 12
    prev_len = 0
    prev = [0] * nunits
    rows = []
    traces = []
    for _ in range(nrows):
        pl, ln = struct.unpack_from(">HH", data, p)
        if pl != prev_len:
            raise FormatError(f"back link {pl} != {prev_len}")
        p += 4
        line = data[p : p + ln]
        p += (ln + 3) & ~3
        tr: list = []
        units = decode_line(line, method, unit, nunits, prev, tr if trace else None, copy_distance)
        traces.append(tr)
        rows.append(units_to_bits(units, unit, width_bits))
        prev = units
        prev_len = ln
    pl, nxt = struct.unpack_from(">HH", data, p)
    if pl != prev_len or nxt != 0 or p + 5 != len(data):
        raise FormatError(f"bad trailer at {p}: {pl} {nxt}, len {len(data)}")
    return (method, unit, bpl, rows, traces) if trace else (method, unit, bpl, rows)
