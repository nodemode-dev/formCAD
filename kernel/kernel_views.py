import math
import time

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Section
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_TrimmedCurve
from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_BezierCurve, GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_Line
from OCP.GeomConvert import GeomConvert
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape, HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape, HLRBRep_TypeOfResultingEdge as RType
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.collections import List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax1, gp_Ax2, gp_Ax3, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec

import kernel_store as store

CLASSES = ("sharp_v", "sharp_h", "smooth_v", "smooth_h", "sewn_v", "sewn_h", "outline_v", "outline_h")
TYPES = {"sharp": RType.HLRBRep_Sharp, "smooth": RType.HLRBRep_Rg1Line, "sewn": RType.HLRBRep_RgNLine, "outline": RType.HLRBRep_OutLine}
MAX_PIECES = 200000
MAX_ATTRIBUTE = 6000
FACE_CAP = 400


def vec3(v):
    return [float(v[0]), float(v[1]), float(v[2])]


def unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-12:
        raise RuntimeError("A direction has zero length.")
    return [v[0] / n, v[1] / n, v[2] / n]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def add(a, b, k=1.0):
    return [a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2]]


def frame_of(normal, up):
    n = unit(normal)
    u = vec3(up)
    x = cross(u, n)
    if math.sqrt(dot(x, x)) < 1e-9:
        pick = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [0.0, 1.0, 0.0]
        x = cross(pick, n)
    x = unit(x)
    y = unit(cross(n, x))
    return x, y, n


def trsf_of(m):
    t = gp_Trsf()
    if not m:
        return t
    if len(m) != 12:
        raise RuntimeError("A component matrix needs 12 numbers.")
    t.SetValues(*[float(v) for v in m])
    return t


def make_compound(shapes):
    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for s in shapes:
        b.Add(comp, s)
    return comp


def edges_of(shape):
    out = []
    if shape is None or shape.IsNull():
        return out
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        out.append(TopoDS.Edge(ex.Current()))
        ex.Next()
    return out


