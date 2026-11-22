import math

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeVertex
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape, BRepExtrema_IsInFace, BRepExtrema_IsVertex
from OCP.BRepLib import BRepLib
from OCP.BRepProj import BRepProj_Projection
from OCP.BRepTools import BRepTools
from OCP.Geom import Geom_BSplineSurface, Geom_RectangularTrimmedSurface, Geom_TrimmedCurve
from OCP.GeomAPI import GeomAPI_PointsToBSpline, GeomAPI_ProjectPointOnCurve
from OCP.GeomAbs import GeomAbs_C2
from OCP.GeomConvert import GeomConvert, GeomConvert_ApproxCurve, GeomConvert_CompCurveToBSplineCurve
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_IN, TopAbs_ON, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS_Compound
from OCP.collections import Array1_gp_Pnt
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as AncestorMap
from OCP.gp import gp_Pln, gp_Pnt, gp_Pnt2d, gp_Vec

import kernel_curves
import kernel_store as store
from kernel_ops import direction, pnt
from kernel_surf import TopoDS, curve_wire, face_of, kind_edges, tolerances

MAX_SOURCES = 256
MAX_PLANES = 1000
MAX_ISOS = 512
ON_SAMPLES = 33
CHECK_SAMPLES = 9
CLIP_STEPS = 240
PULL_START = 64
PULL_MOST = 1024
NORMAL_OK = 0.01
LIGHT_POLES = 32
INFINITE = 1e99


def compound_of(parts):
    if len(parts) == 1:
        return parts[0]
    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for s in parts:
        builder.Add(comp, s)
    return comp


def target_shape(p):
    items = p.get("targets") or []
    if not items:
        raise RuntimeError("Give the surfaces or solids to work on under targets.")
    parts = []
    for it in items:
        faces = it.get("faces")
        if faces:
            parts.extend(face_of({"id": it["id"], "index": i}) for i in faces)
        else:
            parts.append(store.shape_of(it["id"]))
    shape = compound_of(parts)
    if not kind_edges(shape, TopAbs_FACE):
        raise RuntimeError("The target has no faces.")
    return shape


def sources_of(p):
    items = p.get("curves") or []
    if not items or len(items) > MAX_SOURCES:
        raise RuntimeError("Give from 1 to %d curves under curves." % MAX_SOURCES)
    return [curve_wire(s) for s in items]


def edge_bspline(edge):
    if BRep_Tool.Degenerated_s(edge):
        return None
    ad = BRepAdaptor_Curve(edge)
    first, last = ad.FirstParameter(), ad.LastParameter()
    curve = BRep_Tool.Curve_s(edge, first, last)
    if curve is None:
        BRepLib.BuildCurves3d_s(edge)
        curve = BRep_Tool.Curve_s(edge, first, last)
    if curve is None or last - first <= 1e-12:
        return None
    return GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, first, last))


def lighter(g, shape, tol):
    if g.NbPoles() <= LIGHT_POLES:
        return g
    try:
        ap = GeomConvert_ApproxCurve(g, tol * 0.2, GeomAbs_C2, 200, 8)
        if not ap.HasResult():
            return g
        out = ap.Curve()
    except Exception:
        return g
    if out.NbPoles() >= g.NbPoles() or off_shape(samples(out, 2 * ON_SAMPLES - 1), shape) > 0.5 * tol:
        return g
    return out


def pieces_of(shape, target=None, tol=0.0):
    out = []
    for e in kind_edges(shape, TopAbs_EDGE):
        g = edge_bspline(TopoDS.Edge_s(e))
        if g is not None:
            out.append(lighter(g, target, tol) if target is not None else g)
    return out


def chain(pieces, tol):
    left = list(pieces)
    runs = []
    while left:
        run = [left.pop(0)]
        grown = True
        while grown and left:
            grown = False
            head, tail = run[0].StartPoint(), run[-1].EndPoint()
            if head.Distance(tail) <= tol:
                break
            for i, c in enumerate(left):
                a, b = c.StartPoint(), c.EndPoint()
                if tail.Distance(a) <= tol:
                    run.append(left.pop(i))
                elif tail.Distance(b) <= tol:
                    c.Reverse()
                    run.append(left.pop(i))
                elif head.Distance(b) <= tol:
                    run.insert(0, left.pop(i))
                elif head.Distance(a) <= tol:
                    c.Reverse()
                    run.insert(0, left.pop(i))
                else:
                    continue
                grown = True
                break
        runs.append(run)
    return runs


