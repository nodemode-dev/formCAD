import math

import numpy as np

from app.topo import filters as F
from app.topo.grid import SOLID, VOID, Grid, TopoError

P = 30.0
EPS = 1e-4
AXES = {"x": 2, "y": 1, "z": 0}


def axis_of(value, what: str = "axis"):
    text = str(value).strip().lower()
    sign = 1
    if text[:1] in "+-" and len(text) > 1:
        sign = -1 if text[0] == "-" else 1
        text = text[1:]
    if text not in AXES:
        raise TopoError("The %s is x, y or z, optionally with a sign (for example +z)." % what)
    return AXES[text], sign


def smax2(a, b):
    q = P + math.log10(2.0)
    s = (a + EPS) ** P + (b + EPS) ** P
    return s ** (1.0 / q)


def smax2_d(a, b):
    q = P + math.log10(2.0)
    s = (a + EPS) ** P + (b + EPS) ** P
    f = (1.0 / q) * s ** (1.0 / q - 1.0)
    return f * P * (a + EPS) ** (P - 1.0), f * P * (b + EPS) ** (P - 1.0)


def shift(a, dy, dx):
    out = np.zeros_like(a)
    ny, nx = a.shape
    ys = slice(max(0, -dy), min(ny, ny - dy))
    xs = slice(max(0, -dx), min(nx, nx - dx))
    yd = slice(max(0, dy), min(ny, ny + dy))
    xd = slice(max(0, dx), min(nx, nx + dx))
    out[ys, xs] = a[yd, xd]
    return out


OFFS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def support(prev):
    q = P + math.log10(len(OFFS))
    t = sum((shift(prev, dy, dx) + EPS) ** P for dy, dx in OFFS)
    return t ** (1.0 / q), t, q


def support_vjp(prev, g):
    s, t, q = support(prev)
    gt = g * (1.0 / q) * t ** (1.0 / q - 1.0)
    out = np.zeros_like(prev)
    for dy, dx in OFFS:
        out += shift(gt * P * (shift(prev, dy, dx) + EPS) ** (P - 1.0), -dy, -dx)
    return out


def layers(grid: Grid, x: np.ndarray, axis: int, sign: int):
    a = np.moveaxis(x.reshape(grid.shape()), axis, 0)
    return a[::-1] if sign < 0 else a


def unlayers(grid: Grid, a: np.ndarray, axis: int, sign: int):
    a = a[::-1] if sign < 0 else a
    return np.moveaxis(a, 0, axis).reshape(-1)


def overhang_forward(x3):
    out = np.empty_like(x3)
    out[0] = x3[0]
    for l in range(1, len(x3)):
        s, _t, _q = support(out[l - 1])
        out[l] = np.clip(x3[l] + s - smax2(x3[l], s), 0.0, 1.0)
    return out


def overhang_backward(x3, out, g):
    gx = np.zeros_like(x3)
    gxi = g.copy()
    for l in range(len(x3) - 1, 0, -1):
        s, _t, _q = support(out[l - 1])
        da, ds = smax2_d(x3[l], s)
        gx[l] += gxi[l] * (1.0 - da)
        gxi[l - 1] += support_vjp(out[l - 1], gxi[l] * (1.0 - ds))
    gx[0] += gxi[0]
    return gx


def reach_forward(x3):
    out = np.empty_like(x3)
    out[0] = x3[0]
    for l in range(1, len(x3)):
        out[l] = np.clip(smax2(x3[l], out[l - 1]), 0.0, 1.0)
    return out


def reach_backward(x3, out, g):
    gx = np.zeros_like(x3)
    gxi = g.copy()
    for l in range(len(x3) - 1, 0, -1):
        da, db = smax2_d(x3[l], out[l - 1])
        gx[l] += gxi[l] * da
        gxi[l - 1] += gxi[l] * db
    gx[0] += gxi[0]
    return gx


class Overhang(F.Filter):
    name = "overhang"

    def __init__(self, grid: Grid, direction="+z", cls=None):
        self.grid = grid
        self.axis, self.sign = axis_of(direction, "build direction")
        self.direction = direction
        self.cls = cls

    def pre(self, x):
        if self.cls is None:
            return x
        y = x.copy()
        y[self.cls == SOLID] = 1.0
        y[self.cls == VOID] = 0.0
        return y

    def forward(self, x):
        x3 = layers(self.grid, self.pre(x), self.axis, self.sign)
        return unlayers(self.grid, overhang_forward(x3), self.axis, self.sign)

    def backward(self, x, y, g):
        x3 = layers(self.grid, self.pre(x), self.axis, self.sign)
        out = overhang_forward(x3)
        g3 = layers(self.grid, g, self.axis, self.sign)
        gx = unlayers(self.grid, overhang_backward(x3, out, g3), self.axis, self.sign)
        if self.cls is not None:
            gx[(self.cls == SOLID) | (self.cls == VOID)] = 0.0
        return gx

    def info(self):
        return {"name": self.name, "direction": self.direction}


class Access(F.Filter):
    name = "access"

    def __init__(self, grid: Grid, directions=("+z",), cls=None):
        if isinstance(directions, str):
            directions = [directions]
        if not directions:
            raise TopoError("Name at least one tool or draw direction.")
        self.grid = grid
        self.dirs = [axis_of(d, "tool direction") for d in directions]
        self.names = [str(d) for d in directions]
        self.cls = cls

    def pre(self, x):
        if self.cls is None:
            return x
        y = x.copy()
        y[self.cls == SOLID] = 1.0
        y[self.cls == VOID] = 0.0
        return y

    def scans(self, x):
        xs = self.pre(x)
        return [reach_forward(layers(self.grid, xs, ax, -sg)) for ax, sg in self.dirs]

    def combine(self, parts):
        y = parts[0]
        for p in parts[1:]:
            y = y + p - smax2(y, p)
        return y

    def forward(self, x):
        parts = [unlayers(self.grid, p, ax, -sg) for p, (ax, sg) in zip(self.scans(x), self.dirs)]
        return np.clip(self.combine(parts), 0.0, 1.0)

    def backward(self, x, y, g):
        xs = self.pre(x)
        outs = [unlayers(self.grid, p, ax, -sg) for p, (ax, sg) in zip(self.scans(x), self.dirs)]
        gout = [None] * len(outs)
        run = outs[0]
        chain = [run]
        for p in outs[1:]:
            run = run + p - smax2(run, p)
            chain.append(run)
        gr = g
        for k in range(len(outs) - 1, 0, -1):
            da, db = smax2_d(chain[k - 1], outs[k])
            gout[k] = gr * (1.0 - db)
            gr = gr * (1.0 - da)
        gout[0] = gr
        gx = np.zeros_like(x)
        for k, (ax, sg) in enumerate(self.dirs):
            x3 = layers(self.grid, xs, ax, -sg)
            o3 = layers(self.grid, outs[k], ax, -sg)
            g3 = layers(self.grid, gout[k], ax, -sg)
            gx += unlayers(self.grid, reach_backward(x3, o3, g3), ax, -sg)
        if self.cls is not None:
            gx[(self.cls == SOLID) | (self.cls == VOID)] = 0.0
        return gx

    def info(self):
        return {"name": self.name, "directions": self.names}


@F.register("overhang")
def make_overhang(grid: Grid, direction="+z", cls=None):
    return Overhang(grid, direction, cls)


@F.register("access")
def make_access(grid: Grid, directions=("+z",), cls=None):
    return Access(grid, directions, cls)
