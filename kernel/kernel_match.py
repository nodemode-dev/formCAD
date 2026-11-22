import math

import numpy as np

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_NurbsConvert
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
from OCP.BRepTools import BRepTools
from OCP.Geom import Geom_BSplineSurface
from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
from OCP.GeomAbs import GeomAbs_C2, GeomAbs_G1, GeomAbs_G2, GeomAbs_C0
from OCP.LocalAnalysis import LocalAnalysis_SurfaceContinuity
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.collections import Array1_double, Array1_int, Array2_double, Array2_gp_Pnt
from OCP.gp import gp_Pnt, gp_Vec

import kernel_store as store
from kernel_surf import TopoDS, edge_of_shape, face_of, finish, kind_edges, tolerances

MAX_SAMPLES = 2000


def vec(v):
    return np.array([v.X(), v.Y(), v.Z()], dtype=float)


def unit(v):
    n = np.linalg.norm(v)
    if n < 1e-300:
        raise RuntimeError("A direction has zero length.")
    return v / n


def basis_matrix(U, p, params, deriv=0):
    n = len(U) - p - 1
    out = np.zeros((len(params), n))
    for r, u in enumerate(params):
        u = min(max(float(u), U[p]), U[n])
        if u >= U[n]:
            span = n - 1
            while span > p and U[span] >= U[n]:
                span -= 1
        else:
            lo, hi = p, n
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if u < U[mid]:
                    hi = mid
                else:
                    lo = mid
            span = lo
        ndu = np.zeros((p + 1, p + 1))
        left = np.zeros(p + 1)
        right = np.zeros(p + 1)
        ndu[0, 0] = 1.0
        for j in range(1, p + 1):
            left[j] = u - U[span + 1 - j]
            right[j] = U[span + j] - u
            saved = 0.0
            for k in range(j):
                ndu[j, k] = right[k + 1] + left[j - k]
                temp = ndu[k, j - 1] / ndu[j, k]
                ndu[k, j] = saved + right[k + 1] * temp
                saved = left[j - k] * temp
            ndu[j, j] = saved
        if deriv == 0:
            out[r, span - p : span + 1] = ndu[:, p]
            continue
        ders = np.zeros((deriv + 1, p + 1))
        a = np.zeros((2, p + 1))
        for j in range(p + 1):
            ders[0, j] = ndu[j, p]
        for j in range(p + 1):
            s1, s2 = 0, 1
            a[0, 0] = 1.0
            for k in range(1, deriv + 1):
                d = 0.0
                rk = j - k
                pk = p - k
                if j >= k:
                    a[s2, 0] = a[s1, 0] / ndu[pk + 1, rk]
                    d = a[s2, 0] * ndu[rk, pk]
                j1 = 1 if rk >= -1 else -rk
                j2 = k - 1 if j - 1 <= pk else p - j
                for jj in range(j1, j2 + 1):
                    a[s2, jj] = (a[s1, jj] - a[s1, jj - 1]) / ndu[pk + 1, rk + jj]
                    d += a[s2, jj] * ndu[rk + jj, pk]
                if j <= pk:
                    a[s2, k] = -a[s1, k - 1] / ndu[pk + 1, j]
                    d += a[s2, k] * ndu[j, pk]
                ders[k, j] = d
                s1, s2 = s2, s1
        factor = float(p)
        for k in range(1, deriv + 1):
            ders[k, :] *= factor
            factor *= p - k
        out[r, span - p : span + 1] = ders[deriv, :]
    return out


def greville(U, p):
    n = len(U) - p - 1
    return np.array([sum(U[i + 1 : i + p + 1]) / p for i in range(n)])


def clamped_uniform(n, p, spans):
    inner = [k / spans for k in range(1, spans)]
    return np.array([0.0] * (p + 1) + inner + [1.0] * (p + 1))


def distinct(U):
    ks, ms = [], []
    for k in U:
        if ks and abs(k - ks[-1]) < 1e-13:
            ms[-1] += 1
        else:
            ks.append(float(k))
            ms.append(1)
    return ks, ms


def surface_from_arrays(P, U, V, pu, pv, W=None):
    nu, nv, _ = P.shape
    arr = Array2_gp_Pnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            arr.SetValue(i + 1, j + 1, gp_Pnt(float(P[i, j, 0]), float(P[i, j, 1]), float(P[i, j, 2])))
    uk, um = distinct(U)
    vk, vm = distinct(V)
    ua, ub = Array1_double(1, len(uk)), Array1_int(1, len(um))
    va, vb = Array1_double(1, len(vk)), Array1_int(1, len(vm))
    for i, (k, m) in enumerate(zip(uk, um)):
        ua.SetValue(i + 1, k)
        ub.SetValue(i + 1, m)
    for i, (k, m) in enumerate(zip(vk, vm)):
        va.SetValue(i + 1, k)
        vb.SetValue(i + 1, m)
    if W is not None:
        wa = Array2_double(1, nu, 1, nv)
        for i in range(nu):
            for j in range(nv):
                wa.SetValue(i + 1, j + 1, float(W[i, j]))
        return Geom_BSplineSurface(arr, wa, ua, va, ub, vb, pu, pv)
    return Geom_BSplineSurface(arr, ua, va, ub, vb, pu, pv)


def weights_of(surf):
    nu, nv = surf.NbUPoles(), surf.NbVPoles()
    W = np.ones((nu, nv))
    if surf.IsURational() or surf.IsVRational():
        for i in range(nu):
            for j in range(nv):
                W[i, j] = surf.Weight(i + 1, j + 1)
    return W


def bezier_blossom(poles, a, b, args):
    work = np.array(poles, dtype=float)
    span = b - a
    for t in args:
        lam = (t - a) / span
        work = (1.0 - lam) * work[:-1] + lam * work[1:]
    return work[0]