def merged(run, tol):
    if len(run) == 1:
        return [run[0]]
    comp = GeomConvert_CompCurveToBSplineCurve()
    for c in run:
        if not comp.Add(c, tol, True):
            return list(run)
    return [comp.BSplineCurve()]


def joined(pieces, tol, join):
    if not join:
        return list(pieces)
    out = []
    for run in chain(pieces, max(tol, 1e-6)):
        out.extend(merged(run, max(tol, 1e-6)))
    return out


def samples(g, count):
    a, b = g.FirstParameter(), g.LastParameter()
    return [g.Value(a + (b - a) * i / (count - 1)) for i in range(count)]


def length_of(pts):
    return sum(pts[i].Distance(pts[i + 1]) for i in range(len(pts) - 1))


def gap(q, shape):
    d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(q).Vertex(), shape)
    return d if d.IsDone() and d.NbSolution() > 0 else None


def off_shape(pts, shape):
    worst = 0.0
    for q in pts:
        d = gap(q, shape)
        if d is not None:
            worst = max(worst, d.Value())
    return worst


def record(g, tol, pts, shape, extra):
    rec = kernel_curves.finish(g, tol)
    rec["deviation"] = off_shape(pts, shape)
    rec["closed"] = bool(g.StartPoint().Distance(g.EndPoint()) <= max(tol, 1e-6))
    rec["length"] = length_of(pts)
    rec.update(extra)
    return rec


def extent_of(shape, extra=()):
    box = store.bbox_of(compound_of([shape, *extra]))
    if box is None:
        return 1.0
    return math.dist(box[:3], box[3:]) + 1.0


def along_error(pts, wire, d, reach):
    worst = 0.0
    for q in pts:
        a = gp_Pnt(q.X() - d.X() * reach, q.Y() - d.Y() * reach, q.Z() - d.Z() * reach)
        b = gp_Pnt(q.X() + d.X() * reach, q.Y() + d.Y() * reach, q.Z() + d.Z() * reach)
        dist = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeEdge(a, b).Edge(), wire)
        if dist.IsDone():
            worst = max(worst, dist.Value())
    return worst


def thin(pts, count):
    step = (len(pts) - 1) / float(count - 1)
    return [pts[int(round(i * step))] for i in range(count)]


def project(p):
    tol, _ang = tolerances(p)
    shape = target_shape(p)
    wires = sources_of(p)
    d = direction(p.get("direction"))
    join = bool(p.get("join", True))
    light = None if p.get("exact") else shape
    reach = extent_of(shape, wires) * 2.0
    curves, missed = [], []
    worst = worst_along = 0.0
    for ci, wire in enumerate(wires):
        pieces = []
        try:
            proj = BRepProj_Projection(wire, shape, d)
            while proj.More():
                pieces.extend(pieces_of(proj.Current(), light, tol))
                proj.Next()
        except Exception:
            pieces = []
        made = joined(pieces, tol, join)
        if not made:
            missed.append(ci)
            continue
        for g in made:
            pts = samples(g, ON_SAMPLES)
            along = along_error(thin(pts, CHECK_SAMPLES), wire, d, reach)
            rec = record(g, tol, pts, shape, {"source": ci, "direction_error": along})
            worst = max(worst, rec["deviation"])
            worst_along = max(worst_along, along)
            curves.append(rec)
    report = {"op": "project", "tol": tol, "direction": [d.X(), d.Y(), d.Z()], "sources": len(wires), "curves": len(curves), "missed": missed, "max_deviation": worst, "max_direction_error": worst_along, "samples_per_curve": ON_SAMPLES, "within_tolerance": bool(worst <= tol)}
    return {"curves": curves, "report": report}


