import math

import numpy as np
import OCP.collections as col
from OCP.Approx import Approx_Centripetal, Approx_ChordLength, Approx_IsoParametric
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_NurbsConvert
from OCP.GC import GC_MakeArcOfCircle
from OCP.Geom import Geom_BezierCurve, Geom_BSplineCurve, Geom_Circle, Geom_Line, Geom_OffsetCurve, Geom_TrimmedCurve
from OCP.GeomAPI import GeomAPI_Interpolate, GeomAPI_PointsToBSpline, GeomAPI_ProjectPointOnCurve
from OCP.GeomAbs import GeomAbs_C0, GeomAbs_C1, GeomAbs_C2, GeomAbs_C3, GeomAbs_G1, GeomAbs_G2
from OCP.GeomConvert import GeomConvert, GeomConvert_CompCurveToBSplineCurve
from OCP.GeomLib import GeomLib
from OCP.GeomLProp import GeomLProp_CLProps
from OCP.LocalAnalysis import LocalAnalysis_CurveContinuity
from OCP.ShapeFix import ShapeFix_ShapeTolerance
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec

import kernel_store as store

FLOOR = 1e-7
MAX_POINTS = 50000
MAX_DEGREE = 25
PARAM_KINDS = {"chord": Approx_ChordLength, "centripetal": Approx_Centripetal, "uniform": Approx_IsoParametric}
CONTINUITY = {0: GeomAbs_C0, 1: GeomAbs_C1, 2: GeomAbs_C2, 3: GeomAbs_C3}


def tolerances(p, floor=True):
    tol = float(p.get("tol", 1e-6))
    ang = float(p.get("angle_tol", 1e-6))
    if not math.isfinite(tol) or tol <= 0 or not math.isfinite(ang) or ang <= 0:
        raise RuntimeError("The tolerances must be positive numbers.")
    return (max(tol, FLOOR) if floor else tol), ang


def vec3(v):
    if v is None or len(v) < 2:
        raise RuntimeError("A point needs coordinates.")
    return [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0]


def pnt_array(points):
    n = len(points)
    if n < 2 or n > MAX_POINTS:
        raise RuntimeError("A curve needs from 2 to %d points." % MAX_POINTS)
    arr = col.Array1_gp_Pnt(1, n)
    for i, q in enumerate(points):
        q = vec3(q)
        if not all(math.isfinite(c) for c in q):
            raise RuntimeError("A point has a coordinate that is not finite.")
        arr.SetValue(i + 1, gp_Pnt(q[0], q[1], q[2]))
    return arr


def real_array(values):
    arr = col.Array1_double(1, len(values))
    for i, v in enumerate(values):
        arr.SetValue(i + 1, float(v))
    return arr


def clamped(n, p):
    spans = n - p
    knots = [float(i) for i in range(spans + 1)]
    mults = [p + 1] + [1] * (spans - 1) + [p + 1] if spans > 0 else [p + 1]
    return knots, mults


def to_geom(rec):
    if not isinstance(rec, dict):
        raise RuntimeError("The curve record is missing.")
    poles = rec.get("poles") or []
    p = int(rec.get("degree", 3))
    periodic = bool(rec.get("periodic", False))
    n = len(poles)
    if p < 1 or p > MAX_DEGREE:
        raise RuntimeError("The degree must be from 1 to %d." % MAX_DEGREE)
    if n < p + 1 and not periodic:
        raise RuntimeError("A degree %d curve needs at least %d poles." % (p, p + 1))
    if n < 2 or n > MAX_POINTS:
        raise RuntimeError("A curve needs from 2 to %d poles." % MAX_POINTS)
    knots, mults = rec.get("knots") or [], rec.get("mults") or []
    if not knots:
        if periodic:
            knots, mults = [float(i) for i in range(n + 1)], [1] * (n + 1)
        else:
            knots, mults = clamped(n, p)
    if len(knots) != len(mults):
        raise RuntimeError("knots and mults must have the same length.")
    weights = rec.get("weights") or []
    if weights and len(weights) != n:
        raise RuntimeError("There must be one weight per pole.")
    if weights and min(float(w) for w in weights) <= 0:
        raise RuntimeError("Weights must be positive.")
    try:
        if weights:
            g = Geom_BSplineCurve(pnt_array(poles), real_array(weights), real_array(knots), int_array(mults), p, periodic)
        else:
            g = Geom_BSplineCurve(pnt_array(poles), real_array(knots), int_array(mults), p, periodic)
    except Exception as err:
        raise RuntimeError("The curve data are not a valid B-spline (%s)." % str(err).splitlines()[0])
    return g


def int_array(values):
    arr = col.Array1_int(1, len(values))
    for i, v in enumerate(values):
        arr.SetValue(i + 1, int(v))
    return arr


