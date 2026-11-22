import math

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_CompCurve
from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_UniformAbscissa
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface, Geom_RectangularTrimmedSurface, Geom_TrimmedCurve
from OCP.GeomConvert import GeomConvert
from OCP.ShapeFix import ShapeFix_Shape, ShapeFix_ShapeTolerance
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopoDS import TopoDS_Compound, TopoDS_CompSolid, TopoDS_Edge, TopoDS_Face, TopoDS_Iterator, TopoDS_Shell, TopoDS_Solid, TopoDS_Vertex, TopoDS_Wire
from OCP.collections import Array1_double, Array1_gp_Pnt, Array1_int, Array2_double, Array2_gp_Pnt
from OCP.gp import gp_Pnt, gp_Vec
from scipy.interpolate import BSpline
from scipy.spatial import cKDTree

import kernel_store as store
from kernel_surf import TopoDS, curve_wire, face_of, finish, tolerances

FIT_SHARE = 0.25
MIN_DEGREE = 3
AXIS_CAP = 512
FACE_CAP = 40000
ROUNDS = 40
TEST_AT = (1.0 / 6.0, 0.5, 5.0 / 6.0)
REPORT_AT = (0.12, 0.37, 0.63, 0.88)
REPORT_AXIS = 240
CHUNK = 2048
RAIL_START = 128
RAIL_MOST = 4096
GRID = 48
PAST_EDGE = 0.5
CAGE_MOST = 16


def vec(value, what):
    try:
        out = [float(c) for c in value]
    except (TypeError, ValueError):
        raise RuntimeError("%s needs three numbers." % what)
    if len(out) == 2:
        out.append(0.0)
    if len(out) != 3 or not all(math.isfinite(c) for c in out):
        raise RuntimeError("%s needs three finite numbers." % what)
    return np.array(out)


def unit(v, what):
    size = float(np.linalg.norm(v))
    if size < 1e-9:
        raise RuntimeError("%s has no length." % what)
    return v / size


def rows_unit(a):
    size = np.linalg.norm(a, axis=1, keepdims=True)
    return a / np.where(size > 1e-300, size, 1.0)


def dot(a, b):
    return np.einsum("ij,ij->i", a, b)


def basis(x, t, p, deriv=False, extend=False):
    b = BSpline.design_matrix(x, t, p, extend).toarray()
    if not deriv:
        return b
    d = np.zeros_like(b)
    n = b.shape[1]
    if p > 0:
        low = BSpline.design_matrix(x, t[1:-1], p - 1, extend).toarray()
        for i in range(n):
            if i >= 1 and t[i + p] > t[i]:
                d[:, i] += p * low[:, i - 1] / (t[i + p] - t[i])
            if i + 1 < n and t[i + p + 1] > t[i + 1]:
                d[:, i] -= p * low[:, i] / (t[i + p + 1] - t[i + 1])
    return b, d


def greville(t, p):
    n = len(t) - p - 1
    return np.clip(np.array([t[i + 1:i + p + 1].sum() / p for i in range(n)]), t[0], t[-1])


def spans_of(t):
    k = np.unique(t)
    return k[:-1], k[1:]


def span_points(t, fractions):
    lo, hi = spans_of(t)
    x = np.concatenate([lo + (hi - lo) * f for f in fractions])
    idx = np.concatenate([np.arange(len(lo))] * len(fractions))
    order = np.argsort(x, kind="stable")
    return x[order], idx[order], len(lo)


def along(mats, q):
    out = q
    for ax, m in enumerate(mats):
        out = np.moveaxis(np.tensordot(m, out, axes=(1, ax)), 0, ax)
    return out


def solve_along(mats, r):
    out = r
    for ax, m in enumerate(mats):
        moved = np.moveaxis(out, ax, 0)
        got = np.linalg.solve(m, moved.reshape(moved.shape[0], -1)).reshape(moved.shape)
        out = np.moveaxis(got, 0, ax)
    return out


def raised(t, by):
    if by <= 0:
        return t.copy()
    values, counts = np.unique(t, return_counts=True)
    return np.repeat(values, counts + by)


def cartesian(h):
    return h[..., :3] / h[..., 3:]


