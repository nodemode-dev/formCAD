import math

from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.registry import Field, OpType, register
from app.turning import emit

_ = emit

MAX_HOLES = 360


def pos(r, a, z, deg):
    return [round(r * math.cos(math.radians(a)), 4), round(r * math.sin(math.radians(a)), 4), round(z, 4), {"live": {"c": round(a, 4)}, "k": deg}]


def common_checks(p):
    if p["rpm"] is None or p["rpm"] <= 0 or p["feed"] is None or p["feed"] <= 0:
        raise CamError("Give the spindle speed and the feed.")
    if p["count"] < 1 or p["count"] > MAX_HOLES:
        raise CamError("The hole count is 1 to %d." % MAX_HOLES)


def start(ctx, p):
    t = ctx.tool
    return [["comment", "%s T%d %s" % (ctx.op.get("label") or ctx.op["type"], t.number, t.name)], T.tool_change(t.number, p["rpm"], t.name), T.spindle(p["rpm"], "cw")]


def gen_axial(ctx):
    p = ctx.p
    common_checks(p)
    if p["pcd"] is None or p["depth"] is None or p["z_face"] is None:
        raise CamError("Give the face z, the bolt circle diameter and the depth.")
    moves = start(ctx, p)
    r = p["pcd"] / 2.0
    top = p["z_face"]
    bottom = top - p["depth"]
    for i in range(int(p["count"])):
        ctx.check()
        a = p["start_angle"] + 360.0 * i / p["count"]
        x, y, _z, o = pos(r, a, top + p["clearance"], "approach")
        moves.append(["rapid", x, y, top + p["clearance"], o])
        z = top
        step = p["peck"] if p["peck"] > 0 else p["depth"]
        moves.append(["rapid", x, y, top + p["retract"], dict(o)])
        while z > bottom + 1e-9:
            z = max(z - step, bottom)
            moves.append(["feed", x, y, round(z, 4), p["feed"], {"live": {"c": round(a, 4)}, "k": "plunge"}])
            if z > bottom + 1e-9:
                moves.append(["rapid", x, y, top + p["retract"], {"live": {"c": round(a, 4)}, "k": "retract"}])
                moves.append(["rapid", x, y, round(z + 0.5, 4), {"live": {"c": round(a, 4)}, "k": "approach"}])
        moves.append(["rapid", x, y, top + p["clearance"], {"live": {"c": round(a, 4)}, "k": "retract"}])
    moves.append(["spindle", 0, "off"])
    return T.Toolpath(moves, {"live": True, "holes": int(p["count"])})


def gen_radial(ctx):
    p = ctx.p
    common_checks(p)
    if p["radius"] is None or p["depth"] is None or p["z"] is None:
        raise CamError("Give the axial position, the surface radius and the depth.")
    moves = start(ctx, p)
    rs = p["radius"]
    bottom = rs - p["depth"]
    if bottom < 0:
        raise CamError("The hole is deeper than the radius.")
    for i in range(int(p["count"])):
        ctx.check()
        a = p["start_angle"] + 360.0 * i / p["count"]
        o = {"live": {"c": round(a, 4)}}
        rad = lambda r_: [round(r_ * math.cos(math.radians(a)), 4), round(r_ * math.sin(math.radians(a)), 4)]
        x, y = rad(rs + p["clearance"])
        moves.append(["rapid", x, y, p["z"], dict(o, k="approach")])
        r = rs
        step = p["peck"] if p["peck"] > 0 else p["depth"]
        x, y = rad(rs + p["retract"])
        moves.append(["rapid", x, y, p["z"], dict(o, k="approach")])
        while r > bottom + 1e-9:
            r = max(r - step, bottom)
            x, y = rad(r)
            moves.append(["feed", x, y, p["z"], p["feed"], dict(o, k="plunge")])
            if r > bottom + 1e-9:
                x, y = rad(rs + p["retract"])
                moves.append(["rapid", x, y, p["z"], dict(o, k="retract")])
                x, y = rad(r + 0.5)
                moves.append(["rapid", x, y, p["z"], dict(o, k="approach")])
        x, y = rad(rs + p["clearance"])
        moves.append(["rapid", x, y, p["z"], dict(o, k="retract")])
    moves.append(["spindle", 0, "off"])
    return T.Toolpath(moves, {"live": True, "holes": int(p["count"])})


SHARED = [Field("count", "int", 4, "Holes", min=1, max=MAX_HOLES, group="Holes"), Field("start_angle", "number", 0.0, "First hole angle", min=-360, max=360, unit="deg", group="Holes"), Field("depth", "number", None, "Depth", min=0.01, max=1000, unit="mm", group="Cut"), Field("peck", "number", 0.0, "Peck depth (0 drills straight)", min=0, max=100, unit="mm", group="Cut"), Field("clearance", "number", 5.0, "Clearance", min=0.5, max=100, unit="mm", group="Heights"), Field("retract", "number", 1.0, "Retract", min=0.1, max=50, unit="mm", group="Heights"), Field("rpm", "number", None, "Spindle speed", min=1, max=60000, unit="rpm", group="Feeds"), Field("feed", "number", None, "Feed", min=1, max=20000, unit="mm/min", group="Feeds")]

register(OpType(kind="live_drill_axial", label="Live drill on the face", group="mill-turn", generate=gen_axial, tool_kinds=("drill",), needs_feeds=False, description="Axial holes on a bolt circle of the end face, the part indexed by the C axis.", fields=[Field("z_face", "number", None, "Face z", min=-10000, max=10000, unit="mm", group="Holes"), Field("pcd", "number", None, "Bolt circle diameter", min=0, max=2000, unit="mm", group="Holes")] + SHARED))
register(OpType(kind="live_drill_radial", label="Live drill across the part", group="mill-turn", generate=gen_radial, tool_kinds=("drill",), needs_feeds=False, description="Radial holes at one axial position, the part indexed by the C axis.", fields=[Field("z", "number", None, "Axial position z", min=-10000, max=10000, unit="mm", group="Holes"), Field("radius", "number", None, "Surface radius", min=0.1, max=1000, unit="mm", group="Holes")] + SHARED))
