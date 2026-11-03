import re

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.mates import explode, interf, motion, ops
from app.mates import store as S
from app.solid.work import SolidError

FAILURES = (S.MateRefused, SolidError, ValueError, KeyError)
KIND_WORDS = ["Coincident", "Concentric", "Distance", "Angle", "Parallel", "Perpendicular", "Tangent", "Lock", "Gear", "Rack", "Screw", "LimitDistance", "LimitAngle"]
REF_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*(?::\s*([A-Za-z]+)\s*(\d*))?\s*$")
NEEDS_VALUE = {"distance": "Distance", "angle": "Angle in degrees", "gear": "Gear ratio (turns of the second per turn of the first)", "rackpinion": "Pinion pitch radius", "screw": "Pitch (travel per turn)"}


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except S.MateRefused as err:
        raise CommandError(err.message)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def parse_ref(value):
    if isinstance(value, dict):
        return value
    m = REF_RE.match(str(value))
    if not m:
        raise CommandError("A reference reads like C1:f2 (face 2), C1:e0 (edge), C1:v3 (vertex), C1:xy or C1:z (origin plane or axis), or just C1 for a lock.")
    comp, what, num = m.group(1), (m.group(2) or "").lower(), m.group(3)
    comp = None if comp.lower() in ("world", "ground") else comp.upper()
    if not what:
        return {"comp": comp}
    if what in ("f", "e", "v"):
        if num == "":
            raise CommandError("Give the number after %s, like C1:%s2." % (what, what))
        return {"comp": comp, {"f": "face", "e": "edge", "v": "vertex"}[what]: int(num)}
    return {"comp": comp, "origin": what}


def refs_of(args):
    raw = args.get("refs")
    if raw is None:
        raw = [x for x in (args.get("first"), args.get("second"), args.get("about")) if x is not None]
    if not isinstance(raw, list):
        raise CommandError("refs is a list of references.")
    return [parse_ref(r) for r in raw]


def comp_ref(ctx, text):
    from app.assembly import store as A

    return A.find_component(ctx.d, text)["id"]


def say_state(ctx, st):
    ctx.say("State %s, %d degree(s) of freedom." % (st["state"], st["dof"]))


@command("mate", aliases=("addmate",), group="solids", label="Mate", description="Position a component against another with a mate: coincident, concentric, distance, angle, parallel, perpendicular, tangent, lock, gear, rack and pinion, screw or a limit.", menu="Assembly > Mate")
def mate_cmd(ctx):
    k = yield ctx.keyword("Mate [%s]" % "/".join(KIND_WORDS), KIND_WORDS, "Coincident")
    if k.kind != "keyword":
        return
    kind = ops.kind_of(k.value)
    r1 = yield ctx.text("Enter the first reference (like C1:f2, C1:z or C1:xy)")
    if r1.kind != "text":
        return
    r2 = yield ctx.text("Enter the second reference")
    if r2.kind != "text":
        return
    refs = [parse_ref(r1.value), parse_ref(r2.value)]
    value = None
    opt = {}
    if kind in ("angle", "limitangle"):
        r3 = yield ctx.text("Enter the rotation axis reference, or press Enter for the plain angle")
        if r3.kind == "text" and str(r3.value).strip():
            refs.append(parse_ref(r3.value))
    if kind in NEEDS_VALUE:
        v = yield ctx.number(NEEDS_VALUE[kind], default=0.0 if kind in ("distance", "angle") else 1.0)
        if v.kind != "number":
            return
        value = float(v.value)
    if kind.startswith("limit"):
        lo = yield ctx.number("Minimum", default=0.0)
        hi = yield ctx.number("Maximum", default=10.0)
        if lo.kind != "number" or hi.kind != "number":
            return
        opt = {"min": float(lo.value), "max": float(hi.value)}
    out = run(ops.add_mate, ctx.doc, kind, refs, value, opt)
    ctx.say("%s added. %s" % (out["mate"]["name"], "Moved %s." % ", ".join(out["moved"]) if out["moved"] else "Nothing moved."))
    say_state(ctx, out["status"])
    return {"id": out["mate"]["id"]}


