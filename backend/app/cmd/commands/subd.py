import functools
import math
import os
import shutil

import numpy as np

from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd import registry
from app.cmd.registry import command
from app.meshes import jobs
from app.param.units import mm_per_unit
from app.solid import work
from app.solid.work import SolidError
from app.subd import convert, edit, ops, prims, store, sym as symmetry
from app.subd.cage import Cage
from app.subd.cc import SubdError

GROUP = "solids"
LONG = 300.0


def executes(*names):
    base = registry.executes(*names)

    def wrap(fn):
        @functools.wraps(fn)
        def inner(ctx, args):
            try:
                return fn(ctx, args)
            except (ValueError, TypeError, KeyError, IndexError) as err:
                raise CommandError("A value is not valid (%s)." % err)

        return base(inner)

    return wrap


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (SubdError, SolidError) as err:
        raise CommandError(str(err))
    except (ValueError, TypeError, IndexError, KeyError) as err:
        raise CommandError("A value is not valid (%s)." % err)


def is_agent(ctx) -> bool:
    return barred.caller(ctx.runner) in ("macro", "agent")


def handle_of(args):
    h = args.get("handle")
    if h is None and args.get("handles"):
        h = args["handles"][0]
    if h is None:
        raise CommandError("Give the handle of a form.")
    return int(h)


def get_cage(ctx, args, need_edit=True):
    h = handle_of(args)
    e = ctx.d.get(h)
    if e is None or e.kind != "subdbody":
        raise CommandError("Handle %d is not a form." % h)
    if need_edit and ctx.locked(e):
        raise CommandError("That form is on a locked layer.")
    return e, guard(store.load, e)


def commit(ctx, ent, cage, op, info=None, sym=None):
    target = ctx.d.modify(ent.handle)
    src = dict(ent.source or {})
    src.update({"op": op})
    guard(store.fill, ctx.d, target, cage, src, sym)
    if info:
        ctx.say("%s: %s." % (op.upper(), ", ".join("%s %s" % (v, k.replace("_", " ")) for k, v in info.items())))
    return target


def vec(value, n=3, what="value"):
    try:
        out = [float(x) for x in value]
    except (TypeError, ValueError):
        raise CommandError("%s must be %d numbers." % (what.capitalize(), n))
    if len(out) < n:
        out += [0.0] * (n - len(out))
    if not all(math.isfinite(x) for x in out):
        raise CommandError("%s must be finite." % what.capitalize())
    return out[:n]


def positive(value, what):
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise CommandError("%s must be positive." % what)
    return v


def sym_for(ctx, args, center):
    spec = args.get("symmetry", "none")
    mirror = prims.sym_mirror(spec, center) if isinstance(spec, str) else []
    return {"mirror": mirror, "radial": None, "tol": 1e-6}


def add_cage(ctx, cage, name, op, args, center, extra=None):
    cage.validate(is_agent(ctx))
    src = {"op": op}
    if extra:
        src.update(extra)
    ent = guard(store.new_entity, ctx.d, cage, args.get("name") or name, src, sym_for(ctx, args, center), "both", 3, args.get("rgb"))
    ctx.add(ent)
    ctx.say("%s: %d vertices, %d faces." % (op.upper(), ent.summary["vertices"], ent.summary["faces"]))
    return {"handles": [ent.handle], "summary": ent.summary}


def origin_of(args):
    return vec(args.get("origin", [0, 0, 0]), 3, "origin")


def text_ints(text):
    out = []
    for tok in str(text).replace(";", ",").split(","):
        tok = tok.strip()
        if tok:
            out.append(int(tok))
    return out


def pick(ctx, message):
    sel = yield ctx.select(message)
    if sel.kind != "selection":
        return None
    return [int(h) for h in sel.value]


def first_form(ctx, handles):
    for h in handles or []:
        e = ctx.d.get(int(h))
        if e is not None and e.kind == "subdbody":
            return int(h)
    raise CommandError("Select a form.")


@command("subdbox", group=GROUP, label="Form Box", description="Make a box-shaped subdivision form with a chosen number of faces along each side.", menu="Draw > Form > Box")
def subdbox_cmd(ctx):
    r = yield ctx.point("Specify first corner of the form box")
    if r.kind != "point":
        return
    o = [float(r.value[0]), float(r.value[1]), float(r.value[2]) if len(r.value) > 2 else 0.0]
    w = yield ctx.number("Length", default=10.0, positive=True)
    d = yield ctx.number("Width", default=10.0, positive=True)
    h = yield ctx.number("Height", default=10.0, positive=True)
    if not all(x.kind == "number" for x in (w, d, h)):
        return
    run_box(ctx, {"origin": o, "size": [float(w.value), float(d.value), float(h.value)]})


