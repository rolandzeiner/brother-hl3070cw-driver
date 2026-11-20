"""Candidate models of Brother's RGB -> CMYK step, tested against measurements."""
from __future__ import annotations


def tetra(T, r, g, b, rnd=8, sh=4):
    """Tetrahedral interpolation, nodes every 16, weights in 1/16."""
    rk, gk, bk = r >> 4, g >> 4, b >> 4
    fr, fg, fb = r & 15, g & 15, b & 15
    c000 = T.node(rk, gk, bk)
    c111 = T.node(rk + 1, gk + 1, bk + 1)
    if fr >= fg >= fb:
        n1, n2 = T.node(rk + 1, gk, bk), T.node(rk + 1, gk + 1, bk)
        w = (16 - fr, fr - fg, fg - fb, fb)
    elif fr >= fb >= fg:
        n1, n2 = T.node(rk + 1, gk, bk), T.node(rk + 1, gk, bk + 1)
        w = (16 - fr, fr - fb, fb - fg, fg)
    elif fb >= fr >= fg:
        n1, n2 = T.node(rk, gk, bk + 1), T.node(rk + 1, gk, bk + 1)
        w = (16 - fb, fb - fr, fr - fg, fg)
    elif fg >= fr >= fb:
        n1, n2 = T.node(rk, gk + 1, bk), T.node(rk + 1, gk + 1, bk)
        w = (16 - fg, fg - fr, fr - fb, fb)
    elif fg >= fb >= fr:
        n1, n2 = T.node(rk, gk + 1, bk), T.node(rk, gk + 1, bk + 1)
        w = (16 - fg, fg - fb, fb - fr, fr)
    else:  # fb >= fg >= fr
        n1, n2 = T.node(rk, gk, bk + 1), T.node(rk, gk + 1, bk + 1)
        w = (16 - fb, fb - fg, fg - fr, fr)
    return tuple((w[0] * c000[i] + w[1] * n1[i] + w[2] * n2[i] + w[3] * c111[i] + rnd) >> sh for i in range(4))


def trilinear(T, r, g, b, rnd=2048):
    rk, gk, bk = r >> 4, g >> 4, b >> 4
    fr, fg, fb = r & 15, g & 15, b & 15
    acc = [0, 0, 0, 0]
    for dr, wr in ((0, 16 - fr), (1, fr)):
        for dg, wg in ((0, 16 - fg), (1, fg)):
            for db, wb in ((0, 16 - fb), (1, fb)):
                w = wr * wg * wb
                if w:
                    n = T.node(rk + dr, gk + dg, bk + db)
                    for i in range(4):
                        acc[i] += w * n[i]
    return tuple((a + rnd) >> 12 for a in acc)