class Fit:
    def __init__(self, knots, degrees, net, mapping):
        self.t0 = knots
        self.p0 = degrees
        self.p = [max(g, MIN_DEGREE) for g in degrees]
        self.q0 = net
        self.mapping = mapping
        self.t = [raised(k, p - g) for k, g, p in zip(knots, degrees, self.p)]
        self.q = None
        self.rounds = 0
        self.capped = False
        self.moved = 0.0

    def source(self, points):
        return along([basis(x, t, p) for x, t, p in zip(points, self.t0, self.p0)], self.q0)

    def mapped(self, points):
        h = self.source(points)
        x = cartesian(h)
        return x, self.mapping(x.reshape(-1, 3)).reshape(x.shape), h[..., 3:]

    def error(self, points):
        _x, y, _w = self.mapped(points)
        got = cartesian(along([basis(x, t, p) for x, t, p in zip(points, self.t, self.p)], self.q))
        return np.linalg.norm(got - y, axis=-1)

    def solve(self):
        g = [greville(t, p) for t, p in zip(self.t, self.p)]
        x, y, w = self.mapped(g)
        self.moved = float(np.linalg.norm(y - x, axis=-1).max())
        self.q = solve_along([basis(a, t, p) for a, t, p in zip(g, self.t, self.p)], np.concatenate([y * w, w], axis=-1))
        return g

    def marks(self, g, limit):
        dims = len(self.t)
        out = []
        for k in range(dims):
            x, idx, count = span_points(self.t[k], TEST_AT)
            pts = list(g)
            pts[k] = x
            err = self.error(pts)
            line = err.max(axis=tuple(a for a in range(dims) if a != k)) if dims > 1 else err
            worst = np.zeros(count)
            np.maximum.at(worst, idx, line)
            out.append(worst > limit)
        if any(m.any() for m in out):
            return out
        tests = [span_points(t, TEST_AT) for t in self.t]
        err = self.error([s[0] for s in tests])
        for k in range(dims):
            line = err.max(axis=tuple(a for a in range(dims) if a != k)) if dims > 1 else err
            worst = np.zeros(tests[k][2])
            np.maximum.at(worst, tests[k][1], line)
            out[k] = worst > limit
        return out

    def grow(self, marks, cap):
        sizes = [len(t) - p - 1 + int(m.sum()) for t, p, m in zip(self.t, self.p, marks)]
        if max(sizes) > AXIS_CAP or int(np.prod(sizes)) > cap:
            return False
        for k, m in enumerate(marks):
            lo, hi = spans_of(self.t[k])
            self.t[k] = np.sort(np.concatenate([self.t[k], (lo[m] + hi[m]) / 2.0]))
        return True

    def run(self, limit, cap):
        for _ in range(ROUNDS):
            self.rounds += 1
            g = self.solve()
            marks = self.marks(g, limit)
            if not any(m.any() for m in marks):
                return self
            if not self.grow(marks, cap):
                self.capped = True
                return self
        self.capped = True
        return self

    def deviation(self):
        pts = []
        for t in self.t:
            count = len(np.unique(t)) - 1
            per = len(REPORT_AT) if count * len(REPORT_AT) <= REPORT_AXIS else (2 if count * 2 <= REPORT_AXIS else 1)
            fractions = REPORT_AT[:per] if per > 1 else (0.37,)
            pts.append(span_points(t, fractions)[0])
        err = self.error(pts)
        return float(err.max()), float(err.sum()), int(err.size)


def knot_arrays(t):
    values, counts = np.unique(t, return_counts=True)
    ks = Array1_double(1, len(values))
    ms = Array1_int(1, len(values))
    for i, (v, c) in enumerate(zip(values, counts)):
        ks.SetValue(i + 1, float(v))
        ms.SetValue(i + 1, int(c))
    return ks, ms


def surface_net(bs):
    nu, nv = bs.NbUPoles(), bs.NbVPoles()
    q = np.empty((nu, nv, 4))
    for i in range(nu):
        for j in range(nv):
            c = bs.Pole(i + 1, j + 1)
            w = bs.Weight(i + 1, j + 1)
            q[i, j] = (c.X() * w, c.Y() * w, c.Z() * w, w)
    return [np.array(list(bs.UKnotSequence())), np.array(list(bs.VKnotSequence()))], q


def curve_net(bc):
    n = bc.NbPoles()
    q = np.empty((n, 4))
    for i in range(n):
        c = bc.Pole(i + 1)
        w = bc.Weight(i + 1)
        q[i] = (c.X() * w, c.Y() * w, c.Z() * w, w)
    return [np.array(list(bc.KnotSequence()))], q


def open_surface(face, trim_pad):
    surf = BRep_Tool.Surface_s(face)
    a0, a1, b0, b1 = BRepTools.UVBounds_s(face)
    if not isinstance(surf, Geom_BSplineSurface):
        surf = GeomConvert.SurfaceToBSplineSurface_s(Geom_RectangularTrimmedSurface(surf, a0, a1, b0, b1))
    bs = Geom_BSplineSurface(surf)
    if bs.IsUPeriodic():
        bs.SetUNotPeriodic()
    if bs.IsVPeriodic():
        bs.SetVNotPeriodic()
    u0, u1, v0, v1 = bs.Bounds()
    du, dv = u1 - u0, v1 - v0
    if a0 < u0 - 1e-6 * du or a1 > u1 + 1e-6 * du or b0 < v0 - 1e-6 * dv or b1 > v1 + 1e-6 * dv:
        raise RuntimeError("A face is trimmed across the seam of a periodic surface; split it at the seam first.")
    lu, hu = max(u0, a0 - trim_pad * (a1 - a0)), min(u1, a1 + trim_pad * (a1 - a0))
    lv, hv = max(v0, b0 - trim_pad * (b1 - b0)), min(v1, b1 + trim_pad * (b1 - b0))
    if hu - lu > 1e-9 * du and hv - lv > 1e-9 * dv and (hu - lu < 0.9 * du or hv - lv < 0.9 * dv):
        bs.Segment(lu, hu, lv, hv)
    else:
        bs.Segment(u0, u1, v0, v1)
    return bs


