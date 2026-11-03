from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.registry import Field, OpType, register
from app.cam3d import multiaxis, opkit


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    cu = opkit.cutter_of(ctx)
    if cu.kind != "ball":
        raise CamError("Flowline finishing is written for a ball cutter.")
    rails = multiaxis.rails_of(ctx.op.get("geometry"))
    machine = multiaxis.machine_of(p["machine"])
    f = ctx.feed_for(0.0, 0.0)
    passes, ds = multiaxis.flowline_passes(rails, cu.R, p["stock_to_leave"], p["side"], p["scallop"], p["lead"], p["tilt"], p["step"], p["max_angle_step"], ctx.warn, p["stepover"])
    moves = multiaxis.emit(ctx, f, machine, passes, p["retract"], p["approach"])
    ctx.meta = {"passes": len(passes), "samples": sum(len(a) for a, _ in passes), "stepover": round(ds, 4), "machine": p["machine"], "lead": p["lead"], "tilt": p["tilt"], "stock_to_leave": p["stock_to_leave"]}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="flowline", label="Flowline finishing", group="5axis", generate=generate, tool_kinds=("ball",), geometry=("ruled",),
    description="Finish a ruled surface along its parameter lines with the ball tool leaning at a lead and tilt angle from the surface normal, all five axes moving together.",
    fields=[
        Field("machine", "text", "mill5_table_table", "Machine model", group="Machine"),
        Field("side", "choice", "positive", "Tool side", choices=("positive", "negative", "up"), group="Surface"),
        Field("stepover", "number", None, "Stepover", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("scallop", "number", 0.01, "Scallop height (used when no stepover)", 0.0005, 5.0, "mm", group="Passes"),
        Field("lead", "number", 5.0, "Lead angle", -60.0, 60.0, "deg", group="Tool axis"),
        Field("tilt", "number", 0.0, "Tilt angle", -60.0, 60.0, "deg", group="Tool axis"),
        Field("step", "number", 0.8, "Sample spacing", 0.05, 100.0, "mm", group="Accuracy"),
        Field("max_angle_step", "number", 2.0, "Largest rotary step", 0.1, 20.0, "deg", group="Accuracy"),
        Field("stock_to_leave", "number", 0.0, "Stock to leave", 0.0, 50.0, "mm", group="Passes"),
        Field("retract", "number", 30.0, "Retract along the tool axis", 1.0, 1000.0, "mm", group="Linking"),
        Field("approach", "number", 3.0, "Approach distance", 0.5, 100.0, "mm", group="Linking"),
    ],
))
