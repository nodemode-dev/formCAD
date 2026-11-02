from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import dynblock as DB
from app.doc.blocktools import EditError

AUTOMATION = "Dynamic block operations are available through the automation form only."


def _guard(fn):
    try:
        return fn()
    except EditError as err:
        raise CommandError(str(err))


@command("dynblock.define", group="block", label="Attach Dynamic Data", description="Attach parameters and actions to a block definition (kept as given).", menu="")
def dyn_define(ctx):
    ctx.say(AUTOMATION)
    yield from ()


@executes("dynblock.define")
def dyn_define_exec(ctx, args):
    return _guard(lambda: DB.define(ctx.doc, str(args.get("name", "")), args.get("data")))


@command("dynblock.read", group="block", label="Read Dynamic Block", description="Read a dynamic block definition.", menu="", undoable=False)
def dyn_read(ctx):
    ctx.say(AUTOMATION)
    yield from ()


@executes("dynblock.read")
def dyn_read_exec(ctx, args):
    return _guard(lambda: DB.read_definition(ctx.d, str(args.get("name", ""))))


@command("dynblock.props", group="block", label="Dynamic Block Properties", description="Read the dynamic property values of a block reference.", menu="", undoable=False)
def dyn_props(ctx):
    ctx.say(AUTOMATION)
    yield from ()


@executes("dynblock.props")
def dyn_props_exec(ctx, args):
    return _guard(lambda: DB.reference_properties(ctx.d, args.get("handle", 0)))


@command("dynblock.set", group="block", label="Set Dynamic Property", description="Set a custom property of a dynamic block reference.", menu="")
def dyn_set(ctx):
    ctx.say(AUTOMATION)
    yield from ()


@executes("dynblock.set")
def dyn_set_exec(ctx, args):
    return _guard(lambda: DB.set_property(ctx.doc, args.get("handle", 0), str(args.get("name", "")), args.get("value")))


@command("dynblock.grips", group="block", label="Dynamic Block Grips", description="List the custom grips of a dynamic block reference.", menu="", undoable=False)
def dyn_grips(ctx):
    ctx.say(AUTOMATION)
    yield from ()


@executes("dynblock.grips")
def dyn_grips_exec(ctx, args):
    return {"grips": _guard(lambda: DB.custom_grips(ctx.d, args.get("handle", 0)))}


@command("dynblock.drag", group="block", label="Drag Dynamic Grip", description="Drag a custom grip of a dynamic block reference to a point.", menu="")
def dyn_drag(ctx):
    ctx.say(AUTOMATION)
    yield from ()


@executes("dynblock.drag")
def dyn_drag_exec(ctx, args):
    return _guard(lambda: DB.drag_grip(ctx.doc, args.get("handle", 0), str(args.get("grip", "")), args.get("point", [0.0, 0.0])))
