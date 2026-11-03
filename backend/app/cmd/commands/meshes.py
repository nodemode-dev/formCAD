from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.meshes import core, files as mesh_files, store
from app.meshes.core import MeshError
from app.param.units import mm_per_unit
from app.solid.work import SolidError

GROUP = "solids"


def mesh_bodies(ctx, handles, need_edit=True):
    out = []
    for h in handles:
        e = ctx.d.get(int(h))
        if e is not None and e.kind == "meshbody" and not e.points_only and not (need_edit and ctx.locked(e)):
            out.append(e)
    return out


def pick(ctx, message):
    sel = yield ctx.select(message)
    if sel.kind != "selection":
        return None
    return [int(h) for h in sel.value]


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (MeshError, SolidError) as err:
        raise CommandError(str(err))


def replace(ctx, ent, m, op, info):
    target = ctx.d.modify(ent.handle)
    source = dict(ent.source or {})
    source.update({"op": op, "info": info})
    guard(store.fill_body, ctx.d, target, m, source, mm_per_unit(ctx.d))
    return target


def say_report(ctx, label, s):
    ctx.say("%s: %d triangles, %d vertices, %d naked edges in %d loops, %d non-manifold edges, %s." % (label, s["triangles"], s["vertices"], s["naked_edges"], s["naked_loops"], s["nonmanifold_edges"], "closed" if s["closed"] else "open"))


def need(ctx, handles):
    found = mesh_bodies(ctx, handles)
    if not found:
        raise CommandError("Give the handles of mesh objects.")
    return found


@command("meshfromsolid", aliases=("tomesh",), group=GROUP, label="Mesh From Solid", description="Make a mesh object from a solid or surface by tessellating it and welding the seams.", menu="Modify > 3D Operations > Mesh From Solid")
def meshfromsolid_cmd(ctx):
    handles = yield from pick(ctx, "Select solids or surfaces to convert")
    if not handles:
        return
    detail = yield ctx.number("Detail (1 is the display detail, larger is finer)", default=1.0, positive=True)
    if detail.kind != "number":
        return
    run_fromsolid(ctx, handles, float(detail.value))


def run_fromsolid(ctx, handles, detail):
    made = []
    for h in handles:
        e = ctx.d.get(int(h))
        if e is None or e.kind != "solidbody":
            continue
        m = guard(mesh_files.solid_mesh, ctx.d, e, detail)
        body = store.new_body(ctx.d, m, (e.name or "mesh") + " mesh", {"op": "tessellate", "from": e.name, "detail": detail}, mm_per_unit(ctx.d), False, list(e.rgb or []))
        ctx.add(body)
        made.append(body.handle)
        say_report(ctx, "MESHFROMSOLID", body.summary)
    if not made:
        raise CommandError("Select solids or surfaces.")
    return {"handles": made}


@executes("meshfromsolid")
def meshfromsolid_exec(ctx, args):
    hs = [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])]
    detail = float(args.get("detail", 1.0))
    if not detail > 0:
        raise CommandError("Detail must be positive.")
    return run_fromsolid(ctx, hs, detail)


@command("meshweld", group=GROUP, label="Weld Mesh", description="Merge mesh vertices that lie within a distance of each other and drop the triangles that collapse.", menu="Modify > Mesh > Weld")
def meshweld_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to weld")
    if not handles:
        return
    r = yield ctx.distance("Weld distance", default=ctx.d.tolerances["absolute"], positive=True)
    if r.kind != "number":
        return
    run_weld(ctx, handles, float(r.value))


def run_weld(ctx, handles, tol):
    if not tol > 0:
        raise CommandError("The weld distance must be positive.")
    out = []
    for e in need(ctx, handles):
        m = guard(store.load, ctx.d, e)
        res, info = guard(core.weld, m, tol * mm_per_unit(ctx.d))
        t = replace(ctx, e, res, "weld", info)
        ctx.say("MESHWELD: merged %d vertices, removed %d triangles." % (info["merged"], info["removed_triangles"]))
        say_report(ctx, "MESHWELD", t.summary)
        out.append({"handle": t.handle, **info})
    return {"results": out}


@executes("meshweld")
def meshweld_exec(ctx, args):
    hs = [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])]
    return run_weld(ctx, hs, float(args.get("tolerance", ctx.d.tolerances["absolute"])))


@command("meshunify", group=GROUP, label="Unify Mesh Normals", description="Make the triangles of each connected piece face the same way, outward for closed pieces.", menu="Modify > Mesh > Unify Normals")
def meshunify_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to unify")
    if handles:
        run_unify(ctx, handles)


def run_unify(ctx, handles):
    out = []
    for e in need(ctx, handles):
        m = guard(store.load, ctx.d, e)
        res, info = guard(core.unify, m)
        t = replace(ctx, e, res, "unify", info)
        ctx.say("MESHUNIFY: flipped %d triangles in %d pieces, %d edges stay inconsistent." % (info["flipped"], info["components"], info["conflicts"]))
        out.append({"handle": t.handle, **info})
    return {"results": out}


@executes("meshunify")
def meshunify_exec(ctx, args):
    return run_unify(ctx, [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])])


