import math

import numpy as np
from scipy import ndimage

from app.cam3d.cutters import Cutter
from app.cam3d.surface import CamError

BIG = 1e9
MAX_EVENTS = 400


class Grid:
    def __init__(self, bmin, bmax, cell: float):
        self.cell = float(cell)
        self.o = np.asarray(bmin, dtype=float)
        self.n = np.maximum(np.ceil((np.asarray(bmax, dtype=float) - self.o) / cell).astype(np.int64), 1)
        self.xs = self.o[0] + (np.arange(self.n[0]) + 0.5) * cell
        self.ys = self.o[1] + (np.arange(self.n[1]) + 0.5) * cell
        self.zs = self.o[2] + (np.arange(self.n[2]) + 0.5) * cell

    @property
    def count(self) -> int:
        return int(self.n[0] * self.n[1] * self.n[2])

    def index(self, P):
        return np.floor((P - self.o) / self.cell).astype(np.int64)


def voxelize(tris, g: Grid) -> np.ndarray:
    nx, ny, nz = (int(v) for v in g.n)
    c = g.cell
    t = np.asarray(tris, dtype=float)
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    keep = (ln > 1e-12) & (np.abs(nrm[:, 2]) > 1e-9 * np.maximum(ln, 1e-12))
    t, nrm, ln = t[keep], nrm[keep], ln[keep]
    nrm = nrm / ln[:, None]
    lo = t.min(axis=1)
    hi = t.max(axis=1)
    i0 = np.clip(np.ceil((lo[:, 0] - g.o[0]) / c - 0.5).astype(np.int64), 0, nx - 1)
    i1 = np.clip(np.floor((hi[:, 0] - g.o[0]) / c - 0.5).astype(np.int64), 0, nx - 1)
    j0 = np.clip(np.ceil((lo[:, 1] - g.o[1]) / c - 0.5).astype(np.int64), 0, ny - 1)
    j1 = np.clip(np.floor((hi[:, 1] - g.o[1]) / c - 0.5).astype(np.int64), 0, ny - 1)
    wi = np.maximum(i1 - i0 + 1, 0)
    wj = np.maximum(j1 - j0 + 1, 0)
    per = wi * wj
    diff = np.zeros(nx * ny * (nz + 1), dtype=np.int16)
    step = 400000
    order = np.arange(len(t))
    pos = 0
    while pos < len(t):
        cum = np.cumsum(per[pos:])
        cnt = int(np.searchsorted(cum, step, side="right")) + 1
        sel = order[pos:pos + max(cnt, 1)]
        pos += max(cnt, 1)
        pr = per[sel]
        total = int(pr.sum())
        if total == 0:
            continue
        tid = np.repeat(sel, pr)
        start = np.cumsum(pr) - pr
        local = np.arange(total) - np.repeat(start, pr)
        wjr = np.repeat(wj[sel], pr)
        ci = np.repeat(i0[sel], pr) + local // np.maximum(wjr, 1)
        cj = np.repeat(j0[sel], pr) + local % np.maximum(wjr, 1)
        qx = g.o[0] + (ci + 0.5) * c
        qy = g.o[1] + (cj + 0.5) * c
        T = t[tid]
        ax, ay = T[:, 0, 0], T[:, 0, 1]
        v0x, v0y = T[:, 1, 0] - ax, T[:, 1, 1] - ay
        v1x, v1y = T[:, 2, 0] - ax, T[:, 2, 1] - ay
        v2x, v2y = qx - ax, qy - ay
        d00 = v0x * v0x + v0y * v0y
        d01 = v0x * v1x + v0y * v1y
        d11 = v1x * v1x + v1y * v1y
        d20 = v2x * v0x + v2y * v0y
        d21 = v2x * v1x + v2y * v1y
        den = d00 * d11 - d01 * d01
        ok = np.abs(den) > 1e-18
        den = np.where(ok, den, 1.0)
        u = (d11 * d20 - d01 * d21) / den
        v = (d00 * d21 - d01 * d20) / den
        hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        N = nrm[tid]
        zc = T[:, 0, 2] - (N[:, 0] * (qx - ax) + N[:, 1] * (qy - T[:, 0, 1])) / N[:, 2]
        k = np.ceil((zc - g.o[2]) / c - 0.5).astype(np.int64)
        k = np.clip(k, 0, nz)
        col = (ci * ny + cj)[hit]
        k = k[hit]
        sign = np.where(N[hit, 2] < 0, 1, -1).astype(np.int16)
        np.add.at(diff, col * (nz + 1) + k, sign)
    cov = np.cumsum(diff.reshape(nx * ny, nz + 1), axis=1)[:, :nz]
    return (cov > 0).reshape(nx, ny, nz)


def box_mask(g: Grid, lo, hi, rings=None) -> np.ndarray:
    m = ((g.xs[:, None, None] >= lo[0]) & (g.xs[:, None, None] <= hi[0]) & (g.ys[None, :, None] >= lo[1]) & (g.ys[None, :, None] <= hi[1]) & (g.zs[None, None, :] >= lo[2]) & (g.zs[None, None, :] <= hi[2]))
    if rings:
        from app.cam3d.simulate import ring_mask

        X, Y = np.meshgrid(g.xs, g.ys, indexing="ij")
        m &= ring_mask(rings, X, Y)[:, :, None]
    return m