def bbox(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if box.IsVoid():
        return None
    return [box.GetXMin(), box.GetYMin(), box.GetZMin(), box.GetXMax(), box.GetYMax(), box.GetZMax()]


def load_items(items):
    shapes = []
    for idx, it in enumerate(items):
        base = store.shape_of(it.get("id"))
        t = trsf_of(it.get("matrix"))
        moved = base if not it.get("matrix") else BRepBuilderAPI_Transform(base, t, False).Shape()
        shapes.append(moved)
    return shapes


class Attributor:
    def __init__(self, shapes):
        self.edges = []
        self.faces = []
        self.verts = []
        for i, sh in enumerate(shapes):
            maps = store.build_maps(sh)
            for kind, bucket in (("edges", self.edges), ("faces", self.faces)):
                m = maps[kind]
                for k in range(1, m.Extent() + 1):
                    s = m.FindKey(k)
                    bucket.append((i, k, s, bbox(s)))
            m = maps["vertices"]
            for k in range(1, m.Extent() + 1):
                p = BRep_Tool.Pnt_s(TopoDS.Vertex(m.FindKey(k)))
                self.verts.append((i, k, p.X(), p.Y(), p.Z()))
        self.tol = 1e-5

    def _near(self, table, point, tol):
        vtx = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()
        best = None
        for row in table:
            bb = row[3]
            if bb is None:
                continue
            if point[0] < bb[0] - tol or point[0] > bb[3] + tol or point[1] < bb[1] - tol or point[1] > bb[4] + tol or point[2] < bb[2] - tol or point[2] > bb[5] + tol:
                continue
            ext = BRepExtrema_DistShapeShape(vtx, row[2])
            if not ext.IsDone() or ext.NbSolution() < 1:
                continue
            d = ext.Value()
            if d <= tol and (best is None or d < best[0]):
                best = (d, row[0], row[1])
        return best

    def edge(self, point, tol):
        return self._near(self.edges, point, tol)

    def face(self, point, tol):
        return self._near(self.faces, point, tol)

    def vertex(self, point, tol):
        best = None
        for row in self.verts:
            d = math.sqrt((row[2] - point[0]) ** 2 + (row[3] - point[1]) ** 2 + (row[4] - point[2]) ** 2)
            if d <= tol and (best is None or d < best[0]):
                best = (d, row[0], row[1])
        return best


def curve_pt(c, u):
    p = c.Value(u)
    return p.X(), p.Y(), p.Z()


def spline_record(curve, first, last, flip=False):
    trimmed = Geom_TrimmedCurve(curve, first, last)
    bs = GeomConvert.CurveToBSplineCurve_s(trimmed)
    if bs.IsPeriodic():
        bs.SetNotPeriodic()
    deg = bs.Degree()
    knots = []
    for k in range(1, bs.NbKnots() + 1):
        knots.extend([bs.Knot(k)] * bs.Multiplicity(k))
    ctrl = [[bs.Pole(i).X(), bs.Pole(i).Y()] for i in range(1, bs.NbPoles() + 1)]
    w = [bs.Weight(i) for i in range(1, bs.NbPoles() + 1)] if bs.IsRational() else None
    return {"t": "spline", "deg": deg, "knots": knots, "ctrl": ctrl, "w": w}


def sample_record(c, first, last, n=24):
    pts = []
    for i in range(n + 1):
        x, y, _z = curve_pt(c, first + (last - first) * i / n)
        pts.append([x, y])
    return {"t": "poly", "pts": pts}


def edge_record(edge):
    c = BRepAdaptor_Curve(edge)
    f, l = c.FirstParameter(), c.LastParameter()
    ty = c.GetType()
    if ty == GeomAbs_Line:
        a, b = curve_pt(c, f), curve_pt(c, l)
        return {"t": "line", "a": [a[0], a[1]], "b": [b[0], b[1]]}
    if ty == GeomAbs_Circle:
        circ = c.Circle()
        ctr = circ.Location()
        ccw = circ.Axis().Direction().Z() >= 0.0
        px, py, _ = curve_pt(c, f)
        qx, qy, _ = curve_pt(c, l)
        a0 = math.atan2(py - ctr.Y(), px - ctr.X())
        a1 = math.atan2(qy - ctr.Y(), qx - ctr.X())
        if not ccw:
            a0, a1 = a1, a0
        if abs(l - f - 2.0 * math.pi) < 1e-9 or abs(abs(l - f) - 2.0 * math.pi) < 1e-9:
            return {"t": "circle", "c": [ctr.X(), ctr.Y()], "r": circ.Radius()}
        return {"t": "arc", "c": [ctr.X(), ctr.Y()], "r": circ.Radius(), "a0": a0, "a1": a1}
    if ty == GeomAbs_Ellipse:
        el = c.Ellipse()
        ctr = el.Location()
        xd = el.XAxis().Direction()
        ccw = el.Axis().Direction().Z() >= 0.0
        u0, u1 = f, l
        if not ccw:
            u0, u1 = -l, -f
        major = [xd.X() * el.MajorRadius(), xd.Y() * el.MajorRadius()]
        full = abs(abs(l - f) - 2.0 * math.pi) < 1e-9
        rec = {"t": "ellipse", "c": [ctr.X(), ctr.Y()], "major": major, "ratio": el.MinorRadius() / el.MajorRadius(), "a0": 0.0 if full else u0, "a1": 2.0 * math.pi if full else u1}
        return rec
    if ty in (GeomAbs_BSplineCurve, GeomAbs_BezierCurve):
        curve =c.BSpline() if ty == GeomAbs_BSplineCurve else c.Bezier()
        return spline_record(curve, f, l)
    return sample_record(c, f, l)


def project_xy(trsf_view, point):
    p = gp_Pnt(*point).Transformed(trsf_view)
    return p.X(), p.Y(), p.Z()


def hlr_pieces(shape, normal, up, origin, mode, deflection):
    x, y, n = frame_of(normal, up)
    ax = gp_Ax2(gp_Pnt(*origin), gp_Dir(*n), gp_Dir(*x))
    out = {}
    stats = {"mode": mode}
    t0 = time.perf_counter()
    if mode == "draft":
        bb = bbox(shape)
        diag = math.dist(bb[:3], bb[3:]) if bb else 1.0
        BRepMesh_IncrementalMesh(shape, max(deflection, diag * 1e-4), False, 0.5, True)
        algo = HLRBRep_PolyAlgo()
        algo.Load(shape)
        algo.Projector(HLRAlgo_Projector(ax))
        algo.Update()
        sh = HLRBRep_PolyHLRToShape()
        sh.Update(algo)
        names = {"sharp_v": sh.VCompound, "sharp_h": sh.HCompound, "smooth_v": sh.Rg1LineVCompound, "smooth_h": sh.Rg1LineHCompound, "sewn_v": sh.RgNLineVCompound, "sewn_h": sh.RgNLineHCompound, "outline_v": sh.OutLineVCompound, "outline_h": sh.OutLineHCompound}
        for cls, fn in names.items():
            out[cls] = [(e, None) for e in edges_of(fn())]
        stats["ms"] = (time.perf_counter() - t0) * 1000.0
        return out, stats
    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(HLRAlgo_Projector(ax))
    algo.Update()
    algo.Hide()
    sh = HLRBRep_HLRToShape(algo)
    for kind, ty in TYPES.items():
        for vis, suffix in ((True, "_v"), (False, "_h")):
            two = edges_of(sh.CompoundOfEdges(ty, vis, False))
            three = []
            if kind != "outline":
                three = edges_of(sh.CompoundOfEdges(ty, vis, True))
                if len(three) != len(two):
                    three = []
            out[kind + suffix] = [(e, three[i] if three else None) for i, e in enumerate(two)]
    if True:
        three_out = edges_of(sh.CompoundOfEdges(RType.HLRBRep_OutLine, True, True))
        stats["outline3d_v"] = three_out
        stats["outline3d_h"] = edges_of(sh.CompoundOfEdges(RType.HLRBRep_OutLine, False, True))
    stats["ms"] = (time.perf_counter() - t0) * 1000.0
    return out, stats


def mid_point(edge):
    c = BRepAdaptor_Curve(edge)
    return curve_pt(c, 0.5 * (c.FirstParameter() + c.LastParameter()))


def end_points(edge):
    c = BRepAdaptor_Curve(edge)
    return curve_pt(c, c.FirstParameter()), curve_pt(c, c.LastParameter())


def attribute(pieces_by_class, stats, attr, view_t, diag):
    tol = max(diag * 1e-6, 1e-6)
    vtol = max(diag * 1e-6, 1e-5)
    count = 0
    meta = {}
    cand_v = [(e, project_xy(view_t, mid_point(e))) for e in stats.get("outline3d_v", [])]
    cand_h = [(e, project_xy(view_t, mid_point(e))) for e in stats.get("outline3d_h", [])]
    for cls, rows in pieces_by_class.items():
        for k, (e2, e3) in enumerate(rows):
            key = (cls, k)
            if e3 is None and not cls.startswith("outline"):
                continue
            count += 1
            if count > MAX_ATTRIBUTE:
                return meta
            if cls.startswith("outline"):
                m2 = mid_point(e2)
                pool = cand_v if cls.endswith("_v") else cand_h
                hit = None
                best = 1e-6 + diag * 1e-6
                for e, pm in pool:
                    d = math.hypot(pm[0] - m2[0], pm[1] - m2[1])
                    if d < best:
                        best, hit = d, e
                if hit is None:
                    continue
                face = attr.face(mid_point(hit), tol)
                if face:
                    meta[key] = {"s": [face[1], 0, face[2], 0, 0]}
                continue
            a3, b3 = end_points(e3)
            m3 = mid_point(e3)
            hit = attr.edge(m3, tol)
            s = [0, 0, 0, 0, 0]
            if hit:
                s[0], s[1] = hit[1], hit[2]
            else:
                fh = attr.face(m3, tol)
                if fh:
                    s[0], s[2] = fh[1], fh[2]
            for slot, pt in ((3, a3), (4, b3)):
                v = attr.vertex(pt, vtol)
                if v:
                    s[slot] = v[2]
                    if not hit and not s[2]:
                        s[0] = v[1]
            meta[key] = {"s": s, "p": [round(a3[0], 6), round(a3[1], 6), round(a3[2], 6), round(b3[0], 6), round(b3[1], 6), round(b3[2], 6)]}
    return meta


def view_transform(origin, normal, up):
    x, y, n = frame_of(normal, up)
    t = gp_Trsf()
    t.SetTransformation(gp_Ax3(gp_Pnt(*origin), gp_Dir(*n), gp_Dir(*x)))
    return t


def box_in_frame(origin, xdir, ydir, zdir, x0, x1, y0, y1, z0, z1):
    corner = add(add(add(origin, xdir, x0), ydir, y0), zdir, z0)
    ax = gp_Ax2(gp_Pnt(*corner), gp_Dir(*zdir), gp_Dir(*xdir))
    return BRepPrimAPI_MakeBox(ax, x1 - x0, y1 - y0, z1 - z0).Shape()


def shape_list(items):
    out = ShapeList()
    for s in items:
        out.Append(s)
    return out


def boolean(cls, args, tools):
    maker = cls()
    maker.SetArguments(shape_list(args))
    maker.SetTools(shape_list(tools))
    maker.SetRunParallel(True)
    maker.SetNonDestructive(True)
    maker.Build()
    probe = getattr(maker, "HasErrors", None)
    if not maker.IsDone() or (callable(probe) and probe()):
        raise RuntimeError("The section cut could not be computed.")
    return maker


def poly_wire_faces(points3, ext_dir, lo, hi):
    wire = BRepBuilderAPI_MakePolygon()
    for p in points3:
        wire.Add(gp_Pnt(*p))
    w = wire.Wire()
    sheet = BRepPrimAPI_MakePrism(w, gp_Vec(*[ext_dir[i] * (hi - lo) for i in range(3)])).Shape()
    moved = BRepBuilderAPI_Transform(sheet, trsf_translate([ext_dir[i] * lo for i in range(3)]), False).Shape()
    return moved


def trsf_translate(v):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*v))
    return t


