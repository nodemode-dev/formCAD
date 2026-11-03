from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam.registry import Field, OpType, register
from app.cam3d import multiaxis, opkit


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    cu = opkit.cutter_of(ctx)
    if cu.kind not in ("flat", "bull"):
        raise CamError("Swarf cutting needs a flat or bull end mill; the flank of the tool does the cutting.")
    rails = multiaxis.rails_of(ctx.op.get("geometry"))
    machine = multiaxis.machine_of(p["machine"])
    f = ctx.feed_for(0.0, 0.0)
    flute = t.flute_length or 1e6
    passes = []
    n = p["passes"]
    worst = 0.0
    for i in range(n):
        stl = p["stock_to_leave"] + (n - 1 - i) * p["pass_step"]
        (tips, axes, lat), ln = multiaxis.swarf_pass(rails, cu.R, stl, p["side"], p["step"], p["max_angle_step"], flute, ctx.warn, p["protect_floor"])
        worst = max(worst, ln)
        passes.append((tips, axes, lat))
    moves = multiaxis.emit(ctx, f, machine, passes, p["retract"], p["approach"])
    ctx.meta = {"passes": n, "samples": sum(len(q[0]) for q in passes), "ruling_max": round(worst, 3), "machine": p["machine"], "side": p["side"], "stock_to_leave": p["stock_to_leave"]}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="swarf", label="Swarf cutting", group="5axis", generate=generate, tool_kinds=("flat", "bull"), geometry=("ruled",),
    description="Machine a ruled wall with the side of the tool: the tool axis follows the ruling lines between two rails and the flank rests on the surface, the rotary axes solved on the machine model with branch and limit checks.",
    fields=[
        Field("machine", "text", "mill5_table_table", "Machine model", group="Machine"),
        Field("side", "choice", "positive", "Tool side", choices=("positive", "negative", "up", "down"), group="Surface"),
        Field("step", "number", 1.0, "Sample spacing", 0.05, 100.0, "mm", group="Accuracy"),
        Field("max_angle_step", "number", 2.0, "Largest rotary step", 0.1, 20.0, "deg", group="Accuracy"),
        Field("stock_to_leave", "number", 0.0, "Stock to leave", 0.0, 50.0, "mm", group="Passes"),
        Field("protect_floor", "bool", True, "Lift the tool so its tilted end stays above the lower rail", group="Surface"),
        Field("passes", "int", 1, "Number of passes", 1, 20, "", group="Passes"),
        Field("pass_step", "number", 0.2, "Offset between passes", 0.0, 20.0, "mm", group="Passes"),
        Field("retract", "number", 30.0, "Retract along the tool axis", 1.0, 1000.0, "mm", group="Linking"),
        Field("approach", "number", 3.0, "Approach distance", 0.5, 100.0, "mm", group="Linking"),
    ],
))
