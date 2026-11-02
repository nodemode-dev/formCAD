import math
import os

from app.cmd.commands.draw import dnum
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.solid import work
from app.solid.work import SolidError

MAX_SIZE = 1e9
OPS = {"fuse": "Union", "cut": "Subtract", "common": "Intersect"}


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except SolidError as err:
        raise CommandError(str(err))


def positive(ctx, value, what):
    v = float(value)
    if not math.isfinite(v) or v <= ctx.d.tolerances["absolute"] or v > MAX_SIZE:
        raise CommandError("%s must be positive and finite." % what)
    return v


def xyz(p):
    return [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]


def bodies_of(ctx, handles):
    out = []
    for h in handles:
        e = ctx.d.get(int(h))
        if e is not None and e.kind == "solidbody" and not ctx.locked(e):
            out.append(e)
    return out


def any_solid(ctx, handles) -> bool:
    return any((ctx.d.get(int(h)) is not None and ctx.d.get(int(h)).kind == "solidbody") for h in handles)


def say_body(ctx, body, label):
    s = body.summary
    ctx.say("%s: %s with %d faces and %d edges." % (label, body.name or "solid", s.get("faces", 0), s.get("edges", 0)))


def add_box(ctx, origin, dx, dy, dz):
    positive(ctx, dx, "Length")
    positive(ctx, dy, "Width")
    positive(ctx, dz, "Height")
    body = guard(work.create_primitive, ctx, {"kind": "box", "origin": origin, "dx": dx, "dy": dy, "dz": dz}, "Box")
    say_body(ctx, body, "BOX")
    return body.handle


def corner_box(origin, p1, h):
    x, y = min(origin[0], p1[0]), min(origin[1], p1[1])
    z = origin[2] + (h if h < 0 else 0.0)
    return [x, y, z], abs(p1[0] - origin[0]), abs(p1[1] - origin[1]), abs(h)


@command("box", group="solids", label="Box", description="Solid box from two corners and a height, a centre, or a cube.", menu="Draw > Modeling > Box")
def box_cmd(ctx):
    r = yield ctx.point("Specify first corner of box", options=["Center"])
    centred = False
    if r.kind == "keyword" and r.value == "Center":
        r = yield ctx.point("Specify center of box")
        centred = True
    if r.kind != "point":
        return
    p0 = xyz(r.value)
    s = yield ctx.point("Specify other corner", options=["Cube", "Length"], base=p0, rect=True)
    if s.kind == "keyword" and s.value == "Cube":
        v = yield ctx.distance("Specify length", base=p0, positive=True)
        length = dnum(v, p0)
        if length is None:
            return
        dx = dy = dz = length
    elif s.kind == "keyword" and s.value == "Length":
        vals = []
        for msg in ("Specify length", "Specify width", "Specify height"):
            v = yield ctx.distance(msg, base=p0, positive=True)
            n = dnum(v, p0)
            if n is None:
                return
            vals.append(n)
        dx, dy, dz = vals
    elif s.kind == "point":
        q = xyz(s.value)
        h = yield ctx.distance("Specify height", base=p0)
        hv = dnum(h, p0)
        if hv is None:
            return
        if centred:
            origin = [p0[0] - abs(q[0] - p0[0]), p0[1] - abs(q[1] - p0[1]), p0[2] - abs(hv)]
            add_box(ctx, origin, 2 * abs(q[0] - p0[0]), 2 * abs(q[1] - p0[1]), 2 * abs(hv))
        else:
            origin, dx, dy, dz = corner_box(p0, q, hv)
            add_box(ctx, origin, dx, dy, dz)
        return
    else:
        return
    origin = [p0[0] - dx / 2, p0[1] - dy / 2, p0[2] - dz / 2] if centred else p0
    add_box(ctx, origin, dx, dy, dz)


@executes("box")
def box_exec(ctx, args):
    size = args.get("size")
    if args.get("cube") is not None:
        size = [float(args["cube"])] * 3
    if not size or len(size) != 3:
        raise CommandError("Give size as [length, width, height] or cube as one number.")
    if args.get("center") is not None:
        c = xyz(args["center"])
        origin = [c[0] - size[0] / 2, c[1] - size[1] / 2, c[2] - size[2] / 2]
    else:
        origin = xyz(args.get("corner") or [0, 0, 0])
    return {"handle": add_box(ctx, origin, *[float(v) for v in size])}


