import math

import numpy as np

from app.cam import geom, limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam.registry import Field, OpType, register


def rot(rings, ang):
    c, s = math.cos(ang), math.sin(ang)
    return [[(x * c - y * s, x * s + y * c) for x, y in r] for r in rings]


def lines_for(region_rings, step: float, angle_deg: float):
    ang = math.radians(angle_deg)
    rr = rot(region_rings, -ang)
    x0, y0, x1, y1 = geom.bounds(rr)
    inset = min(0.002, (y1 - y0) / 4.0)
    y0 += inset
    y1 -= inset
    n = max(1, int(math.ceil((y1 - y0) / step - 1e-9)))
    limits.need(n + 1, "passes", "Facing passes")
    ys = [y0 + (y1 - y0) * i / n for i in range(n + 1)]
    pad = 1.0
    raw = [[(x0 - pad, y), (x1 + pad, y)] for y in ys]
    clipped = geom.clip_open_lines(raw, rr)
    return ang, clipped


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    h = ctx.h
    g = ctx.op.get("geometry") or ctx.default_geometry
    region = ctx.region()
    over = p["overhang"]
    if over is None:
        over = t.radius * 1.1 if g.get("kind") == "stock" else 0.0
    cx = region.offset(over - t.radius)
    if cx.empty():
        raise CamError("The tool is too large for the facing region.")
    step = p["stepover"] if p["stepover"] is not None else 0.7 * t.diameter
    if step > t.diameter * 0.99:
        raise CamError("Stepover must be less than the tool diameter.")
    bottom = h.bottom if h.bottom is not None else h.top - p["depth"]
    zs = common.levels(h.top, bottom, p["stepdown"] if p["stepdown"] is not None else p["depth"])
    f = ctx.feed_for(step, 0.0)
    ang, segs = lines_for(cx.rings, step, p["angle"])
    if not segs:
        raise CamError("No facing passes fit the region.")
    segs = sorted(segs, key=lambda s: (round(s[0][1], 6), s[0][0]))
    c, s_ = math.cos(ang), math.sin(ang)
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    zigzag = p["pattern"] == "zigzag"
    flip = p["direction"] == "climb"
    for li, z in enumerate(zs):
        row_y = None
        k = -1
        z_from = h.feed
        for seg in segs:
            ctx.check()
            a, b = seg[0], seg[-1]
            if row_y is None or abs(a[1] - row_y) > 1e-6:
                row_y = a[1]
                k += 1
            lr = (a[0] > b[0])
            want_rev = flip if not zigzag else (flip != (k % 2 == 1))
            if want_rev != lr:
                a, b = b, a
            pa = (a[0] * c - a[1] * s_, a[0] * s_ + a[1] * c)
            pb = (b[0] * c - b[1] * s_, b[0] * s_ + b[1] * c)
            last = pen.pos
            if last is not None and abs(last[2] - z) < 1e-9 and zigzag and common.segment_inside(cx.rings, last[:2], pa, 0.5) and math.dist(last[:2], pa) < 3.0 * step + t.diameter:
                pen.feed(pa[0], pa[1], z, f["vf_cut"], "link")
            else:
                pen.over(pa[0], pa[1], h.retract)
                pen.rapid(pa[0], pa[1], max(z_from, z + 0.0) if li == 0 else zs[li - 1] + 0.5, k="approach")
                pen.feed(pa[0], pa[1], z, f["vf_plunge"], "plunge")
            pen.feed(pb[0], pb[1], z, f["vf_cut"], "cut")
        ctx.progress((li + 1) / len(zs))
    pen.finish()
    ctx.meta = {"passes": len(segs), "levels": len(zs), "stepover": step, "bottom": bottom}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="face", label="Face", group="2d", generate=generate, tool_kinds=("flat", "bull"), geometry=("stock", "polygons", "rect", "entities", "section"), default_geometry={"kind": "stock"},
    description="Machine the top of the stock flat with parallel passes that run off the edge of the region.",
    fields=[
        Field("stepover", "number", None, "Stepover", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("depth", "number", 0.5, "Depth below the top", 0.001, 100.0, "mm", group="Passes"),
        Field("stepdown", "number", None, "Maximum stepdown", 0.001, 100.0, "mm", group="Passes", nullable=True),
        Field("angle", "number", 0.0, "Pass angle", -360.0, 360.0, "deg", group="Passes"),
        Field("pattern", "choice", "zigzag", "Pattern", choices=("zigzag", "one_way"), group="Passes"),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Passes"),
        Field("overhang", "number", None, "Overhang past the edge", 0.0, 500.0, "mm", group="Passes", nullable=True),
    ],
))