def run_box(ctx, args):
    o = origin_of(args)
    size = vec(args.get("size", [10, 10, 10]), 3, "size")
    for s in size:
        positive(s, "Size")
    segs = [int(x) for x in vec(args.get("segments", [2, 2, 2]), 3, "segments")]
    cage = guard(prims.box, o, size, segs)
    return add_cage(ctx, cage, "Form Box", "subdbox", args, [o[i] + size[i] / 2 for i in range(3)])


@executes("subdbox")
def subdbox_exec(ctx, args):
    return run_box(ctx, args)


@command("subdcylinder", group=GROUP, label="Form Cylinder", description="Make a cylinder-shaped subdivision form.", menu="Draw > Form > Cylinder")
def subdcylinder_cmd(ctx):
    r = yield ctx.point("Specify centre of the base")
    if r.kind != "point":
        return
    o = [float(r.value[0]), float(r.value[1]), float(r.value[2]) if len(r.value) > 2 else 0.0]
    rad = yield ctx.number("Radius", default=5.0, positive=True)
    h = yield ctx.number("Height", default=10.0, positive=True)
    if rad.kind != "number" or h.kind != "number":
        return
    run_cylinder(ctx, {"origin": o, "radius": float(rad.value), "height": float(h.value)})


def run_cylinder(ctx, args):
    o = origin_of(args)
    rad = positive(args.get("radius", 5.0), "Radius")
    h = positive(args.get("height", 10.0), "Height")
    cage = guard(prims.cylinder, o, rad, h, int(args.get("segments", 8)), int(args.get("height_segments", 2)))
    return add_cage(ctx, cage, "Form Cylinder", "subdcylinder", args, [o[0], o[1], o[2] + h / 2])


@executes("subdcylinder")
def subdcylinder_exec(ctx, args):
    return run_cylinder(ctx, args)


@command("subdsphere", group=GROUP, label="Form Sphere", description="Make a sphere-shaped subdivision form with poles.", menu="Draw > Form > Sphere")
def subdsphere_cmd(ctx):
    r = yield ctx.point("Specify centre of the form sphere")
    if r.kind != "point":
        return
    o = [float(r.value[0]), float(r.value[1]), float(r.value[2]) if len(r.value) > 2 else 0.0]
    rad = yield ctx.number("Radius", default=5.0, positive=True)
    if rad.kind != "number":
        return
    run_sphere(ctx, {"origin": o, "radius": float(rad.value)})


def run_sphere(ctx, args):
    o = origin_of(args)
    rad = positive(args.get("radius", 5.0), "Radius")
    cage = guard(prims.sphere, o, rad, int(args.get("segments", 8)), int(args.get("rings", 6)))
    return add_cage(ctx, cage, "Form Sphere", "subdsphere", args, o)


@executes("subdsphere")
def subdsphere_exec(ctx, args):
    return run_sphere(ctx, args)


@command("subdquadball", group=GROUP, label="Form Quadball", description="Make a ball-shaped subdivision form that is all quads, from a cube.", menu="Draw > Form > Quadball")
def subdquadball_cmd(ctx):
    r = yield ctx.point("Specify centre of the quadball")
    if r.kind != "point":
        return
    o = [float(r.value[0]), float(r.value[1]), float(r.value[2]) if len(r.value) > 2 else 0.0]
    rad = yield ctx.number("Radius", default=5.0, positive=True)
    if rad.kind != "number":
        return
    run_quadball(ctx, {"origin": o, "radius": float(rad.value)})


def run_quadball(ctx, args):
    o = origin_of(args)
    rad = positive(args.get("radius", 5.0), "Radius")
    cage = guard(prims.quadball, o, rad, int(args.get("spans", 2)))
    return add_cage(ctx, cage, "Form Quadball", "subdquadball", args, o)


@executes("subdquadball")
def subdquadball_exec(ctx, args):
    return run_quadball(ctx, args)


@command("subdtorus", group=GROUP, label="Form Torus", description="Make a torus-shaped subdivision form.", menu="Draw > Form > Torus")
def subdtorus_cmd(ctx):
    r = yield ctx.point("Specify centre of the form torus")
    if r.kind != "point":
        return
    o = [float(r.value[0]), float(r.value[1]), float(r.value[2]) if len(r.value) > 2 else 0.0]
    a = yield ctx.number("Major radius", default=10.0, positive=True)
    b = yield ctx.number("Minor radius", default=3.0, positive=True)
    if a.kind != "number" or b.kind != "number":
        return
    run_torus(ctx, {"origin": o, "major": float(a.value), "minor": float(b.value)})


def run_torus(ctx, args):
    o = origin_of(args)
    major = positive(args.get("major", 10.0), "Major radius")
    minor = positive(args.get("minor", 3.0), "Minor radius")
    if minor >= major:
        raise CommandError("The minor radius must be smaller than the major radius.")
    cage = guard(prims.torus, o, major, minor, int(args.get("segments_major", 12)), int(args.get("segments_minor", 8)))
    return add_cage(ctx, cage, "Form Torus", "subdtorus", args, o)


