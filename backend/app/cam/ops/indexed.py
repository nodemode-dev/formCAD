from app.cam.registry import Field, OpType, register
from app.cam3d import indexing, multiaxis


def generate(ctx):
    p = ctx.p
    machine = multiaxis.machine_of(p["machine"])
    axis = (p["axis_x"], p["axis_y"], p["axis_z"])
    return indexing.build(ctx, p["base"], p["base_params"], machine, p["a"], p["c"], axis if any(v is not None for v in axis) else None)


register(OpType(
    kind="indexed", label="Indexed operation (3+2)", group="5axis", generate=generate, tool_kinds=(), geometry=("model", "section", "removal", "model_holes", "stock"),
    description="Run another operation with the tool axis tilted to a fixed pair of rotary angles (or to a tool axis vector solved on the machine model); the output carries the axis and the solved angles with every move.",
    fields=[
        Field("base", "text", "parallel", "Base operation kind", group="Operation"),
        Field("base_params", "text", "{}", "Base operation parameters (JSON)", group="Operation"),
        Field("machine", "text", "mill5_table_table", "Machine model", group="Machine"),
        Field("a", "number", 0.0, "A angle", -360.0, 360.0, "deg", group="Orientation"),
        Field("c", "number", 0.0, "C angle", -100000.0, 100000.0, "deg", group="Orientation"),
        Field("axis_x", "number", None, "Tool axis x (overrides A and C)", -1.0, 1.0, "", group="Orientation", nullable=True),
        Field("axis_y", "number", None, "Tool axis y", -1.0, 1.0, "", group="Orientation", nullable=True),
        Field("axis_z", "number", None, "Tool axis z", -1.0, 1.0, "", group="Orientation", nullable=True),
    ],
    needs_model=True,
))
