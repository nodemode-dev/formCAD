import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve2d
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_MakeEdge,BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_NurbsConvert
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.Geom import Geom_BSplineSurface
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED, TopAbs_WIRE
from OCP.gp import gp_Pnt, gp_Pnt2d

import kernel_store as store
from kernel_surf import TopoDS, finish, kind_edges, tolerances

MAX_POLES = 40000
GRID_TARGET = 64
GRID_SPAN = 48
GRID_TRIMMED = 80
GRID_MAX = 128


def editable_face(ident):
    shape = store.shape_of(ident)
    faces = kind_edges(shape, TopAbs_FACE)
    if len(faces) != 1:
        raise RuntimeError("Control points can be edited on a single surface; this object has %d faces." % len(faces))
    bare = BRepBuilderAPI_Copy(faces[0], True, False).Shape()
    face = TopoDS.Face_s(kind_edges(bare, TopAbs_FACE)[0])
    surf = BRep_Tool.Surface_s(face)
    if not isinstance(surf, Geom_BSplineSurface):
        nc = BRepBuilderAPI_NurbsConvert(face, True)
        face = TopoDS.Face_s(kind_edges(nc.Shape(), TopAbs_FACE)[0])
        surf = BRep_Tool.Surface_s(face)
    if not isinstance(surf, Geom_BSplineSurface):
        raise RuntimeError("The surface could not be converted to a B-spline surface.")
    if surf.IsUPeriodic() or surf.IsVPeriodic():
        surf = Geom_BSplineSurface(surf)
        if surf.IsUPeriodic():
            surf.SetUNotPeriodic()
        if surf.IsVPeriodic():
            surf.SetVNotPeriodic()
    if surf.NbUPoles() * surf.NbVPoles() > MAX_POLES:
        raise RuntimeError("The surface has more than %d control points." % MAX_POLES)
    return face, surf


def is_natural(face, surf):
    a0, a1, b0, b1 = BRepTools.UVBounds_s(face)
    u0, u1, v0, v1 = surf.Bounds()
    du, dv = max(u1 - u0, 1e-12), max(v1 - v0, 1e-12)
    if abs(a0 - u0) / du > 1e-6 or abs(a1 - u1) / du > 1e-6 or abs(b0 - v0) / dv > 1e-6 or abs(b1 - v1) / dv > 1e-6:
        return False
    return len(kind_edges(face, TopAbs_WIRE)) == 1 and len(kind_edges(face, TopAbs_EDGE)) <= 4


def grid_params(knots, lo, hi, target, most):
    stops = [lo] + [k for k in knots if lo + 1e-12 < k < hi - 1e-12] + [hi]
    per = max(2, min(most, int(math.ceil(target / max(len(stops) - 1, 1)))))
    while (len(stops) - 1) * per + 1 > GRID_MAX and per > 1:
        per -= 1
    out = []
    for a, b in zip(stops[:-1], stops[1:]):
        out.extend(a + (b - a) * k / per for k in range(per))
    out.append(hi)
    return out


def net(p):
    face, surf = editable_face(p["id"])
    nu, nv = surf.NbUPoles(), surf.NbVPoles()
    poles = []
    weights = []
    rational = surf.IsURational() or surf.IsVRational()
    for i in range(1, nu + 1):
        for j in range(1, nv + 1):
            q = surf.Pole(i, j)
            poles.append([q.X(), q.Y(), q.Z()])
            if rational:
                weights.append(surf.Weight(i, j))
    natural = is_natural(face, surf)
    u0, u1, v0, v1 = surf.Bounds()
    if not natural:
        a0, a1, b0, b1 = BRepTools.UVBounds_s(face)
        u0, u1, v0, v1 = max(u0, a0), min(u1, a1), max(v0, b0), min(v1, b1)
    target, most = (GRID_TARGET, GRID_SPAN) if natural else (GRID_TRIMMED, GRID_TRIMMED)
    us = grid_params(list(surf.UKnots()), u0, u1, target, most)
    vs = grid_params(list(surf.VKnots()), v0, v1, target, most)
    mask = []
    if not natural:
        fwd = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
        cls = BRepClass_FaceClassifier()
        for u in us:
            for v in vs:
                cls.Perform(fwd, gp_Pnt2d(u, v), 1e-9)
                mask.append(1 if cls.State() in (TopAbs_IN, TopAbs_ON) else 0)
    return {
        "degree": [surf.UDegree(), surf.VDegree()], "count": [nu, nv], "poles": poles, "weights": weights,
        "uknots": list(surf.UKnotSequence()), "vknots": list(surf.VKnotSequence()),
        "trimmed": not natural, "reversed": face.Orientation() == TopAbs_REVERSED, "grid": {"u": us, "v": vs, "mask": mask},
    }


