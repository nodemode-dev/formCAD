import math
import os
import struct

import numpy as np
import OCP.collections as col
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire, BRepBuilderAPI_NurbsConvert, BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface, Geom_TrimmedCurve
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.ShapeFix import ShapeFix_Edge, ShapeFix_Face
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SHELL
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shell
from OCP.gp import gp_Pnt

import kernel_3dm_brep as joined
import kernel_store as store
from kernel_curves import from_geom, to_geom
from kernel_surf import TopoDS, kind_edges

FCM_MAGIC = b"FCM1"
MAX_OBJECTS = 200000
MAX_FACES = 20000
KNOWN_ARCHIVE = 80
OLDEST_ARCHIVE = 2
FLOOR_TOL = 1e-6
CEIL_TOL = 1.0
UNIT_MM = {
    "Angstroms": 1e-7, "Nanometers": 1e-6, "Microns": 1e-3, "Millimeters": 1.0, "Centimeters": 10.0, "Decimeters": 100.0, "Meters": 1000.0, "Dekameters": 1e4,
    "Hectometers": 1e5, "Kilometers": 1e6, "Megameters": 1e9, "Gigameters": 1e12, "Microinches": 2.54e-5, "Mils": 0.0254, "Inches": 25.4, "Feet": 304.8,
    "Yards": 914.4, "Miles": 1609344.0, "NauticalMiles": 1852000.0,
}
WRITE_UNITS = {"mm": "Millimeters", "cm": "Centimeters", "m": "Meters", "in": "Inches", "ft": "Feet", "km": "Kilometers", "yd": "Yards", "mi": "Miles", "um": "Microns", "mil": "Mils"}


def lib3dm():
    try:
        import rhino3dm
    except ImportError:
        raise RuntimeError("The 3DM library (rhino3dm) is not installed in the kernel worker.")
    return rhino3dm


def tol_of(raw) -> float:
    return min(max(float(raw), FLOOR_TOL), CEIL_TOL)


def colour_of(attrs, layers) -> list | None:
    rh = lib3dm()
    if attrs.ColorSource == rh.ObjectColorSource.ColorFromObject:
        c = attrs.ObjectColor
        return [int(c[0]), int(c[1]), int(c[2])]
    return None


def group_knots(flat):
    ks, ms = [], []
    for k in flat:
        if ks and abs(k - ks[-1]) <= 1e-12 * max(1.0, abs(k)):
            ms[-1] += 1
        else:
            ks.append(float(k))
            ms.append(1)
    ms[0] += 1
    ms[-1] += 1
    return ks, ms


def curve_geom(nc, scale):
    p = int(nc.Degree)
    n = len(nc.Points)
    rational = bool(nc.IsRational)
    poles, weights = [], []
    for i in range(n):
        q = nc.Points[i]
        w = q.W if rational else 1.0
        if rational and not (w > 1e-12):
            raise RuntimeError("a control point has a weight of zero or less")
        poles.append([q.X / w * scale, q.Y / w * scale, q.Z / w * scale])
        weights.append(float(w))
    ks, ms = group_knots(nc.Knots.ToList())
    if sum(ms) != n + p + 1:
        raise RuntimeError("the knot vector does not match the control points")
    g = to_geom({"degree": p, "poles": poles, "weights": weights if rational else [], "knots": ks, "mults": ms, "periodic": False})
    dom = nc.Domain
    if g.FirstParameter() < dom.T0 - 1e-12 or g.LastParameter() > dom.T1 + 1e-12:
        g.Segment(float(dom.T0), float(dom.T1))
    return g