@executes("mate")
def mate_exec(ctx, args):
    if not args.get("kind"):
        raise CommandError("Give kind.")
    out = run(ops.add_mate, ctx.doc, str(args["kind"]), refs_of(args), args.get("value"), args.get("opt") or {}, str(args.get("label") or ""), bool(args.get("force", False)))
    return {"id": out["mate"]["id"], "name": out["mate"]["name"], "moved": out["moved"], "poses": out["poses"], "state": out["status"]["state"], "dof": out["status"]["dof"], "status": out["status"], "ms": out["ms"], "iterations": out["iterations"], "message": "%s added; %d degree(s) of freedom left." % (out["mate"]["name"], out["status"]["dof"])}


@command("mateedit", group="solids", label="Edit Mate", description="Change the value, label, options or suppression of a mate.", menu="Assembly > Edit Mate")
def mateedit(ctx):
    t = yield ctx.text("Enter the mate name or id")
    if t.kind != "text":
        return
    rec = S.get(ctx.d, t.value.strip())
    if rec is None:
        raise CommandError("There is no mate %s." % t.value)
    if rec["kind"] in ("distance", "angle", "gear", "rackpinion", "screw"):
        v = yield ctx.number("New value", default=rec.get("value") or 0.0)
        if v.kind != "number":
            return
        out = run(ops.set_mate, ctx.doc, rec["id"], float(v.value))
    else:
        s = yield ctx.yesno("Suppress this mate", "No")
        out = run(ops.set_mate, ctx.doc, rec["id"], None, None, None, s.value == "Yes")
    ctx.say("%s updated." % out["mate"]["name"])


@executes("mateedit")
def mateedit_exec(ctx, args):
    ident = args.get("mate")
    rec = S.get(ctx.d, ident if not str(ident).isdigit() else int(ident))
    if rec is None:
        raise CommandError("There is no mate %s." % ident)
    out = run(ops.set_mate, ctx.doc, rec["id"], args.get("value"), args.get("opt"), args.get("label"), args.get("suppressed"))
    return {"id": rec["id"], "moved": out.get("moved", []), "poses": out.get("poses", {}), "status": out["status"], "mate": out["mate"]}


@command("matedelete", aliases=("delmate",), group="solids", label="Delete Mate", description="Remove one or more mates.", menu="Assembly > Delete Mate")
def matedelete(ctx):
    t = yield ctx.text("Enter the mate names or ids, separated by commas")
    if t.kind != "text":
        return
    out = run(ops.remove_mates, ctx.doc, [x.strip() for x in t.value.split(",") if x.strip()])
    ctx.say("Removed %d mate(s)." % len(out["removed"]))


@executes("matedelete")
def matedelete_exec(ctx, args):
    ids = args.get("mates")
    if ids is None:
        ids = [args.get("mate")]
    return run(ops.remove_mates, ctx.doc, [i for i in ids if i is not None])


@command("matesolve", group="solids", label="Solve Mates", description="Solve every mate again from the current positions.", menu="Assembly > Solve Mates")
def matesolve(ctx):
    out = run(ops.resolve_all, ctx.doc)
    ctx.say("Solved in %.1f ms; moved %s." % (out["ms"], ", ".join(out["moved"]) or "nothing"))
    say_state(ctx, out["status"])


@executes("matesolve")
def matesolve_exec(ctx, args):
    out = run(ops.resolve_all, ctx.doc)
    return {"moved": out["moved"], "poses": out["poses"], "status": out["status"], "ms": out["ms"], "iterations": out["iterations"]}


@command("matestatus", aliases=("dof", "matedof"), group="solids", label="Mate Status", description="Show the degrees of freedom of every component and the state of every mate.", menu="Assembly > Mate Status", transparent=True)
def matestatus(ctx):
    st = run(ops.status, ctx.doc)
    say_state(ctx, st)
    for cid, v in st["components"].items():
        ctx.say("%s: %s, %d free" % (cid, v["state"], v["dof"]))
    for m in st["mates"]:
        ctx.say("%s %s: %s" % (m["name"], m["kind"], m["state"]))


@executes("matestatus")
def matestatus_exec(ctx, args):
    return run(ops.status, ctx.doc)


@command("matedrive", aliases=("drive",), group="solids", label="Drive Mate", description="Set a distance or angle mate to a value and move the mechanism along its free motion.", menu="Assembly > Drive Mate")
def matedrive(ctx):
    t = yield ctx.text("Enter the distance or angle mate name or id")
    if t.kind != "text":
        return
    rec = S.get(ctx.d, t.value.strip())
    if rec is None:
        raise CommandError("There is no mate %s." % t.value)
    v = yield ctx.number("Value to drive to", default=rec.get("value") or 0.0)
    if v.kind != "number":
        return
    out = run(ops.drive, ctx.doc, rec["id"], float(v.value))
    ctx.say("Driven to %g in %.1f ms." % (out["final"], out["ms"]))
    if out["message"]:
        ctx.say(out["message"])


