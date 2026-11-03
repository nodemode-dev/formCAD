import math

import numpy as np

from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.registry import Field, OpType, register
from app.cam3d import opkit, paths3d


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    surf = opkit.model_surface(ctx)
    cu = opkit.cutter_of(ctx)
    stl = p["stock_to_leave"]
    if cu.kind not in ("ball", "bull"):
        ctx.warn("Constant scallop is meant for ball and bull cutters; the stepover was taken from the tool radius.")
    step = p["stepover"]
    if step is None:
        step = paths3d.scallop_step(max(cu.r, t.radius if cu.kind == "flat" else cu.r, 1e-6), p["scallop"])
    if step > t.diameter * 0.99:
        raise CamError("Stepover must be less than the tool diameter.")
    bottom = opkit.clamp_bottom(ctx, surf)
    bounds = opkit.model_bounds(surf, cu.R + stl + 2.0 * step)
    grid = p["grid"] if p["grid"] is not None else max(step / 3.0, 0.05)
    f = ctx.feed_for(step, 0.0)
    rings = opkit.region_rings(ctx)
    mask = None
    if rings:
        from app.cam import geom

        def mask(X, Y):
            out = np.zeros(X.shape, dtype=bool)
            flat = out.reshape(-1)
            xs, ys = X.reshape(-1), Y.reshape(-1)
            for k in range(len(xs)):
                flat[k] = geom.inside((xs[k], ys[k]), rings)
            return out

    cap = ctx.limit["grid_cells"]
    passes, meta = paths3d.scallop(surf, cu, bounds, step, grid, p["tolerance"], stl, bottom, mask, ctx.check, ctx.progress, p["direction"] == "climb", cap)
    if not passes:
        raise CamError("No constant-scallop passes were found; check the tool and region.")
    cur = None
    order = opkit.order_nearest(passes, lambda it, end=False: it[0][-1 if end else 0], cur)
    arrs = [q for q, _ in order]
    moves = opkit.emit_passes(ctx, f, arrs, surf, cu, stl, bottom, 2.0 * step + t.diameter, max(min(t.radius * 0.5, 0.5), 0.05))
    ctx.meta = {"passes": len(passes), "stepover": round(step, 4), "grid": round(grid, 4), "scallop_target": p["scallop"], "distance_max": round(meta["max_distance"], 3), "method": "geodesic grid distance"}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="scallop", label="Constant scallop finishing", group="3d", generate=generate, tool_kinds=("ball", "bull"), geometry=("model", "polygons", "rect", "entities", "section"), needs_model=True,
    description="Finish with passes kept a constant distance apart along the surface, found as contours of the surface distance from the edge of the machinable area, so steep and shallow parts get the same scallop.",
    fields=[
        Field("stepover", "number", None, "Surface stepover", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("scallop", "number", 0.01, "Scallop height (used when no stepover)", 0.0005, 5.0, "mm", group="Passes"),
        Field("grid", "number", None, "Distance grid cell", 0.01, 20.0, "mm", group="Accuracy", nullable=True),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Passes"),
        Field("tolerance", "number", 0.01, "Path tolerance", 0.0005, 1.0, "mm", group="Accuracy"),
        Field("stock_to_leave", "number", 0.0, "Stock to leave", 0.0, 50.0, "mm", group="Accuracy"),
    ],
))
