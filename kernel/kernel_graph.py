import math
import os

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_CompCurve, BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Section
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_Copy,
    BRepBuilderAPI_GTransform,
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Transform,
)
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.GC import GC_MakeArcOfCircle
from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_TangentialDeflection, GCPnts_UniformAbscissa
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_BSplineCurve
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Intersection
from OCP.GeomConvert import GeomConvert, GeomConvert_CompCurveToBSplineCurve
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.collections import HArray1_gp_Pnt, HSequence_TopoDS_Shape, List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_GTrsf, gp_Mat, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec, gp_XYZ

import kernel_curves as kc
import kernel_mesh as mesh
import kernel_ops as ops
import kernel_props as props
import kernel_store as store

EPS = 1e-9
MAX_ITEMS = 20000
MAX_POINTS = 200000
MAX_PARTS = 5000


def pnt(v):
    return gp_Pnt(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def vec(v):
    return gp_Vec(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def xyz(p):
    return [p.X(), p.Y(), p.Z()]


def need(item, key):
    if item.get(key) is None:
        raise RuntimeError("Missing input %s." % key)
    return item[key]


def kind_of(shape):
    t = shape.ShapeType()
    if t in (TopAbs_WIRE, TopAbs_EDGE):
        return "curve"
    if t == TopAbs_FACE or t == TopAbs_SHELL:
        return "surface"
    if t == TopAbs_SOLID:
        return "brep"
    if t == TopAbs_VERTEX:
        return "point"
    if store.count_of(shape, TopAbs_SOLID):
        return "brep"
    if store.count_of(shape, TopAbs_FACE):
        return "surface"
    return "curve"


def describe(shape, kind=None):
    ident = store.put(shape)
    out = {"sid": ident, "kind": kind or kind_of(shape), "bbox": store.bbox_of(shape)}
    if out["kind"] == "curve":
        out["closed"] = curve_closed(shape)
    return out


def curve_closed(shape):
    try:
        if shape.ShapeType() == TopAbs_WIRE:
            return bool(TopoDS.Wire(shape).Closed())
        if shape.ShapeType() == TopAbs_EDGE:
            return bool(BRep_Tool.IsClosed_s(shape))
    except Exception:
        pass
    return False


def ordered_edges(wire):
    out = []
    ex = BRepTools_WireExplorer(wire)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def edges_of(shape):
    out = []
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    seen = store.ShapeMap()
    while ex.More():
        e = ex.Current()
        if seen.FindIndex(e) == 0:
            seen.Add(e)
            out.append(TopoDS.Edge(e))
        ex.Next()
    return out


def wires_from_edges(edges, tol=1e-6):
    seq = HSequence_TopoDS_Shape()
    for e in edges:
        seq.Append(e)
    out = HSequence_TopoDS_Shape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq, float(tol), False, out)
    return [TopoDS.Wire(out.Value(i)) for i in range(1, out.Length() + 1)]


def wire_from_edges(edges):
    mk = BRepBuilderAPI_MakeWire()
    for e in edges:
        mk.Add(e)
    if not mk.IsDone():
        wires = wires_from_edges(edges)
        if len(wires) != 1:
            raise RuntimeError("The edges do not join into one connected chain.")
        return wires[0]
    return mk.Wire()


def interp_edge(points, closed):
    n = len(points)
    if n < 2:
        raise RuntimeError("Interpolation needs at least two points.")
    arr = HArray1_gp_Pnt(1, n)
    for i, q in enumerate(points):
        arr.SetValue(i + 1, pnt(q))
    if closed and n >= 3:
        interp = GeomAPI_Interpolate(arr, True, 1e-7)
    else:
        interp = GeomAPI_Interpolate(arr, False, 1e-7)
    interp.Perform()
    if not interp.IsDone():
        raise RuntimeError("The points cannot be interpolated; check for duplicates.")
    return BRepBuilderAPI_MakeEdge(interp.Curve()).Edge()


def poly_wire(points, closed):
    pts = [pnt(q) for q in points]
    if len(pts) < 2:
        raise RuntimeError("A polyline needs at least two points.")
    mk = BRepBuilderAPI_MakeWire()
    n = len(pts)
    count = n if closed and n > 2 else n - 1
    for i in range(count):
        a, b = pts[i], pts[(i + 1) % n]
        if a.Distance(b) <= 1e-9:
            continue
        mk.Add(BRepBuilderAPI_MakeEdge(a, b).Edge())
    if not mk.IsDone():
        raise RuntimeError("The polyline has no length.")
    return mk.Wire()


def wire_of(spec):
    if not isinstance(spec, dict):
        raise RuntimeError("A curve input is missing.")
    if "sid" in spec:
        shape = store.shape_of(spec["sid"])
        t = shape.ShapeType()
        if t == TopAbs_WIRE:
            return TopoDS.Wire(shape)
        if t == TopAbs_EDGE:
            return BRepBuilderAPI_MakeWire(TopoDS.Edge(shape)).Wire()
        if t == TopAbs_FACE:
            return BRepTools.OuterWire_s(TopoDS.Face(shape))
        edges = edges_of(shape)
        if not edges:
            raise RuntimeError("The shape has no curve in it.")
        return wire_from_edges(edges)
    kind = spec.get("t")
    if kind == "line":
        a, b = pnt(spec["a"]), pnt(spec["b"])
        if a.Distance(b) <= 1e-9:
            raise RuntimeError("A line has no length.")
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(a, b).Edge()).Wire()
    if kind == "poly":
        return poly_wire(spec["pts"], bool(spec.get("closed")))
    if kind == "arc":
        arc = GC_MakeArcOfCircle(pnt(spec["a"]), pnt(spec["m"]), pnt(spec["b"]))
        if not arc.IsDone():
            raise RuntimeError("The three points of the arc are in a line.")
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(arc.Value()).Edge()).Wire()
    if kind == "circle":
        from OCP.gp import gp_Circ

        r = float(spec["r"])
        if r <= 1e-9:
            raise RuntimeError("A circle has no radius.")
        ax = gp_Ax2(pnt(spec["c"]), ops.direction(spec.get("n")), ops.direction(spec["x"])) if spec.get("x") else gp_Ax2(pnt(spec["c"]), ops.direction(spec.get("n")))
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(ax, r)).Edge()).Wire()
    if kind == "nurbs":
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(kc.to_geom(spec["curve"])).Edge()).Wire()
    raise RuntimeError("Unknown curve input.")