@executes("subdtorus")
def subdtorus_exec(ctx, args):
    return run_torus(ctx, args)


@command("subdplane", group=GROUP, label="Form Plane", description="Make a flat open grid form.", menu="Draw > Form > Plane")
def subdplane_cmd(ctx):
    r = yield ctx.point("Specify first corner of the form plane")
    if r.kind != "point":
        return
    o = [float(r.value[0]), float(r.value[1]), float(r.value[2]) if len(r.value) > 2 else 0.0]
    w = yield ctx.number("Length", default=10.0, positive=True)
    d = yield ctx.number("Width", default=10.0, positive=True)
    if w.kind != "number" or d.kind != "number":
        return
    run_plane(ctx, {"origin": o, "size": [float(w.value), float(d.value)]})


def run_plane(ctx, args):
    o = origin_of(args)
    size = vec(args.get("size", [10, 10]), 2, "size")
    for s in size:
        positive(s, "Size")
    segs = [int(x) for x in vec(args.get("segments", [4, 4]), 2, "segments")]
    cage = guard(prims.plane, o, size, segs)
    return add_cage(ctx, cage, "Form Plane", "subdplane", args, [o[0] + size[0] / 2, o[1] + size[1] / 2, o[2]])


@executes("subdplane")
def subdplane_exec(ctx, args):
    return run_plane(ctx, args)


def arc_points(p0, p1, bulge, steps=8):
    if abs(bulge) < 1e-12:
        return [p1]
    chord = math.dist(p0, p1)
    if chord < 1e-12:
        return [p1]
    theta = 4.0 * math.atan(bulge)
    radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    offset = math.copysign(radius - abs(bulge) * chord / 2.0, bulge)
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    dx, dy = (p1[0] - p0[0]) / chord, (p1[1] - p0[1]) / chord
    cx, cy = mx - dy * offset, my + dx * offset
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    out = []
    for i in range(1, steps + 1):
        a = a0 + theta * i / steps
        out.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    out[-1] = tuple(p1)
    return out


def profile_points(ctx, ent, segments):
    if ent.kind == "circle":
        n = max(3, int(segments))
        cx, cy = ent.center[0], ent.center[1]
        return [(cx + ent.radius * math.cos(2 * math.pi * i / n), cy + ent.radius * math.sin(2 * math.pi * i / n)) for i in range(n)], 0.0, True
    if ent.kind == "lwpolyline":
        pts = []
        verts = ent.vertices
        n = len(verts)
        last = n if ent.closed else n - 1
        for i in range(last):
            a = verts[i]
            b = verts[(i + 1) % n]
            pts.append(tuple(a["p"][:2]))
            pts.extend(arc_points(a["p"][:2], b["p"][:2], float(a.get("bulge", 0.0) or 0.0))[:-1])
        if not ent.closed:
            pts.append(tuple(verts[-1]["p"][:2]))
        return pts, float(ent.elevation), bool(ent.closed)
    if ent.kind == "region":
        loop = ent.loops[0]["vertices"]
        return [tuple(v["p"][:2]) for v in loop], 0.0, True
    raise CommandError("Use a closed polyline, circle or region as the profile.")


@command("subdextrude", group=GROUP, label="Form Extrude", description="Extrude a closed sketch profile into a subdivision form.", menu="Draw > Form > Extrude")
def subdextrude_cmd(ctx):
    handles = yield from pick(ctx, "Select a closed profile to extrude into a form")
    if not handles:
        return
    h = yield ctx.number("Height", default=10.0)
    if h.kind != "number":
        return
    run_extrude(ctx, {"profile": handles[0], "height": float(h.value)})


def run_extrude(ctx, args):
    ent = ctx.d.get(int(args.get("profile", 0)))
    if ent is None:
        raise CommandError("Give the handle of the profile.")
    pts, z0, closed = profile_points(ctx, ent, int(args.get("segments", 8)))
    if not closed:
        raise CommandError("The profile is open; close it first.")
    h = float(args.get("height", 10.0))
    if not math.isfinite(h) or h == 0:
        raise CommandError("The height must be a non-zero number.")
    cage = guard(prims.prism, pts, z0, h, int(args.get("spans", 2)))
    cx = float(np.mean([p[0] for p in pts]))
    cy = float(np.mean([p[1] for p in pts]))
    return add_cage(ctx, cage, "Form Extrusion", "subdextrude", args, [cx, cy, z0 + h / 2], {"profile": ent.kind})


@executes("subdextrude")
def subdextrude_exec(ctx, args):
    return run_extrude(ctx, args)