def open_curve(edge):
    curve = BRep_Tool.Curve_s(edge, 0.0, 0.0)
    f, l = BRep_Tool.Range_s(edge)
    if not isinstance(curve, Geom_BSplineCurve):
        curve = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, f, l))
    bc = Geom_BSplineCurve(curve)
    if bc.IsPeriodic():
        bc.SetNotPeriodic()
    c0, c1 = bc.FirstParameter(), bc.LastParameter()
    span = c1 - c0
    if f < c0 - 1e-6 * span or l > c1 + 1e-6 * span:
        raise RuntimeError("An edge runs across the seam of a periodic curve; split it at the seam first.")
    f, l = max(f, c0), min(l, c1)
    if l - f > 1e-9 * span:
        bc.Segment(f, l)
    return bc


class Rebuild:
    def __init__(self, mapping, tol, cap, mirror):
        self.mapping = mapping
        self.limit = tol * FIT_SHARE
        self.tol = tol
        self.cap = cap
        self.mirror = mirror
        self.keys = store.ShapeMap()
        self.made = {}
        self.b = BRep_Builder()
        self.face_max = 0.0
        self.face_sum = 0.0
        self.samples = 0
        self.edge_max = 0.0
        self.poles = 0
        self.largest = [0, 0]
        self.capped = 0
        self.rounds = 0
        self.moved = 0.0
        self.faces = 0

    def image(self, shape):
        return self.made.get(self.keys.FindIndex(shape))

    def keep(self, shape, new):
        self.made[self.keys.Add(shape)] = new
        return new

    def vertex(self, v):
        got = self.image(v)
        if got is None:
            q = BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))
            to = self.mapping(np.array([[q.X(), q.Y(), q.Z()]]))[0]
            got = TopoDS_Vertex()
            self.b.MakeVertex(got, gp_Pnt(*[float(c) for c in to]), self.limit)
            self.keep(v, got)
        return got

    def edge(self, e):
        got = self.image(e)
        if got is not None:
            return got
        old = TopoDS.Edge_s(e.Oriented(TopAbs_FORWARD))
        got = TopoDS_Edge()
        self.b.MakeEdge(got)
        if BRep_Tool.Degenerated_s(old) or BRep_Tool.Curve_s(old, 0.0, 0.0) is None:
            self.b.Degenerated(got, True)
        else:
            bc = open_curve(old)
            knots, net = curve_net(bc)
            fit = Fit(knots, [bc.Degree()], net, self.mapping).run(self.limit, AXIS_CAP)
            worst, _total, _count = fit.deviation()
            self.edge_max = max(self.edge_max, worst)
            self.moved = max(self.moved, fit.moved)
            self.capped += 1 if fit.capped else 0
            n = fit.q.shape[0]
            poles = Array1_gp_Pnt(1, n)
            weights = Array1_double(1, n)
            pts = cartesian(fit.q)
            for i in range(n):
                poles.SetValue(i + 1, gp_Pnt(float(pts[i, 0]), float(pts[i, 1]), float(pts[i, 2])))
                weights.SetValue(i + 1, float(fit.q[i, 3]) if bc.IsRational() else 1.0)
            ks, ms = knot_arrays(fit.t[0])
            self.b.UpdateEdge(got, Geom_BSplineCurve(poles, weights, ks, ms, fit.p[0], False), self.limit)
        f, l = BRep_Tool.Range_s(old)
        self.b.Range(got, f, l)
        it = TopoDS_Iterator(old, True, True)
        while it.More():
            v = it.Value()
            if v.ShapeType() == TopAbs_VERTEX:
                self.b.Add(got, self.vertex(v).Oriented(v.Orientation()))
            it.Next()
        return self.keep(e, got)

    def surface(self, face):
        bs = open_surface(face, 0.02)
        knots, net = surface_net(bs)
        fit = Fit(knots, [bs.UDegree(), bs.VDegree()], net, self.mapping).run(self.limit, self.cap)
        worst, total, count = fit.deviation()
        self.face_max = max(self.face_max, worst)
        self.face_sum += total
        self.samples += count
        self.moved = max(self.moved, fit.moved)
        self.capped += 1 if fit.capped else 0
        self.rounds = max(self.rounds, fit.rounds)
        nu, nv = fit.q.shape[:2]
        self.poles += nu * nv
        self.faces += 1
        if nu * nv > self.largest[0] * self.largest[1]:
            self.largest = [nu, nv]
        rational = bs.IsURational() or bs.IsVRational()
        poles = Array2_gp_Pnt(1, nu, 1, nv)
        weights = Array2_double(1, nu, 1, nv)
        pts = cartesian(fit.q)
        for i in range(nu):
            for j in range(nv):
                poles.SetValue(i + 1, j + 1, gp_Pnt(float(pts[i, j, 0]), float(pts[i, j, 1]), float(pts[i, j, 2])))
                weights.SetValue(i + 1, j + 1, float(fit.q[i, j, 3]) if rational else 1.0)
        uk, um = knot_arrays(fit.t[0])
        vk, vm = knot_arrays(fit.t[1])
        return Geom_BSplineSurface(poles, weights, uk, vk, um, vm, fit.p[0], fit.p[1], False, False)

    def face(self, f):
        got = self.image(f)
        if got is not None:
            return got
        old = TopoDS.Face_s(f.Oriented(TopAbs_FORWARD))
        got = TopoDS_Face()
        self.b.MakeFace(got, self.surface(old), self.limit)
        done = store.ShapeMap()
        it = TopoDS_Iterator(old, True, True)
        while it.More():
            w = it.Value()
            it.Next()
            if w.ShapeType() != TopAbs_WIRE:
                continue
            wire = TopoDS_Wire()
            self.b.MakeWire(wire)
            ew = TopoDS_Iterator(w.Oriented(TopAbs_FORWARD), True, True)
            while ew.More():
                e = TopoDS.Edge_s(ew.Value())
                ew.Next()
                new = self.edge(e)
                if done.FindIndex(e) == 0:
                    done.Add(e)
                    fwd = TopoDS.Edge_s(e.Oriented(TopAbs_FORWARD))
                    c1 = BRep_Tool.CurveOnSurface_s(fwd, old, 0.0, 0.0)
                    if c1 is None:
                        raise RuntimeError("An edge has no trim curve on its face.")
                    if BRep_Tool.IsClosed_s(fwd, old):
                        c2 = BRep_Tool.CurveOnSurface_s(TopoDS.Edge_s(fwd.Reversed()), old, 0.0, 0.0)
                        self.b.UpdateEdge(new, c1, c2, got, self.limit)
                    else:
                        self.b.UpdateEdge(new, c1, got, self.limit)
                    a, z = BRep_Tool.Range_s(fwd)
                    self.b.Range(new, got, a, z)
                self.b.Add(wire, new.Oriented(e.Orientation()))
            wire.Closed(w.Closed())
            self.b.Add(got, wire.Oriented(w.Orientation()))
        self.b.NaturalRestriction(got, BRep_Tool.NaturalRestriction_s(old))
        return self.keep(f, got)

    def shape(self, s):
        kind = s.ShapeType()
        flip = s.Orientation()
        if kind == TopAbs_VERTEX:
            return self.vertex(s).Oriented(flip)
        if kind == TopAbs_EDGE:
            return self.edge(s).Oriented(flip)
        if kind == TopAbs_FACE:
            if self.mirror:
                flip = TopAbs_FORWARD if flip == TopAbs_REVERSED else (TopAbs_REVERSED if flip == TopAbs_FORWARD else flip)
            return self.face(s).Oriented(flip)
        got = self.image(s)
        if got is None:
            if kind == TopAbs_WIRE:
                got = TopoDS_Wire()
                self.b.MakeWire(got)
            elif kind == TopAbs_SHELL:
                got = TopoDS_Shell()
                self.b.MakeShell(got)
            elif kind == TopAbs_SOLID:
                got = TopoDS_Solid()
                self.b.MakeSolid(got)
            elif kind == TopAbs_COMPSOLID:
                got = TopoDS_CompSolid()
                self.b.MakeCompSolid(got)
            elif kind == TopAbs_COMPOUND:
                got = TopoDS_Compound()
                self.b.MakeCompound(got)
            else:
                raise RuntimeError("The shape holds a part that cannot be deformed.")
            it = TopoDS_Iterator(s.Oriented(TopAbs_FORWARD), True, True)
            while it.More():
                self.b.Add(got, self.shape(it.Value()))
                it.Next()
            got.Closed(s.Closed())
            self.keep(s, got)
        return got.Oriented(flip)