def extension_poles(rows, a, b, new_start):
    p = len(rows) - 1
    out = []
    for j in range(p + 1):
        out.append(bezier_blossom(rows, a, b, [new_start] * (p - j) + [b] * j))
    return np.array(out)


def extend(p):
    tol, ang = tolerances(p)
    face = face_of(p["face"])
    edge = edge_of_shape(p["edge"])
    length = float(p["length"])
    if not math.isfinite(length) or length <= tol:
        raise RuntimeError("The extension length must be larger than the tolerance.")
    cont = str(p.get("continuity", "g2")).lower()
    nc = BRepBuilderAPI_NurbsConvert(face, True)
    conv = TopoDS.Face_s(kind_edges(nc.Shape(), TopAbs_FACE)[0])
    raw = BRep_Tool.Surface_s(conv)
    if not isinstance(raw, Geom_BSplineSurface):
        raise RuntimeError("The surface could not be converted to a B-spline surface.")
    along_u, at_max = locate_edge(raw, edge, max(tol, 1e-4))
    across_u = not along_u
    if (raw.IsUPeriodic() if across_u else raw.IsVPeriodic()):
        raise RuntimeError("This surface is periodic in the direction across that edge, so it cannot be extended there; rebuild it as a non-periodic surface first.")
    sf = Geom_BSplineSurface(raw)
    if sf.IsUPeriodic():
        sf.SetUNotPeriodic()
    if sf.IsVPeriodic():
        sf.SetVNotPeriodic()
    pk = sf.UDegree() if across_u else sf.VDegree()
    ks = list(sf.UKnots() if across_u else sf.VKnots())
    knot_pos = len(ks) - 1 if at_max else 2
    old_mult = 0
    if len(ks) > 2:
        inner = ks[-2] if at_max else ks[1]
        old_mult = sf.UMultiplicity(knot_pos) if across_u else sf.VMultiplicity(knot_pos)
        if across_u:
            sf.InsertUKnot(inner, pk, 0.0, False)
        else:
            sf.InsertVKnot(inner, pk, 0.0, False)
    P, U, V, pu, pv = arrays_from_surface(sf)
    W = weights_of(sf)
    H = np.concatenate([P * W[:, :, None], W[:, :, None]], axis=2)
    arr, UU, VV, du, dv = canonical(H, U, V, pu, pv, along_u, at_max)
    anchor = VV[0] + VV[-1]
    a = VV[dv]
    b = VV[dv + 1] if VV[dv + 1] > a else VV[-1]
    rows = list(range(dv + 1))
    cols = basis_matrix(UU, du, np.linspace(UU[du], UU[-du - 1], 9))

    def build(delta):
        new = arr.copy()
        for i in range(arr.shape[0]):
            new[i, rows, :] = extension_poles(arr[i, rows, :], a, b, a - delta)
        vv = VV.copy()
        vv[: dv + 1] = a - delta
        return new, vv

    def reach(delta):
        new, _vv = build(delta)
        pn = cols @ new[:, 0, :]
        po = cols @ arr[:, 0, :]
        d = np.linalg.norm(pn[:, :3] / pn[:, 3:4] - po[:, :3] / po[:, 3:4], axis=1)
        return float(np.mean(d))

    delta = (b - a) * 0.1
    for _ in range(60):
        got = reach(delta)
        if got <= 0:
            break
        if abs(got - length) <= tol * 0.1:
            break
        delta *= length / got
    new, vv = build(delta)
    achieved = reach(delta)
    Hn = uncanonical(new, UU, vv, du, dv, along_u, at_max, U, V)
    Wn = Hn[:, :, 3]
    Pn = Hn[:, :, :3] / Wn[:, :, None]
    across_knots = anchor - vv[::-1] if at_max else vv
    if along_u:
        new_u, new_v = U, across_knots
    else:
        new_u, new_v = across_knots, V
    rational = bool(np.max(np.abs(Wn - 1.0)) > 1e-12)
    out = surface_from_arrays(Pn, new_u, new_v, pu, pv, Wn if rational else None)
    restored = None
    if old_mult:
        count = len(list(out.UKnots() if across_u else out.VKnots()))
        which = count - 1 if at_max else 2
        try:
            restored = bool(out.RemoveUKnot(which, old_mult, tol * 0.01) if across_u else out.RemoveVKnot(which, old_mult, tol * 0.01))
        except Exception:
            restored = False
    new_face = BRepBuilderAPI_MakeFace(out, tol).Face()
    rep = {"direction": "across_u" if across_u else "across_v", "side": "end" if at_max else "start", "length": length, "achieved_length": achieved, "continuity": cont, "knot_restored": restored, "contact": "the end span is continued as the same polynomial, so every derivative continues across the old edge", "poles": [int(out.NbUPoles()), int(out.NbVPoles())]}
    return finish("extend", new_face, tol, ang, rep)


def arrays_from_surface(surf):
    nu, nv = surf.NbUPoles(), surf.NbVPoles()
    poles = surf.Poles()
    P = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            q = poles.Value(i + 1, j + 1)
            P[i, j] = (q.X(), q.Y(), q.Z())
    U = np.array(list(surf.UKnotSequence()), dtype=float)
    V = np.array(list(surf.VKnotSequence()), dtype=float)
    return P, U, V, surf.UDegree(), surf.VDegree()


def d2(surf, u, v):
    P, a, b, c, d, e = gp_Pnt(), gp_Vec(), gp_Vec(), gp_Vec(), gp_Vec(), gp_Vec()
    surf.D2(u, v, P, a, b, c, d, e)
    return np.array([P.X(), P.Y(), P.Z()]), vec(a), vec(b), vec(c), vec(d), vec(e)


