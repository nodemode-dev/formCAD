import numpy as np


class CamError(ValueError):
    pass


class Cancelled(Exception):
    pass


class Surface:
    def __init__(self, tris, cell: float = 0.0):
        t = np.ascontiguousarray(np.asarray(tris, dtype=float))
        if t.ndim != 3 or t.shape[1:] != (3, 3) or len(t) == 0:
            raise CamError("The model has no triangles to machine.")
        if not np.isfinite(t).all():
            raise CamError("The model has triangles with values that are not numbers.")
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        ln = np.linalg.norm(n, axis=1)
        keep = ln > 1e-12
        t = t[keep]
        n = n[keep] / ln[keep, None]
        if len(t) == 0:
            raise CamError("The model has no triangles with area.")
        self.t = t
        self.n = n
        self.count = len(t)
        self.lo = t.min(axis=1)
        self.hi = t.max(axis=1)
        self.bmin = self.lo.min(axis=0)
        self.bmax = self.hi.max(axis=0)
        self._cs = 0.0
        self._ready = None
        if cell > 0:
            self.bin(cell)

    def bin(self, cell: float):
        if self._ready is not None and abs(self._cs - cell) < 1e-12:
            return
        cs = float(cell)
        ox, oy = self.bmin[0], self.bmin[1]
        nx = max(int(np.ceil((self.bmax[0] - ox) / cs)) + 1, 1)
        ny = max(int(np.ceil((self.bmax[1] - oy) / cs)) + 1, 1)
        while nx * ny > 4_000_000:
            cs *= 2.0
            nx = max(int(np.ceil((self.bmax[0] - ox) / cs)) + 1, 1)
            ny = max(int(np.ceil((self.bmax[1] - oy) / cs)) + 1, 1)
        i0 = np.clip(((self.lo[:, 0] - ox) / cs).astype(np.int64), 0, nx - 1)
        i1 = np.clip(((self.hi[:, 0] - ox) / cs).astype(np.int64), 0, nx - 1)
        j0 = np.clip(((self.lo[:, 1] - oy) / cs).astype(np.int64), 0, ny - 1)
        j1 = np.clip(((self.hi[:, 1] - oy) / cs).astype(np.int64), 0, ny - 1)
        wi = i1 - i0 + 1
        wj = j1 - j0 + 1
        per = wi * wj
        total = int(per.sum())
        if total > 60_000_000:
            raise CamError("The model triangles are too large for the grid; use a larger cell.")
        tid = np.repeat(np.arange(self.count), per)
        start = np.cumsum(per) - per
        local = np.arange(total) - np.repeat(start, per)
        wjr = np.repeat(wj, per)
        ci = np.repeat(i0, per) + local // wjr
        cj = np.repeat(j0, per) + local % wjr
        key = ci * ny + cj
        order = np.argsort(key, kind="stable")
        key = key[order]
        tid = tid[order]
        ptr = np.zeros(nx * ny + 1, dtype=np.int64)
        np.add.at(ptr, key + 1, 1)
        ptr = np.cumsum(ptr)
        self._cs = cs
        self._ready = (cs, ox, oy, nx, ny, ptr, tid.astype(np.int64))

    @property
    def cs(self) -> float:
        return self._cs

    def near(self, x0: float, x1: float, y0: float, y1: float, z_min: float = -1e30) -> np.ndarray:
        cs, ox, oy, nx, ny, ptr, tid = self._ready
        i0 = int(np.clip(np.floor((x0 - ox) / cs), 0, nx - 1))
        i1 = int(np.clip(np.floor((x1 - ox) / cs), 0, nx - 1))
        j0 = int(np.clip(np.floor((y0 - oy) / cs), 0, ny - 1))
        j1 = int(np.clip(np.floor((y1 - oy) / cs), 0, ny - 1))
        parts = []
        for i in range(i0, i1 + 1):
            a = ptr[i * ny + j0]
            b = ptr[i * ny + j1 + 1]
            if b > a:
                parts.append(tid[a:b])
        if not parts:
            return np.zeros(0, dtype=np.int64)
        ids = np.unique(np.concatenate(parts))
        if z_min > -1e29:
            ids = ids[self.hi[ids, 2] >= z_min]
        return ids

    def size(self) -> tuple:
        return tuple(self.bmin), tuple(self.bmax)
