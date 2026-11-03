import math

import numpy as np
from scipy import ndimage

from app.cam import feeds as F
from app.cam import geom, limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common, pocket
from app.cam.registry import Field, OpType, register

SAMPLES = 128
CAND = 25
EPS = 0.05


def raster(rings, x0, y0, cs, nx, ny):
    tog = np.zeros((ny, nx + 1), dtype=np.int32)
    for ring in rings:
        p = np.asarray(ring, dtype=float)
        if len(p) < 3:
            continue
        a = p
        b = np.roll(p, -1, axis=0)
        ymin = np.minimum(a[:, 1], b[:, 1])
        ymax = np.maximum(a[:, 1], b[:, 1])
        j0 = np.ceil((ymin - y0) / cs - 0.5).astype(np.int64)
        j1 = np.ceil((ymax - y0) / cs - 0.5).astype(np.int64)
        cnt = np.maximum(j1 - j0, 0)
        total = int(cnt.sum())
        if total == 0:
            continue
        e = np.repeat(np.arange(len(p)), cnt)
        start = np.cumsum(cnt) - cnt
        offs = np.arange(total) - np.repeat(start, cnt)
        j = j0[e] + offs
        yj = y0 + (j + 0.5) * cs
        dy = b[e, 1] - a[e, 1]
        t = (yj - a[e, 1]) / np.where(dy == 0, 1e-12, dy)
        x = a[e, 0] + t * (b[e, 0] - a[e, 0])
        c = np.ceil((x - x0) / cs - 0.5).astype(np.int64)
        ok = (j >= 0) & (j < ny)
        c = np.clip(c, 0, nx)
        np.add.at(tog, (j[ok], c[ok]), 1)
    return (np.cumsum(tog, axis=1)[:, :nx] & 1).astype(bool)


class Grid:
    def __init__(self, bounds, cs, pad, inflate=0.0):
        x0, y0, x1, y1 = bounds
        self.cs = cs
        self.inflate = inflate
        self.x0 = x0 - pad
        self.y0 = y0 - pad
        self.nx = int(math.ceil((x1 - x0 + 2 * pad) / cs)) + 1
        self.ny = int(math.ceil((y1 - y0 + 2 * pad) / cs)) + 1

    def idx(self, x, y):
        return np.floor((y - self.y0) / self.cs).astype(np.int64), np.floor((x - self.x0) / self.cs).astype(np.int64)

    def lookup(self, mask, x, y):
        j, i = self.idx(x, y)
        ok = (j >= 0) & (j < self.ny) & (i >= 0) & (i < self.nx)
        out = np.zeros(np.shape(x), dtype=bool)
        out[ok] = mask[j[ok], i[ok]]
        return out

    def centres(self):
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.cs
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.cs
        return xs, ys

    def clear_capsule(self, mask, a, b, r) -> int:
        lo_x = min(a[0], b[0]) - r - self.cs
        hi_x = max(a[0], b[0]) + r + self.cs
        lo_y = min(a[1], b[1]) - r - self.cs
        hi_y = max(a[1], b[1]) + r + self.cs
        i0 = max(int((lo_x - self.x0) / self.cs), 0)
        i1 = min(int((hi_x - self.x0) / self.cs) + 1, self.nx)
        j0 = max(int((lo_y - self.y0) / self.cs), 0)
        j1 = min(int((hi_y - self.y0) / self.cs) + 1, self.ny)
        if i1 <= i0 or j1 <= j0:
            return 0
        xs = self.x0 + (np.arange(i0, i1) + 0.5) * self.cs
        ys = self.y0 + (np.arange(j0, j1) + 0.5) * self.cs
        X, Y = np.meshgrid(xs, ys)
        ab = np.array([b[0] - a[0], b[1] - a[1]])
        L2 = float(ab @ ab)
        if L2 < 1e-12:
            t = np.zeros_like(X)
        else:
            t = np.clip(((X - a[0]) * ab[0] + (Y - a[1]) * ab[1]) / L2, 0.0, 1.0)
        d2 = (X - (a[0] + t * ab[0])) ** 2 + (Y - (a[1] + t * ab[1])) ** 2
        sub = mask[j0:j1, i0:i1]
        hit = sub & (d2 <= (r + self.inflate * self.cs) ** 2)
        n = int(hit.sum())
        sub[hit] = False
        return n