def normal_curvature(Su, Sv, Suu, Svv, Suv, n, d):
    E, F, G = Su @ Su, Su @ Sv, Sv @ Sv
    det = E * G - F * F
    if abs(det) < 1e-300:
        raise RuntimeError("degenerate")
    a = (G * (d @ Su) - F * (d @ Sv)) / det
    b = (E * (d @ Sv) - F * (d @ Su)) / det
    II = a * a * (Suu @ n) + 2 * a * b * (Suv @ n) + b * b * (Svv @ n)
    I = a * a * E + 2 * a * b * F + b * b * G
    return II / I


def d3(surf, u, v):
    P = gp_Pnt()
    g = [gp_Vec() for _ in range(9)]
    surf.D3(u, v, P, *g)
    return [vec(x) for x in g]


def tangent_coords(Su, Sv, d):
    E, F, G = Su @ Su, Su @ Sv, Sv @ Sv
    det = E * G - F * F
    if abs(det) < 1e-300:
        raise RuntimeError("degenerate")
    return (G * (d @ Su) - F * (d @ Sv)) / det, (E * (d @ Sv) - F * (d @ Su)) / det


def curvature_rate(ders, n, d):
    Su, Sv, Suu, Svv, Suv, Suuu, Svvv, Suuv, Suvv = ders
    a, b = tangent_coords(Su, Sv, d)
    second = a * a * Suu + 2 * a * b * Suv + b * b * Svv
    a2, b2 = tangent_coords(Su, Sv, -(second - (second @ n) * n))
    third = a * a * a * Suuu + 3 * a * a * b * Suuv + 3 * a * b * b * Suvv + b * b * b * Svvv
    mixed = a * a2 * Suu + (a * b2 + b * a2) * Suv + b * b2 * Svv
    return float((third + 3.0 * mixed) @ n)


def cross_rates(surf, uv, n, across, along):
    ders = d3(surf, uv[0], uv[1])
    x = unit(across - (across @ n) * n)
    y = unit(along - (along @ n) * n - ((along - (along @ n) * n) @ x) * x)
    r = math.sqrt(0.5)
    fxxx = curvature_rate(ders, n, x)
    fyyy = curvature_rate(ders, n, y)
    plus = curvature_rate(ders, n, r * (x + y))
    minus = curvature_rate(ders, n, r * (x - y))
    root2 = math.sqrt(2.0)
    fxyy = (root2 * (plus + minus) - fxxx) / 3.0
    fxxy = (root2 * (plus - minus) - fyyy) / 3.0
    return np.array([fxxx, fxxy, fxyy])


class Side:
    def __init__(self, face, edge, tol):
        self.face = face
        self.edge = edge
        self.tol = tol
        self.surf = BRep_Tool.Surface_s(face)
        self.ad3 = BRepAdaptor_Curve(edge)
        try:
            self.c2 = BRepAdaptor_Curve2d(edge, face)
        except Exception:
            self.c2 = None
        self.sas = ShapeAnalysis_Surface(self.surf)
        a, b = self.ad3.FirstParameter(), self.ad3.LastParameter()
        self.t0, self.t1 = a, b
        geom = BRep_Tool.Curve_s(edge, a, b)
        self.geom = geom

    def point(self, t):
        q = self.ad3.Value(t)
        return np.array([q.X(), q.Y(), q.Z()])

    def surface_point(self, t):
        uv = self.uv(t)
        q = self.surf.Value(uv[0], uv[1])
        return np.array([q.X(), q.Y(), q.Z()])

    def tangent(self, t):
        q, v = gp_Pnt(), gp_Vec()
        self.ad3.D1(t, q, v)
        return vec(v)

    def uv(self, t, near=None):
        if self.c2 is not None:
            q = self.c2.Value(t)
            return q.X(), q.Y()
        p = self.ad3.Value(t) if near is None else gp_Pnt(*near)
        r = self.sas.ValueOfUV(p, self.tol)
        return r.X(), r.Y()

    def uv_of_point(self, pt):
        q = gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2]))
        try:
            proj = GeomAPI_ProjectPointOnSurf(q, self.surf)
            if proj.NbPoints() > 0:
                return proj.LowerDistanceParameters()
        except Exception:
            pass
        r = self.sas.ValueOfUV(q, self.tol)
        return r.X(), r.Y()

    def param_near(self, pt):
        proj = GeomAPI_ProjectPointOnCurve(gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2])), self.geom, self.t0, self.t1)
        if proj.NbPoints() == 0:
            return None
        return proj.LowerDistanceParameter()

    def frame(self, uv):
        P, Su, Sv, Suu, Svv, Suv = d2(self.surf, uv[0], uv[1])
        n = unit(np.cross(Su, Sv))
        return P, Su, Sv, Suu, Svv, Suv, n


def sample_params(side, count):
    n_int = 1
    try:
        n_int = max(1, side.ad3.NbIntervals(GeomAbs_C2))
    except Exception:
        pass
    k = min(MAX_SAMPLES, max(count, 8 * n_int + 1))
    return [side.t0 + (side.t1 - side.t0) * i / (k - 1) for i in range(k)]


