"""Black-box fit of Brother's colour interpolation weights (run with: uv run --no-project --with scipy --with numpy python tools/<this>.py <repo> <data dir>). Data: JSON from tools/measure_color.py."""
import sys, json
import numpy as np
from scipy.optimize import linprog
sys.path.insert(0, sys.argv[1] + "/tools")
import colortables as ct
S = sys.argv[2]
T = [t for t in ct.load() if "600dpi ImpGray=ON" in t.name and "Match Monitor" in t.name][0]
def pos(x): return (15, 16) if x == 255 else (x >> 4, x & 15)
obs = [(c, lv) for c, lv in json.load(open(S + "/random3d.json"))] + [(c, lv) for c, m, lv in json.load(open(S + "/edges.json"))]
for name, rows in json.load(open(S + "/ramps.json")).items(): obs += [(c, lv) for c, lv in rows]
meas_order = (1, 2, 3, 0)
def build(group, model):
    A_ub, b_ub, wi_bad = [], [], 0
    for c, lv in obs:
        if tuple(c) == (255, 255, 255) or c[0] == c[1] == c[2]: continue
        ks, fs = zip(*(pos(x) for x in c))
        if sum(1 for f in fs if f not in (0, 16)) != group: continue
        order = sorted(range(3), key=lambda i: -fs[i]); cur = list(ks); nodes = [tuple(cur)]
        for i in order: cur[i] += 1; nodes.append(tuple(cur))
        N = [T.node(*n) for n in nodes]; f = [fs[i] for i in order]
        w = [16 - f[0], f[0] - f[1], f[1] - f[2], f[2]]
        for p in range(4):
            const = sum(wi * n[p] for wi, n in zip(w, N)) / 16.0
            coef = np.zeros(15)
            if model == "axis":   # value = N0 + sum_j (N_{j+1}-N_j) * w(f_j), w(f) = f/16 + e(f)
                for j in range(3):
                    if 1 <= f[j] <= 15: coef[f[j] - 1] += N[j + 1][p] - N[j][p]
            else:                 # value = sum_i T(w_i) N_i, T(d) = d/16 + e(d)
                for wi, n in zip(w, N):
                    if 1 <= wi <= 15: coef[wi - 1] += n[p]
            ms = lv[meas_order[p]]; lo, hi = min(ms) - 0.5, max(ms) + 0.5
            if not coef.any():
                wi_bad += not (lo <= const < hi); continue
            A_ub.append(-coef); b_ub.append(const - lo)
            A_ub.append(coef); b_ub.append(hi - const - 1e-9)
    return np.array(A_ub), np.array(b_ub), wi_bad
for group in (1, 2, 3):
    for model in ("axis", "diff"):
        A, b, wib = build(group, model)
        m = len(b)
        cc = np.concatenate([np.zeros(15), np.ones(m)])
        rr = linprog(cc, A_ub=np.hstack([A, -np.eye(m)]), b_ub=b, bounds=[(-0.005, 0.005)] * 15 + [(0, None)] * m, method="highs")
        viol = int((rr.x[15:] > 1e-6).sum())
        print(f"group {group} ({'edges' if group == 1 else 'faces' if group == 2 else 'interior'}), model {model}: constraints {m}, weight-independent misses {wib}, violated {viol}, slack {rr.fun:.4f}")