class Planner:
    def __init__(self, ctx, region, cen_rings, stl, phi_t, hr_want, step, beta, cs):
        t = ctx.tool
        self.ctx = ctx
        self.r = t.radius
        self.phi_t = phi_t
        self.step = step
        self.beta = beta
        self.cs = cs
        self.hr_want = hr_want
        bnds = geom.bounds(region.rings)
        self.grid = Grid(bnds, cs, self.r + 2 * cs)
        limits.need(self.grid.nx * self.grid.ny, "grid_cells", "Adaptive grid")
        g = self.grid
        self.U = raster(region.offset(-stl).rings, g.x0, g.y0, cs, g.nx, g.ny)
        self.C = raster(cen_rings, g.x0, g.y0, cs, g.nx, g.ny)
        self.dist_c = ndimage.distance_transform_edt(self.C) * cs
        near = ndimage.distance_transform_edt(~self.C) * cs
        self.U &= near <= self.r + cs
        self.ang = np.linspace(0.0, 2.0 * math.pi, SAMPLES, endpoint=False)
        self.off = np.stack([self.r * np.cos(self.ang), self.r * np.sin(self.ang)], axis=1)
        self.chains = []
        self.hist = []
        self.max_eng = 0.0
        self.steps = 0
        self.ignored = 0

    def engagement(self, px, py):
        pts_x = px[:, None] + self.off[None, :, 0]
        pts_y = py[:, None] + self.off[None, :, 1]
        hit = self.grid.lookup(self.U, pts_x, pts_y)
        return hit.sum(axis=1) * (2.0 * math.pi / SAMPLES)

    def feasible(self, px, py):
        return self.grid.lookup(self.C, px, py)

    def stay_ok(self, a, b) -> bool:
        ln = math.dist(a, b)
        n = max(2, int(ln / (self.cs * 2)) + 1)
        t = np.linspace(0.0, 1.0, n + 1)
        px = a[0] + (b[0] - a[0]) * t
        py = a[1] + (b[1] - a[1]) * t
        if not self.feasible(px, py).all():
            return False
        near_end = np.hypot(px - b[0], py - b[1]) <= 0.6 * self.r
        return bool((self.engagement(px, py)[~near_end] < EPS).all())

    def entry_for(self, p0):
        hr = self.hr_want
        if hr > 0.0:
            best = None
            for k in range(12):
                a = 2.0 * math.pi * k / 12
                c = (p0[0] - hr * math.cos(a), p0[1] - hr * math.sin(a))
                ang = np.linspace(0, 2 * math.pi, 16, endpoint=False)
                px = c[0] + hr * np.cos(ang)
                py = c[1] + hr * np.sin(ang)
                if self.feasible(np.array([c[0]]), np.array([c[1]]))[0] and self.feasible(px, py).all():
                    best = (c, a)
                    break
            if best:
                return ("helix", best[0], hr, best[1])
        return ("plunge", None, 0.0, 0.0)

    def apply_entry(self, entry, p0):
        if entry[0] == "helix":
            c, hr = entry[1], entry[2]
            self.grid.clear_capsule(self.U, c, c, hr + self.r)
        else:
            self.grid.clear_capsule(self.U, p0, p0, self.r)

    def run_chain(self, p0, heading):
        pts = [p0]
        cur = np.array(p0, dtype=float)
        d = heading
        idle = 0
        narrow = np.linspace(-self.beta, self.beta, CAND)
        wide = np.linspace(-math.pi, math.pi, 73, endpoint=False)
        first = True
        while True:
            self.steps += 1
            if self.steps % 200 == 0:
                self.ctx.check()
                limits.need(self.steps, "moves", "Adaptive steps")
            offs = wide if first else narrow
            first = False
            ang = d + offs
            nx_ = cur[0] + self.step * np.cos(ang)
            ny_ = cur[1] + self.step * np.sin(ang)
            ok = self.feasible(nx_, ny_)
            if not ok.any():
                break
            eng = self.engagement(nx_, ny_)
            err = eng - self.phi_t
            cost = np.where(err > 0, 4.0 * err, -err) + 0.04 * np.abs(offs)
            cost = np.where(ok, cost, 1e9)
            k = int(np.argmin(cost))
            if eng[k] < EPS:
                far = ok & (eng >= EPS)
                if not far.any():
                    break
                k = int(np.argmin(np.where(far, cost, 1e9)))
            new = np.array([nx_[k], ny_[k]])
            n = self.grid.clear_capsule(self.U, cur, new, self.r)
            self.max_eng = max(self.max_eng, float(eng[k]))
            self.hist.append(float(eng[k]))
            d = float(ang[k])
            cur = new
            pts.append((float(cur[0]), float(cur[1])))
            idle = idle + 1 if n == 0 else 0
            if idle > 60:
                break
        return pts

    def next_start(self, cur):
        g = self.grid
        while True:
            js, is_ = np.nonzero(self.U)
            if len(js) == 0:
                return None
            xs = g.x0 + (is_ + 0.5) * g.cs
            ys = g.y0 + (js + 0.5) * g.cs
            d = np.hypot(xs - cur[0], ys - cur[1])
            k = int(np.argmin(d))
            ux, uy = float(xs[k]), float(ys[k])
            lo_i = max(int((ux - self.r - g.x0) / g.cs) - 1, 0)
            hi_i = min(int((ux + self.r - g.x0) / g.cs) + 2, g.nx)
            lo_j = max(int((uy - self.r - g.y0) / g.cs) - 1, 0)
            hi_j = min(int((uy + self.r - g.y0) / g.cs) + 2, g.ny)
            sub = self.C[lo_j:hi_j, lo_i:hi_i]
            jj, ii = np.nonzero(sub)
            if len(jj) == 0:
                self.U[js[k], is_[k]] = False
                continue
            cx = g.x0 + (ii + lo_i + 0.5) * g.cs
            cy = g.y0 + (jj + lo_j + 0.5) * g.cs
            dd = np.hypot(cx - ux, cy - uy)
            ok = dd <= self.r + g.cs
            if not ok.any():
                self.U[js[k], is_[k]] = False
                continue
            cand = np.nonzero(ok)[0]
            cand = cand[np.argsort(dd[cand])[:10]]
            counts = [self.under((float(cx[q]), float(cy[q]))) for q in cand]
            top = max(counts)
            best = [q for q, c in zip(cand, counts) if c >= 0.85 * top]
            pick = best[int(np.argmin(np.hypot(cx[best] - cur[0], cy[best] - cur[1])))]
            p = (float(cx[pick]), float(cy[pick]))
            if top < 3:
                g.clear_capsule(self.U, (ux, uy), (ux, uy), self.cs * 1.5)
                self.ignored += 1
                continue
            return p, math.atan2(uy - p[1], ux - p[0])

    def under(self, p) -> int:
        g = self.grid
        i0 = max(int((p[0] - self.r - g.x0) / g.cs), 0)
        i1 = min(int((p[0] + self.r - g.x0) / g.cs) + 2, g.nx)
        j0 = max(int((p[1] - self.r - g.y0) / g.cs), 0)
        j1 = min(int((p[1] + self.r - g.y0) / g.cs) + 2, g.ny)
        xs = g.x0 + (np.arange(i0, i1) + 0.5) * g.cs
        ys = g.y0 + (np.arange(j0, j1) + 0.5) * g.cs
        X, Y = np.meshgrid(xs, ys)
        return int((self.U[j0:j1, i0:i1] & ((X - p[0]) ** 2 + (Y - p[1]) ** 2 <= self.r ** 2)).sum())

    def plan(self):
        g = self.grid
        if not self.U.any():
            raise CamError("There is no material to clear in this region.")
        j, i = np.unravel_index(int(np.argmax(self.dist_c)), self.dist_c.shape)
        c0 = (g.x0 + (i + 0.5) * g.cs, g.y0 + (j + 0.5) * g.cs)
        maxd = float(self.dist_c[j, i])
        hr = min(self.hr_want, maxd * 0.8)
        if hr < 0.1:
            hr = 0.0
        self.hr_want = hr
        p0 = (c0[0] + hr, c0[1]) if hr > 0 else c0
        entry = ("helix", c0, hr, 0.0) if hr > 0 else ("plunge", None, 0.0, 0.0)
        self.apply_entry(entry, p0)
        heading = math.pi / 2.0
        link = "start"
        cur = p0
        while True:
            pts = self.run_chain(p0, heading)
            self.chains.append({"entry": entry, "link": link, "pts": pts})
            cur = pts[-1]
            if len(self.chains) > 5000:
                raise CamError("The adaptive path needs too many separate passes; use a larger region step or a smaller region.")
            nxt = self.next_start(cur)
            if nxt is None:
                break
            p0, heading = nxt
            link = "stay" if self.stay_ok(cur, p0) else "retract"
            entry = self.entry_for(p0)
            self.apply_entry(entry, p0)
            self.ctx.progress(1.0 - float(self.U.sum()) / max(float(self.initial), 1.0))


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    h = ctx.h
    region = ctx.region()
    stl = p["stock_to_leave_xy"]
    cen = geom.offset(region.rings, -(t.radius + stl))
    if not cen:
        raise CamError("The tool is too large for this region.")
    ae = p["optimal_load"] if p["optimal_load"] is not None else 0.1 * t.diameter
    if ae <= 0 or ae >= t.diameter / 2.0:
        raise CamError("The optimal load must be between zero and half the tool diameter.")
    phi_t = F.engagement_angle(ae, t.diameter)
    bottom = ctx.bottom() + p["stock_to_leave_z"]
    zs = common.levels(h.top, bottom, p["stepdown"] if p["stepdown"] is not None else t.diameter)
    f = ctx.feed_for(ae, 0.0)
    cs = max(t.radius / 10.0, 0.04)
    bnds = geom.bounds(region.rings)
    area = (bnds[2] - bnds[0] + 2 * t.diameter) * (bnds[3] - bnds[1] + 2 * t.diameter)
    cs = max(cs, math.sqrt(area / ctx.limit["grid_cells"]) * 1.02)
    step = max(cs * 1.2, 0.2 * t.radius)
    limits.need(int(area / max(ae, 1e-6) / step), "moves", "Estimated adaptive steps")
    hr = ((p["helix_diameter"] or 1.5 * t.diameter) - t.diameter) / 2.0 if p["entry"] == "helix" else 0.0
    pl = Planner(ctx, region, cen, stl, phi_t, max(hr, 0.0), step, math.radians(70.0), cs)
    pl.initial = float(pl.U.sum())
    pl.plan()
    limits.need(len(pl.chains) * len(zs), "passes", "Adaptive passes")
    tol = p["tolerance"]
    for ch in pl.chains:
        ch["pts"] = geom.simplify(ch["pts"], tol)
    npts = sum(len(c["pts"]) for c in pl.chains) * len(zs)
    limits.need(npts, "moves", "Adaptive moves")
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    for li, z in enumerate(zs):
        z_from = min(h.feed, h.top + 1.0) if li == 0 else zs[li - 1]
        for ci, ch in enumerate(pl.chains):
            ctx.check()
            pts = ch["pts"]
            a = pts[0]
            if ci > 0 and ch["link"] == "stay" and pen.pos is not None:
                pen.feed(a[0], a[1], z, f["vf_cut"], "link")
            else:
                if ci == 0 and li == 0 or pen.pos is None:
                    pen.over(a[0], a[1], z_from if ch["entry"][0] != "helix" else z_from)
                else:
                    pocket.descend(pen, a, h, z_from, li, f)
                kind, c, hr_, ang = ch["entry"]
                if kind == "helix":
                    common.helix_at(pen, c[0], c[1], hr_, z_from, z, f["vf_ramp"], p["ramp_angle"], ang)
                else:
                    pen.feed(a[0], a[1], z, f["vf_plunge"], "plunge")
            for q in pts[1:]:
                pen.feed(q[0], q[1], z, f["vf_cut"], "cut")
        ctx.progress((li + 1) / len(zs))
    pen.finish()
    ctx.meta = {"chains": len(pl.chains), "levels": len(zs), "optimal_load": ae, "engagement_target_deg": round(math.degrees(phi_t), 2), "engagement_max_deg": round(math.degrees(pl.max_eng), 2), "cell": round(cs, 4), "ignored_crumbs": pl.ignored}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="adaptive", label="Adaptive clearing", group="2d", generate=generate, tool_kinds=("flat", "bull"), geometry=("polygons", "rect", "entities", "section", "removal"),
    description="Clear a region with a path that holds the tool's radial engagement near a target angle, so deep cuts and full flute use stay safe.",
    fields=[
        Field("optimal_load", "number", None, "Optimal load (radial engagement)", 0.001, 500.0, "mm", group="Passes", nullable=True),
        Field("stepdown", "number", None, "Maximum stepdown", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stock_to_leave_xy", "number", 0.3, "Stock to leave on walls", 0.0, 50.0, "mm", group="Passes"),
        Field("stock_to_leave_z", "number", 0.0, "Stock to leave on floor", 0.0, 50.0, "mm", group="Passes"),
        Field("tolerance", "number", 0.02, "Path smoothing tolerance", 0.001, 1.0, "mm", group="Passes"),
        Field("entry", "choice", "helix", "Entry", choices=("helix", "plunge"), group="Linking"),
        Field("ramp_angle", "number", 3.0, "Ramp angle", 0.1, 45.0, "deg", group="Linking"),
        Field("helix_diameter", "number", None, "Helix diameter", 0.1, 1000.0, "mm", group="Linking", nullable=True),
    ],
))