def add_cylinder(ctx, center, radius, height, axis=None):
    positive(ctx, radius, "Radius")
    h = float(height)
    positive(ctx, abs(h), "Height")
    c = xyz(center)
    spec = {"kind": "cylinder", "origin": c, "radius": radius, "height": abs(h)}
    if axis is not None:
        if len(axis) != 3 or not any(float(v) for v in axis):
            raise CommandError("axis is three numbers that are not all zero.")
        sign = -1.0 if h < 0 else 1.0
        spec["axis"] = [sign * float(v) for v in axis]
    elif h < 0:
        c[2] += h
    body = guard(work.create_primitive, ctx, spec, "Cylinder")
    say_body(ctx, body, "CYLINDER")
    return body.handle


@command("cylinder", aliases=("cyl",), group="solids", label="Cylinder", description="Solid cylinder from a base centre, a radius and a height.", menu="Draw > Modeling > Cylinder")
def cylinder_cmd(ctx):
    c = yield ctx.point("Specify center point of base")
    if c.kind != "point":
        return
    base = xyz(c.value)
    r = yield ctx.distance("Specify base radius or [Diameter]", options=["Diameter"], base=base, positive=True)
    if r.kind == "keyword" and r.value == "Diameter":
        r = yield ctx.distance("Specify diameter", base=base, positive=True)
        radius = (dnum(r, base) or 0.0) / 2
    else:
        radius = dnum(r, base)
    if not radius:
        return
    h = yield ctx.distance("Specify height", base=base)
    hv = dnum(h, base)
    if hv is None:
        return
    add_cylinder(ctx, base, radius, hv)


@executes("cylinder")
def cylinder_exec(ctx, args):
    return {"handle": add_cylinder(ctx, args.get("center") or [0, 0, 0], args.get("radius", 0), args.get("height", 0), args.get("axis"))}


def add_sphere(ctx, center, radius):
    positive(ctx, radius, "Radius")
    body = guard(work.create_primitive, ctx, {"kind": "sphere", "origin": xyz(center), "radius": radius}, "Sphere")
    say_body(ctx, body, "SPHERE")
    return body.handle


@command("sphere", group="solids", label="Sphere", description="Solid sphere from a centre and a radius.", menu="Draw > Modeling > Sphere")
def sphere_cmd(ctx):
    c = yield ctx.point("Specify center point")
    if c.kind != "point":
        return
    base = xyz(c.value)
    r = yield ctx.distance("Specify radius or [Diameter]", options=["Diameter"], base=base, positive=True)
    if r.kind == "keyword" and r.value == "Diameter":
        r = yield ctx.distance("Specify diameter", base=base, positive=True)
        radius = (dnum(r, base) or 0.0) / 2
    else:
        radius = dnum(r, base)
    if radius:
        add_sphere(ctx, base, radius)


@executes("sphere")
def sphere_exec(ctx, args):
    return {"handle": add_sphere(ctx, args.get("center") or [0, 0, 0], args.get("radius", 0))}


def add_cone(ctx, center, r1, r2, height):
    r1, r2, h = float(r1), float(r2), float(height)
    if r1 < 0 or r2 < 0 or max(r1, r2) <= ctx.d.tolerances["absolute"] or abs(r1 - r2) <= ctx.d.tolerances["absolute"]:
        raise CommandError("A cone needs two different radii, at least one positive.")
    positive(ctx, abs(h), "Height")
    c = xyz(center)
    if h < 0:
        c[2] += h
    body = guard(work.create_primitive, ctx, {"kind": "cone", "origin": c, "radius1": r1, "radius2": r2, "height": abs(h)}, "Cone")
    say_body(ctx, body, "CONE")
    return body.handle


