import base64
import struct
import zlib

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
from OCP.BRepLib import BRepLib
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface
from OCP.Geom2d import Geom2d_BSplineCurve, Geom2d_TrimmedCurve
from OCP.Geom2dConvert import Geom2dConvert
from OCP.GeomAbs import GeomAbs_BSplineCurve
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Pnt2d, gp_Vec2d

import kernel_store as store
from kernel_surf import TopoDS, kind_edges

T_CLASS = 0x00027FFA
T_CLASS_UUID = 0x0002FFFB
T_CLASS_DATA = 0x0002FFFC
T_CLASS_END = 0x80027FFF
T_ANONYMOUS = 0x40008000
BREP_UUID = bytes.fromhex("c5dbb56060e6d311bfe40010830122f0")
UNSET = -1.23432101234321e308
SQRT_EPS = 1.490116119385000000e-8
EPS = 2.2204460492503131e-16
TRIM_BOUNDARY, TRIM_MATED, TRIM_SEAM, TRIM_SINGULAR = 1, 2, 3, 4
LOOP_OUTER, LOOP_INNER = 1, 2
ISO_NONE, ISO_X, ISO_Y, ISO_W, ISO_S, ISO_E, ISO_N = 0, 1, 2, 3, 4, 5, 6


def chunk(code, body):
    if code & 0x8000:
        body = body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)
    return struct.pack("<Iq", code, len(body)) + body


def ints(*values):
    return struct.pack("<%di" % len(values), *values)


def reals(*values):
    return struct.pack("<%dd" % len(values), *values)


def int_list(values):
    return ints(len(values), *values)


def table(rows):
    return chunk(T_ANONYMOUS, b"\x10" + ints(len(rows)) + b"".join(rows))


def object_bytes(obj):
    return base64.b64decode(obj.Encode()["data"])


def object_table(blobs):
    return table([ints(1) + b for b in blobs])


def body_parts(shape):
    parts = []
    for kind, avoid in ((TopAbs_SOLID, None), (TopAbs_SHELL, TopAbs_SOLID)):
        ex = TopExp_Explorer(shape, kind) if avoid is None else TopExp_Explorer(shape, kind, avoid)
        seen = store.ShapeMap()
        while ex.More():
            if seen.FindIndex(ex.Current()) == 0:
                seen.Add(ex.Current())
                parts.append([TopoDS.Face_s(x) for x in kind_edges(ex.Current(), TopAbs_FACE)])
            ex.Next()
    loose = []
    ex = TopExp_Explorer(shape, TopAbs_FACE, TopAbs_SHELL)
    seen = store.ShapeMap()
    while ex.More():
        if seen.FindIndex(ex.Current()) == 0:
            seen.Add(ex.Current())
            loose.append(TopoDS.Face_s(ex.Current()))
        ex.Next()
    emap = store.ShapeMap()
    root = list(range(len(loose)))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    owner = {}
    for i, face in enumerate(loose):
        for e in kind_edges(face, TopAbs_EDGE):
            k = emap.FindIndex(e) or emap.Add(e)
            if k in owner:
                root[find(i)] = find(owner[k])
            else:
                owner[k] = i
    groups = {}
    for i, face in enumerate(loose):
        groups.setdefault(find(i), []).append(face)
    parts.extend(groups.values())
    return [p for p in parts if p]


def edge_curve(edge):
    ad = BRepAdaptor_Curve(edge)
    if ad.GetType() != GeomAbs_BSplineCurve:
        raise RuntimeError("an edge has no B-spline curve")
    bs = Geom_BSplineCurve(ad.BSpline())
    a, b = ad.FirstParameter(), ad.LastParameter()
    span = bs.LastParameter() - bs.FirstParameter()
    inside = a >= bs.FirstParameter() - 1e-12 * max(1.0, span) and b <= bs.LastParameter() + 1e-12 * max(1.0, span)
    if bs.IsPeriodic() and not inside:
        bs.Segment(a, b)
    if bs.IsPeriodic():
        bs.SetNotPeriodic()
    if inside and (a > bs.FirstParameter() + 1e-12 or b < bs.LastParameter() - 1e-12):
        bs.Segment(max(a, bs.FirstParameter()), min(b, bs.LastParameter()))
    return bs, ad