def trsf_rotate(origin, axis, angle):
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(*origin), gp_Dir(*axis)), angle)
    return t


def prism_of_polygon(points3, ext_dir, half):
    mk = BRepBuilderAPI_MakePolygon()
    for p in points3:
        mk.Add(gp_Pnt(*p))
    mk.Close()
    face = BRepBuilderAPI_MakeFace(mk.Wire(), True).Face()
    face = BRepBuilderAPI_Transform(face, trsf_translate([-ext_dir[i] * half for i in range(3)]), False).Shape()
    return BRepPrimAPI_MakePrism(face, gp_Vec(*[ext_dir[i] * 2.0 * half for i in range(3)])).Shape()


class Section:
    def __init__(self, spec, diag):
        self.kind = str(spec.get("kind", "full"))
        self.points = [vec3(p) for p in spec.get("points") or []]
        if len(self.points) < 2:
            raise RuntimeError("A section line needs at least two points.")
        self.pn = unit(spec.get("pnormal") or [0, 0, 1])
        self.L = max(diag * 4.0, 10.0)
        self.keep = None
        d1 = unit(add(self.points[1], self.points[0], -1.0))
        self.d1 = d1
        a = spec.get("keep")
        self.a = unit(a) if a else unit(cross(self.pn, d1))
        if self.kind in ("full", "half"):
            self.cutter_planes = [(self.points[0] if self.kind == "full" else self.points[1], self.a)]

    def _plane_basis(self):
        return self.d1, self.pn

    def removal(self):
        L = self.L
        a = self.a
        o = self.points[1] if self.kind == "half" else self.points[0]
        if self.kind == "full":
            u = self.d1
            v = self.pn
            return box_in_frame(o, u, v, [-a[0], -a[1], -a[2]], -L, L, -L, L, 0.0, L)
        if self.kind == "half":
            u = unit(add(self.points[0], self.points[1], -1.0))
            v = self.pn
            return box_in_frame(o, u, v, [-a[0], -a[1], -a[2]], 0.0, L, -L, L, 0.0, L)
        pts = self.points
        d_first = unit(add(pts[1], pts[0], -1.0))
        d_last = unit(add(pts[-1], pts[-2], -1.0))
        side = [-a[0], -a[1], -a[2]]
        poly = [add(pts[0], d_first, -L)] + pts + [add(pts[-1], d_last, L)]
        far = [add(poly[-1], side, L), add(poly[0], side, L)]
        return prism_of_polygon(poly + far, self.pn, L)

    def cutter_faces(self):
        L = self.L
        if self.kind in ("full", "half"):
            o = self.points[0] if self.kind == "full" else self.points[1]
            pln = gp_Pln(gp_Ax3(gp_Pnt(*o), gp_Dir(*self.a), gp_Dir(*self.d1)))
            if self.kind == "full":
                f = BRepBuilderAPI_MakeFace(pln, -L, L, -L, L).Face()
            else:
                u = unit(add(self.points[0], self.points[1], -1.0))
                pln = gp_Pln(gp_Ax3(gp_Pnt(*o), gp_Dir(*self.a), gp_Dir(*u)))
                f = BRepBuilderAPI_MakeFace(pln, 0.0, L, -L, L).Face()
            return [f], True
        pts = self.points
        d_first = unit(add(pts[1], pts[0], -1.0))
        d_last = unit(add(pts[-1], pts[-2], -1.0))
        poly = [add(pts[0], d_first, -L)] + pts + [add(pts[-1], d_last, L)]
        sheet = poly_wire_faces(poly, self.pn, -L, L)
        faces = []
        ex = TopExp_Explorer(sheet, TopAbs_FACE)
        while ex.More():
            faces.append(TopoDS.Face(ex.Current()))
            ex.Next()
        return faces, False