@executes("matedrive")
def matedrive_exec(ctx, args):
    ident = args.get("mate")
    rec = S.get(ctx.d, ident if not str(ident).isdigit() else int(ident))
    if rec is None:
        raise CommandError("There is no mate %s." % ident)
    out = run(ops.drive, ctx.doc, rec["id"], args.get("value"), args.get("values"), args.get("start"), args.get("end"), args.get("count"), args.get("max_step"), bool(args.get("commit", True)), bool(args.get("report", False)), args.get("components"))
    return {k: out[k] for k in ("ok", "message", "samples", "final", "moved", "ms", "iterations", "poses", "status") if k in out}


@command("matedrag", group="solids", label="Drag Component", description="Move a component toward a point along the motion its mates leave free.", menu="Assembly > Drag Component")
def matedrag(ctx):
    t = yield ctx.text("Enter the component name or id")
    if t.kind != "text":
        return
    cid = comp_ref(ctx, t.value)
    a = yield ctx.point("Specify the point on the component to grab")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify where to drag it", base=a.value)
    if b.kind != "point":
        return
    out = run(ops.drag, ctx.doc, cid, list(a.value) + [0.0] * (3 - len(a.value)), list(b.value) + [0.0] * (3 - len(b.value)), True)
    ctx.say(out["message"] or "Dragged %s in %.1f ms." % (cid, out["ms"]))


@executes("matedrag")
def matedrag_exec(ctx, args):
    cid = comp_ref(ctx, args.get("component"))
    if args.get("point") is None or args.get("target") is None:
        raise CommandError("Give point and target.")
    out = run(ops.drag, ctx.doc, cid, [float(v) for v in args["point"]], [float(v) for v in args["target"]], bool(args.get("commit", False)))
    return out


@command("explodeview", aliases=("asmexplode",), group="solids", label="Exploded View", description="Make exploded views from named steps; each step moves components along a direction by a distance.", menu="Assembly > Exploded View")
def explode_cmd(ctx):
    k = yield ctx.keyword("Exploded view [List/New/Delete/Active/Step/Auto]", ["List", "New", "Delete", "Active", "Step", "Auto"], "List")
    word = (k.value if k.kind == "keyword" else "").lower()
    if word == "list":
        for name, v in explode.listing(ctx.d)["views"].items():
            ctx.say("%s: %d step(s)" % (name, len(v["steps"])))
        return
    if word == "auto":
        s = run(explode.suggest, ctx.doc)
        for st in s["steps"]:
            ctx.say("%s: %s along %s by %g" % (st["name"], ", ".join(st["comps"]), st["dir"], st["dist"]))
        ctx.say("This is a suggestion; use EXPLODE with the Step option to keep it.")
        return
    n = yield ctx.text("Enter the view name")
    if n.kind != "text":
        return
    if word == "new":
        run(explode.new_view, ctx.d, n.value)
    elif word == "delete":
        run(explode.delete_view, ctx.d, n.value.strip())
    elif word == "active":
        run(explode.set_active, ctx.d, n.value.strip())
    else:
        c = yield ctx.text("Enter the component names or ids to move, separated by commas")
        if c.kind != "text":
            return
        dirw = yield ctx.word("Direction [X/-X/Y/-Y/Z/-Z]", ["X", "-X", "Y", "-Y", "Z", "-Z"], "Z")
        dist = yield ctx.distance("Distance", positive=True)
        if dirw.kind not in ("keyword", "text") or dist.kind != "number":
            return
        run(explode.add_step, ctx.d, n.value.strip(), {"comps": [comp_ref(ctx, x.strip()) for x in c.value.split(",") if x.strip()], "dir": str(dirw.value), "dist": float(dist.value)})