def trim_curve(edge, face):
    ad = BRepAdaptor_Curve2d(edge, face)
    a, b = ad.FirstParameter(), ad.LastParameter()
    base = ad.Curve()
    if base is None or not (b > a):
        raise RuntimeError("an edge has no curve on its face")
    bs = Geom2dConvert.CurveToBSplineCurve_s(Geom2d_TrimmedCurve(base, a, b))
    bs = Geom2d_BSplineCurve(bs)
    if bs.IsPeriodic():
        bs.SetNotPeriodic()
    return bs, ad


def new_trim_curve(rh, g):
    p = g.Degree()
    n = g.NbPoles()
    rational = bool(g.IsRational())
    nc = rh.NurbsCurve(2, rational, p + 1, n)
    for i in range(n):
        q = g.Pole(i + 1)
        w = g.Weight(i + 1) if rational else 1.0
        nc.Points[i] = rh.Point4d(q.X() * w, q.Y() * w, 0.0, w)
    flat = []
    for i in range(1, g.NbKnots() + 1):
        flat.extend([g.Knot(i)] * g.Multiplicity(i))
    flat = flat[1:-1]
    if len(flat) != len(nc.Knots):
        raise RuntimeError("the knot vector length is not what the 3DM trim curve expects")
    for i, k in enumerate(flat):
        nc.Knots[i] = float(k)
    return nc


def side_band(lo, hi, t):
    d = (hi - lo) * 8.0 * SQRT_EPS + (abs(lo) + abs(hi)) * EPS
    if d >= hi - lo:
        d = 0.5 * (hi - lo)
    return t - d, t + d


def iso_of(g, bounds):
    xs = [g.Pole(i + 1).X() for i in range(g.NbPoles())]
    ys = [g.Pole(i + 1).Y() for i in range(g.NbPoles())]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s0, s1, t0, t1 = bounds
    ds, dt = x1 - x0, y1 - y0
    stol, ttol = (s1 - s0) / 32.0, (t1 - t0) / 32.0
    if not (s0 < s1 and t0 < t1 and (ds <= stol or dt <= ttol)):
        return ISO_NONE
    if ds * (t1 - t0) <= dt * (s1 - s0):
        lo, hi, a, b, low, high, mid = x0, x1, s0, s1, ISO_W, ISO_E, ISO_X
        tol = stol
    else:
        lo, hi, a, b, low, high, mid = y0, y1, t0, t1, ISO_S, ISO_N, ISO_Y
        tol = ttol
    if lo <= a + tol:
        m, n = side_band(a, b, a)
        if m <= lo and hi <= n:
            return low
    elif hi >= b - tol:
        m, n = side_band(a, b, b)
        if m <= lo and hi <= n:
            return high
    m, n = side_band(a, b, 0.5 * (lo + hi))
    if m <= lo and hi <= n:
        return mid
    return ISO_NONE


def loop_area(curves):
    pts = []
    for g in curves:
        a, b = g.FirstParameter(), g.LastParameter()
        for k in range(24):
            q = g.Value(a + (b - a) * k / 24.0)
            pts.append((q.X(), q.Y()))
    total = 0.0
    for k in range(len(pts)):
        x0, y0 = pts[k]
        x1, y1 = pts[(k + 1) % len(pts)]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def open_surface(face, curves):
    sg = BRep_Tool.Surface_s(face)
    if not isinstance(sg, Geom_BSplineSurface):
        raise RuntimeError("a face surface has no B-spline form")
    sg = Geom_BSplineSurface(sg)
    a0, a1, b0, b1 = sg.Bounds()
    us, vs = [], []
    for g in curves:
        a, b = g.FirstParameter(), g.LastParameter()
        for k in range(25):
            q = g.Value(a + (b - a) * k / 24.0)
            us.append(q.X())
            vs.append(q.Y())
    shift_u = shift_v = 0.0
    if sg.IsUPeriodic():
        period = a1 - a0
        shift_u = -period * round((0.5 * (min(us) + max(us)) - 0.5 * (a0 + a1)) / period)
        sg.SetUNotPeriodic()
    if sg.IsVPeriodic():
        period = b1 - b0
        shift_v = -period * round((0.5 * (min(vs) + max(vs)) - 0.5 * (b0 + b1)) / period)
        sg.SetVNotPeriodic()
    if shift_u or shift_v:
        for g in curves:
            g.Translate(gp_Vec2d(shift_u, shift_v))
    c0, c1, d0, d1 = sg.Bounds()
    eu, ev = 1e-6 * (c1 - c0), 1e-6 * (d1 - d0)
    if min(us) + shift_u < c0 - eu or max(us) + shift_u > c1 + eu or min(vs) + shift_v < d0 - ev or max(vs) + shift_v > d1 + ev:
        raise RuntimeError("a trim loop runs outside its surface")
    for g in curves:
        for i in (1, g.NbPoles()):
            q = g.Pole(i)
            u, v = min(max(q.X(), c0), c1), min(max(q.Y(), d0), d1)
            if u != q.X() or v != q.Y():
                g.SetPole(i, gp_Pnt2d(u, v))
    return sg


