import math
import os
import struct

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform, BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.Bnd import Bnd_Box
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.Geom import Geom_Line
from OCP.GeomAPI import GeomAPI_ExtremaCurveCurve, GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
from OCP.GeomAbs import GeomAbs_C2, GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_Line, GeomAbs_Sphere
from OCP.GeomAdaptor import GeomAdaptor_Curve
from OCP.GeomLProp import GeomLProp_CLProps
from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.collections import Array1_double
from OCP.gp import gp_Dir, gp_GTrsf, gp_Lin, gp_Pnt, gp_Pnt2d

import kernel_mesh as mesh
import kernel_store as store
from kernel_ops import input_history
from kernel_surf import curve_wire, edge_pieces

DATA_MAGIC = 0x54444146
MAX_POINTS = 2_000_000
MAX_SAMPLES = 20000
NUDGES = (1e-4, 1e-3, 1e-2)
SNAP_KINDS = {"vertex": 0, "mid": 1, "centre": 2, "quadrant": 3, "end": 4, "intersection": 5, "perpendicular": 6, "nearest": 7, "surface": 8, "curve": 9}
EDGE_LIMIT = 40
_edge_cache: dict = {}


def finite_path(raw, suffix):
    return store.absolute_path(raw, (suffix,))


def face_rows(shape_id):
    maps = store.maps_of(shape_id)["faces"]
    return [TopoDS.Face(maps.FindKey(i)) for i in range(1, maps.Extent() + 1)]


def eval_face(face, tri, curvature):
    n = tri.NbNodes()
    normals = np.zeros((n, 3), dtype=np.float32)
    curv = np.full((n, 4), np.nan, dtype=np.float32) if curvature else None
    ad = BRepAdaptor_Surface(face, True)
    umin, umax, vmin, vmax = ad.FirstUParameter(), ad.LastUParameter(), ad.FirstVParameter(), ad.LastVParameter()
    uc, vc = 0.5 * (umin + umax), 0.5 * (vmin + vmax)
    reversed_face = face.Orientation() == TopAbs_REVERSED
    s = -1.0 if reversed_face else 1.0
    has_uv = tri.HasUVNodes()
    if not has_uv:
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface

        sas = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face))
    if not tri.HasNormals():
        tri.ComputeNormals()
    sl = BRepLProp_SLProps(ad, uc, vc, 2, 1e-9)
    for i in range(1, n + 1):
        if has_uv:
            uv = tri.UVNode(i)
            u, v = uv.X(), uv.Y()
        else:
            uv = sas.ValueOfUV(tri.Node(i), 1e-6)
            u, v = uv.X(), uv.Y()
        defined = False
        for k in (0.0,) + NUDGES:
            uu, vv = u + (uc - u) * k, v + (vc - v) * k
            sl.SetParameters(uu, vv)
            if sl.IsNormalDefined():
                defined = True
                if not curvature or sl.IsCurvatureDefined():
                    break
        if not defined or not sl.IsNormalDefined():
            if tri.HasNormals():
                d = tri.Normal(i)
                normals[i - 1] = (s * d.X(), s * d.Y(), s * d.Z())
            continue
        nd = sl.Normal()
        normals[i - 1] = (s * nd.X(), s * nd.Y(), s * nd.Z())
        if curvature and sl.IsCurvatureDefined():
            k_gauss = sl.GaussianCurvature()
            k_mean = -s * sl.MeanCurvature()
            k_a = -s * sl.MaxCurvature()
            k_b = -s * sl.MinCurvature()
            hi, lo = (k_a, k_b) if k_a >= k_b else (k_b, k_a)
            curv[i - 1] = (k_gauss, k_mean, hi, lo)
    return normals, curv


