import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from app.cam3d import contours, dropcutter
from app.cam3d.cutters import Cutter
from app.cam3d.surface import CamError, Surface

POINT = Cutter("flat", 0.002)
MIN_STEP = 0.02


def grown(cu: Cutter, s: float) -> Cutter:
    if s <= 1e-9:
        return cu
    if cu.kind == "ball":
        return Cutter("ball", 2.0 * (cu.R + s), flute=cu.flute)
    if cu.kind == "bull":
        return Cutter("bull", 2.0 * (cu.R + s), cu.r + s, flute=cu.flute)
    if cu.kind == "flat":
        return Cutter("bull", 2.0 * (cu.R + s), s, flute=cu.flute)
    half = math.degrees(math.atan(cu.tan))
    return Cutter("cone", 2.0 * (cu.R + s), half_angle=half, tip_diameter=2.0 * cu.rt, flute=cu.flute)


def scallop_step(radius: float, scallop: float) -> float:
    h = min(max(scallop, 1e-6), radius)
    return 2.0 * math.sqrt(max(2.0 * h * radius - h * h, 0.0))


def heightfield(surf: Surface, cu: Cutter, xs, ys, cancel=None, progress=None) -> np.ndarray:
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    z = dropcutter.drop(surf, cu, np.stack([X.ravel(), Y.ravel()], axis=1), cancel, progress)
    return z.reshape(len(xs), len(ys))


def drop_points(surf, cu, stl, xy, cancel=None, foot=True):
    z = dropcutter.drop(surf, grown(cu, stl), xy, cancel) + stl
    if foot:
        z = np.where(np.isfinite(dropcutter.drop(surf, POINT, xy, cancel)), z, np.nan)
    return z


def refine(surf, cu, stl, lines, tol, cancel=None, max_depth=9):
    cug = grown(cu, stl)
    active = [np.ones(len(L["t"]) - 1, dtype=bool) for L in lines]
    for depth in range(max_depth):
        mids, owners = [], []
        for li, L in enumerate(lines):
            idx = np.nonzero(active[li])[0]
            if len(idx):
                idx = idx[(L["t"][idx + 1] - L["t"][idx]) > MIN_STEP * 2.0]
            active[li] = np.zeros(len(L["t"]) - 1, dtype=bool)
            if len(idx) == 0:
                continue
            tm = (L["t"][idx] + L["t"][idx + 1]) / 2.0
            mids.append(np.stack([L["o"][0] + tm * L["d"][0], L["o"][1] + tm * L["d"][1]], axis=1))
            owners.append((li, idx, tm))
        if not mids:
            break
        zm = drop_points(surf, cu, stl, np.concatenate(mids), cancel)
        pos = 0
        for li, idx, tm in owners:
            L = lines[li]
            z0, z1 = L["z"][idx], L["z"][idx + 1]
            z_mid = zm[pos:pos + len(idx)]
            pos += len(idx)
            f0, f1, fm = np.isfinite(z0), np.isfinite(z1), np.isfinite(z_mid)
            flat = f0 & f1 & fm & (np.abs(np.where(f0 & f1 & fm, z_mid - (z0 + z1) / 2.0, 0.0)) <= tol)
            split = ~(flat | (~f0 & ~f1 & ~fm))
            if not split.any():
                continue
            t_new = np.concatenate([L["t"], tm[split]])
            z_new = np.concatenate([L["z"], z_mid[split]])
            fresh = np.concatenate([np.zeros(len(L["t"]), dtype=bool), np.ones(int(split.sum()), dtype=bool)])
            o = np.argsort(t_new, kind="stable")
            L["t"], L["z"] = t_new[o], z_new[o]
            fresh = fresh[o]
            active[li] = fresh[:-1] | fresh[1:]
    return lines


def runs_of(L, bottom):
    t, z = L["t"], L["z"]
    ok = np.isfinite(z)
    out = []
    i = 0
    n = len(t)
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1]:
            j += 1
        xy = np.stack([L["o"][0] + t[i:j + 1] * L["d"][0], L["o"][1] + t[i:j + 1] * L["d"][1]], axis=1)
        zz = np.maximum(z[i:j + 1], bottom)
        out.append(np.column_stack([xy, zz]))
        i = j + 1
    return out