def shape_of(spec):
    if isinstance(spec, dict) and "sid" in spec:
        return store.shape_of(spec["sid"])
    return wire_of(spec)


def adaptor(wire):
    return BRepAdaptor_CompCurve(wire)


def tangent_at(ad, u):
    p, d = gp_Pnt(), gp_Vec()
    ad.D1(u, p, d)
    n = d.Magnitude()
    if n < 1e-12:
        return [0.0, 0.0, 0.0]
    return [d.X() / n, d.Y() / n, d.Z() / n]


def op_interp(item):
    pts = need(item, "pts")
    degree = int(item.get("degree", 3))
    closed = bool(item.get("closed"))
    if degree == 1:
        return describe(poly_wire(pts, closed), "curve")
    if degree != 3:
        raise RuntimeError("Interpolation supports degree 1 and 3.")
    edge = interp_edge(pts, closed)
    return describe(BRepBuilderAPI_MakeWire(edge).Wire(), "curve")


def op_nurbs(item):
    pts = need(item, "pts")
    degree = int(item.get("degree", 3))
    n = len(pts)
    if n < degree + 1:
        raise RuntimeError("A degree %d curve needs at least %d control points." % (degree, degree + 1))
    rec = {"degree": degree, "poles": [list(map(float, q)) for q in pts], "weights": [float(w) for w in item.get("weights") or []], "periodic": False}
    if item.get("closed"):
        rec["poles"] = rec["poles"] + [rec["poles"][i] for i in range(degree)]
        if rec["weights"]:
            rec["weights"] = rec["weights"] + rec["weights"][:degree]
        k = len(rec["poles"])
        rec["knots"] = [float(i) for i in range(k - degree + 1)]
        rec["mults"] = [degree + 1] + [1] * (len(rec["knots"]) - 2) + [degree + 1]
    return describe(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(kc.to_geom(rec)).Edge()).Wire(), "curve")


def op_rect(item):
    o = pnt(item.get("o", [0, 0, 0]))
    x = ops.direction(item.get("x"), (1.0, 0.0, 0.0))
    z = ops.direction(item.get("n"), (0.0, 0.0, 1.0))
    ax = gp_Ax2(o, z, x)
    xd, yd = ax.XDirection(), ax.YDirection()
    w, h = float(item["w"]), float(item["h"])
    x0, x1 = float(item.get("x0", 0.0)), float(item.get("x0", 0.0)) + w
    y0, y1 = float(item.get("y0", 0.0)), float(item.get("y0", 0.0)) + h

    def at(a, b):
        return [o.X() + a * xd.X() + b * yd.X(), o.Y() + a * xd.Y() + b * yd.Y(), o.Z() + a * xd.Z() + b * yd.Z()]

    return describe(poly_wire([at(x0, y0), at(x1, y0), at(x1, y1), at(x0, y1)], True), "curve")


