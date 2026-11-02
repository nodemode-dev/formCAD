import math
from dataclasses import dataclass, field

import numpy as np

MAX_FIT_POINTS = 2000
SAMPLES_PER_SPAN = 24
KNOT_CHORD, KNOT_SQRT, KNOT_UNIFORM = 0, 1, 2


@dataclass
class Curve:
    degree: int
    knots: list
    ctrl: list
    weights: list = field(default_factory=list)
    closed: bool = False

    def domain(self):
        return self.knots[self.degree], self.knots[len(self.ctrl)]

    def valid(self) -> bool:
        p, n = self.degree, len(self.ctrl)
        if p < 1 or n < p + 1 or len(self.knots) != n + p + 1:
            return False
        if self.weights and len(self.weights) != n:
            return False
        if any(self.knots[i] > self.knots[i + 1] for i in range(len(self.knots) - 1)):
            return False
        return self.knots[n] > self.knots[p]


def find_span(nc: int, p: int, u: float, U: list) -> int:
    n = nc - 1
    if u >= U[n + 1]:
        return n
    if u <= U[p]:
        return p
    lo, hi = p, n + 1
    mid = (lo + hi) // 2
    while u < U[mid] or u >= U[mid + 1]:
        if u < U[mid]:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) // 2
    return mid