def mirrors(mapping, box):
    c = np.array([(box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0, (box[2] + box[5]) / 2.0])
    h = max(1e-4, 1e-5 * float(np.linalg.norm(np.array(box[3:]) - np.array(box[:3]))))
    pts = np.array([c + h * np.eye(3)[k] * sgn for k in range(3) for sgn in (1.0, -1.0)])
    y = mapping(pts)
    jac = np.array([(y[2 * k] - y[2 * k + 1]) / (2.0 * h) for k in range(3)])
    return float(np.linalg.det(jac)) < 0.0


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-6)
    return props.Mass()


def area_of(shape):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props.Mass()


def image_rows(src_maps, converted, work, out_maps, key):
    rows = {}
    src = src_maps[key]
    dst = out_maps[key]
    for i in range(1, src.Extent() + 1):
        to = []
        try:
            new = work.image(converted.ModifiedShape(src.FindKey(i)))
        except Exception:
            new = None
        if new is not None:
            idx = dst.FindIndex(new)
            if idx > 0:
                to = [idx - 1]
        rows[str(i - 1)] = {"to": to, "deleted": not to}
    return rows


def deform(p, op, mapping, extra):
    tol, ang = tolerances(p)
    ident = p.get("id")
    src = store.shape_of(ident)
    box = store.bbox_of(src)
    if box is None:
        raise RuntimeError("The object has no geometry to deform.")
    try:
        cap = int(p.get("max_points", FACE_CAP))
    except (TypeError, ValueError):
        raise RuntimeError("max_points must be a whole number.")
    cap = max(64, min(cap, 250000))
    before = store.summarize(src)
    converted = BRepBuilderAPI_NurbsConvert(src, True)
    if not converted.IsDone():
        raise RuntimeError("The object could not be converted to NURBS surfaces.")
    work = Rebuild(mapping, tol, cap, mirrors(mapping, box))
    out = work.shape(converted.Shape())
    BRepLib.SameParameter_s(out, 1e-7, True)
    ShapeFix_ShapeTolerance().LimitTolerance(out, 1e-7, max(tol, 4.0 * work.face_max, 4.0 * work.edge_max))
    healed = False
    if not BRepCheck_Analyzer(out).IsValid():
        fixer = ShapeFix_Shape(out)
        fixer.SetPrecision(tol)
        fixer.Perform()
        fixed = fixer.Shape()
        if not BRepCheck_Analyzer(fixed).IsValid() or store.summarize(fixed)["faces"] != before["faces"]:
            raise RuntimeError("The deformation gives a shape that is not valid; it may fold over itself, or the trims may not survive it.")
        out, healed = fixed, True
    worst = max(work.face_max, work.edge_max)
    report = {
        "deviation": {"max": worst, "faces": work.face_max, "edges": work.edge_max, "mean": work.face_sum / max(work.samples, 1), "samples": work.samples, "limit": tol, "within": worst <= tol, "fit_target": tol * FIT_SHARE},
        "largest_move": work.moved, "faces": work.faces, "poles": work.poles, "largest_net": work.largest, "rounds": work.rounds, "capped": work.capped, "mirrored": work.mirror, "healed": healed,
        "closed_before": bool(before["closed"]), "area": area_of(out),
    }
    if before["solids"]:
        report["volume_before"] = volume_of(src)
        report["volume"] = volume_of(out)
    report.update(extra)
    history = None
    if not healed:
        maps = store.build_maps(out)
        src_maps = store.maps_of(ident)
        history = {"inputs": [{"id": ident, "faces": image_rows(src_maps, converted, work, maps, "faces"), "edges": image_rows(src_maps, converted, work, maps, "edges")}]}
    return finish(op, out, tol, ang, report, history)