def an_shape_data(p):
    ident = str(p.get("id"))
    linear, angular = float(p["linear"]), float(p.get("angular", 0.3))
    curvature = bool(p.get("curvature", True))
    out = finite_path(p.get("path"), ".adat")
    ent = store.entry(ident)
    if ent.meshed != (linear, angular):
        mesh.run_mesh(ent.shape, linear, angular)
        ent.meshed = (linear, angular)
    positions, normals, curvs = [], [], []
    for face in face_rows(ident):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        pos = np.empty((tri.NbNodes(), 3), dtype=np.float32)
        for i in range(1, tri.NbNodes() + 1):
            q = tri.Node(i).Transformed(trsf)
            pos[i - 1] = (q.X(), q.Y(), q.Z())
        nr, cv = eval_face(face, tri, curvature)
        positions.append(pos)
        normals.append(nr)
        if curvature:
            curvs.append(cv)
    nv = sum(len(a) for a in positions)
    if nv > MAX_POINTS:
        raise RuntimeError("The mesh has too many vertices for analysis; raise the tolerance.")
    cols = 7 if curvature else 3
    pos = np.concatenate(positions) if positions else np.zeros((0, 3), dtype=np.float32)
    data = np.concatenate([np.concatenate(normals)] + ([np.concatenate(curvs)] if curvature else []), axis=1) if positions else np.zeros((0, cols), dtype=np.float32)
    tmp = out + ".part"
    with open(tmp, "wb") as fh:
        fh.write(struct.pack("<4I", DATA_MAGIC, nv, cols, 0))
        fh.write(np.ascontiguousarray(pos, dtype="<f4").tobytes())
        fh.write(np.ascontiguousarray(data, dtype="<f4").tobytes())
    os.replace(tmp, out)
    return {"path": out, "vertices": nv, "columns": cols}


def read_points(p):
    if p.get("points") is not None:
        arr = np.asarray(p["points"], dtype=np.float64).reshape(-1, 3)
    else:
        path = store.absolute_path(p.get("points_path"), (".pts",), exists=True)
        arr = np.fromfile(path, dtype="<f4").astype(np.float64).reshape(-1, 3)
    if len(arr) > MAX_POINTS:
        raise RuntimeError("Too many points for one deviation call.")
    return arr


def single_face(shape):
    maps = store.build_maps(shape)
    if maps["faces"].Extent() != 1:
        return None
    return TopoDS.Face(maps["faces"].FindKey(1))


def inside_face(face, u, v):
    cl = BRepClass_FaceClassifier()
    cl.Perform(face, gp_Pnt2d(u, v), 1e-7)
    return cl.State() in (TopAbs_IN, TopAbs_ON)


def face_normal_at(face, u, v):
    sl = BRepLProp_SLProps(BRepAdaptor_Surface(face, True), u, v, 1, 1e-9)
    if not sl.IsNormalDefined():
        return None
    nd = sl.Normal()
    s = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
    return (s * nd.X(), s * nd.Y(), s * nd.Z())


def face_compound(ident, indices):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    faces = face_rows(ident)
    chosen = faces if not indices else [faces[int(i)] for i in indices if 0 <= int(i) < len(faces)]
    if not chosen:
        raise RuntimeError("The target has no face to measure against.")
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for f in chosen:
        builder.Add(comp, f)
    return comp