@command("meshfill", group=GROUP, label="Fill Mesh Holes", description="Close the holes in a mesh with a triangulation that follows the surface around each hole.", menu="Modify > Mesh > Fill Holes")
def meshfill_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to fill")
    if not handles:
        return
    r = yield ctx.number("Largest hole in edges", default=32, integer=True, minimum=3, maximum=4096)
    if r.kind != "number":
        return
    run_fill(ctx, handles, int(r.value), 0.0)


def run_fill(ctx, handles, edges, size):
    if edges < 3:
        raise CommandError("A hole has at least 3 edges.")
    out = []
    for e in need(ctx, handles):
        m = guard(store.load, ctx.d, e)
        res, info = guard(core.fill_holes, m, edges, size * mm_per_unit(ctx.d))
        t = replace(ctx, e, res, "fill", info)
        ctx.say("MESHFILL: filled %d holes with %d triangles, skipped %d." % (info["filled"], info["triangles_added"], len(info["skipped"])))
        for sk in info["skipped"][:5]:
            ctx.say("MESHFILL: a hole of %d edges was left open because %s." % (sk["edges"], sk["reason"]))
        say_report(ctx, "MESHFILL", t.summary)
        out.append({"handle": t.handle, **info})
    return {"results": out}


@executes("meshfill")
def meshfill_exec(ctx, args):
    hs = [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])]
    return run_fill(ctx, hs, int(args.get("max_edges", 32)), float(args.get("max_size", 0.0)))


@command("meshnaked", group=GROUP, label="Naked Edges", description="Count the naked edges of meshes and show them as highlighted loops.", menu="Tools > Inquiry > Mesh Naked Edges", undoable=False)
def meshnaked_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to inspect")
    if handles:
        run_naked(ctx, handles)


def run_naked(ctx, handles):
    found = mesh_bodies(ctx, handles, False)
    if not found:
        raise CommandError("Give the handles of mesh objects.")
    out = []
    for e in found:
        m = guard(store.load, ctx.d, e)
        s = core.report(m)
        loops = len(store.naked_polylines(m))
        ctx.say("%s: %d naked edges in %d loops or chains." % (e.name or "Mesh", s["naked_edges"], loops))
        out.append({"handle": e.handle, "naked_edges": s["naked_edges"], "loops": s["naked_loops"], "open_chains": s["open_chains"], "nonmanifold_edges": s["nonmanifold_edges"]})
    return {"results": out}


@executes("meshnaked")
def meshnaked_exec(ctx, args):
    return run_naked(ctx, [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])])


@command("meshreport", aliases=("meshcheck",), group=GROUP, label="Mesh Report", description="List the counts, naked and non-manifold edges and volume of meshes.", menu="Tools > Inquiry > Mesh Report", undoable=False)
def meshreport_cmd(ctx):
    handles = yield from pick(ctx, "Select meshes to check")
    if handles:
        run_report(ctx, handles)


def run_report(ctx, handles):
    found = mesh_bodies(ctx, handles, False)
    if not found:
        raise CommandError("Give the handles of mesh objects.")
    out = []
    s = mm_per_unit(ctx.d)
    for e in found:
        r = core.report(guard(store.load, ctx.d, e))
        say_report(ctx, e.name or "Mesh", r)
        vol = ctx.fd(r["volume"] / s**3) if r["volume"] is not None else "none (open)"
        ctx.say("Area %s, volume %s, %d pieces, %d degenerate triangles, %d edges with mismatched direction." % (ctx.fd(r["area"] / s**2), vol, r["components"], r["degenerate_triangles"], r["inconsistent_edges"]))
        out.append({"handle": e.handle, **r})
    return {"results": out}


@executes("meshreport")
def meshreport_exec(ctx, args):
    return run_report(ctx, [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])])


@command("info3dm", group=GROUP, label="3DM File Info", description="Read a 3DM file's version, units, tolerances, layers and object counts without opening it.", menu="File > 3DM Info...", undoable=False, repeatable=False)
def info3dm_cmd(ctx):
    r = yield ctx.text("Enter file name (.3dm)")
    if r.kind != "text" or not str(r.value).strip():
        return
    run_info(ctx, str(r.value).strip())


def run_info(ctx, path):
    import os

    from app.cmd import barred
    from app.cmd.registry import COMMANDS
    from app.interchange import threedm
    from app.interchange.errors import InterchangeError

    why = barred.args_refusal(ctx.runner, COMMANDS["info3dm"], {"path": path})
    if why:
        raise CommandError(why)
    full = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(full) or os.path.splitext(full)[1].lower() != ".3dm":
        raise CommandError("Give the path of an existing .3dm file.")
    try:
        res = threedm.info(full)
    except InterchangeError as err:
        raise CommandError(str(err))
    ctx.say("3DM archive version %s, units %s, %d layers." % (res.get("archive_version"), (res.get("unit") or {}).get("name"), len(res.get("layers") or [])))
    return res


@executes("info3dm")
def info3dm_exec(ctx, args):
    return run_info(ctx, str(args.get("path", "")))
