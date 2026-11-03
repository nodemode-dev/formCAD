import math

from app.cam import geom, limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam.registry import Field, OpType, register

CUTTERS = ("flat", "bull", "ball")

COMMON_ENTRY = [
    Field("entry", "choice", "helix", "Entry", choices=("helix", "ramp", "plunge"), group="Linking"),
    Field("ramp_angle", "number", 3.0, "Ramp angle", 0.1, 45.0, "deg", group="Linking"),
    Field("helix_diameter", "number", None, "Helix diameter", 0.1, 1000.0, "mm", group="Linking", nullable=True),
]


def stepover_of(ctx, key="stepover") -> float:
    s = ctx.p.get(key)
    d = ctx.tool.diameter
    s = 0.5 * d if s is None else float(s)
    if s > d * 0.99:
        raise CamError("Stepover must be less than the tool diameter.")
    return s


def stepdown_of(ctx) -> float:
    s = ctx.p.get("stepdown")
    return 0.5 * ctx.tool.diameter if s is None else float(s)


def build_layers(ctx, locus: list, stepover: float) -> list:
    layers = []
    cur = locus
    while cur:
        layers.append(cur)
        limits.need(len(layers), "passes", "Pocket rings")
        ctx.check()
        nxt = geom.offset(cur, -stepover)
        if not nxt:
            mid = geom.offset(cur, -stepover * 0.5)
            if mid and geom.vertex_count(mid) >= 3:
                layers.append(mid)
            break
        cur = nxt
    return layers


def link_ok(locus, a, b, limit) -> bool:
    return math.dist(a, b) <= limit and common.segment_inside(locus, a, b)


def descend(pen, a, h, z_from, li, f):
    pen.over(a[0], a[1], h.retract)
    if li == 0:
        if z_from < h.retract - 1e-9:
            pen.rapid(a[0], a[1], z_from, k="approach")
        return
    pen.rapid(a[0], a[1], z_from + 1.0, k="approach")
    pen.feed(a[0], a[1], z_from, f["vf_plunge"], "plunge")


def cut_pocket(ctx, locus: list, layers: list, zs: list, f: dict, stepover: float, wall: list | None):
    p = ctx.p
    h = ctx.h
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    climb = p["direction"] == "climb"
    ordered_layers = list(reversed(layers))
    total_rings = sum(len(l) for l in layers) * len(zs)
    limits.need(total_rings, "passes", "Pocket passes")
    done = 0
    link_max = max(stepover * 2.5, ctx.tool.diameter)
    for li, z in enumerate(zs):
        z_from = min(h.feed, h.top + 1.0) if li == 0 else zs[li - 1]
        first = True
        seq = []
        start = None
        for layer in ordered_layers:
            lr = [list(r if climb else geom.reverse(r)) for r in layer]
            if start is None:
                start = (sum(q[0] for q in lr[0]) / len(lr[0]), sum(q[1] for q in lr[0]) / len(lr[0]))
            ordered = common.order_rings(lr, seq[-1][0] if seq else start)
            seq.extend(ordered)
        for ring in seq:
            ctx.check()
            pts = common.ring_points(ring)
            a = pts[0]
            if first:
                if li == 0 or pen.pos is None:
                    pen.over(a[0], a[1], z_from)
                else:
                    last = pen.pos
                    if link_ok(locus, last[:2], a, 1e9):
                        pen.feed(a[0], a[1], last[2], f["vf_cut"], "link")
                    else:
                        descend(pen, a, h, z_from, li, f)
                common.entry_at(ctx, pen, pts, locus, z_from, z, f, p["entry"], p.get("helix_diameter") or 1.5 * ctx.tool.diameter, p["ramp_angle"])
                first = False
            else:
                last = pen.pos
                if link_ok(locus, last[:2], a, link_max):
                    pen.feed(a[0], a[1], z, f["vf_cut"], "link")
                else:
                    descend(pen, a, h, z_from, li, f)
                    common.entry_at(ctx, pen, pts, locus, z_from, z, f, p["entry"], p.get("helix_diameter") or 1.5 * ctx.tool.diameter, p["ramp_angle"])
            common.cut_polyline(pen, pts, z, f["vf_cut"], "cut", p["arc_tolerance"])
            done += 1
            ctx.progress(done / max(total_rings, 1))
        if wall:
            wr = common.order_rings([list(r if climb else geom.reverse(r)) for r in wall], pen.pos[:2])
            for ring in wr:
                pts = common.ring_points(ring)
                pen.feed(pts[0][0], pts[0][1], z, f["vf_cut"], "link")
                common.cut_polyline(pen, pts, z, f["vf_cut"], "cut", p["arc_tolerance"])
    pen.finish()
    return moves


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    region = ctx.region()
    stl = p["stock_to_leave_xy"]
    stepover = stepover_of(ctx)
    locus_region = region.offset(-(t.radius + stl))
    if locus_region.empty():
        raise CamError("The tool is too large for this region.")
    locus = locus_region.rings
    bottom = ctx.bottom() + p["stock_to_leave_z"]
    zs = common.levels(ctx.h.top, bottom, stepdown_of(ctx))
    layers = build_layers(ctx, locus, stepover)
    f = ctx.feed_for(stepover, 0.0)
    wall = None
    if p["finish_walls"] and stl > 0:
        w = region.offset(-t.radius)
        wall = w.rings if not w.empty() else None
    moves = cut_pocket(ctx, locus, layers, zs, f, stepover, wall)
    ctx.meta = {"layers": len(layers), "levels": len(zs), "stepover": stepover, "stepdown": (ctx.h.top - bottom) / len(zs)}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="pocket", label="Pocket", group="2d", generate=generate, tool_kinds=CUTTERS, geometry=("polygons", "rect", "entities", "section", "removal"),
    description="Clear an enclosed or open region by nested offsets, inside out, in even depth steps.",
    fields=[
        Field("stepover", "number", None, "Stepover", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stepdown", "number", None, "Maximum stepdown", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stock_to_leave_xy", "number", 0.0, "Stock to leave on walls", 0.0, 50.0, "mm", group="Passes"),
        Field("stock_to_leave_z", "number", 0.0, "Stock to leave on floor", 0.0, 50.0, "mm", group="Passes"),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Passes"),
        Field("finish_walls", "bool", False, "Finish walls at each depth", group="Passes"),
        Field("arc_tolerance", "number", 0.01, "Arc fitting tolerance (0 keeps line segments)", 0.0, 1.0, "mm", group="Passes"),
    ] + COMMON_ENTRY,
))
