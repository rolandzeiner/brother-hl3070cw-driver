"""Brother's "Fine" (600x2400 dpi class) line format: decoder and encoder.

Fine bands carry 4 bits per pixel. A line is a sequence of one-byte tokens,
each expanding to whole bytes of the line, plus repeat headers that repeat
or interleave tokens (see docs/FORMAT.md, "Fine").

    decode_line(data, bpl)  -> line bytes             exact, checked against
                                                      Brother's output
    tokenize(line)          -> plain tokens           matches Brother's tokens
    encode_tokens(tokens)   -> encoded line           a model of Brother's
                                                      header choice (close,
                                                      not exact; see FORMAT.md)
    encode_line(line)       -> encoded line

Every encoding this module produces decodes back to the line it was given.
"""

from __future__ import annotations

V = (2, 4, 6, 8, 10, 12, 14, 15)  # nibble values of the 3-bit code q
QV = {v: q for q, v in enumerate(V)}

# header byte -> (fixed tokens, fresh tokens per period, count offset)
HEADERS = {0x03: (1, 0, 6), 0x07: (2, 0, 5), 0x0F: (3, 0, 3),
           0x09: (1, 1, 4), 0x0B: (1, 2, 4), 0x0D: (2, 1, 3)}
KIND = {"R1": 0x03, "R2": 0x07, "R3": 0x0F, "I11": 0x09, "I12": 0x0B, "I21": 0x0D}
SHAPE = {k: HEADERS[h] for k, h in KIND.items()}
MAX_COUNT = 1024  # Brother never repeats more than this in one header


class DecodeError(Exception):
    pass


# ---- decoder -------------------------------------------------------------------

def token_bytes(t: int) -> bytes:
    """Bytes produced by one plain token."""
    hi = t >> 4
    if hi == 1:                                   # 0001 c kkk: k+1 bytes of 00 / FF
        return bytes([0xFF if t & 8 else 0]) * ((t & 7) + 1)
    if hi == 2:                                   # 0010 k qqq: k+1 zeros, (V, F)
        return bytes(((t >> 3) & 1) + 1) + bytes([V[t & 7] << 4 | 15])
    if hi == 3:                                   # 0011 k qqq: k+1 zeros, (0, V)
        return bytes(((t >> 3) & 1) + 1) + bytes([V[t & 7]])
    if t >> 6 == 1:                               # 01 hhh qqq: (2h, V)
        return bytes([((t >> 3) & 7) * 2 << 4 | V[t & 7]])
    top, k, q = t >> 5, (t >> 3) & 3, t & 7
    if top == 4:                                  # 100 kk qqq: k+1 FF, (2q, 0)
        return b"\xff" * (k + 1) + bytes([(2 * q) << 4])
    if top == 5:                                  # 101 kk qqq: k zeros, (V, 0)
        return bytes(k) + bytes([V[q] << 4])
    if top == 6:                                  # 110 kk qqq: k FF, (F, 2q)
        return b"\xff" * k + bytes([0xF0 | 2 * q])
    if top == 7:                                  # 111 kk qqq: k+1 FF, (2q, F)
        return b"\xff" * (k + 1) + bytes([(2 * q) << 4 | 15])
    raise DecodeError(f"0x{t:02x} is a header, not a token")


def read_count(d: bytes, i: int) -> tuple[int, int]:
    n = d[i]
    i += 1
    total = n
    if n == 0xFF:
        while True:
            b = d[i]
            i += 1
            total += b
            if b != 0xFF:
                break
    return total, i


def tokens(d: bytes) -> list[int]:
    """Expand the headers of an encoded line into plain tokens."""
    i, out = 0, []
    try:
        while i < len(d):
            t = d[i]
            if t >> 4:
                out.append(t)
                i += 1
                continue
            if t not in HEADERS:
                raise DecodeError(f"unknown header 0x{t:02x} at {i}")
            fixed, fresh, off = HEADERS[t]
            n, i = read_count(d, i + 1)
            n += off
            group = list(d[i:i + fixed])
            i += fixed
            for _ in range(n):
                out += group
                for _ in range(fresh):
                    out.append(d[i])
                    i += 1
            if any(x >> 4 == 0 for x in out[-n * (fixed + fresh):]):
                raise DecodeError("header inside a repeat")
    except IndexError:
        raise DecodeError("line ends inside a header") from None
    return out


