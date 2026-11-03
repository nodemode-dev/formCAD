import math

import numpy as np
from scipy import ndimage

from app.cam3d.cutters import Cutter

BIG = 1e9


class Underside:
    def __init__(self, profile):
        pts = sorted((float(r), float(z)) for r, z in profile) if profile else []
        a = sorted(((float(z), float(r)) for r, z in profile)) if profile else []
        self.z = np.array([p[0] for p in a]) if a else np.zeros(0)
        r = np.array([p[1] for p in a]) if a else np.zeros(0)
        self.r = np.maximum.accumulate(r) if len(r) else r
        self.rmax = float(self.r[-1]) if len(self.r) else 0.0
        self.zmin = float(self.z[0]) if len(self.z) else 0.0

    def __call__(self, rho):
        rho = np.asarray(rho, dtype=float)
        if not len(self.r):
            return np.full_like(rho, BIG)
        r, idx = np.unique(self.r, return_index=True)
        out = np.interp(rho, r, self.z[idx])
        return np.where(rho <= self.rmax + 1e-9, np.maximum(out, self.zmin), BIG)


class DexelStock:
    def __init__(self, bmin, bmax, cell: float, inside=None):
        self.cell = float(cell)
        self.x0, self.y0 = float(bmin[0]), float(bmin[1])
        self.nx = max(int(math.ceil((bmax[0] - bmin[0]) / cell)), 1)
        self.ny = max(int(math.ceil((bmax[1] - bmin[1]) / cell)), 1)
        self.xc = self.x0 + (np.arange(self.nx) + 0.5) * cell
        self.yc = self.y0 + (np.arange(self.ny) + 0.5) * cell
        self.top = np.full((self.nx, self.ny), float(bmax[2]))
        self.bot = np.full((self.nx, self.ny), float(bmin[2]))
        self.zmin = float(bmin[2])
        self.zmax = float(bmax[2])
        if inside is not None:
            X, Y = np.meshgrid(self.xc, self.yc, indexing="ij")
            m = inside(X, Y)
            self.top[~m] = self.bot[~m]
        self.design = None
        self.design_chk = None
        self.fixture = None
        self.gouge_depth = np.zeros(self.nx * self.ny, dtype=np.float32)
        self.gouge_first = np.full(self.nx * self.ny, np.iinfo(np.int64).max, dtype=np.int64)
        self.gouge_tool = np.zeros((self.nx * self.ny, 3), dtype=np.float32)
        self.min_clear = math.inf
        self.min_clear_at = None
        self.rapid_hits = []

    def volume(self) -> float:
        return float((self.top - self.bot).sum() * self.cell * self.cell)

    def set_design(self, z, tol_cells: int = 1):
        self.design = z
        valid = np.isfinite(z)
        lo = np.where(valid, z, -BIG)
        lo = ndimage.minimum_filter(lo, size=2 * tol_cells + 1, mode="nearest")
        self.design_chk = np.where(lo <= -BIG / 2, np.nan, lo)

    def set_fixture(self, z):
        self.fixture = z

    def window(self, R):
        return int(math.ceil(R / self.cell)) + 1

    def cut(self, P, cu: Cutter, gouge_tol: float, ids, cutting: bool = True):
        R = cu.R
        w = self.window(R)
        i0 = np.floor((P[:, 0] - self.x0) / self.cell).astype(np.int64)
        j0 = np.floor((P[:, 1] - self.y0) / self.cell).astype(np.int64)
        top = self.top.reshape(-1)
        dchk = self.design_chk.reshape(-1) if self.design_chk is not None else None
        hit_rapid = np.zeros(len(P), dtype=bool)
        for di in range(-w, w + 1):
            ci = i0 + di
            okx = (ci >= 0) & (ci < self.nx)
            if not okx.any():
                continue
            dx = self.x0 + (ci + 0.5) * self.cell - P[:, 0]
            for dj in range(-w, w + 1):
                cj = j0 + dj
                rho = np.hypot(dx, self.y0 + (cj + 0.5) * self.cell - P[:, 1])
                m = okx & (cj >= 0) & (cj < self.ny) & (rho <= R)
                if not m.any():
                    continue
                k = np.nonzero(m)[0]
                flat = ci[k] * self.ny + cj[k]
                zt = P[k, 2] + cu.under(rho[k])
                if dchk is not None:
                    dv = dchk[flat]
                    okd = np.isfinite(dv)
                    if okd.any():
                        clear = zt[okd] - dv[okd]
                        j = int(np.argmin(clear))
                        if clear[j] < self.min_clear:
                            self.min_clear = float(clear[j])
                            kk = k[okd][j]
                            self.min_clear_at = (float(P[kk, 0]), float(P[kk, 1]), float(P[kk, 2]))
                        viol = clear < -gouge_tol
                        if viol.any():
                            fl = flat[okd][viol]
                            dep = (-clear[viol]).astype(np.float32)
                            np.maximum.at(self.gouge_depth, fl, dep)
                            kk = k[okd][viol]
                            np.minimum.at(self.gouge_first, fl, ids[kk])
                            self.gouge_tool[fl] = P[kk]
                if cutting:
                    np.minimum.at(top, flat, zt)
                else:
                    below = (zt < top[flat] - 1e-3) & (top[flat] > self.bot.reshape(-1)[flat] + 1e-9)
                    hit_rapid[k[below]] = True
        if cutting:
            np.maximum(self.top, self.bot, out=self.top)
        return hit_rapid

    def clearance_body(self, P, under, rmax, ids, label, record, coarse: int):
        c = self.cell * coarse
        if c <= 0:
            return
        nx = int(math.ceil(self.nx / coarse))
        ny = int(math.ceil(self.ny / coarse))
        pad_x = nx * coarse - self.nx
        pad_y = ny * coarse - self.ny
        t = np.pad(np.where(self.top > self.bot + 1e-9, self.top, -BIG), ((0, pad_x), (0, pad_y)), constant_values=-BIG)
        tc = t.reshape(nx, coarse, ny, coarse).max(axis=(1, 3)).reshape(-1)
        fx = None
        if self.fixture is not None:
            f = np.pad(np.where(np.isfinite(self.fixture), self.fixture, -BIG), ((0, pad_x), (0, pad_y)), constant_values=-BIG)
            fx = f.reshape(nx, coarse, ny, coarse).max(axis=(1, 3)).reshape(-1)
        w = int(math.ceil(rmax / c)) + 1
        i0 = np.floor((P[:, 0] - self.x0) / c).astype(np.int64)
        j0 = np.floor((P[:, 1] - self.y0) / c).astype(np.int64)
        for di in range(-w, w + 1):
            ci = i0 + di
            okx = (ci >= 0) & (ci < nx)
            if not okx.any():
                continue
            dx = self.x0 + (ci + 0.5) * c - P[:, 0]
            for dj in range(-w, w + 1):
                cj = j0 + dj
                rho = np.hypot(dx, self.y0 + (cj + 0.5) * c - P[:, 1])
                m = okx & (cj >= 0) & (cj < ny) & (rho <= max(rmax - c * 0.5, 0.0))
                if not m.any():
                    continue
                k = np.nonzero(m)[0]
                flat = ci[k] * ny + cj[k]
                zb = P[k, 2] + under(np.minimum(rho[k], rmax))
                gap_s = zb - tc[flat]
                record(label + "_stock", k, gap_s, P, ids)
                if fx is not None:
                    record(label + "_fixture", k, zb - fx[flat], P, ids)