def from_geom(g):
    poles = []
    for i in range(1, g.NbPoles() + 1):
        q = g.Pole(i)
        poles.append([q.X(), q.Y(), q.Z()])
    weights = [g.Weight(i) for i in range(1, g.NbPoles() + 1)] if g.IsRational() else []
    knots = [g.Knot(i) for i in range(1, g.NbKnots() + 1)]
    mults = [g.Multiplicity(i) for i in range(1, g.NbKnots() + 1)]
    return {"degree": g.Degree(), "poles": poles, "weights": weights, "knots": knots, "mults": mults, "periodic": bool(g.IsPeriodic())}


def span_params(g, per=8):
    knots = [g.Knot(i) for i in range(1, g.NbKnots() + 1)]
    lo, hi = g.FirstParameter(), g.LastParameter()
    keys = [lo] + [k for k in knots if lo < k < hi] + [hi]
    out = []
    for a, b in zip(keys, keys[1:]):
        out.extend(a + (b - a) * j / per for j in range(per))
    out.append(hi)
    return out


def point_of(g, u):
    q = g.Value(u)
    return [q.X(), q.Y(), q.Z()]


def derivs(g, u, order=3):
    p = gp_Pnt()
    v = [gp_Vec() for _ in range(3)]
    if order <= 0:
        g.D0(u, p)
    elif order == 1:
        g.D1(u, p, v[0])
    elif order == 2:
        g.D2(u, p, v[0], v[1])
    else:
        g.D3(u, p, v[0], v[1], v[2])
    return [p.X(), p.Y(), p.Z()], [[w.X(), w.Y(), w.Z()] for w in v[: max(order, 0)]]


def distance_to(g, q):
    proj = GeomAPI_ProjectPointOnCurve(gp_Pnt(q[0], q[1], q[2]), g)
    if proj.NbPoints() == 0:
        return min(g.Value(g.FirstParameter()).Distance(gp_Pnt(*q)), g.Value(g.LastParameter()).Distance(gp_Pnt(*q)))
    best = proj.LowerDistance()
    for end in (g.FirstParameter(), g.LastParameter()):
        best = min(best, g.Value(end).Distance(gp_Pnt(q[0], q[1], q[2])))
    return best


def deviation(a, b, per=10):
    worst = 0.0
    for u in span_params(a, per):
        worst = max(worst, distance_to(b, point_of(a, u)))
    return worst


def audit_edge(shape, limit):
    vmax = emax = 0.0
    nv = ne = 0
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap

    for kind in (TopAbs_VERTEX, TopAbs_EDGE):
        m = ShapeMap()
        TopExp.MapShapes_s(shape, kind, m)
        for i in range(1, m.Extent() + 1):
            s = m.FindKey(i)
            if kind == TopAbs_VERTEX:
                vmax = max(vmax, BRep_Tool.Tolerance_s(TopoDS.Vertex(s)))
                nv += 1
            else:
                emax = max(emax, BRep_Tool.Tolerance_s(TopoDS.Edge(s)))
                ne += 1
    return {"vertex_max": vmax, "edge_max": emax, "face_max": 0.0, "vertices": nv, "edges": ne, "limit": limit, "exceeds": bool(max(vmax, emax) > limit * (1 + 1e-9))}


def finish(g, tol, extra=None):
    out = {"curve": from_geom(g), "tol_used": tol}
    try:
        edge = BRepBuilderAPI_MakeEdge(g).Edge()
        out["tolerances"] = audit_edge(edge, tol)
    except Exception as err:
        out["tolerances"] = {"error": str(err).splitlines()[0] if str(err) else "audit failed", "exceeds": False}
    if extra:
        out.update(extra)
    return out


def chord_params(points, kind, closed=False):
    seq = [vec3(q) for q in points] + ([vec3(points[0])] if closed else [])
    steps = []
    for a, b in zip(seq, seq[1:]):
        d = math.dist(a, b)
        steps.append(1.0 if kind == "uniform" else math.sqrt(d) if kind == "centripetal" else d)
    out = [0.0]
    for s in steps:
        out.append(out[-1] + s)
    if out[-1] <= 0:
        raise RuntimeError("The points all coincide.")
    return out


def make(p):
    tol, _ang = tolerances(p)
    rec = p.get("curve") or {k: p[k] for k in ("poles", "degree", "weights", "knots", "mults", "periodic") if k in p}
    g = to_geom(rec)
    return finish(g, tol)


