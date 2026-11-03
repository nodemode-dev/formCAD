import os
import tempfile
import time

import numpy as np

from app.cmd.commands.meshes import GROUP, mesh_bodies, pick, replace, say_report
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc.entities import Polyline3d
from app.meshes import core, files as mesh_files, jobs, remesh, reduce as reducer, repair, section as sectioner, solidops, store
from app.meshes.core import Mesh, MeshError
from app.param.units import mm_per_unit
from app.solid import work
from app.solid.work import SolidError

PLANES = {"xy": (0.0, 0.0, 1.0), "yz": (1.0, 0.0, 0.0), "zx": (0.0, 1.0, 0.0)}


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except jobs.Cancelled as err:
        raise CommandError(str(err))
    except (MeshError, SolidError, ImportError) as err:
        raise CommandError(str(err))


def handles_of(args, key="handles", single="handle"):
    for name in (key, single):
        got = args.get(name)
        if got is None:
            continue
        try:
            return [int(h) for h in got] if isinstance(got, (list, tuple)) else [int(got)]
        except (TypeError, ValueError):
            raise CommandError("%s must be handles (whole numbers)." % name)
    return []


def need_meshes(ctx, handles):
    found = mesh_bodies(ctx, handles)
    if not found:
        raise CommandError("Give the handles of mesh objects.")
    for e in found:
        if e.points_only:
            raise CommandError("%s is a point cloud; this operation needs triangles." % (e.name or "A mesh"))
    return found


def flag(args, key, default):
    v = args.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def number(args, key, default, low=None, high=None, what=None):
    try:
        v = float(args.get(key, default))
    except (TypeError, ValueError):
        raise CommandError("%s must be a number." % (what or key))
    if v != v or v in (float("inf"), float("-inf")):
        raise CommandError("%s must be a finite number." % (what or key))
    if low is not None and v < low:
        raise CommandError("%s must be at least %g." % (what or key, low))
    if high is not None and v > high:
        raise CommandError("%s must be at most %g." % (what or key, high))
    return v


def compact_info(info: dict) -> dict:
    out = {}
    for k, v in info.items():
        if k == "pair_array":
            continue
        out[k] = v
    return out


@command("meshrepair", aliases=("repairmesh",), group=GROUP, label="Repair Mesh", description="Weld vertices, drop degenerate and duplicate triangles, make the normals agree, fill holes and report self-intersections.", menu="Modify > Mesh > Repair")
def meshrepair_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to repair")
    if not handles:
        return
    r = yield ctx.distance("Weld distance (0 to skip)", default=ctx.d.tolerances["absolute"], nonneg=True)
    if r.kind != "number":
        return
    run_repair(ctx, handles, {"weld": float(r.value)})


def run_repair(ctx, handles, args):
    weld = number(args, "weld", ctx.d.tolerances["absolute"], 0.0, what="The weld distance")
    fill = int(number(args, "fill_edges", 32, 0, core.MAX_FILL_EDGES, "The hole size"))
    if 0 < fill < 3:
        raise CommandError("A hole has at least 3 edges.")
    found = need_meshes(ctx, handles)
    unit = mm_per_unit(ctx.d)
    for e in found:
        guard(jobs.need_room, ctx.runner, "repair", int(e.summary.get("triangles", 0)), "Repairing")
    done = []
    with jobs.activity(ctx, "meshrepair") as act:
        for k, e in enumerate(found):
            m = guard(store.load, ctx.d, e)
            check = flag(args, "self_check", True) and len(m.t) <= jobs.cap(ctx.runner, "selfx")
            res, info = guard(repair.repair, m, weld * unit, flag(args, "degenerate", True), flag(args, "duplicates", True), flag(args, "unify", True), fill, check, flag(args, "resolve_intersections", False), act)
            if flag(args, "self_check", True) and not check:
                info["self_intersections"] = {"skipped": "the mesh has more than %d triangles" % jobs.cap(ctx.runner, "selfx")}
            done.append((e, res, info))
    out = []
    for e, res, info in done:
        t = replace(ctx, e, res, "repair", {"steps": info["steps"]})
        b, a = info["before"], info["after"]
        ctx.say("MESHREPAIR: %d to %d triangles, naked edges %d to %d, %s." % (b["triangles"], a["triangles"], b["naked_edges"], a["naked_edges"], "closed" if a["closed"] else "still open"))
        sx = info.get("self_intersections")
        if sx and "pairs" in sx:
            ctx.say("MESHREPAIR: %d self-intersecting triangle pairs%s." % (sx["pairs"], " (list capped)" if sx.get("capped") else ""))
        out.append({"handle": t.handle, **info})
    return {"results": out}


