"""Collect Brother's encodings (both methods) for hand-made 1-bit rows.

    python3 -I tools/explore.py   # edits the CASES list below
"""
from __future__ import annotations
import collections, os, struct, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import oracle, pxl, rasterwrite as rw, roundtrip  # noqa: E402

def variants(rows: list[bytes], tries: int = 12, size: str = "A6", options: str = "BRMonoColor=Mono"):
    width, _ = rw.page_geometry(size)
    content = dict(enumerate(rows))
    def source(y, w, h):
        return roundtrip.rgb_row(content[y], w) if y in content else rw.WHITE * w
    out = collections.OrderedDict()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "in.ras")
        rw.write(path, size, [source])
        for _ in range(tries):
            job = pxl.parse(oracle.run(path, options))
            for start, h, mode, data in job.images():
                mu = struct.unpack_from(">H", data, 2)[0]
                lines, p = [], 12
                for _ in range(struct.unpack_from(">H", data, 6)[0]):
                    pl, ln = struct.unpack_from(">HH", data, p); p += 4
                    lines.append(data[p:p+ln].hex(" ")); p += (ln + 3) & ~3
                out.setdefault((start, f"{mu >> 8}/{mu & 0xff}", tuple(lines)), 0)
                out[(start, f"{mu >> 8}/{mu & 0xff}", tuple(lines))] += 1
    return out

def row_from_units(vals, unit=12, width=2275):
    row = bytearray((width + 7) // 8)
    for k, v in enumerate(vals):
        for i in range(unit):
            if (v >> (unit - 1 - i)) & 1:
                x = k * unit + i
                if x < width:
                    row[x >> 3] |= 0x80 >> (x & 7)
    return bytes(row)

if __name__ == "__main__":
    import ast
    for spec in sys.argv[1:]:
        vals = ast.literal_eval(spec)
        print("units", spec)
        for (start, mu, lines), n in variants([row_from_units(vals)]).items():
            print(f"   x{n:2d} m{mu:5s} {' / '.join(lines)}")
