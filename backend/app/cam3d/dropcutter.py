import numpy as np

from app.cam3d.cutters import Cutter
from app.cam3d.surface import Cancelled, Surface

PAIR_CHUNK = 600_000
GOLDEN = 0.3819660112501051


def inside_xy(T, qx, qy, eps=1e-9):
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
    return ok & (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps)


def pair_drop(cu: Cutter, px, py, T, N):
    R = cu.R
    z = np.full(len(px), -np.inf)
    for vi in range(3):
        d = np.hypot(T[:, vi, 0] - px, T[:, vi, 1] - py)
        m = d <= R
        zc = T[:, vi, 2] - cu.under(np.minimum(d, R))
        z = np.where(m, np.maximum(z, zc), z)
    nz = N[:, 2]
    nxy = np.hypot(N[:, 0], N[:, 1])
    valid = nz > 1e-9
    rho, hc = cu.support(nxy, nz)
    safe = np.where(nxy > 1e-9, nxy, 1.0)
    ux = np.where(nxy > 1e-9, -N[:, 0] / safe, 0.0)
    uy = np.where(nxy > 1e-9, -N[:, 1] / safe, 0.0)
    rho = np.where(nxy > 1e-9, rho, 0.0)
    qx = px + rho * ux
    qy = py + rho * uy
    pz = T[:, 0, 2] - (N[:, 0] * (qx - T[:, 0, 0]) + N[:, 1] * (qy - T[:, 0, 1])) / np.where(valid, nz, 1.0)
    ok = valid & inside_xy(T, qx, qy)
    z = np.where(ok, np.maximum(z, pz - hc), z)
    for ia, ib in ((0, 1), (1, 2), (2, 0)):
        a = T[:, ia]
        b = T[:, ib]
        ex, ey, ez = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1], b[:, 2] - a[:, 2]
        a2 = ex * ex + ey * ey
        use = a2 > 1e-18
        a2s = np.where(use, a2, 1.0)
        wx, wy = a[:, 0] - px, a[:, 1] - py
        b2 = 2.0 * (wx * ex + wy * ey)
        c2 = wx * wx + wy * wy - R * R
        disc = b2 * b2 - 4.0 * a2s * c2
        use &= disc >= 0
        sq = np.sqrt(np.maximum(disc, 0.0))
        lo = np.maximum((-b2 - sq) / (2.0 * a2s), 0.0)
        hi = np.minimum((-b2 + sq) / (2.0 * a2s), 1.0)
        use &= lo <= hi
        if not use.any():
            continue
        sd = np.clip(-(wx * ex + wy * ey) / a2s, 0.0, 1.0)
        dmin = np.hypot(wx + sd * ex, wy + sd * ey)
        ub = np.maximum(a[:, 2], b[:, 2]) - cu.under(np.minimum(dmin, R))
        use &= ub > z + 1e-9
        if not use.any():
            continue
        idx = np.nonzero(use)[0]
        wx, wy, ex, ey, ez = wx[idx], wy[idx], ex[idx], ey[idx], ez[idx]
        az = a[idx, 2]
        lo, hi = lo[idx], hi[idx]

        def f(s):
            d = np.minimum(np.hypot(wx + s * ex, wy + s * ey), R)
            return az + s * ez - cu.under(d)

        flo, fhi = f(lo), f(hi)
        best = np.maximum(flo, fhi)
        if cu.kind != "flat":
            aa, bb = lo.copy(), hi.copy()
            c = aa + GOLDEN * (bb - aa)
            d = bb - GOLDEN * (bb - aa)
            fc, fd = f(c), f(d)
            for _ in range(34):
                left = fc > fd
                bb = np.where(left, d, bb)
                aa = np.where(left, aa, c)
                nd = np.where(left, c, d)
                nfd = np.where(left, fc, fd)
                nc = np.where(left, aa + GOLDEN * (bb - aa), nd)
                nfc = f(nc)
                d_new = np.where(left, nd, bb - GOLDEN * (bb - aa))
                nfd2 = np.where(left, nfd, f(d_new))
                c, d, fc, fd = nc, d_new, nfc, nfd2
            best = np.maximum(best, np.maximum(fc, fd))
        z[idx] = np.maximum(z[idx], best)
    return z


def drop(surface: Surface, cu: Cutter, xy, cancel=None, progress=None) -> np.ndarray:
    pts = np.asarray(xy, dtype=float).reshape(-1, 2)
    out = np.full(len(pts), -np.inf)
    if len(pts) == 0:
        return np.full(0, np.nan)
    R = cu.R
    surface.bin(max(R * 2.0, 1e-6, float(max(surface.bmax[0] - surface.bmin[0], surface.bmax[1] - surface.bmin[1])) / 64.0))
    cs = surface.cs
    ox, oy = surface.bmin[0], surface.bmin[1]
    ci = np.floor((pts[:, 0] - ox) / cs).astype(np.int64)
    cj = np.floor((pts[:, 1] - oy) / cs).astype(np.int64)
    key = ci * 1_000_003 + cj
    order = np.argsort(key, kind="stable")
    skey = key[order]
    cuts = np.nonzero(np.diff(skey))[0] + 1
    groups = np.split(order, cuts)
    done = 0
    for g in groups:
        if cancel is not None:
            cancel()
        gp = pts[g]
        x0, x1 = gp[:, 0].min() - R, gp[:, 0].max() + R
        y0, y1 = gp[:, 1].min() - R, gp[:, 1].max() + R
        tid = surface.near(x0, x1, y0, y1)
        if len(tid):
            tlo = surface.lo[tid]
            thi = surface.hi[tid]
            step = max(1, PAIR_CHUNK // max(len(tid), 1))
            for s in range(0, len(g), step):
                gi = g[s:s + step]
                p = pts[gi]
                m = (p[:, 0:1] >= tlo[None, :, 0] - R) & (p[:, 0:1] <= thi[None, :, 0] + R) & (p[:, 1:2] >= tlo[None, :, 1] - R) & (p[:, 1:2] <= thi[None, :, 1] + R)
                pi, ti = np.nonzero(m)
                if len(pi) == 0:
                    continue
                for c0 in range(0, len(pi), PAIR_CHUNK):
                    pc = pi[c0:c0 + PAIR_CHUNK]
                    tc = tid[ti[c0:c0 + PAIR_CHUNK]]
                    z = pair_drop(cu, p[pc, 0], p[pc, 1], surface.t[tc], surface.n[tc])
                    np.maximum.at(out, gi[pc], z)
        done += len(g)
        if progress is not None:
            progress(done / len(pts))
    out[~np.isfinite(out)] = np.nan
    return out