@executes("explodeview")
def explode_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    d = ctx.d
    name = str(args.get("view") or "")
    if action == "list":
        return explode.listing(d)
    if action == "new":
        return run(explode.new_view, d, name)
    if action == "delete":
        run(explode.delete_view, d, name)
        return {"deleted": name}
    if action == "active":
        run(explode.set_active, d, name)
        return {"active": name}
    if action in ("step", "addstep"):
        return run(explode.add_step, d, name, args.get("step") or args, args.get("index"))
    if action == "editstep":
        return run(explode.edit_step, d, name, int(args.get("id")), args.get("step") or args)
    if action in ("delstep", "removestep"):
        run(explode.remove_step, d, name, int(args.get("id")))
        return {"removed": int(args.get("id"))}
    if action == "movestep":
        return {"steps": run(explode.move_step, d, name, int(args.get("id")), int(args.get("index", 0)))}
    if action == "pose":
        return run(explode.pose, d, name or explode.views(d).get("active", ""), args.get("t"))
    if action == "auto":
        return run(explode.suggest, ctx.doc, args.get("save_as"))
    raise CommandError("action is list, new, delete, active, step, editstep, delstep, movestep, pose or auto.")


@command("interfere", aliases=("interference", "checkinterference"), group="solids", label="Interference Check", description="Find components whose solids overlap, with the overlapping volume, and list clearances below a distance.", menu="Assembly > Interference")
def interfere_cmd(ctx):
    c = yield ctx.number("Report clearances below this distance (0 for none)", default=0.0)
    if c.kind != "number":
        return
    out = run(interf.check, ctx.doc, float(c.value) or None)
    for r in out["interferences"]:
        ctx.say("%s and %s overlap by volume %g." % (r["label_a"], r["label_b"], r["volume"]))
    for r in out["clearances"]:
        if not r["contact"]:
            ctx.say("%s and %s are %g apart." % (r["label_a"], r["label_b"], r["distance"]))
    ctx.say("%d interference(s) among %d bodies in %.0f ms." % (out["count"], out["bodies"], out["ms"]))


@executes("interfere")
def interfere_exec(ctx, args):
    return run(interf.check, ctx.doc, args.get("clearance"), args.get("fuzzy"), args.get("min_volume"), None, args.get("ignore"))


@command("interferesweep", group="solids", label="Interference Over Motion", description="Drive a mate through a range and check for interference at every position.", menu="Assembly > Interference Over Motion")
def interferesweep_cmd(ctx):
    t = yield ctx.text("Enter the distance or angle mate name or id")
    if t.kind != "text":
        return
    rec = S.get(ctx.d, t.value.strip())
    if rec is None:
        raise CommandError("There is no mate %s." % t.value)
    a = yield ctx.number("Start value", default=0.0)
    b = yield ctx.number("End value", default=360.0)
    n = yield ctx.number("Number of positions", default=36, integer=True, positive=True)
    if a.kind != "number" or b.kind != "number" or n.kind != "number":
        return
    out = run(motion.interference_sweep, ctx.doc, rec["id"], float(a.value), float(b.value), int(n.value))
    ctx.say("%d position(s) checked, %d interference(s)." % (out["samples"], out["interference_total"]))


@executes("interferesweep")
def interferesweep_exec(ctx, args):
    ident = args.get("mate")
    rec = S.get(ctx.d, ident if not str(ident).isdigit() else int(ident))
    if rec is None:
        raise CommandError("There is no mate %s." % ident)
    return run(motion.interference_sweep, ctx.doc, rec["id"], float(args.get("start", 0.0)), float(args.get("end", 350.0)), int(args.get("count", 36)), args.get("clearance"), args.get("fuzzy"), args.get("max_step"), args.get("ignore"))


@command("matesettings", group="settings", label="Mate Settings", description="Set the interference tolerance, clearance threshold and smallest reported volume.", menu="Assembly > Mate Settings")
def matesettings(ctx):
    h = S.header(ctx.d)
    cur = h["settings"]
    f = yield ctx.number("Fuzzy tolerance for interference (0 uses the document tolerance)", default=cur.get("fuzzy", 0.0))
    if f.kind != "number":
        return
    c = yield ctx.number("Clearance threshold (0 for none)", default=cur.get("clearance", 0.0))
    if c.kind != "number":
        return
    h["settings"].update(fuzzy=float(f.value), clearance=float(c.value))
    S.save_header(ctx.d, h)
    ctx.say("Mate settings updated.")


@executes("matesettings")
def matesettings_exec(ctx, args):
    h = S.header(ctx.d)
    for key in ("fuzzy", "clearance", "min_volume"):
        if args.get(key) is not None:
            v = float(args[key])
            if v < 0:
                raise CommandError("%s cannot be negative." % key)
            h["settings"][key] = v
    S.save_header(ctx.d, h)
    return h["settings"]