def parallel(surf, cu, bounds, angle, step, tol, stl, bottom, rings=None, zigzag=True, climb=True, cancel=None, progress=None):
    x0, y0, x1, y1 = bounds
    ang = math.radians(angle)
    u = (math.cos(ang), math.sin(ang))
    v = (-math.sin(ang), math.cos(ang))
    corners = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    cu_ = corners @ np.array(u)
    cv_ = corners @ np.array(v)
    umin, umax, vmin, vmax = cu_.min(), cu_.max(), cv_.min(), cv_.max()
    n = int(math.ceil((vmax - vmin) / step - 1e-9)) + 1
    if n > 100000:
        raise CamError("The stepover gives too many passes.")
    vs = vmin + step * np.arange(n)
    ds = max(min(cu.R, 1.0), tol * 2.0, MIN_STEP * 4.0)
    lines = []
    raw = []
    for vv in vs:
        o = (u[0] * umin + v[0] * vv, u[1] * umin + v[1] * vv)
        raw.append((o, vv))
    if rings:
        from app.cam import geom

        def rot(rs, a):
            c, s = math.cos(a), math.sin(a)
            return [[(px * c - py * s, px * s + py * c) for px, py in r] for r in rs]

        rr = rot(rings, -ang)
        lines_r = [[(umin - 1.0, vv), (umax + 1.0, vv)] for vv in vs]
        clipped = geom.clip_open_lines(lines_r, rr)
        spans = []
        for seg in clipped:
            a, b = seg[0], seg[-1]
            spans.append((min(a[1], b[1]), min(a[0], b[0]), max(a[0], b[0])))
        pieces = [(vv, a, b) for vv, a, b in ((s[0], s[1], s[2]) for s in spans)]
    else:
        pieces = [(vv, umin, umax) for vv in vs]
    for vv, a, b in pieces:
        L = b - a
        if L < 1e-6:
            continue
        o = (u[0] * a + v[0] * vv, u[1] * a + v[1] * vv)
        m = max(int(math.ceil(L / ds)), 1)
        t = np.linspace(0.0, L, m + 1)
        lines.append({"o": o, "d": u, "t": t, "v": vv})
    if not lines:
        raise CamError("No passes fit the region.")
    allxy = np.concatenate([np.stack([L["o"][0] + L["t"] * L["d"][0], L["o"][1] + L["t"] * L["d"][1]], axis=1) for L in lines])
    z = drop_points(surf, cu, stl, allxy, cancel)
    p = 0
    for L in lines:
        L["z"] = z[p:p + len(L["t"])]
        p += len(L["t"])
    refine(surf, cu, stl, lines, tol, cancel)
    lines.sort(key=lambda L: L["v"])
    passes = []
    for k, L in enumerate(lines):
        rs = runs_of(L, bottom)
        want_rev = climb if not zigzag else (climb != (k % 2 == 1))
        for r in rs:
            if len(r) < 2:
                continue
            r = contours.simplify3(r, tol * 0.5)
            passes.append(r[::-1] if want_rev else r)
    return passes


def waterline(surf, cu, zs, bounds, grid, tol, stl, cancel=None, progress=None, climb=True):
    cug = grown(cu, stl)
    out = []
    for k, z in enumerate(zs):
        loops = contours.weave_loops(surf, cug, z - stl, bounds, grid, cancel)
        level = []
        for pts, closed in loops:
            if len(pts) < 3:
                continue
            q = pts
            if closed:
                q = np.vstack([pts, pts[:1]])
            q = contours.simplify2(q, tol * 0.5, closed)
            if len(q) < 3:
                continue
            if climb:
                q = q[::-1]
            level.append((np.column_stack([q, np.full(len(q), z)]), closed))
        out.append((z, level))
        if progress is not None:
            progress((k + 1) / len(zs))
    return out