def seam_report(sa, sb, tol, ang, samples=41, curv_rel=0.01):
    ts = sample_params(sa, samples)
    rows = []
    skipped = 0
    la_worst = {"c0": 0.0, "g1": 0.0, "g2": 0.0, "status": "none"}
    length = 0.0
    prev = None
    flip_votes = 0
    kmax = 0.0
    rmax = 0.0
    for t in ts:
        try:
            pa = sa.point(t)
            if prev is not None:
                length += float(np.linalg.norm(pa - prev))
            prev = pa
            uva = sa.uv(t)
            if sb.c2 is not None and sb.edge.IsSame(sa.edge):
                uvb = sb.uv(t)
            else:
                uvb = sb.uv_of_point(sa.surface_point(t))
            Pa, Sua, Sva, Suua, Svva, Suva, na = sa.frame(uva)
            Pb, Sub, Svb, Suub, Svvb, Suvb, nb = sb.frame(uvb)
            gap = float(np.linalg.norm(Pa - Pb))
            dot = float(na @ nb)
            sign = 1.0 if dot >= 0 else -1.0
            nb_al = nb * sign
            angle = math.acos(max(-1.0, min(1.0, abs(dot))))
            tv = unit(sa.tangent(t))
            bv = unit(np.cross(na, tv))
            tb_vec = tv - (tv @ nb_al) * nb_al
            bb_vec = bv - (bv @ nb_al) * nb_al
            ka_t = normal_curvature(Sua, Sva, Suua, Svva, Suva, na, tv)
            ka_b = normal_curvature(Sua, Sva, Suua, Svva, Suva, na, bv)
            kb_t = sign * normal_curvature(Sub, Svb, Suub, Svvb, Suvb, nb, unit(tb_vec))
            kb_b = sign * normal_curvature(Sub, Svb, Suub, Svvb, Suvb, nb, unit(bb_vec))
            curv = max(abs(ka_t - kb_t), abs(ka_b - kb_b))
            kmax = max(kmax, abs(ka_t), abs(ka_b), abs(kb_t), abs(kb_b))
            rate = None
            try:
                ra = cross_rates(sa.surf, uva, na, bv, tv)
                rb = cross_rates(sb.surf, uvb, nb_al, bv, tv)
                if np.all(np.isfinite(ra)) and np.all(np.isfinite(rb)):
                    rate = float(np.max(np.abs(ra - rb)))
                    rmax = max(rmax, float(np.max(np.abs(ra))), float(np.max(np.abs(rb))))
            except Exception:
                rate = None
            try:
                la = LocalAnalysis_SurfaceContinuity(sa.surf, uva[0], uva[1], sb.surf, uvb[0], uvb[1], GeomAbs_G2, 1e-9, tol, ang, ang, ang, curv_rel, 1e9)
                la_worst["c0"] = max(la_worst["c0"], la.C0Value())
                la_worst["g1"] = max(la_worst["g1"], la.G1Angle() if la.IsC0() or True else 0.0)
                la_worst["g2"] = max(la_worst["g2"], la.G2CurvatureGap())
            except Exception:
                pass
            rows.append({"t": t, "p": [float(x) for x in pa], "gap": gap, "angle": angle, "curv": curv, "rate": rate, "na": [float(x) for x in na], "nb": [float(x) for x in nb_al], "flip": bool(dot < 0), "ka": [float(ka_t), float(ka_b)], "kb": [float(kb_t), float(kb_b)]})
            if dot < 0:
                flip_votes += 1
        except RuntimeError:
            skipped += 1
        except Exception:
            skipped += 1
    if not rows:
        raise RuntimeError("The seam could not be evaluated: no sample point had a defined tangent plane on both surfaces.")
    ktol = max(curv_rel * kmax, ang / max(length, 1e-9))
    worst_gap = max(rows, key=lambda r: r["gap"])
    worst_ang = max(rows, key=lambda r: r["angle"])
    worst_cur = max(rows, key=lambda r: r["curv"])
    g0 = bool(worst_gap["gap"] <= tol)
    g1 = bool(g0 and worst_ang["angle"] <= ang)
    g2 = bool(g1 and worst_cur["curv"] <= ktol)
    span = max(length, 1e-9)
    rtol = max(curv_rel * max(rmax, kmax * kmax), ang / (span * span))
    rated = [r for r in rows if r["rate"] is not None]
    worst_rate = max(rated, key=lambda r: r["rate"]) if rated else None
    g3 = bool(g2 and worst_rate["rate"] <= rtol) if worst_rate else None
    level = "G3" if g3 else "G2" if g2 else "G1" if g1 else "G0" if g0 else "none"
    step = max(1, len(rows) // 64)
    hair = [{"p": r["p"], "na": r["na"], "nb": r["nb"], "gap": r["gap"], "angle": r["angle"], "curv": r["curv"], "rate": r["rate"]} for r in rows[::step]]
    return {
        "level": level,
        "g0": g0,
        "g1": g1,
        "g2": g2,
        "g3": g3,
        "g3_note": "largest gap in the rate of change of normal curvature across the seam, per mm of travel across it" if worst_rate else "not measured; the third derivatives could not be evaluated at any sample",
        "max_curvature_rate_gap": worst_rate["rate"] if worst_rate else None,
        "max_curvature_rate_at": worst_rate["p"] if worst_rate else None,
        "curvature_rate_samples": len(rated),
        "max_gap": worst_gap["gap"],
        "max_gap_at": worst_gap["p"],
        "max_angle": worst_ang["angle"],
        "max_angle_deg": math.degrees(worst_ang["angle"]),
        "max_angle_at": worst_ang["p"],
        "max_curvature_gap": worst_cur["curv"],
        "max_curvature_at": worst_cur["p"],
        "tolerance": {"length": tol, "angle": ang, "curvature": ktol, "curvature_relative": curv_rel, "curvature_rate": rtol},
        "samples": len(rows),
        "skipped": skipped,
        "length": length,
        "flipped_normals": flip_votes > len(rows) / 2,
        "local_analysis": {"max_c0": la_worst["c0"], "max_g1_angle": la_worst["g1"], "max_g2_curvature_gap": la_worst["g2"]},
        "hair": hair,
    }


def resolve_side(spec, tol):
    face = face_of(spec["face"]) if "face" in spec else None
    edge = edge_of_shape(spec["edge"])
    if face is None:
        raise RuntimeError("A seam side needs a face.")
    return Side(face, edge, tol)


def edge_offset(sa, sb):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    worst = 0.0
    for k in (0.0, 0.5, 1.0):
        q = sa.point(sa.t0 + (sa.t1 - sa.t0) * k)
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(float(q[0]), float(q[1]), float(q[2]))).Vertex()
        d = BRepExtrema_DistShapeShape(v, sb.edge)
        if d.IsDone():
            worst = max(worst, float(d.Value()))
    return worst