def close_loop(curves, sg, slack):
    c0, c1, d0, d1 = sg.Bounds()
    for k, g in enumerate(curves):
        h = curves[(k + 1) % len(curves)]
        p, q = g.Pole(g.NbPoles()), h.Pole(1)
        du, dv = abs(p.X() - q.X()), abs(p.Y() - q.Y())
        if du == 0.0 and dv == 0.0:
            continue
        if du > 1e-6 * (c1 - c0) or dv > 1e-6 * (d1 - d0):
            if du > 0.25 * (c1 - c0) or dv > 0.25 * (d1 - d0) or sg.Value(p.X(), p.Y()).Distance(sg.Value(q.X(), q.Y())) > slack:
                raise RuntimeError("a trim loop is not closed on its surface")
        if h is g:
            g.SetPole(g.NbPoles(), q)
            continue
        u, v = 0.5 * (p.X() + q.X()), 0.5 * (p.Y() + q.Y())
        for line, here, far in ((g, p, g.Pole(1)), (h, q, h.Pole(h.NbPoles()))):
            if line.NbPoles() == 2:
                if far.X() == here.X():
                    u = here.X()
                if far.Y() == here.Y():
                    v = here.Y()
        g.SetPole(g.NbPoles(), gp_Pnt2d(u, v))
        h.SetPole(1, gp_Pnt2d(u, v))