@executes("meshrepair")
def meshrepair_exec(ctx, args):
    return run_repair(ctx, handles_of(args), args)


@command("meshselfx", aliases=("meshintersections",), group=GROUP, label="Mesh Self-Intersections", description="Find the pairs of triangles that cut through each other.", menu="Tools > Inquiry > Mesh Self-Intersections", undoable=False)
def meshselfx_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to check")
    if handles:
        run_selfx(ctx, handles, {})


def run_selfx(ctx, handles, args):
    found = mesh_bodies(ctx, handles, False)
    if not found:
        raise CommandError("Give the handles of mesh objects.")
    maxp = int(number(args, "max_pairs", 1000, 1, jobs.SELFX_MAX_PAIRS, "max_pairs"))
    out = []
    with jobs.activity(ctx, "meshselfx") as act:
        for e in found:
            guard(jobs.need_room, ctx.runner, "selfx", int(e.summary.get("triangles", 0)), "The self-intersection check")
            res = guard(repair.self_intersections, guard(store.load, ctx.d, e), maxp, act)
            ctx.say("%s: %d self-intersecting triangle pairs involving %d triangles." % (e.name or "Mesh", res["pairs"], res["triangles_involved"]))
            out.append({"handle": e.handle, **{k: v for k, v in compact_info(res).items() if k != "points"}})
    return {"results": out}


@executes("meshselfx")
def meshselfx_exec(ctx, args):
    return run_selfx(ctx, handles_of(args), args)


@command("meshreduce", aliases=("meshdecimate",), group=GROUP, label="Reduce Mesh", description="Cut the triangle count by a proportion, to a count, or as far as a tolerance allows.", menu="Modify > Mesh > Reduce")
def meshreduce_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to reduce")
    if not handles:
        return
    k = yield ctx.keyword("Reduce by", ["Proportion", "Count", "Tolerance"], "Proportion")
    if k.kind != "keyword":
        return
    mode = str(k.value).lower()
    if mode == "proportion":
        v = yield ctx.number("Share of triangles to keep (0 to 1)", default=0.5, positive=True)
    elif mode == "count":
        v = yield ctx.number("Target number of triangles", default=5000, integer=True, positive=True)
    else:
        v = yield ctx.distance("Largest deviation", default=ctx.d.tolerances["absolute"] * 50, positive=True)
    if v.kind != "number":
        return
    run_reduce(ctx, handles, {"mode": mode, "value": float(v.value)})


def run_reduce(ctx, handles, args):
    mode = str(args.get("mode", "proportion")).lower()
    if mode not in reducer.MODES:
        raise CommandError("The mode is proportion, count or tolerance.")
    value = number(args, "value", 0.5, what="The value")
    unit = mm_per_unit(ctx.d)
    if mode == "tolerance":
        value = value * unit
    lock = flag(args, "lock_boundary", True)
    found = need_meshes(ctx, handles)
    for e in found:
        guard(jobs.need_room, ctx.runner, "reduce", int(e.summary.get("triangles", 0)), "Reducing")
    done = []
    with jobs.activity(ctx, "meshreduce") as act:
        for e in found:
            res, info = guard(reducer.reduce, guard(store.load, ctx.d, e), mode, value, lock, act)
            done.append((e, res, info))
    out = []
    for e, res, info in done:
        t = replace(ctx, e, res, "reduce", info)
        ctx.say("MESHREDUCE: %d to %d triangles, largest deviation %s, rms %s." % (info["before"], info["after"], ctx.fd(info["deviation_max"] / unit), ctx.fd(info["deviation_rms"] / unit)))
        out.append({"handle": t.handle, **info, "deviation_max": info["deviation_max"] / unit, "deviation_rms": info["deviation_rms"] / unit})
    return {"results": out}


@executes("meshreduce")
def meshreduce_exec(ctx, args):
    return run_reduce(ctx, handles_of(args), args)


@command("meshremesh", group=GROUP, label="Remesh", description="Rebuild a mesh with triangles of an even target edge length, keeping sharp edges and boundaries.", menu="Modify > Mesh > Remesh")
def meshremesh_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to remesh")
    if not handles:
        return
    r = yield ctx.distance("Target edge length", default=1.0, positive=True)
    if r.kind != "number":
        return
    run_remesh(ctx, handles, {"edge_length": float(r.value)})