def continuity(p):
    tol, ang = tolerances(p)
    sa = resolve_side(p["a"], tol)
    sb = resolve_side(p["b"], tol)
    rep = seam_report(sa, sb, tol, ang, int(p.get("samples", 41)), float(p.get("curvature_relative", 0.01)))
    rep["op"] = "continuity"
    rep["edge_offset"] = edge_offset(sa, sb)
    rep["tol"] = tol
    rep["angtol"] = ang
    return {"report": rep}


def nearest_edge_of(face, pt):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex

    v = BRepBuilderAPI_MakeVertex(gp_Pnt(float(pt[0]), float(pt[1]), float(pt[2]))).Vertex()
    best = None
    for e in kind_edges(face, TopAbs_EDGE):
        d = BRepExtrema_DistShapeShape(v, e)
        if d.IsDone() and (best is None or d.Value() < best[0]):
            best = (d.Value(), TopoDS.Edge_s(e))
    return best[1]


def edge_samples(side, count):
    return [side.t0 + (side.t1 - side.t0) * i / (count - 1) for i in range(count)]


def frame_at(side, pt, toward):
    uv = side.uv_of_point(pt)
    P, Su, Sv, Suu, Svv, Suv, n = side.frame(uv)
    t = side.param_near(pt)
    tv = unit(side.tangent(t))
    b = unit(np.cross(n, tv))
    if b @ toward < 0:
        b = -b
    kappa = normal_curvature(Su, Sv, Suu, Svv, Suv, n, b)
    return n, b, kappa, tv


def fit_rows(rows, params, spans, deg=3):
    n = spans + deg
    U = clamped_uniform(n, deg, spans)
    A = basis_matrix(U, deg, params)
    coef = []
    for r in rows:
        sol, *_ = np.linalg.lstsq(A, r, rcond=None)
        coef.append(sol)
    return U, coef


def hermite_blend(sa, sb, cont_a, cont_b, infl_a, infl_b, flip, tol, samples=48):
    pa0, pa1 = sa.point(sa.t0), sa.point(sa.t1)
    pb0, pb1 = sb.point(sb.t0), sb.point(sb.t1)
    straight = np.linalg.norm(pa0 - pb0) + np.linalg.norm(pa1 - pb1)
    crossed = np.linalg.norm(pa0 - pb1) + np.linalg.norm(pa1 - pb0)
    reverse_b = crossed < straight
    if flip:
        reverse_b = not reverse_b
    best = None
    for spans in (6, 12, 24, 48):
        K = max(samples, 6 * (spans + 3))
        ss = np.linspace(0.0, 1.0, K)
        rowsets = [[] for _ in range(6)]
        for s in ss:
            ta = sa.t0 + (sa.t1 - sa.t0) * s
            tb = (sb.t1 + (sb.t0 - sb.t1) * s) if reverse_b else (sb.t0 + (sb.t1 - sb.t0) * s)
            a, b = sa.point(ta), sb.point(tb)
            D = float(np.linalg.norm(b - a))
            if D < 1e-9:
                raise RuntimeError("The two edges touch each other; there is nothing to blend there.")
            na, ba, ka, _ = frame_at(sa, a, b - a)
            nb, bb, kb, _ = frame_at(sb, b, a - b)
            if cont_a == 0:
                w0 = (b - a)
                v0 = np.zeros(3)
            else:
                w0 = infl_a * D * ba
                v0 = (infl_a * D) ** 2 * ka * na if cont_a >= 2 else np.zeros(3)
            if cont_b == 0:
                w1 = (b - a)
                v1 = np.zeros(3)
            else:
                w1 = -infl_b * D * bb
                v1 = (infl_b * D) ** 2 * kb * nb if cont_b >= 2 else np.zeros(3)
            P1 = a + w0 / 5.0
            P2 = a + 2.0 * w0 / 5.0 + v0 / 20.0
            P4 = b - w1 / 5.0
            P3 = b - 2.0 * w1 / 5.0 + v1 / 20.0
            for j, row in enumerate((a, P1, P2, P3, P4, b)):
                rowsets[j].append(row)
        U, coef = fit_rows([np.array(r) for r in rowsets], ss, spans)
        A = basis_matrix(U, 3, ss)
        errs = [float(np.max(np.linalg.norm(A @ coef[j] - np.array(rowsets[j]), axis=1))) for j in range(6)]
        err = max(errs)
        best = (spans, U, coef, err)
        if err <= tol * 0.01:
            break
    spans, U, coef, err = best
    n = len(coef[0])
    P = np.zeros((n, 6, 3))
    for j in range(6):
        P[:, j, :] = coef[j]
    V = np.array([0.0] * 6 + [1.0] * 6)
    return surface_from_arrays(P, U, V, 3, 5), {"spans": spans, "edge_fit_error": err, "edge_b_reversed": bool(reverse_b)}