@command("subdrevolve", group=GROUP, label="Form Revolve", description="Revolve an open or closed sketch profile around an axis into a subdivision form.", menu="Draw > Form > Revolve")
def subdrevolve_cmd(ctx):
    handles = yield from pick(ctx, "Select a profile polyline to revolve")
    if not handles:
        return
    a = yield ctx.point("Specify a point on the axis")
    b = yield ctx.point("Specify the axis direction point", base=a.value if a.kind == "point" else None)
    if a.kind != "point" or b.kind != "point":
        return
    p = [float(a.value[0]), float(a.value[1]), float(a.value[2]) if len(a.value) > 2 else 0.0]
    q = [float(b.value[0]), float(b.value[1]), float(b.value[2]) if len(b.value) > 2 else 0.0]
    run_revolve(ctx, {"profile": handles[0], "axis": {"origin": p, "dir": [q[i] - p[i] for i in range(3)]}})


def run_revolve(ctx, args):
    ent = ctx.d.get(int(args.get("profile", 0)))
    if ent is None:
        raise CommandError("Give the handle of the profile.")
    pts, z0, closed = profile_points(ctx, ent, int(args.get("profile_segments", 16)))
    ax = args.get("axis") or {}
    origin = vec(ax.get("origin", [0, 0, 0]), 3, "axis origin")
    direction = vec(ax.get("dir", [0, 1, 0]), 3, "axis direction")
    pts3 = [[p[0], p[1], z0] for p in pts]
    if closed:
        pts3.append(pts3[0])
    angle = float(args.get("angle", 360.0))
    if not math.isfinite(angle) or angle == 0 or abs(angle) > 360.0:
        raise CommandError("The angle must be non-zero and at most 360 degrees.")
    cage = guard(prims.revolve, pts3, origin, direction, angle, int(args.get("segments", 8)))
    full = abs(abs(angle) - 360.0) < 1e-9
    spec = {"symmetry": "none"}
    res = add_cage(ctx, cage, "Form Revolve", "subdrevolve", {**args, **spec}, origin, {"profile": ent.kind})
    if full:
        e = ctx.d.modify(res["handles"][0])
        axis_name = None
        d = np.asarray(direction, dtype=float)
        d = d / np.linalg.norm(d)
        for i, nm in enumerate("xyz"):
            if abs(abs(d[i]) - 1.0) < 1e-9:
                axis_name = nm
        if axis_name:
            i1, i2 = [i for i in range(3) if i != "xyz".index(axis_name)]
            e.sym = symmetry.clean({"mirror": [], "radial": {"axis": axis_name, "count": int(args.get("segments", 8)), "center": [origin[i1], origin[i2]]}})
    return res


@executes("subdrevolve")
def subdrevolve_exec(ctx, args):
    return run_revolve(ctx, args)


def selection_args(cage, args):
    return {"vertices": args.get("vertices") or [], "edges": args.get("edges") or [], "faces": args.get("faces") or []}


def sym_state(ctx, ent, args, cage):
    use = bool(args.get("symmetry", True)) and symmetry.active(ent.sym)
    return use, (ent.sym if use else None)


def run_transform(ctx, args, kind):
    ent, cage = get_cage(ctx, args)
    sel_args = selection_args(cage, args)
    sel = guard(edit.selection_vertices, cage, **sel_args)
    if not sel:
        raise CommandError("Select vertices, edges or faces first.")
    use, sym = sym_state(ctx, ent, args, cage)
    soft = args.get("soft") or {}
    radius = float(soft.get("radius", 0.0) or 0.0)
    weights = guard(edit.soft_weights, cage, sel, radius, soft.get("falloff", "smooth"))
    if kind == "move":
        n = guard(edit.move, cage, sel, weights, vec(args.get("delta", [0, 0, 0]), 3, "delta"), use, sym)
    elif kind == "rotate":
        pivot = args.get("pivot")
        n = guard(edit.rot, cage, sel, weights, vec(args.get("axis", [0, 0, 1]), 3, "axis"), float(args.get("angle", 0.0)), vec(pivot, 3, "pivot") if pivot is not None else None, use, sym)
    else:
        pivot = args.get("pivot")
        factor = args.get("factor", 1.0)
        factor = vec(factor, 3, "factor") if isinstance(factor, (list, tuple)) else float(factor)
        n = guard(edit.scale, cage, sel, weights, factor, vec(pivot, 3, "pivot") if pivot is not None else None, use, sym)
    t = commit(ctx, ent, cage, "subd" + kind)
    ctx.say("SUBD%s: moved %d vertices." % (kind.upper(), n))
    return {"handle": t.handle, "moved": n, "summary": t.summary}


def text_selection(ctx, label):
    r = yield ctx.text("Enter %s indices separated by commas" % label)
    if r.kind != "text":
        return None
    try:
        return text_ints(r.value)
    except ValueError:
        raise CommandError("Give whole numbers separated by commas.")