def surface_geom(ns, scale):
    pu, pv = int(ns.OrderU) - 1, int(ns.OrderV) - 1
    nu, nv = int(ns.Points.CountU), int(ns.Points.CountV)
    rational = bool(ns.IsRational)
    poles = col.Array2_gp_Pnt(1, nu, 1, nv)
    weights = col.Array2_double(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            q = ns.Points.GetControlPoint(i, j)
            w = q.W if rational else 1.0
            if rational and not (w > 1e-12):
                raise RuntimeError("a control point has a weight of zero or less")
            poles.SetValue(i + 1, j + 1, gp_Pnt(q.X / w * scale, q.Y / w * scale, q.Z / w * scale))
            weights.SetValue(i + 1, j + 1, float(w))
    uk, um = group_knots(ns.KnotsU.ToList())
    vk, vm = group_knots(ns.KnotsV.ToList())
    if sum(um) != nu + pu + 1 or sum(vm) != nv + pv + 1:
        raise RuntimeError("the knot vectors do not match the control points")
    ua, ub = col.Array1_double(1, len(uk)), col.Array1_int(1, len(um))
    va, vb = col.Array1_double(1, len(vk)), col.Array1_int(1, len(vm))
    for i, (k, m) in enumerate(zip(uk, um)):
        ua.SetValue(i + 1, k)
        ub.SetValue(i + 1, m)
    for i, (k, m) in enumerate(zip(vk, vm)):
        va.SetValue(i + 1, k)
        vb.SetValue(i + 1, m)
    g = Geom_BSplineSurface(poles, weights, ua, va, ub, vb, pu, pv, False, False) if rational else Geom_BSplineSurface(poles, ua, va, ub, vb, pu, pv, False, False)
    du, dv = ns.Domain(0), ns.Domain(1)
    if g.UKnot(1) < du.T0 - 1e-12 or g.UKnot(g.NbUKnots()) > du.T1 + 1e-12 or g.VKnot(1) < dv.T0 - 1e-12 or g.VKnot(g.NbVKnots()) > dv.T1 + 1e-12:
        g.Segment(float(du.T0), float(du.T1), float(dv.T0), float(dv.T1))
    return g


def new_nurbs_curve(g, scale):
    rh = lib3dm()
    work = Geom_BSplineCurve(g)
    if work.IsPeriodic():
        work.SetNotPeriodic()
    p = work.Degree()
    n = work.NbPoles()
    rational = bool(work.IsRational())
    nc = rh.NurbsCurve(3, rational, p + 1, n)
    for i in range(n):
        q = work.Pole(i + 1)
        w = work.Weight(i + 1) if rational else 1.0
        nc.Points[i] = rh.Point4d(q.X() * scale * w, q.Y() * scale * w, q.Z() * scale * w, w)
    flat = []
    for i in range(1, work.NbKnots() + 1):
        flat.extend([work.Knot(i)] * work.Multiplicity(i))
    flat = flat[1:-1]
    if len(flat) != len(nc.Knots):
        raise RuntimeError("the knot vector length is not what the 3DM curve expects")
    for i, k in enumerate(flat):
        nc.Knots[i] = float(k)
    return nc


def new_nurbs_surface(g, scale):
    rh = lib3dm()
    work = Geom_BSplineSurface(g)
    if work.IsUPeriodic():
        work.SetUNotPeriodic()
    if work.IsVPeriodic():
        work.SetVNotPeriodic()
    nu, nv = work.NbUPoles(), work.NbVPoles()
    rational = bool(work.IsURational() or work.IsVRational())
    ns = rh.NurbsSurface.Create(3, rational, work.UDegree() + 1, work.VDegree() + 1, nu, nv)
    if ns is None:
        raise RuntimeError("the 3DM library refused the surface size")
    for i in range(nu):
        for j in range(nv):
            q = work.Pole(i + 1, j + 1)
            w = work.Weight(i + 1, j + 1) if rational else 1.0
            ns.Points[i, j] = rh.Point4d(q.X() * scale * w, q.Y() * scale * w, q.Z() * scale * w, w)
    for lst, count, getk, getm in ((ns.KnotsU, work.NbUKnots(), work.UKnot, work.UMultiplicity), (ns.KnotsV, work.NbVKnots(), work.VKnot, work.VMultiplicity)):
        flat = []
        for i in range(1, count + 1):
            flat.extend([getk(i)] * getm(i))
        flat = flat[1:-1]
        if len(flat) != len(lst):
            raise RuntimeError("the knot vector length is not what the 3DM surface expects")
        for i, k in enumerate(flat):
            lst[i] = float(k)
    return ns


def unit_info(settings) -> dict:
    name = settings.ModelUnitSystem.name
    mm = UNIT_MM.get(name)
    return {"name": name, "mm": mm if mm else 1.0, "known": bool(mm)}


def settings_info(f) -> dict:
    s = f.Settings
    unit = unit_info(s)
    return {
        "archive_version": int(f.ArchiveVersion), "unit": unit,
        "abs_tol": float(s.ModelAbsoluteTolerance) * unit["mm"], "abs_tol_file": float(s.ModelAbsoluteTolerance),
        "angle_tol": float(s.ModelAngleToleranceRadians), "created_by": str(f.CreatedBy or ""), "application": str(f.ApplicationName or ""),
    }


def open_file(path):
    rh = lib3dm()
    version = rh.File3dm.ReadArchiveVersion(path)
    if not version or version < 0:
        raise RuntimeError("The file is not a readable 3DM archive.")
    if version < OLDEST_ARCHIVE:
        raise RuntimeError("The archive version %d is older than the oldest readable version (%d)." % (version, OLDEST_ARCHIVE))
    f = rh.File3dm.Read(path)
    if f is None:
        raise RuntimeError("The 3DM file could not be read (archive version %d)." % version)
    return f, int(version)


def layer_rows(f) -> list:
    rows = []
    for layer in f.Layers:
        c = layer.Color
        rows.append({"index": int(layer.Index), "name": str(layer.Name), "path": str(layer.FullPath or layer.Name), "color": [int(c[0]), int(c[1]), int(c[2])], "visible": bool(layer.Visible), "locked": bool(layer.Locked)})
    return rows


def kind_name(geom) -> str:
    return type(geom).__name__


def threedm_info(p):
    path = store.absolute_path(p.get("path"), (".3dm",), True)
    f, version = open_file(path)
    out = settings_info(f)
    counts = {}
    for obj in f.Objects:
        k = kind_name(obj.Geometry)
        counts[k] = counts.get(k, 0) + 1
    out["objects"] = counts
    out["object_count"] = sum(counts.values())
    out["layers"] = layer_rows(f)
    out["newer_than_known"] = version > KNOWN_ARCHIVE
    return out


def write_fmesh(path, verts, tris, points_only=False):
    v = np.ascontiguousarray(np.asarray(verts, dtype="<f8").reshape(-1, 3))
    t = np.ascontiguousarray(np.asarray(tris, dtype="<i4").reshape(-1, 3))
    with open(path, "wb") as fh:
        fh.write(FCM_MAGIC + struct.pack("<III", len(v), len(t), 1 if points_only else 0))
        fh.write(v.tobytes())
        fh.write(t.tobytes())


def read_fmesh(path):
    with open(path, "rb") as fh:
        head = fh.read(16)
        if len(head) < 16 or head[:4] != FCM_MAGIC:
            raise RuntimeError("A mesh file has the wrong header.")
        nv, nt, flags = struct.unpack("<III", head[4:16])
        if nv > 50_000_000 or nt > 100_000_000:
            raise RuntimeError("A mesh file is too large.")
        v = np.frombuffer(fh.read(nv * 24), dtype="<f8").reshape(nv, 3)
        t = np.frombuffer(fh.read(nt * 12), dtype="<i4").reshape(nt, 3)
    return v, t, bool(flags & 1)


def mesh_arrays(mesh, scale):
    verts = np.array([[v.X, v.Y, v.Z] for v in mesh.Vertices.ToPoint3dArray()], dtype=np.float64) * scale if len(mesh.Vertices) else np.zeros((0, 3))
    tris = []
    quads = 0
    faces = mesh.Faces
    for i in range(len(faces)):
        a, b, c, d = faces[i]
        tris.append((a, b, c))
        if c != d:
            tris.append((a, c, d))
            quads += 1
    return verts, np.array(tris, dtype=np.int32).reshape(-1, 3), quads


def edge_ends(brep):
    ends = {}
    for face in brep.Faces:
        for loop in face.Loops:
            for t in loop.Trims:
                ei = t.EdgeIndex
                if ei < 0 or ei in ends:
                    continue
                a, b = t.StartVertexIndex, t.EndVertexIndex
                ends[ei] = (b, a) if t.IsReversed else (a, b)
    return ends


def uv_rectangle(surf, curves, tol, seams=()):
    a0, a1, b0, b1 = surf.Bounds()
    pts = []
    wrap_u = wrap_v = False
    for curve in seams:
        cp = []
        for k in range(1, 6):
            q = curve.Value(curve.FirstParameter() + (curve.LastParameter() - curve.FirstParameter()) * k / 6.0)
            proj = GeomAPI_ProjectPointOnSurf(q, surf)
            if proj.NbPoints():
                cp.append(proj.LowerDistanceParameters())
        if cp:
            us = [a0 if surf.IsUClosed() and abs(p[0] - a1) <= 1e-6 * (a1 - a0) else p[0] for p in cp]
            vs = [b0 if surf.IsVClosed() and abs(p[1] - b1) <= 1e-6 * (b1 - b0) else p[1] for p in cp]
            if max(us) - min(us) <= 1e-6 * (a1 - a0):
                wrap_u = True
            elif max(vs) - min(vs) <= 1e-6 * (b1 - b0):
                wrap_v = True
    for curve in curves:
        a, b = curve.FirstParameter(), curve.LastParameter()
        for k in range(9):
            q = curve.Value(a + (b - a) * k / 8.0)
            proj = GeomAPI_ProjectPointOnSurf(q, surf)
            if proj.NbPoints() == 0 or proj.LowerDistance() > max(tol * 10.0, 1e-5):
                return None
            pts.append(proj.LowerDistanceParameters())
    if not pts:
        return None
    u0, u1 = max(min(p[0] for p in pts), a0), min(max(p[0] for p in pts), a1)
    v0, v1 = max(min(p[1] for p in pts), b0), min(max(p[1] for p in pts), b1)
    if wrap_u:
        u0, u1 = a0, a1
    if wrap_v:
        v0, v1 = b0, b1
    if u1 - u0 <= 1e-9 or v1 - v0 <= 1e-9:
        return None
    eu, ev = 5e-5 * (u1 - u0), 5e-5 * (v1 - v0)
    for u, v in pts:
        if not (abs(u - u0) <= eu or abs(u - u1) <= eu or abs(v - v0) <= ev or abs(v - v1) <= ev):
            return None
    return u0, u1, v0, v1


def vertex_shapes(brep, scale, tol):
    out = []
    for v in brep.Vertices:
        loc = v.Location
        out.append(BRepBuilderAPI_MakeVertex(gp_Pnt(loc.X * scale, loc.Y * scale, loc.Z * scale)).Vertex())
    return out


def analytic_curve(g, tol):
    from OCP.ElCLib import ElCLib
    from OCP.Geom import Geom_Circle, Geom_Line
    from OCP.GeomConvert import GeomConvert_CurveToAnaCurve
    from OCP.gp import gp_Dir, gp_Lin, gp_Vec

    limit = max(tol * 1e-3, 1e-7)
    a, b = g.FirstParameter(), g.LastParameter()
    pts = [g.Value(a + (b - a) * k / 16.0) for k in range(17)]
    chord = pts[0].Distance(pts[-1])
    if chord > tol:
        line = gp_Lin(pts[0], gp_Dir(gp_Vec(pts[0], pts[-1])))
        along = [ElCLib.Parameter_s(line, q) for q in pts]
        if all(line.Distance(q) <= limit for q in pts) and all(y > x for x, y in zip(along, along[1:])):
            return Geom_Line(line), 0.0, chord
    found = GeomConvert_CurveToAnaCurve.ComputeCircle_s(g, limit, a, b, 0.0, 0.0, 0.0)
    if found is None or not isinstance(found, Geom_Circle):
        return None
    full = 2.0 * math.pi
    for _ in range(2):
        circ = found.Circ()
        if any(circ.Distance(q) > limit for q in pts):
            return None
        turn = [ElCLib.Parameter_s(circ, q) for q in pts]
        steps = [(y - x) % full for x, y in zip(turn, turn[1:])]
        if all(0.0 < s < math.pi for s in steps):
            sweep = sum(steps)
            if chord <= limit:
                sweep = full
            if sweep > full + 1e-9:
                return None
            return found, turn[0], turn[0] + sweep
        found.Reverse()
    return None


def build_edges(brep, scale, tol, notes):
    ends = edge_ends(brep)
    verts = vertex_shapes(brep, scale, tol)
    builder = BRep_Builder()
    edges = {}
    geoms = {}
    for ei, e in enumerate(brep.Edges):
        if ei not in ends:
            continue
        try:
            nc = e.ToNurbsCurve()
            g = curve_geom(nc, scale)
            sv, ev = ends[ei]
            va, vb = verts[sv], verts[ev]
            p0, p1 = g.Value(g.FirstParameter()), g.Value(g.LastParameter())
            builder.UpdateVertex(va, max(BRep_Tool.Tolerance_s(va), BRep_Tool.Pnt_s(va).Distance(p0) * 1.01 + 1e-9))
            builder.UpdateVertex(vb, max(BRep_Tool.Tolerance_s(vb), BRep_Tool.Pnt_s(vb).Distance(p1) * 1.01 + 1e-9))
            if sv == ev and not e.IsClosed and p0.Distance(p1) > tol:
                raise RuntimeError("the edge starts and ends at one vertex but is not closed")
            exact = analytic_curve(g, tol)
            mk = BRepBuilderAPI_MakeEdge(exact[0], va, vb, exact[1], exact[2]) if exact else None
            if mk is not None and mk.IsDone():
                g = Geom_TrimmedCurve(exact[0], exact[1], exact[2])
            else:
                mk = BRepBuilderAPI_MakeEdge(g, va, vb, g.FirstParameter(), g.LastParameter())
            if not mk.IsDone():
                mk = BRepBuilderAPI_MakeEdge(g, g.FirstParameter(), g.LastParameter())
            if not mk.IsDone():
                raise RuntimeError("the edge could not be built")
            edges[ei] = mk.Edge()
            geoms[ei] = g
        except Exception as err:
            notes.append({"edge": ei, "message": str(err).splitlines()[0]})
    return edges, geoms


def loop_wire(loop, edges):
    mk = BRepBuilderAPI_MakeWire()
    count = 0
    for t in loop.Trims:
        if t.EdgeIndex < 0:
            continue
        e = edges.get(t.EdgeIndex)
        if e is None:
            raise RuntimeError("an edge of the loop is missing")
        if t.IsReversed:
            e = TopoDS.Edge_s(e.Reversed())
        mk.Add(e)
        count += 1
        if not mk.IsDone():
            raise RuntimeError("the edges of a loop do not join")
    if count == 0:
        raise RuntimeError("a loop has no edges")
    return mk.Wire()


def rebuild_face(face, surf, edges, geoms, tol):
    loops = list(face.Loops)
    outers = [lp for lp in loops if lp.LoopType.name == "Outer"]
    inners = [lp for lp in loops if lp.LoopType.name == "Inner"]
    if len(outers) != 1:
        raise RuntimeError("the face has %d outer loops" % len(outers))
    rect = None
    if not inners and outers[0].TrimCount <= 4:
        used = [t.EdgeIndex for t in outers[0].Trims if t.EdgeIndex >= 0]
        if used and all(ei in geoms for ei in used):
            rect = uv_rectangle(surf, [geoms[ei] for ei in sorted(set(used))], tol, [geoms[ei] for ei in set(used) if used.count(ei) > 1])
    built = None
    if rect:
        mk = BRepBuilderAPI_MakeFace(surf, rect[0], rect[1], rect[2], rect[3], tol)
        if mk.IsDone() and BRepCheck_Analyzer(mk.Face()).IsValid() and area_of(mk.Face()) > 0:
            built = mk.Face()
            how = "natural"
    if built is None:
        built = wire_face(surf, outers[0], inners, edges, tol, False)
        if not (BRepCheck_Analyzer(built).IsValid() and area_of(built) > 0):
            built = wire_face(surf, outers[0], inners, edges, tol, True)
        how = "trimmed"
    if face.OrientationIsReversed:
        built = TopoDS.Face_s(built.Reversed())
    return built, how


def wire_face(surf, outer, inners, edges, tol, inside):
    from OCP.TopExp import TopExp_Explorer

    mk = BRepBuilderAPI_MakeFace(surf, loop_wire(outer, edges), inside)
    if not mk.IsDone():
        raise RuntimeError("the outer loop does not fit the surface (%s)" % mk.Error().name)
    for lp in inners:
        mk.Add(loop_wire(lp, edges))
    built = mk.Face()
    fixer = ShapeFix_Edge()
    ex = TopExp_Explorer(built, TopAbs_EDGE)
    seen = set()
    while ex.More():
        e = TopoDS.Edge_s(ex.Current())
        key = e.__hash__()
        if key not in seen:
            seen.add(key)
            fixer.FixAddPCurve(e, built, False, tol)
        ex.Next()
    sf = ShapeFix_Face(built)
    sf.SetPrecision(tol)
    sf.Perform()
    built = TopoDS.Face_s(sf.Face())
    if not BRepCheck_Analyzer(built).IsValid():
        from OCP.ShapeFix import ShapeFix_Shape

        ss = ShapeFix_Shape(built)
        ss.SetPrecision(tol)
        ss.Perform()
        built = TopoDS.Face_s(kind_edges(ss.Shape(), TopAbs_FACE)[0])
    return built


def analytic_form(surf, tol):
    from OCP.Geom import Geom_ElementarySurface, Geom_Plane
    from OCP.GeomConvert import GeomConvert_SurfToAnaSurf

    limit = max(tol * 1e-3, 1e-7)
    conv = GeomConvert_SurfToAnaSurf(surf)
    exact = conv.ConvertToAnalytical(limit)
    if exact is None or not isinstance(exact, Geom_ElementarySurface) or conv.Gap() > limit:
        return None
    if isinstance(exact, Geom_Plane):
        return exact
    u0, u1, v0, v1 = surf.Bounds()
    um, vm = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
    mid = surf.Value(um, vm)
    turn = 0.0
    if surf.Value(u0, vm).Distance(surf.Value(u1, vm)) <= limit and surf.Value(u0, vm).Distance(mid) > tol:
        mark = surf.Value(u0, vm)
    elif surf.Value(um, v0).Distance(surf.Value(um, v1)) <= limit and surf.Value(um, v0).Distance(mid) > tol:
        mark = surf.Value(um, v0)
    else:
        mark, turn = mid, math.pi
    proj = GeomAPI_ProjectPointOnSurf(mark, exact)
    if proj.NbPoints() == 0:
        return None
    pos = exact.Position()
    pos.Rotate(pos.Axis(), proj.LowerDistanceParameters()[0] - turn)
    exact.SetPosition(pos)
    return exact


def true_area(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props, 1e-6)
    return props.Mass()


def exact_face(face, surf, built, edges, geoms, tol):
    exact = analytic_form(surf, tol)
    if exact is None:
        return None
    try:
        alt, how = rebuild_face(face, exact, edges, geoms, tol)
        if not BRepCheck_Analyzer(alt).IsValid():
            return None
        a, b = true_area(built), true_area(alt)
        if not (a > 0 and abs(a - b) <= 2e-5 * a):
            return None
    except Exception:
        return None
    return alt, how


def shape_of_faces(faces, tol, as_solid):
    if len(faces) == 1:
        sew = BRepBuilderAPI_Sewing(tol)
        sew.Add(faces[0])
        sew.Perform()
        shape = sew.SewedShape()
        if shape.IsNull():
            return faces[0], 0
        if as_solid and sew.NbFreeEdges() == 0:
            shells = kind_edges(shape, TopAbs_SHELL)
            if not shells and shape.ShapeType() == TopAbs_FACE:
                shell = TopoDS_Shell()
                BRep_Builder().MakeShell(shell)
                BRep_Builder().Add(shell, shape)
                shells = [shell]
            if shells:
                solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells[0])).Solid()
                BRepLib.OrientClosedSolid_s(solid)
                if BRepCheck_Analyzer(solid).IsValid():
                    return solid, 0
        return shape, 0
    sew = BRepBuilderAPI_Sewing(tol)
    for f in faces:
        sew.Add(f)
    sew.Perform()
    shape = sew.SewedShape()
    free = sew.NbFreeEdges()
    if as_solid and free == 0:
        from OCP.TopExp import TopExp_Explorer

        ex = TopExp_Explorer(shape, TopAbs_SHELL)
        if ex.More():
            solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current())).Solid()
            BRepLib.OrientClosedSolid_s(solid)
            return solid, free
    return shape, free


