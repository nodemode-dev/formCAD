import numpy as np

from app.cam3d.cutters import Cutter
from app.cam3d.dropcutter import GOLDEN, inside_xy
from app.cam3d.surface import CamError, Surface

EDGE_SAMPLES = 40
PAIR_BLOCK = 20000
MAX_PAIRS = 30_000_000
OFFSET = 1.0e6
BIGV = 1e6


def _edge_fun(cu, z, y0, a, e, sign):
    def g(s):
        qx = a[:, 0] + s * e[:, 0]
        qy = a[:, 1] + s * e[:, 1]
        qz = a[:, 2] + s * e[:, 2]
        h = qz - z
        rho = cu.radius_at(np.maximum(h, 0.0))
        perp = np.abs(qy - y0)
        viol = np.maximum(perp - rho, 0.0) + np.maximum(-h, 0.0) + np.maximum(h - cu.flute, 0.0)
        half = np.sqrt(np.maximum(rho * rho - perp * perp, 0.0))
        edge = qx - half if sign > 0 else -(qx + half)
        return np.where(viol <= 0, edge, BIGV + viol * 1e3)
    return g


def pair_push(cu: Cutter, z: float, y0, T, N, refine: bool = True):
    n = len(y0)
    lo = np.full(n, np.inf)
    hi = np.full(n, -np.inf)
    for vi in range(3):
        h = T[:, vi, 2] - z
        rho = cu.radius_at(np.maximum(h, 0.0))
        perp = np.abs(T[:, vi, 1] - y0)
        ok = (h >= 0) & (h <= cu.flute) & (perp <= rho)
        half = np.sqrt(np.maximum(rho * rho - perp * perp, 0.0))
        lo = np.where(ok, np.minimum(lo, T[:, vi, 0] - half), lo)
        hi = np.where(ok, np.maximum(hi, T[:, vi, 0] + half), hi)
    nxy = np.hypot(N[:, 0], N[:, 1])
    valid = (N[:, 2] > 1e-9) & (nxy > 1e-9) & (np.abs(N[:, 0]) > 1e-9)
    if valid.any():
        rho, hc = cu.support(nxy, N[:, 2])
        safe = np.where(nxy > 1e-9, nxy, 1.0)
        ox = -N[:, 0] / safe * rho
        oy = -N[:, 1] / safe * rho
        nx_s = np.where(np.abs(N[:, 0]) > 1e-9, N[:, 0], 1.0)
        t = T[:, 0, 0] - ox - (N[:, 1] * (y0 + oy - T[:, 0, 1]) + N[:, 2] * (z + hc - T[:, 0, 2])) / nx_s
        ok = valid & inside_xy(T, t + ox, y0 + oy)
        lo = np.where(ok, np.minimum(lo, t), lo)
        hi = np.where(ok, np.maximum(hi, t), hi)
    s_grid = np.linspace(0.0, 1.0, EDGE_SAMPLES)
    for ia, ib in ((0, 1), (1, 2), (2, 0)):
        a = T[:, ia]
        e = T[:, ib] - a
        h0 = a[:, 2] - z
        ez = e[:, 2]
        flat = np.abs(ez) < 1e-12
        s_lo = np.where(flat, 0.0, np.where(ez > 0, np.clip(-h0 / np.where(flat, 1.0, ez), 0.0, 1.0), 0.0))
        s_hi = np.where(flat, 1.0, np.where(ez < 0, np.clip(-h0 / np.where(flat, 1.0, ez), 0.0, 1.0), 1.0))
        okr = (s_hi > s_lo) | (flat & (h0 >= 0))
        okr &= ~(flat & (h0 < 0))
        if not okr.any():
            continue
        idx = np.nonzero(okr)[0]
        aa, ee, y = a[idx], e[idx], y0[idx]
        sl, sh = s_lo[idx], s_hi[idx]
        S = sl[:, None] + (sh - sl)[:, None] * s_grid[None, :]
        qx = aa[:, 0:1] + S * ee[:, 0:1]
        qy = aa[:, 1:2] + S * ee[:, 1:2]
        qz = aa[:, 2:3] + S * ee[:, 2:3]
        h = qz - z
        rho = cu.radius_at(np.maximum(h, 0.0))
        perp = np.abs(qy - y[:, None])
        ok = (perp <= rho) & (h >= -1e-12) & (h <= cu.flute)
        half = np.sqrt(np.maximum(rho * rho - perp * perp, 0.0))
        tl = np.where(ok, qx - half, np.inf)
        th = np.where(ok, qx + half, -np.inf)
        anyok = ok.any(axis=1)
        if not anyok.any():
            continue
        lo_i = tl.min(axis=1)
        hi_i = th.max(axis=1)
        for sign, best in (((1.0, lo_i), (-1.0, hi_i)) if refine else ()):
            arr = tl if sign > 0 else -th
            k = np.argmin(np.where(np.isfinite(arr), arr, np.inf), axis=1)
            rows = np.arange(len(idx))
            k0 = np.clip(k - 1, 0, EDGE_SAMPLES - 1)
            k1 = np.clip(k + 1, 0, EDGE_SAMPLES - 1)
            wa = sl + (sh - sl) * s_grid[k0]
            wb = sl + (sh - sl) * s_grid[k1]
            g = _edge_fun(cu, z, y, aa, ee, sign)
            c = wa + GOLDEN * (wb - wa)
            d = wb - GOLDEN * (wb - wa)
            fc, fd = g(c), g(d)
            for _ in range(22):
                left = fc < fd
                wb = np.where(left, d, wb)
                wa = np.where(left, wa, c)
                nc = np.where(left, wa + GOLDEN * (wb - wa), d)
                nd = np.where(left, c, wb - GOLDEN * (wb - wa))
                c, d = nc, nd
                fc, fd = g(c), g(d)
            ref = np.minimum(fc, fd)
            if sign > 0:
                best = np.where(ref < BIGV * 0.5, np.minimum(best, ref), best)
                lo_i = np.where(anyok, best, np.inf)
            else:
                best = np.where(ref < BIGV * 0.5, np.maximum(best, -ref), best)
                hi_i = np.where(anyok, best, -np.inf)
        cur_lo = lo[idx]
        cur_hi = hi[idx]
        lo[idx] = np.where(anyok, np.minimum(cur_lo, lo_i), cur_lo)
        hi[idx] = np.where(anyok, np.maximum(cur_hi, hi_i), cur_hi)
    return lo, hi