def op_divide(item):
    wire = wire_of(item["curve"])
    ad = adaptor(wire)
    u0, u1 = ad.FirstParameter(), ad.LastParameter()
    total = GCPnts_AbscissaPoint.Length_s(ad, u0, u1)
    if total <= 1e-12:
        raise RuntimeError("The curve has no length.")
    if item.get("count") is not None:
        count = int(item["count"])
        if count < 1 or count > MAX_POINTS:
            raise RuntimeError("The count must be from 1 to %d." % MAX_POINTS)
        closed = curve_closed(wire)
        steps = count if closed else count + 1
        lengths = [total * i / count for i in range(steps)]
    else:
        step = float(need(item, "length"))
        if step <= 1e-9:
            raise RuntimeError("The length must be positive.")
        n = int(math.floor(total / step + 1e-9))
        if n + 1 > MAX_POINTS:
            raise RuntimeError("That length gives too many points.")
        lengths = [step * i for i in range(n + 1)]
    pts, tans, ts = [], [], []
    for s in lengths:
        if s <= 1e-12:
            u = u0
        elif s >= total - 1e-12:
            u = u1
        else:
            ap = GCPnts_AbscissaPoint(ad, s, u0)
            u = ap.Parameter() if ap.IsDone() else u0 + (u1 - u0) * s / total
        pts.append(xyz(ad.Value(u)))
        tans.append(tangent_at(ad, u))
        ts.append(s / total)
    return {"points": pts, "tangents": tans, "t": ts, "length": total}


def op_eval(item):
    wire = wire_of(item["curve"])
    ad = adaptor(wire)
    u0, u1 = ad.FirstParameter(), ad.LastParameter()
    total = GCPnts_AbscissaPoint.Length_s(ad, u0, u1)
    t = float(need(item, "t"))
    t = min(1.0, max(0.0, t)) if not curve_closed(wire) else t - math.floor(t)
    if item.get("by_length"):
        s = t * total
        ap = GCPnts_AbscissaPoint(ad, s, u0)
        u = ap.Parameter() if ap.IsDone() else u0 + (u1 - u0) * t
    else:
        u = u0 + (u1 - u0) * t
    p, d1, d2 = gp_Pnt(), gp_Vec(), gp_Vec()
    ad.D2(u, p, d1, d2)
    n = d1.Magnitude()
    tan = [d1.X() / n, d1.Y() / n, d1.Z() / n] if n > 1e-12 else [0.0, 0.0, 0.0]
    kappa = d1.Crossed(d2).Magnitude() / (n**3) if n > 1e-12 else 0.0
    return {"point": xyz(p), "tangent": tan, "curvature": kappa, "u": u, "domain": [u0, u1], "length": total}


def op_length(item):
    wire = wire_of(item["curve"])
    gp = GProp_GProps()
    BRepGProp.LinearProperties_s(wire, gp)
    return {"length": gp.Mass(), "closed": curve_closed(wire)}


def op_closest(item):
    wire = wire_of(item["curve"])
    q = BRepBuilderAPI_MakeVertex(pnt(item["point"])).Vertex()
    d = BRepExtrema_DistShapeShape(q, wire)
    if not d.IsDone() or d.NbSolution() < 1:
        raise RuntimeError("No closest point was found.")
    p = d.PointOnShape2(1)
    param = 0.0
    try:
        edge = TopoDS.Edge(d.SupportOnShape2(1))
        u = d.ParOnEdgeS2(1)
        u = u[0] if isinstance(u, tuple) else u
        ad = adaptor(wire)
        before = 0.0
        for e in ordered_edges(wire):
            if e.IsSame(edge):
                edge = e
                break
            before += GCPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(e))
        eb = BRepAdaptor_Curve(edge)
        part = GCPnts_AbscissaPoint.Length_s(eb, eb.FirstParameter(), u)
        if edge.Orientation() == 1:
            part = GCPnts_AbscissaPoint.Length_s(eb) - part
        total = GCPnts_AbscissaPoint.Length_s(ad, ad.FirstParameter(), ad.LastParameter())
        param = (before + part) / total if total > 0 else 0.0
    except Exception:
        param = 0.0
    return {"point": xyz(p), "t": param, "distance": d.Value()}