@command("subdmove", group=GROUP, label="Move Form Points", description="Move vertices, edges or faces of a form, with optional soft selection and symmetry.", menu="Modify > Form > Move")
def subdmove_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    verts = yield from text_selection(ctx, "vertex")
    if not verts:
        return
    d = yield ctx.number("Move along X", default=0.0)
    e = yield ctx.number("Move along Y", default=0.0)
    f = yield ctx.number("Move along Z", default=0.0)
    if not all(x.kind == "number" for x in (d, e, f)):
        return
    run_transform(ctx, {"handle": first_form(ctx, handles), "vertices": verts, "delta": [float(d.value), float(e.value), float(f.value)]}, "move")


@executes("subdmove")
def subdmove_exec(ctx, args):
    return run_transform(ctx, args, "move")


@command("subdrotate", group=GROUP, label="Rotate Form Points", description="Rotate vertices, edges or faces of a form around an axis.", menu="Modify > Form > Rotate")
def subdrotate_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    verts = yield from text_selection(ctx, "vertex")
    if not verts:
        return
    a = yield ctx.number("Rotation angle in degrees", default=15.0)
    if a.kind != "number":
        return
    run_transform(ctx, {"handle": first_form(ctx, handles), "vertices": verts, "angle": float(a.value)}, "rotate")


@executes("subdrotate")
def subdrotate_exec(ctx, args):
    return run_transform(ctx, args, "rotate")


@command("subdscale", group=GROUP, label="Scale Form Points", description="Scale vertices, edges or faces of a form about a pivot.", menu="Modify > Form > Scale")
def subdscale_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    verts = yield from text_selection(ctx, "vertex")
    if not verts:
        return
    f = yield ctx.number("Scale factor", default=1.2, positive=True)
    if f.kind != "number":
        return
    run_transform(ctx, {"handle": first_form(ctx, handles), "vertices": verts, "factor": float(f.value)}, "scale")


@executes("subdscale")
def subdscale_exec(ctx, args):
    return run_transform(ctx, args, "scale")


def expand_sym(ctx, ent, cage, args, vertices=None, edges=None, faces=None):
    if not (bool(args.get("symmetry", True)) and symmetry.active(ent.sym)):
        return vertices, edges, faces
    pl = symmetry.perms(cage, ent.sym)
    if not pl:
        return vertices, edges, faces
    if vertices:
        vertices = sorted(symmetry.image_set(pl, [int(v) for v in vertices]))
    if edges:
        edges = sorted(symmetry.image_edges(pl, [(int(e[0]), int(e[1])) for e in edges]))
    if faces:
        faces = sorted(symmetry.image_faces(cage, pl, [int(f) for f in faces]))
    return vertices, edges, faces


@command("subdinsertedge", group=GROUP, label="Insert Form Edge", description="Cut a new ring of edges through a form across the quads next to chosen edges.", menu="Modify > Form > Insert Edge")
def subdinsertedge_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    r = yield ctx.text("Enter edges as pairs of vertex indices, for example 0-1, 4-5")
    if r.kind != "text":
        return
    run_insert(ctx, {"handle": first_form(ctx, handles), "edges": parse_edges(r.value)})


def parse_edges(text):
    out = []
    for tok in str(text).replace(";", ",").split(","):
        tok = tok.strip()
        if tok:
            a, b = tok.replace(" ", "-").split("-")[:2]
            out.append([int(a), int(b)])
    return out


