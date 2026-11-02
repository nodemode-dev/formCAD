import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_NurbsConvert, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepLib import BRepLib_FindSurface
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling, BRepOffsetAPI_MakeOffsetShape, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffset import BRepOffset_Skin
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface, Geom_TrimmedCurve
from OCP.GeomAbs import GeomAbs_C0, GeomAbs_C2, GeomAbs_G1, GeomAbs_G2, GeomAbs_Arc, GeomAbs_Intersection
from OCP.GeomConvert import GeomConvert
from OCP.GeomFill import GeomFill, GeomFill_BSplineCurves, GeomFill_CurvedStyle, GeomFill_StretchStyle
from OCP.Law import Law_Interpol
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_REVERSED, TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_SHELL, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS as _Cast, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.collections import Array1_double, Array1_gp_Pnt, Array1_gp_Pnt2d, Array1_int, List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Elips, gp_Pnt2d, gp_Vec, gp_Trsf

import kernel_store as store
from kernel_ops import direction, input_history, pnt

class TopoDS:
    Edge_s = staticmethod(_Cast.Edge)
    Face_s = staticmethod(_Cast.Face)
    Vertex_s = staticmethod(_Cast.Vertex)
    Shell_s = staticmethod(_Cast.Shell)
    Wire_s = staticmethod(_Cast.Wire)
    Solid_s = staticmethod(_Cast.Solid)


MAX_POINTS = 200000
MAX_CURVES = 256
ORDERS = {"c0": GeomAbs_C0, "g0": GeomAbs_C0, "g1": GeomAbs_G1, "g2": GeomAbs_G2, "0": GeomAbs_C0, "1": GeomAbs_G1, "2": GeomAbs_G2}