def run_remesh(ctx, handles, args):
    unit = mm_per_unit(ctx.d)
    length = number(args, "edge_length", 1.0, what="The edge length")
    if not length > 0:
        raise CommandError("The edge length must be positive.")
    iterations = int(number(args, "iterations", 5, 1, remesh.MAX_ITERATIONS, "iterations"))
    feature = number(args, "feature_angle", 30.0, 0.0, 180.0, "feature_angle")
    lock = flag(args, "lock_boundary", True)
    found = need_meshes(ctx, handles)
    for e in found:
        guard(jobs.need_room, ctx.runner, "remesh", int(e.summary.get("triangles", 0)), "Remeshing")
    done = []
    with jobs.activity(ctx, "meshremesh") as act:
        for e in found:
            res, info = guard(remesh.remesh, guard(store.load, ctx.d, e), length * unit, iterations, feature, lock, act)
            done.append((e, res, info))
    out = []
    for e, res, info in done:
        t = replace(ctx, e, res, "remesh", info)
        ctx.say("MESHREMESH: %d to %d triangles, mean edge %s, largest deviation %s." % (info["before"], info["after"], ctx.fd(info["edge_mean"] / unit), ctx.fd(info["deviation_max"] / unit)))
        scaled = {k: (v / unit if k.startswith(("edge_", "deviation")) else v) for k, v in info.items()}
        out.append({"handle": t.handle, **scaled})
    return {"results": out}


@executes("meshremesh")
def meshremesh_exec(ctx, args):
    return run_remesh(ctx, handles_of(args), args)


@command("meshsection", aliases=("meshslice",), group=GROUP, label="Mesh Section", description="Cut meshes with a plane and draw the cut as 3D polylines.", menu="Modify > Mesh > Section")
def meshsection_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to cut")
    if not handles:
        return
    p = yield ctx.point("Specify a point on the cutting plane")
    if p.kind != "point":
        return
    k = yield ctx.keyword("Plane normal", ["X", "Y", "Z"], "Z")
    if k.kind != "keyword":
        return
    normal = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[str(k.value).lower()]
    pt = list(p.value) + [0.0] * (3 - len(p.value))
    run_section(ctx, handles, {"origin": pt[:3], "normal": list(normal)})


def plane_of(ctx, args):
    unit = mm_per_unit(ctx.d)
    if args.get("normal") is not None:
        normal = [float(c) for c in args["normal"]]
        if len(normal) != 3:
            raise CommandError("Give the normal as three numbers.")
        origin = [float(c) for c in (args.get("origin") or [0, 0, 0])]
        if len(origin) == 2:
            origin.append(0.0)
        if len(origin) != 3:
            raise CommandError("Give the origin as three numbers.")
        return origin, normal
    name = str(args.get("plane", "")).lower()
    if name not in PLANES:
        raise CommandError("Give a plane (xy, yz or zx) with an offset, or an origin and a normal.")
    n = PLANES[name]
    off = number(args, "offset", 0.0, what="The offset")
    return [n[0] * off, n[1] * off, n[2] * off], list(n)


def run_section(ctx, handles, args):
    origin, normal = plane_of(ctx, args)
    if not all(np.isfinite(origin + normal)) or not any(abs(c) > 1e-12 for c in normal):
        raise CommandError("The section plane needs a finite origin and a normal that is not zero.")
    unit = mm_per_unit(ctx.d)
    found = need_meshes(ctx, handles)
    for e in found:
        guard(jobs.need_room, ctx.runner, "section", int(e.summary.get("triangles", 0)), "Sectioning")
    only_closed = flag(args, "closed_only", False)
    made, loops, chains = [], 0, 0
    pieces = []
    with jobs.activity(ctx, "meshsection") as act:
        for e in found:
            act.step("Cutting %s" % (e.name or "mesh"), 0.3)
            m = guard(store.load, ctx.d, e)
            off = np.array(e.offset, dtype=np.float64) * unit
            lines, route = guard(sectioner.section, m, np.array(origin) * unit - off, np.array(normal))
            for ln in lines:
                if only_closed and not ln["closed"]:
                    continue
                pieces.append((e, ln, off))
    for e, ln, off in pieces:
        pts = (ln["points"] + off) / unit
        ent = Polyline3d(points=[[float(c) for c in p] for p in pts], closed=bool(ln["closed"]))
        ent.layer = e.layer
        h = ctx.add(ent)
        ent.layer = e.layer
        made.append(h)
        loops += 1 if ln["closed"] else 0
        chains += 0 if ln["closed"] else 1
    if not made:
        ctx.say("MESHSECTION: the plane does not cut the mesh.")
    else:
        ctx.say("MESHSECTION: %d closed curves and %d open curves." % (loops, chains))
    return {"curves": made, "loops": loops, "chains": chains}


