from app.cmd.commands import meshws, solids
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.gen import jobs as gen_jobs, run as gen_run
from app.meshes import core, store
from app.meshes.core import Mesh, MeshError
from app.param.units import mm_per_unit
from app.sim import records
from app.sim import study as sim_study
from app.sim.fem import SimError
from app.sim.records import SimRecordError
from app.solid.work import SolidError
from app.topo import jobs as tj, outcome as topo_outcome, surface
from app.topo.grid import Cancelled, TopoError

GROUP = "solids"
ERRORS = (TopoError, SimError, SimRecordError, SolidError, MeshError, KeyError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Cancelled as err:
        raise CommandError(str(err))
    except ERRORS as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def last_study(ctx) -> str:
    rows = [r for r in records.of_kind(ctx.d, "study") if r.get("type") == "generative"]
    if not rows:
        raise CommandError("The drawing has no generative study; create one with SIMSTUDY and the type generative.")
    return rows[-1]["id"]


def line(o: dict) -> str:
    return "%s: mass %.4g kg, safety factor %s, %s" % (o["label"], o["mass_kg"], ("%.3g" % o["safety_factor"]) if o["safety_factor"] else "n/a", "manufacturable" if o["manufacturable"] else "needs review")


def run_generative(ctx, args):
    sid = str(args.get("study") or last_study(ctx))
    restrict = tj.restricted(ctx.runner)
    overrides = {k: v for k, v in args.items() if k != "study"}
    parts = run(gen_run.compute, ctx.doc, sid, overrides, tj.Inline(restrict), restrict)
    out = run(gen_jobs.store, ctx.d, parts)
    for o in out["summary"]["outcomes"]:
        ctx.say("GENRUN: %s %s." % (o["id"], line(o)))
    return out


@command("genrun", aliases=("generate", "generativedesign"), group=GROUP, label="Generate Outcomes", description="Run a generative study: several manufacturable outcomes, each with its mass and safety factor.", menu="Simulate > Generate Outcomes")
def genrun_cmd(ctx):
    k = yield ctx.yesno("Run every method of the last generative study?", "Yes")
    if k.kind != "keyword" or k.value != "Yes":
        return
    return run_generative(ctx, {})


@executes("genrun")
def genrun_exec(ctx, args):
    return run_generative(ctx, args)


def flag(args, key, default):
    v = args.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def number(args, key, default, low, high):
    try:
        v = float(args.get(key, default))
    except (TypeError, ValueError):
        raise CommandError("%s must be a number." % key)
    if not (low <= v <= high):
        raise CommandError("%s must be between %g and %g." % (key, low, high))
    return v


def apply_outcome(ctx, args):
    sid = str(args.get("study") or last_study(ctx))
    row = run(records.need, ctx.d, sid, "study")
    rid = row.get("result")
    if not rid:
        raise CommandError("Study %s has no outcomes yet; run GENRUN first." % sid)
    res = records.get(ctx.d, rid, "result")
    oid = str(args.get("outcome") or "")
    found = [o for o in res["summary"].get("outcomes", []) if o["id"] == oid]
    if not found:
        names = ", ".join(o["id"] for o in res["summary"].get("outcomes", []))
        raise CommandError("Name the outcome to apply (%s)." % names)
    o = found[0]
    grid, arrays, _meta = run(gen_run.unpack, run(sim_study.get_blob, ctx.d, res["blob"]))
    to_solid = flag(args, "to_solid", False)
    unite = flag(args, "unite_preserve", False)
    restrict = tj.restricted(ctx.runner)
    limit = int(number(args, "max_triangles", 5000 if to_solid else 20000, 100, 50000 if restrict else 200000))
    v, t, level = run(topo_outcome.extract, grid, {"solid": arrays[oid + "_solid"]}, int(number(args, "smooth", 8, 0, 100)), number(args, "sigma", 0.6, 0.0, 2.0))
    before = len(t)
    v, t = run(topo_outcome.decimate, v, t, limit)
    m = Mesh(v, t)
    rep = core.report(m)
    name = str(args.get("name") or ("%s outcome %s" % (o["label"], oid)))
    source = {"op": "generative", "study": sid, "result": rid, "outcome": oid, "method": o["method"], "safety_factor": o["safety_factor"]}
    body = run(store.new_body, ctx.d, m, name, source, mm_per_unit(ctx.d))
    h = ctx.add(body)
    vol = surface.volume(m.v, m.t)
    rho = float(res["summary"]["material"]["rho_kg_mm3"])
    ctx.say("GENAPPLY: %s as a mesh of %d triangles (%d before reduction), %s, mass %.5g kg." % (oid, len(t), before, "closed" if rep["closed"] else "open", abs(vol) * rho))
    out = {"mesh": h, "outcome": oid, "triangles": int(len(t)), "closed": bool(rep["closed"]), "volume_mm3": abs(vol), "mass_kg": abs(vol) * rho, "safety_factor": o["safety_factor"]}
    if to_solid:
        solid = run(meshws.run_tobrep, ctx, [h], {"merge_planar": flag(args, "merge_planar", True), "tolerance": args.get("tolerance", 0.05 / mm_per_unit(ctx.d)), "name": name + " solid", "keep_mesh": flag(args, "keep_mesh", True)})
        out["solid"] = solid["handle"]
        out["solid_info"] = {k: solid[k] for k in ("faces", "valid", "closed", "solids", "volume", "relative_volume_error", "seconds")}
        if unite:
            regions = [int(r["body"]) for r in (row.get("options") or {}).get("preserve") or [] if isinstance(r, dict) and "body" in r]
            if regions:
                fused = run(solids.boolean_run, ctx, "fuse", [solid["handle"]], regions)
                out["united"] = fused
                ctx.say("GENAPPLY: united %s with %d exact preserve bodies." % (oid, len(regions)))
    return out


@command("genapply", aliases=("generativeapply",), group=GROUP, label="Outcome To Body", description="Turn one generative outcome into a mesh object and, if asked, a solid united with the exact preserve bodies.", menu="Simulate > Generative Outcome To Body")
def genapply_cmd(ctx):
    k = yield ctx.keyword("Outcome", ["O1", "O2", "O3", "O4"], "O1")
    if k.kind != "keyword":
        return
    return apply_outcome(ctx, {"outcome": k.value})


@executes("genapply")
def genapply_exec(ctx, args):
    return apply_outcome(ctx, args)
