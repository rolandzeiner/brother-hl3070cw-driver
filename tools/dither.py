"""Brother "BRCD" dither cache files: one 1-bit tile per input level.

File layout: b"BRCD", b"0\\0", u16 LE width, u16 LE height, then 256 tiles of
height rows x ceil(width / 8) bytes, MSB first, tile index = toner level.
"""
from __future__ import annotations
import struct

LUT_DIR = "/Library/Printers/Brother/Brother LUT/"


class Cache:
    def __init__(self, path: str):
        d = open(path, "rb").read()
        if d[:4] != b"BRCD":
            raise ValueError(f"{path}: not a BRCD file")
        self.w, self.h = struct.unpack_from("<HH", d, 6)
        self.stride = (self.w + 7) // 8
        self.tile = self.h * self.stride
        self.body = d[10:]
        if len(self.body) != 256 * self.tile:
            raise ValueError(f"{path}: {len(self.body)} bytes, want {256 * self.tile}")

    def bit(self, level: int, x: int, y: int) -> int:
        x %= self.w
        y %= self.h
        b = self.body[level * self.tile + y * self.stride + (x >> 3)]
        return (b >> (7 - (x & 7))) & 1