@executes("meshsection")
def meshsection_exec(ctx, args):
    return run_section(ctx, handles_of(args), args)


def boolean_names(found):
    return [(e.name or "mesh") for e in found]


@command("meshboolean", group=GROUP, label="Mesh Boolean", description="Union, difference or intersection of closed meshes, with a manifold result.", menu="Modify > Mesh > Boolean")
def meshboolean_cmd(ctx):
    k = yield ctx.keyword("Operation", ["Union", "Difference", "Intersection"], "Union")
    if k.kind != "keyword":
        return
    base = yield from pick(ctx, "Select the base mesh")
    if not base:
        return
    tools = yield from pick(ctx, "Select the tool meshes")
    if not tools:
        return
    run_boolean(ctx, str(k.value).lower(), base[:1], tools, {})


def make_boolean_alias(name, op, label, description):
    @command(name, group=GROUP, label=label, description=description, menu="Modify > Mesh > " + label)
    def cmd(ctx):
        base = yield from pick(ctx, "Select the base mesh")
        if not base:
            return
        tools = yield from pick(ctx, "Select the tool meshes")
        if not tools:
            return
        run_boolean(ctx, op, base[:1], tools, {})

    @executes(name)
    def exe(ctx, args):
        return run_boolean(ctx, op, handles_of(args, "base", "base"), handles_of(args, "tools", "tool"), args)

    return cmd


make_boolean_alias("meshunion", "union", "Mesh Union", "Join closed meshes into one.")
make_boolean_alias("meshsubtract", "difference", "Mesh Subtract", "Cut the tool meshes out of the base mesh.")
make_boolean_alias("meshintersect", "intersection", "Mesh Intersect", "Keep only the volume common to the meshes.")


def run_boolean(ctx, op, base_handles, tool_handles, args):
    if op not in solidops.OPS:
        raise CommandError("The operation is union, difference or intersection.")
    base_list = need_meshes(ctx, base_handles)
    if len(base_list) != 1:
        raise CommandError("Give one base mesh.")
    base = base_list[0]
    tools = [t for t in need_meshes(ctx, tool_handles) if t.handle != base.handle]
    if not tools:
        raise CommandError("Give at least one tool mesh other than the base.")
    unit = mm_per_unit(ctx.d)
    total = int(base.summary.get("triangles", 0)) + sum(int(t.summary.get("triangles", 0)) for t in tools)
    guard(jobs.need_room, ctx.runner, "boolean", total, "The boolean")
    bo = np.array(base.offset, dtype=np.float64)
    with jobs.activity(ctx, "meshboolean") as act:
        bm = guard(store.load, ctx.d, base)
        tm = []
        for t in tools:
            lm = guard(store.load, ctx.d, t)
            tm.append(Mesh(lm.v + (np.array(t.offset, dtype=np.float64) - bo) * unit, lm.t))
        res, info = guard(solidops.combine, bm, tm, op, [base.name or "the base mesh"] + [t.name or "a tool mesh" for t in tools], act)
    target = replace(ctx, base, res, "boolean", {"op": op, "tools": [t.name for t in tools], "volume": info["volume"]})
    if not flag(args, "keep_inputs", False):
        for t in tools:
            ctx.d.erase_entity(t.handle)
    ctx.say("MESH%s: %d triangles, volume %s." % (op.upper(), info["triangles"], ctx.fd(info["volume"] / unit**3)))
    say_report(ctx, "MESHBOOLEAN", target.summary)
    return {"handle": target.handle, "op": op, "triangles": info["triangles"], "volume": info["volume"] / unit**3}


@executes("meshboolean")
def meshboolean_exec(ctx, args):
    return run_boolean(ctx, str(args.get("op", "")).lower(), handles_of(args, "base", "base"), handles_of(args, "tools", "tool"), args)


@command("meshtobrep", aliases=("meshtosolid",), group=GROUP, label="Mesh To Solid", description="Convert a mesh to a B-rep body by sewing its triangles, merging flat and round regions when asked.", menu="Modify > Mesh > Convert To Solid")
def meshtobrep_cmd(ctx):
    handles = yield from pick(ctx, "Select a mesh to convert")
    if not handles:
        return
    r = yield ctx.yesno("Merge flat regions into single faces", "Yes")
    if r.kind != "keyword":
        return
    c = yield ctx.yesno("Merge round regions into cylinders", "No")
    if c.kind != "keyword":
        return
    run_tobrep(ctx, handles[:1], {"merge_planar": r.value == "Yes", "merge_cylinders": c.value == "Yes"})