def wires_of_edges(edges, tol):
    from OCP.collections import HSequence_TopoDS_Shape

    src = HSequence_TopoDS_Shape()
    for e in edges:
        src.Append(e)
    out = HSequence_TopoDS_Shape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(src, tol, False, out)
    res = []
    for i in range(1, out.Length() + 1):
        res.append(TopoDS.Wire(out.Value(i)))
    return res


def section_faces(shape, section, diag):
    from OCP.TopAbs import TopAbs_SOLID

    solids = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        solids.append(ex.Current())
        ex.Next()
    if len(solids) < 2:
        return section_faces_one(shape, section, diag)
    found = []
    for s in solids:
        found.extend(section_faces_one(s, section, diag))
    return found


def section_faces_one(shape, section, diag):
    tol = max(diag * 1e-7, 1e-6)
    found = []
    faces, single = section.cutter_faces()
    for cf in faces:
        try:
            sec = BRepAlgoAPI_Section(shape, cf)
            sec.Build()
            if not sec.IsDone():
                continue
        except Exception:
            continue
        edges = edges_of(sec.Shape())
        if not edges:
            continue
        pl = cutter_plane(cf)
        if pl is None:
            continue
        wires = wires_of_edges(edges, tol)
        if not wires:
            continue
        mk = BRepBuilderAPI_MakeFace(pl, wires[0], True)
        for w in wires[1:]:
            mk.Add(w)
        fixer = ShapeFix_Face(mk.Face())
        fixer.SetPrecision(tol)
        fixer.FixOrientation()
        fixer.Perform()
        res = fixer.Result()
        ex = TopExp_Explorer(res, TopAbs_FACE)
        while ex.More():
            found.append(TopoDS.Face(ex.Current()))
            ex.Next()
    return found