def interpolate(p):
    tol, _ang = tolerances(p)
    points = [vec3(q) for q in p.get("points") or []]
    periodic = bool(p.get("periodic", False))
    kind = str(p.get("param", "chord"))
    if kind not in PARAM_KINDS:
        raise RuntimeError("param is chord, centripetal or uniform.")
    if len(points) < (3 if periodic else 2):
        raise RuntimeError("Interpolation needs %d points or more." % (3 if periodic else 2))
    for a, b in zip(points, points[1:] + ([points[0]] if periodic else [])):
        if math.dist(a, b) <= tol:
            raise RuntimeError("Two consecutive points coincide within the tolerance.")
    params = real_array(chord_params(points, kind, periodic))
    harr = col.HArray1_gp_Pnt(pnt_array(points))
    hpar = col.HArray1_double(params)
    it = GeomAPI_Interpolate(harr, hpar, periodic, tol)
    scale = bool(p.get("scale", True))
    n = len(points)
    if p.get("tangents"):
        flags = p.get("tangent_flags") or [t is not None for t in p["tangents"]]
        if len(p["tangents"]) != n or len(flags) != n:
            raise RuntimeError("Give one tangent entry and one flag per point.")
        vecs = col.Array1_gp_Vec(1, n)
        hflags = col.HArray1_bool(1, n)
        for i in range(n):
            t = vec3(p["tangents"][i]) if p["tangents"][i] is not None else [1.0, 0.0, 0.0]
            vecs.SetValue(i + 1, gp_Vec(t[0], t[1], t[2]))
            hflags.SetValue(i + 1, bool(flags[i]))
        it.Load(vecs, hflags, scale)
    elif p.get("start_tangent") is not None or p.get("end_tangent") is not None:
        if periodic:
            raise RuntimeError("A periodic curve takes no end tangents.")
        t0 = vec3(p["start_tangent"]) if p.get("start_tangent") is not None else None
        t1 = vec3(p["end_tangent"]) if p.get("end_tangent") is not None else None
        if t0 is None or t1 is None:
            vecs = col.Array1_gp_Vec(1, n)
            hflags = col.HArray1_bool(1, n)
            for i in range(n):
                vecs.SetValue(i + 1, gp_Vec(1, 0, 0))
                hflags.SetValue(i + 1, False)
            for idx, t in ((1, t0), (n, t1)):
                if t is not None:
                    vecs.SetValue(idx, gp_Vec(t[0], t[1], t[2]))
                    hflags.SetValue(idx, True)
            it.Load(vecs, hflags, scale)
        else:
            it.Load(gp_Vec(t0[0], t0[1], t0[2]), gp_Vec(t1[0], t1[1], t1[2]), scale)
    it.Perform()
    if not it.IsDone():
        raise RuntimeError("The points cannot be interpolated; check for repeated points or zero tangents.")
    g = it.Curve()
    worst = max(distance_to(g, q) for q in points)
    return finish(g, tol, {"deviation": worst})


def approx_points(points, kind, dmin, dmax, cont, tol, params=None):
    arr = pnt_array(points)
    if params is not None:
        return GeomAPI_PointsToBSpline(arr, real_array(params), dmin, dmax, CONTINUITY[cont], tol).Curve()
    return GeomAPI_PointsToBSpline(arr, PARAM_KINDS[kind], dmin, dmax, CONTINUITY[cont], tol).Curve()


def approximate(p):
    tol, _ang = tolerances(p)
    points = [vec3(q) for q in p.get("points") or []]
    dmin, dmax = int(p.get("deg_min", 3)), int(p.get("deg_max", 8))
    cont = int(p.get("continuity", 2))
    if not (1 <= dmin <= dmax <= MAX_DEGREE) or cont not in CONTINUITY:
        raise RuntimeError("Degrees are 1 to %d with deg_min <= deg_max; continuity is 0 to 3." % MAX_DEGREE)
    if len(points) < 3:
        raise RuntimeError("Fitting needs three points or more.")
    kind = str(p.get("param", "chord"))
    if kind not in PARAM_KINDS:
        raise RuntimeError("param is chord, centripetal or uniform.")
    g = approx_points(points, kind, dmin, dmax, cont, tol)
    worst = max(distance_to(g, q) for q in points)
    return finish(g, tol, {"deviation": worst, "within": bool(worst <= tol * (1 + 1e-9))})


