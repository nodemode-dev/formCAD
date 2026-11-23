import math

from app.cmd.commands.surfaces import GROUP, announce, ask_style, guard, handles_of
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc.kinds.nurbscurve import NurbsCurve
from app.nurbs3d import service
from app.solid import surfwork as sw

MODES = {"all": "all", "holes": "holes"}


def face_arg(ctx, args):
    d = ctx.d
    picked = list(ctx.doc.subselection.get("faces") or [])
    handles = handles_of(args)
    if handles:
        body = guard(sw.body_of, d, handles[0])
        ref = {"body": body.handle, "face": args.get("face"), "face_index": args.get("face_index")}
        if ref["face"] is None and ref["face_index"] is None:
            mine = [f for f in picked if f["body"] == body.handle]
            if mine:
                ref["face"] = mine[0]["face"]
            elif sw.single_face(body):
                ref["face_index"] = 0
            else:
                raise CommandError("This surface has %d faces; select the face first, or give face or face_index." % len(body.face_ids))
    elif picked:
        ref = {"body": picked[0]["body"], "face": picked[0]["face"]}
    else:
        raise CommandError("Give the handle of a trimmed surface, or select a face first.")
    return guard(sw.face_ref, d, ref)


def span(values) -> str:
    return " to ".join("unbounded" if v is None else "%.6g" % v for v in values)


def keep_curves(ctx, body, res) -> list:
    made = []
    for item in res.get("curves") or []:
        got = service.from_mm(ctx.d, item)
        e = NurbsCurve(name="Trim curve")
        e.set_record(got["curve"])
        e.audit = service.audit_of(got)
        e.source = {"op": "untrim", "from": body.handle}
        made.append(ctx.add(e))
    return made


def do_untrim(ctx, args):
    body, face = face_arg(ctx, args)
    mode = MODES.get(str(args.get("mode", "all")).lower())
    if mode is None:
        raise CommandError("The mode is all or holes.")
    res = guard(sw.call, ctx.d, "surf_untrim", {"face": face, "mode": mode, "keep_curves": bool(args.get("keep_curves", False))})
    made, in_place = guard(sw.edit_surface, ctx, body, res, "untrim")
    curves = keep_curves(ctx, body, res)
    rep = res["report"]
    announce(ctx, "SRFUNTRIM", res)
    ctx.say("Removed %d trim loop(s); area %.6g became %.6g square mm; %d trim curve(s) kept." % (rep.get("wires_removed", 0), rep.get("area_before", 0.0), rep.get("area_after", 0.0), len(curves)))
    return {"handle": made.handle, "in_place": in_place, "curves": curves, "report": rep}


def do_shrink(ctx, args):
    body, face = face_arg(ctx, args)
    params = {"face": face}
    if args.get("margin") is not None:
        try:
            margin = float(args["margin"])
        except (TypeError, ValueError):
            raise CommandError("The margin must be a number.")
        if not math.isfinite(margin) or not 0.0 <= margin <= 1.0:
            raise CommandError("The margin is a fraction from 0 to 1 of the trimmed extent.")
        params["margin"] = margin
    res = guard(sw.call, ctx.d, "surf_shrink", params)
    made, in_place = guard(sw.edit_surface, ctx, body, res, "shrink")
    rep = res["report"]
    announce(ctx, "SRFSHRINK", res)
    before, after = rep.get("uv_before") or [None] * 4, rep.get("uv_after") or [None] * 4
    ctx.say("U range %s became %s; V range %s became %s." % (span(before[:2]), span(after[:2]), span(before[2:]), span(after[2:])))
    ctx.say("The trimmed area is %.6g square mm, changed by %.3g." % (rep.get("area_after", 0.0), abs(rep.get("area_after", 0.0) - rep.get("area_before", 0.0))))
    return {"handle": made.handle, "in_place": in_place, "report": rep}


@command("srfuntrim", aliases=("surfuntrim", "untrim"), group=GROUP, label="Untrim Surface", description="Remove the trim of a surface face and give back its whole underlying surface, or remove only its holes; the trim curves can be kept as curves.", menu="Modify > 3D Operations > Untrim Surface")
def srfuntrim_cmd(ctx):
    sel = yield ctx.select("Select the trimmed surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    what = yield from ask_style(ctx, "Remove", ["All", "Holes"], "All")
    if what is None:
        return
    keep = yield from ask_style(ctx, "Keep the trim curves", ["Yes", "No"], "No")
    if keep is None:
        return
    do_untrim(ctx, {"handle": int(sel.value[0]), "mode": what.lower(), "keep_curves": keep == "Yes"})


@executes("srfuntrim")
def srfuntrim_exec(ctx, args):
    return do_untrim(ctx, args)


@command("srfshrink", aliases=("surfshrink", "shrinktrimmed"), group=GROUP, label="Shrink Trimmed Surface", description="Shrink the underlying surface of a trimmed face to just beyond its trim boundary; the face keeps its shape.", menu="Modify > 3D Operations > Shrink Trimmed Surface")
def srfshrink_cmd(ctx):
    sel = yield ctx.select("Select the trimmed surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    do_shrink(ctx, {"handle": int(sel.value[0])})


@executes("srfshrink")
def srfshrink_exec(ctx, args):
    return do_shrink(ctx, args)