def brep_of_faces(rh, faces, inv, tol, make_curve, make_surface):
    comp = TopoDS_Compound()
    BRep_Builder().MakeCompound(comp)
    for face in faces:
        BRep_Builder().Add(comp, face)
    conv = BRepBuilderAPI_NurbsConvert(comp, True)
    work = conv.Shape()
    BRepLib.BuildCurves3d_s(work)
    vmap, emap = store.ShapeMap(), store.ShapeMap()
    TopExp.MapShapes_s(work, TopAbs_VERTEX, vmap)
    TopExp.MapShapes_s(work, TopAbs_EDGE, emap)
    verts, vert_of = [], {}
    edges, edge_of = [], {}
    trims, loops, face_rows = [], [], []
    c2, c3, surfs = [], [], []

    def vertex_index(v):
        if v.IsNull():
            raise RuntimeError("an edge has no end vertex")
        k = vmap.FindIndex(v)
        if k not in vert_of:
            q = BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))
            vert_of[k] = len(verts)
            verts.append({"p": (q.X(), q.Y(), q.Z()), "at": q, "ei": [], "tol": 0.0, "limit": BRep_Tool.Tolerance_s(TopoDS.Vertex_s(v))})
        return vert_of[k]

    def edge_index(e):
        k = emap.FindIndex(e)
        if k == 0:
            raise RuntimeError("an edge of a loop is not part of the body")
        if k not in edge_of:
            fwd = TopoDS.Edge_s(emap.FindKey(k).Oriented(TopAbs_FORWARD))
            bs, ad = edge_curve(fwd)
            va, vb = vertex_index(TopExp.FirstVertex_s(fwd, True)), vertex_index(TopExp.LastVertex_s(fwd, True))
            for vi, q in ((va, bs.StartPoint()), (vb, bs.EndPoint())):
                d = q.Distance(verts[vi]["at"])
                if d > max(10.0 * tol, 4.0 * verts[vi]["limit"]):
                    raise RuntimeError("an edge does not end at its vertex")
                verts[vi]["tol"] = max(verts[vi]["tol"], d)
            edge_of[k] = len(edges)
            verts[va]["ei"].append(len(edges))
            verts[vb]["ei"].append(len(edges))
            edges.append({"c3": len(c3), "vi": (va, vb), "ti": [], "tol": 0.0, "dom": (bs.FirstParameter(), bs.LastParameter()), "ad": ad})
            c3.append(object_bytes(make_curve(bs, inv)))
        return edge_of[k]

    for face in kind_edges(work, TopAbs_FACE):
        face = TopoDS.Face_s(face)
        fwd = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
        outer = BRepTools.OuterWire_s(fwd)
        rows = []
        for wire in kind_edges(fwd, TopAbs_WIRE):
            wire = TopoDS.Wire_s(wire)
            if wire.Orientation() not in (TopAbs_FORWARD, TopAbs_REVERSED):
                raise RuntimeError("a face has an internal wire")
            ex = BRepTools_WireExplorer(wire, fwd)
            row = []
            while ex.More():
                e = ex.Current()
                if e.Orientation() not in (TopAbs_FORWARD, TopAbs_REVERSED):
                    raise RuntimeError("a face has an internal edge")
                g, ad2 = trim_curve(e, fwd)
                rev = e.Orientation() == TopAbs_REVERSED
                item = {"g": g, "rev": rev, "ad2": ad2, "edge": e, "singular": bool(BRep_Tool.Degenerated_s(e))}
                if rev:
                    g.Reverse()
                row.append(item)
                ex.Next()
            count = 0
            every_edge = TopExp_Explorer(wire, TopAbs_EDGE)
            while every_edge.More():
                count += 1
                every_edge.Next()
            if len(row) != count:
                raise RuntimeError("the edges of a loop could not be put in order")
            if not row:
                raise RuntimeError("a loop has no edges")
            rows.append((0 if wire.IsSame(outer) else 1, row))
        rows.sort(key=lambda r: r[0])
        if not rows or rows[0][0] != 0 or (len(rows) > 1 and rows[1][0] == 0):
            raise RuntimeError("a face has no single outer loop")
        every = [x["g"] for _, row in rows for x in row]
        base = BRep_Tool.Surface_s(fwd)
        sg = open_surface(fwd, every)
        bounds = sg.Bounds()
        fi = len(face_rows)
        loop_ids = []
        slack = max(10.0 * tol, 4.0 * max(BRep_Tool.Tolerance_s(TopoDS.Vertex_s(v)) for v in kind_edges(fwd, TopAbs_VERTEX)))
        for inner, row in rows:
            close_loop([x["g"] for x in row], sg, slack)
            area = loop_area([x["g"] for x in row])
            if (area <= 0.0) != bool(inner):
                raise RuntimeError("a trim loop runs the wrong way round")
            li = len(loops)
            ids = []
            for x in row:
                g = x["g"]
                ti = len(trims)
                iso = iso_of(g, bounds)
                if x["singular"]:
                    vi = vertex_index(TopExp.FirstVertex_s(TopoDS.Edge_s(x["edge"].Oriented(TopAbs_FORWARD)), True))
                    if iso not in (ISO_W, ISO_S, ISO_E, ISO_N):
                        raise RuntimeError("a collapsed edge does not lie on a surface side")
                    trims.append({"c2": len(c2), "ei": -1, "vi": (vi, vi), "rev": 0, "type": TRIM_SINGULAR, "iso": iso, "li": li, "dom": (g.FirstParameter(), g.LastParameter())})
                else:
                    ei = edge_index(x["edge"])
                    edge = edges[ei]
                    a, b = x["ad2"].FirstParameter(), x["ad2"].LastParameter()
                    ad3 = edge["ad"]
                    lo, hi = ad3.FirstParameter(), ad3.LastParameter()
                    dev = 0.0
                    for k in range(9):
                        t = a + (b - a) * k / 8.0
                        uv = x["ad2"].Value(t)
                        dev = max(dev, base.Value(uv.X(), uv.Y()).Distance(ad3.Value(min(max(t, lo), hi))))
                    edge["tol"] = max(edge["tol"], dev)
                    edge["ti"].append(ti)
                    va, vb = edge["vi"]
                    trims.append({"c2": len(c2), "ei": ei, "vi": (vb, va) if x["rev"] else (va, vb), "rev": 1 if x["rev"] else 0, "type": TRIM_BOUNDARY, "iso": iso, "li": li, "dom": (g.FirstParameter(), g.LastParameter())})
                c2.append(object_bytes(new_trim_curve(rh, g)))
                ids.append(ti)
            loops.append({"ti": ids, "type": LOOP_INNER if inner else LOOP_OUTER, "fi": fi})
            loop_ids.append(li)
        face_rows.append({"li": loop_ids, "si": len(surfs), "rev": 1 if face.Orientation() == TopAbs_REVERSED else 0})
        surfs.append(object_bytes(make_surface(sg, inv)))

    for edge in edges:
        used = edge["ti"]
        if len(used) == 2 and trims[used[0]]["li"] == trims[used[1]]["li"]:
            kind = TRIM_SEAM
        else:
            kind = TRIM_MATED if len(used) > 1 else TRIM_BOUNDARY
        for ti in used:
            trims[ti]["type"] = kind

    data = b"\x32" + object_table(c2) + object_table(c3) + object_table(surfs)
    data += table([ints(i) + reals(v["p"][0] * inv, v["p"][1] * inv, v["p"][2] * inv) + int_list(v["ei"]) + reals(v["tol"] * inv) for i, v in enumerate(verts)])
    data += table([ints(i, e["c3"], 0) + reals(*e["dom"]) + ints(*e["vi"]) + int_list(e["ti"]) + reals(e["tol"] * inv) + reals(*e["dom"]) for i, e in enumerate(edges)])
    data += table([ints(i, t["c2"]) + reals(*t["dom"]) + ints(t["ei"], t["vi"][0], t["vi"][1], t["rev"], t["type"], t["iso"], t["li"]) + reals(0.0, 0.0) + reals(*t["dom"]) + bytes(32) + reals(UNSET, UNSET) for i, t in enumerate(trims)])
    data += table([ints(i) + int_list(lp["ti"]) + ints(lp["type"], lp["fi"]) for i, lp in enumerate(loops)])
    data += table([ints(i) + int_list(f["li"]) + ints(f["si"], f["rev"], 0) for i, f in enumerate(face_rows)])
    data += reals(1.0, 0.0, 0.0, -1.0, 0.0, 0.0)
    data += chunk(T_ANONYMOUS, bytes(len(face_rows))) * 2
    data += ints(0)
    blob = chunk(T_CLASS, chunk(T_CLASS_UUID, BREP_UUID) + chunk(T_CLASS_DATA, data) + struct.pack("<Iq", T_CLASS_END, 0))
    seed = rh.Point(rh.Point3d(0.0, 0.0, 0.0)).Encode()
    seed["data"] = base64.b64encode(blob).decode("ascii")
    brep = rh.CommonObject.Decode(seed)
    if brep is None or not isinstance(brep, rh.Brep):
        raise RuntimeError("the 3DM library did not accept the joined body")
    if len(brep.Faces) != len(face_rows) or len(brep.Edges) != len(edges):
        raise RuntimeError("the 3DM library read back a different body")
    ok, log = brep.IsValidWithLog
    if not ok:
        raise RuntimeError("the joined body is not a valid 3DM polysurface (%s)" % (" ".join(str(log).split())[:160] or "no reason given"))
    naked = sum(1 for e in edges if len(e["ti"]) == 1)
    worst = max([e["tol"] for e in edges] or [0.0])
    return brep, {"faces": len(face_rows), "edges": len(edges), "trims": len(trims), "loops": len(loops), "naked_edges": naked, "edge_gap": worst}
