"""Black-box fit of Brother's colour interpolation weights (run with: uv run --no-project --with scipy --with numpy python tools/<this>.py <repo> <data dir>). Data: JSON from tools/measure_color.py."""
import sys, json
import numpy as np
from scipy.optimize import linprog
sys.path.insert(0, sys.argv[1] + "/tools")
import colortables as ct
S = sys.argv[2]
per_channel = len(sys.argv) > 3 and sys.argv[3] == "perchannel"
T = [t for t in ct.load() if "600dpi ImpGray=ON" in t.name and "Match Monitor" in t.name][0]
BASE = [1, 2, 3, 5, 6, 7]
nvar = 6 * (3 if per_channel else 1)
def eps_vec(f, ch):
    """coefficient vector so that eps(f) = vec . e"""
    v = np.zeros(nvar)
    off = 6 * ch if per_channel else 0
    if f in (0, 4, 8, 12, 16): return v
    if f in BASE: v[off + BASE.index(f)] = 1.0
    else: v[off + BASE.index(16 - f)] = -1.0
    return v
def pos(x): return (15, 16) if x == 255 else (x >> 4, x & 15)
obs = []
for c, lv in json.load(open(S + "/random3d.json")): obs.append((c, lv))
for c, m, lv in json.load(open(S + "/edges.json")): obs.append((c, lv))
rd = json.load(open(S + "/ramps.json"))
for name, rows in rd.items():
    for c, lv in rows: obs.append((c, lv))
meas_order = (1, 2, 3, 0)
A_ub, b_ub = [], []
skipped = 0
for c, lv in obs:
    if tuple(c) == (255, 255, 255): continue
    ks, fs = zip(*(pos(x) for x in c))
    order = sorted(range(3), key=lambda i: -fs[i])
    cur = list(ks); nodes = [tuple(cur)]
    for i in order: cur[i] += 1; nodes.append(tuple(cur))
    N = [T.node(*n) for n in nodes]
    for p in range(4):
        # value = N0 + wa (N1-N0) + wb (N2-N1) + wc (N3-N2), w = f/16 + eps
        const = N[0][p]; coef = np.zeros(nvar)
        for j, ax in enumerate(order):
            d = N[j + 1][p] - N[j][p]
            const += d * fs[ax] / 16.0
            coef += d * eps_vec(fs[ax], ax)
        ms = lv[meas_order[p]]
        lo, hi = min(ms) - 0.5, max(ms) + 0.5
        if not coef.any():
            if not (lo <= const < hi): skipped += 1
            continue
        # lo <= const + coef.e < hi   ->   -coef.e <= const - lo ; coef.e <= hi - const - tiny
        A_ub.append(-coef); b_ub.append(const - lo)
        A_ub.append(coef); b_ub.append(hi - const - 1e-9)
A_ub = np.array(A_ub); b_ub = np.array(b_ub)
print("constraints:", len(b_ub), "exact-only observations violating the base rounding:", skipped)
bounds = [(-0.01, 0.01)] * nvar
res = linprog(np.zeros(nvar), A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
print("feasible:", res.status == 0, res.message)
if res.status == 0:
    for i in range(nvar):
        lo = linprog(np.eye(nvar)[i], A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs").x[i]
        hi = linprog(-np.eye(nvar)[i], A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs").x[i]
        ch = "RGB"[i // 6] if per_channel else "all"
        f = BASE[i % 6]
        print(f"  {ch} eps({f:2d}) in [{lo*16:+.6f}, {hi*16:+.6f}] /16   -> w*16 in [{f+lo*16:.6f}, {f+hi*16:.6f}]")
else:
    # find how many constraints must be dropped: minimise slack sum
    m = len(b_ub)
    c = np.concatenate([np.zeros(nvar), np.ones(m)])
    A = np.hstack([A_ub, -np.eye(m)])
    r = linprog(c, A_ub=A, b_ub=b_ub, bounds=bounds + [(0, None)] * m, method="highs")
    viol = int((r.x[nvar:] > 1e-7).sum())
    print("min total slack", r.fun, "violated constraints at optimum:", viol)