def decode_line(d: bytes, bpl: int) -> bytes:
    line = b"".join(token_bytes(t) for t in tokens(d))
    if len(line) != bpl:
        raise DecodeError(f"line decodes to {len(line)} bytes, want {bpl}")
    return line


# ---- encoder, stage 1: bytes -> tokens (exact) ------------------------------------

def _runs(fill: int, n: int) -> list[int]:
    out = []
    while n > 8:
        out.append(0x10 | (8 if fill else 0) | 7)
        n -= 8
    if n:
        out.append(0x10 | (8 if fill else 0) | (n - 1))
    return out


def _edge(b: int) -> int:
    """Token for an edge byte with no run in front of it."""
    h, l = b >> 4, b & 15
    if h == 15 and l % 2 == 0:
        return 0xC0 | l // 2
    if l == 0 and h in QV:
        return 0xA0 | QV[h]
    if h % 2 == 0 and l in QV:
        return 0x40 | (h // 2) << 3 | QV[l]
    raise ValueError(f"byte 0x{b:02x} has an odd partial nibble")


def tokenize(line: bytes) -> list[int]:
    out: list[int] = []
    i, n = 0, len(line)
    while i < n:
        b = line[i]
        if b not in (0, 0xFF):
            out.append(_edge(b))
            i += 1
            continue
        j = i
        while j < n and line[j] == b:
            j += 1
        run = j - i
        if j == n:
            out += _runs(b, run)
            break
        e = line[j]
        h, l = e >> 4, e & 15
        if b == 0:
            if e == 0xFF:                      # FF after zeros: an edge only after 1-2 zeros
                if run > 2:
                    out += _runs(0, run)
                    i = j
                else:
                    out.append(0x20 | (run - 1) << 3 | 7)
                    i = j + 1
                continue
            if l == 0 and h in QV:             # (V,0) takes up to 3 zeros
                a = min(run, 3)
                out += _runs(0, run - a) + [0xA0 | a << 3 | QV[h]]
            elif h == 0 and l in QV:           # (0,V) takes up to 2
                a = min(run, 2)
                out += _runs(0, run - a) + [0x30 | (a - 1) << 3 | QV[l]]
            elif l == 15 and h in QV:          # (V,F) takes up to 2
                a = min(run, 2)
                out += _runs(0, run - a) + [0x20 | (a - 1) << 3 | QV[h]]
            else:
                out += _runs(0, run)
                i = j
                continue
            i = j + 1
            continue
        # a run of FF
        if e == 0:                             # FF..FF 00: only when the whole run fits
            if run <= 4:
                out.append(0x80 | (run - 1) << 3)
                i = j + 1
            else:
                out += _runs(0xFF, run)
                i = j
            continue
        if h == 15 and l % 2 == 0:             # (F,e) takes up to 3
            a = min(run, 3)
            out += _runs(0xFF, run - a) + [0xC0 | a << 3 | l // 2]
        elif l == 0 and h % 2 == 0:            # (e,0) takes up to 4
            a = min(run, 4)
            out += _runs(0xFF, run - a) + [0x80 | (a - 1) << 3 | h // 2]
        elif l == 15 and h % 2 == 0:           # (e,F) takes up to 4
            a = min(run, 4)
            out += _runs(0xFF, run - a) + [0xE0 | (a - 1) << 3 | h // 2]
        else:
            out += _runs(0xFF, run)
            i = j
            continue
        i = j + 1
    return out


# ---- encoder, stage 2: header choice (a fitted model) -----------------------------

ORDER_FULL = ("R3", "R2", "I11", "I21", "I12")   # candidates covering >= 12 tokens
ORDER_SHORT = ("R3", "R2", "I21", "I11", "I12")  # shorter ones, taken at these counts
MIN_SHORT = {"R2": 5, "R3": 3, "I11": 4, "I12": 4, "I21": 3}
NEAR_MISS = {"R3": 2, "R2": 2, "I21": 2, "I11": 3}  # below MIN_SHORT: written out as literals


def count(t: list[int], i: int, kind: str) -> int:
    """Periods of a header kind that fit at token i (at most MAX_COUNT)."""
    fixed, fresh, _ = SHAPE[kind]
    p, n, k = fixed + fresh, len(t), 0
    head = t[i:i + fixed]
    while k < MAX_COUNT and i + (k + 1) * p <= n and t[i + k * p:i + k * p + fixed] == head:
        k += 1
    if kind == "R2" and i + 1 < n and t[i] == t[i + 1]:
        return 0  # two equal tokens are a run, never a pair
    return k


def covered(kind: str, c: int) -> int:
    fixed, fresh, _ = SHAPE[kind]
    return c * (fixed + fresh)


def header_bytes(kind: str, c: int) -> int:
    fixed, fresh, off = SHAPE[kind]
    nn = c - off
    ext = 0 if nn < 255 else 1 + (nn - 255) // 255
    return 2 + ext + fixed + c * fresh


def savings(kind: str, c: int) -> int:
    return covered(kind, c) - header_bytes(kind, c)


def _best_full(t, i):
    if i >= len(t):
        return None
    for k in ORDER_FULL:
        c = count(t, i, k)
        if covered(k, c) >= 12:
            return k, c
    return None


def _emit(out: list[int], t: list[int], i: int, kind: str, c: int) -> int:
    fixed, fresh, off = SHAPE[kind]
    nn = c - off
    out.append(KIND[kind])
    if nn < 255:
        out.append(nn)
    else:
        out.append(255)
        nn -= 255
        while nn >= 255:
            out.append(255)
            nn -= 255
        out.append(nn)
    out += t[i:i + fixed]
    if fresh:
        for k in range(c):
            base = i + k * (fixed + fresh) + fixed
            out += t[base:base + fresh]
    return i + c * (fixed + fresh)


def encode_tokens(t: list[int]) -> bytes:
    out: list[int] = []
    i, n = 0, len(t)
    while i < n:
        r = count(t, i, "R1")
        if r >= 12:                                  # long runs always
            i = _emit(out, t, i, "R1", r)
            continue
        b = _best_full(t, i)
        if b:                                        # anything covering 12 tokens
            if b[0] == "I12":                        # ... looking two tokens further
                nb = _best_full(t, i + 2)
                if nb and savings(*nb) >= savings(*b):
                    out += t[i:i + 2]
                    i += 2
                    b = nb
            i = _emit(out, t, i, *b)
            continue
        if r >= 6:                                   # a run of 6 to 11: thirds or literals
            c = count(t, i, "R3")
            if c >= MIN_SHORT["R3"]:
                i = _emit(out, t, i, "R3", c)
                continue
        span = 0
        for k in ORDER_SHORT:                        # the first kind that fits decides
            c = count(t, i, k)
            if r < 6 and c >= MIN_SHORT[k]:
                if i + 2 < n and count(t, i + 2, "R1") >= 3:
                    break                            # a run two tokens on wins: literals
                i = _emit(out, t, i, k, c)
                span = -1
                break
            if c >= NEAR_MISS.get(k, MAX_COUNT + 1):
                span = covered(k, c)                 # a near miss: its tokens as literals
                break
        if span < 0:
            continue
        if not span:
            span = r if r >= 3 else 1
        span = min(span, n - i)
        out += t[i:i + span]
        i += span
    return bytes(out)


def encode_line(line: bytes) -> bytes:
    return encode_tokens(tokenize(line))