def cutter_plane(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    ad = BRepAdaptor_Surface(face)
    if ad.GetType() != GeomAbs_Plane:
        return None
    return ad.Plane()


def face_loops(moved):
    from OCP.BRepTools import BRepTools

    ow = BRepTools.OuterWire_s(TopoDS.Face(moved))
    loops = []
    from OCP.TopAbs import TopAbs_WIRE

    ex = TopExp_Explorer(moved, TopAbs_WIRE)
    while ex.More():
        w = TopoDS.Wire(ex.Current())
        ex.Next()
        recs = []
        wx = TopExp_Explorer(w, TopAbs_EDGE)
        while wx.More():
            recs.append(edge_record(TopoDS.Edge(wx.Current())))
            wx.Next()
        loops.append((w.IsSame(ow), recs))
    outer_loop = [r for isouter, r in loops if isouter]
    holes = [r for isouter, r in loops if not isouter]
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(moved, props)
    return {"outer": outer_loop[0] if outer_loop else [], "holes": holes, "area": props.Mass()}


def normal_dot(face, view_n):
    cp = cutter_plane(face)
    if cp is None:
        return 0.0
    d = cp.Axis().Direction()
    return abs(d.X() * view_n[0] + d.Y() * view_n[1] + d.Z() * view_n[2])


def apply_aligned(kept, section, diag):
    pts = section.points
    if len(pts) != 3:
        raise RuntimeError("An aligned section line needs exactly three points.")
    d1 = unit(add(pts[1], pts[0], -1.0))
    d2 = unit(add(pts[2], pts[1], -1.0))
    h = unit(add(d2, d1, -1.0)) if abs(dot(d1, d2) - 1.0) > 1e-9 else d2
    perp = unit(cross(section.pn, h))
    L = section.L
    ref = dot([-d1[0], -d1[1], -d1[2]], perp)
    sgn = 1.0 if ref >= 0.0 else -1.0
    region1 = box_in_frame(pts[1], perp, section.pn, h, 0.0 if sgn > 0 else -L, L if sgn > 0 else 0.0, -L, L, -L, L)
    region2 = box_in_frame(pts[1], perp, section.pn, h, -L if sgn > 0 else 0.0, 0.0 if sgn > 0 else L, -L, L, -L, L)
    part1 = boolean(BRepAlgoAPI_Common, [kept], [region1]).Shape()
    part2 = boolean(BRepAlgoAPI_Common, [kept], [region2]).Shape()
    ang = math.atan2(dot(cross(d2, d1), section.pn), dot(d2, d1))
    rot = BRepBuilderAPI_Transform(part2, trsf_rotate(pts[1], section.pn, ang), False).Shape()
    fused = boolean(BRepAlgoAPI_Fuse, [part1], [rot]).Shape()
    try:
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

        uni = ShapeUpgrade_UnifySameDomain(fused, True, True, True)
        uni.Build()
        fused = uni.Shape()
    except Exception:
        pass
    return fused


def clean_edge(edge):
    c = BRepAdaptor_Curve(edge)
    f, l = c.FirstParameter(), c.LastParameter()
    ty = c.GetType()
    if ty == GeomAbs_Line:
        return BRepBuilderAPI_MakeEdge(c.Line(), f, l).Edge()
    if ty == GeomAbs_Circle:
        return BRepBuilderAPI_MakeEdge(c.Circle(), f, l).Edge()
    if ty == GeomAbs_Ellipse:
        return BRepBuilderAPI_MakeEdge(c.Ellipse(), f, l).Edge()
    if ty == GeomAbs_BSplineCurve:
        return BRepBuilderAPI_MakeEdge(c.BSpline(), f, l).Edge()
    if ty == GeomAbs_BezierCurve:
        return BRepBuilderAPI_MakeEdge(c.Bezier(), f, l).Edge()
    pts = [curve_pt(c, f + (l - f) * i / 24.0) for i in range(25)]
    mk = BRepBuilderAPI_MakePolygon()
    for q in pts:
        mk.Add(gp_Pnt(*q))
    return mk.Wire()


def apply_clip_face(pieces, face):
    out = []
    if not pieces:
        return out
    cleaned = []
    for row in pieces:
        try:
            cleaned.append((clean_edge(row[0]),) + tuple(row[1:]))
        except Exception:
            continue
    pieces = cleaned
    maker = boolean(BRepAlgoAPI_Common, [e for e, *_ in pieces], [face])
    for row in pieces:
        e = row[0]
        if maker.IsDeleted(e):
            continue
        mods = list(maker.Modified(e))
        if mods:
            for m in mods:
                for sub in edges_of(m):
                    out.append((sub, True) + tuple(row[1:]))
        else:
            out.append((e, False) + tuple(row[1:]))
    return out


def rect_face(x0, y0, x1, y1):
    mk = BRepBuilderAPI_MakePolygon()
    for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        mk.Add(gp_Pnt(p[0], p[1], 0.0))
    mk.Close()
    return BRepBuilderAPI_MakeFace(mk.Wire(), True).Face()


def circle_face(cx, cy, r):
    from OCP.gp import gp_Circ

    edge = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(cx, cy, 0.0), gp_Dir(0, 0, 1)), r)).Edge()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire

    return BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(edge).Wire(), True).Face()


