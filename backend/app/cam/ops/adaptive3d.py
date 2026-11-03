import math

import numpy as np

from app.cam import feeds as F
from app.cam import geom, limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import adaptive as ad
from app.cam.ops import common
from app.cam.registry import Field, OpType, register
from app.cam3d import contours, opkit, paths3d


def loops_to_rings(loops, closed_only=True):
    rings = []
    for pts, closed in loops:
        if closed and len(pts) >= 3:
            rings.append([(float(a), float(b)) for a, b in pts[:, :2]])
    return geom.normalize(rings) if rings else []


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    h = ctx.h
    surf = opkit.model_surface(ctx)
    cu = opkit.cutter_of(ctx)
    stl = p["stock_to_leave"]
    stock_rings = ctx.stock_polygon()
    sb = ctx.stock
    top = h.top
    bottom = opkit.clamp_bottom(ctx, surf) + p["stock_to_leave_floor"]
    zs = common.levels(top, bottom, p["stepdown"] if p["stepdown"] is not None else t.diameter)
    ae = p["optimal_load"] if p["optimal_load"] is not None else 0.1 * t.diameter
    if ae <= 0 or ae >= t.diameter / 2.0:
        raise CamError("The optimal load must be between zero and half the tool diameter.")
    phi_t = F.engagement_angle(ae, t.diameter)
    f = ctx.feed_for(ae, 0.0)
    bnds = geom.bounds(stock_rings)
    cs = max(t.radius / 8.0, 0.04)
    area = (bnds[2] - bnds[0] + 2 * t.diameter) * (bnds[3] - bnds[1] + 2 * t.diameter)
    cs = max(cs, math.sqrt(area / ctx.limit["grid_cells"]) * 1.02)
    step = max(cs * 1.2, 0.2 * t.radius)
    hr = ((p["helix_diameter"] or 1.5 * t.diameter) - t.diameter) / 2.0 if p["entry"] == "helix" else 0.0
    grid = p["sampling"] if p["sampling"] is not None else max(min(t.radius * 0.25, 1.0), 0.1)
    pad = cu.R + stl + 3.0 * grid
    wb = (bnds[0] - pad, bnds[1] - pad, bnds[2] + pad, bnds[3] + pad)
    gx = np.arange(wb[0], wb[2] + grid, grid)
    gy = np.arange(wb[1], wb[3] + grid, grid)
    limits.need(len(gx) * len(gy), "grid_cells", "Roughing grid")
    ctx.progress(0.0)
    H = paths3d.heightfield(surf, paths3d.POINT, gx, gy, ctx.check)
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    stats = {"levels": 0, "chains": 0, "engagement_max": 0.0, "skipped_levels": 0}
    tol = p["tolerance"]
    prev_z = None
    for li, z in enumerate(zs):
        ctx.check()
        sil = contours.field_loops(np.where(np.isfinite(H), H, -1e30), z + 1e-6, gx, gy)
        sil_rings = loops_to_rings(sil)
        sil_g = geom.offset(sil_rings, stl) if sil_rings and stl > 1e-9 else sil_rings
        region_rings = geom.difference(stock_rings, sil_g) if sil_g else stock_rings
        bar = paths3d.waterline(surf, cu, [z], wb, grid, tol, stl, ctx.check, None, True)[0][1]
        barrier = loops_to_rings(bar)
        cen = geom.difference(stock_rings, barrier) if barrier else stock_rings
        if not region_rings or not cen:
            stats["skipped_levels"] += 1
            continue
        pl = ad.Planner(ctx, geom.Region(region_rings), cen, 0.0, phi_t, max(hr, 0.0), step, math.radians(70.0), cs)
        pl.initial = float(pl.U.sum())
        if pl.initial < 1.0:
            stats["skipped_levels"] += 1
            continue
        try:
            pl.plan()
        except CamError:
            stats["skipped_levels"] += 1
            continue
        stats["levels"] += 1
        stats["chains"] += len(pl.chains)
        stats["engagement_max"] = max(stats["engagement_max"], pl.max_eng)
        limits.need(len(pl.chains) * len(zs), "passes", "Adaptive passes")
        z_from = min(h.feed, h.top + 1.0) if prev_z is None else prev_z
        for ci, ch in enumerate(pl.chains):
            ctx.check()
            pts = geom.simplify(ch["pts"], tol)
            a = pts[0]
            if ci > 0 and ch["link"] == "stay" and pen.pos is not None and abs(pen.pos[2] - z) < 1e-9:
                pen.feed(a[0], a[1], z, f["vf_cut"], "link")
            else:
                pen.over(a[0], a[1], max(h.retract, z_from + 0.5))
                kind, c, hr_, ang = ch["entry"]
                if kind == "helix":
                    common.helix_at(pen, c[0], c[1], hr_, z_from, z, f["vf_ramp"], p["ramp_angle"], ang)
                else:
                    pen.feed(a[0], a[1], z_from, f["vf_plunge"], "plunge")
                    pen.feed(a[0], a[1], z, f["vf_plunge"], "plunge")
            for q in pts[1:]:
                pen.feed(q[0], q[1], z, f["vf_cut"], "cut")
        prev_z = z
        ctx.progress((li + 1) / len(zs))
    pen.finish()
    if stats["levels"] == 0:
        raise CamError("There is no material to clear at any level.")
    ctx.meta = {"levels": stats["levels"], "skipped_levels": stats["skipped_levels"], "chains": stats["chains"], "optimal_load": ae, "engagement_target_deg": round(math.degrees(phi_t), 2), "engagement_max_deg": round(math.degrees(stats["engagement_max"]), 2), "stock_to_leave": stl, "cell": round(cs, 4)}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="adaptive3d", label="3D adaptive roughing", group="3d", generate=generate, tool_kinds=("flat", "bull"), geometry=("model",), needs_model=True,
    description="Rough a stock down to the model level by level with a constant-engagement path; each level clears the stock outline minus the model silhouette and keeps the tool out of the model found by the push cutter.",
    fields=[
        Field("optimal_load", "number", None, "Optimal load (radial engagement)", 0.001, 500.0, "mm", group="Passes", nullable=True),
        Field("stepdown", "number", None, "Maximum stepdown", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stock_to_leave", "number", 0.3, "Stock to leave", 0.0, 50.0, "mm", group="Passes"),
        Field("stock_to_leave_floor", "number", 0.0, "Extra stock to leave on the floor", 0.0, 50.0, "mm", group="Passes"),
        Field("sampling", "number", None, "Fibre spacing", 0.01, 20.0, "mm", group="Accuracy", nullable=True),
        Field("tolerance", "number", 0.02, "Path smoothing tolerance", 0.001, 1.0, "mm", group="Accuracy"),
        Field("entry", "choice", "helix", "Entry", choices=("helix", "plunge"), group="Linking"),
        Field("ramp_angle", "number", 3.0, "Ramp angle", 0.1, 45.0, "deg", group="Linking"),
        Field("helix_diameter", "number", None, "Helix diameter", 0.1, 1000.0, "mm", group="Linking", nullable=True),
    ],
))
