import itertools

import numpy as np
import scipy.sparse as sp
from scipy.spatial import cKDTree

from app.topo.grid import DESIGN, SOLID, VOID, Grid, TopoError

MAX_FILTER_ENTRIES = 24_000_000
FILTERS: dict = {}


def register(name: str):
    def wrap(factory):
        FILTERS[name] = factory
        return factory

    return wrap


class Filter:
    name = "filter"

    def forward(self, x: np.ndarray) -> np.ndarray:
        return x

    def backward(self, x: np.ndarray, y: np.ndarray, g: np.ndarray) -> np.ndarray:
        return g

    def info(self) -> dict:
        return {"name": self.name}


class Chain:
    def __init__(self, stages):
        self.stages = list(stages)

    def forward(self, x: np.ndarray) -> np.ndarray:
        for s in self.stages:
            x = s.forward(x)
        return x

    def trace(self, x: np.ndarray) -> list:
        seen = [x]
        for s in self.stages:
            seen.append(s.forward(seen[-1]))
        return seen

    def backward(self, seen: list, g: np.ndarray) -> np.ndarray:
        for k in range(len(self.stages) - 1, -1, -1):
            g = self.stages[k].backward(seen[k], seen[k + 1], g)
        return g

    def find(self, name: str):
        for s in self.stages:
            if s.name == name:
                return s
        return None


class Linear(Filter):
    def __init__(self, W: sp.csr_matrix, name: str):
        self.W = W.tocsr()
        self.WT = W.T.tocsr()
        self.name = name

    def forward(self, x):
        return self.W @ x

    def backward(self, x, y, g):
        return self.WT @ g


@register("density")
class DensityFilter(Linear):
    def __init__(self, grid: Grid, radius: float):
        if not radius > 0:
            raise TopoError("The filter radius must be positive.")
        if radius > 8 * grid.h:
            raise TopoError("The filter radius is more than 8 cells; use a coarser grid or a smaller radius.")
        c = grid.centers()
        tree = cKDTree(c)
        est = grid.ne * (4.0 / 3.0 * np.pi * (radius / grid.h) ** 3 + 1.0)
        if est > MAX_FILTER_ENTRIES:
            raise TopoError("The filter would hold about %d neighbour pairs; the limit is %d. Use a smaller radius or a coarser grid." % (est, MAX_FILTER_ENTRIES))
        d = tree.sparse_distance_matrix(tree, radius, output_type="coo_matrix")
        w = np.maximum(0.0, radius - d.data)
        rows = np.concatenate([d.row, np.arange(grid.ne)])
        cols = np.concatenate([d.col, np.arange(grid.ne)])
        vals = np.concatenate([w, np.full(grid.ne, radius)])
        W = sp.coo_matrix((vals, (rows, cols)), shape=(grid.ne, grid.ne)).tocsr()
        W.sum_duplicates()
        sums = np.asarray(W.sum(axis=1)).ravel()
        super().__init__(sp.diags(1.0 / sums) @ W, "density")
        self.radius = radius

    def info(self):
        return {"name": self.name, "radius": self.radius}


class Projection(Filter):
    name = "projection"

    def __init__(self, beta: float = 1.0, eta: float = 0.5):
        self.beta = float(beta)
        self.eta = float(eta)

    def _norm(self):
        return np.tanh(self.beta * self.eta) + np.tanh(self.beta * (1.0 - self.eta))

    def forward(self, x):
        return (np.tanh(self.beta * self.eta) + np.tanh(self.beta * (x - self.eta))) / self._norm()

    def backward(self, x, y, g):
        return g * self.beta * (1.0 - np.tanh(self.beta * (x - self.eta)) ** 2) / self._norm()

    def info(self):
        return {"name": self.name, "beta": self.beta, "eta": self.eta}


class Passive(Filter):
    name = "passive"

    def __init__(self, cls: np.ndarray):
        self.solid = cls == SOLID
        self.void = cls == VOID
        self.free = ~(self.solid | self.void)

    def forward(self, x):
        y = x.copy()
        y[self.solid] = 1.0
        y[self.void] = 0.0
        return y

    def backward(self, x, y, g):
        out = g.copy()
        out[~self.free] = 0.0
        return out


def orbit_matrix(grid: Grid, planes) -> sp.csr_matrix:
    i, j, k = grid.element_ijk()
    dims = (grid.nx, grid.ny, grid.nz)
    axes = sorted(set(planes))
    perms = []
    for flips in itertools.product((0, 1), repeat=len(axes)):
        idx = [i.copy(), j.copy(), k.copy()]
        for f, ax in zip(flips, axes):
            if f:
                idx[ax] = dims[ax] - 1 - idx[ax]
        perms.append(idx[0] + grid.nx * (idx[1] + grid.ny * idx[2]))
    n = grid.ne
    rows = np.tile(np.arange(n), len(perms))
    cols = np.concatenate(perms)
    return sp.csr_matrix((np.full(len(rows), 1.0 / len(perms)), (rows, cols)), shape=(n, n))


def plane_axes(grid: Grid, planes, bounds):
    out = []
    lo, hi = bounds
    for p in planes:
        if isinstance(p, dict):
            ax = p.get("axis")
            pos = p.get("position")
        else:
            ax, pos = p, None
        ax = "xyz".index(ax) if isinstance(ax, str) else int(ax)
        if ax not in (0, 1, 2):
            raise TopoError("A symmetry plane is normal to x, y or z.")
        mid = 0.5 * (lo[ax] + hi[ax])
        if pos is not None and abs(float(pos) - mid) > 0.01 * grid.h + 1e-9:
            raise TopoError("The symmetry plane normal to %s must pass through the middle of the design space (%g); it is at %g." % ("xyz"[ax], mid, float(pos)))
        out.append(ax)
    return out


@register("symmetry")
def make_symmetry(grid: Grid, planes):
    return Linear(orbit_matrix(grid, planes), "symmetry")


@register("extrusion")
def make_extrusion(grid: Grid, axis):
    ax = "xyz".index(axis) if isinstance(axis, str) else int(axis)
    i, j, k = grid.element_ijk()
    idx = [i, j, k]
    dims = (grid.nx, grid.ny, grid.nz)
    line = np.zeros(grid.ne, dtype=np.int64)
    mul = 1
    for d in range(3):
        if d == ax:
            continue
        line += idx[d] * mul
        mul *= dims[d]
    count = np.bincount(line)
    W = sp.csr_matrix((1.0 / count[line], (np.arange(grid.ne), line)), shape=(grid.ne, len(count)))
    W = W @ sp.csr_matrix((np.ones(grid.ne), (line, np.arange(grid.ne))), shape=(len(count), grid.ne))
    return Linear(W, "extrusion")


def symmetry_conflicts(grid: Grid, cls: np.ndarray, axes) -> list:
    S = orbit_matrix(grid, axes)
    bad = []
    for name, code in (("preserve", SOLID), ("obstacle", VOID)):
        m = (cls == code).astype(float)
        diff = np.abs(S @ m - m)
        if np.any(diff > 1e-9):
            bad.append(name)
    return bad