def op_offset(item):
    wire = wire_of(item["curve"])
    dist = float(need(item, "distance"))
    join = GeomAbs_Intersection if str(item.get("corner", "sharp")) == "sharp" else GeomAbs_Arc
    closed = curve_closed(wire)
    mk = BRepOffsetAPI_MakeOffset(wire, join, not closed)
    mk.Perform(dist)
    if not mk.IsDone():
        raise RuntimeError("The offset failed; the curve may not be planar.")
    res = mk.Shape()
    edges = edges_of(res)
    if not edges:
        raise RuntimeError("The offset collapsed to nothing.")
    wires = wires_from_edges(edges, 1e-6)
    return {"shapes": [describe(w, "curve") for w in wires]}


def bspline_of_wire(wire):
    edges = ordered_edges(wire)
    comp = None
    for e in edges:
        ad = BRepAdaptor_Curve(e)
        curve = BRep_Tool.Curve_s(e, ad.FirstParameter(), ad.LastParameter())
        from OCP.Geom import Geom_TrimmedCurve

        piece = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, ad.FirstParameter(), ad.LastParameter()))
        piece.Transform(ad.Trsf())
        if e.Orientation() == 1:
            piece.Reverse()
        if comp is None:
            comp = GeomConvert_CompCurveToBSplineCurve(piece)
        elif not comp.Add(piece, 1e-6, True, False, 0):
            raise RuntimeError("The curve pieces cannot be joined smoothly.")
    return comp.BSplineCurve()


def op_extend(item):
    wire = wire_of(item["curve"])
    g = bspline_of_wire(wire)
    rec = kc.from_geom(g)
    length = float(need(item, "length"))
    ends = ["start", "end"] if item.get("end", "both") == "both" else [item["end"]]
    for which in ends:
        res = kc.extend({"curve": rec, "end": which, "length": length, "style": str(item.get("style", "line")), "tol": 1e-6})
        rec = res["curve"]
    return describe(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(kc.to_geom(rec)).Edge()).Wire(), "curve")


def op_join(item):
    specs = need(item, "curves")
    edges = []
    for s in specs:
        edges.extend(edges_of(wire_of(s)))
    wires = wires_from_edges(edges, float(item.get("tol", 1e-6)))
    return {"shapes": [describe(w, "curve") for w in wires]}


def op_explode(item):
    wire = wire_of(item["curve"])
    out = []
    for e in edges_of(wire):
        ed = describe(BRepBuilderAPI_MakeWire(e).Wire(), "curve")
        out.append(ed)
    return {"shapes": out}


def planar_face(wire):
    mk = BRepBuilderAPI_MakeFace(wire, True)
    if not mk.IsDone():
        raise RuntimeError("The curve is not closed and planar.")
    return mk.Face()


def op_area(item):
    wire = wire_of(item["curve"])
    if not curve_closed(wire):
        raise RuntimeError("The curve is not closed.")
    face = planar_face(wire)
    gp = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, gp)
    c = gp.CentreOfMass()
    return {"area": gp.Mass(), "centroid": xyz(c)}


def op_extrude(item):
    shape = shape_of(item["curve"])
    v = vec(need(item, "vector"))
    if v.Magnitude() <= 1e-9:
        raise RuntimeError("The extrusion vector is zero.")
    if shape.ShapeType() in (TopAbs_WIRE, TopAbs_EDGE) and item.get("cap"):
        wire = wire_of(item["curve"])
        if not curve_closed(wire):
            raise RuntimeError("A capped extrusion needs a closed curve.")
        shape = planar_face(wire)
    res = BRepPrimAPI_MakePrism(shape, v).Shape()
    return describe(res)


def op_loft(item):
    specs = need(item, "curves")
    if len(specs) < 2:
        raise RuntimeError("A loft needs at least two curves.")
    mk = BRepOffsetAPI_ThruSections(bool(item.get("solid")), bool(item.get("ruled")), 1e-6)
    for s in specs:
        mk.AddWire(wire_of(s))
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The loft failed; the curves may be incompatible.")
    return describe(mk.Shape())


def op_sweep(item):
    rail = wire_of(item["rail"])
    profiles = need(item, "profiles")
    mk = BRepOffsetAPI_MakePipeShell(rail)
    mk.SetMode(True)
    for p in profiles:
        mk.Add(wire_of(p), False, False)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The sweep failed; check that the profile touches the rail.")
    if item.get("solid"):
        mk.MakeSolid()
    return describe(mk.Shape())


