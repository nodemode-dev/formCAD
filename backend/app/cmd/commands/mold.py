from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.mold import service, settings
from app.mold.settings import MoldError
from app.solid.work import SolidError

FAILURES = (MoldError, SolidError, ValueError, KeyError)
OPTIONS = ("body", "pull", "min_draft", "grid", "height", "margin", "cavity_margin", "core_margin", "shrink")


def guarded(fn, *a, **k):
    try:
        return fn(*a, **k)
    except FAILURES as err:
        raise CommandError(str(err))


def options(args) -> dict:
    out = {k: args[k] for k in OPTIONS if args.get(k) is not None}
    for k in ("shrink_percent", "shrink_convention", "shrink_origin"):
        if args.get(k) is not None:
            sh = dict(out.get("shrink") or {}) if isinstance(out.get("shrink"), dict) else {}
            sh[k[len("shrink_"):]] = args[k]
            out["shrink"] = sh
    return out


def settings_text(rec) -> str:
    sh = rec["shrink"]
    pc = sh["percent"]
    return "Mold settings: pull %s, minimum draft %.3g degrees, shrinkage %.3g / %.3g / %.3g percent (%s)." % (rec["pull"], rec["min_draft"], pc[0], pc[1], pc[2], sh["convention"])


def ask_vector(ctx, label, default):
    raw = yield ctx.text(label, default)
    if raw.kind != "text":
        return None
    try:
        v = [float(t) for t in str(raw.value).replace(",", " ").split()]
    except ValueError:
        raise CommandError("Give three numbers separated by spaces.")
    if len(v) != 3:
        raise CommandError("Give three numbers separated by spaces.")
    return v


def apply(ctx, values):
    rec = guarded(settings.put, ctx.doc.drawing, values)
    ctx.say(settings_text(rec))
    return {"settings": rec}


@command("moldsettings", group="solids", label="Mold Settings", description="Show or change the mold settings: pull direction, minimum draft, shrinkage and block margins.", menu="Tools > Mold > Settings")
def moldsettings(ctx):
    rec = settings.current(ctx.d)
    ctx.say(settings_text(rec))
    key = yield ctx.text("Value to change: pull, min_draft, shrink, height, margin or body (blank to keep)", "")
    if key.kind != "text" or not str(key.value).strip():
        return
    name = str(key.value).strip()
    if name == "pull":
        v = yield from ask_vector(ctx, "Pull direction as x y z", "0 0 1")
        if v is not None:
            apply(ctx, {"pull": v})
        return
    if name == "shrink":
        pc = yield ctx.number("Shrinkage in percent", minimum=0.0)
        if pc.kind != "number":
            return
        conv = yield ctx.text("Convention, multiply (1 + s) or divide (1 / (1 - s))", rec["shrink"]["convention"])
        if conv.kind != "text":
            return
        apply(ctx, {"shrink": {"percent": pc.value, "convention": str(conv.value).strip() or "multiply"}})
        return
    val = yield ctx.number("New value")
    if val.kind != "number":
        return
    apply(ctx, {name: val.value})


@executes("moldsettings")
def moldsettings_exec(ctx, args):
    if str(args.get("action") or "") == "reset":
        guarded(settings.reset, ctx.doc.drawing)
        return {"settings": settings.current(ctx.d)}
    values = options(args)
    if not values:
        return {"settings": settings.current(ctx.d), "result": settings.last_result(ctx.d)}
    return apply(ctx, values)


def analysis_lines(ctx, out):
    pc = out["percent_by_class"]
    ctx.say("MOLDDRAFT: %.1f percent of the area has enough draft, %.1f percent is steep, %.1f percent is undercut." % (pc["ok"], pc["steep"], pc["undercut"]))
    if out["undercut_faces"]:
        ctx.say("Undercut faces: %s." % ", ".join(str(f) for f in out["undercut_faces"][:30]))


@command("molddraft", group="solids", label="Mold Draft Report", description="Report draft and undercuts of the part along the mold pull direction, per face.", menu="Tools > Mold > Draft and Undercut Report", undoable=False)
def molddraft(ctx):
    analysis_lines(ctx, guarded(service.analyze, ctx.doc, {}))


@executes("molddraft")
def molddraft_exec(ctx, args):
    out = guarded(service.analyze, ctx.doc, options(args))
    analysis_lines(ctx, out)
    return out


def parting_lines(ctx, out):
    ctx.say("MOLDPARTING: height %.4g along the pull (%s), %d silhouette wire(s), %d through hole(s)%s." % (out["height"], out["height_source"], len(out["wires"]), len(out["through_holes"]), "" if out["planar"] else ", not planar"))
    for n in out["notes"]:
        ctx.say(n)


@command("moldparting", group="solids", label="Mold Parting Line", description="Find the parting line as the silhouette of the part along the pull direction, with its through holes.", menu="Tools > Mold > Parting Line", undoable=False)
def moldparting(ctx):
    parting_lines(ctx, guarded(service.parting, ctx.doc, {}))


@executes("moldparting")
def moldparting_exec(ctx, args):
    out = guarded(service.parting, ctx.doc, options(args))
    parting_lines(ctx, out)
    return out


@command("moldblock", group="solids", label="Mold Block", description="Add a rectangular mold block around the part, aligned to the pull direction.", menu="Tools > Mold > Block")
def moldblock(ctx):
    out = guarded(service.block, ctx.doc, {})
    ctx.say("MOLDBLOCK: block %s, volume %.6g." % (" x ".join("%.4g" % c for c in out["size"]), out["volume"]))


@executes("moldblock")
def moldblock_exec(ctx, args):
    out = guarded(service.block, ctx.doc, options(args))
    ctx.say("MOLDBLOCK: block %s, volume %.6g." % (" x ".join("%.4g" % c for c in out["size"]), out["volume"]))
    return out


def split_lines(ctx, out):
    c = out["check"]
    ctx.say("MOLDSPLIT: core %.6g, cavity %.6g, part %.6g, block %.6g (residual %.3g, %s)." % (c["core"], c["cavity"], c["part"], c["block"], c["residual"], "volume check passed" if c["ok"] else "volume check FAILED"))
    ctx.say("%d shut-off patch(es); parting height %.4g." % (len(out["shut_offs"]), out["height"]))


@command("moldsplit", group="solids", label="Mold Core and Cavity", description="Split a mold block into core and cavity along the parting surface, with shut-offs for through holes and a volume check.", menu="Tools > Mold > Split Core and Cavity")
def moldsplit(ctx):
    split_lines(ctx, guarded(service.split, ctx.doc, {}))


@executes("moldsplit")
def moldsplit_exec(ctx, args):
    spec = options(args)
    for k in ("keep_block", "keep_part"):
        if args.get(k) is not None:
            spec[k] = args[k]
    out = guarded(service.split, ctx.doc, spec)
    split_lines(ctx, out)
    return out


@command("moldclear", group="solids", label="Clear Mold", description="Erase the mold bodies made by the block and split commands.", menu="Tools > Mold > Clear")
def moldclear(ctx):
    gone = service.clear(ctx.d)
    ctx.say("MOLDCLEAR: erased %d mold bodies." % len(gone))


@executes("moldclear")
def moldclear_exec(ctx, args):
    gone = service.clear(ctx.d)
    return {"erased": gone}
