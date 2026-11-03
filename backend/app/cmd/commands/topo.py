from app.cmd.commands import meshws
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.meshes import core, store
from app.meshes.core import Mesh, MeshError
from app.param.units import mm_per_unit
from app.sim import records
from app.sim import study as sim_study
from app.sim.fem import SimError
from app.sim.records import SimRecordError
from app.solid.work import SolidError
from app.topo import jobs, outcome, shape, surface
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


def last_topology(ctx) -> str:
    rows = [r for r in records.of_kind(ctx.d, "study") if r.get("type") == "topology"]
    if not rows:
        raise CommandError("The drawing has no topology study; create one with SIMSTUDY and the type topology.")
    return rows[-1]["id"]


def headline(s: dict) -> str:
    return "mass %.4g to %.4g kg (%.1f percent removed, target %.1f), peak stress %.4g to %.4g MPa (limit %s), %s" % (
        s["initial_mass_kg"], s["final_mass_kg"], s["reduction"] * 100, s["target_reduction"] * 100, s["peak_stress_before_mpa"], s["peak_stress_after_mpa"],
        ("%.4g MPa" % s["stress_limit_mpa"]) if s["stress_limit_mpa"] else "none", "target met" if s["met_target"] and s["met_stress"] else "target not met")


def run_topology(ctx, args):
    sid = str(args.get("study") or last_topology(ctx))
    restrict = jobs.restricted(ctx.runner)
    overrides = {k: v for k, v in args.items() if k not in ("study",)}
    parts = run(jobs.compute, ctx.doc, sid, overrides, jobs.Inline(restrict), restrict)
    out = run(jobs.store, ctx.d, parts)
    s = out["summary"]
    for note in s.get("notes", []):
        ctx.say("TOPORUN: %s" % note)
    ctx.say("TOPORUN: %s: %s." % (sid, headline(s)))
    return out


@command("toporun", aliases=("topology", "optimisetopology"), group=GROUP, label="Optimise Topology", description="Remove material from a topology study's design space while keeping its stiffness and checking the stress.", menu="Simulate > Optimise Topology")
def toporun_cmd(ctx):
    r = yield ctx.number("Share of the mass to remove (0.02 to 0.95)", default=0.5, minimum=0.02, maximum=0.95)
    if r.kind != "number":
        return
    return run_topology(ctx, {"reduction": float(r.value)})


@executes("toporun")
def toporun_exec(ctx, args):
    return run_topology(ctx, args)


def number(args, key, default, low, high):
    try:
        v = float(args.get(key, default))
    except (TypeError, ValueError):
        raise CommandError("%s must be a number." % key)
    if not (low <= v <= high):
        raise CommandError("%s must be between %g and %g." % (key, low, high))
    return v


def flag(args, key, default):
    v = args.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def apply_outcome(ctx, args):
    sid = str(args.get("study") or last_topology(ctx))
    study_row = run(records.need, ctx.d, sid, "study")
    rid = study_row.get("result")
    if not rid:
        raise CommandError("Study %s has no result yet; run TOPORUN first." % sid)
    res = records.get(ctx.d, rid, "result")
    grid, arrays, meta = run(outcome.unpack, run(sim_study.get_blob, ctx.d, res["blob"]))
    to_solid = flag(args, "to_solid", False)
    limit = int(number(args, "max_triangles", 5000 if to_solid else 20000, 100, 200000 if not jobs.restricted(ctx.runner) else 50000))
    smooth = int(number(args, "smooth", 8, 0, 100))
    sigma = number(args, "sigma", 0.6, 0.0, 2.0)
    v, t, surface_level = run(outcome.extract, grid, arrays, smooth, sigma)
    before = len(t)
    v, t = run(outcome.decimate, v, t, limit)
    m = Mesh(v, t)
    rep = core.report(m)
    scale = mm_per_unit(ctx.d)
    name = str(args.get("name") or ("Topology outcome " + sid))
    summary = meta["summary"]
    source = {"op": "topology", "study": sid, "result": rid, "reduction": summary["reduction"], "peak_stress_mpa": summary["peak_stress_after_mpa"]}
    body = run(store.new_body, ctx.d, m, name, source, scale)
    h = ctx.add(body)
    vol = surface.volume(m.v, m.t)
    rho = float(summary["material"]["rho_kg_mm3"])
    voxel_volume = float(arrays["solid"].sum()) * grid.h ** 3
    ctx.say("TOPOAPPLY: mesh of %d triangles (%d before reduction), %s, volume %.5g mm3 against %.5g mm3 of cells, mass %.5g kg." % (len(t), before, "closed" if rep["closed"] else "open", vol, voxel_volume, vol * rho))
    out = {"mesh": h, "triangles": int(len(t)), "closed": bool(rep["closed"]), "naked_edges": int(rep["naked_edges"]), "volume_mm3": vol, "cell_volume_mm3": voxel_volume, "mass_kg": vol * rho, "surface_level": surface_level, "study": sid, "result": rid}
    if to_solid:
        solid = run(meshws.run_tobrep, ctx, [h], {"merge_planar": flag(args, "merge_planar", True), "tolerance": args.get("tolerance", 0.05 / scale), "name": name + " solid", "keep_mesh": flag(args, "keep_mesh", True)})
        out["solid"] = solid["handle"]
        out["solid_info"] = {k: solid[k] for k in ("faces", "valid", "closed", "solids", "volume", "relative_volume_error", "seconds")}
    return out


@command("topoapply", aliases=("topologymesh",), group=GROUP, label="Topology Outcome To Body", description="Turn the stored topology outcome into a smooth mesh object and, if asked, a solid body.", menu="Simulate > Outcome To Body")
def topoapply_cmd(ctx):
    k = yield ctx.yesno("Also make a solid body (slower)?", "No")
    if k.kind != "keyword":
        return
    return apply_outcome(ctx, {"to_solid": k.value == "Yes"})


@executes("topoapply")
def topoapply_exec(ctx, args):
    return apply_outcome(ctx, args)


def apply_shape(ctx, args):
    rows = [r for r in records.of_kind(ctx.d, "study") if r.get("type") == "shape"]
    sid = str(args.get("study") or (rows[-1]["id"] if rows else ""))
    if not sid:
        raise CommandError("The drawing has no shape study; create one with SIMSTUDY and the type shape.")
    out = run(shape.apply_best, ctx, sid, args.get("values"))
    ctx.say("TOPOSHAPE: set %s." % ", ".join("%s to %.6g" % (k, v) for k, v in out["values"].items()))
    return out


@command("toposhape", aliases=("shapeapply",), group=GROUP, label="Apply Shape Result", description="Set the document parameters of a shape study to the best values its search found.", menu="Simulate > Apply Shape Result")
def toposhape_cmd(ctx):
    k = yield ctx.yesno("Apply the best values of the last shape study?", "Yes")
    if k.kind != "keyword" or k.value != "Yes":
        return
    return apply_shape(ctx, {})


@executes("toposhape")
def toposhape_exec(ctx, args):
    return apply_shape(ctx, args)