def bend(p):
    a = vec(p.get("start"), "The spine start")
    b = vec(p.get("end"), "The spine end")
    length = float(np.linalg.norm(b - a))
    t = unit(b - a, "The spine")
    limit = bool(p.get("limit", False))
    side = None
    if p.get("through") is not None:
        side = vec(p["through"], "The bend point") - a
    elif p.get("direction") is not None:
        side = vec(p["direction"], "The bend direction")
    if side is None:
        raise RuntimeError("Give a point to bend through, or an angle with a direction.")
    across = side - float(side @ t) * t
    if float(np.linalg.norm(across)) < 1e-9:
        raise RuntimeError("The bend point lies on the line of the spine; pick it to one side.")
    n = unit(across, "The bend direction")
    if p.get("angle") is not None:
        angle = float(p["angle"])
        if not math.isfinite(angle) or abs(angle) < 1e-9:
            raise RuntimeError("The bend angle must not be zero.")
        if angle < 0:
            n, angle = -n, -angle
        radius = length / angle
    else:
        radius = float(side @ side) / (2.0 * float(side @ n))
        angle = length / radius
    box = store.bbox_of(store.shape_of(p.get("id")))
    if box is None:
        raise RuntimeError("The object has no geometry to deform.")
    corners = np.array([[box[i], box[j], box[k]] for i in (0, 3) for j in (1, 4) for k in (2, 5)]) - a
    reach = float((corners @ n).max())
    along_spine = corners @ t
    if reach >= radius:
        raise RuntimeError("The bend radius %.6g mm is not larger than the object's reach of %.6g mm toward the bend centre; the object would fold over itself." % (radius, reach))
    turn = angle if limit else float(along_spine.max() - along_spine.min()) / radius
    if turn >= 2.0 * math.pi:
        raise RuntimeError("The bend would wrap the object more than a full turn.")
    centre = a + radius * n

    def mapping(x):
        d = x - a
        s = d @ t
        h = d @ n
        rest = d - np.outer(s, t) - np.outer(h, n)
        sc = np.clip(s, 0.0, length) if limit else s
        phi = sc / radius
        c, sn = np.cos(phi)[:, None], np.sin(phi)[:, None]
        return centre + (radius - h)[:, None] * (t * sn - n * c) + rest + (s - sc)[:, None] * (t * c + n * sn)

    return deform(p, "bend", mapping, {"radius": radius, "angle": angle, "spine_length": length, "limit": limit, "centre": [float(c) for c in centre]})


