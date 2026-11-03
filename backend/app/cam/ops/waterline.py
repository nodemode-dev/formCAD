import math

import numpy as np

from app.cam import limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam.registry import Field, OpType, register
from app.cam3d import opkit, paths3d


def levels_of(top, bottom, step):
    n = max(1, int(math.ceil((top - bottom) / max(step, 1e-3) - 1e-9)))
    limits.need(n, "passes", "Depth levels")
    return [top - (top - bottom) * (i + 1) / n for i in range(n)]


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    h = ctx.h
    surf = opkit.model_surface(ctx)
    cu = opkit.cutter_of(ctx)
    stl = p["stock_to_leave"]
    top = min(h.top, float(surf.bmax[2])) if p["start_at_model_top"] else h.top
    bottom = opkit.clamp_bottom(ctx, surf)
    if top - bottom <= 1e-6:
        raise CamError("The bottom must be below the top of the cut.")
    zs = levels_of(top - p["first_offset"], bottom, p["stepdown"])
    grid = p["sampling"] if p["sampling"] is not None else max(min(t.radius * 0.25, 1.0), 0.05)
    bounds = opkit.model_bounds(surf, cu.R + stl + 3.0 * grid)
    nx = (bounds[2] - bounds[0]) / grid
    ny = (bounds[3] - bounds[1]) / grid
    limits.need(int(nx * ny), "grid_cells", "Waterline grid")
    f = ctx.feed_for(0.0, p["stepdown"])
    res = paths3d.waterline(surf, cu, zs, bounds, grid, p["tolerance"], stl, ctx.check, ctx.progress, p["direction"] == "climb")
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    count = 0
    z_prev = None
    for k, (z, loops) in enumerate(res):
        z_from = zs[k - 1] if k > 0 else min(z + p["stepdown"], max(h.top, z))
        todo = [(q, c) for q, c in loops if c and len(q) >= 3]
        cur = pen.pos[:2] if pen.pos else None
        order = opkit.order_nearest(todo, lambda it, end=False: it[0][-1 if end else 0], cur)
        for pts, closed in order:
            ctx.check()
            xy = [(float(a), float(b)) for a, b in pts[:, :2]]
            pen.over(xy[0][0], xy[0][1], max(h.retract, z_from + 1.0))
            if abs(z_from - z) < 1e-6 or p["entry"] == "plunge":
                pen.feed(xy[0][0], xy[0][1], z, f["vf_plunge"], "plunge")
                for q in xy[1:]:
                    pen.feed(q[0], q[1], z, f["vf_cut"], "cut")
            else:
                pen.feed(xy[0][0], xy[0][1], z_from, f["vf_plunge"], "plunge")
                common.ramp_along(pen, xy, z_from, z, f["vf_ramp"], f["vf_cut"], p["ramp_angle"])
            count += 1
    pen.finish()
    if count == 0:
        raise CamError("No waterline loops were found; check the levels and the model.")
    ctx.meta = {"levels": len(zs), "loops": count, "grid": round(grid, 4), "stepdown": p["stepdown"], "stock_to_leave": stl}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="waterline", label="Waterline finishing", group="3d", generate=generate, tool_kinds=("ball", "bull", "flat"), geometry=("model",), needs_model=True,
    description="Machine the model in constant-height contours found by pushing the tool along fibres into the model at each level, best on steep walls.",
    fields=[
        Field("stepdown", "number", 1.0, "Level spacing", 0.001, 500.0, "mm", group="Levels"),
        Field("first_offset", "number", 0.0, "First level below the top", 0.0, 500.0, "mm", group="Levels"),
        Field("start_at_model_top", "bool", True, "Start at the model top", group="Levels"),
        Field("sampling", "number", None, "Fibre spacing", 0.01, 20.0, "mm", group="Accuracy", nullable=True),
        Field("tolerance", "number", 0.01, "Path tolerance", 0.0005, 1.0, "mm", group="Accuracy"),
        Field("stock_to_leave", "number", 0.0, "Stock to leave", 0.0, 50.0, "mm", group="Accuracy"),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Passes"),
        Field("entry", "choice", "ramp", "Entry", choices=("ramp", "plunge"), group="Linking"),
        Field("ramp_angle", "number", 5.0, "Ramp angle", 0.1, 45.0, "deg", group="Linking"),
    ],
))
