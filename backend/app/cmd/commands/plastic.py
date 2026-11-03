from app.cmd.commands.analysis3d import optional_ramp, pick_surfaces, show
from app.cmd.commands.sheetmetal import ask_ids, sheet_feature
from app.cmd.commands.surfaces import handles_of
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.part.registry import PartError
from app.plastic import check, data, records, rule

FAILURES = (PartError,)


def guarded(fn, *a, **k):
    try:
        return fn(*a, **k)
    except FAILURES as err:
        raise CommandError(str(err))


def ask_vector(ctx, label, default=None):
    raw = yield ctx.text(label, default)
    if raw.kind != "text":
        return None
    try:
        v = [float(t) for t in str(raw.value).replace(",", " ").split()]
    except ValueError:
        raise CommandError("Give three numbers separated by spaces.")
    if len(v) == 2:
        v.append(0.0)
    if len(v) != 3:
        raise CommandError("Give three numbers separated by spaces.")
    return v


def rule_text(rl):
    mat = rl["material"] or "no material"
    wall = "not set" if rl["nominal_wall"] is None else "%.4g mm" % rl["nominal_wall"]
    return "Plastic rule: %s, nominal wall %s, minimum draft %.3g degrees." % (mat, wall, rl["min_draft"])


@command("plasticrule", group="solids", label="Plastic Rule", description="Show the plastic part rule, or change one value of it.", menu="Tools > Plastic > Rule")
def plasticrule(ctx):
    ctx.say(rule_text(rule.current(ctx.doc.drawing)))
    key = yield ctx.text("Value to change, for example nominal_wall (blank to keep the rule)", "")
    if key.kind != "text" or not str(key.value).strip():
        return
    name = str(key.value).strip()
    if name == "material":
        val = yield ctx.text("Material id, for example abs, pc, nylon", "")
        if val.kind != "text":
            return
        set_rule(ctx, {"material": str(val.value).strip()})
        return
    val = yield ctx.number("New value")
    if val.kind != "number":
        return
    set_rule(ctx, {name: val.value})


def set_rule(ctx, values):
    out = guarded(rule.put, ctx.doc.drawing, values)
    guarded(rule.refresh, ctx.doc)
    ctx.say(rule_text(out))
    return {"rule": out}


@executes("plasticrule")
def plasticrule_exec(ctx, args):
    values = dict(args.get("values") or {})
    for k in rule.KEYS:
        if k in args and k not in values:
            values[k] = args[k]
    if str(args.get("action") or "") == "reset":
        guarded(rule.reset, ctx.doc.drawing)
        guarded(rule.refresh, ctx.doc)
        return {"rule": rule.current(ctx.doc.drawing)}
    if str(args.get("action") or "") == "materials":
        return {"materials": data.materials()}
    if not values:
        return {"rule": rule.current(ctx.doc.drawing), "features": records.features(ctx.doc.drawing)}
    return set_rule(ctx, values)


@command("plasticboss", group="solids", label="Plastic Boss", description="Add a screw boss with draft, a hole and a base fillet, sized from the plastic rule.", menu="Draw > Plastic > Boss")
def plasticboss(ctx):
    ids = yield from ask_ids(ctx, "Persistent id of the face the boss stands on")
    if not ids:
        return
    pt = yield from ask_vector(ctx, "Boss centre as x y z")
    if pt is None:
        return
    d = yield ctx.number("Screw diameter", positive=True)
    if d.kind != "number":
        return
    sheet_feature(ctx, {"face": ids[0], "point": pt, "screw_diameter": d.value}, "plastic_boss")


@executes("plasticboss")
def plasticboss_exec(ctx, args):
    return sheet_feature(ctx, args, "plastic_boss")


@command("plasticrib", group="solids", label="Plastic Rib", description="Add a drafted rib along a line on a face, with its thickness taken from the plastic rule.", menu="Draw > Plastic > Rib")
def plasticrib(ctx):
    ids = yield from ask_ids(ctx, "Persistent id of the face the rib stands on")
    if not ids:
        return
    a = yield from ask_vector(ctx, "Rib start as x y z")
    if a is None:
        return
    b = yield from ask_vector(ctx, "Rib end as x y z")
    if b is None:
        return
    h = yield ctx.number("Rib height", positive=True)
    if h.kind != "number":
        return
    sheet_feature(ctx, {"face": ids[0], "start": a, "end": b, "height": h.value}, "plastic_rib")


