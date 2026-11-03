import math

from app.cam import feeds as F
from app.cam import limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam.registry import Field, OpType, register


def nearest_order(holes, start=(0.0, 0.0)):
    left = list(holes)
    out = []
    cur = start
    while left:
        i = min(range(len(left)), key=lambda k: (left[k]["x"] - cur[0]) ** 2 + (left[k]["y"] - cur[1]) ** 2)
        h = left.pop(i)
        out.append(h)
        cur = (h["x"], h["y"])
    return out


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    h = ctx.h
    holes = ctx.points()
    tol = p["diameter_tolerance"]
    if tol is not None:
        holes = [q for q in holes if q.get("diameter") is None or abs(q["diameter"] - t.diameter) <= tol]
    if not holes:
        raise CamError("No holes match this tool.")
    limits.need(len(holes), "holes", "Holes")
    bottom = ctx.bottom()
    z_bot = bottom - (t.tip_length() if p["through"] else 0.0)
    r_plane = p["retract_plane"] if p["retract_plane"] is not None else h.feed
    if r_plane <= z_bot:
        raise CamError("The retract plane must be above the hole bottom.")
    if p["feed_per_rev"] is None:
        f = ctx.feed_for(0.0, 0.0)
    else:
        fin = ctx.op.get("feeds") or {}
        rpm = fin.get("rpm")
        if rpm is None:
            vc = fin.get("vc") or (t.cutting.get(fin.get("material") or "") or {}).get("vc")
            if not vc:
                raise CamError("Give a spindle speed or a cutting speed.")
            rpm = F.rpm_from_vc(vc, t.diameter)
        rpm = min(float(rpm), t.rpm_max) if t.rpm_max else float(rpm)
        vf = F.drill_feed(p["feed_per_rev"], rpm)
        f = {"rpm": rpm, "vf_cut": vf, "vf_plunge": vf, "vf_ramp": vf, "vc": F.vc_from_rpm(rpm, t.diameter), "fz": 0.0, "notes": [], "chip_thinning": 1.0, "material": ""}
    ordered = nearest_order(holes)
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    kind = p["cycle"]
    q = p["peck"] if kind in ("peck", "chip") else 0.0
    if kind in ("peck", "chip") and not q:
        raise CamError("A peck or chip-breaking cycle needs a peck depth.")
    dwell = p["dwell"] if kind == "dwell" else 0.0
    for i, hole in enumerate(ordered):
        ctx.check()
        if i == 0:
            pen.over(hole["x"], hole["y"], h.clearance)
        moves.append(["cycle", kind, hole["x"], hole["y"], z_bot, r_plane, q or 0.0, dwell, f["vf_cut"]])
        pen.pos = (hole["x"], hole["y"], r_plane)
        ctx.progress((i + 1) / len(ordered))
    pen.rapid(pen.pos[0], pen.pos[1], h.clearance, k="retract")
    ctx.meta = {"holes": len(ordered), "bottom": z_bot, "cycle": kind}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="drill", label="Drill", group="2d", generate=generate, tool_kinds=("drill", "flat", "ball", "chamfer", "engraver"), geometry=("points", "model_holes", "entities"),
    description="Drill holes with a canned cycle (drill, dwell, peck, chip-breaking), nearest-neighbour order.",
    fields=[
        Field("cycle", "choice", "drill", "Cycle", choices=("drill", "dwell", "peck", "chip"), group="Cycle"),
        Field("peck", "number", None, "Peck depth", 0.01, 500.0, "mm", group="Cycle", nullable=True),
        Field("dwell", "number", 0.0, "Dwell at the bottom", 0.0, 60.0, "s", group="Cycle"),
        Field("retract_plane", "number", None, "Retract plane", None, None, "mm", group="Cycle", nullable=True),
        Field("through", "bool", False, "Add the drill tip below the bottom", group="Cycle"),
        Field("feed_per_rev", "number", None, "Feed per revolution", 0.0001, 10.0, "mm", group="Cycle", nullable=True),
        Field("diameter_tolerance", "number", None, "Only holes within this diameter tolerance", 0.0, 100.0, "mm", group="Selection", nullable=True),
    ],
))