def basis_funs(span: int, u: float, p: int, U: list) -> list:
    N = [0.0] * (p + 1)
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    N[0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            temp = N[r] / den if den != 0.0 else 0.0
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N


def ders_basis(span: int, u: float, p: int, nd: int, U: list) -> list:
    ndu = [[0.0] * (p + 1) for _ in range(p + 1)]
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    ndu[0][0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            ndu[j][r] = right[r + 1] + left[j - r]
            temp = ndu[r][j - 1] / ndu[j][r] if ndu[j][r] != 0.0 else 0.0
            ndu[r][j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j][j] = saved
    ders = [[0.0] * (p + 1) for _ in range(nd + 1)]
    for j in range(p + 1):
        ders[0][j] = ndu[j][p]
    a = [[0.0] * (p + 1), [0.0] * (p + 1)]
    for r in range(p + 1):
        s1, s2 = 0, 1
        a[0][0] = 1.0
        for k in range(1, nd + 1):
            d = 0.0
            rk = r - k
            pk = p - k
            if r >= k:
                a[s2][0] = a[s1][0] / ndu[pk + 1][rk] if ndu[pk + 1][rk] != 0.0 else 0.0
                d = a[s2][0] * ndu[rk][pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if r - 1 <= pk else p - r
            for j in range(j1, j2 + 1):
                a[s2][j] = (a[s1][j] - a[s1][j - 1]) / ndu[pk + 1][rk + j] if ndu[pk + 1][rk + j] != 0.0 else 0.0
                d += a[s2][j] * ndu[rk + j][pk]
            if r <= pk:
                a[s2][k] = -a[s1][k - 1] / ndu[pk + 1][r] if ndu[pk + 1][r] != 0.0 else 0.0
                d += a[s2][k] * ndu[r][pk]
            ders[k][r] = d
            s1, s2 = s2, s1
    r = float(p)
    for k in range(1, nd + 1):
        for j in range(p + 1):
            ders[k][j] *= r
        r *= p - k
    return ders


def point_at(c: Curve, u: float) -> list:
    p, nc = c.degree, len(c.ctrl)
    lo, hi = c.domain()
    u = min(max(u, lo), hi)
    span = find_span(nc, p, u, c.knots)
    N = basis_funs(span, u, p, c.knots)
    x = y = z = w = 0.0
    for j in range(p + 1):
        i = span - p + j
        q = c.ctrl[i]
        wt = c.weights[i] if c.weights else 1.0
        f = N[j] * wt
        x += f * q[0]
        y += f * q[1]
        z += f * (q[2] if len(q) > 2 else 0.0)
        w += f
    if w == 0.0:
        w = 1.0
    return [x / w, y / w, z / w]


def tangent_at(c: Curve, u: float) -> list:
    p, nc = c.degree, len(c.ctrl)
    lo, hi = c.domain()
    u = min(max(u, lo), hi)
    span = find_span(nc, p, u, c.knots)
    D = ders_basis(span, u, p, 1, c.knots)
    if not c.weights:
        d = [0.0, 0.0, 0.0]
        for j in range(p + 1):
            q = c.ctrl[span - p + j]
            for k in range(3):
                d[k] += D[1][j] * (q[k] if k < len(q) else 0.0)
        return d
    a = [0.0] * 3
    da = [0.0] * 3
    w = dw = 0.0
    for j in range(p + 1):
        i = span - p + j
        q = c.ctrl[i]
        wt = c.weights[i]
        for k in range(3):
            v = q[k] if k < len(q) else 0.0
            a[k] += D[0][j] * wt * v
            da[k] += D[1][j] * wt * v
        w += D[0][j] * wt
        dw += D[1][j] * wt
    pt = [a[k] / w for k in range(3)]
    return [(da[k] - dw * pt[k]) / w for k in range(3)]


def spans(c: Curve) -> list:
    lo, hi = c.domain()
    ks = sorted({k for k in c.knots if lo <= k <= hi})
    return ks


def sample_params(c: Curve, per_span: int = SAMPLES_PER_SPAN, cap: int = 60000) -> list:
    ks = spans(c)
    if len(ks) < 2:
        return [c.domain()[0]]
    per = max(2, min(per_span, cap // max(len(ks) - 1, 1)))
    out = []
    for a, b in zip(ks, ks[1:]):
        for i in range(per):
            out.append(a + (b - a) * i / per)
    out.append(ks[-1])
    return out


def sample(c: Curve, per_span: int = SAMPLES_PER_SPAN) -> list:
    return [point_at(c, u) for u in sample_params(c, per_span)]


def length_table(c: Curve, per_span: int = 96):
    us = sample_params(c, per_span)
    pts = [point_at(c, u) for u in us]
    acc = [0.0]
    for a, b in zip(pts, pts[1:]):
        acc.append(acc[-1] + math.dist(a, b))
    return us, pts, acc


def clamped_uniform(nc: int, p: int) -> list:
    inner = max(nc - p - 1, 0)
    return [0.0] * (p + 1) + [float(i + 1) for i in range(inner)] + [float(inner + 1)] * (p + 1)


def periodic_uniform(n_unique: int, p: int) -> list:
    return [float(i - p) for i in range(n_unique + 2 * p + 1)]


def from_control_points(pts: list, degree: int = 3, closed: bool = False, weights=None) -> Curve:
    pts = [list(p) + [0.0] * (3 - len(p)) for p in pts]
    if closed:
        n = len(pts)
        p = max(1, min(degree, n - 1)) if n > 1 else 1
        ctrl = pts + [list(q) for q in pts[:p]]
        w = None
        if weights:
            w = list(weights) + list(weights[:p])
        return Curve(p, periodic_uniform(n, p), ctrl, w or [], True)
    p = max(1, min(degree, len(pts) - 1))
    return Curve(p, clamped_uniform(len(pts), p), pts, list(weights) if weights else [], False)


def parameters(pts: list, kind: int, closed: bool = False) -> list:
    n = len(pts)
    seq = list(pts) + ([pts[0]] if closed else [])
    steps = []
    for a, b in zip(seq, seq[1:]):
        d = math.dist(a, b)
        steps.append(d if kind == KNOT_CHORD else math.sqrt(d) if kind == KNOT_SQRT else 1.0)
    total = sum(steps)
    out = [0.0]
    for s in steps:
        out.append(out[-1] + s)
    if total <= 0:
        return [float(i) for i in range(len(seq))]
    if not closed:
        return [v / total for v in out]
    return out


def dedupe(pts: list, tol: float = 1e-9) -> list:
    out = []
    for p in pts:
        if not out or math.dist(out[-1], p) > tol:
            out.append(p)
    return out


def _tan3(t):
    return list(t) + [0.0] * (3 - len(t))


def interpolate_open(pts: list, kind: int, t0=None, t1=None) -> Curve:
    m = len(pts)
    p = 3
    ub = parameters(pts, kind)
    U = [ub[0]] * 4 + [ub[j] for j in range(1, m - 1)] + [ub[-1]] * 4
    nc = m + 2
    A = np.zeros((nc, nc))
    R = np.zeros((nc, 3))
    for k in range(m):
        span = find_span(nc, p, ub[k], U)
        N = basis_funs(span, ub[k], p, U)
        A[k, span - p : span + 1] = N
        R[k] = pts[k]
    span0 = find_span(nc, p, ub[0], U)
    D0 = ders_basis(span0, ub[0], p, 2, U)
    span1 = find_span(nc, p, ub[-1], U)
    D1 = ders_basis(span1, ub[-1], p, 2, U)
    if t0 is not None:
        sp = (ub[1] - ub[0]) or 1.0
        mag = math.dist(pts[0], pts[1]) / sp
        n = math.sqrt(sum(v * v for v in t0)) or 1.0
        A[m, span0 - p : span0 + 1] = D0[1]
        R[m] = [v / n * mag for v in _tan3(t0)]
    else:
        A[m, span0 - p : span0 + 1] = D0[2]
    if t1 is not None:
        sp = (ub[-1] - ub[-2]) or 1.0
        mag = math.dist(pts[-1], pts[-2]) / sp
        n = math.sqrt(sum(v * v for v in t1)) or 1.0
        A[m + 1, span1 - p : span1 + 1] = D1[1]
        R[m + 1] = [v / n * mag for v in _tan3(t1)]
    else:
        A[m + 1, span1 - p : span1 + 1] = D1[2]
    P = np.linalg.solve(A, R)
    return Curve(p, U, [list(map(float, row)) for row in P], [], False)


def interpolate_closed(pts: list, kind: int) -> Curve:
    m = len(pts)
    p = 3
    u = parameters(pts, kind, True)
    T = u[m] - u[0]
    U = [0.0] * (m + 2 * p + 1)
    for k in range(m + 1):
        U[p + k] = u[k]
    for i in range(1, p + 1):
        U[p - i] = U[p - i + m] - T
        U[p + m + i] = U[p + i] + T
    nc = m + p
    A = np.zeros((m, m))
    for k in range(m):
        span = find_span(nc, p, u[k], U)
        N = basis_funs(span, u[k], p, U)
        for j in range(p + 1):
            A[k, (span - p + j) % m] += N[j]
    P = np.linalg.solve(A, np.array(pts, dtype=float))
    ctrl = [list(map(float, row)) for row in P]
    ctrl = ctrl + [list(q) for q in ctrl[:p]]
    return Curve(p, U, ctrl, [], True)


def approximate_open(pts: list, kind: int, tol: float) -> Curve:
    m = len(pts)
    p = 3
    ub = parameters(pts, kind)
    Q = np.array(pts, dtype=float)
    nc = p + 1
    while nc < m:
        d = m / (nc - p)
        inner = []
        for j in range(1, nc - p):
            i = int(j * d)
            alpha = j * d - i
            inner.append((1 - alpha) * ub[i - 1] + alpha * ub[min(i, m - 1)])
        U = [0.0] * (p + 1) + inner + [1.0] * (p + 1)
        Nm = np.zeros((m, nc))
        for k in range(m):
            span = find_span(nc, p, ub[k], U)
            Nm[k, span - p : span + 1] = basis_funs(span, ub[k], p, U)
        R = Q - np.outer(Nm[:, 0], Q[0]) - np.outer(Nm[:, nc - 1], Q[-1])
        P = np.zeros((nc, 3))
        P[0], P[-1] = Q[0], Q[-1]
        if nc > 2:
            Ni = Nm[:, 1 : nc - 1]
            try:
                P[1 : nc - 1] = np.linalg.lstsq(Ni, R, rcond=None)[0]
            except np.linalg.LinAlgError:
                nc += 1
                continue
        cur = Curve(p, U, [list(map(float, r)) for r in P], [], False)
        dev = max(math.dist(point_at(cur, ub[k]), pts[k]) for k in range(m))
        if dev <= tol:
            return cur
        nc += 1 + nc // 16
    return interpolate_open(pts, kind)


def _join(a: Curve, b: Curve) -> Curve:
    p = a.degree
    shift = a.knots[-1] - b.knots[0]
    ks = list(a.knots[:-1]) + [k + shift for k in b.knots[p + 1 :]]
    return Curve(p, ks, a.ctrl + b.ctrl[1:], [], False)


def fit(pts: list, kind: int = KNOT_CHORD, closed: bool = False, t0=None, t1=None, tol: float = 0.0):
    raw = [list(p) + [0.0] * (3 - len(p)) for p in pts]
    if closed:
        flat = dedupe(raw)
        if len(flat) > 1 and math.dist(flat[0], flat[-1]) <= 1e-9:
            flat.pop()
        if len(flat) < 3:
            raise ValueError("A closed spline needs three distinct points.")
        if len(flat) > MAX_FIT_POINTS:
            return from_control_points(flat, 3, True), flat
        return interpolate_closed(flat, kind), flat
    flat = dedupe(raw)
    if len(flat) < 2:
        raise ValueError("A spline needs two distinct points.")
    kinks = _kink_split(raw)
    if len(flat) > MAX_FIT_POINTS:
        return from_control_points(flat, 3, False), flat
    if len(kinks) > 1:
        curves = [_fit_piece(piece, kind, t0 if i == 0 else None, t1 if i == len(kinks) - 1 else None, tol) for i, piece in enumerate(kinks)]
        out = curves[0]
        for c in curves[1:]:
            out = _join(out, c)
        return out, flat
    return _fit_piece(flat, kind, t0, t1, tol), flat


def _kink_split(raw: list) -> list:
    pieces = [[raw[0]]]
    prev_repeat = False
    for q in raw[1:]:
        if math.dist(q, pieces[-1][-1]) <= 1e-9:
            if not prev_repeat and len(pieces[-1]) >= 1:
                pieces.append([q])
                prev_repeat = True
            continue
        pieces[-1].append(q)
        prev_repeat = False
    out = [pc for pc in pieces if len(pc) >= 2]
    if len(out) <= 1:
        return [dedupe(raw)]
    return out


def _fit_piece(pts: list, kind: int, t0, t1, tol: float) -> Curve:
    if tol > 0 and len(pts) > 4 and t0 is None and t1 is None:
        return approximate_open(pts, kind, tol)
    return interpolate_open(pts, kind, t0, t1)


def deviation(c: Curve, pts: list) -> float:
    ts, ps, acc = length_table(c, 64)
    worst = 0.0
    for q in pts:
        best = min(math.dist(q, p) for p in ps)
        worst = max(worst, best)
    return worst


def closest_param(c: Curve, q) -> float:
    us = sample_params(c, 48)
    best, bu = None, us[0]
    for u in us:
        d = math.dist(point_at(c, u), q)
        if best is None or d < best:
            best, bu = d, u
    lo, hi = c.domain()
    step = (hi - lo) / max(len(us), 1)
    a, b = max(lo, bu - step), min(hi, bu + step)
    for _ in range(60):
        m1 = a + (b - a) / 3.0
        m2 = b - (b - a) / 3.0
        if math.dist(point_at(c, m1), q) < math.dist(point_at(c, m2), q):
            b = m2
        else:
            a = m1
    return (a + b) / 2.0