def an_deviation(p):
    pts = read_points(p)
    target = face_compound(p.get("target"), p.get("faces"))
    signed = bool(p.get("signed", False))
    out = finite_path(p.get("path"), ".adat")
    n = len(pts)
    dist = np.full(n, np.nan, dtype=np.float64)
    near = np.zeros((n, 3), dtype=np.float64)
    sign = np.ones(n, dtype=np.float64)
    flat = single_face(target)
    surf = BRep_Tool.Surface_s(flat) if flat is not None else None
    dss = BRepExtrema_DistShapeShape()
    dss.LoadS2(target)
    fast = 0
    for i in range(n):
        q = gp_Pnt(float(pts[i, 0]), float(pts[i, 1]), float(pts[i, 2]))
        if surf is not None:
            proj = GeomAPI_ProjectPointOnSurf(q, surf)
            best = None
            for j in range(1, proj.NbPoints() + 1):
                u, v = proj.Parameters(j)
                if inside_face(flat, u, v) and (best is None or proj.Distance(j) < best[0]):
                    best = (proj.Distance(j), proj.Point(j), u, v)
            if best is not None:
                dist[i] = best[0]
                near[i] = (best[1].X(), best[1].Y(), best[1].Z())
                if signed:
                    nrm = face_normal_at(flat, best[2], best[3])
                    if nrm is not None:
                        sign[i] = 1.0 if (pts[i, 0] - best[1].X()) * nrm[0] + (pts[i, 1] - best[1].Y()) * nrm[1] + (pts[i, 2] - best[1].Z()) * nrm[2] >= 0 else -1.0
                fast += 1
                continue
        dss.LoadS1(BRepBuilderAPI_MakeVertex(q).Vertex())
        if not dss.Perform() or dss.NbSolution() < 1:
            continue
        c = dss.PointOnShape2(1)
        dist[i] = dss.Value()
        near[i] = (c.X(), c.Y(), c.Z())
        if signed and str(dss.SupportTypeShape2(1)).endswith("IsInFace"):
            try:
                face = TopoDS.Face(dss.SupportOnShape2(1))
                u, v = dss.ParOnFaceS2(1)
                nrm = face_normal_at(face, u, v)
                if nrm is not None:
                    sign[i] = 1.0 if (pts[i, 0] - c.X()) * nrm[0] + (pts[i, 1] - c.Y()) * nrm[1] + (pts[i, 2] - c.Z()) * nrm[2] >= 0 else -1.0
            except Exception:
                pass
    tmp = out + ".part"
    with open(tmp, "wb") as fh:
        fh.write(struct.pack("<4I", DATA_MAGIC, n, 5, 0))
        fh.write(np.ascontiguousarray(np.concatenate([dist.reshape(-1, 1), near, sign.reshape(-1, 1)], axis=1), dtype="<f8").tobytes())
    os.replace(tmp, out)
    return {"path": out, "count": n, "columns": 5, "exact_projection": fast}


def curve_intervals(ad, per_span):
    kind = ad.GetType()
    first, last = ad.FirstParameter(), ad.LastParameter()
    if kind == GeomAbs_Line:
        return [(first, last, 2)]
    if kind in (GeomAbs_Circle, GeomAbs_Ellipse):
        return [(first, last, max(8, int(math.ceil((last - first) / (2.0 * math.pi) * 4 * per_span))))]
    count = max(1, ad.NbIntervals(GeomAbs_C2))
    arr = Array1_double(1, count + 1)
    ad.Intervals(arr, GeomAbs_C2)
    return [(arr.Value(i), arr.Value(i + 1), per_span) for i in range(1, count + 1)]


def an_comb(p):
    specs = p.get("curves") or []
    per_span = max(8, min(int(p.get("per_span", 12)), 64))
    if not isinstance(specs, list) or not specs or len(specs) > 256:
        raise RuntimeError("Give between 1 and 256 curves.")
    results = []
    total = 0
    for spec in specs:
        if "id" in spec and "index" in spec and spec.get("kind") == "shape_edge":
            maps = store.maps_of(spec["id"])["edges"]
            edges = [TopoDS.Edge(maps.FindKey(int(spec["index"]) + 1))]
        else:
            edges = edge_pieces(curve_wire(spec))
        rows = []
        for edge in edges:
            if BRep_Tool.Degenerated_s(edge):
                continue
            ad = BRepAdaptor_Curve(edge)
            geom = ad.Curve().Curve().Transformed(ad.Trsf())
            us = []
            for a, b, count in curve_intervals(ad, per_span):
                seg = np.linspace(a, b, max(2, count))
                if us:
                    seg = seg[1:]
                us.extend(float(u) for u in seg)
            total += len(us)
            if total > MAX_SAMPLES:
                raise RuntimeError("The curves need too many comb samples; select fewer curves or lower the density.")
            cl = GeomLProp_CLProps(geom, us[0], 2, 1e-9)
            pts, kap, nor, tan = [], [], [], []
            for u in us:
                cl.SetParameter(u)
                q = cl.Value()
                pts.append((q.X(), q.Y(), q.Z()))
                if cl.IsTangentDefined():
                    k = cl.Curvature()
                    t = gp_Dir(1, 0, 0)
                    cl.Tangent(t)
                    tan.append((t.X(), t.Y(), t.Z()))
                    if k > 1e-12:
                        nd = gp_Dir(1, 0, 0)
                        cl.Normal(nd)
                        nor.append((nd.X(), nd.Y(), nd.Z()))
                    else:
                        nor.append((0.0, 0.0, 0.0))
                    kap.append(k)
                else:
                    kap.append(0.0)
                    nor.append((0.0, 0.0, 0.0))
                    tan.append((0.0, 0.0, 0.0))
            rows.append({"u": us, "points": pts, "curvature": kap, "normal": nor, "tangent": tan, "type": str(ad.GetType()).split(".")[-1]})
        results.append({"edges": rows})
    return {"curves": results}


