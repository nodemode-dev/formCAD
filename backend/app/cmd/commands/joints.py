from app.cmd import barred
from app.cmd.commands.mates import parse_ref
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.joints import contact, dyn, jobs, ops, study
from app.joints import store as J
from app.mates import joint_eq
from app.mates import store as S
from app.solid.work import SolidError

FAILURES = (S.MateRefused, J.MotionError, jobs.JobError, joint_eq.JointError, SolidError, ValueError, KeyError)
TYPE_WORDS = ["Revolute", "Slider", "Cylindrical", "Pinslot", "Planar", "Ball", "Rigid"]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except S.MateRefused as err:
        raise CommandError(err.message)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def restricted(ctx) -> bool:
    return bool(barred.caller(ctx.runner))


def ref_of(value):
    if isinstance(value, dict):
        return value
    return parse_ref(value)


def say_status(ctx, st):
    ctx.say("State %s, %d degree(s) of freedom." % (st["state"], st["dof"]))


@command("joint", aliases=("addjoint",), group="solids", label="Joint", description="Join two components with a joint: rigid, revolute, slider, cylindrical, pin-slot, planar or ball. A joint keeps only the motion its type allows.", menu="Assembly > Joint")
def joint_cmd(ctx):
    k = yield ctx.keyword("Joint type [%s]" % "/".join(TYPE_WORDS), TYPE_WORDS, "Revolute")
    if k.kind != "keyword":
        return
    r1 = yield ctx.text("Enter the first reference (like C1:f2, C1:z or C1:e0)")
    if r1.kind != "text":
        return
    r2 = yield ctx.text("Enter the second reference")
    if r2.kind != "text":
        return
    ab = yield ctx.yesno("Are the components already in place (as-built)", "Yes")
    if ab.kind != "keyword":
        return
    out = run(ops.add_joint, ctx.doc, k.value, parse_ref(r1.value), parse_ref(r2.value), ab.value == "Yes")
    ctx.say("%s added. %s" % (out["joint"]["name"], "Moved %s." % ", ".join(out["moved"]) if out["moved"] else "Nothing moved."))
    say_status(ctx, out["status"])
    return {"id": out["joint"]["id"]}


@executes("joint")
def joint_exec(ctx, args):
    if not args.get("type"):
        raise CommandError("Give type.")
    out = run(ops.add_joint, ctx.doc, str(args["type"]), ref_of(args.get("a")), ref_of(args.get("b")), bool(args.get("as_built", False)), args.get("limits"), str(args.get("label") or ""))
    return {"id": out["joint"]["id"], "name": out["joint"]["name"], "joint": out["joint"], "moved": out["moved"], "poses": out["poses"], "status": out["status"], "message": "%s added; %d degree(s) of freedom left." % (out["joint"]["name"], out["status"]["dof"])}


def joint_key(ident):
    return int(ident) if str(ident).isdigit() else str(ident)


@command("jointedit", group="solids", label="Edit Joint", description="Change the label, limits or suppression of a joint.", menu="Assembly > Edit Joint")
def jointedit(ctx):
    t = yield ctx.text("Enter the joint name or id")
    if t.kind != "text":
        return
    s = yield ctx.yesno("Suppress this joint", "No")
    if s.kind != "keyword":
        return
    out = run(ops.set_joint, ctx.doc, joint_key(t.value.strip()), None, s.value == "Yes")
    ctx.say("%s updated." % out["joint"]["name"])


@executes("jointedit")
def jointedit_exec(ctx, args):
    out = run(ops.set_joint, ctx.doc, joint_key(args.get("joint")), args.get("label"), args.get("suppressed"), args.get("limits"))
    return {"joint": out["joint"], "moved": out["moved"], "poses": out["poses"], "status": out["status"]}


@command("jointdelete", aliases=("deljoint",), group="solids", label="Delete Joint", description="Remove a joint and the motion links that use it.", menu="Assembly > Delete Joint")
def jointdelete(ctx):
    t = yield ctx.text("Enter the joint name or id")
    if t.kind != "text":
        return
    out = run(ops.remove_joint, ctx.doc, joint_key(t.value.strip()))
    ctx.say("Removed %d item(s)." % len(out["removed"]))


@executes("jointdelete")
def jointdelete_exec(ctx, args):
    return run(ops.remove_joint, ctx.doc, joint_key(args.get("joint")))


@command("jointdrive", aliases=("drivejoint",), group="solids", label="Drive Joint", description="Move a joint coordinate to a value and carry the mechanism along; stops at the joint limits.", menu="Assembly > Drive Joint")
def jointdrive(ctx):
    t = yield ctx.text("Enter the joint name or id")
    if t.kind != "text":
        return
    c = yield ctx.text("Enter the coordinate (rz, tz, tx, ty, rx, ry)", "rz")
    if c.kind != "text":
        return
    v = yield ctx.number("Value to drive to (degrees or length)", default=0.0)
    if v.kind != "number":
        return
    out = run(ops.drive_joint, ctx.doc, joint_key(t.value.strip()), c.value.strip(), float(v.value))
    ctx.say("Driven to %g in %.1f ms." % (out["final"], out["ms"]))
    if out["message"]:
        ctx.say(out["message"])