def tolerances(p):
    try:
        tol = float(p["tol"])
        ang = float(p["angtol"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("The operation needs the document tolerance (tol) and angle tolerance (angtol).")
    if not (math.isfinite(tol) and math.isfinite(ang)) or tol < 1e-7 or ang <= 0.0:
        raise RuntimeError("The tolerances must be finite, the length at least 1e-7 mm and the angle above zero.")
    return tol, ang


def order_of(value, default="g0"):
    return ORDERS.get(str(value if value is not None else default).lower(), GeomAbs_C0)


def kind_edges(shape, kind=TopAbs_EDGE):
    out = []
    ex = TopExp_Explorer(shape, kind)
    seen = store.ShapeMap()
    while ex.More():
        sub = ex.Current()
        if seen.FindIndex(sub) == 0:
            seen.Add(sub)
            out.append(sub)
        ex.Next()
    return out


def edge_pieces(shape):
    return [TopoDS.Edge_s(e) for e in kind_edges(shape, TopAbs_EDGE)]


def bspline_edge(spec):
    poles = spec.get("poles") or []
    deg = int(spec.get("degree", 3))
    knots = [float(k) for k in spec.get("knots") or []]
    n = len(poles)
    if n < 2 or n > MAX_POINTS or deg < 1 or deg >= n:
        raise RuntimeError("A B-spline curve needs a degree below its number of poles.")
    if len(knots) != n + deg + 1:
        raise RuntimeError("A B-spline curve needs poles + degree + 1 knots.")
    distinct, mults = [], []
    for k in knots:
        if distinct and abs(k - distinct[-1]) < 1e-12:
            mults[-1] += 1
        else:
            distinct.append(k)
            mults.append(1)
    arr = Array1_gp_Pnt(1, n)
    for i, q in enumerate(poles):
        arr.SetValue(i + 1, pnt(q))
    ks = Array1_double(1, len(distinct))
    ms = Array1_int(1, len(distinct))
    for i, k in enumerate(distinct):
        ks.SetValue(i + 1, k)
        ms.SetValue(i + 1, mults[i])
    weights = spec.get("weights") or []
    if weights and len(weights) == n and any(abs(float(w) - 1.0) > 1e-12 for w in weights):
        wa = Array1_double(1, n)
        for i, w in enumerate(weights):
            wa.SetValue(i + 1, float(w))
        curve = Geom_BSplineCurve(arr, wa, ks, ms, deg, False)
    else:
        curve = Geom_BSplineCurve(arr, ks, ms, deg, False)
    return BRepBuilderAPI_MakeEdge(curve).Edge()


def circle_edge(spec):
    centre = pnt(spec["center"])
    normal = direction(spec.get("normal"))
    xdir = spec.get("xdir")
    ax = gp_Ax2(centre, normal, direction(xdir)) if xdir else gp_Ax2(centre, normal)
    r = float(spec["radius"])
    if r <= 1e-7:
        raise RuntimeError("A circle has no radius.")
    a0, a1 = spec.get("a0"), spec.get("a1")
    if a0 is None or a1 is None:
        return BRepBuilderAPI_MakeEdge(gp_Circ(ax, r)).Edge()
    a0, a1 = float(a0), float(a1)
    while a1 <= a0:
        a1 += 2 * math.pi
    return BRepBuilderAPI_MakeEdge(gp_Circ(ax, r), a0, a1).Edge()


def ellipse_edge(spec):
    centre = pnt(spec["center"])
    normal = direction(spec.get("normal"))
    major = spec["major"]
    ax = gp_Ax2(centre, normal, direction(major))
    a = math.sqrt(sum(float(c) ** 2 for c in major))
    b = a * float(spec["ratio"])
    if a <= 1e-7 or b <= 1e-7:
        raise RuntimeError("An ellipse has no size.")
    if b > a:
        ax = gp_Ax2(centre, normal, gp_Dir(ax.YDirection()))
        a, b = b, a
    p0, p1 = spec.get("p0"), spec.get("p1")
    if p0 is None or p1 is None:
        return BRepBuilderAPI_MakeEdge(gp_Elips(ax, a, b)).Edge()
    p0, p1 = float(p0), float(p1)
    while p1 <= p0:
        p1 += 2 * math.pi
    return BRepBuilderAPI_MakeEdge(gp_Elips(ax, a, b), p0, p1).Edge()


def line_edge(spec):
    a, b = pnt(spec["a"]), pnt(spec["b"])
    if a.Distance(b) <= 1e-7:
        raise RuntimeError("A line has no length.")
    return BRepBuilderAPI_MakeEdge(a, b).Edge()


def path_wire(spec):
    from OCP.GC import GC_MakeArcOfCircle

    wire = BRepBuilderAPI_MakeWire()
    segs = spec.get("segments") or []
    if not segs or len(segs) > MAX_POINTS:
        raise RuntimeError("A path needs segments.")
    for s in segs:
        if "line" in s:
            a, b = pnt(s["line"][0]), pnt(s["line"][1])
            if a.Distance(b) <= 1e-7:
                continue
            wire.Add(BRepBuilderAPI_MakeEdge(a, b).Edge())
        else:
            a, m, b = (pnt(q) for q in s["arc"])
            arc = GC_MakeArcOfCircle(a, m, b)
            if not arc.IsDone():
                raise RuntimeError("An arc of the path is degenerate.")
            wire.Add(BRepBuilderAPI_MakeEdge(arc.Value()).Edge())
    if not wire.IsDone():
        raise RuntimeError("The path segments do not join end to end.")
    return wire.Wire()


def edge_of_shape(spec):
    shape = store.shape_of(spec["id"])
    m = store.maps_of(spec["id"])["edges"]
    i = int(spec["index"])
    if not 0 <= i < m.Extent():
        raise RuntimeError("The edge index is outside the shape.")
    return TopoDS.Edge_s(m.FindKey(i + 1))


def curve_wire(spec):
    kind = spec.get("kind")
    if kind == "path":
        return path_wire(spec)
    if kind == "shape":
        held = store.shape_of(spec["id"])
        if held.ShapeType() == TopAbs_WIRE:
            return TopoDS.Wire_s(held)
        edges = kind_edges(held, TopAbs_EDGE)
        if not edges:
            raise RuntimeError("The stored shape has no edges.")
        mk = BRepBuilderAPI_MakeWire()
        for e in edges:
            mk.Add(TopoDS.Edge_s(e))
        return mk.Wire()
    if kind == "shape_edge":
        edge = edge_of_shape(spec)
    elif kind == "bspline":
        edge = bspline_edge(spec)
    elif kind == "circle":
        edge = circle_edge(spec)
    elif kind == "ellipse":
        edge = ellipse_edge(spec)
    elif kind == "line":
        edge = line_edge(spec)
    else:
        raise RuntimeError("Unknown curve kind %s." % kind)
    return BRepBuilderAPI_MakeWire(edge).Wire()


def curve_edge(spec):
    wire = curve_wire(spec)
    edges = edge_pieces(wire)
    if len(edges) == 1:
        return edges[0]
    raise RuntimeError("This operation needs a single smooth curve, not a chain of segments.")


def specs(p, key, minimum=1, maximum=MAX_CURVES):
    items = p.get(key) or []
    if not isinstance(items, list) or len(items) < minimum or len(items) > maximum:
        raise RuntimeError("Give at least %d curve(s) under %s." % (minimum, key))
    return items


def face_of(spec):
    maps = store.maps_of(spec["id"])["faces"]
    i = int(spec["index"])
    if not 0 <= i < maps.Extent():
        raise RuntimeError("The face index is outside the shape.")
    return TopoDS.Face_s(maps.FindKey(i + 1))


def tol_audit(shape, tol):
    worst = {"vertex": 0.0, "edge": 0.0, "face": 0.0}
    over = 0
    for name, kind in (("vertex", TopAbs_VERTEX), ("edge", TopAbs_EDGE), ("face", TopAbs_FACE)):
        ex = TopExp_Explorer(shape, kind)
        seen = store.ShapeMap()
        while ex.More():
            sub = ex.Current()
            if seen.FindIndex(sub) == 0:
                seen.Add(sub)
                if name == "vertex":
                    t = BRep_Tool.Tolerance_s(TopoDS.Vertex_s(sub))
                elif name == "edge":
                    t = BRep_Tool.Tolerance_s(TopoDS.Edge_s(sub))
                else:
                    t = BRep_Tool.Tolerance_s(TopoDS.Face_s(sub))
                worst[name] = max(worst[name], t)
                if t > tol * (1 + 1e-9):
                    over += 1
            ex.Next()
    worst["limit"] = tol
    worst["over"] = over
    worst["exceeded"] = over > 0
    return worst


def base_report(op, tol, ang, shape):
    return {"op": op, "tol": tol, "angtol": ang, "audit": tol_audit(shape, tol)}


def finish(op, shape, tol, ang, report=None, history=None):
    if shape is None or shape.IsNull():
        raise RuntimeError("The operation produced nothing.")
    ident = store.put(shape)
    rep = base_report(op, tol, ang, shape)
    if report:
        rep.update(report)
    out = {"id": ident, "summary": store.summarize(shape), "report": rep}
    if history is not None:
        out["history"] = history
    return out


def to_bspline_surface(face):
    nc = BRepBuilderAPI_NurbsConvert(face, True)
    conv = nc.Shape()
    f2 = TopoDS.Face_s(kind_edges(conv, TopAbs_FACE)[0])
    surf = BRep_Tool.Surface_s(f2)
    if not isinstance(surf, Geom_BSplineSurface):
        from OCP.Geom import Geom_BSplineSurface as B

        surf = B.DownCast_s(surf) if hasattr(B, "DownCast_s") else surf
    return surf, f2


def surface_distance_samples(surface_shape, points):
    worst = 0.0
    for q in points:
        v = BRepBuilderAPI_MakeVertex(q).Vertex()
        d = BRepExtrema_DistShapeShape(v, surface_shape)
        if d.IsDone():
            worst = max(worst, d.Value())
    return worst


def curve_points(edge, count=25):
    ad = BRepAdaptor_Curve(edge)
    a, b = ad.FirstParameter(), ad.LastParameter()
    return [ad.Value(a + (b - a) * i / (count - 1)) for i in range(count)]


def shell_of(shape):
    faces = kind_edges(shape, TopAbs_FACE)
    return faces


def order_wires(edges, tol):
    left = list(edges)
    chain = [left.pop(0)]
    while left:
        tail = chain[-1]
        end = ends_of(tail)[1]
        pick = None
        for i, e in enumerate(left):
            a, b = ends_of(e)
            if end.Distance(a) <= tol * 50:
                pick = (i, False)
                break
            if end.Distance(b) <= tol * 50:
                pick = (i, True)
                break
        if pick is None:
            raise RuntimeError("The boundary curves do not meet end to end within %.3g." % (tol * 50))
        e = left.pop(pick[0])
        chain.append(TopoDS.Edge_s(e.Reversed()) if pick[1] else e)
    return chain


def ends_of(edge):
    ad = BRepAdaptor_Curve(edge)
    a, b = ad.Value(ad.FirstParameter()), ad.Value(ad.LastParameter())
    return (b, a) if edge.Orientation() == TopAbs_REVERSED else (a, b)


def loft(p):
    tol, ang = tolerances(p)
    sections = [curve_wire(s) for s in specs(p, "sections", 2)]
    ruled = bool(p.get("ruled", False))
    closed = bool(p.get("closed", False))
    if closed and len(sections) < 3:
        raise RuntimeError("A closed loft needs at least three curves.")
    maker = BRepOffsetAPI_ThruSections(False, ruled, tol)
    maker.CheckCompatibility(True)
    maker.SetSmoothing(bool(p.get("smooth", not ruled)))
    maker.SetMaxDegree(int(p.get("max_degree", 8)))
    items = sections + ([sections[0]] if closed else [])
    for w in items:
        maker.AddWire(w)
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The loft failed; check that the curves have matching direction and a similar number of segments.")
    shape = maker.Shape()
    return finish("loft", shape, tol, ang, {"sections": len(sections), "ruled": ruled, "closed": closed})


def chord_fraction_points(edge, count):
    from OCP.GCPnts import GCPnts_AbscissaPoint

    ad = BRepAdaptor_Curve(edge)
    total = GCPnts_AbscissaPoint.Length_s(ad)
    out = []
    for i in range(count):
        s = total * i / (count - 1)
        ap = GCPnts_AbscissaPoint(ad, s, ad.FirstParameter())
        out.append(ap.Parameter())
    return ad, out


def sweep(p):
    tol, ang = tolerances(p)
    rail = curve_wire(p["rail"])
    profiles = [curve_wire(s) for s in specs(p, "profiles")]
    rail2 = p.get("rail2")
    maker = BRepOffsetAPI_MakePipeShell(rail)
    method = "one rail"
    frame = str(p.get("frame", "freeform")).lower()
    report = {"frame": frame}
    if rail2:
        method = "two rails"
        report.update(sweep_two_rail_setup(maker, rail, curve_wire(rail2), profiles, p, tol))
    elif frame == "frenet":
        maker.SetMode(True)
    elif frame == "fixed":
        maker.SetMode(gp_Ax2(pnt([0, 0, 0]), direction(p.get("axis"))))
    elif frame == "binormal":
        maker.SetMode(direction(p.get("axis")))
    else:
        maker.SetMode(False)
    corner = str(p.get("corner", "right")).lower()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_RightCorner, BRepBuilderAPI_RoundCorner, BRepBuilderAPI_Transformed

    maker.SetTransitionMode({"round": BRepBuilderAPI_RoundCorner, "transformed": BRepBuilderAPI_Transformed}.get(corner, BRepBuilderAPI_RightCorner))
    maker.SetTolerance(tol, tol, ang)
    if rail2:
        pass
    else:
        for w in profiles:
            maker.Add(w, False, bool(p.get("correct", False)))
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The sweep failed; the profile may be too far from the rail or the rail too sharp for this frame.")
    shape = maker.Shape()
    report["method"] = method
    report["error"] = float(maker.ErrorOnSurface()) if hasattr(maker, "ErrorOnSurface") else 0.0
    if rail2:
        rails = [rail, curve_wire(rail2)]
        report["rail_deviation"] = [max(surface_distance_samples(shape, curve_points(e, 21)) for e in edge_pieces(r)) for r in rails]
    return finish("sweep", shape, tol, ang, report)


def sweep_two_rail_setup(maker, rail, rail2, profiles, p, tol):
    maker.SetMode(rail2, True, __import__("OCP.BRepFill", fromlist=["BRepFill_NoContact"]).BRepFill_NoContact)
    e1, e2 = edge_pieces(rail)[0], edge_pieces(rail2)[0]
    ad1, par1 = chord_fraction_points(e1, 41)
    ad2, par2 = chord_fraction_points(e2, 41)
    base = None
    pts = []
    for i in range(41):
        d = ad1.Value(par1[i]).Distance(ad2.Value(par2[i]))
        if base is None:
            base = d
        pts.append((i / 40.0, d))
    if base is None or base <= 1e-9:
        raise RuntimeError("The two rails touch at their start; the sweep has no width there.")
    arr = Array1_gp_Pnt2d(1, len(pts))
    first = ad1.FirstParameter()
    last = ad1.LastParameter()
    for i, (s, d) in enumerate(pts):
        arr.SetValue(i + 1, gp_Pnt2d(first + (last - first) * s, d / base))
    law = Law_Interpol()
    law.Set(arr, False)
    for w in profiles[:1]:
        maker.SetLaw(w, law, False, False)
    return {"rail_gap_start": base, "rail_gap_end": pts[-1][1], "scaling": "profile scaled by the rail distance"}


def network(p):
    tol, ang = tolerances(p)
    us = [curve_edge(s) for s in specs(p, "u", 2)]
    vs = [curve_edge(s) for s in specs(p, "v", 2)]
    degree = int(p.get("degree", 3))
    mk = BRepOffsetAPI_MakeFilling(degree, int(p.get("points", 20)), int(p.get("iterations", 3)), False, tol / 10.0, tol, ang, 0.1, int(p.get("max_degree", 8)), int(p.get("segments", 9)))
    frame = [us[0], vs[-1], us[-1], vs[0]]
    inner = us[1:-1] + vs[1:-1]
    try:
        chain = order_wires(frame, tol)
    except RuntimeError:
        chain = order_wires([us[0], vs[0], us[-1], vs[-1]], tol)
    for e in chain:
        mk.Add(e, GeomAbs_C0, True)
    for e in inner:
        mk.Add(e, GeomAbs_C0, False)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The network surface could not be fitted; check that the u curves cross the v curves without touching each other.")
    face = mk.Shape()
    dev = 0.0
    for e in us + vs:
        dev = max(dev, surface_distance_samples(face, curve_points(e, 17)))
    rep = {"u": len(us), "v": len(vs), "g0_error": mk.G0Error(), "curve_deviation": dev, "within_tolerance": dev <= tol}
    return finish("network", face, tol, ang, rep)


def patch(p):
    tol, ang = tolerances(p)
    curves = [e for s in (p.get("curves") or []) for e in edge_pieces(curve_wire(s))]
    points = [pnt(q) for q in (p.get("points") or [])]
    supports = p.get("supports") or []
    if not curves and not points and not supports:
        raise RuntimeError("A patch needs curves, points or a support edge.")
    if len(curves) + len(supports) + len(points) < 1 or len(points) > 5000:
        raise RuntimeError("A patch needs curves or points.")
    mk = BRepOffsetAPI_MakeFilling(int(p.get("degree", 3)), int(p.get("samples", 15)), int(p.get("iterations", 3)), bool(p.get("anisotropic", False)), tol / 10.0, tol, ang, 0.1, int(p.get("max_degree", 8)), int(p.get("segments", 9)))
    bound = bool(p.get("bounded", True))
    for e in curves:
        mk.Add(e, order_of(p.get("order"), "g0"), bound)
    for s in supports:
        edge = edge_of_shape(s["edge"])
        face = face_of(s["face"])
        mk.Add(edge, face, order_of(s.get("order"), "g1"), True)
    for q in points:
        mk.Add(q)
    start = p.get("start")
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The patch could not be fitted; use fewer constraints or relax the order.")
    face = mk.Shape()
    rep = {"g0_error": mk.G0Error(), "g1_error": mk.G1Error(), "g2_error": mk.G2Error(), "g1_error_deg": math.degrees(mk.G1Error())}
    return finish("patch", face, tol, ang, rep)


def extrude_curve(p):
    tol, ang = tolerances(p)
    wire = curve_wire(p["curve"])
    vec = gp_Vec(*[float(c) for c in p["vector"]])
    if vec.Magnitude() <= 1e-7:
        raise RuntimeError("The extrusion vector is zero.")
    if p.get("cap"):
        probe = BRepLib_FindSurface(wire, tol, True, True)
        if not probe.Found():
            raise RuntimeError("A capped extrusion needs a closed planar curve.")
        face = BRepBuilderAPI_MakeFace(wire, True).Face()
        shape = BRepPrimAPI_MakePrism(face, vec).Shape()
    else:
        shape = BRepPrimAPI_MakePrism(wire, vec).Shape()
    return finish("extrude_curve", shape, tol, ang, {"length": vec.Magnitude(), "capped": bool(p.get("cap"))})


def revolve_curve(p):
    tol, ang = tolerances(p)
    wire = curve_wire(p["curve"])
    a, b = pnt(p["axis"][0]), pnt(p["axis"][1])
    if a.Distance(b) <= 1e-7:
        raise RuntimeError("The axis of revolution has no length.")
    axis = gp_Ax1(a, gp_Dir(gp_Vec(a, b)))
    sweep_angle = float(p.get("degrees", 360.0))
    if not 0 < abs(sweep_angle) <= 360.0:
        raise RuntimeError("The sweep angle must be between 0 and 360 degrees.")
    rad = math.radians(sweep_angle)
    shape = BRepPrimAPI_MakeRevol(wire, axis, rad).Shape() if abs(sweep_angle) < 360.0 else BRepPrimAPI_MakeRevol(wire, axis).Shape()
    return finish("revolve_curve", shape, tol, ang, {"degrees": sweep_angle})


def wire_area(wire, tol):
    probe = BRepLib_FindSurface(wire, tol, True, True)
    if not probe.Found():
        return None
    face = BRepBuilderAPI_MakeFace(wire, True).Face()
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return face, abs(props.Mass())


def planar(p):
    tol, ang = tolerances(p)
    wires = [curve_wire(s) for s in specs(p, "curves")]
    found = []
    for i, w in enumerate(wires):
        got = wire_area(w, tol)
        if got is None:
            raise RuntimeError("Curve %d is not closed and planar within the tolerance." % (i + 1))
        found.append((got[1], i, w, got[0]))
    found.sort(key=lambda t: -t[0])
    groups = []
    for area, i, w, face in found:
        placed = False
        for g in groups:
            outer_face = g["face"]
            probe = first_vertex_point(w)
            cl = BRepClass_FaceClassifier()
            cl.Perform(outer_face, probe, tol)
            if cl.State() == TopAbs_IN:
                g["holes"].append(w)
                placed = True
                break
        if not placed:
            groups.append({"wire": w, "face": face, "holes": []})
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    count = 0
    for g in groups:
        mk = BRepBuilderAPI_MakeFace(g["wire"], True)
        for h in g["holes"]:
            mk.Add(TopoDS.Wire_s(h.Reversed()))
        f = mk.Face()
        from OCP.ShapeFix import ShapeFix_Face

        fx = ShapeFix_Face(f)
        fx.FixOrientation()
        fx.Perform()
        builder.Add(comp, fx.Face())
        count += 1
    shape = kind_edges(comp, TopAbs_FACE)[0] if count == 1 else comp
    return finish("planar", shape, tol, ang, {"faces": count, "holes": sum(len(g["holes"]) for g in groups)})


def first_vertex_point(wire):
    ex = TopExp_Explorer(wire, TopAbs_VERTEX)
    return BRep_Tool.Pnt_s(TopoDS.Vertex_s(ex.Current()))


def edge_surface(p):
    tol, ang = tolerances(p)
    edges = [curve_edge(s) for s in specs(p, "curves", 2, 4)]
    style = GeomFill_StretchStyle if str(p.get("style", "curved")).lower() == "stretch" else GeomFill_CurvedStyle
    if len(edges) == 2:
        a = bs_of_edge(edges[0], tol / 10.0)
        b = bs_of_edge(edges[1], tol / 10.0)
        surf = GeomFill.Surface_s(a, b)
    else:
        chain = order_wires(edges, tol)
        arr = [bs_of_edge(e, tol / 10.0) for e in chain]
        if len(arr) == 3:
            gen = GeomFill_BSplineCurves(arr[0], arr[1], arr[2], style)
        else:
            gen = GeomFill_BSplineCurves(arr[0], arr[1], arr[2], arr[3], style)
        surf = gen.Surface()
    face = BRepBuilderAPI_MakeFace(surf, tol).Face()
    dev = 0.0
    for e in edges:
        dev = max(dev, surface_distance_samples(face, curve_points(e, 17)))
    return finish("edge_surface", face, tol, ang, {"curves": len(edges), "edge_deviation": dev, "within_tolerance": dev <= tol})


def bs_of_edge(edge, tol=1e-6):
    ad = BRepAdaptor_Curve(edge)
    curve = BRep_Tool.Curve_s(edge, ad.FirstParameter(), ad.LastParameter())
    trimmed = Geom_TrimmedCurve(curve, ad.FirstParameter(), ad.LastParameter())
    spline = GeomConvert.CurveToBSplineCurve_s(trimmed)
    if spline.IsRational():
        from OCP.GeomConvert import GeomConvert_ApproxCurve

        approx = GeomConvert_ApproxCurve(spline, tol, GeomAbs_C2, 64, 8)
        if approx.IsDone():
            return approx.Curve()
    return spline


def surface_direction(face, surf, edge):
    sas = ShapeAnalysis_Surface(surf)
    ad = BRepAdaptor_Curve(edge)
    mid = ad.Value((ad.FirstParameter() + ad.LastParameter()) / 2.0)
    uv = sas.ValueOfUV(mid, 1e-3)
    u0, u1, v0, v1 = surf.Bounds()
    cand = [("u", False, abs(uv.X() - u0)), ("u", True, abs(uv.X() - u1)), ("v", False, abs(uv.Y() - v0)), ("v", True, abs(uv.Y() - v1))]
    scale_u, scale_v = max(u1 - u0, 1e-12), max(v1 - v0, 1e-12)
    best = min(cand, key=lambda c: c[2] / (scale_u if c[0] == "u" else scale_v))
    return best[0] == "u", best[1]


def face_continuity_floor(shape):
    worst = None
    for i, f in enumerate(kind_edges(shape, TopAbs_FACE)):
        ad = BRepAdaptor_Surface(TopoDS.Face_s(f))
        if ad.UContinuity() == GeomAbs_C0 or ad.VContinuity() == GeomAbs_C0:
            worst = i
            break
    return worst


def offset(p):
    tol, ang = tolerances(p)
    shape = store.shape_of(p["id"])
    dist = float(p["distance"])
    if not math.isfinite(dist) or abs(dist) <= tol:
        raise RuntimeError("The offset distance must be larger than the tolerance.")
    bad = face_continuity_floor(shape)
    if bad is not None:
        raise RuntimeError("Face %d is only C0 (it has a kink inside it), and an offset needs every face to be at least C1; split the surface at the kink or rebuild it first." % (bad + 1))
    mk = BRepOffsetAPI_MakeOffsetShape()
    join = GeomAbs_Intersection if str(p.get("join", "arc")).lower() == "intersection" else GeomAbs_Arc
    try:
        mk.PerformByJoin(shape, dist, tol, BRepOffset_Skin, False, False, join, False)
    except Exception as err:
        raise RuntimeError("The offset failed (%s); try a smaller distance." % err)
    if not mk.IsDone():
        raise RuntimeError("The offset failed; try a smaller distance or split the surface at its sharp edges.")
    result = mk.Shape()
    dev = 0.0
    faces = kind_edges(shape, TopAbs_FACE)
    for f in faces[:1]:
        props = BRepAdaptor_Surface(TopoDS.Face_s(f))
        uu, vv = (props.FirstUParameter() + props.LastUParameter()) / 2, (props.FirstVParameter() + props.LastVParameter()) / 2
        q = props.Value(uu, vv)
        d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(q).Vertex(), result)
        if d.IsDone():
            dev = abs(d.Value() - abs(dist))
    return finish("offset", result, tol, ang, {"distance": dist, "centre_error": dev}, {"inputs": [{"id": p["id"], **input_history(mk, shape, store.maps_of(p["id"]), store.build_maps(result))}]})


def sheet_through(curve_spec, vector, extent):
    wire = curve_wire(curve_spec)
    v = gp_Vec(*[float(c) for c in vector])
    if v.Magnitude() <= 1e-9:
        raise RuntimeError("The projection direction is zero.")
    v.Normalize()
    mv = gp_Vec(-v.X() * extent, -v.Y() * extent, -v.Z() * extent)
    trsf = gp_Trsf()
    trsf.SetTranslation(mv)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    start = BRepBuilderAPI_Transform(wire, trsf, True).Shape()
    long_v = gp_Vec(v.X() * 2 * extent, v.Y() * 2 * extent, v.Z() * 2 * extent)
    return BRepPrimAPI_MakePrism(start, long_v).Shape()


def split(p):
    tol, ang = tolerances(p)
    target = store.shape_of(p["id"])
    tools = ShapeList()
    box = store.bbox_of(target) or [0, 0, 0, 1, 1, 1]
    extent = math.dist(box[:3], box[3:]) * 2.0 + 1.0
    for s in p.get("tool_curves") or []:
        tools.Append(sheet_through(s, p.get("direction") or [0, 0, 1], extent))
    for tid in p.get("tools") or []:
        tools.Append(store.shape_of(tid))
    if tools.Size() == 0:
        raise RuntimeError("Give curves (with a direction) or tool shapes to split with.")
    args = ShapeList()
    args.Append(target)
    mk = BRepAlgoAPI_Splitter()
    mk.SetArguments(args)
    mk.SetTools(tools)
    mk.SetFuzzyValue(tol)
    mk.SetToFillHistory(True)
    mk.SetRunParallel(True)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The split failed; the tool may not cross the surface.")
    result = mk.Shape()
    faces = kind_edges(result, TopAbs_FACE)
    pieces = []
    for f in faces:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, props)
        c = props.CentreOfMass()
        pieces.append({"area": abs(props.Mass()), "centre": [c.X(), c.Y(), c.Z()]})
    if len(faces) < 2:
        raise RuntimeError("The tool does not cut the surface; nothing was split.")
    remove = p.get("remove_points") or []
    drop = set()
    for q in remove:
        v = BRepBuilderAPI_MakeVertex(pnt(q)).Vertex()
        best = None
        for i, f in enumerate(faces):
            d = BRepExtrema_DistShapeShape(v, f)
            if d.IsDone() and (best is None or d.Value() < best[0]):
                best = (d.Value(), i)
        if best:
            drop.add(best[1])
    if drop and len(drop) >= len(faces):
        raise RuntimeError("That would remove every piece.")
    keep = [f for i, f in enumerate(faces) if i not in drop]
    if remove:
        sew = BRepBuilderAPI_Sewing(tol)
        for f in keep:
            sew.Add(f)
        sew.Perform()
        out = sew.SewedShape()
        return finish("trim", out, tol, ang, {"pieces": len(faces), "removed": sorted(drop), "kept": len(keep), "free_edges": sew.NbFreeEdges()})
    ids = []
    for i, f in enumerate(faces):
        ident = store.put(f)
        pieces[i]["id"] = ident
        pieces[i]["summary"] = store.summarize(f)
        pieces[i]["audit"] = tol_audit(f, tol)
        ids.append(ident)
    return {"pieces": pieces, "report": {"op": "split", "tol": tol, "angtol": ang, "pieces": len(pieces)}, "history": {"inputs": [{"id": p["id"], **input_history(mk, target, store.maps_of(p["id"]), store.build_maps(result))}]}}