def sample_for_fit(g):
    spans = max(g.NbKnots() - 1, 1)
    per = max(24, min(400, 600 // spans))
    return span_params(g, per)


def refit_geom(g, tol, dmin, dmax, cont=2):
    us = sample_for_fit(g)
    pts = [point_of(g, u) for u in us]
    best = None
    t = tol
    for _ in range(4):
        try:
            cand = approx_points(pts, "chord", dmin, dmax, cont, t, us)
        except Exception:
            t *= 0.25
            continue
        dev = deviation(cand, g, 6)
        dev = max(dev, deviation(g, cand, 6))
        best = (cand, dev)
        if dev <= tol:
            break
        t *= 0.2
    if best is None:
        raise RuntimeError("The curve could not be refitted.")
    return best


def refit(p):
    tol, _ang = tolerances(p)
    src = to_geom(p.get("curve"))
    dmin, dmax = int(p.get("deg_min", 3)), int(p.get("deg_max", 8))
    if not (1 <= dmin <= dmax <= MAX_DEGREE):
        raise RuntimeError("Degrees are 1 to %d with deg_min <= deg_max." % MAX_DEGREE)
    if src.IsPeriodic():
        src.SetNotPeriodic()
    degree = min(max(src.Degree(), dmin), dmax)
    if degree > src.Degree():
        src.IncreaseDegree(degree)
    ref = Geom_BSplineCurve(src)

    def trial(count, rounds, per_span):
        g, _resid = fit_fixed(ref, count, degree, False, rounds, per_span)
        return g, max(deviation(g, ref, 6), deviation(ref, g, 6))

    lo, hi = degree + 1, src.NbPoles()
    if hi <= lo:
        return finish(src, tol, {"deviation": 0.0, "within": True, "pole_count": src.NbPoles()})
    g, dev = trial(hi, 5, 24)
    if dev > tol:
        return finish(src, tol, {"deviation": 0.0, "within": True, "pole_count": src.NbPoles(), "reduced": False})
    best = (g, dev, hi)
    while lo < hi:
        mid = (lo + hi) // 2
        g, dev = trial(mid, 5, 24)
        if dev <= tol:
            hi, best = mid, (g, dev, mid)
        else:
            lo = mid + 1
    g, dev = trial(best[2], 10, 32)
    if dev > tol:
        g, dev = best[0], best[1]
    return finish(g, tol, {"deviation": dev, "within": bool(dev <= tol * (1 + 1e-9)), "pole_count": g.NbPoles(), "reduced": g.NbPoles() < src.NbPoles()})


def basis_row(span_knots, degree, u):
    n = len(span_knots) - degree - 1
    row = np.zeros(n)
    k = None
    for i in range(degree, n):
        if span_knots[i] <= u < span_knots[i + 1]:
            k = i
            break
    if k is None:
        k = n - 1
    nb = np.zeros(degree + 1)
    left = np.zeros(degree + 1)
    right = np.zeros(degree + 1)
    nb[0] = 1.0
    for j in range(1, degree + 1):
        left[j] = u - span_knots[k + 1 - j]
        right[j] = span_knots[k + j] - u
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            tmp = nb[r] / den if den else 0.0
            nb[r] = saved + right[r + 1] * tmp
            saved = left[j - r] * tmp
        nb[j] = saved
    row[k - degree : k + 1] = nb
    return row


def rebuild(p):
    tol, _ang = tolerances(p)
    src = to_geom(p.get("curve"))
    count, degree = int(p.get("count", 0)), int(p.get("degree", 3))
    if degree < 1 or degree > MAX_DEGREE or count < degree + 1 or count > 5000:
        raise RuntimeError("count must be at least degree + 1 (and at most 5000); degree is 1 to %d." % MAX_DEGREE)
    keep_tan = bool(p.get("keep_tangents", False))
    if src.IsPeriodic() or src.IsClosed():
        if count < 4:
            raise RuntimeError("A closed curve needs at least 4 points.")
        us = np.linspace(src.FirstParameter(), src.LastParameter(), count + 1)[:-1]
        pts = [point_of(src, u) for u in us]
        it = GeomAPI_Interpolate(col.HArray1_gp_Pnt(pnt_array(pts)), True, tol)
        it.Perform()
        if not it.IsDone():
            raise RuntimeError("The closed curve could not be rebuilt.")
        g = it.Curve()
        return finish(g, tol, {"deviation": max(deviation(g, src, 6), deviation(src, g, 6)), "pole_count": g.NbPoles()})
    g, _resid = fit_fixed(src, count, degree, keep_tan)
    dev = max(deviation(g, src, 8), deviation(src, g, 8))
    return finish(g, tol, {"deviation": dev, "pole_count": g.NbPoles()})


def fit_fixed(src, count, degree, keep_tan, rounds=10, per_span=None):
    us = span_params(src, per_span) if per_span else sample_for_fit(src)
    pts = np.array([point_of(src, u) for u in us])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    if seg.sum() <= 0:
        raise RuntimeError("The curve has no length.")
    t = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
    n = count
    inner = n - degree - 1
    knots = [0.0] * (degree + 1)
    m = len(t)
    for j in range(1, inner + 1):
        pos = j * (m - 1) / (inner + 1)
        i = int(pos)
        a = pos - i
        knots.append(float(t[i] * (1 - a) + t[min(i + 1, m - 1)] * a))
    knots += [1.0] * (degree + 1)
    q0, q1 = pts[0], pts[-1]
    d0 = tangent_unit(src, src.FirstParameter())
    d1 = tangent_unit(src, src.LastParameter())
    if keep_tan and n < 5:
        raise RuntimeError("Keeping the end tangents needs at least 5 points.")
    inner_knots = len(knots) - 2 * (degree + 1)
    if inner_knots < 0:
        raise RuntimeError("count must be at least degree + 1.")
    ks = sorted(set(knots))
    mults = [knots.count(k) for k in ks]
    native = (np.array(us) - us[0]) / (us[-1] - us[0])
    best = None
    for start in (t, native):
        cur = np.array(start)
        for _round in range(rounds):
            rows = np.array([basis_row(knots, degree, float(min(max(x, 0.0), 1.0 - 1e-15))) for x in cur])
            rows[-1] = 0.0
            rows[-1, -1] = 1.0
            poles = lsq_poles(rows, pts, n, keep_tan, d0, d1)
            g = to_geom({"degree": degree, "poles": poles.tolist(), "weights": [], "knots": ks, "mults": mults, "periodic": False})
            near = np.empty(len(cur))
            resid = 0.0
            for i in range(len(cur)):
                proj = GeomAPI_ProjectPointOnCurve(gp_Pnt(*pts[i]), g)
                near[i] = proj.LowerDistanceParameter() if proj.NbPoints() else cur[i]
                resid = max(resid, proj.LowerDistance() if proj.NbPoints() else 0.0)
            if best is None or resid < best[0]:
                best = (resid, g)
            near[0], near[-1] = 0.0, 1.0
            near = np.maximum.accumulate(near)
            if np.abs(near - cur).max() < 1e-10:
                break
            cur = near
    return best[1], best[0]


def tangent_unit(g, u):
    v = g.DN(u, 1)
    a = np.array([v.X(), v.Y(), v.Z()])
    return a / (np.linalg.norm(a) or 1.0)


def lsq_poles(rows, pts, n, keep_tan, d0, d1):
    q0, q1 = pts[0], pts[-1]
    m = len(pts)
    rhs = pts - np.outer(rows[:, 0], q0) - np.outer(rows[:, n - 1], q1)
    free = list(range(2, n - 2)) if keep_tan else list(range(1, n - 1))
    cols = []
    for j in free:
        for ax in range(3):
            v = np.zeros(3 * m)
            v[ax::3] = rows[:, j]
            cols.append(v)
    if keep_tan:
        rhs = rhs - np.outer(rows[:, 1], q0) - np.outer(rows[:, n - 2], q1)
        cols.append(np.kron(rows[:, 1], d0))
        cols.append(np.kron(rows[:, n - 2], -d1))
    poles = np.zeros((n, 3))
    poles[0], poles[-1] = q0, q1
    if cols:
        sol = np.linalg.lstsq(np.stack(cols, axis=1), rhs.reshape(-1), rcond=None)[0]
        for k, j in enumerate(free):
            poles[j] = sol[3 * k : 3 * k + 3]
        if keep_tan:
            poles[1] = q0 + sol[3 * len(free)] * d0
            poles[n - 2] = q1 - sol[3 * len(free) + 1] * d1
    return poles


def change_degree(p):
    tol, _ang = tolerances(p)
    src = to_geom(p.get("curve"))
    want = int(p.get("degree", 3))
    if want < 1 or want > MAX_DEGREE:
        raise RuntimeError("The degree must be from 1 to %d." % MAX_DEGREE)
    have = src.Degree()
    if want == have:
        return finish(src, tol, {"deviation": 0.0})
    if want > have:
        src.IncreaseDegree(want)
        return finish(src, tol, {"deviation": 0.0})
    if src.IsPeriodic():
        src.SetNotPeriodic()
    g, dev = refit_geom(src, tol, want, want, 0 if want == 1 else min(want - 1, 2))
    return finish(g, tol, {"deviation": dev, "within": bool(dev <= tol * (1 + 1e-9)), "pole_count": g.NbPoles()})


def knot_insert(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    u = float(p.get("u"))
    mult = int(p.get("mult", 1))
    if not (g.FirstParameter() <= u <= g.LastParameter()) and not g.IsPeriodic():
        raise RuntimeError("The parameter is outside the curve.")
    if mult < 1 or mult > g.Degree():
        raise RuntimeError("The multiplicity is from 1 to the degree.")
    ends = (g.FirstParameter(), g.LastParameter())
    if not g.IsPeriodic() and min(abs(u - ends[0]), abs(u - ends[1])) < 1e-12:
        raise RuntimeError("The parameter is at the end of the curve.")
    before = from_geom(g)
    g.InsertKnot(u, mult, 1e-12, True)
    ref = to_geom(before)
    return finish(g, tol, {"deviation": deviation(g, ref, 4), "pole_count": g.NbPoles()})


def find_knot(g, u):
    best, bi = None, 1
    for i in range(1, g.NbKnots() + 1):
        d = abs(g.Knot(i) - u)
        if best is None or d < best:
            best, bi = d, i
    return bi


def knot_remove(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    ref = to_geom(p.get("curve"))
    if p.get("index") is not None:
        idx = int(p["index"])
    else:
        idx = find_knot(g, float(p.get("u")))
    if idx < 1 or idx > g.NbKnots():
        raise RuntimeError("No such knot.")
    interior = 1 < idx < g.NbKnots() or g.IsPeriodic()
    if not interior:
        raise RuntimeError("The end knots cannot be removed.")
    have = g.Multiplicity(idx)
    target = int(p.get("mult", have - 1))
    if target < 0 or target >= have:
        raise RuntimeError("The new multiplicity must be from 0 to %d." % (have - 1))
    ok = bool(g.RemoveKnot(idx, target, tol))
    dev = deviation(g, ref, 8) if ok else 0.0
    dev = max(dev, deviation(ref, g, 8)) if ok else 0.0
    return finish(g, tol, {"removed": ok, "deviation": dev, "pole_count": g.NbPoles()})


def simplify(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    ref = to_geom(p.get("curve"))
    removed = 0
    changed = True
    while changed:
        changed = False
        for idx in range(g.NbKnots() - 1, 1, -1):
            if g.Multiplicity(idx) == 0:
                continue
            have = g.Multiplicity(idx)
            for target in range(0, have):
                trial = Geom_BSplineCurve(g)
                if trial.RemoveKnot(idx, target, tol):
                    d = max(deviation(trial, ref, 6), deviation(ref, trial, 6))
                    if d <= tol:
                        g = trial
                        removed += have - target
                        changed = True
                        break
            if changed:
                break
    dev = max(deviation(g, ref, 8), deviation(ref, g, 8))
    return finish(g, tol, {"removed": removed, "deviation": dev, "pole_count": g.NbPoles()})


def periodic(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    want = bool(p.get("periodic", True))
    ref = to_geom(p.get("curve"))
    if want and not g.IsPeriodic():
        if not g.IsClosed():
            raise RuntimeError("Only a closed curve can be made periodic.")
        try:
            g.SetPeriodic()
        except Exception:
            raise RuntimeError("The curve is closed but not smooth enough at the join to be made periodic.")
    elif not want and g.IsPeriodic():
        g.SetNotPeriodic()
    return finish(g, tol, {"deviation": deviation(g, ref, 4)})


def trim(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    u0, u1 = float(p.get("u0")), float(p.get("u1"))
    if not u1 > u0:
        raise RuntimeError("u1 must be greater than u0.")
    if not g.IsPeriodic() and (u0 < g.FirstParameter() - 1e-12 or u1 > g.LastParameter() + 1e-12):
        raise RuntimeError("The parameters are outside the curve.")
    g.Segment(u0, u1, 1e-12)
    return finish(g, tol)


def reverse(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    g.Reverse()
    return finish(g, tol)


def plane_normal(g):
    pts = np.array([point_of(g, u) for u in span_params(g, 6)])
    c = pts.mean(axis=0)
    _u, s, vt = np.linalg.svd(pts - c)
    scale = max(float(s[0]), 1e-300)
    if s[-1] / scale > 1e-7:
        raise RuntimeError("The curve is not planar; give the plane normal.")
    if s[1] / scale < 1e-9:
        return None
    return vt[2]


def offset(p):
    tol, _ang = tolerances(p)
    src = to_geom(p.get("curve"))
    dist = float(p.get("distance", 0.0))
    if not math.isfinite(dist) or abs(dist) <= tol:
        raise RuntimeError("The offset distance must be larger than the tolerance.")
    if src.Degree() > 1 and src.Continuity() == GeomAbs_C0:
        raise RuntimeError("The curve has a kink; offset needs at least tangent continuity.")
    n = p.get("normal")
    if n is None:
        got = plane_normal(src)
        if got is None:
            raise RuntimeError("The curve is straight; give the plane normal.")
        n = [float(x) for x in got]
    n = vec3(n)
    nl = math.sqrt(sum(c * c for c in n))
    if nl <= 1e-12:
        raise RuntimeError("The plane normal has zero length.")
    exact = Geom_OffsetCurve(src, -dist, gp_Dir(n[0] / nl, n[1] / nl, n[2] / nl), True)
    us = span_params(src, int(p.get("samples", 24)))
    pts = [point_of(exact, u) for u in us]
    t = tol
    best = None
    for _ in range(4):
        g = approx_points(pts, "chord", 3, 8, 2, t, us)
        dev = offset_error(g, exact, us)
        best = (g, dev)
        if dev <= tol:
            break
        t *= 0.2
    g, dev = best
    return finish(g, tol, {"deviation": dev, "within": bool(dev <= tol * (1 + 1e-9)), "pole_count": g.NbPoles()})


def offset_error(g, exact, us):
    lo, hi = us[0], us[-1]
    dense = np.array([point_of(exact, u) for u in np.linspace(lo, hi, max(len(us) * 24, 400))])
    a, b = dense[:-1], dense[1:]
    ab = b - a
    denom = np.maximum((ab * ab).sum(axis=1), 1e-300)
    worst = 0.0
    for u in span_params(g, 8):
        q = np.array(point_of(g, u))
        t = np.clip(((q - a) * ab).sum(axis=1) / denom, 0.0, 1.0)
        d = np.linalg.norm(a + ab * t[:, None] - q, axis=1)
        worst = max(worst, float(d.min()))
    return worst


def end_frame(g, which):
    u = g.LastParameter() if which == "end" else g.FirstParameter()
    props = GeomLProp_CLProps(g, u, 2, 1e-9)
    if not props.IsTangentDefined():
        raise RuntimeError("The curve end has no tangent.")
    td = gp_Dir()
    props.Tangent(td)
    tangent = gp_Vec(td.X(), td.Y(), td.Z())
    k = props.Curvature()
    nv = gp_Vec(0, 0, 0)
    if k > 1e-12:
        d = gp_Dir()
        props.Normal(d)
        nv = gp_Vec(d.X(), d.Y(), d.Z())
    return g.Value(u), tangent, k, nv


def extend(p):
    tol, _ang = tolerances(p)
    g = to_geom(p.get("curve"))
    if g.IsPeriodic():
        raise RuntimeError("A periodic curve has no ends to extend.")
    which = str(p.get("end", "end"))
    style = str(p.get("style", "line"))
    length = float(p.get("length", 0.0))
    if which not in ("start", "end") or style not in ("line", "arc", "smooth"):
        raise RuntimeError("end is start or end; style is line, arc or smooth.")
    if not math.isfinite(length) or length <= tol:
        raise RuntimeError("The extension length must be larger than the tolerance.")
    pt, tv, k, nv = end_frame(g, which)
    tdir = gp_Dir(tv)
    sign = 1.0 if which == "end" else -1.0
    used = style
    if style == "smooth":
        far = [pt.X() + sign * tdir.X() * length + 0.5 * k * nv.X() * length * length, pt.Y() + sign * tdir.Y() * length + 0.5 * k * nv.Y() * length * length, pt.Z() + sign * tdir.Z() * length + 0.5 * k * nv.Z() * length * length]
        mid = [pt.X() + sign * tdir.X() * length / 2, pt.Y() + sign * tdir.Y() * length / 2, pt.Z() + sign * tdir.Z() * length / 2]
        ordered = [[pt.X(), pt.Y(), pt.Z()], mid, far] if which == "end" else [far, mid, [pt.X(), pt.Y(), pt.Z()]]
        comp = GeomConvert_CompCurveToBSplineCurve(g)
        if not comp.Add(Geom_BezierCurve(pnt_array(ordered)), max(tol * 10, 1e-6), which == "end", True, 0):
            raise RuntimeError("The extension could not be joined to the curve.")
        return finish(comp.BSplineCurve(), tol, {"style_used": "smooth", "added_length": length})
    if style == "arc" and k * length < 1e-9:
        used = "line"
    comp = GeomConvert_CompCurveToBSplineCurve(g)
    if used == "line":
        start = pt if which == "end" else gp_Pnt(pt.X() - tdir.X() * length, pt.Y() - tdir.Y() * length, pt.Z() - tdir.Z() * length)
        piece = Geom_TrimmedCurve(Geom_Line(start, tdir), 0.0, length)
    else:
        radius = 1.0 / k
        nd = gp_Dir(nv)
        axis = tdir.Crossed(nd)
        centre = gp_Pnt(pt.X() + nd.X() * radius, pt.Y() + nd.Y() * radius, pt.Z() + nd.Z() * radius)
        xdir = gp_Dir(pt.X() - centre.X(), pt.Y() - centre.Y(), pt.Z() - centre.Z())
        circle = Geom_Circle(gp_Ax2(centre, axis, xdir), radius)
        angle = length * k
        piece = Geom_TrimmedCurve(circle, 0.0, angle) if which == "end" else Geom_TrimmedCurve(circle, -angle, 0.0)
    if not comp.Add(piece, max(tol * 10, 1e-6), which == "end", True, 0):
        raise RuntimeError("The extension could not be joined to the curve.")
    return finish(comp.BSplineCurve(), tol, {"style_used": used, "added_length": length})


def continuity(p):
    tol, ang = tolerances(p, floor=False)
    a, b = to_geom(p.get("a")), to_geom(p.get("b"))
    ua = a.LastParameter() if p.get("end_a", "end") == "end" else a.FirstParameter()
    ub = b.LastParameter() if p.get("end_b", "start") == "end" else b.FirstParameter()
    curv = float(p.get("curvature_tol", 1e-3))
    out = {"tolerances_used": {"position": tol, "angle": ang, "curvature_relative": curv}}
    ka = GeomLProp_CLProps(a, ua, 2, 1e-12).Curvature()
    kb = GeomLProp_CLProps(b, ub, 2, 1e-12).Curvature()
    out["curvature_a"], out["curvature_b"] = ka, kb
    straight = max(ka, kb) < 1e-12
    la = LocalAnalysis_CurveContinuity(a, ua, b, ub, GeomAbs_G1 if straight or min(ka, kb) < 1e-12 else GeomAbs_G2, 1e-12, tol, ang, ang, ang, ang, curv, 1e9)
    out["is_done"] = bool(la.IsDone())
    if not la.IsDone():
        out["status_error"] = str(la.StatusError()).split(".")[-1]
        return out
    out["position_gap"] = la.C0Value()
    out["g0"] = bool(la.IsC0())
    out["g1"] = bool(la.IsG1())
    try:
        out["tangent_angle"] = la.G1Angle()
    except Exception:
        out["tangent_angle"] = None
    if straight:
        out["g2"] = bool(out["g1"])
        out["normal_angle"], out["curvature_variation"] = 0.0, 0.0
    elif min(ka, kb) < 1e-12:
        out["g2"] = False
        out["normal_angle"], out["curvature_variation"] = None, 1.0
    else:
        out["g2"] = bool(la.IsG2())
        out["normal_angle"], out["curvature_variation"] = la.G2Angle(), la.G2CurvatureVariation()
    return out


def evaluate(p):
    g = to_geom(p.get("curve"))
    order = int(p.get("derivs", 0))
    if order < 0 or order > 3:
        raise RuntimeError("derivs is from 0 to 3.")
    us = [float(u) for u in p.get("params") or []][:MAX_POINTS]
    if not us:
        us = [g.FirstParameter(), g.LastParameter()]
    pts, dv = [], []
    for u in us:
        q, d = derivs(g, u, order)
        pts.append(q)
        dv.append(d)
    return {"points": pts, "derivatives": dv, "domain": [g.FirstParameter(), g.LastParameter()]}


def to_shape(p):
    tol, _ang = tolerances(p)
    ids, report = [], []
    recs = p.get("curves") or []
    if not recs or len(recs) > 4096:
        raise RuntimeError("Give from 1 to 4096 curves.")
    for rec in recs:
        g = to_geom(rec)
        edge = BRepBuilderAPI_MakeEdge(g).Edge()
        fix = ShapeFix_ShapeTolerance()
        fix.SetTolerance(edge, tol)
        ids.append(store.put(edge))
        report.append(audit_edge(edge, tol))
    return {"ids": ids, "tolerances": report, "tol_used": tol}


def from_shape(p):
    tol, _ang = tolerances(p)
    shape = store.shape_of(p.get("id"))
    maps = store.maps_of(p.get("id"))["edges"]
    idx = int(p.get("edge", 0))
    if idx < 0 or idx >= maps.Extent():
        raise RuntimeError("The shape has %d edges." % maps.Extent())
    edge = TopoDS.Edge(maps.FindKey(idx + 1))
    ad = BRepAdaptor_Curve(edge)
    first, last = ad.FirstParameter(), ad.LastParameter()
    curve = BRep_Tool.Curve_s(edge, first, last)
    if curve is None:
        raise RuntimeError("The edge has no 3D curve.")
    bs = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, first, last))
    bs.Transform(ad.Trsf())
    return finish(bs, tol)


METHODS = {
    "curve_make": make,
    "curve_interpolate": interpolate,
    "curve_approximate": approximate,
    "curve_refit": refit,
    "curve_rebuild": rebuild,
    "curve_degree": change_degree,
    "curve_knot_insert": knot_insert,
    "curve_knot_remove": knot_remove,
    "curve_simplify": simplify,
    "curve_periodic": periodic,
    "curve_trim": trim,
    "curve_reverse": reverse,
    "curve_offset": offset,
    "curve_extend": extend,
    "curve_continuity": continuity,
    "curve_eval": evaluate,
    "curve_to_shape": to_shape,
    "curve_from_shape": from_shape,
}