class Puller:
    def __init__(self, shape, tol, limit):
        self.shape, self.tol, self.limit = shape, tol, limit
        self.edges, self.verts = AncestorMap(), AncestorMap()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, self.edges)
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_VERTEX, TopAbs_FACE, self.verts)

    def hit(self, s):
        d = gap(s, self.shape)
        if d is None:
            return None
        far = d.Value()
        if self.limit is not None and far > self.limit:
            return None
        q = d.PointOnShape2(1)
        kind = d.SupportTypeShape2(1)
        support = d.SupportOnShape2(1)
        if kind == BRepExtrema_IsInFace:
            face = TopoDS.Face_s(support)
            u, v = d.ParOnFaceS2(1)
        else:
            owners = self.verts if kind == BRepExtrema_IsVertex else self.edges
            if not owners.Contains(support):
                return None
            face = TopoDS.Face_s(owners.FindFromKey(support).First())
            uv = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face)).ValueOfUV(q, self.tol)
            u, v = uv.X(), uv.Y()
        angle = 0.0
        if far > self.tol:
            at, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
            BRepAdaptor_Surface(face).D1(u, v, at, du, dv)
            n = du.Crossed(dv)
            if n.Magnitude() > 1e-12:
                a = n.Angle(gp_Vec(q, s))
                angle = min(a, math.pi - a)
        if kind != BRepExtrema_IsInFace and angle > NORMAL_OK:
            return None
        return q, far, angle


def fit_run(puller, run, hit, tol):
    ts, pts = [], []
    for t in sorted(set(run)):
        q = hit(t)[0]
        if pts and pts[-1].Distance(q) <= 1e-9:
            continue
        ts.append(t)
        pts.append(q)
    if len(pts) < 2 or length_of(pts) <= tol:
        return None
    arr = Array1_gp_Pnt(1, len(pts))
    for i, q in enumerate(pts):
        arr.SetValue(i + 1, q)
    mk = GeomAPI_PointsToBSpline(arr, min(3, len(pts) - 1), 8, GeomAbs_C2, max(tol * 0.2, 1e-7))
    if not mk.IsDone():
        return None
    g = mk.Curve()
    error = 0.0
    for t0, t1 in zip(ts, ts[1:]):
        h = hit(0.5 * (t0 + t1))
        if h is None:
            continue
        pr = GeomAPI_ProjectPointOnCurve(h[0], g)
        if pr.NbPoints() > 0:
            error = max(error, pr.LowerDistance())
    return {"g": g, "error": error, "angle": max(hit(t)[2] for t in ts), "far": max(hit(t)[1] for t in ts), "off": off_shape(samples(g, ON_SAMPLES), puller.shape)}


def pull_edge(puller, edge, tol):
    ad = BRepAdaptor_Curve(edge)
    a, b = ad.FirstParameter(), ad.LastParameter()
    cache = {}

    def hit(t):
        if t not in cache:
            cache[t] = puller.hit(ad.Value(t))
        return cache[t]

    def bound(t_in, t_out):
        for _ in range(30):
            m = 0.5 * (t_in + t_out)
            if hit(m) is None:
                t_out = m
            else:
                t_in = m
        return t_in

    def jump(t0, t1):
        return hit(t0)[0].Distance(hit(t1)[0]) > 25.0 * ad.Value(t0).Distance(ad.Value(t1)) + 100.0 * tol

    n = PULL_START
    while True:
        ts = [a + (b - a) * i / n for i in range(n + 1)]
        runs, run = [], []
        for i, t in enumerate(ts):
            if hit(t) is None:
                if run:
                    run.append(bound(run[-1], t))
                    runs.append(run)
                    run = []
                continue
            if not run and i > 0 and hit(ts[i - 1]) is None:
                run.append(bound(t, ts[i - 1]))
            if run and jump(run[-1], t):
                runs.append(run)
                run = []
            run.append(t)
        if run:
            runs.append(run)
        made = [m for m in (fit_run(puller, r, hit, tol) for r in runs) if m is not None]
        if n >= PULL_MOST or all(m["error"] <= 0.5 * tol and m["off"] <= 0.5 * tol for m in made):
            return made
        n *= 2