def poly_face(points):
    mk = BRepBuilderAPI_MakePolygon()
    for p in points:
        mk.Add(gp_Pnt(float(p[0]), float(p[1]), 0.0))
    mk.Close()
    return BRepBuilderAPI_MakeFace(mk.Wire(), True).Face()


def view_build(p):
    t_start = time.perf_counter()
    items = p.get("items") or []
    if not items:
        raise RuntimeError("The view has nothing to show.")
    normal = vec3(p.get("normal") or [0, -1, 0])
    up = vec3(p.get("up") or [0, 0, 1])
    mode = str(p.get("mode", "exact"))
    shapes = load_items(items)
    whole = make_compound(shapes)
    bb = bbox(whole)
    if bb is None:
        raise RuntimeError("The model has no extent.")
    diag = math.dist(bb[:3], bb[3:])
    centre = [(bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0]
    origin = vec3(p["origin"]) if p.get("origin") else centre
    x, y, n = frame_of(normal, up)
    stats_out = {"faces": sum(store.count_of(s, TopAbs_FACE) for s in shapes)}
    if mode == "auto":
        mode = "draft" if stats_out["faces"] > int(p.get("cutover", 1500)) else "exact"
    section = None
    target = whole
    secfaces = []
    sec_ms = 0.0
    sec_spec = p.get("section")
    if sec_spec:
        t_sec = time.perf_counter()
        section = Section(sec_spec, diag)
        rem = section.removal()
        if section.kind == "aligned":
            kept = boolean(BRepAlgoAPI_Cut, [whole], [rem]).Shape()
            secfaces = section_faces(whole, section, diag)
            target = apply_aligned(kept, section, diag)
        else:
            target = boolean(BRepAlgoAPI_Cut, [whole], [rem]).Shape()
            secfaces = section_faces(whole, section, diag)
        sec_ms = (time.perf_counter() - t_sec) * 1000.0
    pieces, hstats = hlr_pieces(target, section_view_normal(normal, section), up, origin, mode, float(p.get("deflection", 0.0)))
    view_t = view_transform(origin, n, up)
    attr_ms = 0.0
    meta = {}
    if p.get("attribute", True) and mode == "exact" and not (section is not None and section.kind == "aligned"):
        t_a = time.perf_counter()
        attr = Attributor(shapes)
        meta = attribute(pieces, hstats, attr, view_t, diag)
        attr_ms = (time.perf_counter() - t_a) * 1000.0
    rows = []
    for cls, lst in pieces.items():
        for k, (e2, e3) in enumerate(lst):
            m = meta.get((cls, k))
            rows.append([e2, False, cls, m])
    vfaces = []
    for f in secfaces:
        if normal_dot(f, n) < 0.05:
            continue
        vfaces.append(TopoDS.Face(BRepBuilderAPI_Transform(f, view_t, False).Shape()))
    clip = p.get("clip")
    breaks = p.get("breaks") or []
    extra = []
    cbox = None
    if clip:
        face = None
        if clip.get("circle"):
            c = clip["circle"]
            face = circle_face(float(c["c"][0]), float(c["c"][1]), float(c["r"]))
            cbox = [c["c"][0] - c["r"], c["c"][1] - c["r"], c["c"][0] + c["r"], c["c"][1] + c["r"]]
        elif clip.get("polygon"):
            face = poly_face(clip["polygon"])
            xs = [q[0] for q in clip["polygon"]]
            ys = [q[1] for q in clip["polygon"]]
            cbox = [min(xs), min(ys), max(xs), max(ys)]
        elif clip.get("rect"):
            r = clip["rect"]
            face = rect_face(r[0], r[1], r[2], r[3])
            cbox = [min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])]
        if face is not None:
            clipped = apply_clip_face([(r[0], r[2], r[3]) for r in rows], face)
            rows = [[c[0], bool(c[1]), c[2], c[3]] for c in clipped]
            vfaces = clip_faces(vfaces, face)
    shift_info = []
    if breaks:
        rows, vfaces, extra, shift_info = apply_breaks(rows, vfaces, breaks, bb, diag)
    face_recs = []
    for f in vfaces:
        loops = face_loops(f)
        if loops["area"] > 1e-9:
            face_recs.append(loops)
    classes = {c: [] for c in CLASSES}
    count = 0
    for e2, clipped, cls, m in rows:
        try:
            rec = edge_record(e2)
        except Exception:
            continue
        if m:
            rec["s"] = m["s"]
            if not clipped and m.get("p"):
                rec["p"] = m["p"]
        classes[cls].append(rec)
        count += 1
        if count > MAX_PIECES:
            raise RuntimeError("The view has too many edges to keep.")
    lo = [1e300, 1e300]
    hi = [-1e300, -1e300]
    for cls in ("sharp_v", "smooth_v", "outline_v", "sewn_v"):
        for rec in classes[cls]:
            grow(rec, lo, hi)
    for f in face_recs:
        for rec in f["outer"]:
            grow(rec, lo, hi)
    if lo[0] > hi[0]:
        for cls in CLASSES:
            for rec in classes[cls]:
                grow(rec, lo, hi)
    for rec in extra:
        grow(rec, lo, hi)
    if cbox and clip.get("circle"):
        lo = [min(lo[0], cbox[0]), min(lo[1], cbox[1])]
        hi = [max(hi[0], cbox[2]), max(hi[1], cbox[3])]
    bounds =[lo[0], lo[1], hi[0], hi[1]] if lo[0] <= hi[0] else [0.0, 0.0, 0.0, 0.0]
    return {
        "ok": True,
        "classes": classes,
        "faces": face_recs,
        "extra": extra,
        "bounds": bounds,
        "origin": origin,
        "frame": {"x": x, "y": y, "n": n},
        "model_bbox": bb,
        "counts": {c: len(v) for c, v in classes.items()},
        "stats": {"mode": mode, "hlr_ms": hstats.get("ms", 0.0), "attr_ms": attr_ms, "section_ms": sec_ms, "total_ms": (time.perf_counter() - t_start) * 1000.0, "faces": stats_out["faces"], "attributed": len(meta), "section_kind": section.kind if section else ""},
        "breaks": shift_info,
    }