def merge(lo, hi, eps=1e-9):
    if len(lo) == 0:
        return np.zeros((0, 2))
    o = np.argsort(lo)
    lo, hi = lo[o], hi[o]
    run = np.maximum.accumulate(hi)
    start = np.concatenate(([True], lo[1:] > run[:-1] + eps))
    sid = np.nonzero(start)[0]
    ends = np.concatenate((sid[1:] - 1, [len(lo) - 1]))
    return np.stack([lo[sid], run[ends]], axis=1)


def fibers(surface: Surface, cu: Cutter, z: float, axis: int, coords, t0: float, t1: float, cancel=None) -> list:
    coords = np.asarray(coords, dtype=float)
    R = cu.R
    keep = surface.hi[:, 2] >= z
    tri_all = np.nonzero(keep)[0]
    out = [np.zeros((0, 2)) for _ in coords]
    if len(tri_all) == 0:
        return out
    T = surface.t[tri_all]
    N = surface.n[tri_all]
    if axis == 1:
        T = T[:, :, [1, 0, 2]]
        N = N[:, [1, 0, 2]]
    lo_y = T[:, :, 1].min(axis=1)
    hi_y = T[:, :, 1].max(axis=1)
    lo_x = T[:, :, 0].min(axis=1)
    hi_x = T[:, :, 0].max(axis=1)
    span = (hi_x >= t0 - R) & (lo_x <= t1 + R)
    fid_l, tri_l = [], []
    for fi, y0 in enumerate(coords):
        if cancel is not None:
            cancel()
        ids = np.nonzero(span & (lo_y - R <= y0) & (hi_y + R >= y0))[0]
        if len(ids):
            fid_l.append(np.full(len(ids), fi, dtype=np.int64))
            tri_l.append(ids)
    if not fid_l:
        return out
    fid = np.concatenate(fid_l)
    tri = np.concatenate(tri_l)
    if len(fid) > MAX_PAIRS:
        raise CamError("The push-cutter calculation would need %d fibre and triangle pairs, more than the limit of %d; use a larger fibre spacing or fewer triangles." % (len(fid), MAX_PAIRS))
    lo = np.empty(len(fid))
    hi = np.empty(len(fid))
    for b in range(0, len(fid), PAIR_BLOCK):
        if cancel is not None:
            cancel()
        s = slice(b, b + PAIR_BLOCK)
        lo[s], hi[s] = pair_push(cu, z, coords[fid[s]], T[tri[s]], N[tri[s]], False)
    ok = lo <= hi
    fid, tri, lo, hi = fid[ok], tri[ok], lo[ok], hi[ok]
    if len(fid) == 0:
        return out
    offs = fid * OFFSET
    o = np.argsort(lo + offs, kind="stable")
    fid, tri, lo, hi = fid[o], tri[o], lo[o], hi[o]
    run = np.maximum.accumulate(hi + fid * OFFSET)
    start = np.concatenate(([True], lo[1:] + fid[1:] * OFFSET > run[:-1] + 1e-9))
    cid = np.cumsum(start) - 1
    sid = np.nonzero(start)[0]
    ends = np.concatenate((sid[1:] - 1, [len(lo) - 1]))
    cl_lo = lo[sid]
    cl_hi = run[ends] - fid[ends] * OFFSET
    band = 0.1
    need = (lo <= cl_lo[cid] + band) | (hi >= cl_hi[cid] - band)
    if need.any():
        idx = np.nonzero(need)[0]
        for b in range(0, len(idx), PAIR_BLOCK // 4):
            if cancel is not None:
                cancel()
            sel = idx[b:b + PAIR_BLOCK // 4]
            lo2, hi2 = pair_push(cu, z, coords[fid[sel]], T[tri[sel]], N[tri[sel]], True)
            lo[sel] = np.minimum(lo[sel], lo2)
            hi[sel] = np.maximum(hi[sel], hi2)
        o = np.argsort(lo + fid * OFFSET, kind="stable")
        fid, lo, hi = fid[o], lo[o], hi[o]
        run = np.maximum.accumulate(hi + fid * OFFSET)
        start = np.concatenate(([True], lo[1:] + fid[1:] * OFFSET > run[:-1] + 1e-9))
        sid = np.nonzero(start)[0]
        ends = np.concatenate((sid[1:] - 1, [len(lo) - 1]))
        cl_lo = lo[sid]
        cl_hi = run[ends] - fid[ends] * OFFSET
    cf = fid[sid]
    for f in np.unique(cf):
        m = cf == f
        iv = np.stack([np.maximum(cl_lo[m], t0), np.minimum(cl_hi[m], t1)], axis=1)
        out[int(f)] = iv[iv[:, 0] < iv[:, 1]]
    return out
