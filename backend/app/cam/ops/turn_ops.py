import json

from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.registry import Field, OpType, register
from app.turning import emit, passes
from app.turning import profile as PF
from app.turning.profile import TurnError

_ = emit

INSERT_DEFAULTS = {"nose_radius": 0.4, "tip_angle": 80.0, "lead_angle": 95.0, "insert_size": 8.0, "width": 0.0}


def lathe_tool(ctx) -> dict:
    t = ctx.tool
    ins = dict(INSERT_DEFAULTS)
    ins.update({k: v for k, v in (t.rec.get("insert") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
    width = ins["width"] or t.diameter
    return {"number": t.number, "name": t.name, "nose_radius": float(ins["nose_radius"]), "tip_angle": float(ins["tip_angle"]), "lead_angle": float(ins["lead_angle"]), "insert_size": float(ins["insert_size"]), "width": float(width)}


def need_cut_data(p):
    for k, label in (("vc", "a cutting speed"), ("fpr", "a feed per revolution"), ("max_rpm", "a maximum spindle speed")):
        if p.get(k) is None or p[k] <= 0:
            raise CamError("Give %s." % label)


def stock_of(ctx, p):
    d = p.get("stock_diameter") or 0.0
    if d <= 0:
        st = ctx.setup.get("stock") or {}
        d = float(st.get("diameter") or 0.0)
    if d <= 0:
        raise CamError("Give the stock diameter, here or on a cylinder stock of the setup.")
    return d / 2.0


def profile_of(ctx, p):
    src = p["profile_source"]
    if src == "model":
        try:
            prof = PF.from_triangles(ctx.triangles())
        except TurnError as err:
            raise CamError(str(err))
        return prof
    text = (p.get("profile") or "").strip()
    if not text:
        raise CamError("Give the profile as JSON, or take it from the model.")
    if len(text) > 200000:
        raise CamError("The profile text is too large.")
    try:
        spec = json.loads(text)
    except ValueError:
        raise CamError("The profile is not valid JSON.")
    try:
        return PF.build(spec)
    except (TurnError, KeyError, TypeError, ValueError) as err:
        raise CamError("The profile is not usable: %s" % err)


def wrap(ctx, res, label):
    for w in res.get("warnings", []):
        ctx.warn(w)
    meta = {"lathe": True, "feed_unit": "mm/rev", "stats": {k: v for k, v in res["stats"].items() if k != "gouge"}}
    if res["stats"].get("gouge") is not None:
        meta["gouge"] = res["stats"]["gouge"]
    return T.Toolpath(res["moves"], meta)


COMMON = [
    Field("clear_x", "number", 2.0, "Clearance beyond the stock radius", min=0.1, max=100, unit="mm", group="Heights"),
    Field("clear_z", "number", 2.0, "Clearance in front of the stock", min=0.1, max=100, unit="mm", group="Heights"),
    Field("retract", "number", 0.5, "Retract distance", min=0.05, max=20, unit="mm", group="Heights"),
    Field("vc", "number", None, "Cutting speed", min=1, max=2000, unit="m/min", group="Feeds"),
    Field("fpr", "number", None, "Feed per revolution", min=0.005, max=5, unit="mm/rev", group="Feeds"),
    Field("max_rpm", "number", None, "Maximum spindle speed", min=10, max=30000, unit="rpm", group="Feeds"),
]

PROFILE_FIELDS = [
    Field("profile_source", "choice", "json", "Profile from", choices=("json", "model"), group="Profile"),
    Field("profile", "text", "", "Profile (JSON: units, pts of z and d, fillet or chamfer)", group="Profile"),
]


def gen_rough(ctx):
    p = ctx.p
    need_cut_data(p)
    tool = lathe_tool(ctx)
    prof = profile_of(ctx, p)
    try:
        res = passes.rough(prof, p, tool, stock_of(ctx, p), p["z_front"], ctx.check)
    except TurnError as err:
        raise CamError(str(err))
    return wrap(ctx, res, "rough")


def gen_finish(ctx):
    p = ctx.p
    need_cut_data(p)
    tool = lathe_tool(ctx)
    prof = profile_of(ctx, p)
    try:
        res = passes.finish(prof, p, tool, stock_of(ctx, p), p["z_front"])
    except TurnError as err:
        raise CamError(str(err))
    return wrap(ctx, res, "finish")


def gen_face(ctx):
    p = ctx.p
    need_cut_data(p)
    tool = lathe_tool(ctx)
    try:
        res = passes.face(p, tool, stock_of(ctx, p), p["z_front"], p["z_target"])
    except TurnError as err:
        raise CamError(str(err))
    return wrap(ctx, res, "face")


def gen_groove(ctx):
    p = ctx.p
    need_cut_data(p)
    if p["z_start"] is None or p["width"] is None or p["bottom_diameter"] is None:
        raise CamError("Give the groove front wall, width and bottom diameter.")
    tool = lathe_tool(ctx)
    try:
        res = passes.groove(p, tool, stock_of(ctx, p))
    except TurnError as err:
        raise CamError(str(err))
    return wrap(ctx, res, "groove")


def gen_thread(ctx):
    p = ctx.p
    for k, label in (("vc", "a cutting speed"), ("max_rpm", "a maximum spindle speed")):
        if p.get(k) is None or p[k] <= 0:
            raise CamError("Give %s." % label)
    if p["major_diameter"] is None or p["pitch"] is None or p["z_start"] is None or p["z_end"] is None:
        raise CamError("Give the major diameter, pitch, start and end of the thread.")
    tool = lathe_tool(ctx)
    q = dict(p)
    q["depth"] = p["depth"] or None
    q["first_depth"] = p["first_depth"] or None
    q["lead_in"] = p["lead_in"] or None
    try:
        res = passes.thread(q, tool, p["major_diameter"] / 2.0)
    except TurnError as err:
        raise CamError(str(err))
    return wrap(ctx, res, "thread")


def gen_partoff(ctx):
    p = ctx.p
    need_cut_data(p)
    if p["z"] is None:
        raise CamError("Give the z of the back face of the part.")
    tool = lathe_tool(ctx)
    try:
        res = passes.partoff(p, tool, stock_of(ctx, p))
    except TurnError as err:
        raise CamError(str(err))
    return wrap(ctx, res, "partoff")


STOCK = [Field("stock_diameter", "number", 0.0, "Stock diameter (0 takes the setup stock)", min=0, max=2000, unit="mm", group="Stock"), Field("z_front", "number", 0.5, "Stock front, above the finished face", min=0, max=100, unit="mm", group="Stock")]

register(OpType(kind="turn_face", label="Face turning", group="turning", generate=gen_face, tool_kinds=("insert",), needs_feeds=False, description="Facing passes across the end of the stock, from the outside to the axis.", fields=STOCK + [Field("z_target", "number", 0.0, "Finished face z", min=-1000, max=1000, unit="mm", group="Cut"), Field("doc", "number", 1.0, "Depth of cut", min=0.01, max=20, unit="mm", group="Cut"), Field("allowance", "number", 0.0, "Stock to leave", min=0, max=5, unit="mm", group="Cut"), Field("overtravel", "number", 0.0, "Travel past the axis", min=0, max=5, unit="mm", group="Cut")] + COMMON))
register(OpType(kind="turn_rough", label="Rough turning", group="turning", generate=gen_rough, tool_kinds=("insert",), needs_feeds=False, description="Layered passes along the axis toward the profile, leaving an allowance, with a contour pass that follows the profile offset by the nose radius.", fields=STOCK + PROFILE_FIELDS + [Field("doc", "number", 2.0, "Depth of cut", min=0.01, max=20, unit="mm", group="Cut"), Field("allowance", "number", 0.3, "Stock to leave", min=0, max=5, unit="mm", group="Cut"), Field("contour_pass", "bool", True, "Follow the profile after the passes", group="Cut")] + COMMON))
register(OpType(kind="turn_finish", label="Finish turning", group="turning", generate=gen_finish, tool_kinds=("insert",), needs_feeds=False, description="One pass along the profile with nose radius compensation and a check of the insert shape against the profile.", fields=STOCK + PROFILE_FIELDS + [Field("allowance", "number", 0.0, "Stock to leave", min=0, max=5, unit="mm", group="Cut"), Field("check_insert", "bool", True, "Check the insert shape for gouging", group="Cut")] + COMMON))
register(OpType(kind="turn_groove", label="Groove turning", group="turning", generate=gen_groove, tool_kinds=("groove", "insert"), needs_feeds=False, description="A square groove by plunges across its width with pecks, then a pass along its floor and walls.", fields=[Field("stock_diameter", "number", 0.0, "Stock diameter (0 takes the setup stock)", min=0, max=2000, unit="mm", group="Stock"), Field("z_start", "number", None, "Groove front wall z", min=-10000, max=10000, unit="mm", group="Groove"), Field("width", "number", None, "Groove width", min=0.1, max=500, unit="mm", group="Groove"), Field("bottom_diameter", "number", None, "Groove bottom diameter", min=0, max=2000, unit="mm", group="Groove"), Field("top_diameter", "number", 0.0, "Surface diameter (0 takes the stock)", min=0, max=2000, unit="mm", group="Groove"), Field("allowance", "number", 0.1, "Stock to leave on floor and walls", min=0, max=2, unit="mm", group="Cut"), Field("overlap", "number", 0.2, "Overlap of plunges", min=0, max=0.9, group="Cut"), Field("peck", "number", 2.0, "Peck depth", min=0.1, max=20, unit="mm", group="Cut")] + COMMON))
register(OpType(kind="turn_thread", label="Thread turning", group="turning", generate=gen_thread, tool_kinds=("thread", "insert"), needs_feeds=False, description="An external thread as spindle-synchronised passes with falling depth (equal chip area), radial or flank infeed and spring passes.", fields=[Field("major_diameter", "number", None, "Major diameter", min=1, max=1000, unit="mm", group="Thread"), Field("pitch", "number", None, "Pitch", min=0.1, max=20, unit="mm", group="Thread"), Field("z_start", "number", None, "Thread start z", min=-10000, max=10000, unit="mm", group="Thread"), Field("z_end", "number", None, "Thread end z", min=-10000, max=10000, unit="mm", group="Thread"), Field("depth", "number", 0.0, "Thread depth (0 is 0.6134 times the pitch)", min=0, max=20, unit="mm", group="Thread"), Field("passes", "int", 6, "Passes", min=1, max=40, group="Cut"), Field("first_depth", "number", 0.0, "First pass depth (0 is automatic)", min=0, max=5, unit="mm", group="Cut"), Field("infeed", "choice", "radial", "Infeed", choices=("radial", "flank"), group="Cut"), Field("spring_passes", "int", 1, "Spring passes at full depth", min=0, max=5, group="Cut"), Field("lead_in", "number", 0.0, "Run-in before the start (0 is three pitches)", min=0, max=100, unit="mm", group="Cut"), Field("clear_x", "number", 2.0, "Clearance beyond the major diameter", min=0.1, max=100, unit="mm", group="Heights"), Field("clear_z", "number", 2.0, "Clearance in front", min=0.1, max=100, unit="mm", group="Heights"), Field("retract", "number", 0.5, "Retract distance", min=0.05, max=20, unit="mm", group="Heights"), Field("vc", "number", None, "Cutting speed", min=1, max=2000, unit="m/min", group="Feeds"), Field("max_rpm", "number", None, "Spindle speed limit", min=10, max=30000, unit="rpm", group="Feeds")]))
register(OpType(kind="turn_partoff", label="Part off", group="turning", generate=gen_partoff, tool_kinds=("groove", "insert"), needs_feeds=False, description="A plunge to the axis with pecks and a slower feed near the centre.", fields=[Field("stock_diameter", "number", 0.0, "Stock diameter (0 takes the setup stock)", min=0, max=2000, unit="mm", group="Stock"), Field("z", "number", None, "Back face z of the part", min=-10000, max=10000, unit="mm", group="Cut"), Field("to_diameter", "number", 0.0, "Plunge down to this diameter", min=0, max=2000, unit="mm", group="Cut"), Field("peck", "number", 5.0, "Peck depth", min=0.1, max=100, unit="mm", group="Cut"), Field("slow_radius", "number", 3.0, "Slow feed below this radius", min=0, max=100, unit="mm", group="Cut"), Field("slow_factor", "number", 0.5, "Feed factor near the centre", min=0.05, max=1, group="Cut"), Field("stop_after", "bool", False, "Optional stop after the cut", group="Cut")] + COMMON))