def run_tobrep(ctx, handles, args):
    found = need_meshes(ctx, handles)
    if len(found) != 1:
        raise CommandError("Give one mesh to convert.")
    e = found[0]
    n = int(e.summary.get("triangles", 0))
    cap = jobs.cap(ctx.runner, "tobrep")
    if n > cap:
        who = " from a macro or an outside agent" if jobs.restricted(ctx.runner) else ""
        raise CommandError("A mesh with more than %d triangles cannot be converted to a solid%s; this one has %d. Reduce it first." % (cap, who, n))
    if n > jobs.BREP_INTERACTIVE and jobs.restricted(ctx.runner) and not flag(args, "confirm_large", False):
        raise CommandError("Converting %d triangles takes a while; pass confirm_large to go on." % n)
    unit = mm_per_unit(ctx.d)
    tol = number(args, "tolerance", 0.001 / unit, 1e-9, what="The tolerance") * unit
    merge_planar = flag(args, "merge_planar", True)
    merge_cyl = flag(args, "merge_cylinders", False)
    if not e.summary.get("closed"):
        ctx.say("MESHTOBREP: the mesh is open (%d naked edges); the result will be an open surface, not a solid." % int(e.summary.get("naked_edges", 0)))
    began = time.time()
    with jobs.activity(ctx, "meshtobrep") as act:
        act.step("Preparing the mesh", 0.05)
        wm = guard(mesh_files.body_mesh, ctx.d, e)
        with tempfile.TemporaryDirectory(prefix="fcmesh_") as tmp:
            path = os.path.join(tmp, "in.fcm")
            with open(path, "wb") as fh:
                fh.write(store.pack(wm))
            act.step("Building the B-rep in the kernel", 0.2)
            params = {"path": path, "tolerance": tol, "merge_planar": merge_planar, "merge_cylinders": merge_cyl, "angle": number(args, "angle", 12.0, 0.5, 60.0, "angle")}
            res = guard(work.kcall, "mesh_to_brep", params, 900.0)
        act.step("Storing the body", 0.9)
    if not res["summary"].get("valid"):
        try:
            work.kcall("shape_free", {"ids": [res["id"]]}, 10.0)
        except SolidError:
            pass
        rep = res.get("report", {})
        raise CommandError("The mesh does not make a valid body (%d free edges, %d non-manifold edges in the mesh). Repair it first with MESHREPAIR." % (int(rep.get("free_edges", 0)), int(e.summary.get("nonmanifold_edges", 0))))
    name = str(args.get("name") or ((e.name or "mesh") + " solid"))
    body = work.new_body(ctx.d, res["id"], res["summary"], name, {"op": "meshtobrep", "from": e.name, "merge_planar": merge_planar, "merge_cylinders": merge_cyl})
    body.rgb = list(e.rgb or [])
    body.layer = e.layer
    h = ctx.add(body)
    rep = res.get("report", {})
    mv = e.summary.get("volume")
    bv = rep.get("volume")
    rel = abs(bv - mv) / abs(mv) if (mv and bv is not None) else None
    seconds = time.time() - began
    if not flag(args, "keep_mesh", True):
        ctx.d.erase_entity(e.handle)
    ctx.say("MESHTOBREP: %d triangles to %d faces (%d flat merged, %d round), %s, %d free edges, volume %s, %.1f s." % (n, int(res["summary"].get("faces", 0)), int(rep.get("planar_faces", 0)), int(rep.get("cylinder_faces", 0)), "valid solid" if (res["summary"].get("valid") and res["summary"].get("solids")) else "open or invalid", int(rep.get("free_edges", 0)), ctx.fd(bv / unit**3) if bv is not None else "none", seconds))
    return {"handle": h, "faces": int(res["summary"].get("faces", 0)), "planar_merged": int(rep.get("planar_faces", 0)), "cylinders": int(rep.get("cylinder_faces", 0)), "valid": bool(res["summary"].get("valid")), "closed": bool(res["summary"].get("closed")), "solids": int(res["summary"].get("solids", 0)), "free_edges": int(rep.get("free_edges", 0)), "volume": (bv / unit**3) if bv is not None else None, "mesh_volume": (mv / unit**3) if mv is not None else None, "relative_volume_error": rel, "seconds": round(seconds, 2), "report": rep}


@executes("meshtobrep")
def meshtobrep_exec(ctx, args):
    return run_tobrep(ctx, handles_of(args), args)