def import_brep(brep, scale, tol, label):
    rep = {"faces": len(brep.Faces), "built": 0, "natural": 0, "trimmed": 0, "failed": [], "edge_failures": [], "solid": bool(brep.IsSolid)}
    if len(brep.Faces) > MAX_FACES:
        raise RuntimeError("the Brep has more than %d faces" % MAX_FACES)
    edges, geoms = build_edges(brep, scale, tol, rep["edge_failures"])
    built = []
    for fi, face in enumerate(brep.Faces):
        try:
            ns = face.UnderlyingSurface().ToNurbsSurface()
            if ns is None:
                raise RuntimeError("the surface has no NURBS form")
            surf = surface_geom(ns, scale)
            shape, how = rebuild_face(face, surf, edges, geoms, tol)
            if not BRepCheck_Analyzer(shape).IsValid():
                raise RuntimeError("the rebuilt face is not valid")
            shape, how = exact_face(face, surf, shape, edges, geoms, tol) or (shape, how)
            built.append(shape)
            rep["built"] += 1
            rep[how] += 1
        except Exception as err:
            rep["failed"].append({"face": fi, "message": "%s: %s" % (label, str(err).splitlines()[0] if str(err) else type(err).__name__)})
    if not built:
        return None, rep
    shape, free = shape_of_faces(built, tol, bool(brep.IsSolid) and not rep["failed"])
    rep["free_edges"] = int(free)
    return shape, rep