def pull(p):
    tol, _ang = tolerances(p)
    shape = target_shape(p)
    wires = sources_of(p)
    join = bool(p.get("join", True))
    limit = p.get("max_distance")
    puller = Puller(shape, tol, float(limit) if limit is not None else None)
    curves, missed = [], []
    worst = worst_angle = worst_far = worst_error = 0.0
    for ci, wire in enumerate(wires):
        fits = []
        for e in kind_edges(wire, TopAbs_EDGE):
            fits.extend(pull_edge(puller, TopoDS.Edge_s(e), tol))
        made = joined([m["g"] for m in fits], tol, join)
        if not made:
            missed.append(ci)
            continue
        error, ang, far = (max(m[k] for m in fits) for k in ("error", "angle", "far"))
        worst_error, worst_angle, worst_far = max(worst_error, error), max(worst_angle, ang), max(worst_far, far)
        for g in made:
            rec = record(g, tol, samples(g, ON_SAMPLES), shape, {"source": ci, "pull_error": error, "normal_angle": ang, "pull_distance": far})
            worst = max(worst, rec["deviation"])
            curves.append(rec)
    report = {"op": "pull", "tol": tol, "sources": len(wires), "curves": len(curves), "missed": missed, "max_deviation": worst, "max_pull_error": worst_error, "max_normal_angle": worst_angle, "max_pull_distance": worst_far, "samples_per_curve": ON_SAMPLES, "within_tolerance": bool(max(worst, worst_error) <= tol)}
    return {"curves": curves, "report": report}