def op_revolve(item):
    shape = shape_of(item["curve"])
    ax = gp_Ax1(pnt(item.get("origin", [0, 0, 0])), ops.direction(item.get("axis")))
    angle = float(item.get("degrees", 360.0))
    if abs(angle) <= 1e-9:
        raise RuntimeError("The revolve angle is zero.")
    res = BRepPrimAPI_MakeRevol(shape, ax, math.radians(angle), True).Shape()
    return describe(res)


def op_planar(item):
    specs = need(item, "curves")
    wires = [wire_of(s) for s in specs]
    areas = []
    for w in wires:
        if not curve_closed(w):
            raise RuntimeError("A boundary curve is not closed.")
        gp = GProp_GProps()
        BRepGProp.SurfaceProperties_s(planar_face(w), gp)
        areas.append(gp.Mass())
    order = sorted(range(len(wires)), key=lambda i: -areas[i])
    mk = BRepBuilderAPI_MakeFace(wires[order[0]], True)
    if not mk.IsDone():
        raise RuntimeError("The outer boundary is not planar.")
    for i in order[1:]:
        hole = wires[i]
        mk.Add(TopoDS.Wire(hole.Reversed()))
    if not mk.IsDone():
        raise RuntimeError("The boundaries do not make a planar surface.")
    from OCP.ShapeFix import ShapeFix_Face

    fx = ShapeFix_Face(mk.Face())
    fx.Perform()
    return describe(fx.Face(), "surface")


def face_of(spec):
    shape = store.shape_of(spec["sid"]) if isinstance(spec, dict) and "sid" in spec else None
    if shape is None:
        raise RuntimeError("A surface input is missing.")
    if shape.ShapeType() == TopAbs_FACE:
        return TopoDS.Face(shape)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    if not ex.More():
        raise RuntimeError("The input has no surface.")
    return TopoDS.Face(ex.Current())


def eval_face(face, u, v, bounds):
    u0, u1, v0, v1 = bounds
    uu, vv = u0 + (u1 - u0) * u, v0 + (v1 - v0) * v
    sl = BRepLProp_SLProps(BRepAdaptor_Surface(face), uu, vv, 1, 1e-9)
    p = sl.Value()
    du, dv = sl.D1U(), sl.D1V()
    if sl.IsNormalDefined():
        nd = sl.Normal()
        n = [nd.X(), nd.Y(), nd.Z()]
        if face.Orientation() == 1:
            n = [-c for c in n]
    else:
        n = [0.0, 0.0, 0.0]
    return {"point": xyz(p), "normal": n, "du": [du.X(), du.Y(), du.Z()], "dv": [dv.X(), dv.Y(), dv.Z()]}


def op_srf_divide(item):
    face = face_of(item["surface"])
    nu, nv = int(need(item, "u")), int(need(item, "v"))
    if nu < 1 or nv < 1 or (nu + 1) * (nv + 1) > MAX_POINTS:
        raise RuntimeError("The counts must be at least 1 and the grid under %d points." % MAX_POINTS)
    b = BRepTools.UVBounds_s(face)
    pts, nor, uv = [], [], []
    for i in range(nu + 1):
        row_p, row_n = [], []
        for j in range(nv + 1):
            e = eval_face(face, i / nu, j / nv, b)
            row_p.append(e["point"])
            row_n.append(e["normal"])
        pts.append(row_p)
        nor.append(row_n)
    return {"points": pts, "normals": nor}


def op_srf_eval(item):
    face = face_of(item["surface"])
    b = BRepTools.UVBounds_s(face)
    e = eval_face(face, min(1.0, max(0.0, float(need(item, "u")))), min(1.0, max(0.0, float(need(item, "v")))), b)
    e["domain"] = list(b)
    return e


def op_srf_closest(item):
    shape = store.shape_of(item["surface"]["sid"])
    q = BRepBuilderAPI_MakeVertex(pnt(item["point"])).Vertex()
    d = BRepExtrema_DistShapeShape(q, shape)
    if not d.IsDone() or d.NbSolution() < 1:
        raise RuntimeError("No closest point was found.")
    p = d.PointOnShape2(1)
    u = v = 0.0
    try:
        face = TopoDS.Face(d.SupportOnShape2(1))
        uu, vv = d.ParOnFaceS2(1)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        u = (uu - u0) / (u1 - u0) if u1 > u0 else 0.0
        v = (vv - v0) / (v1 - v0) if v1 > v0 else 0.0
    except Exception:
        pass
    return {"point": xyz(p), "u": u, "v": v, "distance": d.Value()}