def filling_blend(sa, sb, cont_a, cont_b, tol, ang):
    mk = BRepOffsetAPI_MakeFilling(3, 20, 3, False, tol / 10.0, tol, ang, 0.1, 8, 9)
    pa0, pa1 = sa.point(sa.t0), sa.point(sa.t1)
    pb0, pb1 = sb.point(sb.t0), sb.point(sb.t1)
    straight = np.linalg.norm(pa0 - pb0) + np.linalg.norm(pa1 - pb1)
    crossed = np.linalg.norm(pa0 - pb1) + np.linalg.norm(pa1 - pb0)
    ends = [(pa0, pb1 if crossed < straight else pb0), (pa1, pb0 if crossed < straight else pb1)]
    orders = {0: GeomAbs_C0, 1: GeomAbs_G1, 2: GeomAbs_G2}
    mk.Add(sa.edge, sa.face, orders[cont_a], True)
    mk.Add(sb.edge, sb.face, orders[cont_b], True)
    for a, b in ends:
        mk.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*[float(x) for x in a]), gp_Pnt(*[float(x) for x in b])).Edge(), GeomAbs_C0, True)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("The fill did not converge.")
    return mk.Shape(), {"g0_error": mk.G0Error(), "g1_error": mk.G1Error(), "g2_error": mk.G2Error()}


def blend(p):
    tol, ang = tolerances(p)
    sa = resolve_side(p["a"], tol)
    sb = resolve_side(p["b"], tol)
    ca = int(p.get("continuity_a", p.get("continuity", 2)))
    cb = int(p.get("continuity_b", p.get("continuity", 2)))
    if ca not in (0, 1, 2) or cb not in (0, 1, 2):
        raise RuntimeError("Continuity is 0, 1 or 2 at each end.")
    method = str(p.get("method", "auto")).lower()
    infl_a = float(p.get("influence_a", p.get("influence", 0.5)))
    infl_b = float(p.get("influence_b", p.get("influence", 0.5)))
    if infl_a <= 0 or infl_b <= 0:
        raise RuntimeError("The influence must be positive.")
    curv_rel = float(p.get("curvature_relative", 0.01))
    candidates = []
    report = {"requested": [ca, cb], "influence": [infl_a, infl_b]}
    if method in ("auto", "filling"):
        fa, fb = ca, cb
        while True:
            try:
                shape, errs = filling_blend(sa, sb, fa, fb, tol, ang)
                face = TopoDS.Face_s(kind_edges(shape, TopAbs_FACE)[0])
                errs["orders"] = [fa, fb]
                candidates.append(("filling", face, errs))
                break
            except Exception as err:
                report.setdefault("filling_failed", []).append({"orders": [fa, fb], "message": str(err)})
                if max(fa, fb) == 0:
                    if method == "filling":
                        raise RuntimeError("The filling method failed: %s" % err)
                    break
                fa, fb = min(fa, max(fa - 1, 0) if fa == max(fa, fb) else fa), min(fb, max(fb - 1, 0) if fb == max(fa, fb) else fb)
    judged = []
    for name, face, extra in candidates:
        seams = seams_of(face, sa, sb, tol, ang, curv_rel)
        judged.append((name, face, extra, seams))
    need = min(ca, cb)

    def good(item):
        s0, s1 = item[3]
        return s0["level"][-1:] >= str(ca)[-1:] and s1["level"][-1:] >= str(cb)[-1:] and s0["level"] != "none" and s1["level"] != "none"

    chosen = None
    for item in judged:
        if good(item) or method == "filling":
            chosen = item
            break
    if chosen is None:
        surf, extra = hermite_blend(sa, sb, ca, cb, infl_a, infl_b, bool(p.get("flip", False)), tol)
        face = BRepBuilderAPI_MakeFace(surf, tol).Face()
        seams = seams_of(face, sa, sb, tol, ang, curv_rel)
        chosen = ("hermite", face, extra, seams)
        if judged:
            report["filling_attempt"] = {"errors": judged[0][2], "seams": [{k: s[k] for k in ("level", "max_gap", "max_angle", "max_curvature_gap")} for s in judged[0][3]]}
    name, face, extra, seams = chosen
    report["method"] = name
    report["construction"] = extra
    report["seams"] = {"a": seams[0], "b": seams[1]}
    report["achieved"] = [seams[0]["level"], seams[1]["level"]]
    return finish("blend", face, tol, ang, report)


def seams_of(face, sa, sb, tol, ang, curv_rel):
    out = []
    for side in (sa, sb):
        mid = side.point((side.t0 + side.t1) / 2.0)
        edge = nearest_edge_of(face, mid)
        f_side = Side(face, edge, tol)
        out.append(seam_report(side, f_side, tol, ang, 41, curv_rel))
    return out


def canonical(P, U, V, pu, pv, along_u, at_max):
    if along_u:
        pass
    arr = P
    UU, VV = U, V
    du, dv = pu, pv
    if not along_u:
        arr = np.swapaxes(P, 0, 1)
        UU, VV = V, U
        du, dv = pv, pu
    flipped = False
    if at_max:
        arr = arr[:, ::-1, :]
        VV = (VV[-1] + VV[0]) - VV[::-1]
        flipped = True
    return arr, UU, VV, du, dv


def uncanonical(arr, UU, VV, du, dv, along_u, at_max, orig_U, orig_V):
    if at_max:
        arr = arr[:, ::-1, :]
    if not along_u:
        return np.swapaxes(arr, 0, 1)
    return arr