class Rail:
    def __init__(self, wire, tol, reverse):
        ad = BRepAdaptor_CompCurve(wire, False)
        self.length = float(GCPnts_AbscissaPoint.Length_s(ad))
        if not math.isfinite(self.length) or self.length < 1e-6:
            raise RuntimeError("A flow curve has no length.")
        n = RAIL_START
        while True:
            pts, tan = self.sample(ad, 2 * n)
            if reverse:
                pts, tan = pts[::-1], -tan[::-1]
            self.n, self.h = n, self.length / n
            self.p, self.tan = pts[::2], tan[::2]
            mid, _d, _dd = self.position(np.arange(n) * self.h + self.h / 2.0)
            self.error = float(np.linalg.norm(mid - pts[1::2], axis=1).max())
            if self.error <= tol / 100.0 or n >= RAIL_MOST:
                break
            n *= 2
        ref = np.array([0.0, 0.0, 1.0])
        first = ref - float(ref @ self.tan[0]) * self.tan[0]
        if float(np.linalg.norm(first)) < 1e-6:
            ref = np.array([1.0, 0.0, 0.0])
            first = ref - float(ref @ self.tan[0]) * self.tan[0]
        self.nor = np.empty_like(self.p)
        self.nor[0] = first / np.linalg.norm(first)
        for k in range(self.n):
            v1 = self.p[k + 1] - self.p[k]
            c1 = float(v1 @ v1)
            rl = self.nor[k] - (2.0 / c1) * float(v1 @ self.nor[k]) * v1
            tl = self.tan[k] - (2.0 / c1) * float(v1 @ self.tan[k]) * v1
            v2 = self.tan[k + 1] - tl
            c2 = float(v2 @ v2)
            self.nor[k + 1] = rl if c2 < 1e-24 else rl - (2.0 / c2) * float(v2 @ rl) * v2
        self.tree = cKDTree(self.p)

    @staticmethod
    def sample(ad, count):
        ua = GCPnts_UniformAbscissa(ad, count + 1, 1e-9)
        if not ua.IsDone() or ua.NbPoints() != count + 1:
            raise RuntimeError("A flow curve could not be measured along its length.")
        pts = np.empty((count + 1, 3))
        tan = np.empty((count + 1, 3))
        q, d = gp_Pnt(), gp_Vec()
        for i in range(count + 1):
            ad.D1(ua.Parameter(i + 1), q, d)
            pts[i] = (q.X(), q.Y(), q.Z())
            tan[i] = (d.X(), d.Y(), d.Z())
        return pts, rows_unit(tan)

    def position(self, s):
        k = np.clip(np.floor(s / self.h), 0, self.n - 1).astype(int)
        x = np.clip(s / self.h - k, 0.0, 1.0)[:, None]
        p0, p1, t0, t1 = self.p[k], self.p[k + 1], self.tan[k] * self.h, self.tan[k + 1] * self.h
        c = (2 * x**3 - 3 * x**2 + 1) * p0 + (x**3 - 2 * x**2 + x) * t0 + (-2 * x**3 + 3 * x**2) * p1 + (x**3 - x**2) * t1
        d = ((6 * x**2 - 6 * x) * p0 + (3 * x**2 - 4 * x + 1) * t0 + (-6 * x**2 + 6 * x) * p1 + (3 * x**2 - 2 * x) * t1) / self.h
        dd = ((12 * x - 6) * p0 + (6 * x - 4) * t0 + (-12 * x + 6) * p1 + (6 * x - 2) * t1) / self.h**2
        low, high = s < 0.0, s > self.length
        if low.any():
            c[low] = self.p[0] + s[low, None] * self.tan[0]
            d[low] = self.tan[0]
            dd[low] = 0.0
        if high.any():
            c[high] = self.p[-1] + (s[high, None] - self.length) * self.tan[-1]
            d[high] = self.tan[-1]
            dd[high] = 0.0
        return c, d, dd

    def frame(self, s):
        c, d, _dd = self.position(s)
        k = np.clip(np.floor(s / self.h), 0, self.n - 1).astype(int)
        x = np.clip(s / self.h - k, 0.0, 1.0)[:, None]
        tan = rows_unit(d)
        nor = (1.0 - x) * self.nor[k] + x * self.nor[k + 1]
        nor = rows_unit(nor - dot(nor, tan)[:, None] * tan)
        return c, nor, np.cross(tan, nor)

    def closest(self, x):
        _dist, idx = self.tree.query(x)
        s = idx * self.h
        for _ in range(30):
            c, d, dd = self.position(s)
            r = c - x
            slope = dot(d, d) + dot(r, dd)
            step = dot(r, d) / np.where(slope > 0.25, slope, 1.0)
            s = s - step
            if float(np.abs(step).max()) < 1e-12 * max(self.length, 1.0):
                break
        return s


def flow(p):
    tol, _ang = tolerances(p)
    if not isinstance(p.get("base"), dict) or not isinstance(p.get("target"), dict):
        raise RuntimeError("Give the base curve and the target curve.")
    base = Rail(curve_wire(p["base"]), tol, bool(p.get("reverse_base", False)))
    target = Rail(curve_wire(p["target"]), tol, bool(p.get("reverse_target", False)))
    stretch = bool(p.get("stretch", False))
    ratio = target.length / base.length if stretch else 1.0

    def mapping(x):
        out = np.empty_like(x)
        for i in range(0, len(x), 65536):
            part = x[i:i + 65536]
            s = base.closest(part)
            c, nor, bi = base.frame(s)
            r = part - c
            c2, n2, b2 = target.frame(s * ratio)
            out[i:i + 65536] = c2 + dot(r, nor)[:, None] * n2 + dot(r, bi)[:, None] * b2
        return out

    return deform(p, "flow", mapping, {"base_length": base.length, "target_length": target.length, "stretch": stretch, "ratio": ratio, "curve_error": max(base.error, target.error), "stations": [base.n, target.n]})