def section_view_normal(normal, section):
    return normal


def grow(rec, lo, hi):
    t = rec["t"]
    pts = []
    if t == "line":
        pts = [rec["a"], rec["b"]]
    elif t in ("arc", "circle"):
        c, r = rec["c"], rec["r"]
        if t == "circle":
            pts = [[c[0] - r, c[1] - r], [c[0] + r, c[1] + r]]
        else:
            a0, a1 = rec["a0"], rec["a1"]
            sweep = (a1 - a0) % (2.0 * math.pi)
            if sweep == 0.0:
                sweep = 2.0 * math.pi
            n = max(8, int(sweep / 0.15))
            pts = [[c[0] + r * math.cos(a0 + sweep * i / n), c[1] + r * math.sin(a0 + sweep * i / n)] for i in range(n + 1)]
    elif t == "ellipse":
        c, m = rec["c"], rec["major"]
        a = math.hypot(m[0], m[1])
        pts = [[c[0] - a, c[1] - a], [c[0] + a, c[1] + a]]
    elif t == "spline":
        pts = rec["ctrl"]
    elif t == "poly":
        pts = rec["pts"]
    for q in pts:
        lo[0] = min(lo[0], q[0])
        lo[1] = min(lo[1], q[1])
        hi[0] = max(hi[0], q[0])
        hi[1] = max(hi[1], q[1])