def locate_edge(surf, edge, tol):
    sas = ShapeAnalysis_Surface(surf)
    ad = BRepAdaptor_Curve(edge)
    mid = ad.Value((ad.FirstParameter() + ad.LastParameter()) / 2.0)
    uv = sas.ValueOfUV(mid, tol)
    u0, u1, v0, v1 = surf.Bounds()
    cand = [(True, False, abs(uv.Y() - v0) / max(v1 - v0, 1e-12)), (True, True, abs(uv.Y() - v1) / max(v1 - v0, 1e-12)), (False, False, abs(uv.X() - u0) / max(u1 - u0, 1e-12)), (False, True, abs(uv.X() - u1) / max(u1 - u0, 1e-12))]
    best = min(cand, key=lambda c: c[2])
    return best[0], best[1]


def refine_for_match(surf, along_u, continuity_order):
    sf = Geom_BSplineSurface(surf)
    if continuity_order >= 2:
        pv = sf.VDegree() if along_u else sf.UDegree()
        want = 3
        if pv < want:
            if along_u:
                sf.IncreaseDegree(sf.UDegree(), want)
            else:
                sf.IncreaseDegree(want, sf.VDegree())
        count = sf.NbVPoles() if along_u else sf.NbUPoles()
        guard = 0
        while count < 7 and guard < 8:
            guard += 1
            ks = list(sf.VKnots() if along_u else sf.UKnots())
            spans = [(ks[i + 1] - ks[i], i) for i in range(len(ks) - 1)]
            width, i = max(spans)
            mid = (ks[i] + ks[i + 1]) / 2.0
            if along_u:
                sf.InsertVKnot(mid, 1, 0.0)
            else:
                sf.InsertUKnot(mid, 1, 0.0)
            count = sf.NbVPoles() if along_u else sf.NbUPoles()
    return sf


def unit_weights(surf):
    first = surf.Weight(1, 1)
    for i in range(1, surf.NbUPoles() + 1):
        for j in range(1, surf.NbVPoles() + 1):
            if abs(surf.Weight(i, j) / first - 1.0) > 1e-9:
                return False
    return True


def natural_face(face, surf, tol):
    uu0, uu1, vv0, vv1 = BRepTools.UVBounds_s(face)
    u0, u1, v0, v1 = surf.Bounds()
    du, dv = max(u1 - u0, 1e-12), max(v1 - v0, 1e-12)
    return abs(uu0 - u0) / du < 1e-6 and abs(uu1 - u1) / du < 1e-6 and abs(vv0 - v0) / dv < 1e-6 and abs(vv1 - v1) / dv < 1e-6


