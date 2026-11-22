import math

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_MakeFace
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_BSplineSurface, Geom_BezierSurface, Geom_RectangularTrimmedSurface, Geom_TrimmedCurve
from OCP.GeomConvert import GeomConvert
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Face

import kernel_curves
from kernel_surf import TopoDS, face_of, finish, kind_edges, tolerances

INFINITE = 1e99
MODES = ("all", "holes")


def area_of(shape):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return abs(props.Mass())


def finite(v):
    return math.isfinite(v) and abs(v) < INFINITE


def same(a, b, span):
    return abs(a - b) <= 1e-9 * max(abs(span), 1.0)


def pole_count(surf):
    if isinstance(surf, (Geom_BSplineSurface, Geom_BezierSurface)):
        return [surf.NbUPoles(), surf.NbVPoles()]
    return None


def natural_range(surf, face):
    su0, su1, sv0, sv1 = surf.Bounds()
    fu0, fu1, fv0, fv1 = BRepTools.UVBounds_s(face)
    return [su0 if finite(su0) else fu0, su1 if finite(su1) else fu1, sv0 if finite(sv0) else fv0, sv1 if finite(sv1) else fv1]


def on_natural_boundary(face, edge, rng):
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face, edge)
    du, dv = rng[1] - rng[0], rng[3] - rng[2]
    if same(u0, u1, du) and (same(u0, rng[0], du) or same(u0, rng[1], du)):
        return True
    return same(v0, v1, dv) and (same(v0, rng[2], dv) or same(v0, rng[3], dv))


def edge_record(edge, tol):
    ad = BRepAdaptor_Curve(edge)
    first, last = ad.FirstParameter(), ad.LastParameter()
    curve = BRep_Tool.Curve_s(edge, first, last)
    if curve is None:
        return None
    bs = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, first, last))
    bs.Transform(ad.Trsf())
    return kernel_curves.finish(bs, tol)


def trim_curves(face, wires, rng, tol):
    out = []
    for w in wires:
        for e in kind_edges(w, TopAbs_EDGE):
            edge = TopoDS.Edge_s(e)
            if BRep_Tool.Degenerated_s(edge) or on_natural_boundary(face, edge, rng):
                continue
            rec = edge_record(edge, tol)
            if rec is not None:
                out.append(rec)
    return out


def untrim(p):
    tol, ang = tolerances(p)
    face = face_of(p["face"])
    mode = str(p.get("mode", "all")).lower()
    if mode not in MODES:
        raise RuntimeError("The untrim mode is all or holes.")
    forward = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
    surf = BRep_Tool.Surface_s(face)
    rng = natural_range(surf, face)
    if rng[1] - rng[0] <= 0 or rng[3] - rng[2] <= 0:
        raise RuntimeError("The face has no parameter range to untrim to.")
    wires = [TopoDS.Wire_s(w) for w in kind_edges(forward, TopAbs_WIRE)]
    outer = BRepTools.OuterWire_s(forward)
    inner = [w for w in wires if not w.IsSame(outer)]
    before = area_of(face)
    if mode == "holes":
        if not inner:
            raise RuntimeError("This face has no holes to remove.")
        loc = TopLoc_Location()
        held = BRep_Tool.Surface_s(face, loc)
        made = TopoDS_Face()
        builder = BRep_Builder()
        builder.MakeFace(made, held, loc, BRep_Tool.Tolerance_s(face))
        builder.Add(made, outer)
        removed = inner
    else:
        mk = BRepBuilderAPI_MakeFace(surf, rng[0], rng[1], rng[2], rng[3], tol)
        if not mk.IsDone():
            raise RuntimeError("The full surface could not be made into a face.")
        made = mk.Face()
        removed = wires
    after = area_of(made)
    if mode == "all" and not inner and abs(after - before) <= 1e-9 * max(after, 1e-12):
        raise RuntimeError("This face is not trimmed; it already covers its whole surface.")
    made.Orientation(face.Orientation())
    curves = trim_curves(forward, removed, rng, tol) if p.get("keep_curves") else []
    report = {"mode": mode, "area_before": before, "area_after": after, "uv_range": rng, "wires_removed": len(removed), "curves_kept": len(curves), "valid": bool(BRepCheck_Analyzer(made).IsValid())}
    out = finish("untrim", made, tol, ang, report)
    out["curves"] = curves
    return out