@executes("jointdrive")
def jointdrive_exec(ctx, args):
    out = run(ops.drive_joint, ctx.doc, joint_key(args.get("joint")), str(args.get("coord") or ""), args.get("value"), args.get("values"), args.get("start"), args.get("end"), args.get("count"), args.get("max_step"), bool(args.get("commit", True)), bool(args.get("report", False)), args.get("components"))
    return {k: out[k] for k in ("ok", "message", "samples", "final", "moved", "ms", "poses", "joint", "status") if k in out}


@command("jointlink", group="solids", label="Joint Link", description="Tie one joint coordinate to another by a ratio, so driving one moves the other.", menu="Assembly > Joint Link")
def jointlink(ctx):
    a = yield ctx.text("Enter the first joint and coordinate (like M1:rz)")
    if a.kind != "text":
        return
    b = yield ctx.text("Enter the second joint and coordinate (like M2:tz)")
    if b.kind != "text":
        return
    r = yield ctx.number("Ratio (second per first, in degrees or length)", default=1.0)
    if r.kind != "number":
        return
    out = run(ops.add_link, ctx.doc, pair_of(a.value), pair_of(b.value), float(r.value))
    ctx.say("%s added." % out["link"]["name"])


def pair_of(text):
    if isinstance(text, dict):
        return text
    joint, _, coord = str(text).partition(":")
    if not coord:
        raise CommandError("Write a joint and coordinate like M1:rz.")
    return {"joint": joint_key(joint.strip()), "coord": coord.strip()}


@executes("jointlink")
def jointlink_exec(ctx, args):
    if args.get("link") is not None:
        out = run(ops.set_link, ctx.doc, joint_key(args["link"]), args.get("ratio"), args.get("reverse"), args.get("label"), args.get("suppressed"))
        return {"link": out["link"], "moved": out["moved"], "poses": out["poses"], "status": out["status"]}
    out = run(ops.add_link, ctx.doc, pair_of(args.get("first")), pair_of(args.get("second")), args.get("ratio"), bool(args.get("reverse", False)), str(args.get("label") or ""))
    return {"id": out["link"]["id"], "link": out["link"], "status": out["status"]}


@command("jointlinkdelete", group="solids", label="Delete Joint Link", description="Remove a joint link.", menu="Assembly > Delete Joint Link")
def jointlinkdelete(ctx):
    t = yield ctx.text("Enter the motion link name or id")
    if t.kind != "text":
        return
    run(ops.remove_link, ctx.doc, joint_key(t.value.strip()))
    ctx.say("Removed.")


@executes("jointlinkdelete")
def jointlinkdelete_exec(ctx, args):
    return run(ops.remove_link, ctx.doc, joint_key(args.get("link")))


@command("motionstudy", aliases=("motion",), group="solids", label="Motion Study", description="Make a motion study of keyed joint values over time, run it, and put the mechanism at a moment of the result.", menu="Assembly > Motion Study")
def motionstudy_cmd(ctx):
    k = yield ctx.keyword("Motion study [List/New/Delete/Run]", ["List", "New", "Delete", "Run"], "List")
    word = (k.value if k.kind == "keyword" else "").lower()
    if word == "list":
        for s in run(study.listing, ctx.d)["studies"]:
            ctx.say("%s %s: %g s, %d track(s)" % (s["id"], s["name"], s["duration"], len(s["tracks"])))
        return
    n = yield ctx.text("Enter the study name or id")
    if n.kind != "text":
        return
    caps = J.limits(restricted(ctx))
    if word == "new":
        rec = run(study.new_study, ctx.d, n.value.strip(), None, None, caps)
        ctx.say("%s made." % rec["id"])
    elif word == "delete":
        run(study.delete_study, ctx.d, n.value.strip())
    elif word == "run":
        res = start_study(ctx, n.value.strip(), True)
        ctx.say(res["message"])


def start_study(ctx, sid, wait, mode=None, frames=None):
    flag = restricted(ctx)
    try:
        job = jobs.start(ctx.doc, "study", sid, lambda doc: study.prepare(doc, sid, flag, mode, frames), wait)
    except FAILURES as err:
        raise CommandError(str(err))
    out = job.view()
    out["message"] = job.message
    return out


