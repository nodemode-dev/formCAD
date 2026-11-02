import math
from dataclasses import dataclass, field

import numpy as np

from app.doc import nurbs

MAX_DEGREE = 25
MAX_POLES = 50000
EPS = 1e-14


class FormError(ValueError):
    pass


def _p3(q):
    q = list(q)
    return [float(q[0]), float(q[1]), float(q[2]) if len(q) > 2 else 0.0]


@dataclass
class NurbsForm:
    degree: int
    poles: list
    weights: list = field(default_factory=list)
    knots: list = field(default_factory=list)
    mults: list = field(default_factory=list)
    periodic: bool = False

    @classmethod
    def from_record(cls, rec: dict):
        poles = [_p3(q) for q in rec.get("poles") or []]
        degree = int(rec.get("degree", 3))
        periodic = bool(rec.get("periodic", False))
        weights = [float(w) for w in rec.get("weights") or []]
        knots = [float(k) for k in rec.get("knots") or []]
        mults = [int(m) for m in rec.get("mults") or []]
        if not knots:
            knots, mults = clamped_knots(len(poles), degree, periodic)
        form = cls(degree, poles, weights, knots, mults, periodic)
        form.check()
        return form

    @classmethod
    def from_entity(cls, e):
        return cls.from_record({"degree": e.degree, "poles": e.poles, "weights": e.weights, "knots": e.knots, "mults": e.mults, "periodic": e.periodic})

    @classmethod
    def from_points(cls, points, degree=3, weights=None, periodic=False):
        poles = [_p3(q) for q in points]
        if periodic:
            knots, mults = clamped_knots(len(poles), degree, True)
        else:
            degree = max(1, min(int(degree), len(poles) - 1))
            knots, mults = clamped_knots(len(poles), degree, False)
        form = cls(int(degree), poles, [float(w) for w in weights or []], knots, mults, bool(periodic))
        form.check()
        return form

    def to_record(self) -> dict:
        return {"degree": self.degree, "poles": [list(q) for q in self.poles], "weights": list(self.weights), "knots": list(self.knots), "mults": list(self.mults), "periodic": self.periodic}

    def copy(self):
        return NurbsForm.from_record(self.to_record())

    def check(self) -> None:
        n, p = len(self.poles), self.degree
        if p < 1 or p > MAX_DEGREE:
            raise FormError("The degree must be from 1 to %d." % MAX_DEGREE)
        if n < 2 or n > MAX_POLES:
            raise FormError("A curve needs from 2 to %d poles." % MAX_POLES)
        if not self.periodic and n < p + 1:
            raise FormError("A degree %d curve needs at least %d poles." % (p, p + 1))
        if self.weights and (len(self.weights) != n or min(self.weights) <= 0 or not all(math.isfinite(w) for w in self.weights)):
            raise FormError("There must be one positive weight per pole.")
        if len(self.knots) != len(self.mults) or len(self.knots) < 2:
            raise FormError("The knots and multiplicities do not match.")
        if any(self.knots[i] >= self.knots[i + 1] for i in range(len(self.knots) - 1)):
            raise FormError("The distinct knots must increase.")
        if min(self.mults) < 1 or max(self.mults) > p + 1:
            raise FormError("A multiplicity is outside 1 to degree + 1.")
        total = sum(self.mults)
        if self.periodic:
            if total - self.mults[0] != n:
                raise FormError("The knots do not fit the periodic poles.")
        elif total != n + p + 1:
            raise FormError("The knots do not fit the poles.")
        if not all(math.isfinite(c) for q in self.poles for c in q):
            raise FormError("A pole is not finite.")

    def flat(self) -> list:
        out = []
        for k, m in zip(self.knots, self.mults):
            out.extend([k] * m)
        return out

    def domain(self):
        return self.knots[0], self.knots[-1]

    def rational(self) -> bool:
        return bool(self.weights) and (max(self.weights) - min(self.weights) > 1e-14)

    def unwrapped(self) -> "nurbs.Curve":
        n, p = len(self.poles), self.degree
        flat = self.flat()
        w = list(self.weights) if self.weights else []
        if not self.periodic:
            return nurbs.Curve(p, flat, [list(q) for q in self.poles], w, False)
        period = self.knots[-1] - self.knots[0]
        m0 = self.mults[0]
        shift = m0 - 1 - p

        def knot(j):
            q, r = divmod(j, n)
            return flat[r] + q * period

        nc = n + p
        knots = [knot(shift + i) for i in range(nc + p + 1)]
        ctrl = [list(self.poles[i % n]) for i in range(nc)]
        weights = [w[i % n] for i in range(nc)] if w else []
        return nurbs.Curve(p, knots, ctrl, weights, False)

    def derivs(self, u: float, order: int = 3):
        c = self.unwrapped()
        p, nc = c.degree, len(c.ctrl)
        lo, hi = c.domain()
        d_lo, d_hi = self.domain()
        if self.periodic:
            span = d_hi - d_lo
            u = d_lo + ((u - d_lo) % span)
            u = min(max(u, lo), hi)
        else:
            u = min(max(u, lo), hi)
        span = nurbs.find_span(nc, p, u, c.knots)
        order = min(order, 3)
        D = nurbs.ders_basis(span, u, p, order, c.knots)
        ders = np.zeros((order + 1, 3))
        wd = np.zeros(order + 1)
        for k in range(order + 1):
            for j in range(p + 1):
                i = span - p + j
                wt = c.weights[i] if c.weights else 1.0
                ders[k] += D[k][j] * wt * np.array(c.ctrl[i])
                wd[k] += D[k][j] * wt
        out = []
        for k in range(order + 1):
            v = ders[k].copy()
            for i in range(1, k + 1):
                v -= math.comb(k, i) * wd[i] * out[k - i]
            out.append(v / wd[0])
        return out

    def point(self, u: float) -> list:
        return [float(v) for v in self.derivs(u, 0)[0]]

    def sample_params(self, per_span: int = 24) -> list:
        out = []
        for a, b in zip(self.knots, self.knots[1:]):
            out.extend(a + (b - a) * i / per_span for i in range(per_span))
        out.append(self.knots[-1])
        return out

    def sample(self, per_span: int = 24) -> list:
        return [self.point(u) for u in self.sample_params(per_span)]

    def edit_params(self) -> list:
        if self.periodic:
            return list(self.knots[:-1])
        return list(self.knots)

    def edit_points(self) -> list:
        return [self.point(u) for u in self.edit_params()]

    def basis_at(self, u: float):
        c = self.unwrapped()
        p, nc = c.degree, len(c.ctrl)
        lo, hi = c.domain()
        u = min(max(u, lo), hi)
        span = nurbs.find_span(nc, p, u, c.knots)
        N = nurbs.basis_funs(span, u, p, c.knots)
        n = len(self.poles)
        idx, val = [], []
        total = 0.0
        for j in range(p + 1):
            i = span - p + j
            wt = c.weights[i] if c.weights else 1.0
            total += N[j] * wt
        for j in range(p + 1):
            i = span - p + j
            wt = c.weights[i] if c.weights else 1.0
            idx.append(i % n if self.periodic else i)
            val.append(N[j] * wt / total)
        acc = {}
        for i, v in zip(idx, val):
            acc[i] = acc.get(i, 0.0) + v
        return acc

    def move_edit_point(self, u: float, target) -> None:
        cur = np.array(self.point(u))
        delta = np.array(_p3(target)) - cur
        acc = self.basis_at(u)
        norm = sum(v * v for v in acc.values())
        if norm <= EPS:
            raise FormError("The curve cannot be moved there.")
        for i, v in acc.items():
            self.poles[i] = [float(self.poles[i][k] + delta[k] * v / norm) for k in range(3)]

    def insert_knot(self, u: float, times: int = 1) -> None:
        if self.periodic:
            raise FormError("Make the curve non-periodic before inserting a knot here.")
        for _ in range(times):
            self._insert_once(u)

    def _insert_once(self, u: float) -> None:
        p = self.degree
        flat = self.flat()
        lo, hi = flat[p], flat[len(self.poles)]
        if not (lo < u < hi):
            raise FormError("The knot must lie inside the curve.")
        have = sum(m for k, m in zip(self.knots, self.mults) if abs(k - u) < 1e-14)
        if have >= p:
            raise FormError("The knot already has the highest multiplicity.")
        nc = len(self.poles)
        k = max(i for i in range(len(flat) - 1) if flat[i] <= u)
        k = min(k, nc - 1)
        wts = list(self.weights) if self.weights else [1.0] * nc
        hom = [[wts[i] * self.poles[i][0], wts[i] * self.poles[i][1], wts[i] * self.poles[i][2], wts[i]] for i in range(nc)]
        s = have
        new = []
        for i in range(nc + 1):
            if i <= k - p:
                new.append(hom[i])
            elif i >= k - s + 1:
                new.append(hom[i - 1])
            else:
                a = (u - flat[i]) / (flat[i + p] - flat[i])
                new.append([(1 - a) * hom[i - 1][j] + a * hom[i][j] for j in range(4)])
        self.poles = [[v[0] / v[3], v[1] / v[3], v[2] / v[3]] for v in new]
        if self.weights:
            self.weights = [v[3] for v in new]
        for i, kn in enumerate(self.knots):
            if abs(kn - u) < 1e-14:
                self.mults[i] += 1
                return
        pos = next(i for i, kn in enumerate(self.knots) if kn > u)
        self.knots.insert(pos, float(u))
        self.mults.insert(pos, 1)

    def reversed(self):
        n = len(self.poles)
        lo, hi = self.knots[0], self.knots[-1]
        return NurbsForm(self.degree, [list(q) for q in reversed(self.poles)], list(reversed(self.weights)), [lo + hi - k for k in reversed(self.knots)], list(reversed(self.mults)), self.periodic)

    def scaled(self, k: float):
        return NurbsForm(self.degree, [[c * k for c in q] for q in self.poles], list(self.weights), list(self.knots), list(self.mults), self.periodic)

    def length(self, per_span: int = 64) -> float:
        pts = self.sample(per_span)
        return float(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])))