def convert_object(obj, scale, tol, work_dir, index, rep_obj):
    rh = lib3dm()
    g = obj.Geometry
    attrs = obj.Attributes
    kind = kind_name(g)
    item = {"i": index, "type": kind, "name": str(attrs.Name or ""), "layer": int(attrs.LayerIndex), "color": colour_of(attrs, None), "visible": bool(attrs.Visible) and attrs.Mode != rh.ObjectMode.Hidden, "uuid": str(attrs.Id), "key": str(attrs.GetUserString("formcad.key") or "")}
    if kind == "LineCurve":
        a, b = g.Line.From, g.Line.To
        item["kind"] = "line"
        item["start"] = [a.X * scale, a.Y * scale, a.Z * scale]
        item["end"] = [b.X * scale, b.Y * scale, b.Z * scale]
        rep_obj["status"] = "converted"
    elif kind == "PolylineCurve":
        pl = g.ToPolyline()
        pts = [[pl.PointAt(i).X * scale, pl.PointAt(i).Y * scale, pl.PointAt(i).Z * scale] for i in range(pl.Count)]
        item["kind"] = "polyline"
        item["points"] = pts
        item["closed"] = bool(g.IsClosed)
        rep_obj["status"] = "converted"
    elif kind in ("NurbsCurve", "ArcCurve", "PolyCurve", "Curve"):
        nc = g if kind == "NurbsCurve" else g.ToNurbsCurve()
        if nc is None:
            raise RuntimeError("the curve has no NURBS form")
        geom = curve_geom(nc, scale)
        item["kind"] = "curve"
        item["curve"] = from_geom(geom)
        rep_obj["status"] = "converted"
        if nc.IsPeriodic:
            rep_obj["detail"] = "periodic curve stored as a clamped closed curve (exact)"
        elif kind != "NurbsCurve":
            rep_obj["detail"] = "%s converted to its exact NURBS form" % kind
    elif kind in ("NurbsSurface", "PlaneSurface", "RevSurface", "SumSurface", "Surface"):
        ns = g if kind == "NurbsSurface" else g.ToNurbsSurface()
        if ns is None:
            raise RuntimeError("the surface has no NURBS form")
        sg = surface_geom(ns, scale)
        mk = BRepBuilderAPI_MakeFace(sg, tol)
        if not mk.IsDone():
            raise RuntimeError("the surface could not be made into a face")
        shape = mk.Face()
        item["kind"] = "solid"
        item["id"] = store.put(shape)
        item["summary"] = store.summarize(shape)
        rep_obj["status"] = "converted"
        rep_obj["detail"] = "untrimmed surface"
    elif kind in ("Brep", "Extrusion"):
        brep = g if kind == "Brep" else g.ToBrep(False)
        if brep is None:
            raise RuntimeError("the extrusion has no Brep form")
        shape, info = import_brep(brep, scale, tol, item["name"] or "object %d" % index)
        rep_obj["faces"] = info["faces"]
        rep_obj["failed_faces"] = info["failed"]
        rep_obj["edge_failures"] = info["edge_failures"]
        if shape is None:
            rep_obj["status"] = "skipped"
            rep_obj["detail"] = "no face could be rebuilt"
            item["kind"] = "skipped"
        else:
            item["kind"] = "solid"
            item["id"] = store.put(shape)
            item["summary"] = store.summarize(shape)
            if info["failed"]:
                rep_obj["status"] = "partial"
                rep_obj["detail"] = "%d of %d faces could not be rebuilt" % (len(info["failed"]), info["faces"])
            else:
                rep_obj["status"] = "converted"
                rep_obj["detail"] = "%d face%s rebuilt from surface and boundary curves (%d natural, %d trimmed)%s" % (info["built"], "" if info["built"] == 1 else "s", info["natural"], info["trimmed"], "; closed solid" if item["summary"].get("solids") else "")
    elif kind == "Mesh":
        verts, tris, quads = mesh_arrays(g, scale)
        path = os.path.join(work_dir, "m%d.fmesh" % index)
        write_fmesh(path, verts, tris)
        item["kind"] = "mesh"
        item["path"] = path
        item["vertices"] = int(len(verts))
        item["triangles"] = int(len(tris))
        rep_obj["status"] = "converted"
        if quads:
            rep_obj["detail"] = "%d quad faces split into triangles" % quads
    elif kind == "PointCloud":
        pts = np.array([[q.X, q.Y, q.Z] for q in g.GetPoints()], dtype=np.float64).reshape(-1, 3) * scale
        path = os.path.join(work_dir, "m%d.fmesh" % index)
        write_fmesh(path, pts, np.zeros((0, 3), dtype=np.int32), True)
        item["kind"] = "points"
        item["path"] = path
        item["vertices"] = int(len(pts))
        rep_obj["status"] = "converted"
    elif kind == "Point":
        loc = g.Location
        item["kind"] = "point"
        item["position"] = [loc.X * scale, loc.Y * scale, loc.Z * scale]
        rep_obj["status"] = "converted"
    else:
        item["kind"] = "skipped"
        rep_obj["status"] = "skipped"
        rep_obj["detail"] = SKIPPED.get(kind, "this object type is not read")
    return item