@executes("motionstudy")
def motionstudy_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    d = ctx.d
    caps = J.limits(restricted(ctx))
    sid = args.get("study")
    if action == "list":
        return run(study.listing, d)
    if action == "new":
        return {"study": run(study.new_study, d, args.get("name") or args.get("label"), args.get("duration"), args.get("fps"), caps)}
    if action == "edit":
        fields = {k: args[k] for k in ("name", "duration", "fps", "tracks", "contact", "plots") if k in args}
        return {"study": run(study.edit_study, d, sid, fields, caps)}
    if action == "delete":
        return run(study.delete_study, d, sid)
    if action == "run":
        out = start_study(ctx, str(sid), True, args.get("contact"), args.get("frames"))
        return out
    if action == "apply":
        job = jobs.get(str(args.get("job") or ""))
        if job is None or job.doc_id != ctx.doc.id:
            raise CommandError("Give job, the id of a finished run on this document.")
        return run(study.apply, ctx.doc, job, float(args.get("t", 0.0)))
    if action == "frames":
        job = jobs.get(str(args.get("job") or ""))
        if job is None or job.doc_id != ctx.doc.id:
            raise CommandError("Give job, the id of a run on this document.")
        return study.frames_view(job, args.get("from", 0), args.get("count", 200))
    raise CommandError("action is list, new, edit, delete, run, apply or frames.")


@command("contactset", group="solids", label="Contact Set", description="Choose which component pairs stop a motion study or collide in a dynamics run.", menu="Assembly > Contact Set")
def contactset_cmd(ctx):
    k = yield ctx.keyword("Contact set [List/New/Delete]", ["List", "New", "Delete"], "List")
    word = (k.value if k.kind == "keyword" else "").lower()
    if word == "list":
        for c in J.load(ctx.d)["contacts"].values():
            ctx.say("%s %s: %s" % (c["id"], c["name"], "all pairs" if c["all"] else "%d pair(s)" % len(c["pairs"])))
        return
    if word == "delete":
        n = yield ctx.text("Enter the contact set name or id")
        if n.kind == "text":
            run(contact.delete_set, ctx.d, n.value.strip())
        return
    a = yield ctx.yesno("Check every pair of components", "No")
    if a.kind != "keyword":
        return
    pairs = []
    if a.value == "No":
        p = yield ctx.text("Enter the pairs like C4-C5, separated by commas")
        if p.kind != "text":
            return
        pairs = [x.strip().upper().split("-") for x in p.value.split(",") if x.strip()]
    rec = run(contact.new_set, ctx.d, None, a.value == "Yes", pairs, None, J.limits(restricted(ctx)))
    ctx.say("%s made." % rec["id"])


@executes("contactset")
def contactset_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    caps = J.limits(restricted(ctx))
    kid = args.get("contact")
    if action == "list":
        return {"contacts": [contact.view(c) for c in J.load(ctx.d)["contacts"].values()]}
    if action == "new":
        return {"contact": contact.view(run(contact.new_set, ctx.d, args.get("name") or args.get("label"), bool(args.get("all", False)), args.get("pairs"), args.get("touch"), caps))}
    if action == "edit":
        return {"contact": contact.view(run(contact.edit_set, ctx.d, kid, args.get("name") or args.get("label"), args.get("all"), args.get("pairs"), args.get("touch"), caps))}
    if action == "delete":
        return run(contact.delete_set, ctx.d, kid)
    raise CommandError("action is list, new, edit or delete.")


@command("dynamics", aliases=("simulate",), group="solids", label="Dynamics Run", description="Simulate the assembly with gravity, joint limits, drives and contacts, and report the result.", menu="Assembly > Dynamics Run")
def dynamics_cmd(ctx):
    d = yield ctx.number("Duration in seconds", default=1.0, positive=True)
    if d.kind != "number":
        return
    out = start_dynamics(ctx, {"duration": float(d.value)}, True)
    ctx.say(out["message"])


def start_dynamics(ctx, spec, wait):
    flag = restricted(ctx)
    try:
        job = jobs.start(ctx.doc, "dynamics", str(spec.get("study") or ""), lambda doc: dyn.prepare(doc, spec, flag), wait)
    except FAILURES as err:
        raise CommandError(str(err))
    out = job.view()
    out["message"] = job.message
    return out


@executes("dynamics")
def dynamics_exec(ctx, args):
    spec = {k: args[k] for k in ("study", "duration", "timestep", "record_fps", "free", "contacts", "stop_on_contact") if k in args}
    if "duration" not in spec:
        raise CommandError("Give duration in seconds.")
    return start_dynamics(ctx, spec, bool(args.get("wait", True)))


@command("motionsettings", group="settings", label="Motion Settings", description="Set gravity, default density, servo stiffness, loop softness, time step and friction for dynamics runs.", menu="Assembly > Motion Settings")
def motionsettings_cmd(ctx):
    g = yield ctx.number("Gravity along z in metres per second squared", default=-9.81)
    if g.kind != "number":
        return
    run(J.apply_settings, ctx.d, {"gravity": [0.0, 0.0, float(g.value)]})
    ctx.say("Gravity set.")


@executes("motionsettings")
def motionsettings_exec(ctx, args):
    return {"dynamics": run(J.apply_settings, ctx.d, args)}