def op_srf_boundary(item):
    face = face_of(item["surface"])
    outer = BRepTools.OuterWire_s(face)
    out = []
    ex = TopExp_Explorer(face, TopAbs_WIRE)
    while ex.More():
        w = TopoDS.Wire(ex.Current())
        d = describe(w, "curve")
        d["outer"] = bool(w.IsSame(outer))
        out.append(d)
        ex.Next()
    return {"shapes": out}


def frame_params(item):
    plane = item.get("plane") or {}
    return {"origin": plane.get("o", [0, 0, 0]), "axis": plane.get("n"), "xdir": plane.get("x")}


def op_prim(item):
    kind = str(need(item, "kind"))
    p = frame_params(item)
    if kind == "box":
        dx, dy, dz = float(item["dx"]), float(item["dy"]), float(item["dz"])
        o = p["origin"]
        ax = ops.frame(p)
        if item.get("centered"):
            xd, yd, zd = ax.XDirection(), ax.YDirection(), ax.Direction()
            p["origin"] = [
                o[0] - (dx * xd.X() + dy * yd.X() + dz * zd.X()) / 2,
                o[1] - (dx * xd.Y() + dy * yd.Y() + dz * zd.Y()) / 2,
                o[2] - (dx * xd.Z() + dy * yd.Z() + dz * zd.Z()) / 2,
            ]
        p.update(kind="box", dx=dx, dy=dy, dz=dz)
    elif kind == "sphere":
        p.update(kind="sphere", radius=float(item["radius"]))
    elif kind == "cylinder":
        p.update(kind="cylinder", radius=float(item["radius"]), height=float(item["height"]))
    else:
        raise RuntimeError("Unknown solid %s." % kind)
    return describe(ops.make_primitive(p), "brep")


def shapes_list(specs):
    out = ShapeList()
    for s in specs:
        out.Append(store.shape_of(s["sid"]))
    return out


def split_result(shape):
    solids = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        solids.append(TopoDS.Solid(ex.Current()))
        ex.Next()
    if solids:
        return solids
    if shape.ShapeType() == TopAbs_COMPOUND and not store.count_of(shape, TopAbs_FACE):
        return []
    return [shape]


def op_bool(item):
    op = str(need(item, "mode"))
    a, b = need(item, "a"), item.get("b") or []
    if not a:
        raise RuntimeError("The first list is empty.")
    cls = {"union": BRepAlgoAPI_Fuse, "difference": BRepAlgoAPI_Cut, "intersection": BRepAlgoAPI_Common}.get(op)
    if cls is None:
        raise RuntimeError("Unknown boolean %s." % op)
    if op == "union" and not b:
        b = a[1:]
        a = a[:1]
    if not b:
        raise RuntimeError("The second list is empty.")
    mk = cls()
    mk.SetArguments(shapes_list(a))
    mk.SetTools(shapes_list(b))
    mk.SetRunParallel(True)
    mk.SetNonDestructive(True)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The boolean failed; the shapes may overlap in a way the kernel cannot resolve.")
    mk.SimplifyResult(True, True, 1e-6)
    parts = split_result(mk.Shape())
    return {"shapes": [describe(s) for s in parts]}


def op_fillet(item):
    sid = item["brep"]["sid"]
    shape = store.shape_of(sid)
    radius = float(need(item, "radius"))
    if radius <= 1e-9:
        raise RuntimeError("The fillet radius must be positive.")
    maps = store.maps_of(sid)["edges"]
    which = item.get("edges")
    idx = list(range(maps.Extent())) if which in (None, "all") else [int(i) for i in which]
    mk = BRepFilletAPI_MakeFillet(shape)
    for i in idx:
        if not 0 <= i < maps.Extent():
            raise RuntimeError("Edge %d is outside the shape." % i)
        mk.Add(radius, TopoDS.Edge(maps.FindKey(i + 1)))
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The fillet failed; try a smaller radius or other edges.")
    return describe(mk.Shape(), "brep")


def op_props(item):
    sid = item["brep"]["sid"]
    res = props.mass_properties({"id": sid, "density": float(item.get("density", 1.0))})
    return {"volume": res.get("volume"), "area": res.get("area"), "centroid": res.get("centroid"), "mass": res.get("mass"), "closed": res.get("closed"), "valid": res.get("valid"), "note": res.get("note")}