def retrim(face, surf, tol):
    fwd = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
    outer = BRepTools.OuterWire_s(fwd)
    wires = [outer] + [w for w in kind_edges(fwd, TopAbs_WIRE) if not w.IsSame(outer)]
    built = []
    for w in wires:
        mw = BRepBuilderAPI_MakeWire()
        ex = BRepTools_WireExplorer(TopoDS.Wire_s(w), fwd)
        while ex.More():
            old = ex.Current()
            c2 = BRepAdaptor_Curve2d(old, fwd)
            me = BRepBuilderAPI_MakeEdge(c2.Curve(), surf, c2.FirstParameter(), c2.LastParameter())
            if not me.IsDone():
                raise RuntimeError("A trim curve could not be rebuilt on the edited surface.")
            edge = me.Edge()
            BRepLib.BuildCurves3d_s(edge)
            if old.Orientation() == TopAbs_REVERSED:
                edge = TopoDS.Edge_s(edge.Reversed())
            mw.Add(edge)
            if not mw.IsDone():
                raise RuntimeError("The trim boundary could not be closed on the edited surface.")
            ex.Next()
        built.append(mw.Wire())
    mf = BRepBuilderAPI_MakeFace(surf, built[0], True)
    for w in built[1:]:
        mf.Add(w)
    if not mf.IsDone():
        raise RuntimeError("The trimmed surface could not be rebuilt.")
    fix = ShapeFix_Face(mf.Face())
    fix.SetPrecision(tol)
    fix.Perform()
    return fix.Face()


def uv_mid(edge, face):
    c2 = BRepAdaptor_Curve2d(edge, face)
    q = c2.Value((c2.FirstParameter() + c2.LastParameter()) / 2.0)
    return q.X(), q.Y()


def edge_history(old_face, new_face, old_maps, new_maps, scale):
    rows = {}
    news = []
    for k in range(1, new_maps.Extent() + 1):
        try:
            news.append((k - 1, uv_mid(TopoDS.Edge_s(new_maps.FindKey(k)), new_face)))
        except Exception:
            continue
    taken = set()
    for k in range(1, old_maps.Extent() + 1):
        try:
            a = uv_mid(TopoDS.Edge_s(old_maps.FindKey(k)), old_face)
        except Exception:
            continue
        best, bd = None, 1e-3
        for idx, b in news:
            if idx in taken:
                continue
            dist = math.hypot((a[0] - b[0]) / scale[0], (a[1] - b[1]) / scale[1])
            if dist < bd:
                best, bd = idx, dist
        if best is not None:
            taken.add(best)
            rows[str(k - 1)] = {"to": [best]}
    return rows


def set_poles(p):
    tol, ang = tolerances(p)
    face, src = editable_face(p["id"])
    surf = Geom_BSplineSurface(src)
    nu, nv = surf.NbUPoles(), surf.NbVPoles()
    moves = p.get("moves") or []
    if not moves:
        raise RuntimeError("Give at least one control point to move.")
    worst = 0.0
    for m in moves:
        i, j = int(m["i"]), int(m["j"])
        if not (0 <= i < nu and 0 <= j < nv):
            raise RuntimeError("Control point %d, %d is outside the %d by %d net." % (i, j, nu, nv))
        to = [float(c) for c in m["to"]]
        if len(to) != 3 or not all(math.isfinite(c) for c in to):
            raise RuntimeError("A control point needs three finite coordinates.")
        was = surf.Pole(i + 1, j + 1)
        worst = max(worst, math.dist(to, (was.X(), was.Y(), was.Z())))
        surf.SetPole(i + 1, j + 1, gp_Pnt(*to))
    natural = is_natural(face, src)
    if natural:
        out = BRepBuilderAPI_MakeFace(surf, tol).Face()
    else:
        out = retrim(face, surf, tol)
    if face.Orientation() == TopAbs_REVERSED and out.Orientation() != TopAbs_REVERSED:
        out = TopoDS.Face_s(out.Reversed())
    if not BRepCheck_Analyzer(out).IsValid():
        raise RuntimeError("Moving the control points there gives a surface that is not valid." if natural else "Moving the control points there breaks the trim boundary of the surface.")
    u0, u1, v0, v1 = surf.Bounds()
    new_maps = store.build_maps(out)
    old_maps = store.build_maps(face)
    try:
        edges = edge_history(TopoDS.Face_s(face.Oriented(TopAbs_FORWARD)), TopoDS.Face_s(out.Oriented(TopAbs_FORWARD)), old_maps["edges"], new_maps["edges"], (max(u1 - u0, 1e-12), max(v1 - v0, 1e-12)))
    except Exception:
        edges = {}
    same_edges = old_maps["edges"].Extent() == store.maps_of(p["id"])["edges"].Extent()
    history = {"inputs": [{"id": p["id"], "faces": {"0": {"to": [0]}}, "edges": edges if same_edges else {}}]}
    report = {"moved": len(moves), "largest_move": worst, "poles": [nu, nv], "trimmed": not natural}
    return finish("points", out, tol, ang, report, history)


METHODS = {"surf_net": net, "surf_set_poles": set_poles}