def run_insert(ctx, args):
    ent, cage = get_cage(ctx, args)
    _, edges, _ = expand_sym(ctx, ent, cage, args, None, args.get("edges") or [], None)
    out, info = guard(ops.insert_edge, cage, edges or [], int(args.get("cuts", 1)), float(args.get("position", 0.5)), is_agent(ctx))
    t = commit(ctx, ent, out, "subdinsertedge", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subdinsertedge")
def subdinsertedge_exec(ctx, args):
    return run_insert(ctx, args)


@command("subddivideface", group=GROUP, label="Subdivide Form Face", description="Split chosen faces of a form into smaller quads around a new centre point.", menu="Modify > Form > Subdivide Face")
def subddivideface_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    faces = yield from text_selection(ctx, "face")
    if not faces:
        return
    run_divide(ctx, {"handle": first_form(ctx, handles), "faces": faces})


def run_divide(ctx, args):
    ent, cage = get_cage(ctx, args)
    _, _, faces = expand_sym(ctx, ent, cage, args, None, None, args.get("faces") or [])
    out, info = guard(ops.subdivide_faces, cage, faces or [], is_agent(ctx))
    t = commit(ctx, ent, out, "subddivideface", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subddivideface")
def subddivideface_exec(ctx, args):
    return run_divide(ctx, args)


@command("subddelete", group=GROUP, label="Delete Form Elements", description="Delete faces, vertices (with their faces) or edges (merging the faces beside them) of a form.", menu="Modify > Form > Delete")
def subddelete_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    faces = yield from text_selection(ctx, "face")
    if not faces:
        return
    run_delete(ctx, {"handle": first_form(ctx, handles), "faces": faces})


def run_delete(ctx, args):
    ent, cage = get_cage(ctx, args)
    verts, edges, faces = expand_sym(ctx, ent, cage, args, args.get("vertices") or [], args.get("edges") or [], args.get("faces") or [])
    if not (verts or edges or faces):
        raise CommandError("Select vertices, edges or faces to delete.")
    out, info = guard(ops.delete, cage, verts, edges, faces)
    if not len(out.f):
        raise CommandError("That would delete the whole form.")
    t = commit(ctx, ent, out, "subddelete", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subddelete")
def subddelete_exec(ctx, args):
    return run_delete(ctx, args)


@command("subdcrease", group=GROUP, label="Crease Form", description="Make edges of a form sharp or semi-sharp with a weight from 0 to 10.", menu="Modify > Form > Crease")
def subdcrease_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    r = yield ctx.text("Enter edges as pairs of vertex indices, for example 0-1, 4-5")
    if r.kind != "text":
        return
    w = yield ctx.number("Crease weight", default=10.0, positive=True)
    if w.kind != "number":
        return
    run_crease(ctx, {"handle": first_form(ctx, handles), "edges": parse_edges(r.value), "weight": float(w.value)})


def run_crease(ctx, args):
    ent, cage = get_cage(ctx, args)
    verts, edges, faces = expand_sym(ctx, ent, cage, args, args.get("vertices") or [], args.get("edges") or [], args.get("faces") or [])
    targets = guard(ops.crease_targets, cage, verts, edges, faces)
    out, info = guard(ops.set_crease, cage, targets, float(args.get("weight", 10.0)))
    t = commit(ctx, ent, out, "subdcrease", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subdcrease")
def subdcrease_exec(ctx, args):
    return run_crease(ctx, args)


@command("subduncrease", group=GROUP, label="Uncrease Form", description="Remove or lower the crease weight on edges of a form.", menu="Modify > Form > Uncrease")
def subduncrease_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    r = yield ctx.text("Enter edges as pairs of vertex indices, or all")
    if r.kind != "text":
        return
    txt = str(r.value).strip().lower()
    args = {"handle": first_form(ctx, handles)}
    if txt == "all":
        args["all"] = True
    else:
        args["edges"] = parse_edges(txt)
    run_uncrease(ctx, args)


def run_uncrease(ctx, args):
    ent, cage = get_cage(ctx, args)
    amount = args.get("amount")
    if args.get("all"):
        out, info = guard(ops.remove_crease, cage, None, amount)
    else:
        verts, edges, faces = expand_sym(ctx, ent, cage, args, args.get("vertices") or [], args.get("edges") or [], args.get("faces") or [])
        targets = guard(ops.crease_targets, cage, verts, edges, faces)
        out, info = guard(ops.remove_crease, cage, targets, amount)
    t = commit(ctx, ent, out, "subduncrease", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subduncrease")
def subduncrease_exec(ctx, args):
    return run_uncrease(ctx, args)


@command("subdbridge", group=GROUP, label="Bridge Form Loops", description="Join two open loops of the same length with a ring of new faces.", menu="Modify > Form > Bridge")
def subdbridge_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    a = yield ctx.text("Enter one edge of the first loop as two vertex indices, for example 0-1")
    b = yield ctx.text("Enter one edge of the second loop as two vertex indices")
    if a.kind != "text" or b.kind != "text":
        return
    run_bridge(ctx, {"handle": first_form(ctx, handles), "edges": [parse_edges(a.value)[0], parse_edges(b.value)[0]]})


def run_bridge(ctx, args):
    ent, cage = get_cage(ctx, args)
    kw = {"twist": args.get("twist"), "spans": int(args.get("spans", 1)), "agent": is_agent(ctx)}
    if args.get("faces"):
        groups = args["faces"]
        if not (isinstance(groups, list) and len(groups) == 2 and all(isinstance(g, list) for g in groups)):
            raise CommandError("Give two lists of faces to bridge.")
        out, info = guard(ops.bridge, cage, None, None, groups[0], groups[1], **kw)
    else:
        edges = args.get("edges") or []
        if len(edges) == 2 and all(isinstance(e, (list, tuple)) and len(e) == 2 and not isinstance(e[0], (list, tuple)) for e in edges):
            ea, eb = [edges[0]], [edges[1]]
        elif len(edges) == 2 and all(isinstance(g, (list, tuple)) and g and isinstance(g[0], (list, tuple)) for g in edges):
            ea, eb = edges[0], edges[1]
        else:
            raise CommandError("Give two edges, one on each open loop.")
        out, info = guard(ops.bridge, cage, ea, eb, None, None, **kw)
    t = commit(ctx, ent, out, "subdbridge", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subdbridge")
def subdbridge_exec(ctx, args):
    return run_bridge(ctx, args)


@command("subdfillhole", group=GROUP, label="Fill Form Hole", description="Close an open loop of a form with quads, one polygon or a star of triangles.", menu="Modify > Form > Fill Hole")
def subdfillhole_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if handles:
        run_fill(ctx, {"handle": first_form(ctx, handles), "all": True})


def run_fill(ctx, args):
    ent, cage = get_cage(ctx, args)
    edge = None
    if not args.get("all"):
        e = args.get("edges") or []
        if not e:
            raise CommandError("Give an edge on the hole, or all.")
        edge = (int(e[0][0]), int(e[0][1]))
    out, info = guard(ops.fill_hole, cage, edge, str(args.get("style", "quads")), is_agent(ctx))
    t = commit(ctx, ent, out, "subdfillhole", info)
    return {"handle": t.handle, **info, "summary": t.summary}


@executes("subdfillhole")
def subdfillhole_exec(ctx, args):
    return run_fill(ctx, args)


@command("subdsymmetry", group=GROUP, label="Form Symmetry", description="Keep edits of a form mirrored across planes or repeated around an axis.", menu="Modify > Form > Symmetry")
def subdsymmetry_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    r = yield ctx.text("Mirror axes (x, y, z, xy, ...) or none")
    if r.kind != "text":
        return
    word = str(r.value).strip().lower()
    run_symmetry(ctx, {"handle": first_form(ctx, handles), "mirror": [c for c in word if c in "xyz"], "clear": word in ("", "none")})


def run_symmetry(ctx, args):
    ent, cage = get_cage(ctx, args)
    if args.get("clear"):
        spec = symmetry.default_sym()
    else:
        at = args.get("at")
        centre = cage.v.mean(axis=0) if len(cage.v) else np.zeros(3)
        mirror = []
        for ax in args.get("mirror") or []:
            ax = str(ax).lower()
            if ax not in "xyz" or len(ax) != 1:
                raise CommandError("The mirror axes are x, y and z.")
            value = float(at[ax]) if isinstance(at, dict) and ax in at else (float(at) if isinstance(at, (int, float)) else float(centre["xyz".index(ax)]))
            mirror.append({"axis": ax, "at": value})
        radial = args.get("radial")
        spec = {"mirror": mirror, "radial": radial, "tol": float(args.get("tol", 1e-6))}
    spec = guard(symmetry.clean, spec)
    t = ctx.d.modify(ent.handle)
    t.sym = spec
    t.version = int(t.version) + 1
    store.touch()
    err = guard(symmetry.check, cage, spec) if symmetry.active(spec) else 0.0
    ctx.say("SUBDSYMMETRY: %d mirror planes, radial %s; counterpart error %.3g." % (len(spec["mirror"]), spec["radial"]["count"] if spec["radial"] else "none", err))
    return {"handle": t.handle, "sym": spec, "counterpart_error": err}


@executes("subdsymmetry")
def subdsymmetry_exec(ctx, args):
    return run_symmetry(ctx, args)


@command("subddisplay", group=GROUP, label="Form Display", description="Show a form as the smooth surface, the cage, or both, and set the smooth level.", menu="View > Form Display")
def subddisplay_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if not handles:
        return
    r = yield ctx.text("Display mode: smooth, box or both")
    if r.kind != "text":
        return
    run_display(ctx, {"handle": first_form(ctx, handles), "mode": str(r.value).strip().lower()})


def run_display(ctx, args):
    ent, _cage = get_cage(ctx, args, False)
    t = ctx.d.modify(ent.handle)
    mode = args.get("mode", ent.display)
    if mode not in ("smooth", "box", "both"):
        raise CommandError("The display mode is smooth, box or both.")
    level = int(args.get("level", ent.level))
    if not 1 <= level <= 4:
        raise CommandError("The level must be 1 to 4.")
    t.display = mode
    t.level = level
    t.version = int(t.version) + 1
    store.touch()
    return {"handle": t.handle, "mode": mode, "level": level}


@executes("subddisplay")
def subddisplay_exec(ctx, args):
    return run_display(ctx, args)


@command("subdconvert", group=GROUP, label="Convert Form To Solid", description="Turn a closed subdivision form into a solid made of bicubic patches sewn without gaps.", menu="Modify > Form > Convert To Solid")
def subdconvert_cmd(ctx):
    handles = yield from pick(ctx, "Select a form to convert")
    if not handles:
        return
    lv = yield ctx.number("Patch level (1 coarse, 4 fine)", default=2, integer=True, minimum=1, maximum=4)
    if lv.kind != "number":
        return
    run_convert(ctx, {"handle": first_form(ctx, handles), "levels": int(lv.value)})


def run_convert(ctx, args):
    ent, cage = get_cage(ctx, args, False)
    scale = mm_per_unit(ctx.d)
    try:
        with jobs.activity(ctx, "subdconvert") as act:
            built = guard(convert.build, cage, int(args.get("levels", 2)), is_agent(ctx), bool(args.get("measure", True)), act)
            shift = np.asarray(ent.offset, dtype=np.float64)
            ctrl = (built["ctrl"] + shift) * scale
            box = cage.bbox()
            diag_mm = float(np.linalg.norm(np.array(box[3:]) - np.array(box[:3]))) * scale
            path = convert.write_patches(ctrl)
            moved_box = [(built["bbox"][i] + shift[i % 3]) * scale for i in range(6)]
            try:
                act.step("sewing the patches into a body", 0.6)
                res = guard(work.kcall, "subd_brep", {"path": path, "count": int(len(ctrl)), "tolerance": max(1e-6, 1e-8 * diag_mm), "bbox": moved_box}, LONG)
            finally:
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    except jobs.Cancelled as err:
        raise CommandError(str(err))
    report = dict(built["report"])
    report["closed"] = bool(res["closed"])
    report["valid"] = bool(res["valid"])
    report["free_edges"] = int(res["free_edges"])
    report["free_bound_edges"] = int(res["free_bound_edges"])
    report["multiple_edges"] = int(res["multiple_edges"])
    report["faces"] = int(res["summary"]["faces"])
    report["volume"] = (res["volume"] / scale ** 3) if res.get("volume") is not None else None
    name = (ent.name or "Form") + (" solid" if res["closed"] else " shell")
    body = guard(work.new_body, ctx.d, res["id"], res["summary"], name, {"op": "subdconvert", "from": ent.name, "levels": report["levels"]}, list(ent.rgb or []))
    body.layer = ent.layer
    ctx.add(body)
    if not bool(args.get("keep", True)):
        ctx.d.erase_entity(ent.handle)
    if res["closed"]:
        ctx.say("SUBDCONVERT: closed solid of %d faces, %d free edges, valid %s, volume %s." % (report["faces"], report["free_bound_edges"], report["valid"], ctx.fd(report["volume"])))
    else:
        ctx.say("SUBDCONVERT: the form is not closed (%d free edges); a shell of %d faces was made, not a solid." % (report["free_edges"], report["faces"]))
    for note in report["notes"]:
        ctx.say("SUBDCONVERT: " + note)
    ctx.say("SUBDCONVERT: %d patches (%d regular, %d at extraordinary vertices or creases); largest normal jump across shared edges %.2f degrees; largest distance to the limit surface %.3g." % (report["patches"], report["regular_patches"], report["irregular_patches"], report["max_normal_angle_deg"], report.get("deviation_max", 0.0)))
    return {"handle": body.handle, "handles": [body.handle], "report": report}


@executes("subdconvert")
def subdconvert_exec(ctx, args):
    return run_convert(ctx, args)


@command("subdinfo", group=GROUP, label="Form Report", description="List the counts, creases, extraordinary vertices and conversion readiness of a form.", menu="Tools > Inquiry > Form Report", undoable=False)
def subdinfo_cmd(ctx):
    handles = yield from pick(ctx, "Select a form")
    if handles:
        run_info(ctx, {"handle": first_form(ctx, handles)})


def info_report(cage: Cage, sym, levels=2, agent=False) -> dict:
    an = cage.analysis()
    reasons = []
    if not an["manifold"]:
        reasons.append("The cage is not a manifold surface.")
    if not an["closed"]:
        reasons.append("The cage is open; it converts to a shell, not a solid.")
    try:
        total, need, leftover = convert.level_plan(cage, levels)
        patches = convert.patch_count(cage, total)
        cap = convert.MAX_PATCHES_AGENT if agent else convert.MAX_PATCHES
        if patches > cap:
            reasons.append("Level %d would make %d patches; the limit is %d." % (total, patches, cap))
    except SubdError as err:
        patches = None
        reasons.append(str(err))
    an["conversion"] = {"ready": not reasons, "reasons": reasons, "levels": levels, "patches": patches}
    an["symmetry_error"] = symmetry.check(cage, sym) if symmetry.active(sym) else None
    return an


def run_info(ctx, args):
    ent, cage = get_cage(ctx, args, False)
    r = info_report(cage, ent.sym, int(args.get("levels", 2)), is_agent(ctx))
    ctx.say("%s: %d vertices, %d faces, %d edges, %s, %d creases, %d extraordinary vertices." % (ent.name or "Form", r["vertices"], r["faces"], r["edges"], "closed" if r["closed"] else "open", r["creases"], r["extraordinary_count"]))
    return {"handle": ent.handle, "report": r}


@executes("subdinfo")
def subdinfo_exec(ctx, args):
    return run_info(ctx, args)
