"""Write a one-page A4 test PDF: greys, gradient, lines, text sizes, colours.

    python3 -I tools/testpage.py out.pdf "Title" "line 1" "line 2" ...
"""
from __future__ import annotations
import datetime
import sys


def build(title: str, lines: list[str]) -> bytes:
    c = ["0 g"]

    def text(x, y, size, s, font="F1"):
        s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        c.append(f"BT /{font} {size} Tf {x} {y} Td ({s}) Tj ET")

    text(56, 770, 22, title, "F2")
    for i, ln in enumerate(lines + [datetime.date.today().isoformat() + "  -  github.com/rolandzeiner/brother-hl3070cw-driver"]):
        text(56, 744 - 16 * i, 11, ln)
    text(56, 670, 12, "Grey steps 0 % to 100 %", "F2")
    for i in range(11):
        c.append(f"{1 - i / 10:.2f} g {56 + i * 44} 600 40 56 re f")
        c.append("0 g")
        text(60 + i * 44, 588, 8, f"{i * 10}%")
    text(56, 556, 12, "Continuous gradient", "F2")
    for i in range(240):
        c.append(f"{1 - i / 239:.4f} g {56 + i * 2} 500 2.05 40 re f")
    c.append("0 g")
    text(56, 466, 12, "Lines 0.25 / 0.5 / 1 / 2 pt", "F2")
    for i, lw in enumerate((0.25, 0.5, 1, 2)):
        c.append(f"{lw} w 56 {440 - i * 14} m 539 {440 - i * 14} l S")
    text(56, 370, 12, "Text sizes", "F2")
    for i, sz in enumerate((6, 8, 10, 12, 16)):
        text(56, 350 - i * 22, sz, f"{sz} pt: The quick brown fox jumps over the lazy dog 0123456789")
    text(56, 200, 12, "Colour (should print as grey in Mono)", "F2")
    for i, (r, g, b) in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 1, 1), (1, 0, 1), (1, 1, 0))):
        c.append(f"{r} {g} {b} rg {56 + i * 70} 130 60 50 re f")
    stream = "\n".join(c).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(pdf))
        pdf += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(pdf)


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build(sys.argv[2], sys.argv[3:]))