def surface_points(cu: Cutter, flute: float, spacing: float):
    ph = np.linspace(0.0, 1.0, 1)
    prof = np.array(cu.profile(24))
    top = min(flute if flute > 0 else cu.R * 4.0, 1e5)
    prof = prof[prof[:, 1] <= top + 1e-9]
    if prof[-1, 1] < top - 1e-9:
        prof = np.vstack([prof, [cu.R, top]])
    out = []
    seg = np.diff(prof, axis=0)
    for a, d in zip(prof[:-1], seg):
        ln = float(np.hypot(d[0], d[1]))
        m = max(int(math.ceil(ln / spacing)), 1)
        for s in range(m + 1):
            r, h = a + d * (s / m)
            if r < 1e-9:
                out.append((0.0, 0.0, h))
                continue
            n = max(int(math.ceil(2.0 * math.pi * r / spacing)), 6)
            ang = np.arange(n) * (2.0 * math.pi / n)
            out.extend(zip(r * np.cos(ang), r * np.sin(ang), np.full(n, h)))
    return np.array(out)


def revolve_points(profile, spacing: float, z0: float = 0.0):
    prof = np.array([(float(r), float(z) + z0) for r, z in profile])
    out = []
    if len(prof) < 2:
        return np.zeros((0, 3))
    for a, b in zip(prof[:-1], prof[1:]):
        d = b - a
        ln = float(np.hypot(d[0], d[1]))
        m = max(int(math.ceil(ln / spacing)), 1)
        for s in range(m + 1):
            r, h = a + d * (s / m)
            if r < 1e-9:
                out.append((0.0, 0.0, h))
                continue
            n = max(int(math.ceil(2.0 * math.pi * r / spacing)), 6)
            ang = np.arange(n) * (2.0 * math.pi / n)
            out.extend(zip(r * np.cos(ang), r * np.sin(ang), np.full(n, h)))
    return np.array(out)


def frame_of(k):
    k = np.asarray(k, dtype=float)
    k = k / np.linalg.norm(k)
    ref = np.array([1.0, 0.0, 0.0]) if abs(k[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(k, ref)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(k, e1)
    return e1, e2


class VoxelSim:
    def __init__(self, g: Grid, stock, model, fixture):
        self.g = g
        self.S = stock
        self.M = model
        self.F = fixture
        self.P = model | fixture
        self.sd_tool = None
        self.min = {}
        self.at = {}
        self.events = []
        self.seen = set()
        self.removed_vox = 0

    def volume(self) -> float:
        return float(self.S.sum()) * self.g.cell ** 3

    def prepare_static(self):
        c = self.g.cell
        out = ndimage.distance_transform_edt(~self.P, sampling=c)
        ins = ndimage.distance_transform_edt(self.P, sampling=c)
        self.sd_tool = (out - ins).astype(np.float32)

    def refresh_dynamic(self):
        self.dist_body = ndimage.distance_transform_edt(~(self.S | self.P), sampling=self.g.cell).astype(np.float32)

    def cut_pose_test(self, p, k, cu: Cutter, flute: float):
        return self.cut_pose(p, k, cu, flute, False)

    def cut_pose(self, p, k, cu: Cutter, flute: float, apply: bool = True):
        g = self.g
        L = min(flute if flute > 0 else cu.R * 6.0, 400.0)
        e = p + k * L
        lo = np.minimum(p, e) - cu.R - g.cell
        hi = np.maximum(p, e) + cu.R + g.cell
        i0 = np.maximum(np.floor((lo - g.o) / g.cell).astype(np.int64), 0)
        i1 = np.minimum(np.ceil((hi - g.o) / g.cell).astype(np.int64), g.n)
        if (i1 <= i0).any():
            return 0
        sl = (slice(i0[0], i1[0]), slice(i0[1], i1[1]), slice(i0[2], i1[2]))
        sub = self.S[sl]
        if not sub.any():
            return 0
        X = g.xs[sl[0]][:, None, None] - p[0]
        Y = g.ys[sl[1]][None, :, None] - p[1]
        Z = g.zs[sl[2]][None, None, :] - p[2]
        h = X * k[0] + Y * k[1] + Z * k[2]
        rho2 = X * X + Y * Y + Z * Z - h * h
        rho = np.sqrt(np.maximum(rho2, 0.0))
        inside = (h >= 0) & (h <= L) & (rho <= cu.radius_at(h))
        hit = sub & inside
        n = int(hit.sum())
        if n and apply:
            sub[hit] = False
            self.removed_vox += n
        return n

    def lookup(self, pts, field, fill):
        g = self.g
        idx = g.index(pts)
        ok = ((idx >= 0) & (idx < g.n)).all(axis=1)
        out = np.full(len(pts), fill, dtype=np.float32)
        ii = idx[ok]
        out[ok] = field[ii[:, 0], ii[:, 1], ii[:, 2]]
        return out, ok

    def note(self, kind, value, where, tag, pose_ix, label, extra=None):
        if kind not in self.min or value < self.min[kind]:
            self.min[kind] = float(value)
            self.at[kind] = [float(v) for v in where]
        return

    def event(self, kind, tag, where, dist, abc=None):
        key = (kind, tag)
        if key in self.seen or len(self.events) >= MAX_EVENTS:
            return
        self.seen.add(key)
        row = {"op_move": tag, "kind": kind, "at": [float(v) for v in where], "distance_mm": float(dist)}
        if abc is not None:
            row["abc"] = [float(v) for v in abc]
        self.events.append(row)