@executes("plasticrib")
def plasticrib_exec(ctx, args):
    return sheet_feature(ctx, args, "plastic_rib")


@command("snaphook", group="solids", label="Snap-Fit Hook", description="Add a cantilever snap-fit hook and check its root strain against the plastic rule.", menu="Draw > Plastic > Snap-Fit Hook")
def snaphook(ctx):
    ids = yield from ask_ids(ctx, "Persistent id of the face the hook stands on")
    if not ids:
        return
    pt = yield from ask_vector(ctx, "Hook root position as x y z")
    if pt is None:
        return
    dr = yield from ask_vector(ctx, "Direction the hook projects, lying in the face", "1 0 0")
    if dr is None:
        return
    sheet_feature(ctx, {"face": ids[0], "point": pt, "direction": dr}, "snap_hook")


@executes("snaphook")
def snaphook_exec(ctx, args):
    return sheet_feature(ctx, args, "snap_hook")


@command("plasticlip", group="solids", label="Lip", description="Add a lip around the rim face, sized from the wall of the plastic rule.", menu="Draw > Plastic > Lip")
def plasticlip(ctx):
    ids = yield from ask_ids(ctx, "Persistent id of the rim face")
    if not ids:
        return
    sheet_feature(ctx, {"face": ids[0]}, "plastic_lip")


@executes("plasticlip")
def plasticlip_exec(ctx, args):
    return sheet_feature(ctx, args, "plastic_lip")


@command("plasticgroove", group="solids", label="Groove", description="Cut a groove around the rim face to take a lip, sized from the plastic rule.", menu="Draw > Plastic > Groove")
def plasticgroove(ctx):
    ids = yield from ask_ids(ctx, "Persistent id of the rim face")
    if not ids:
        return
    sheet_feature(ctx, {"face": ids[0]}, "plastic_groove")


@executes("plasticgroove")
def plasticgroove_exec(ctx, args):
    return sheet_feature(ctx, args, "plastic_groove")


def report_lines(ctx, out):
    s = out["summary"]
    w = out["wall"]
    if w["min"] is not None:
        ctx.say("PLASTICCHECK: wall %.3g to %.3g mm (%s method, %d samples)." % (w["min"], w["max"], w["method"], w["samples"]))
    ctx.say("PLASTICCHECK: %d error(s), %d warning(s), %d note(s)." % (s["errors"], s["warnings"], s["info"]))
    for f in out["findings"][:20]:
        ctx.say("%s  %s" % (f["severity"].upper(), f["message"]))


@command("plasticcheck", group="solids", label="Plastic Checks", description="Check the part against the plastic rule: walls, draft, ribs, bosses, snap fits and inside corners.", menu="Tools > Plastic > Check", undoable=False)
def plasticcheck(ctx):
    out = guarded(check.run, ctx.doc, {})
    report_lines(ctx, out)


@executes("plasticcheck")
def plasticcheck_exec(ctx, args):
    opts = {k: args[k] for k in ("pull", "samples", "method") if args.get(k) is not None}
    out = guarded(check.run, ctx.doc, opts)
    report_lines(ctx, out)
    return out


@command("wallthickness", aliases=("wallana",), group="inquiry", label="Wall Thickness", description="Colour the solid by wall thickness measured along the inward surface normal (ray) or by the largest sphere (sphere).", menu="Tools > Inquiry > Wall Thickness", undoable=False)
def wallthickness(ctx):
    handles = yield from pick_surfaces(ctx, "Select solids for wall thickness or press Enter for all")
    if handles is None:
        return
    show(ctx, "WALLTHICKNESS", {"mode": "wall", "targets": handles, "method": "ray"})


@executes("wallthickness")
def wallthickness_exec(ctx, args):
    spec = {"mode": "wall", "targets": handles_of(args, "handles") or handles_of(args, "targets"), "method": args.get("method", "ray")}
    for key in ("low", "high", "max_vertices"):
        if args.get(key) is not None:
            spec[key] = args[key]
    spec.update(optional_ramp(args))
    return show(ctx, "WALLTHICKNESS", spec)
