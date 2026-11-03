from app.cam import geom
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common, pocket
from app.cam.registry import Field, OpType, register


def uncut_region(region_rings, r_prev: float, stl: float):
    opened = geom.offset(geom.offset(region_rings, -(r_prev + stl)), r_prev + stl)
    return geom.difference(region_rings, opened)


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    region = ctx.region()
    r_prev = p["previous_diameter"] / 2.0
    if r_prev <= t.radius + 1e-9:
        raise CamError("The previous tool must be larger than this tool.")
    stl = p["stock_to_leave_xy"]
    unc = uncut_region(region.rings, r_prev, stl)
    unc = [r for r in unc if abs(geom.area(r)) > 1e-4]
    if not unc:
        raise CamError("There is no material left by the previous tool.")
    cen = geom.offset(region.rings, -(t.radius + stl))
    if not cen:
        raise CamError("The tool is too large for this region.")
    unc = geom.intersection(unc, geom.offset(cen, t.radius))
    unc = [r for r in unc if abs(geom.area(r)) > 1e-4]
    if not unc:
        raise CamError("The tool cannot reach the material left by the previous tool.")
    near = geom.offset(unc, t.radius)
    loc = geom.intersection(near, cen)
    if not loc:
        raise CamError("The tool cannot reach the material left by the previous tool.")
    stepover = pocket.stepover_of(ctx)
    layers = pocket.build_layers(ctx, loc, stepover)
    bottom = ctx.bottom() + p["stock_to_leave_z"]
    zs = common.levels(ctx.h.top, bottom, pocket.stepdown_of(ctx))
    f = ctx.feed_for(stepover, 0.0)
    moves = pocket.cut_pocket(ctx, loc, layers, zs, f, stepover, None)
    area = sum(geom.area(r) for r in unc if geom.is_ccw(r)) - sum(abs(geom.area(r)) for r in unc if not geom.is_ccw(r))
    ctx.meta = {"layers": len(layers), "levels": len(zs), "uncut_area": round(area, 3)}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="rest", label="Rest machining", group="2d", generate=generate, tool_kinds=pocket.CUTTERS, geometry=("polygons", "rect", "entities", "section", "removal"),
    description="Clear the corners and narrow places a larger previous tool could not reach.",
    fields=[
        Field("previous_diameter", "number", 10.0, "Previous tool diameter", 0.01, 1000.0, "mm", group="Rest"),
        Field("stepover", "number", None, "Stepover", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stepdown", "number", None, "Maximum stepdown", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stock_to_leave_xy", "number", 0.0, "Stock to leave on walls", 0.0, 50.0, "mm", group="Passes"),
        Field("stock_to_leave_z", "number", 0.0, "Stock to leave on floor", 0.0, 50.0, "mm", group="Passes"),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Passes"),
        Field("arc_tolerance", "number", 0.01, "Arc fitting tolerance (0 keeps line segments)", 0.0, 1.0, "mm", group="Passes"),
    ] + pocket.COMMON_ENTRY,
))
