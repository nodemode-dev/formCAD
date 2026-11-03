import numpy as np

DESIGN, SOLID, VOID = 0, 1, 2


class TopoError(ValueError):
    pass


class Cancelled(TopoError):
    pass


class Grid:
    def __init__(self, nx: int, ny: int, nz: int, h: float, origin=(0.0, 0.0, 0.0)):
        if min(nx, ny, nz) < 1 or not h > 0:
            raise TopoError("The grid needs at least one cell in each direction and a positive cell size.")
        self.nx, self.ny, self.nz = int(nx), int(ny), int(nz)
        self.h = float(h)
        self.origin = np.array(origin, dtype=float)
        self.ne = self.nx * self.ny * self.nz
        self.nn = (self.nx + 1) * (self.ny + 1) * (self.nz + 1)
        self.ndof = 3 * self.nn
        self._edofs = None

    @classmethod
    def fit(cls, lo, hi, h: float):
        lo = np.array(lo, dtype=float)
        hi = np.array(hi, dtype=float)
        size = hi - lo
        if np.any(size <= 0):
            raise TopoError("The design space has no volume.")
        best, best_h = None, h
        for trial in np.linspace(0.75 * h, 1.3 * h, 221):
            n = np.maximum(1, np.round(size / trial))
            misfit = float(np.sum(np.abs(size - n * trial)) / trial) + 0.5 * abs(np.log(trial / h))
            if best is None or misfit < best - 1e-12:
                best, best_h = misfit, float(trial)
        n = np.maximum(1, np.round(size / best_h).astype(int))
        return cls(int(n[0]), int(n[1]), int(n[2]), best_h, lo)

    def element_ijk(self):
        e = np.arange(self.ne)
        return e % self.nx, (e // self.nx) % self.ny, e // (self.nx * self.ny)

    def centers(self) -> np.ndarray:
        i, j, k = self.element_ijk()
        return self.origin + (np.stack([i, j, k], axis=1) + 0.5) * self.h

    def node_xyz(self) -> np.ndarray:
        n = np.arange(self.nn)
        sx = self.nx + 1
        sy = self.ny + 1
        return self.origin + np.stack([n % sx, (n // sx) % sy, n // (sx * sy)], axis=1) * self.h

    def edofs(self) -> np.ndarray:
        if self._edofs is None:
            i, j, k = self.element_ijk()
            sx, sy = self.nx + 1, self.ny + 1
            cols = []
            for c in range(2):
                for b in range(2):
                    for a in range(2):
                        cols.append((i + a) + sx * ((j + b) + sy * (k + c)))
            nodes = np.stack(cols, axis=1)
            self._edofs = (3 * nodes[:, :, None] + np.arange(3)[None, None, :]).reshape(self.ne, 24).astype(np.int64)
        return self._edofs

    def element_nodes(self) -> np.ndarray:
        return self.edofs()[:, ::3] // 3

    def volume_of_cell(self) -> float:
        return self.h ** 3

    def shape(self):
        return (self.nz, self.ny, self.nx)

    def dims(self) -> dict:
        return {"nx": self.nx, "ny": self.ny, "nz": self.nz, "h": self.h, "origin": [float(v) for v in self.origin], "elements": self.ne, "unknowns": self.ndof}


def region_mask_elements(grid: Grid, spec: dict) -> np.ndarray:
    kind = str(spec.get("kind") or "box")
    c = grid.centers()
    tol = 1e-9 * max(1.0, grid.h)
    if kind == "box":
        lo, hi = box_of(spec)
        return np.all((c >= lo - tol) & (c <= hi + tol), axis=1)
    if kind == "cylinder":
        axis, centre, radius, lo_a, hi_a = cylinder_of(spec)
        other = [d for d in range(3) if d != axis]
        r = np.hypot(c[:, other[0]] - centre[other[0]], c[:, other[1]] - centre[other[1]])
        return (r <= radius + tol) & (c[:, axis] >= lo_a - tol) & (c[:, axis] <= hi_a + tol)
    if kind == "sphere":
        centre = vec3(spec.get("centre") or spec.get("center"), "centre")
        radius = positive(spec.get("radius"), "radius")
        return np.linalg.norm(c - centre, axis=1) <= radius + tol
    if kind == "mask":
        m = np.asarray(spec.get("mask"), dtype=bool).ravel()
        if len(m) != grid.ne:
            raise TopoError("A mask region needs one value per cell.")
        return m
    raise TopoError("A region is a box, cylinder, sphere or mask, not %s." % kind)


def region_mask_nodes(grid: Grid, spec: dict) -> np.ndarray:
    kind = str(spec.get("kind") or "box")
    p = grid.node_xyz()
    tol = 1e-6 * max(1.0, grid.h)
    if kind == "box":
        lo, hi = box_of(spec)
        return np.all((p >= lo - tol) & (p <= hi + tol), axis=1)
    if kind == "cylinder":
        axis, centre, radius, lo_a, hi_a = cylinder_of(spec)
        other = [d for d in range(3) if d != axis]
        r = np.hypot(p[:, other[0]] - centre[other[0]], p[:, other[1]] - centre[other[1]])
        return (r <= radius + tol) & (p[:, axis] >= lo_a - tol) & (p[:, axis] <= hi_a + tol)
    if kind == "sphere":
        centre = vec3(spec.get("centre") or spec.get("center"), "centre")
        radius = positive(spec.get("radius"), "radius")
        return np.linalg.norm(p - centre, axis=1) <= radius + tol
    raise TopoError("A load or support region is a box, cylinder or sphere, not %s." % kind)


def vec3(v, what):
    try:
        a = np.array([float(x) for x in v], dtype=float)
    except (TypeError, ValueError):
        raise TopoError("%s must be three numbers." % what)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise TopoError("%s must be three finite numbers." % what)
    return a


def positive(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TopoError("%s must be a number." % what)
    if not np.isfinite(x) or x <= 0:
        raise TopoError("%s must be positive." % what)
    return x


def box_of(spec):
    lo = vec3(spec.get("min"), "min")
    hi = vec3(spec.get("max"), "max")
    if np.any(hi < lo):
        raise TopoError("A box region has its minimum corner above its maximum corner.")
    return lo, hi


def cylinder_of(spec):
    axis = spec.get("axis", "z")
    axis = "xyz".index(axis) if isinstance(axis, str) else int(axis)
    if axis not in (0, 1, 2):
        raise TopoError("The cylinder axis is x, y or z.")
    centre = vec3(spec.get("centre") or spec.get("center"), "centre")
    radius = positive(spec.get("radius"), "radius")
    lo_a, hi_a = float(spec.get("from", -1e30)), float(spec.get("to", 1e30))
    return axis, centre, radius, lo_a, hi_a


def voxelize_mesh(grid: Grid, v: np.ndarray, t: np.ndarray, max_triangles: int = 200_000) -> np.ndarray:
    if len(t) > max_triangles:
        raise TopoError("The shape has %d triangles; at most %d can be turned into a design space. Reduce the mesh first." % (len(t), max_triangles))
    tri = v[t]
    jitter = np.array([0.000731 * grid.h, 0.000419 * grid.h])
    ox, oy = grid.origin[0] + 0.5 * grid.h + jitter[0], grid.origin[1] + 0.5 * grid.h + jitter[1]
    hits = [[] for _ in range(grid.nx * grid.ny)]
    for a, b, c in tri:
        x0, x1 = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
        y0, y1 = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        i0 = max(0, int(np.ceil((x0 - ox) / grid.h)))
        i1 = min(grid.nx - 1, int(np.floor((x1 - ox) / grid.h)))
        j0 = max(0, int(np.ceil((y0 - oy) / grid.h)))
        j1 = min(grid.ny - 1, int(np.floor((y1 - oy) / grid.h)))
        if i1 < i0 or j1 < j0:
            continue
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-18:
            continue
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
        px = ox + ii * grid.h
        py = oy + jj * grid.h
        l1 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / det
        l2 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        if not inside.any():
            continue
        z = l1 * a[2] + l2 * b[2] + l3 * c[2]
        for i, j, zz in zip(ii[inside], jj[inside], z[inside]):
            hits[j * grid.nx + i].append(float(zz))
    mask = np.zeros((grid.nz, grid.ny, grid.nx), dtype=bool)
    zc = grid.origin[2] + (np.arange(grid.nz) + 0.5) * grid.h
    for col, zs in enumerate(hits):
        if len(zs) < 2:
            continue
        zs.sort()
        if len(zs) % 2:
            zs = zs[:-1]
        j, i = divmod(col, grid.nx)
        for lo, hi in zip(zs[0::2], zs[1::2]):
            mask[(zc >= lo) & (zc <= hi), j, i] = True
    return mask.reshape(-1)
