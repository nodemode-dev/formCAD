import math

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
    step = p["stepover"]
    if step is None:
        if cu.kind in ("ball", "bull"):
            step = paths3d.scallop_step(max(cu.r, 1e-6), p["scallop"])
        else:
            step = 0.5 * t.diameter
    if step > t.diameter * 0.99:
        raise CamError("Stepover must be less than the tool diameter.")
    bottom = opkit.clamp_bottom(ctx, surf)
    bounds = opkit.model_bounds(surf, cu.R + stl + step)
    f = ctx.feed_for(step, 0.0)
    passes = paths3d.parallel(surf, cu, bounds, p["angle"], step, p["tolerance"], stl, bottom, opkit.region_rings(ctx), p["pattern"] == "zigzag", p["direction"] == "climb", ctx.check, ctx.progress)
    if not passes:
        raise CamError("The tool touches no model surface; check the region and the tool.")
    moves = opkit.emit_passes(ctx, f, passes, surf, cu, stl, bottom, 2.0 * step + t.diameter, max(min(t.radius * 0.5, 0.5), 0.05))
    ctx.meta = {"passes": len(passes), "stepover": round(step, 4), "tolerance": p["tolerance"], "angle": p["angle"], "stock_to_leave": stl}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="parallel", label="Parallel finishing", group="3d", generate=generate, tool_kinds=("ball", "bull", "flat"), geometry=("model", "polygons", "rect", "entities", "section"), needs_model=True,
    description="Finish a surface with straight passes at an angle, the tool resting on the model through a drop-cutter calculation, refined where the surface bends so the chord error stays within the tolerance.",
    fields=[
        Field("stepover", "number", None, "Stepover", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("scallop", "number", 0.01, "Scallop height (used when no stepover)", 0.0005, 5.0, "mm", group="Passes"),
        Field("angle", "number", 0.0, "Pass angle", -360.0, 360.0, "deg", group="Passes"),
        Field("pattern", "choice", "zigzag", "Pattern", choices=("zigzag", "one_way"), group="Passes"),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Passes"),
        Field("tolerance", "number", 0.01, "Chord tolerance", 0.0005, 1.0, "mm", group="Accuracy"),
        Field("stock_to_leave", "number", 0.0, "Stock to leave", 0.0, 50.0, "mm", group="Accuracy"),
    ],
))