class Patch:
    def __init__(self, face):
        bs = open_surface(face, 0.0)
        knots, self.q = surface_net(bs)
        self.tu, self.tv = knots
        self.pu, self.pv = bs.UDegree(), bs.VDegree()
        self.u0, self.u1, self.v0, self.v1 = bs.Bounds()
        self.du, self.dv = self.u1 - self.u0, self.v1 - self.v0
        self.ulo, self.uhi = self.u0 - PAST_EDGE * self.du, self.u1 + PAST_EDGE * self.du
        self.vlo, self.vhi = self.v0 - PAST_EDGE * self.dv, self.v1 + PAST_EDGE * self.dv
        self.tree = None

    def at(self, u, v):
        s = np.empty((len(u), 3))
        su = np.empty_like(s)
        sv = np.empty_like(s)
        for i in range(0, len(u), CHUNK):
            bu, du = basis(u[i:i + CHUNK], self.tu, self.pu, True, True)
            bv, dv = basis(v[i:i + CHUNK], self.tv, self.pv, True, True)
            a = np.einsum("mi,mj,ijc->mc", bu, bv, self.q, optimize=True)
            au = np.einsum("mi,mj,ijc->mc", du, bv, self.q, optimize=True)
            av = np.einsum("mi,mj,ijc->mc", bu, dv, self.q, optimize=True)
            w = a[:, 3:]
            here = a[:, :3] / w
            s[i:i + CHUNK] = here
            su[i:i + CHUNK] = (au[:, :3] - here * au[:, 3:]) / w
            sv[i:i + CHUNK] = (av[:, :3] - here * av[:, 3:]) / w
        return s, su, sv

    @staticmethod
    def tangent_step(su, sv, r):
        a11, a12, a22 = dot(su, su), dot(su, sv), dot(sv, sv)
        b1, b2 = dot(su, r), dot(sv, r)
        det = a11 * a22 - a12 * a12
        ok = det > 1e-18 * np.maximum(a11 * a22, 1e-300)
        safe = np.where(ok, det, 1.0)
        return np.where(ok, (a22 * b1 - a12 * b2) / safe, 0.0), np.where(ok, (a11 * b2 - a12 * b1) / safe, 0.0)

    def invert(self, x):
        if self.tree is None:
            gu = np.linspace(self.u0, self.u1, GRID)
            gv = np.linspace(self.v0, self.v1, GRID)
            self.grid = np.array([[a, b] for a in gu for b in gv])
            self.tree = cKDTree(self.at(self.grid[:, 0], self.grid[:, 1])[0])
        _dist, idx = self.tree.query(x)
        u, v = self.grid[idx, 0].copy(), self.grid[idx, 1].copy()
        for _ in range(40):
            s, su, sv = self.at(u, v)
            a, b = self.tangent_step(su, sv, x - s)
            nu, nv = np.clip(u + a, self.ulo, self.uhi), np.clip(v + b, self.vlo, self.vhi)
            moved = max(float(np.abs(nu - u).max()) / self.du, float(np.abs(nv - v).max()) / self.dv)
            u, v = nu, nv
            if moved < 1e-13:
                break
        s, su, sv = self.at(u, v)
        r = x - s
        a, b = self.tangent_step(su, sv, r)
        normal = rows_unit(np.cross(su, sv))
        return (u + a - self.u0) / self.du, (v + b - self.v0) / self.dv, dot(r, normal)

    def place(self, ub, vb, h):
        u = self.u0 + ub * self.du
        v = self.v0 + vb * self.dv
        uc, vc = np.clip(u, self.ulo, self.uhi), np.clip(v, self.vlo, self.vhi)
        s, su, sv = self.at(uc, vc)
        normal = rows_unit(np.cross(su, sv))
        return s + su * (u - uc)[:, None] + sv * (v - vc)[:, None] + normal * h[:, None]


class Flat:
    def __init__(self, spec):
        self.o = vec(spec.get("origin"), "The base plane origin")
        self.x = vec(spec.get("x"), "The base plane first side")
        self.y = vec(spec.get("y"), "The base plane second side")
        normal = np.cross(self.x, self.y)
        if float(np.linalg.norm(normal)) < 1e-9 * max(float(np.linalg.norm(self.x)) * float(np.linalg.norm(self.y)), 1e-300) or float(np.linalg.norm(normal)) < 1e-12:
            raise RuntimeError("The two sides of the base plane must not be parallel or empty.")
        self.n = normal / np.linalg.norm(normal)
        self.inv = np.linalg.inv(np.array([self.x, self.y, self.n]).T)

    def invert(self, x):
        c = (x - self.o) @ self.inv.T
        return c[:, 0], c[:, 1], c[:, 2]