def scallop(surf, cu, bounds, step, grid, tol, stl, bottom, mask_fn=None, cancel=None, progress=None, climb=True, max_cells=1_500_000):
    x0, y0, x1, y1 = bounds
    nx = int(math.ceil((x1 - x0) / grid)) + 1
    ny = int(math.ceil((y1 - y0) / grid)) + 1
    if nx * ny > max_cells:
        raise CamError("The scallop grid has %d cells, more than the limit of %d; use a larger grid or a smaller region." % (nx * ny, max_cells))
    xs = np.linspace(x0, x1, nx)
    ys = np.linspace(y0, y1, ny)
    cug = grown(cu, stl)
    Z = heightfield(surf, cug, xs, ys, cancel, None) + stl
    foot = heightfield(surf, POINT, xs, ys, cancel, None)
    Z = np.where(np.isfinite(foot), Z, np.nan)
    if mask_fn is not None:
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        Z = np.where(mask_fn(X, Y), Z, np.nan)
    valid = np.isfinite(Z)
    if not valid.any():
        raise CamError("The tool touches no model surface inside the region.")
    Zf = np.where(valid, Z, 0.0)
    idx = np.arange(nx * ny).reshape(nx, ny)
    rows, cols, wts = [], [], []
    offs = [(1, 0), (0, 1), (1, 1), (1, -1), (2, 1), (1, 2), (2, -1), (1, -2)]
    for di, dj in offs:
        i0, i1 = (0, nx - di) if di >= 0 else (-di, nx)
        j0, j1 = (0, ny - dj) if dj >= 0 else (-dj, ny)
        a = (slice(i0, i1), slice(j0, j1))
        b = (slice(i0 + di, i1 + di), slice(j0 + dj, j1 + dj))
        ok = valid[a] & valid[b]
        w = np.sqrt((di * (xs[1] - xs[0])) ** 2 + (dj * (ys[1] - ys[0])) ** 2 + (Zf[b] - Zf[a]) ** 2)
        rows.append(idx[a][ok])
        cols.append(idx[b][ok])
        wts.append(w[ok])
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    w = np.concatenate(wts)
    g = coo_matrix((np.concatenate([w, w]), (np.concatenate([r, c]), np.concatenate([c, r]))), shape=(nx * ny, nx * ny)).tocsr()
    inv = np.pad(~valid, 1, constant_values=True)
    near_invalid = (inv[:-2, 1:-1] | inv[2:, 1:-1] | inv[1:-1, :-2] | inv[1:-1, 2:]) & valid
    src = np.nonzero(near_invalid.ravel())[0]
    if len(src) == 0:
        src = np.array([int(np.nonzero(valid.ravel())[0][0])])
    dist = dijkstra(g, directed=False, indices=src, min_only=True)
    D = np.where(valid.ravel(), dist, np.nan).reshape(nx, ny)
    Dmax = float(np.nanmax(np.where(np.isfinite(D), D, np.nan)))
    levels = []
    k = 0
    while True:
        lv = grid * 0.5 + k * step
        if lv >= Dmax:
            break
        levels.append(lv)
        k += 1
        if k > 20000:
            raise CamError("The stepover gives too many passes.")
    passes = []
    for li, lv in enumerate(levels):
        if cancel is not None:
            cancel()
        for pts, closed in contours.field_loops(np.where(np.isfinite(D), D, -1e30), lv, xs, ys):
            if len(pts) < 3:
                continue
            q = np.vstack([pts, pts[:1]]) if closed else pts
            q = contours.simplify2(q, tol * 0.5, closed)
            if climb:
                q = q[::-1]
            z = drop_points(surf, cu, stl, q)
            ok = np.isfinite(z)
            if ok.sum() < 2:
                continue
            q, z = q[ok], np.maximum(z[ok], bottom)
            passes.append((np.column_stack([q, z]), closed))
        if progress is not None:
            progress((li + 1) / len(levels))
    return passes, {"cell": grid, "levels": len(levels), "max_distance": Dmax}