def op_decon(item):
    sid = item["brep"]["sid"]
    shape = store.shape_of(sid)
    maps = store.maps_of(sid)
    nf, ne, nv = maps["faces"].Extent(), maps["edges"].Extent(), maps["vertices"].Extent()
    if nf + ne > MAX_PARTS:
        raise RuntimeError("The shape has too many parts to deconstruct.")
    faces = [describe(TopoDS.Face(maps["faces"].FindKey(i + 1)), "surface") for i in range(nf)]
    edges = [describe(BRepBuilderAPI_MakeWire(TopoDS.Edge(maps["edges"].FindKey(i + 1))).Wire(), "curve") for i in range(ne)]
    verts = []
    for i in range(nv):
        verts.append(xyz(BRep_Tool.Pnt_s(TopoDS.Vertex(maps["vertices"].FindKey(i + 1)))))
    return {"faces": faces, "edges": edges, "vertices": verts, "summary": store.summarize(shape)}


def op_x_cc(item):
    wa, wb = wire_of(item["a"]), wire_of(item["b"])
    tol = float(item.get("tol", 1e-6))
    d = BRepExtrema_DistShapeShape(wa, wb, tol)
    pts = []
    if d.IsDone() and d.NbSolution() > 0 and d.Value() <= tol * 10:
        for i in range(1, d.NbSolution() + 1):
            p = xyz(d.PointOnShape1(i))
            if not any(math.dist(p, q) < max(tol * 10, 1e-6) for q in pts):
                pts.append(p)
    return {"points": pts}


def plane_of(spec):
    o = pnt(spec.get("o", [0, 0, 0]))
    return gp_Pln(o, ops.direction(spec.get("n")))


def section_edges(shape, other):
    mk = BRepAlgoAPI_Section(shape, other, False)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The section failed.")
    return mk.Shape()


def op_x_cp(item):
    wire = wire_of(item["curve"])
    res = section_edges(wire, plane_of(item["plane"]))
    pts = []
    ex = TopExp_Explorer(res, TopAbs_VERTEX)
    while ex.More():
        p = xyz(BRep_Tool.Pnt_s(TopoDS.Vertex(ex.Current())))
        if not any(math.dist(p, q) < 1e-6 for q in pts):
            pts.append(p)
        ex.Next()
    return {"points": pts}


def section_curves(res):
    edges = edges_of(res)
    if not edges:
        return {"shapes": []}
    return {"shapes": [describe(w, "curve") for w in wires_from_edges(edges, 1e-6)]}


def op_x_bp(item):
    shape = store.shape_of(item["brep"]["sid"])
    return section_curves(section_edges(shape, plane_of(item["plane"])))


def op_x_bb(item):
    a = store.shape_of(item["a"]["sid"])
    b = store.shape_of(item["b"]["sid"])
    mk = BRepAlgoAPI_Section(a, b, False)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The section failed.")
    return section_curves(mk.Shape())


def matrix_trsf(m):
    if len(m) == 16:
        rows = [m[0:4], m[4:8], m[8:12]]
    elif len(m) == 12:
        rows = [m[0:4], m[4:8], m[8:12]]
    else:
        raise RuntimeError("A transform has 16 numbers.")
    r = [[float(c) for c in row[:3]] for row in rows]
    t = [float(row[3]) for row in rows]
    return r, t


def op_xf(item):
    shape = store.shape_of(item["shape"]["sid"])
    r, t = matrix_trsf(need(item, "matrix"))
    gt = gp_GTrsf()
    gt.SetVectorialPart(gp_Mat(r[0][0], r[0][1], r[0][2], r[1][0], r[1][1], r[1][2], r[2][0], r[2][1], r[2][2]))
    gt.SetTranslationPart(gp_XYZ(t[0], t[1], t[2]))
    cols = [math.sqrt(sum(r[i][j] ** 2 for i in range(3))) for j in range(3)]
    dots = [sum(r[i][a] * r[i][b] for i in range(3)) for a, b in ((0, 1), (0, 2), (1, 2))]
    det = (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )
    rigid = det > 0 and max(abs(c - cols[0]) for c in cols) < 1e-9 and max(abs(x) for x in dots) < 1e-9
    if rigid:
        tr = gp_Trsf()
        tr.SetValues(r[0][0], r[0][1], r[0][2], t[0], r[1][0], r[1][1], r[1][2], t[1], r[2][0], r[2][1], r[2][2], t[2])
        mk = BRepBuilderAPI_Transform(shape, tr, True)
    else:
        mk = BRepBuilderAPI_GTransform(shape, gt, True)
    if not mk.IsDone():
        raise RuntimeError("The transform failed.")
    return describe(mk.Shape())


def op_copy(item):
    out = describe(BRepBuilderAPI_Copy(store.shape_of(item["shape"]["sid"]), True, False).Shape())
    if item.get("summary"):
        out["summary"] = store.summarize(store.shape_of(out["sid"]))
    return out