SKIPPED = {
    "SubD": "subdivision surfaces cannot be converted by the 3DM library",
    "InstanceReference": "block instances are not read",
    "TextDot": "text dots are not read",
    "Light": "lights are not read",
    "Hatch": "hatches are not read",
}


def threedm_read(p):
    path = store.absolute_path(p.get("path"), (".3dm",), True)
    work_dir = str(p.get("work_dir") or "")
    if not work_dir or not os.path.isdir(work_dir):
        raise RuntimeError("The reader needs a work folder for meshes.")
    f, version = open_file(path)
    info = settings_info(f)
    scale = info["unit"]["mm"]
    tol = tol_of(info["abs_tol"])
    objects = list(f.Objects)
    if len(objects) > MAX_OBJECTS:
        raise RuntimeError("The file holds more than %d objects." % MAX_OBJECTS)
    items, report = [], []
    counts = {"converted": 0, "partial": 0, "skipped": 0, "failed": 0}
    for i, obj in enumerate(objects):
        rep_obj = {"i": i, "type": kind_name(obj.Geometry), "name": str(obj.Attributes.Name or ""), "status": "failed"}
        try:
            item = convert_object(obj, scale, tol, work_dir, i, rep_obj)
            if item["kind"] != "skipped":
                items.append(item)
        except Exception as err:
            rep_obj["status"] = "failed"
            rep_obj["detail"] = str(err).splitlines()[0] if str(err) else type(err).__name__
        counts[rep_obj["status"]] = counts.get(rep_obj["status"], 0) + 1
        report.append(rep_obj)
    notes = []
    if not info["unit"]["known"]:
        notes.append("The file names no length unit; millimetres are assumed.")
    if version > KNOWN_ARCHIVE:
        notes.append("The archive version %d is newer than this reader knows (%d); content added by newer versions may be missing." % (version, KNOWN_ARCHIVE))
    failed_faces = [dict(x, object=r["i"]) for r in report for x in r.get("failed_faces", [])]
    info.update({"layers": layer_rows(f), "items": items, "report": report, "counts": counts, "failed_faces": failed_faces, "notes": notes, "sewing_tolerance": tol})
    return info