class SewHistory:
    def __init__(self, sew):
        self.sew = sew

    def IsDeleted(self, s):
        return False

    def Modified(self, s):
        out = []
        try:
            if self.sew.IsModified(s):
                out.append(self.sew.Modified(s))
            elif self.sew.IsModifiedSubShape(s):
                out.append(self.sew.ModifiedSubShape(s))
        except Exception:
            pass
        return out

    def Generated(self, s):
        return []


def join(p):
    tol, ang = tolerances(p)
    ids = [str(i) for i in (p.get("ids") or [])]
    if not ids:
        raise RuntimeError("Give the shapes to join.")
    sew = BRepBuilderAPI_Sewing(tol, True, True, True, bool(p.get("non_manifold", False)))
    for i in ids:
        sew.Add(store.shape_of(i))
    sew.Perform()
    out = sew.SewedShape()
    if out.IsNull():
        raise RuntimeError("Nothing could be joined within the tolerance.")
    solid = False
    if p.get("solid", True) and sew.NbFreeEdges() == 0 and sew.NbMultipleEdges() == 0:
        shells = kind_edges(out, TopAbs_SHELL)
        if len(shells) == 1:
            from OCP.ShapeFix import ShapeFix_Solid

            mk = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells[0]))
            fx = ShapeFix_Solid(mk.Solid())
            fx.Perform()
            cand = fx.Solid()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(cand, props)
            if props.Mass() > 0:
                out = cand
                solid = True
    from kernel_diag import free_edge_polylines

    inputs = []
    result_maps = store.build_maps(out)
    for i in ids:
        inputs.append({"id": i, **input_history(SewHistory(sew), store.shape_of(i), store.maps_of(i), result_maps)})
    rep = {"free_edges": sew.NbFreeEdges(), "multiple_edges": sew.NbMultipleEdges(), "degenerated": sew.NbDegeneratedShapes(), "closed_solid": solid, "naked_edges": free_edge_polylines(out, tol)}
    return finish("join", out, tol, ang, rep, {"inputs": inputs})


METHODS = {"surf_loft": loft, "surf_sweep": sweep, "surf_network": network, "surf_patch": patch, "surf_extrude": extrude_curve, "surf_revolve": revolve_curve, "surf_planar": planar, "surf_edge": edge_surface, "surf_offset": offset, "surf_split": split, "surf_join": join}