def op_record(item):
    wire = wire_of(item["curve"])
    return {"curve": kc.from_geom(bspline_of_wire(wire))}


def op_info(item):
    shape = store.shape_of(item["shape"]["sid"])
    return {"summary": store.summarize(shape), "kind": kind_of(shape)}


def op_bounds(item):
    return {"bbox": store.bbox_of(store.shape_of(item["shape"]["sid"]))}


OPS = {
    "interp": op_interp,
    "nurbs": op_nurbs,
    "rect": op_rect,
    "divide": op_divide,
    "eval": op_eval,
    "length": op_length,
    "closest": op_closest,
    "offset": op_offset,
    "extend": op_extend,
    "join": op_join,
    "explode": op_explode,
    "area": op_area,
    "extrude": op_extrude,
    "loft": op_loft,
    "sweep": op_sweep,
    "revolve": op_revolve,
    "planar": op_planar,
    "srf_divide": op_srf_divide,
    "srf_eval": op_srf_eval,
    "srf_closest": op_srf_closest,
    "srf_boundary": op_srf_boundary,
    "prim": op_prim,
    "bool": op_bool,
    "fillet": op_fillet,
    "props": op_props,
    "decon": op_decon,
    "x_cc": op_x_cc,
    "x_cp": op_x_cp,
    "x_bp": op_x_bp,
    "x_bb": op_x_bb,
    "xf": op_xf,
    "copy": op_copy,
    "record": op_record,
    "info": op_info,
    "bounds": op_bounds,
    "wire": lambda item: describe(wire_of(item["curve"]), "curve"),
}


def batch(p):
    items = p.get("ops") or []
    if len(items) > MAX_ITEMS:
        raise RuntimeError("A batch holds at most %d operations." % MAX_ITEMS)
    out = []
    for item in items:
        name = item.get("op")
        fn = OPS.get(name)
        if fn is None:
            out.append({"error": "Unknown graph operation %s." % name})
            continue
        try:
            out.append(fn(item))
        except Exception as err:
            text = str(err).strip().splitlines()
            out.append({"error": text[0] if text else "The operation failed."})
    freed = store.free(p.get("free") or []) if p.get("free") else 0
    return {"results": out, "freed": freed}


def sample_curve(wire, linear, angular):
    pts = []
    for e in ordered_edges(wire):
        ad = BRepAdaptor_Curve(e)
        disc = GCPnts_TangentialDeflection(ad, float(angular), float(linear))
        seg = []
        for i in range(1, disc.NbPoints() + 1):
            q = disc.Value(i)
            seg.append((q.X(), q.Y(), q.Z()))
        if e.Orientation() == 1:
            seg.reverse()
        if pts and seg and math.dist(pts[-1], seg[0]) < 1e-7:
            seg = seg[1:]
        pts.extend(seg)
    return pts


def preview(p):
    folder = str(p.get("dir") or "")
    if not folder or not os.path.isabs(folder) or not os.path.isdir(folder):
        raise RuntimeError("The preview folder must be an existing absolute path.")
    out = []
    for n, item in enumerate(p.get("items") or []):
        sid = item.get("sid")
        try:
            shape = store.shape_of(sid)
            if item.get("kind") == "curve":
                box = store.bbox_of(shape) or [0, 0, 0, 1, 1, 1]
                diag = math.dist(box[:3], box[3:])
                pts = sample_curve(wire_of({"sid": sid}), max(diag * 0.0005, 1e-4), 0.2)
                out.append({"sid": sid, "polyline": [list(q) for q in pts][:MAX_POINTS]})
                continue
            box = store.bbox_of(shape) or [0, 0, 0, 1, 1, 1]
            diag = math.dist(box[:3], box[3:])
            linear = float(item.get("linear") or max(diag * 0.0008, 1e-3))
            angular = float(item.get("angular") or 0.3)
            path = os.path.join(folder, "p%d.mesh" % n)
            res = mesh.build(sid, linear, angular, path)
            out.append({"sid": sid, "path": path, "info": {k: res.get(k) for k in ("triangles", "faces", "edges") if isinstance(res, dict)}})
        except Exception as err:
            out.append({"sid": sid, "error": str(err).splitlines()[0] if str(err) else "failed"})
    return {"results": out}


def alive(p):
    return {"alive": [str(s) for s in p.get("ids") or [] if str(s) in store.SHAPES]}


METHODS = {"graph_batch": batch, "graph_preview": preview, "graph_alive": alive}