def collect_edges(shape):
    return [TopoDS.Edge_s(e) for e in kind_edges(shape, TopAbs_EDGE)]


def face_patch(face):
    bare = BRepBuilderAPI_Copy(face, True, False).Shape()
    conv = BRepBuilderAPI_NurbsConvert(bare, True)
    cf =TopoDS.Face_s(kind_edges(conv.Shape(), TopAbs_FACE)[0])
    surf = BRep_Tool.Surface_s(cf)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(cf)
    sg = Geom_BSplineSurface.DownCast_s(surf) if hasattr(Geom_BSplineSurface, "DownCast_s") else surf
    if not isinstance(sg, Geom_BSplineSurface):
        raise RuntimeError("the face surface has no B-spline form")
    sg = Geom_BSplineSurface(sg)
    if sg.IsUPeriodic():
        sg.SetUNotPeriodic()
    if sg.IsVPeriodic():
        sg.SetVNotPeriodic()
    a0, a1, b0, b1 = sg.Bounds()
    ru0, ru1, rv0, rv1 = max(u0, a0), min(u1, a1), max(v0, b0), min(v1, b1)
    if ru1 - ru0 > 1e-12 and rv1 - rv0 > 1e-12 and (abs(ru0 - a0) > 1e-9 or abs(ru1 - a1) > 1e-9 or abs(rv0 - b0) > 1e-9 or abs(rv1 - b1) > 1e-9):
        sg.Segment(ru0, ru1, rv0, rv1)
    return sg, cf