def clip_faces(vfaces, face):
    out = []
    for f in vfaces:
        try:
            res = boolean(BRepAlgoAPI_Common, [f], [face]).Shape()
        except RuntimeError:
            continue
        ex = TopExp_Explorer(res, TopAbs_FACE)
        while ex.More():
            out.append(TopoDS.Face(ex.Current()))
            ex.Next()
    return out


def moved_edges(shape, v):
    if shape.IsNull():
        return shape
    out = BRepBuilderAPI_Transform(shape, trsf_translate(v), True).Shape()
    if shape.ShapeType() == TopAbs_EDGE:
        return TopoDS.Edge(out)
    if shape.ShapeType() == TopAbs_FACE:
        return TopoDS.Face(out)
    return out


def break_lines(axis, pos, cross_lo, cross_hi, style):
    out = []
    span = cross_hi - cross_lo
    for at in pos:
        if axis == "x":
            def pt(c, o=0.0, at=at):
                return [at + o, c]
        else:
            def pt(c, o=0.0, at=at):
                return [c, at + o]
        if style == "zigzag":
            amp = max(span * 0.03, 1e-6)
            mid = (cross_lo + cross_hi) / 2.0
            w = span * 0.08
            pts = [pt(cross_lo), pt(mid - w), pt(mid - w / 3.0, amp), pt(mid + w / 3.0, -amp), pt(mid + w), pt(cross_hi)]
            out.append({"t": "poly", "pts": pts, "k": "break"})
        else:
            out.append({"t": "line", "a": pt(cross_lo), "b": pt(cross_hi), "k": "break"})
    return out


def apply_breaks(rows, vfaces, breaks, bb, diag):
    extra = []
    info = []
    big = diag * 10.0 + 1000.0
    for axis in ("x", "y"):
        mine = sorted([b for b in breaks if b.get("axis") == axis], key=lambda b: float(b["lo"]))
        if not mine:
            continue
        cb = bbox(make_compound([r[0] for r in rows])) or [0, 0, 0, 0, 0, 0]
        c_lo, c_hi = (cb[1], cb[4]) if axis == "x" else (cb[0], cb[3])
        edges_pos = [-big] + [v for b in mine for v in (float(b["lo"]), float(b["hi"]))] + [big]
        shift = 0.0
        new_rows = []
        new_faces = []
        line_pos = []
        for k in range(len(mine) + 1):
            r_lo, r_hi = edges_pos[2 * k], edges_pos[2 * k + 1]
            if axis == "x":
                reg = rect_face(r_lo, -big, r_hi, big)
                vec = [shift, 0.0, 0.0]
            else:
                reg = rect_face(-big, r_lo, big, r_hi)
                vec = [0.0, shift, 0.0]
            part = apply_clip_face([(r[0], r[2], r[3], r[1]) for r in rows], reg)
            for sub in part:
                moved = moved_edges(sub[0], vec) if shift else sub[0]
                new_rows.append([moved, bool(sub[1]) or bool(sub[4]), sub[2], sub[3]])
            for f in clip_faces(vfaces, reg):
                new_faces.append(moved_edges(f, vec) if shift else f)
            if k < len(mine):
                b = mine[k]
                width = float(b["hi"]) - float(b["lo"])
                gap = max(float(b.get("gap", 0.0)), 0.0)
                line_pos.append((float(b["lo"]) + shift, float(b["lo"]) + shift + gap, b.get("style", "zigzag")))
                info.append({"axis": axis, "lo": float(b["lo"]), "hi": float(b["hi"]), "gap": gap, "shift_after": shift - (width - gap)})
                shift -= width - gap
        rows = new_rows
        vfaces = new_faces
        for a, bpos, style in line_pos:
            extra.extend(break_lines(axis, [a, bpos], c_lo, c_hi, style))
    return rows, vfaces, extra, info


METHODS = {"view_build": view_build}