def flow_surface(p):
    base_spec, target_spec = p.get("base"), p.get("target")
    if not isinstance(base_spec, dict) or not isinstance(target_spec, dict) or not isinstance(target_spec.get("face"), dict):
        raise RuntimeError("Give the base surface or plane and the target surface.")
    if isinstance(base_spec.get("face"), dict):
        base = Patch(face_of(base_spec["face"]))
    elif isinstance(base_spec.get("plane"), dict):
        base = Flat(base_spec["plane"])
    else:
        raise RuntimeError("Give the base as a face or as a plane with an origin and two sides.")
    target = Patch(face_of(target_spec["face"]))
    swap, ru, rv, flip = (bool(p.get(k, False)) for k in ("swap_uv", "reverse_u", "reverse_v", "flip"))

    def mapping(x):
        u, v, h = base.invert(x)
        if swap:
            u, v = v, u
        if ru:
            u = 1.0 - u
        if rv:
            v = 1.0 - v
        return target.place(u, v, -h if flip else h)

    return deform(p, "flow_surface", mapping, {"base": "face" if isinstance(base, Patch) else "plane", "swap_uv": swap, "reverse_u": ru, "reverse_v": rv, "flip": flip})


def lattice_knots(count, degree):
    inner = count - degree - 1
    return np.array([0.0] * (degree + 1) + [(i + 1) / (inner + 1.0) for i in range(inner)] + [1.0] * (degree + 1))


def cage_setup(p):
    o = vec(p.get("origin"), "The cage origin")
    sides = np.array([vec(p.get(k), "A cage side") for k in ("x", "y", "z")])
    if abs(float(np.linalg.det(sides))) < 1e-12:
        raise RuntimeError("The cage box is flat; give three sides that span a volume.")
    try:
        counts = [int(c) for c in p.get("counts") or []]
        degrees = [int(c) for c in p.get("degrees") or []]
    except (TypeError, ValueError):
        raise RuntimeError("The cage point counts and degrees must be whole numbers.")
    if len(counts) != 3 or any(c < 2 or c > CAGE_MOST for c in counts):
        raise RuntimeError("A cage has from 2 to %d points in each of its three directions." % CAGE_MOST)
    if len(degrees) != 3 or any(g < 1 or g >= c for g, c in zip(degrees, counts)):
        raise RuntimeError("The cage degree in each direction is at least 1 and below the point count.")
    knots = [lattice_knots(c, g) for c, g in zip(counts, degrees)]
    grev = [greville(t, g) for t, g in zip(knots, degrees)]
    rest = o + np.einsum("i,c->ic", grev[0], sides[0])[:, None, None, :] + np.einsum("j,c->jc", grev[1], sides[1])[None, :, None, :] + np.einsum("k,c->kc", grev[2], sides[2])[None, None, :, :]
    return o, sides, counts, degrees, knots, rest


def cage_rest(p):
    _o, _sides, counts, degrees, _knots, rest = cage_setup(p)
    return {"counts": counts, "degrees": degrees, "points": rest.reshape(-1, 3).tolist()}


def cage(p):
    o, sides, counts, degrees, knots, rest = cage_setup(p)
    raw = p.get("points")
    if not isinstance(raw, list) or len(raw) != counts[0] * counts[1] * counts[2]:
        raise RuntimeError("The cage needs %d points, ordered with the third direction running fastest." % (counts[0] * counts[1] * counts[2]))
    net = np.array([vec(q, "A cage point") for q in raw]).reshape(counts[0], counts[1], counts[2], 3)
    inv = np.linalg.inv(sides.T)
    shift = float(np.linalg.norm(net - rest, axis=-1).max())

    def mapping(x):
        out = np.empty_like(x)
        for i in range(0, len(x), CHUNK * 8):
            part = x[i:i + CHUNK * 8]
            c = (part - o) @ inv.T
            cc = np.clip(c, 0.0, 1.0)
            mats = [basis(cc[:, k], knots[k], degrees[k], True) for k in range(3)]
            here = np.einsum("mi,mj,mk,ijkc->mc", mats[0][0], mats[1][0], mats[2][0], net, optimize=True)
            over = c - cc
            if np.any(over != 0.0):
                here = here + np.einsum("mi,mj,mk,ijkc->mc", mats[0][1], mats[1][0], mats[2][0], net, optimize=True) * over[:, :1]
                here = here + np.einsum("mi,mj,mk,ijkc->mc", mats[0][0], mats[1][1], mats[2][0], net, optimize=True) * over[:, 1:2]
                here = here + np.einsum("mi,mj,mk,ijkc->mc", mats[0][0], mats[1][0], mats[2][1], net, optimize=True) * over[:, 2:]
            out[i:i + CHUNK * 8] = here
        return out

    return deform(p, "cage", mapping, {"counts": counts, "degrees": degrees, "cage_shift": shift})


METHODS = {"deform_bend": bend, "deform_flow": flow, "deform_flow_surface": flow_surface, "deform_cage": cage, "deform_cage_rest": cage_rest}
