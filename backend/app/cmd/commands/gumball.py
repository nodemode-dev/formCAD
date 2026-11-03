from app.cmd.commands.surfaces import ask_style, handles_of
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.gumball import frame as fr
from app.gumball import ops, state
from app.solid.work import SolidError

ACTIONS = ("on", "off", "state", "relocate", "align", "reset", "move", "rotate", "scale")


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (state.GumballError, ops.OpError, fr.FrameError) as err:
        raise CommandError(str(err))
    except SolidError as err:
        raise CommandError(str(err))


def say_state(ctx, d):
    o = d["origin"]
    where = "no selection" if o is None else "origin %s, %s, %s" % (ctx.fd(o[0]), ctx.fd(o[1]), ctx.fd(o[2]))
    ctx.say("GUMBALL: %s, aligned to %s%s, %s." % ("on" if d["on"] else "off", d["align"], " (placed by hand)" if d["manual"] else "", where))


def run_op(ctx, op, handles=None, copy_flag=False):
    got = guard(ops.apply, ctx.doc, op, handles, copy_flag)
    ctx.say("GUMBALL: %s applied to %d object(s)%s." % (got["kind"], len(got["handles"]), "" if not got["skipped"] else ", %d could not be changed that way" % got["skipped"]))
    return got


def run_action(ctx, args):
    action = str(args.get("action", "state")).lower()
    if action not in ACTIONS:
        raise CommandError("Choose one of: %s." % ", ".join(ACTIONS))
    doc = ctx.doc
    if action in ("on", "off"):
        d = guard(state.set_on, doc, action == "on")
    elif action == "state":
        d = guard(state.describe, doc, handles_of(args, "handles") or None)
    elif action == "reset":
        d = guard(state.reset, doc)
    elif action == "relocate":
        d = guard(state.relocate, doc, args.get("point"), args.get("ray"), args.get("aperture"), args.get("modes"), args.get("base"), args.get("plane"), handles_of(args, "snap_handles") or None)
    elif action == "align":
        d = guard(state.set_align, doc, args.get("mode", "world"), args.get("plane"), args.get("object"), args.get("face"))
    else:
        op = {k: v for k, v in args.items() if k not in ("action", "handles", "copy")}
        op["type"] = action
        got = run_op(ctx, op, handles_of(args, "handles") or None, bool(args.get("copy", False)))
        return got
    say_state(ctx, d)
    return d


@command("gumball", aliases=("gb",), group="modify", label="Gumball", description="Move, rotate and scale the selection about a pivot with typed values; relocate or align the pivot frame.", menu="Modify > Gumball")
def gumball_cmd(ctx):
    word = yield from ask_style(ctx, "Gumball", ["On", "Off", "Relocate", "Align", "Reset", "Move", "Rotate", "Scale"], "On")
    if word is None:
        return
    w = word.lower()
    if w in ("on", "off", "reset"):
        run_action(ctx, {"action": w})
        return
    if w == "relocate":
        p = yield ctx.point("Specify the new gumball position")
        if p.kind == "point":
            run_action(ctx, {"action": "relocate", "point": [p.value[0], p.value[1], p.value[2] if len(p.value) > 2 else 0.0]})
        return
    if w == "align":
        mode = yield from ask_style(ctx, "Align with", ["World", "Object"], "World")
        if mode is None:
            return
        if mode == "World":
            run_action(ctx, {"action": "align", "mode": "world"})
            return
        sel = yield ctx.select("Select the object to align with", pick_one=True)
        if sel.kind == "selection" and sel.value:
            run_action(ctx, {"action": "align", "mode": "object", "object": int(sel.value[0])})
        return
    if not state.selection_handles(ctx.doc):
        sel = yield ctx.select("Select objects to transform")
        if sel.kind != "selection" or not sel.value:
            return
        handles = [int(h) for h in sel.value]
    else:
        handles = None
    if w == "move":
        axis = yield from ask_style(ctx, "Direction", ["X", "Y", "Z"], "X")
        if axis is None:
            return
        dist = yield ctx.number("Specify the distance to move along %s" % axis)
        if dist.kind == "number":
            run_op(ctx, {"type": "move", "axis": axis.lower(), "distance": dist.value}, handles)
    elif w == "rotate":
        axis = yield from ask_style(ctx, "Rotate about", ["X", "Y", "Z"], "Z")
        if axis is None:
            return
        deg = yield ctx.number("Specify the rotation angle in degrees about %s" % axis)
        if deg.kind == "number":
            run_op(ctx, {"type": "rotate", "axis": axis.lower(), "degrees": deg.value}, handles)
    else:
        axis = yield from ask_style(ctx, "Scale along", ["Uniform", "X", "Y", "Z"], "Uniform")
        if axis is None:
            return
        k = yield ctx.number("Specify the scale factor", positive=True)
        if k.kind == "number":
            op = {"type": "scale", "factor": k.value}
            if axis != "Uniform":
                op["axis"] = axis.lower()
            run_op(ctx, op, handles)


@executes("gumball")
def gumball_exec(ctx, args):
    return run_action(ctx, args)