def an_affine(p):
    ident = p.get("id")
    src = store.shape_of(ident)
    m = p.get("matrix")
    if not isinstance(m, list) or len(m) != 12 or not all(math.isfinite(float(v)) for v in m):
        raise RuntimeError("An affine map has twelve numbers: three rows of a 3 by 3 matrix then the translation.")
    g = gp_GTrsf()
    for r in range(3):
        for c in range(3):
            g.SetValue(r + 1, c + 1, float(m[r * 4 + c]))
        g.SetValue(r + 1, 4, float(m[r * 4 + 3]))
    maker = BRepBuilderAPI_GTransform(src, g, True)
    if not maker.IsDone():
        raise RuntimeError("The scale could not be applied to this shape.")
    result = maker.Shape()
    new_id = store.put(result)
    out_maps = store.maps_of(new_id)
    return {"id": new_id, "summary": store.summarize(result), "history": {"inputs": [{"id": ident, **input_history(maker, src, store.maps_of(ident), out_maps)}]}}


def vec3(v):
    return np.asarray([float(v[0]), float(v[1]), float(v[2])], dtype=np.float64)


def box_hit(origin, d, lo, hi, pad):
    t0, t1 = -1e-9, 1e18
    for k in range(3):
        a, b = lo[k] - pad, hi[k] + pad
        if abs(d[k]) < 1e-14:
            if origin[k] < a or origin[k] > b:
                return False
        else:
            ta, tb = (a - origin[k]) / d[k], (b - origin[k]) / d[k]
            if ta > tb:
                ta, tb = tb, ta
            t0, t1 = max(t0, ta), min(t1, tb)
            if t0 > t1:
                return False
    return True


def ray_distance(origin, d, q):
    w = q - origin
    t = max(0.0, float(np.dot(w, d)))
    return float(np.linalg.norm(w - t * d)), t