def area_of(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props.Mass()


def is_untrimmed(face, patch) -> bool:
    mk = BRepBuilderAPI_MakeFace(patch, 1e-7)
    if not mk.IsDone():
        return False
    a, b = area_of(face), area_of(mk.Face())
    return b > 0 and abs(a - b) <= 1e-6 * b


def edge_bspline(edge):
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    conv = BRepBuilderAPI_NurbsConvert(edge, True)
    e2 = TopoDS.Edge_s(kind_edges(conv.Shape(), TopAbs_EDGE)[0])
    ad = BRepAdaptor_Curve(e2)
    bs = Geom_BSplineCurve(ad.BSpline())
    a, b = ad.FirstParameter(), ad.LastParameter()
    if bs.IsPeriodic():
        bs.SetNotPeriodic()
    if a > bs.FirstParameter() + 1e-12 or b < bs.LastParameter() - 1e-12:
        bs.Segment(max(a, bs.FirstParameter()), min(b, bs.LastParameter()))
    return bs


def write_spec(rh, f, item, inv, layer_map, rep):
    from kernel_surf import curve_wire, edge_pieces

    spec = item["spec"]
    label = item.get("name") or "curve"
    edges = edge_pieces(curve_wire(spec))
    attrs = add_attrs(rh, f, item, layer_map)
    segs = spec.get("segments") if spec.get("kind") == "path" else None
    if spec.get("kind") == "line" or (segs and all("line" in s for s in segs)):
        if spec.get("kind") == "line":
            pts = [spec["a"], spec["b"]]
        else:
            pts = [segs[0]["line"][0]] + [s["line"][1] for s in segs]
        f.Objects.AddPolyline([rh.Point3d(q[0] * inv, q[1] * inv, q[2] * inv) for q in pts], attrs)
        return 1
    for e in edges:
        f.Objects.AddCurve(new_nurbs_curve(edge_bspline(e), inv), add_attrs(rh, f, item, layer_map))
    if len(edges) > 1:
        rep["lossy"].append({"object": label, "kind": "split_path", "count": len(edges), "message": "%s mixes lines and arcs; it is written as %d separate curves." % (label, len(edges))})
    return len(edges)


def add_attrs(rh, f, item, layer_map):
    attrs = rh.ObjectAttributes()
    if item.get("name"):
        attrs.Name = str(item["name"])
    li = layer_map.get(item.get("layer"))
    if li is not None:
        attrs.LayerIndex = li
    c = item.get("color")
    if c:
        attrs.ColorSource = rh.ObjectColorSource.ColorFromObject
        attrs.ObjectColor = (int(c[0]), int(c[1]), int(c[2]), 255)
    if item.get("hidden"):
        attrs.Mode = rh.ObjectMode.Hidden
    if item.get("key"):
        attrs.SetUserString("formcad.key", str(item["key"]))
    return attrs


def write_shape(rh, f, item, inv, tol, layer_map, rep):
    shape = store.shape_of(item["id"])
    label = item.get("name") or "body"
    parts = joined.body_parts(shape)
    written = 0
    for k, faces in enumerate(parts):
        sub = dict(item)
        if len(parts) > 1:
            sub["name"] = "%s part %d of %d" % (label, k + 1, len(parts))
        try:
            brep, info = joined.brep_of_faces(rh, faces, inv, tol, new_nurbs_curve, new_nurbs_surface)
        except Exception as err:
            reason = str(err).splitlines()[0] if str(err) else type(err).__name__
            written += write_faces(rh, f, sub, faces, inv, layer_map, rep, reason)
            continue
        f.Objects.AddBrep(brep, add_attrs(rh, f, sub, layer_map))
        written += 1
        rep["joined"].append(dict(info, object=sub.get("name") or label, solid=bool(brep.IsSolid)))
        if info["edge_gap"] > tol:
            rep["lossy"].append({"object": sub.get("name") or label, "kind": "edge_gap", "count": 1, "message": "An edge of %s lies %.3g mm from a face it bounds, more than the file tolerance of %.3g mm; the receiving program may show it as an open edge." % (sub.get("name") or label, info["edge_gap"], tol)})
    if len(parts) > 1 and written:
        rep["lossy"].append({"object": label, "kind": "separate_parts", "count": len(parts), "message": "%s holds %d separate bodies; each is written as its own polysurface." % (label, len(parts))})
    return written


def write_faces(rh, f, item, faces, inv, layer_map, rep, reason):
    label = item.get("name") or "body"
    trimmed = 0
    written = 0
    for k, face in enumerate(faces):
        sub = dict(item)
        if len(faces) > 1:
            sub["name"] = "%s face %d of %d" % (label, k + 1, len(faces))
        try:
            patch, cf = face_patch(face)
            ns = new_nurbs_surface(patch, inv)
            brep = rh.Brep.CreateFromSurface(ns)
            if brep is None:
                raise RuntimeError("the 3DM library refused the surface")
            if face.Orientation() == TopAbs_REVERSED:
                brep.Flip()
            attrs = add_attrs(rh, f, sub, layer_map)
            f.Objects.AddBrep(brep, attrs)
            written += 1
            if not is_untrimmed(cf, patch):
                trimmed += 1
                n = 0
                for e in collect_edges(cf):
                    if BRep_Tool.Degenerated_s(e):
                        continue
                    n += 1
                    tsub = dict(item)
                    tsub["name"] = "%s trim %d.%d" % (label, k + 1, n)
                    f.Objects.AddCurve(new_nurbs_curve(edge_bspline(e), inv), add_attrs(rh, f, tsub, layer_map))
        except Exception as err:
            rep["failed"].append({"object": label, "face": k, "message": str(err).splitlines()[0] if str(err) else type(err).__name__})
    if trimmed:
        rep["lossy"].append({"object": label, "kind": "trimmed_faces", "count": trimmed, "message": "%d trimmed face%s of %s written as an untrimmed surface plus separate trim curves, because the joined polysurface could not be built (%s). Use STEP to keep the trims." % (trimmed, "" if trimmed == 1 else "s", label, reason)})
    if len(faces) > 1 and written:
        rep["lossy"].append({"object": label, "kind": "unjoined_faces", "count": len(faces), "message": "%s has %d faces; they are written as separate surfaces, because the joined polysurface could not be built (%s), and must be joined again in the receiving program." % (label, len(faces), reason)})
    return written


def threedm_write(p):
    rh = lib3dm()
    path = store.absolute_path(p.get("path"), (".3dm",))
    version = int(p.get("version", 0) or 0)
    if version != 0 and not (OLDEST_ARCHIVE <= version <= KNOWN_ARCHIVE):
        raise RuntimeError("The archive version must be 0 (latest) or from %d to %d." % (OLDEST_ARCHIVE, KNOWN_ARCHIVE))
    unit_key = str(p.get("unit", "mm")).lower()
    unit_name = WRITE_UNITS.get(unit_key, "Millimeters")
    mm = UNIT_MM[unit_name]
    inv = 1.0 / mm
    f = rh.File3dm()
    f.Settings.ModelUnitSystem = getattr(rh.UnitSystem, unit_name)
    tol = float(p.get("abs_tol", 0.001))
    f.Settings.ModelAbsoluteTolerance = tol / mm
    f.Settings.ModelAngleToleranceRadians = float(p.get("angle_tol", 0.001))
    f.ApplicationName = "FormCAD"
    layer_map = {}
    for row in p.get("layers") or []:
        layer = rh.Layer()
        layer.Name = str(row["name"])
        c = row.get("color") or [0, 0, 0]
        layer.Color = (int(c[0]), int(c[1]), int(c[2]), 255)
        layer.Visible = bool(row.get("visible", True))
        layer.Locked = bool(row.get("locked", False))
        idx = f.Layers.Add(layer)
        layer_map[row["name"]] = idx if isinstance(idx, int) and idx >= 0 else len(layer_map)
    rep = {"written": 0, "failed": [], "lossy": [], "skipped": [], "warnings": [], "joined": []}
    for item in p.get("items") or []:
        kind = item.get("kind")
        try:
            attrs = add_attrs(rh, f, item, layer_map)
            if kind == "curve":
                g = to_geom(item["curve"])
                f.Objects.AddCurve(new_nurbs_curve(g, inv), attrs)
                rep["written"] += 1
            elif kind == "spec":
                rep["written"] += write_spec(rh, f, item, inv, layer_map, rep)
            elif kind == "line":
                a, b = item["start"], item["end"]
                f.Objects.AddLine(rh.Line(rh.Point3d(a[0] * inv, a[1] * inv, a[2] * inv), rh.Point3d(b[0] * inv, b[1] * inv, b[2] * inv)), attrs)
                rep["written"] += 1
            elif kind == "polyline":
                pts = [rh.Point3d(q[0] * inv, q[1] * inv, q[2] * inv) for q in item["points"]]
                if item.get("closed") and pts and (pts[0].X, pts[0].Y, pts[0].Z) != (pts[-1].X, pts[-1].Y, pts[-1].Z):
                    pts.append(pts[0])
                f.Objects.AddPolyline(pts, attrs)
                rep["written"] += 1
            elif kind == "point":
                q = item["position"]
                f.Objects.AddPoint(rh.Point3d(q[0] * inv, q[1] * inv, q[2] * inv), attrs)
                rep["written"] += 1
            elif kind == "shape":
                rep["written"] += write_shape(rh, f, item, inv, tol, layer_map, rep)
            elif kind in ("mesh", "points"):
                v, t, pts_only = read_fmesh(item["path"])
                if pts_only or kind == "points":
                    cloud = rh.PointCloud()
                    for q in v:
                        cloud.AppendNew().Location = rh.Point3d(q[0] * inv, q[1] * inv, q[2] * inv)
                    f.Objects.AddPointCloud(cloud, attrs)
                else:
                    mesh = rh.Mesh()
                    for q in v:
                        mesh.Vertices.Add(float(q[0] * inv), float(q[1] * inv), float(q[2] * inv))
                    for a, b, c in t:
                        mesh.Faces.AddFace(int(a), int(b), int(c))
                    f.Objects.AddMesh(mesh, attrs)
                    rep["lossy"].append({"object": item.get("name", "mesh"), "kind": "mesh_precision", "count": 1, "message": "3DM stores mesh vertices as 32-bit numbers; %s loses precision below about 1e-7 of its size." % (item.get("name") or "a mesh")})
                rep["written"] += 1
            else:
                rep["skipped"].append({"object": item.get("name", ""), "kind": str(kind)})
        except Exception as err:
            rep["failed"].append({"object": item.get("name", ""), "message": str(err).splitlines()[0] if str(err) else type(err).__name__})
    if not f.Write(path, version):
        raise RuntimeError("The 3DM file could not be written.")
    rep["path"] = path
    rep["version_requested"] = version
    rep["version_written"] = int(rh.File3dm.ReadArchiveVersion(path))
    rep["unit"] = unit_name
    return rep


def sample_points(shape, per_face=144, per_edge=24):
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface

    pts = []
    for fc in kind_edges(shape, TopAbs_FACE):
        face = TopoDS.Face_s(fc)
        ad = BRepAdaptor_Surface(face, True)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        n = max(3, int(math.sqrt(per_face)))
        from OCP.BRepClass import BRepClass_FaceClassifier
        from OCP.gp import gp_Pnt2d
        from OCP.TopAbs import TopAbs_IN, TopAbs_ON

        for i in range(n + 1):
            for j in range(n + 1):
                u, v = u0 + (u1 - u0) * i / n, v0 + (v1 - v0) * j / n
                cl = BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-9)
                if cl.State() in (TopAbs_IN, TopAbs_ON):
                    q = ad.Value(u, v)
                    pts.append((q.X(), q.Y(), q.Z()))
    for ec in collect_edges(shape):
        if BRep_Tool.Degenerated_s(ec):
            continue
        ad = BRepAdaptor_Curve(ec)
        a, b = ad.FirstParameter(), ad.LastParameter()
        for k in range(per_edge + 1):
            q = ad.Value(a + (b - a) * k / per_edge)
            pts.append((q.X(), q.Y(), q.Z()))
    return pts