@command("cone", group="solids", label="Cone", description="Solid cone or frustum from a base centre, radii and a height.", menu="Draw > Modeling > Cone")
def cone_cmd(ctx):
    c = yield ctx.point("Specify center point of base")
    if c.kind != "point":
        return
    base = xyz(c.value)
    r = yield ctx.distance("Specify base radius", base=base, positive=True)
    r1 = dnum(r, base)
    if not r1:
        return
    t = yield ctx.distance("Specify top radius", base=base, default=0.0, nonneg=True)
    r2 = dnum(t, base)
    if r2 is None:
        return
    h = yield ctx.distance("Specify height", base=base)
    hv = dnum(h, base)
    if hv is not None:
        add_cone(ctx, base, r1, r2, hv)


@executes("cone")
def cone_exec(ctx, args):
    return {"handle": add_cone(ctx, args.get("center") or [0, 0, 0], args.get("radius", 0), args.get("top_radius", 0.0), args.get("height", 0))}


def add_torus(ctx, center, major, minor):
    positive(ctx, major, "Ring radius")
    positive(ctx, minor, "Tube radius")
    if float(minor) >= float(major):
        raise CommandError("The tube radius must be smaller than the ring radius.")
    body = guard(work.create_primitive, ctx, {"kind": "torus", "origin": xyz(center), "major": major, "minor": minor}, "Torus")
    say_body(ctx, body, "TORUS")
    return body.handle


@command("torus", aliases=("tor",), group="solids", label="Torus", description="Solid ring from a centre, a ring radius and a tube radius.", menu="Draw > Modeling > Torus")
def torus_cmd(ctx):
    c = yield ctx.point("Specify center point")
    if c.kind != "point":
        return
    base = xyz(c.value)
    r = yield ctx.distance("Specify ring radius", base=base, positive=True)
    major = dnum(r, base)
    if not major:
        return
    t = yield ctx.distance("Specify tube radius", base=base, positive=True)
    minor = dnum(t, base)
    if minor:
        add_torus(ctx, base, major, minor)


@executes("torus")
def torus_exec(ctx, args):
    return {"handle": add_torus(ctx, args.get("center") or [0, 0, 0], args.get("major", 0), args.get("minor", 0))}


def profile_ents(ctx, handles):
    out = []
    for h in handles:
        e = ctx.d.get(int(h))
        if e is not None and e.kind in ("circle", "lwpolyline", "region") and not ctx.locked(e):
            out.append(e)
    if not out:
        raise CommandError("Select closed polylines, circles or regions.")
    return out


def run_extrude(ctx, handles, height, name="Extrusion", rgb=None):
    h = float(height)
    positive(ctx, abs(h), "Height")
    made = []
    for e in profile_ents(ctx, handles):
        body = guard(work.extrude, ctx, e, h, name, rgb)
        made.append(body.handle)
    ctx.say("EXTRUDE created %d solid(s)." % len(made))
    return made


@command("extrude", aliases=("ext",), group="solids", label="Extrude", description="Push a closed polyline, circle or region up or down into a solid.", menu="Draw > Modeling > Extrude")
def extrude_cmd(ctx):
    sel = yield ctx.select("Select closed objects to extrude")
    if sel.kind != "selection":
        return
    profile_ents(ctx, sel.value)
    h = yield ctx.distance("Specify height of extrusion")
    hv = dnum(h, None)
    if hv is not None:
        run_extrude(ctx, sel.value, hv)


@executes("extrude")
def extrude_exec(ctx, args):
    handles = [int(h) for h in args.get("handles") or []]
    if not handles:
        raise CommandError("Give the handles of the profiles to extrude.")
    rgb = args.get("rgb")
    if rgb is not None and (len(rgb) != 3 or not all(0.0 <= float(v) <= 1.0 for v in rgb)):
        raise CommandError("rgb is three numbers from 0 to 1.")
    return {"handles": run_extrude(ctx, handles, args.get("height", 0), str(args.get("name") or "Extrusion")[:120], rgb)}


def boolean_run(ctx, op, base_handles, tool_handles):
    bases = bodies_of(ctx, base_handles)
    tools = [b for b in bodies_of(ctx, tool_handles) if not bases or b.handle != bases[0].handle]
    if not bases or not tools:
        raise CommandError("Select solids for the operation.")
    body = guard(work.boolean, ctx, op, bases[0], tools)
    say_body(ctx, body, OPS[op].upper())
    return body.handle