def span_along(shape, base, d):
    box = store.bbox_of(shape)
    if box is None:
        raise RuntimeError("The target has no extent.")
    x0, y0, z0, x1, y1, z1 = box
    vals = [(x - base.X()) * d.X() + (y - base.Y()) * d.Y() + (z - base.Z()) * d.Z() for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    return min(vals), max(vals)


def plane_offsets(p, lo, hi):
    spacing, count = p.get("spacing"), p.get("count")
    if count is not None:
        count = int(count)
        if not 1 <= count <= MAX_PLANES:
            raise RuntimeError("The plane count must be from 1 to %d." % MAX_PLANES)
    if spacing is None:
        if count is None:
            raise RuntimeError("Give a spacing or a count of planes.")
        step = (hi - lo) / count
        if step <= 1e-9:
            raise RuntimeError("The target has no extent along the direction.")
        return [lo + (i + 0.5) * step for i in range(count)], step, "count"
    step = float(spacing)
    if not math.isfinite(step) or step <= 1e-7:
        raise RuntimeError("The spacing must be positive.")
    if count is not None:
        return [i * step for i in range(count)], step, "spacing_count"
    k0, k1 = math.ceil((lo - 1e-9) / step), math.floor((hi + 1e-9) / step)
    if k1 - k0 + 1 > MAX_PLANES:
        raise RuntimeError("That spacing makes %d planes; at most %d are cut at once. Use a larger spacing." % (k1 - k0 + 1, MAX_PLANES))
    return [k * step for k in range(k0, k1 + 1)], step, "spacing"


def flattened(g, origin, d):
    for i in range(1, g.NbPoles() + 1):
        q = g.Pole(i)
        h = (q.X() - origin.X()) * d.X() + (q.Y() - origin.Y()) * d.Y() + (q.Z() - origin.Z()) * d.Z()
        if abs(h) > 0.0:
            g.SetPole(i, gp_Pnt(q.X() - d.X() * h, q.Y() - d.Y() * h, q.Z() - d.Z() * h))
    return g


def contour(p):
    tol, _ang = tolerances(p)
    shape = target_shape(p)
    d = direction(p.get("direction"))
    base = pnt(p.get("base") or [0, 0, 0])
    lo, hi = span_along(shape, base, d)
    offsets, step, mode = plane_offsets(p, lo, hi)
    join = bool(p.get("join", True))
    light = None if p.get("exact") else shape
    curves, planes = [], []
    worst = worst_plane = 0.0
    for i, off in enumerate(offsets):
        origin = gp_Pnt(base.X() + d.X() * off, base.Y() + d.Y() * off, base.Z() + d.Z() * off)
        pieces = []
        try:
            sec = BRepAlgoAPI_Section(shape, gp_Pln(origin, d), False)
            sec.Approximation(True)
            sec.Build()
            if sec.IsDone():
                pieces = [flattened(g, origin, d) for g in pieces_of(sec.Shape(), light, tol)]
        except Exception:
            pieces = []
        made = joined(pieces, tol, join)
        for g in made:
            pts = samples(g, ON_SAMPLES)
            flat = max(abs((q.X() - origin.X()) * d.X() + (q.Y() - origin.Y()) * d.Y() + (q.Z() - origin.Z()) * d.Z()) for q in pts)
            rec = record(g, tol, pts, shape, {"plane": i, "offset": off, "plane_distance": flat})
            worst = max(worst, rec["deviation"])
            worst_plane = max(worst_plane, flat)
            curves.append(rec)
        planes.append({"index": i, "offset": off, "origin": [origin.X(), origin.Y(), origin.Z()], "curves": len(made)})
    report = {"op": "contour", "tol": tol, "direction": [d.X(), d.Y(), d.Z()], "base": [base.X(), base.Y(), base.Z()], "mode": mode, "spacing": step, "extent": [lo, hi], "planes": planes, "plane_count": len(planes), "empty_planes": [r["index"] for r in planes if not r["curves"]], "curves": len(curves), "max_deviation": worst, "max_plane_distance": worst_plane, "samples_per_curve": ON_SAMPLES, "within_tolerance": bool(max(worst, worst_plane) <= tol)}
    return {"curves": curves, "report": report}


def iso_face(p):
    spec = p.get("face") or {}
    maps = store.maps_of(spec["id"])["faces"]
    if spec.get("index") is not None:
        return face_of(spec), int(spec["index"])
    if maps.Extent() == 1:
        return TopoDS.Face_s(maps.FindKey(1)), 0
    if p.get("point") is None:
        raise RuntimeError("The object has %d faces; name the face, or give a point on it." % maps.Extent())
    q = pnt(p["point"])
    best, at = None, 0
    for i in range(1, maps.Extent() + 1):
        d = gap(q, maps.FindKey(i))
        if d is not None and (best is None or d.Value() < best):
            best, at = d.Value(), i
    if best is None:
        raise RuntimeError("No face of the object could be measured against the point.")
    return TopoDS.Face_s(maps.FindKey(at)), at - 1


def knots_of(surf, which):
    basis = surf
    while isinstance(basis, Geom_RectangularTrimmedSurface):
        basis = basis.BasisSurface()
    if not isinstance(basis, Geom_BSplineSurface):
        raise RuntimeError("This face is a %s, which has no knots; give a point or a parameter instead." % type(basis).__name__.replace("Geom_", "").replace("Surface", " surface").strip().lower())
    return [float(k) for k in (basis.UKnots() if which == "u" else basis.VKnots())]


def clip(inside, lo, hi):
    ts = [lo + (hi - lo) * i / CLIP_STEPS for i in range(CLIP_STEPS + 1)]
    flags = [inside(t) for t in ts]
    if all(flags):
        return [(lo, hi)]

    def edge(a_in, b_out):
        for _ in range(48):
            m = 0.5 * (a_in + b_out)
            if inside(m):
                a_in = m
            else:
                b_out = m
        return a_in

    runs, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = ts[i] if i == 0 else edge(ts[i], ts[i - 1])
        elif not f and start is not None:
            runs.append((start, edge(ts[i - 1], ts[i])))
            start = None
    if start is not None:
        runs.append((start, hi))
    return runs


def iso_values(p, surf, sas, rng, dirs, tol):
    tasks = []
    info = {}
    names = {"u": (rng[0], rng[1]), "v": (rng[2], rng[3])}
    if p.get("knots"):
        for w in dirs:
            lo, hi = names[w]
            eps = 1e-9 * max(abs(hi - lo), 1.0)
            tasks.extend((w, min(max(k, lo), hi)) for k in knots_of(surf, w) if lo - eps <= k <= hi + eps)
        info["mode"] = "knots"
        return tasks, info
    if p.get("point") is not None:
        q = pnt(p["point"])
        uv = sas.ValueOfUV(q, tol)
        at = {"u": min(max(uv.X(), rng[0]), rng[1]), "v": min(max(uv.Y(), rng[2]), rng[3])}
        info.update({"mode": "point", "uv": [at["u"], at["v"]], "point_distance": q.Distance(sas.Value(gp_Pnt2d(at["u"], at["v"])))})
        return [(w, at[w]) for w in dirs], info
    for w in ("u", "v"):
        given = p.get(w)
        if given is None:
            continue
        lo, hi = names[w]
        for raw in given if isinstance(given, list) else [given]:
            c = float(raw)
            if p.get("normalized"):
                c = lo + (hi - lo) * c
            eps = 1e-9 * max(abs(hi - lo), 1.0)
            if not math.isfinite(c) or c < lo - eps or c > hi + eps:
                raise RuntimeError("The %s parameter %.6g is outside the surface range %.6g to %.6g." % (w.upper(), c, lo, hi))
            tasks.append((w, min(max(c, lo), hi)))
    info["mode"] = "parameter"
    if not tasks:
        raise RuntimeError("Give a point, a U or V parameter, or ask for the isocurves at the knots.")
    return tasks, info


def isocurve(p):
    tol, _ang = tolerances(p)
    face, index = iso_face(p)
    surf = BRep_Tool.Surface_s(face)
    if surf is None:
        raise RuntimeError("The face has no surface.")
    rng = list(BRepTools.UVBounds_s(face))
    if any(abs(c) >= INFINITE or not math.isfinite(c) for c in rng):
        raise RuntimeError("The face has no finite parameter range.")
    which = str(p.get("direction", "both")).lower()
    if which not in ("u", "v", "both"):
        raise RuntimeError("The direction is u, v or both.")
    dirs = ["u", "v"] if which == "both" else [which]
    sas = ShapeAnalysis_Surface(surf)
    tasks, info = iso_values(p, surf, sas, rng, dirs, tol)
    if len(tasks) > MAX_ISOS:
        raise RuntimeError("That asks for %d isocurves; at most %d are made at once." % (len(tasks), MAX_ISOS))
    fwd = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
    cls = BRepClass_FaceClassifier()
    periods = {"u": rng[1] - rng[0] if surf.IsUClosed() else None, "v": rng[3] - rng[2] if surf.IsVClosed() else None}
    curves, empty = [], []
    worst = worst_param = 0.0
    for w, c in tasks:
        lo, hi = (rng[2], rng[3]) if w == "u" else (rng[0], rng[1])
        iso = surf.UIso(c) if w == "u" else surf.VIso(c)

        def inside(t, w=w, c=c):
            cls.Perform(fwd, gp_Pnt2d(c, t) if w == "u" else gp_Pnt2d(t, c), 1e-9)
            return cls.State() in (TopAbs_IN, TopAbs_ON)

        made = 0
        for a, b in clip(inside, lo, hi):
            if b - a <= 1e-9 * max(abs(hi - lo), 1.0):
                continue
            g = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(iso, a, b))
            pts = samples(g, ON_SAMPLES)
            if length_of(pts) <= tol:
                continue
            dev = dpar = 0.0
            for q in thin(pts, CHECK_SAMPLES + 8):
                uv = sas.ValueOfUV(q, tol)
                got = uv.X() if w == "u" else uv.Y()
                err = abs(got - c)
                if periods[w]:
                    err = min(err, abs(periods[w] - err))
                dpar = max(dpar, err)
                dev = max(dev, q.Distance(sas.Value(uv)))
            rec = kernel_curves.finish(g, tol)
            rec.update({"deviation": dev, "param_error": dpar, "dir": w, "param": c, "range": [a, b], "length": length_of(pts), "closed": bool(g.StartPoint().Distance(g.EndPoint()) <= max(tol, 1e-6))})
            worst = max(worst, dev)
            worst_param = max(worst_param, dpar)
            curves.append(rec)
            made += 1
        if not made:
            empty.append({"dir": w, "param": c})
    report = {"op": "isocurve", "tol": tol, "face": index, "uv_range": rng, "asked": len(tasks), "curves": len(curves), "u_curves": sum(1 for r in curves if r["dir"] == "u"), "v_curves": sum(1 for r in curves if r["dir"] == "v"), "empty": empty, "max_deviation": worst, "max_param_error": worst_param, "within_tolerance": bool(worst <= tol)}
    report.update(info)
    return {"curves": curves, "report": report}


METHODS = {"surf_project": project, "surf_pull": pull, "surf_contour": contour, "surf_isocurve": isocurve}