def clamped_knots(n: int, p: int, periodic: bool = False):
    if periodic:
        return [float(i) for i in range(n + 1)], [1] * (n + 1)
    spans = n - p
    if spans < 1:
        raise FormError("A degree %d curve needs at least %d poles." % (p, p + 1))
    return [float(i) for i in range(spans + 1)], [p + 1] + [1] * (spans - 1) + [p + 1]


def arc_derivs(form: NurbsForm, which: str, direction: str):
    lo, hi = form.domain()
    u = hi if which == "end" else lo
    d = form.derivs(u, 3)
    p0, d1, d2, d3 = d[0], d[1], d[2], d[3]
    sp = float(np.linalg.norm(d1))
    if sp < 1e-12:
        raise FormError("The curve has no tangent at that end.")
    t = d1 / sp
    s2 = float(d1 @ d2) / sp
    s3 = (float(d2 @ d2) + float(d1 @ d3)) / sp - (float(d1 @ d2) ** 2) / sp**3
    r2 = (d2 - s2 * t) / sp**2
    r3 = (d3 - 3 * sp * s2 * r2 - s3 * t) / sp**3
    sign = 1.0 if which == "end" else -1.0
    if direction == "away":
        sign = -sign
    return {"u": u, "point": p0, "speed": sp, "t": t * sign, "r2": r2, "r3": r3 * sign, "s2": s2, "s3": s3, "curvature": float(np.linalg.norm(r2))}