def one_way(points, target):
    worst, total, n = 0.0, 0.0, 0
    for q in points:
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*q)).Vertex()
        d = BRepExtrema_DistShapeShape(v, target)
        if d.IsDone():
            dist = d.Value()
            worst = max(worst, dist)
            total += dist * dist
            n += 1
    return worst, total, n


def threedm_compare(p):
    a, b = store.shape_of(p.get("a")), store.shape_of(p.get("b"))
    per_face = int(p.get("samples", 144))
    wa, ta, na = one_way(sample_points(a, per_face), b)
    wb, tb, nb = one_way(sample_points(b, per_face), a)
    n = na + nb
    return {"max": max(wa, wb), "a_to_b": wa, "b_to_a": wb, "rms": math.sqrt((ta + tb) / n) if n else 0.0, "samples": n}


def curve_compare(p):
    ca, cb = to_geom(p["a"]), to_geom(p["b"])
    worst = 0.0
    n = int(p.get("samples", 200))
    for g, h in ((ca, cb), (cb, ca)):
        from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve

        a, b = g.FirstParameter(), g.LastParameter()
        for k in range(n + 1):
            q = g.Value(a + (b - a) * k / n)
            proj = GeomAPI_ProjectPointOnCurve(q, h)
            if proj.NbPoints():
                worst = max(worst, proj.LowerDistance())
            else:
                worst = max(worst, min(q.Distance(h.Value(h.FirstParameter())), q.Distance(h.Value(h.LastParameter()))))
    return {"max": worst, "samples": 2 * (n + 1)}


def threedm_verify(p):
    path = store.absolute_path(p.get("path"), (".3dm",), True)
    work_dir = str(p.get("work_dir") or "")
    back = threedm_read({"path": path, "work_dir": work_dir})
    by_key = {}
    for it in back["items"]:
        if it.get("key"):
            by_key.setdefault(it["key"], []).append(it)
    results = []
    for exp in p.get("expect") or []:
        key = exp["key"]
        row = {"key": key, "name": exp.get("name", ""), "kind": exp["kind"]}
        got = by_key.get(key, [])
        if exp["kind"] == "shape":
            solids = [x for x in got if x["kind"] == "solid"]
            row["found"] = len(solids)
            row["expected"] = int(exp.get("faces", 1))
            if not solids:
                row["missing"] = True
                results.append(row)
                continue
            comp = TopoDS_Compound()
            BRep_Builder().MakeCompound(comp)
            for x in solids:
                BRep_Builder().Add(comp, store.shape_of(x["id"]))
            cid = store.put(comp)
            try:
                row.update(threedm_compare({"a": exp["id"], "b": cid, "samples": int(p.get("samples", 144))}))
            finally:
                store.free([cid] + [x["id"] for x in solids])
        else:
            curves = [x for x in got if x["kind"] == "curve"]
            row["found"] = len(curves)
            if not curves:
                row["missing"] = True
                results.append(row)
                continue
            row.update(curve_compare({"a": exp["curve"], "b": curves[exp.get("order", 0) % len(curves)]["curve"]}))
        results.append(row)
    store.free([it["id"] for it in back["items"] if it.get("id")])
    return {"results": results, "archive_version": back["archive_version"], "unit": back["unit"], "abs_tol": back["abs_tol"], "counts": back["counts"]}


METHODS = {"threedm_info": threedm_info, "threedm_read": threedm_read, "threedm_write": threedm_write, "threedm_compare": threedm_compare, "threedm_curve_compare": curve_compare, "threedm_verify": threedm_verify}