def bbox_tuple(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    if box.IsVoid():
        return None
    return (np.array([box.GetXMin(), box.GetYMin(), box.GetZMin()]), np.array([box.GetXMax(), box.GetYMax(), box.GetZMax()]))


def shape_edges(ident):
    got = _edge_cache.get(ident)
    if got is not None:
        return got
    maps = store.maps_of(ident)["edges"]
    rows = []
    for i in range(1, maps.Extent() + 1):
        edge = TopoDS.Edge(maps.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        bb = bbox_tuple(edge)
        if bb is not None:
            rows.append((i - 1, edge, bb))
    if len(_edge_cache) > 128:
        _edge_cache.clear()
    _edge_cache[ident] = rows
    return rows


def curve_edges(spec):
    return [(i, e, bbox_tuple(e)) for i, e in enumerate(edge_pieces(curve_wire(spec))) if not BRep_Tool.Degenerated_s(e)]


def pt(q):
    return [q.X(), q.Y(), q.Z()]


def edge_param_mid(ad):
    try:
        length = GCPnts_AbscissaPoint.Length_s(ad)
        ap = GCPnts_AbscissaPoint(ad, length / 2.0, ad.FirstParameter())
        return ad.Value(ap.Parameter())
    except Exception:
        return ad.Value(0.5 * (ad.FirstParameter() + ad.LastParameter()))


def quadrant_points(ad, axes):
    first, last = ad.FirstParameter(), ad.LastParameter()
    steps = 360
    us = np.linspace(first, last, steps + 1)
    pts = np.array([[ad.Value(u).X(), ad.Value(u).Y(), ad.Value(u).Z()] for u in us])
    found = []
    closed = np.linalg.norm(pts[0] - pts[-1]) < 1e-9
    for ax in axes:
        f = pts @ ax
        for i in range(1, steps):
            if (f[i] >= f[i - 1] and f[i] > f[i + 1]) or (f[i] > f[i - 1] and f[i] >= f[i + 1]) or (f[i] <= f[i - 1] and f[i] < f[i + 1]) or (f[i] < f[i - 1] and f[i] <= f[i + 1]):
                lo, hi = us[i - 1], us[i + 1]
                sign = 1.0 if (f[i] >= f[i - 1] and f[i] >= f[i + 1]) else -1.0
                for _ in range(40):
                    m1, m2 = lo + (hi - lo) / 3.0, hi - (hi - lo) / 3.0
                    q1 = sign * float(np.dot(vec3(pt(ad.Value(m1))), ax))
                    q2 = sign * float(np.dot(vec3(pt(ad.Value(m2))), ax))
                    if q1 < q2:
                        lo = m1
                    else:
                        hi = m2
                found.append(pt(ad.Value(0.5 * (lo + hi))))
        if closed:
            f0 = f[0]
            if (f0 >= f[1] and f0 >= f[-2]) or (f0 <= f[1] and f0 <= f[-2]):
                found.append(pt(ad.Value(first)))
    return found


def snap_edge(ident_ref, idx, edge, ad, origin, d, aperture, modes, base, axes, out, element):
    ref = ident_ref
    first, last = ad.FirstParameter(), ad.LastParameter()

    def add(kind, q, **extra):
        qv = vec3(q)
        dist, t = ray_distance(origin, d, qv)
        if dist <= aperture:
            out.append({"kind": kind, "point": [float(c) for c in q], "dist": dist, "t": t, "ref": ref, "element": element, "index": idx, **extra})

    if "end" in modes:
        add("end", pt(ad.Value(first)))
        if abs(last - first) > 1e-12 and np.linalg.norm(vec3(pt(ad.Value(first))) - vec3(pt(ad.Value(last)))) > 1e-9:
            add("end", pt(ad.Value(last)))
    if "mid" in modes:
        add("mid", pt(edge_param_mid(ad)))
    if "centre" in modes:
        kind = ad.GetType()
        if kind == GeomAbs_Circle:
            add("centre", pt(ad.Circle().Location()), axis=[ad.Circle().Axis().Direction().X(), ad.Circle().Axis().Direction().Y(), ad.Circle().Axis().Direction().Z()])
        elif kind == GeomAbs_Ellipse:
            add("centre", pt(ad.Ellipse().Location()))
    if "quadrant" in modes and ad.GetType() != GeomAbs_Line:
        for q in quadrant_points(ad, axes):
            add("quadrant", q)
    if "perpendicular" in modes and base is not None:
        try:
            geom = ad.Curve().Curve().Transformed(ad.Trsf())
            proj = GeomAPI_ProjectPointOnCurve(gp_Pnt(*[float(c) for c in base]), geom, first, last)
            for i in range(1, proj.NbPoints() + 1):
                add("perpendicular", pt(proj.Point(i)), param=proj.Parameter(i))
        except Exception:
            pass
    if "nearest" in modes or "curve" in modes:
        try:
            geom = ad.Curve().Curve().Transformed(ad.Trsf())
            line = Geom_Line(gp_Lin(gp_Pnt(*origin.tolist()), gp_Dir(*d.tolist())))
            ex = GeomAPI_ExtremaCurveCurve(geom, line, first, last, 0.0, 1e9)
            if ex.NbExtrema() > 0:
                p1, p2 = gp_Pnt(), gp_Pnt()
                ex.NearestPoints(p1, p2)
                if p1.Distance(p2) <= aperture:
                    u1, u2 = ex.LowerDistanceParameters()
                    if u2 >= 0:
                        rec = {"kind": "nearest", "point": pt(p1), "dist": p1.Distance(p2), "t": u2, "ref": ref, "element": element, "index": idx, "param": u1}
                        if "nearest" in modes:
                            out.append(rec)
                        if "curve" in modes and element == "curve":
                            out.append({**rec, "kind": "curve"})
        except Exception:
            pass


def an_snap(p):
    ray = p.get("ray") or {}
    origin, d = vec3(ray["origin"]), vec3(ray["dir"])
    n = np.linalg.norm(d)
    if n < 1e-12:
        raise RuntimeError("The pick ray has no direction.")
    d = d / n
    aperture = float(p.get("aperture", 1.0))
    modes = set(p.get("modes") or SNAP_KINDS)
    base = p.get("base")
    plane = p.get("plane") or {}
    axes = [vec3(plane.get("x", [1, 0, 0])), vec3(plane.get("y", [0, 1, 0]))]
    out = []
    near_edges = []
    for item in p.get("items") or []:
        ref = item.get("ref")
        if "id" in item:
            ident = str(item["id"])
            bb = bbox_tuple(store.shape_of(ident))
            if bb is None or not box_hit(origin, d, bb[0], bb[1], aperture):
                continue
            element, rows = "edge", [(i, e, b) for i, e, b in shape_edges(ident)]
            if "vertex" in modes:
                vmap = store.maps_of(ident)["vertices"]
                for vi in range(1, vmap.Extent() + 1):
                    q = BRep_Tool.Pnt_s(TopoDS.Vertex(vmap.FindKey(vi)))
                    dist, t = ray_distance(origin, d, vec3(pt(q)))
                    if dist <= aperture:
                        out.append({"kind": "vertex", "point": pt(q), "dist": dist, "t": t, "ref": ref, "element": "vertex", "index": vi - 1})
            if "centre" in modes:
                for face in face_rows(ident):
                    sad = BRepAdaptor_Surface(face, True)
                    if sad.GetType() == GeomAbs_Sphere:
                        q = sad.Sphere().Location()
                        dist, t = ray_distance(origin, d, vec3(pt(q)))
                        if dist <= aperture:
                            out.append({"kind": "centre", "point": pt(q), "dist": dist, "t": t, "ref": ref, "element": "face", "index": -1})
            if "surface" in modes:
                inter = BRepIntCurveSurface_Inter()
                inter.Init(store.shape_of(ident), GeomAdaptor_Curve(Geom_Line(gp_Lin(gp_Pnt(*origin.tolist()), gp_Dir(*d.tolist()))), 0.0, 1e9), 1e-7)
                faces_map = store.maps_of(ident)["faces"]
                while inter.More():
                    face = inter.Face()
                    nrm = face_normal_at(face, inter.U(), inter.V())
                    out.append({"kind": "surface", "point": pt(inter.Pnt()), "dist": 0.0, "t": inter.W(), "ref": ref, "element": "face", "index": faces_map.FindIndex(face) - 1, "normal": list(nrm) if nrm else None})
                    inter.Next()
        else:
            element = "curve"
            try:
                rows = curve_edges(item["curve"])
            except Exception:
                continue
        for idx, edge, bb in rows:
            if bb is None or not box_hit(origin, d, bb[0], bb[1], aperture):
                continue
            if len(near_edges) >= EDGE_LIMIT:
                break
            ad = BRepAdaptor_Curve(edge)
            near_edges.append((ref, element, idx, edge, ad))
            snap_edge(ref, idx, edge, ad, origin, d, aperture, modes, base, axes, out, element)
    if "intersection" in modes:
        for a in range(len(near_edges)):
            for b in range(a + 1, len(near_edges)):
                ra, ea, ia, edge_a, _ = near_edges[a]
                rb, eb, ib, edge_b, _ = near_edges[b]
                dss = BRepExtrema_DistShapeShape(edge_a, edge_b)
                if not dss.IsDone() or dss.Value() > max(1e-6, aperture * 1e-4):
                    continue
                for s in range(1, min(dss.NbSolution(), 6) + 1):
                    q = dss.PointOnShape1(s)
                    dist, t = ray_distance(origin, d, vec3(pt(q)))
                    if dist <= aperture:
                        out.append({"kind": "intersection", "point": pt(q), "dist": dist, "t": t, "ref": ra, "ref2": rb, "element": ea, "index": ia, "index2": ib})
    seen = []
    unique = []
    for rec in sorted(out, key=lambda r: (r["dist"], r["t"])):
        key = (rec["kind"], round(rec["point"][0], 6), round(rec["point"][1], 6), round(rec["point"][2], 6))
        if key in seen:
            continue
        seen.append(key)
        unique.append(rec)
    return {"candidates": unique[: int(p.get("limit", 60))]}


METHODS = {"an_shape_data": an_shape_data, "an_deviation": an_deviation, "an_comb": an_comb, "an_affine": an_affine, "an_snap": an_snap}
