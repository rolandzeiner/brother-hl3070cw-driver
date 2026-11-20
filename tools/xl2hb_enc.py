"""Reference encoder for XL2HB method-2 lines, tuned to match Brother's output.

Kept in Python so the rules can be compared against Brother's filter quickly;
src/ holds the C port used by the real driver.
"""

from __future__ import annotations

COPY_DIST = 2  # method 2


class BitWriter:
    def __init__(self) -> None:
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value: int, bits: int) -> None:
        for i in range(bits - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> i) & 1)
            self.n += 1
            if self.n == 8:
                self.out.append(self.acc)
                self.acc = 0
                self.n = 0

    def align(self) -> None:
        if self.n:
            self.put(0, 8 - self.n)

    def ext(self, value: int) -> None:
        while value >= 255:
            self.put(255, 8)
            value -= 255
        self.put(value, 8)


def _repeat(w: BitWriter, unit_value: int, count: int, unit_bits: int) -> None:
    if count <= 7:
        w.put(0x8 | (count - 1), 4)
        w.put(unit_value, unit_bits)
    else:
        w.put(0xF, 4)
        w.put(unit_value, unit_bits)
        w.align()
        w.ext(count - 8)


def _literal(w: BitWriter, units: list[int], unit_bits: int) -> None:
    n = len(units)
    if n == 1:
        _repeat(w, units[0], 1, unit_bits)
        return
    if n - 2 < 63:
        w.put(0x40 | (n - 2), 8)
    else:
        w.put(0x7F, 8)
        w.ext(n - 65)
    for u in units:
        w.put(u, unit_bits)
    w.align()


def _copy(w: BitWriter, count: int) -> None:
    if count - 1 < 63:
        w.put(count - 1, 8)
    else:
        w.put(0x3F, 8)
        w.ext(count - 64)


def encode_line(units: list[int], unit_bits: int = 12) -> bytes:
    w = BitWriter()
    n = len(units)
    i = 0
    lit: list[int] = []

    def flush() -> None:
        while lit:
            chunk = lit[:]
            lit.clear()
            _literal(w, chunk, unit_bits)

    while i < n:
        # length of a run of identical units starting at i
        run = 1
        while i + run < n and units[i + run] == units[i]:
            run += 1
        if run >= 2:
            flush()
            _repeat(w, units[i], run, unit_bits)
            i += run
            continue
        # length of a match with the units two places back
        cp = 0
        while i + cp < n and i + cp - COPY_DIST >= 0 and units[i + cp] == units[i + cp - COPY_DIST]:
            cp += 1
        if cp >= 2:
            flush()
            _copy(w, cp)
            i += cp
            continue
        lit.append(units[i])
        i += 1
    flush()
    return bytes(w.out)