def match(p):
    tol, ang = tolerances(p)
    cont = int(p.get("continuity", 2))
    if cont not in (0, 1, 2):
        raise RuntimeError("Continuity is 0, 1 or 2.")
    moving = resolve_side(p["moving"], tol)
    target = resolve_side(p["target"], tol)
    nc = BRepBuilderAPI_NurbsConvert(moving.face, True)
    mface = TopoDS.Face_s(kind_edges(nc.Shape(), TopAbs_FACE)[0])
    raw = BRep_Tool.Surface_s(mface)
    if not isinstance(raw, Geom_BSplineSurface):
        raise RuntimeError("The moving surface could not be converted to a B-spline surface.")
    if (raw.IsURational() or raw.IsVRational()) and not unit_weights(raw):
        raise RuntimeError("Match works on non-rational surfaces; rebuild the moving surface first.")
    if raw.IsUPeriodic() or raw.IsVPeriodic():
        raise RuntimeError("Match does not work on a surface that is periodic in either direction; rebuild it as non-periodic first.")
    if not natural_face(moving.face, BRep_Tool.Surface_s(moving.face), tol) and not natural_face(mface, raw, tol):
        raise RuntimeError("Match works on an untrimmed surface; the moving surface is trimmed, so untrim or rebuild it first.")
    along_u, at_max = locate_edge(raw, moving.edge, max(tol, 1e-4))
    before = Geom_BSplineSurface(raw)
    sf = refine_for_match(raw, along_u, cont)
    refine_hits = 0
    best = None
    for attempt in range(5):
        P, U, V, pu, pv = arrays_from_surface(sf)
        arr, UU, VV, du, dv = canonical(P, U, V, pu, pv, along_u, at_max)
        if cont >= 1 and dv < 1:
            raise RuntimeError("The surface has degree 0 across the edge.")
        if cont >= 2 and dv < 2:
            raise RuntimeError("Matching curvature needs a surface of degree 2 or more across the edge.")
        n = arr.shape[0]
        g = greville(UU, du)
        B0 = basis_matrix(UU, du, g)
        Bv1 = basis_matrix(VV, dv, [VV[dv]], 1)[0]
        Bv2 = basis_matrix(VV, dv, [VV[dv]], 2)[0] if dv >= 2 else None
        n0, n1 = Bv1[0], Bv1[1]
        row0_now = arr[:, 0, :]
        cur_pts = B0 @ row0_now
        tpts = []
        tparams = []
        frames = []
        by_closest = str(p.get("correspondence", "parameter")).lower() == "closest"
        span_u = UU[n] - UU[du]
        forward = float(np.linalg.norm(cur_pts[0] - target.point(target.t0)) + np.linalg.norm(cur_pts[-1] - target.point(target.t1))) <= float(np.linalg.norm(cur_pts[0] - target.point(target.t1)) + np.linalg.norm(cur_pts[-1] - target.point(target.t0)))
        for k in range(n):
            if by_closest:
                tparam = target.param_near(cur_pts[k])
            else:
                frac = (g[k] - UU[du]) / span_u
                tparam = target.t0 + (target.t1 - target.t0) * (frac if forward else 1.0 - frac)
            if tparam is None:
                raise RuntimeError("An edge point could not be matched on the target edge.")
            tpts.append(target.surface_point(tparam))
            tparams.append(tparam)
        tpts = np.array(tpts)
        new0 = np.linalg.solve(B0, tpts)
        arr2 = arr.copy()
        arr2[:, 0, :] = new0
        dense = np.linspace(UU[du], UU[n], 4 * n + 1)
        fitted = basis_matrix(UU, du, dense) @ new0
        edge_err = 0.0
        for q in fitted:
            uvq = target.uv_of_point(q)
            sq = target.surf.Value(uvq[0], uvq[1])
            edge_err = max(edge_err, float(np.linalg.norm(q - np.array([sq.X(), sq.Y(), sq.Z()]))))
        if cont >= 1:
            Bd1 = Bv1[0] * new0 + 0.0
            cur1 = Bv1[0] * new0 + Bv1[1] * arr2[:, 1, :]
            Sv_now = B0 @ cur1
            W = np.zeros((n, 3))
            frames = []
            for k in range(n):
                t_t = tparams[k]
                uvt = target.uv(t_t) if target.c2 is not None else target.uv_of_point(tpts[k])
                Pt, Su, Sv, Suu, Svv, Suv, nrm = target.frame(uvt)
                tv = unit(target.tangent(t_t))
                bv = unit(np.cross(nrm, tv))
                if bv @ Sv_now[k] < 0:
                    bv = -bv
                mag = float(np.linalg.norm(Sv_now[k]))
                if mag < 1e-9:
                    mag = float(np.linalg.norm(tpts[min(k + 1, n - 1)] - tpts[max(k - 1, 0)])) / 3.0 + 1e-6
                W[k] = mag * bv
                frames.append((nrm, bv, normal_curvature(Su, Sv, Suu, Svv, Suv, nrm, bv), mag))
            coef1 = np.linalg.solve(B0, W)
            arr2[:, 1, :] = new0 + coef1 / n1
            if cont >= 2:
                cur2 = Bv2[0] * arr2[:, 0, :] + Bv2[1] * arr2[:, 1, :] + Bv2[2] * arr2[:, 2, :]
                Svv_now = B0 @ cur2
                Z = np.zeros((n, 3))
                for k in range(n):
                    nrm, bv, kap, mag = frames[k]
                    tang = Svv_now[k] - (Svv_now[k] @ nrm) * nrm
                    Z[k] = tang + (mag * mag * kap) * nrm
                coef2 = np.linalg.solve(B0, Z)
                if abs(Bv2[2]) < 1e-12:
                    raise RuntimeError("The surface has too few rows near the edge for curvature matching.")
                arr2[:, 2, :] = (coef2 - Bv2[0] * arr2[:, 0, :] - Bv2[1] * arr2[:, 1, :]) / Bv2[2]
        P2 = uncanonical(arr2, UU, VV, du, dv, along_u, at_max, U, V)
        new_surf = surface_from_arrays(P2, U, V, pu, pv)
        face = BRepBuilderAPI_MakeFace(new_surf, tol).Face()
        edge = nearest_edge_of(face, moving.point((moving.t0 + moving.t1) / 2.0))
        side_new = Side(face, edge, tol)
        rep = seam_report(target, side_new, tol, ang, 41, float(p.get("curvature_relative", 0.01)))
        best = (face, rep, new_surf, attempt)
        tk = rep["tolerance"]["curvature"]
        crisp = rep["max_gap"] <= tol * 0.2 and (cont < 1 or rep["max_angle"] <= ang * 0.2) and (cont < 2 or rep["max_curvature_gap"] <= tk * 0.2)
        wanted = {0: rep["g0"], 1: rep["g1"], 2: rep["g2"]}[cont] and crisp and edge_err <= tol * 0.005
        if wanted or not p.get("refine", True):
            break
        refine_hits += 1
        if along_u:
            ks = list(sf.UKnots())
        else:
            ks = list(sf.VKnots())
        spans = [(ks[i + 1] - ks[i], i) for i in range(len(ks) - 1)]
        inserts = [(ks[i] + ks[i + 1]) / 2.0 for _w, i in spans]
        for kn in inserts:
            if along_u:
                sf.InsertUKnot(kn, 1, 0.0)
            else:
                sf.InsertVKnot(kn, 1, 0.0)
    face, rep, new_surf, attempt = best
    report = {"requested": cont, "achieved": rep["level"], "seam": rep, "refinements": refine_hits, "edge_fit_error": edge_err, "poles": [int(new_surf.NbUPoles()), int(new_surf.NbVPoles())], "side": ("u" if along_u else "v") + ("max" if at_max else "min")}
    return finish("match", face, tol, ang, report)


def edge_list(p):
    ident = str(p["id"])
    maps = store.maps_of(ident)
    m = maps["edges"]
    from OCP.TopExp import TopExp
    from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as Ancestors

    anc = Ancestors()
    TopExp.MapShapesAndAncestors_s(store.shape_of(ident), TopAbs_EDGE, TopAbs_FACE, anc)
    out = []
    for i in range(1, min(m.Extent(), 5000) + 1):
        e = TopoDS.Edge_s(m.FindKey(i))
        ad = BRepAdaptor_Curve(e)
        a, b = ad.FirstParameter(), ad.LastParameter()
        s, mid, t = ad.Value(a), ad.Value((a + b) / 2.0), ad.Value(b)
        faces = []
        if anc.Contains(e):
            for f in anc.FindFromKey(e):
                fi = maps["faces"].FindIndex(f)
                if fi > 0 and fi - 1 not in faces:
                    faces.append(fi - 1)
        out.append({"index": i - 1, "start": [s.X(), s.Y(), s.Z()], "mid": [mid.X(), mid.Y(), mid.Z()], "end": [t.X(), t.Y(), t.Z()], "faces": faces})
    return {"edges": out}


METHODS = {"surf_continuity": continuity, "surf_blend": blend, "surf_match": match, "surf_edges": edge_list, "surf_extend": extend}