def shrunk_range(surf, face, margin):
    su0, su1, sv0, sv1 = surf.Bounds()
    fu0, fu1, fv0, fv1 = BRepTools.UVBounds_s(face)
    out = []
    for lo, hi, flo, fhi, periodic in ((su0, su1, fu0, fu1, surf.IsUPeriodic()), (sv0, sv1, fv0, fv1, surf.IsVPeriodic())):
        pad = margin * (fhi - flo)
        a, b = flo - pad, fhi + pad
        if periodic:
            if b - a >= (hi - lo) * (1 - 1e-9):
                a, b = lo, hi
        else:
            if finite(lo):
                a = max(a, lo)
            if finite(hi):
                b = min(b, hi)
        out.extend([a, b])
    return out, [su0, su1, sv0, sv1]


def agrees(a, b, rng, tol):
    for i in range(4):
        for j in range(4):
            u = rng[0] + (rng[1] - rng[0]) * i / 3.0
            v = rng[2] + (rng[3] - rng[2]) * j / 3.0
            if a.Value(u, v).Distance(b.Value(u, v)) > tol * 1e-3:
                return False
    return True


def segmented(base, rng, tol):
    src = base
    if isinstance(src, Geom_BezierSurface):
        src = GeomConvert.SurfaceToBSplineSurface_s(src)
    if isinstance(src, Geom_BSplineSurface):
        try:
            cut = src.Copy()
            cut.CheckAndSegment(rng[0], rng[1], rng[2], rng[3])
            if agrees(cut, base, rng, tol):
                return cut
        except Exception:
            pass
    return Geom_RectangularTrimmedSurface(base, rng[0], rng[1], rng[2], rng[3])


def move_pcurves(face, old, new, loc, builder):
    for e in kind_edges(face, TopAbs_EDGE):
        edge = TopoDS.Edge_s(e)
        etol = BRep_Tool.Tolerance_s(edge)
        first, last = BRep_Tool.Range_s(edge, face)
        if BRep_Tool.IsClosed_s(edge, face):
            c1 = BRep_Tool.CurveOnSurface_s(TopoDS.Edge_s(edge.Oriented(TopAbs_FORWARD)), face, 0.0, 0.0)
            c2 = BRep_Tool.CurveOnSurface_s(TopoDS.Edge_s(edge.Oriented(TopAbs_REVERSED)), face, 0.0, 0.0)
            if c1 is None or c2 is None:
                raise RuntimeError("A seam edge has no parameter-space curve.")
            builder.UpdateEdge(edge, c1, c2, new, loc, etol)
        else:
            c = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
            if c is None:
                raise RuntimeError("A trim edge has no parameter-space curve.")
            builder.UpdateEdge(edge, c, new, loc, etol, c.Value(first), c.Value(last))
        builder.Range(edge, new, loc, first, last)


def shrink(p):
    tol, ang = tolerances(p)
    margin = float(p.get("margin", 0.01))
    if not math.isfinite(margin) or margin < 0 or margin > 1:
        raise RuntimeError("The margin is a fraction from 0 to 1 of the trimmed extent.")
    source = face_of(p["face"])
    face = TopoDS.Face_s(BRepBuilderAPI_Copy(source, True, False).Shape())
    loc = TopLoc_Location()
    old = BRep_Tool.Surface_s(face, loc)
    base = old.BasisSurface() if isinstance(old, Geom_RectangularTrimmedSurface) else old
    rng, was = shrunk_range(old, face, margin)
    spans = [(was[1] - was[0], rng[1] - rng[0]), (was[3] - was[2], rng[3] - rng[2])]
    if all(finite(o) and n >= o * (1 - 1e-9) for o, n in spans):
        raise RuntimeError("The surface already ends at its trim boundary; there is nothing to shrink.")
    new = segmented(base, rng, tol)
    before = area_of(face)
    poles_before = pole_count(base)
    builder = BRep_Builder()
    move_pcurves(face, old, new, loc, builder)
    builder.UpdateFace(face, new, loc, BRep_Tool.Tolerance_s(face))
    after = area_of(face)
    now = list(new.Bounds())
    report = {
        "margin": margin,
        "area_before": before,
        "area_after": after,
        "uv_before": [v if finite(v) else None for v in was],
        "uv_after": now,
        "uv_trim": list(BRepTools.UVBounds_s(face)),
        "poles_before": poles_before,
        "poles_after": pole_count(new),
        "surface": type(new).__name__.replace("Geom_", ""),
        "valid": bool(BRepCheck_Analyzer(face).IsValid()),
    }
    if not report["valid"]:
        raise RuntimeError("The shrunk face did not check as valid; the surface was left as it was.")
    return finish("shrink", face, tol, ang, report)


METHODS = {"surf_untrim": untrim, "surf_shrink": shrink}
