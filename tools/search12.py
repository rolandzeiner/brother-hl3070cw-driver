"""Black-box fit of Brother's colour interpolation weights (run with: uv run --no-project --with scipy --with numpy python tools/<this>.py <repo> <data dir>). Data: JSON from tools/measure_color.py."""
import sys, json, itertools
sys.path.insert(0, sys.argv[1] + "/tools")
import colortables as ct
S = sys.argv[2]
T = [t for t in ct.load() if "600dpi ImpGray=ON" in t.name and "Match Monitor" in t.name][0]
def pos(x): return (15, 16) if x == 255 else (x >> 4, x & 15)
meas_order = (1, 2, 3, 0)
data = []
src = [(c, lv) for c, lv in json.load(open(S + "/random3d.json"))] + [(c, lv) for c, m, lv in json.load(open(S + "/edges.json"))]
for c, lv in src:
    if tuple(c) == (255, 255, 255) or c[0] == c[1] == c[2]: continue
    ks, fs = zip(*(pos(x) for x in c))
    order = sorted(range(3), key=lambda i: -fs[i]); cur = list(ks); nodes = [tuple(cur)]
    for i in order: cur[i] += 1; nodes.append(tuple(cur))
    N = [T.node(*n) for n in nodes]; f = [fs[i] for i in order]
    nfr = sum(1 for x in f if x not in (0, 16))
    for p in range(4):
        data.append((nfr, f, [n[p] for n in N], set(lv[meas_order[p]])))
data.sort(key=lambda d: -d[0])   # interior first: fails fastest
def make_W(e):
    W = [256 * f for f in range(17)]
    for f, v in e.items(): W[f] += v; W[16 - f] -= v
    return W
def val(form, prod, W, f, N):
    if form == "axis":       # N0 + sum (N_{j+1}-N_j) W(f_j)
        terms = [(N[j + 1] - N[j]) * W[f[j]] for j in range(3)]
        base = N[0] * 4096
    else:                    # per-difference node weights
        w = [W[16 - f[0]], W[f[0] - f[1]], W[f[1] - f[2]], W[f[2]]]
        terms = [N[i] * w[i] for i in range(4)]
        base = 0
    if prod == "exact":
        return (base + sum(terms) + 2048) >> 12
    if prod == "floor":
        return ((base >> 4) + sum(t >> 4 for t in terms) + 128) >> 8
    return ((base >> 4) + sum((t + 8) >> 4 for t in terms) + 128) >> 8
ranges = {1: range(-4, 0), 2: range(-6, 0), 3: range(5, 7), 5: range(1, 6), 6: range(-5, 0), 7: range(1, 6)}
results = []
for form in ("axis", "diff"):
    for prod in ("exact", "floor", "round"):
        best = None
        for combo in itertools.product(*ranges.values()):
            e = dict(zip(ranges.keys(), combo))
            W = make_W(e)
            bad = 0
            for nfr, f, N, ms in data:
                if val(form, prod, W, f, N) not in ms:
                    bad += 1
                    if best is not None and bad >= best[0]: break
            if best is None or bad < best[0]:
                best = (bad, e)
                if bad == 0: break
        print(f"form={form:4s} products={prod:5s}: best misses {best[0]} with e={best[1]}", flush=True)