def boolean_pick(ctx, op, handles):
    bodies = bodies_of(ctx, handles)
    if len(bodies) < 2:
        ctx.say("Select at least two solids.")
        return None
    return boolean_run(ctx, op, [bodies[0].handle], [b.handle for b in bodies[1:]])


def boolean_exec(ctx, op, base_handles, tool_handles):
    return {"handle": boolean_run(ctx, op, base_handles, tool_handles)}


@command("massprop", aliases=("massprops",), group="inquiry", label="Mass Properties", description="Volume, surface area, centre of mass and inertia of a solid.", menu="Tools > Inquiry > Region/Mass Properties", undoable=False)
def massprop_cmd(ctx):
    sel = yield ctx.select("Select a solid", pick_one=True)
    if sel.kind != "selection":
        return
    found = bodies_of(ctx, sel.value)
    if not found:
        ctx.say("Select a solid.")
        return
    report_mass(ctx, found[0], 1.0)


def report_mass(ctx, body, density):
    res = guard(work.mass_properties, ctx.d, body, density)
    if res.get("volume") is None:
        ctx.say("%s: %s" % (body.name or "Solid", res.get("note", "No volume.")))
    else:
        c = res["centroid"]
        ctx.say("Volume: %s" % ctx.fd(res["volume"]))
        ctx.say("Surface area: %s" % ctx.fd(res["area"]))
        ctx.say("Centroid: %s, %s, %s" % (ctx.fd(c[0]), ctx.fd(c[1]), ctx.fd(c[2])))
    return res


@executes("massprop")
def massprop_exec(ctx, args):
    found = bodies_of(ctx, [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") else [])])
    if not found:
        raise CommandError("Give the handle of a solid.")
    return report_mass(ctx, found[0], float(args.get("density", 1.0)))


@command("solidmove", aliases=("move3d",), group="solids", label="Move Solid", description="Move solids by a displacement.", menu="Modify > 3D Operations > Move")
def solidmove_cmd(ctx):
    sel = yield ctx.select("Select solids to move")
    if sel.kind != "selection":
        return
    found = bodies_of(ctx, sel.value)
    if not found:
        ctx.say("Select solids.")
        return
    base = yield ctx.point("Specify base point")
    if base.kind != "point":
        return
    to = yield ctx.point("Specify second point", base=base.value)
    if to.kind != "point":
        return
    delta = [to.value[0] - base.value[0], to.value[1] - base.value[1], 0.0]
    for b in found:
        guard(work.transform, ctx, b, {"translate": delta})


@executes("solidmove")
def solidmove_exec(ctx, args):
    found = bodies_of(ctx, [int(h) for h in args.get("handles") or []])
    if not found:
        raise CommandError("Give the handles of the solids to move.")
    p = {k: args[k] for k in ("translate", "rotate", "scale", "scale_origin", "matrix") if args.get(k) is not None}
    if not p:
        raise CommandError("Give translate, rotate, scale or matrix.")
    return {"handles": [guard(work.transform, ctx, b, p).handle for b in found]}


def export_model(ctx, path, ext):
    if ext in (".iges", ".igs"):
        raise CommandError("IGES files can be read but not written; use STEP.")
    full = os.path.realpath(os.path.expanduser(path))
    if os.path.splitext(full)[1].lower() not in (".step", ".stp"):
        full = os.path.splitext(full)[0] + ".step"
    from app.core import outputs

    try:
        full = outputs.checked(full, (".step", ".stp"))
    except outputs.OutputRefused as err:
        raise CommandError(str(err))
    sel = [e for e in (ctx.d.get(h) for h in ctx.doc.selection) if e is not None and e.kind == "solidbody"]
    items = sel or [e for e in ctx.d.entities(ctx.doc.current_space) if e.kind == "solidbody"]
    if not items:
        raise CommandError("There are no solids to export.")
    folder = os.path.dirname(full) or "."
    if not os.path.isdir(folder):
        raise CommandError("The folder does not exist.")
    res = guard(work.export_step, ctx.d, full, items)
    ctx.say("Exported %d solid(s) to %s." % (res.get("bodies", len(items)), full))
    return {"path": full, "bodies": len(items)}
