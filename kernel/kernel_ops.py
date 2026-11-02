import math

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeTorus
from OCP.GC import GC_MakeArcOfCircle
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.collections import List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax2, gp_Ax1, gp_Circ, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec

import kernel_store as store

MIN_SIZE = 1e-7
MAX_LOOP_POINTS = 100000


def pnt(v):
    return gp_Pnt(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def direction(v, default=(0.0, 0.0, 1.0)):
    v = v or default
    d = math.sqrt(sum(float(c) ** 2 for c in v))
    if d < MIN_SIZE:
        raise RuntimeError("A direction has zero length.")
    return gp_Dir(float(v[0]) / d, float(v[1]) / d, float(v[2]) / d)


def frame(p):
    origin = pnt(p.get("origin") or [0, 0, 0])
    axis = direction(p.get("axis"))
    xdir = p.get("xdir")
    if xdir:
        return gp_Ax2(origin, axis, direction(xdir))
    return gp_Ax2(origin, axis)


def positive(p, key):
    v = float(p.get(key, 0.0))
    if not math.isfinite(v) or v <= MIN_SIZE:
        raise RuntimeError("%s must be positive." % key)
    return v


def to_plane(p):
    plane = p.get("plane") or {}
    origin = pnt(plane.get("origin") or [0, 0, 0])
    normal = direction(plane.get("normal"))
    xdir = plane.get("xdir")
    ax = gp_Ax2(origin, normal, direction(xdir)) if xdir else gp_Ax2(origin, normal)
    return ax


def loop_wire(loop, ax):
    loc = ax.Location()
    xd, yd = ax.XDirection(), ax.YDirection()

    def to3(x, y):
        return gp_Pnt(loc.X() + x * xd.X() + y * yd.X(), loc.Y() + x * xd.Y() + y * yd.Y(), loc.Z() + x * xd.Z() + y * yd.Z())

    wire = BRepBuilderAPI_MakeWire()
    if "circle" in loop:
        c = loop["circle"]
        r = float(c["r"])
        if r <= MIN_SIZE:
            raise RuntimeError("A circle in the profile has no radius.")
        centre = to3(float(c["c"][0]), float(c["c"][1]))
        circ = gp_Circ(gp_Ax2(centre, ax.Direction(), ax.XDirection()), r)
        wire.Add(BRepBuilderAPI_MakeEdge(circ).Edge())
        return wire.Wire()
    verts = loop.get("vertices") or []
    if len(verts) < 2 or len(verts) > MAX_LOOP_POINTS:
        raise RuntimeError("A profile loop needs at least two vertices.")
    n = len(verts)
    count = 0
    for i in range(n):
        a = verts[i]
        b = verts[(i + 1) % n]
        pa = to3(float(a[0]), float(a[1]))
        pb = to3(float(b[0]), float(b[1]))
        if pa.Distance(pb) <= MIN_SIZE:
            continue
        bulge = float(a[2]) if len(a) > 2 else 0.0
        if abs(bulge) > 1e-12:
            chord = pa.Distance(pb)
            sagitta = abs(bulge) * chord / 2.0
            mx, my = (float(a[0]) + float(b[0])) / 2.0, (float(a[1]) + float(b[1])) / 2.0
            dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
            ln = math.hypot(dx, dy)
            sign = 1.0 if bulge > 0 else -1.0
            mid = to3(mx + sign * dy / ln * sagitta, my - sign * dx / ln * sagitta)
            arc = GC_MakeArcOfCircle(pa, mid, pb)
            if not arc.IsDone():
                raise RuntimeError("An arc segment of the profile is degenerate.")
            wire.Add(BRepBuilderAPI_MakeEdge(arc.Value()).Edge())
        else:
            wire.Add(BRepBuilderAPI_MakeEdge(pa, pb).Edge())
        count += 1
    if count < 2 and not (count == 1 and n == 2):
        raise RuntimeError("A profile loop is degenerate.")
    if not wire.IsDone():
        raise RuntimeError("A profile loop could not be joined into a wire.")
    return wire.Wire()


def profile_face(loops, ax):
    outers = [lp for lp in loops if lp.get("outer", True)]
    holes = [lp for lp in loops if not lp.get("outer", True)]
    if not outers:
        raise RuntimeError("The profile has no outer loop.")
    if len(outers) > 1:
        raise RuntimeError("The profile has more than one outer loop.")
    plane = gp_Pln(ax.Location(), ax.Direction())
    mk = BRepBuilderAPI_MakeFace(plane, loop_wire(outers[0], ax))
    for h in holes:
        mk.Add(loop_wire(h, ax))
    if not mk.IsDone():
        raise RuntimeError("The profile does not make a face.")
    fixer = ShapeFix_Face(mk.Face())
    fixer.FixOrientation()
    fixer.Perform()
    return fixer.Face()


def make_extrude(p):
    loops = p.get("loops") or []
    if not loops:
        raise RuntimeError("The profile has no loops.")
    ax = to_plane(p)
    face = profile_face(loops, ax)
    if p.get("vector"):
        vec = gp_Vec(float(p["vector"][0]), float(p["vector"][1]), float(p["vector"][2]))
    else:
        h = float(p.get("height", 0.0))
        if not math.isfinite(h) or abs(h) <= MIN_SIZE:
            raise RuntimeError("The extrusion height is zero.")
        vec = gp_Vec(ax.Direction()).Multiplied(h)
    if vec.Magnitude() <= MIN_SIZE:
        raise RuntimeError("The extrusion vector is zero.")
    return BRepPrimAPI_MakePrism(face, vec).Shape()


def make_primitive(p):
    kind = str(p.get("kind", ""))
    if kind == "box":
        ax = frame(p)
        dx, dy, dz = positive(p, "dx"), positive(p, "dy"), positive(p, "dz")
        return BRepPrimAPI_MakeBox(ax, dx, dy, dz).Shape()
    if kind == "cylinder":
        return BRepPrimAPI_MakeCylinder(frame(p), positive(p, "radius"), positive(p, "height")).Shape()
    if kind == "sphere":
        return BRepPrimAPI_MakeSphere(frame(p), positive(p, "radius")).Shape()
    if kind == "cone":
        r1 = float(p.get("radius1", 0.0))
        r2 = float(p.get("radius2", 0.0))
        if r1 < 0 or r2 < 0 or max(r1, r2) <= MIN_SIZE or abs(r1 - r2) <= MIN_SIZE:
            raise RuntimeError("A cone needs two different radii, at least one positive.")
        return BRepPrimAPI_MakeCone(frame(p), r1, r2, positive(p, "height")).Shape()
    if kind == "torus":
        major, minor = positive(p, "major"), positive(p, "minor")
        if minor >= major:
            raise RuntimeError("The tube radius must be smaller than the ring radius.")
        return BRepPrimAPI_MakeTorus(frame(p), major, minor).Shape()
    if kind == "extrude":
        return make_extrude(p)
    raise RuntimeError("Unknown primitive %s." % kind)


def primitive(p):
    shape = make_primitive(p)
    ident = store.put(shape)
    return {"id": ident, "summary": store.summarize(shape)}


def solid_check(shape):
    if store.count_of(shape, TopAbs_SOLID) == 0 and store.count_of(shape, TopAbs_FACE) == 0:
        raise RuntimeError("The result is empty.")


def index_list(mapping, lst):
    out = []
    for s in lst:
        idx = mapping.FindIndex(s)
        if idx > 0:
            out.append(idx - 1)
    return sorted(set(out))


def input_history(maker, in_shape, in_maps, out_maps):
    result = {}
    for key, kind in (("faces", TopAbs_FACE), ("edges", TopAbs_EDGE)):
        rows = {}
        src = in_maps[key]
        dst = out_maps[key]
        for i in range(1, src.Extent() + 1):
            sub = src.FindKey(i)
            deleted = bool(maker.IsDeleted(sub))
            to = []
            if not deleted:
                to = index_list(dst, list(maker.Modified(sub)))
                if not to:
                    idx = dst.FindIndex(sub)
                    if idx > 0:
                        to = [idx - 1]
            gen = index_list(dst, list(maker.Generated(sub)))
            for g in gen:
                if g not in to:
                    to.append(g)
            rows[str(i - 1)] = {"to": to, "deleted": deleted and not to}
        result[key] = rows
    return result


def boolean(p):
    op = str(p.get("op", ""))
    base_id = p.get("base")
    tool_ids = [str(t) for t in (p.get("tools") or [])]
    if op not in ("fuse", "cut", "common") or not base_id or not tool_ids:
        raise RuntimeError("A boolean needs op, base and at least one tool.")
    cls = {"fuse": BRepAlgoAPI_Fuse, "cut": BRepAlgoAPI_Cut, "common": BRepAlgoAPI_Common}[op]
    base = store.shape_of(base_id)
    args = ShapeList()
    args.Append(base)
    tools = ShapeList()
    for t in tool_ids:
        tools.Append(store.shape_of(t))
    maker = cls()
    maker.SetArguments(args)
    maker.SetTools(tools)
    maker.SetRunParallel(True)
    maker.SetNonDestructive(True)
    maker.SetToFillHistory(True)
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The boolean operation failed; the solids may overlap in a way the kernel cannot resolve.")
    unify = bool(p.get("unify", True))
    if unify:
        maker.SimplifyResult(True, True, 1e-6)
    result = maker.Shape()
    solid_check(result)
    ident = store.put(result)
    out_maps = store.maps_of(ident)
    inputs = []
    for sid in [base_id] + tool_ids:
        inputs.append({"id": sid, **input_history(maker, store.shape_of(sid), store.maps_of(sid), out_maps)})
    return {"id": ident, "summary": store.summarize(result), "history": {"inputs": inputs}}


def make_trsf(p):
    t = gp_Trsf()
    m = p.get("matrix")
    if m is not None:
        if len(m) != 12:
            raise RuntimeError("A matrix has twelve numbers: three rows of rotation then translation.")
        t.SetValues(*[float(v) for v in m])
        return t
    parts = []
    if p.get("scale") is not None:
        s = float(p["scale"])
        if not math.isfinite(s) or s <= 0:
            raise RuntimeError("The scale must be positive.")
        c = gp_Trsf()
        c.SetScale(pnt(p.get("scale_origin") or [0, 0, 0]), s)
        parts.append(c)
    if p.get("rotate"):
        r = p["rotate"]
        c = gp_Trsf()
        c.SetRotation(gp_Ax1(pnt(r.get("origin") or [0, 0, 0]), direction(r.get("axis"))), math.radians(float(r.get("degrees", 0.0))))
        parts.append(c)
    if p.get("translate"):
        v = p["translate"]
        c = gp_Trsf()
        c.SetTranslation(gp_Vec(float(v[0]), float(v[1]), float(v[2])))
        parts.append(c)
    for c in parts:
        t = c.Multiplied(t)
    return t


def transform(p):
    ident = p.get("id")
    src = store.shape_of(ident)
    maker = BRepBuilderAPI_Transform(src, make_trsf(p), True)
    if not maker.IsDone():
        raise RuntimeError("The transform failed.")
    result = maker.Shape()
    new_id = store.put(result)
    out_maps = store.maps_of(new_id)
    return {"id": new_id, "summary": store.summarize(result), "history": {"inputs": [{"id": ident, **input_history(maker, src, store.maps_of(ident), out_maps)}]}}


def shape_free(p):
    return {"freed": store.free(p.get("ids") or [])}


def shape_list(_p):
    return {"ids": sorted(store.SHAPES.keys())}


def shape_summary(p):
    return {"summary": store.summarize(store.shape_of(p.get("id")))}


METHODS = {"primitive": primitive, "boolean": boolean, "transform": transform, "shape_free": shape_free, "shape_list": shape_list, "shape_summary": shape_summary}
