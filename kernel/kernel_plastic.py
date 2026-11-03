import math

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.LocOpe import LocOpe_DPrism
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Lin, gp_Pnt, gp_Trsf, gp_Vec

import kernel_feat as feat
import kernel_sheet as sheet
import kernel_store as store
from kernel_sheet import add, cross, dot, mul, norm, num, sub, unit

MAX_SAMPLES = 60000
MAX_SPHERE = 6000
MAX_FILE_POINTS = 400000
BIG = 1.0e9
RAY_EPS = 1.0e-3


def tup3(raw, name):
    try:
        v = tuple(float(c) for c in raw)
    except (TypeError, ValueError):
        raise RuntimeError("%s needs three numbers." % name)
    if len(v) != 3 or not all(math.isfinite(c) for c in v):
        raise RuntimeError("%s needs three finite numbers." % name)
    return v


def face_at(ident, index):
    maps = store.maps_of(ident)
    n = maps["faces"].Extent()
    try:
        i = int(index)
    except (TypeError, ValueError):
        raise RuntimeError("The face reference is not a face index.")
    if not 0 <= i < n:
        raise RuntimeError("The body has no face %s." % index)
    return TopoDS.Face(maps["faces"].FindKey(i + 1))


def plane_frame(face):
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() != GeomAbs_Plane:
        raise RuntimeError("The feature needs a planar face to stand on.")
    pl = ad.Plane()
    n = pl.Axis().Direction()
    nn = (n.X(), n.Y(), n.Z())
    if face.Orientation() == TopAbs_REVERSED:
        nn = (-nn[0], -nn[1], -nn[2])
    o = pl.Location()
    x = pl.XAxis().Direction()
    return (o.X(), o.Y(), o.Z()), nn, (x.X(), x.Y(), x.Z())


def project(point, origin, n):
    d = dot(sub(point, origin), n)
    return sub(point, mul(n, d))


def inside_face(face, pt, tol=1e-6):
    cl = BRepClass_FaceClassifier(face, gp_Pnt(*pt), tol)
    return cl.State() in (TopAbs_IN, TopAbs_ON)


def local_axes(n, hint):
    a = sub(hint, mul(n, dot(hint, n)))
    if norm(a) < 1e-6 * max(norm(hint), 1e-12):
        raise RuntimeError("The hook direction points along the face normal; give a direction that lies in the face.")
    a = unit(a)
    return a, unit(cross(n, a))


def polygon_prism(points, roles, vec, caps):
    edges = []
    k = len(points)
    for i in range(k):
        mk = BRepBuilderAPI_MakeEdge(gp_Pnt(*points[i]), gp_Pnt(*points[(i + 1) % k]))
        if not mk.IsDone():
            raise RuntimeError("The profile has a zero length side.")
        edges.append(mk.Edge())
    wm = BRepBuilderAPI_MakeWire()
    for e in edges:
        wm.Add(e)
    if not wm.IsDone():
        raise RuntimeError("The profile does not close.")
    fm = BRepBuilderAPI_MakeFace(wm.Wire(), True)
    if not fm.IsDone():
        raise RuntimeError("The profile does not make a face.")
    mk = BRepPrimAPI_MakePrism(fm.Face(), gp_Vec(*vec))
    if not mk.IsDone():
        raise RuntimeError("The feature could not be extruded.")
    labels = []
    fedges = store.build_maps(fm.Face())["edges"]
    for j in range(1, fedges.Extent() + 1):
        fe = TopoDS.Edge(fedges.FindKey(j))
        _t, _ad, a0, b0 = edge_info(fe)
        mid = mul(add(a0, b0), 0.5)
        for i in range(k):
            m2 = mul(add(points[i], points[(i + 1) % k]), 0.5)
            if roles[i] is not None and norm(sub(mid, m2)) < 1e-7:
                for g in mk.Generated(fe):
                    if g.ShapeType() == TopAbs_FACE:
                        labels.append((roles[i], TopoDS.Face(g)))
    first, last = mk.FirstShape(), mk.LastShape()
    if caps[0] and first.ShapeType() == TopAbs_FACE:
        labels.append((caps[0], TopoDS.Face(first)))
    if caps[1] and last.ShapeType() == TopAbs_FACE:
        labels.append((caps[1], TopoDS.Face(last)))
    return mk.Shape(), labels


def face_centre(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def tool_faces(tool):
    maps = store.build_maps(tool)
    return [TopoDS.Face(maps["faces"].FindKey(i)) for i in range(1, maps["faces"].Extent() + 1)]


def axis_distance(point, c, n):
    v = sub(point, c)
    return norm(sub(v, mul(n, dot(v, n))))


class PBuild(sheet.Build):
    def op(self, kind, tool, labels=None):
        maker = feat.run_boolean("fuse" if kind == "fuse" else "cut", self.cur, tool)
        self.take(maker, labels)

    def take(self, maker, labels=None):
        res = maker.Shape()
        feat.check_result(res, "plastic feature")
        rows = feat.history_rows(maker, self.cur, store.build_maps(self.cur), store.build_maps(res))
        self.rows = rows if self.rows is None else sheet.compose(self.rows, rows)
        for key in list(self.tracks):
            self.tracks[key] = sheet.advance(maker, self.tracks[key])
        for key, face in labels or []:
            self.tracks.setdefault(key, [])
            self.tracks[key] = self.tracks[key] + sheet.advance(maker, [face])
        self.cur = res

    def fillet(self, pick, radius, what):
        if radius is None or radius <= 1e-6:
            return False
        em = store.build_maps(self.cur)["edges"]
        mk = BRepFilletAPI_MakeFillet(self.cur)
        count = 0
        for i in range(1, em.Extent() + 1):
            e = TopoDS.Edge(em.FindKey(i))
            if pick(e):
                mk.Add(radius, e)
                count += 1
        if count == 0:
            self.warnings.append("The %s fillet found no edge to round." % what)
            return False
        try:
            mk.Build()
            if not mk.IsDone():
                raise RuntimeError("not done")
            self.take(mk)
        except Exception:
            self.warnings.append("The %s fillet of %.3g mm could not be made; the feature has a sharp base." % (what, radius))
            return False
        return True


def check_gain(build, kind):
    v = sheet.volume_of(build.cur)
    if kind == "add" and v <= build.v0 + 1e-9:
        raise RuntimeError("The feature adds no material; it may lie inside the body.")
    if kind == "cut" and v >= build.v0 - 1e-9:
        raise RuntimeError("The feature removes no material; it may miss the body.")


def edge_info(e):
    ad = BRepAdaptor_Curve(e)
    t = ad.GetType()
    p0 = ad.Value(ad.FirstParameter())
    p1 = ad.Value(ad.LastParameter())
    return t, ad, (p0.X(), p0.Y(), p0.Z()), (p1.X(), p1.Y(), p1.Z())


def on_plane(pt, origin, n, tol=1e-5):
    return abs(dot(sub(pt, origin), n)) <= tol


def pl_boss(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    face = face_at(base_id, p.get("face"))
    o, n, xd = plane_frame(face)
    c = project(tup3(p.get("point"), "point"), o, n)
    od = num(p, "outer_diameter", None, 1e-3)
    hole = num(p, "hole_diameter", 0.0, 0.0)
    h = num(p, "height", None, 1e-3)
    depth = num(p, "hole_depth", None, 0.0)
    depth = h if depth is None else min(depth, h)
    draft = math.radians(num(p, "draft", 0.0, 0.0, 15.0))
    fillet = num(p, "base_fillet", 0.0, 0.0)
    r1 = od / 2.0
    r2 = r1 - h * math.tan(draft)
    if r2 <= 1e-3:
        raise RuntimeError("The draft closes the boss before its top; reduce the draft or the height.")
    if hole >= od - 1e-6:
        raise RuntimeError("The hole is as wide as the boss; make the boss outer diameter larger.")
    if not inside_face(face, c):
        raise RuntimeError("The boss centre is not on the face.")
    for k in range(8):
        a = k * math.pi / 4.0
        q = add(c, add(mul(xd, r1 * math.cos(a)), mul(cross(n, xd), r1 * math.sin(a))))
        if not inside_face(face, q):
            raise RuntimeError("The boss base reaches past the edge of the face.")
    ax = gp_Ax2(gp_Pnt(*c), gp_Dir(*n), gp_Dir(*xd))
    if draft > 1e-9:
        tool = BRepPrimAPI_MakeCone(ax, r1, r2, h).Shape()
    else:
        tool = BRepPrimAPI_MakeCylinder(ax, r1, h).Shape()
    floor_z = h - depth
    if hole > 0.0 and depth > 1e-9:
        e = 1.0
        z0 = floor_z if floor_z > 1e-9 else -e
        hb = hole / 2.0 - (h - z0) * math.tan(draft) if draft > 1e-9 else hole / 2.0
        ht = hole / 2.0 + e * math.tan(draft)
        if hb <= 1e-3:
            raise RuntimeError("The draft closes the hole before its bottom; reduce the draft or the hole depth.")
        bax = gp_Ax2(gp_Pnt(*add(c, mul(n, z0))), gp_Dir(*n), gp_Dir(*xd))
        if draft > 1e-9:
            bore = BRepPrimAPI_MakeCone(bax, hb, ht, h - z0 + e).Shape()
        else:
            bore = BRepPrimAPI_MakeCylinder(bax, hole / 2.0, h - z0 + e).Shape()
        cut = BRepAlgoAPI_Cut(tool, bore)
        if not cut.IsDone():
            raise RuntimeError("The hole could not be cut in the boss.")
        tool = cut.Shape()
    labels = []
    for f in tool_faces(tool):
        ad = BRepAdaptor_Surface(f)
        ctr = face_centre(f)
        z = dot(sub(ctr, c), n)
        if ad.GetType() == GeomAbs_Plane:
            d = BRepAdaptor_Surface(f).Plane().Axis().Direction()
            nn = (d.X(), d.Y(), d.Z())
            if f.Orientation() == TopAbs_REVERSED:
                nn = mul(nn, -1.0)
            if dot(nn, n) > 0.9:
                labels.append(("top" if abs(z - h) < 1e-6 else "floor", f))
        elif ad.GetType() in (GeomAbs_Cylinder, GeomAbs_Cone):
            ref = ad.Cylinder().Radius() if ad.GetType() == GeomAbs_Cylinder else ad.Cone().RefRadius()
            cut_at = (hole / 2.0 + r2) / 2.0 if hole > 0 else 0.0
            labels.append(("side" if ref > cut_at else "bore", f))
    build = PBuild(base_id, base)
    build.op("fuse", tool, labels)
    check_gain(build, "add")
    if fillet > 0.0:
        def pick(e):
            t, ad, a, b = edge_info(e)
            if t != GeomAbs_Circle:
                return False
            ci = ad.Circle()
            cc = ci.Location()
            return abs(ci.Radius() - r1) < 1e-5 and on_plane(a, o, n) and axis_distance((cc.X(), cc.Y(), cc.Z()), c, n) < 1e-5

        build.fillet(pick, fillet, "boss base")
    return build.result([], {"kind": "plastic_boss", "outer_diameter": od, "hole_diameter": hole, "height": h, "top_diameter": 2.0 * r2})


def pl_rib(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    face = face_at(base_id, p.get("face"))
    o, n, xd = plane_frame(face)
    s = project(tup3(p.get("start"), "start"), o, n)
    e = project(tup3(p.get("end"), "end"), o, n)
    t = num(p, "thickness", None, 1e-3)
    h = num(p, "height", None, 1e-3)
    draft = math.radians(num(p, "draft", 0.0, 0.0, 15.0))
    fillet = num(p, "base_fillet", 0.0, 0.0)
    length = norm(sub(e, s))
    if length < 1e-3:
        raise RuntimeError("The rib start and end are the same point.")
    u = unit(sub(e, s))
    w = cross(n, u)
    t2 = t - 2.0 * h * math.tan(draft)
    if t2 <= 1e-3 or length - 2.0 * h * math.tan(draft) <= 1e-3:
        raise RuntimeError("The draft closes the rib before its top; reduce the draft or the height.")
    for q in (s, e, add(s, mul(w, t / 2.0)), add(s, mul(w, -t / 2.0)), add(e, mul(w, t / 2.0)), add(e, mul(w, -t / 2.0))):
        if not inside_face(face, q):
            raise RuntimeError("The rib base reaches past the edge of the face.")
    corners = [add(s, mul(w, -t / 2.0)), add(e, mul(w, -t / 2.0)), add(e, mul(w, t / 2.0)), add(s, mul(w, t / 2.0))]
    wm = BRepBuilderAPI_MakeWire()
    for i in range(4):
        wm.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*corners[i]), gp_Pnt(*corners[(i + 1) % 4])).Edge())
    base_face = BRepBuilderAPI_MakeFace(wm.Wire(), True).Face()
    tool = drafted_prism(base_face, h, draft, 1.0, o, n, False)
    labels = []
    for f in tool_faces(tool):
        ad = BRepAdaptor_Surface(f)
        if ad.GetType() != GeomAbs_Plane:
            continue
        d = ad.Plane().Axis().Direction()
        nn = (d.X(), d.Y(), d.Z())
        if f.Orientation() == TopAbs_REVERSED:
            nn = mul(nn, -1.0)
        comp = (dot(nn, u), dot(nn, w), dot(nn, n))
        k = max(range(3), key=lambda i: abs(comp[i]))
        if k == 2 and comp[2] > 0:
            labels.append(("top", f))
        elif k == 0:
            labels.append(("end:end" if comp[0] > 0 else "end:start", f))
        elif k == 1:
            labels.append(("side:r" if comp[1] > 0 else "side:l", f))
    build = PBuild(base_id, base)
    build.op("fuse", tool, labels)
    check_gain(build, "add")
    if fillet > 0.0:
        def pick(ed):
            ty, ad, a, b = edge_info(ed)
            if ty != GeomAbs_Line or not (on_plane(a, o, n) and on_plane(b, o, n)):
                return False
            d = unit(sub(b, a))
            if abs(abs(dot(d, u)) - 1.0) < 1e-6:
                return abs(abs(dot(sub(a, s), w)) - t / 2.0) < 1e-5 and -1e-5 <= dot(sub(a, s), u) <= length + 1e-5
            if abs(abs(dot(d, w)) - 1.0) < 1e-6:
                x = dot(sub(a, s), u)
                return (abs(x) < 1e-5 or abs(x - length) < 1e-5) and abs(dot(sub(a, s), w)) <= t / 2.0 + 1e-5
            return False

        build.fillet(pick, fillet, "rib base")
    return build.result([], {"kind": "plastic_rib", "thickness": t, "height": h, "length": length, "top_thickness": t2})


def pl_snap_hook(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    face = face_at(base_id, p.get("face"))
    o, n, xd = plane_frame(face)
    c = project(tup3(p.get("point"), "point"), o, n)
    a, w = local_axes(n, tup3(p.get("direction") or (1.0, 0.0, 0.0), "direction"))
    L = num(p, "beam_length", None, 1e-3)
    h = num(p, "root_thickness", None, 1e-3)
    ratio = num(p, "tip_ratio", 1.0, 0.1, 1.0)
    b = num(p, "width", None, 1e-3)
    y = num(p, "undercut", None, 1e-4)
    la = math.radians(num(p, "lead_angle", 30.0, 5.0, 80.0))
    ra = math.radians(num(p, "return_angle", 90.0, 20.0, 90.0))
    fillet = num(p, "root_fillet", 0.0, 0.0)
    ht = h * ratio
    k = (h - ht) / L
    dz_r = y / math.tan(ra)
    tl = math.tan(la)
    if tl <= k + 1e-9:
        raise RuntimeError("The lead angle is too shallow for the beam taper; increase it.")
    hl = (y + tl * dz_r) / (tl - k)
    if hl >= L * 0.8:
        raise RuntimeError("The hook is longer than the beam allows; reduce the undercut or raise the lead angle.")
    for q in (c, add(c, mul(w, b / 2.0)), add(c, mul(w, -b / 2.0)), add(c, mul(a, h)), add(c, mul(a, -h))):
        if not inside_face(face, q):
            raise RuntimeError("The snap hook base reaches past the edge of the face.")

    def xb(z):
        return h - k * z

    za = L - hl

    def pt(x, z):
        return add(add(c, mul(a, x)), mul(n, z))

    aa = (xb(za), za)
    cc = (aa[0] + y, za + dz_r)
    pts2 = [(0.0, 0.0), (h, 0.0), aa, cc, (ht, L), (0.0, L)]
    pts = [add(pt(*q), mul(w, -b / 2.0)) for q in pts2]
    roles = [None, "beam:front", "hook:return", "hook:lead", "tip", "beam:back"]
    tool, labels = polygon_prism(pts, roles, mul(w, b), ("beam:l", "beam:r"))
    build = PBuild(base_id, base)
    build.op("fuse", tool, labels)
    check_gain(build, "add")
    if fillet > 0.0:
        def pick(ed):
            ty, ad, p0, p1 = edge_info(ed)
            if ty != GeomAbs_Line or not (on_plane(p0, o, n) and on_plane(p1, o, n)):
                return False
            d = sub(p1, p0)
            if abs(abs(dot(unit(d), w)) - 1.0) > 1e-6 or abs(norm(d) - b) > 1e-5:
                return False
            x = dot(sub(p0, c), a)
            return abs(x) < 1e-5 or abs(x - h) < 1e-5

        build.fillet(pick, fillet, "snap hook root")
    return build.result([], {"kind": "snap_hook", "hook_length": hl, "tip_thickness": ht, "lead_angle": math.degrees(la)})


def inward_wire(face, wire, dist):
    if abs(dist) < 1e-9:
        return wire
    o, n, xd = plane_frame(face)
    base = BRepBuilderAPI_MakeFace(BRepAdaptor_Surface(face).Plane(), wire, True).Face()
    a0 = area_of(base)
    best = None
    for sgn in (1.0, -1.0):
        try:
            w = feat.offset_wire(wire, sgn * dist, False)
            fa = BRepBuilderAPI_MakeFace(BRepAdaptor_Surface(face).Plane(), w, True)
            if not fa.IsDone():
                continue
            ar = area_of(fa.Face())
        except Exception:
            continue
        if ar < a0 - 1e-9 and (best is None or ar > best[0]):
            best = (ar, w)
    if best is None:
        raise RuntimeError("The rim cannot be offset inward by %.3g mm; the face is too narrow or its outline too small." % dist)
    return best[1]


def area_of(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def drafted_prism(f, height, ang, direction, o, n, grow):
    if ang <= 1e-9:
        return BRepPrimAPI_MakePrism(f, gp_Vec(*mul(n, direction * height))).Shape()
    sgn = -1.0 if grow else 1.0
    sol = LocOpe_DPrism(f, height / math.cos(ang), sgn * ang).Shape()
    b = store.bbox_of(sol)
    mid = dot(sub(((b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0, (b[2] + b[5]) / 2.0), o), n)
    if mid * direction < 0:
        trsf = gp_Trsf()
        trsf.SetMirror(gp_Ax2(gp_Pnt(*o), gp_Dir(*n)))
        sol = BRepBuilderAPI_Transform(sol, trsf, True).Shape()
        if sheet.volume_of(sol) < 0:
            sol = sol.Reversed()
    return sol


def ring_tool(face, d1, d2, height, direction, draft_deg):
    o, n, xd = plane_frame(face)
    outer = BRepTools.OuterWire_s(face)
    w1 = inward_wire(face, outer, d1)
    w2 = inward_wire(face, outer, d2)
    plane = BRepAdaptor_Surface(face).Plane()
    fa = BRepBuilderAPI_MakeFace(plane, w1, True).Face()
    fb = BRepBuilderAPI_MakeFace(plane, w2, True).Face()
    if area_of(fb) >= area_of(fa) - 1e-9:
        raise RuntimeError("The ring is empty; the width must be above zero.")
    ang = math.radians(draft_deg)
    A = drafted_prism(fa, height, ang, direction, o, n, False)
    B = drafted_prism(fb, height, ang, direction, o, n, True)
    cut = BRepAlgoAPI_Cut(A, B)
    if not cut.IsDone():
        raise RuntimeError("The ring could not be formed.")
    tool = cut.Shape()
    wm = inward_wire(face, outer, (d1 + d2) / 2.0)
    fm = BRepBuilderAPI_MakeFace(plane, wm, True).Face()
    labels = []
    for f in tool_faces(tool):
        ad = BRepAdaptor_Surface(f)
        ctr = face_centre(f)
        if ad.GetType() == GeomAbs_Plane:
            d = ad.Plane().Axis().Direction()
            nn = (d.X(), d.Y(), d.Z())
            if f.Orientation() == TopAbs_REVERSED:
                nn = mul(nn, -1.0)
            if abs(dot(nn, n)) > 0.999:
                far = dot(sub(ctr, o), n)
                if abs(far) > height * 0.5:
                    labels.append((nn, f, "cap"))
                continue
        q = project(ctr, o, n)
        labels.append((None, f, "inner" if inside_face(fm, q, 1e-6) else "outer"))
    return tool, labels, area_of(fa) - area_of(fb)


def pl_lip(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    face = face_at(base_id, p.get("face"))
    width = num(p, "width", None, 1e-3)
    height = num(p, "height", None, 1e-3)
    offset = num(p, "offset", 0.0, 0.0)
    draft = num(p, "draft", 0.0, 0.0, 15.0)
    tool, found, ring_area = ring_tool(face, offset, offset + width, height, 1.0, draft)
    labels = []
    for nn, f, role in found:
        labels.append(("top" if role == "cap" else role, f))
    build = PBuild(base_id, base)
    build.op("fuse", tool, labels)
    check_gain(build, "add")
    return build.result([], {"kind": "plastic_lip", "width": width, "height": height, "ring_area": ring_area})


def pl_groove(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    face = face_at(base_id, p.get("face"))
    width = num(p, "width", None, 1e-3)
    depth = num(p, "depth", None, 1e-3)
    offset = num(p, "offset", 0.0, 0.0)
    draft = num(p, "draft", 0.0, 0.0, 15.0)
    tool, found, ring_area = ring_tool(face, offset, offset + width, depth, -1.0, draft)
    labels = []
    for nn, f, role in found:
        labels.append(("floor" if role == "cap" else role, f))
    build = PBuild(base_id, base)
    build.op("cut", tool, labels)
    check_gain(build, "cut")
    return build.result([], {"kind": "plastic_groove", "width": width, "depth": depth, "ring_area": ring_area})


def read_f4(path, suffix, cols=3):
    full = store.absolute_path(path, (suffix,), exists=True)
    arr = np.fromfile(full, dtype="<f4")
    if arr.size % cols:
        raise RuntimeError("The sample file has the wrong size.")
    arr = arr.reshape(-1, cols)
    if len(arr) > MAX_FILE_POINTS:
        raise RuntimeError("The sample file holds too many points.")
    return arr.astype(np.float64)


def face_normal(face, u, v):
    gf = BRepGProp_Face(face)
    pnt = gp_Pnt()
    vec = gp_Vec()
    gf.Normal(u, v, pnt, vec)
    m = vec.Magnitude()
    if m < 1e-14:
        return None
    return (pnt.X(), pnt.Y(), pnt.Z()), (vec.X() / m, vec.Y() / m, vec.Z() / m)


def boundary_segments(face):
    segs = []
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        ad = BRepAdaptor_Curve(TopoDS.Edge(ex.Current()))
        f, l = ad.FirstParameter(), ad.LastParameter()
        k = 1 if ad.GetType() == GeomAbs_Line else 48
        prev = ad.Value(f)
        for i in range(1, k + 1):
            cur = ad.Value(f + (l - f) * i / k)
            segs.append((prev.X(), prev.Y(), prev.Z(), cur.X(), cur.Y(), cur.Z()))
            prev = cur
        ex.Next()
    arr = np.asarray(segs, dtype=np.float64).reshape(-1, 6)
    return arr[:, :3], arr[:, 3:]


def boundary_distance(points, segs):
    a, b = segs
    ab = b - a
    ll = np.maximum((ab * ab).sum(1), 1e-18)
    out = np.empty(len(points))
    for i in range(0, len(points), 256):
        p = points[i : i + 256, None, :]
        t = np.clip(((p - a) * ab).sum(2) / ll, 0.0, 1.0)
        q = a + t[..., None] * ab
        out[i : i + 256] = np.sqrt(((p - q) ** 2).sum(2)).min(axis=1)
    return out


def sample_faces(ident, total, margin=0.0):
    maps = store.maps_of(ident)
    faces = [TopoDS.Face(maps["faces"].FindKey(i)) for i in range(1, maps["faces"].Extent() + 1)]
    areas = [area_of(f) for f in faces]
    whole = sum(areas) or 1.0
    pts, nrm, owner = [], [], []
    for idx, (f, ar) in enumerate(zip(faces, areas)):
        want = max(4, int(round(total * ar / whole)))
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        m = max(2, int(math.ceil(math.sqrt(want * 1.6))))
        cands = []
        for i in range(m):
            for j in range(m):
                u = u0 + (u1 - u0) * (i + 0.5) / m
                v = v0 + (v1 - v0) * (j + 0.5) / m
                got = face_normal(f, u, v)
                if got is None:
                    continue
                pt, nv = got
                if not inside_face(f, pt, 1e-7):
                    continue
                cands.append((pt, nv))
        if margin > 0.0 and cands:
            segs = boundary_segments(f)
            dist = boundary_distance(np.asarray([c[0] for c in cands]), segs)
            keep = [c for c, d in zip(cands, dist) if d >= margin]
            if not keep:
                fine = []
                for i in range(24):
                    for j in range(24):
                        got = face_normal(f, u0 + (u1 - u0) * (i + 0.5) / 24, v0 + (v1 - v0) * (j + 0.5) / 24)
                        if got is not None and inside_face(f, got[0], 1e-7):
                            fine.append(got)
                pool = fine or cands
                fd = boundary_distance(np.asarray([c[0] for c in pool]), segs)
                keep = [pool[int(np.argmax(fd))]]
            cands = keep
        for pt, nv in cands:
            pts.append(pt)
            nrm.append(nv)
            owner.append(idx)
    return np.asarray(pts, dtype=np.float64).reshape(-1, 3), np.asarray(nrm, dtype=np.float64).reshape(-1, 3), np.asarray(owner, dtype=np.int64)


def ray_thickness(shape, pts, nrm):
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-7)
    out = np.full(len(pts), np.nan)
    for i in range(len(pts)):
        d = -nrm[i]
        o = pts[i] + d * RAY_EPS
        inter.Perform(gp_Lin(gp_Pnt(*o), gp_Dir(*d)), 0.0, BIG)
        if not inter.IsDone():
            continue
        best = None
        for k in range(1, inter.NbPnt() + 1):
            t = inter.WParameter(k)
            if t > RAY_EPS and (best is None or t < best):
                best = t
        if best is not None:
            out[i] = best + RAY_EPS
    return out


def sphere_thickness(shape, pts, nrm, ray, diag):
    out = np.full(len(pts), np.nan)
    for i in range(len(pts)):
        t0 = ray[i]
        if not math.isfinite(t0):
            continue
        p = pts[i]
        nv = nrm[i]
        r = t0 / 2.0
        for _ in range(10):
            ctr = p - nv * r
            vm = BRepBuilderAPI_MakeVertex(gp_Pnt(*ctr)).Vertex()
            ds = BRepExtrema_DistShapeShape(vm, shape)
            if not ds.IsDone() or ds.NbSolution() < 1:
                break
            dist = ds.Value()
            if dist >= r * (1.0 - 1e-4):
                break
            q = ds.PointOnShape2(1)
            v = np.array([q.X(), q.Y(), q.Z()]) - p
            nd = float(np.dot(nv, v))
            if nd >= -1e-9:
                break
            rn = -float(np.dot(v, v)) / (2.0 * nd)
            if not math.isfinite(rn) or rn <= 1e-6 or rn >= r:
                break
            if r - rn < 1e-6 * diag:
                r = rn
                break
            r = rn
        out[i] = 2.0 * r
    return out


def pl_wall(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    method = str(p.get("method") or "ray")
    if method not in ("ray", "sphere"):
        raise RuntimeError("The wall thickness method is ray or sphere.")
    box = store.bbox_of(shape) or [0, 0, 0, 1, 1, 1]
    diag = math.dist(box[:3], box[3:])
    owner = None
    if p.get("points_path"):
        pts = read_f4(p["points_path"], ".pts")
        nrm = read_f4(p["normals_path"], ".nrm")
        if len(pts) != len(nrm):
            raise RuntimeError("The points and normals differ in count.")
        if len(pts) > MAX_SAMPLES:
            raise RuntimeError("Too many points for one wall thickness call (limit %d)." % MAX_SAMPLES)
    else:
        total = int(num(p, "samples", 2000, 8, MAX_SAMPLES))
        if method == "sphere":
            total = min(total, MAX_SPHERE)
        pts, nrm, owner = sample_faces(ident, total, num(p, "margin", 0.0, 0.0))
    if method == "sphere" and len(pts) > MAX_SPHERE:
        raise RuntimeError("The sphere method takes at most %d points; use the ray method or fewer points." % MAX_SPHERE)
    ln = np.linalg.norm(nrm, axis=1)
    ln[ln < 1e-12] = 1.0
    nrm = nrm / ln[:, None]
    ray = ray_thickness(shape, pts, nrm)
    val = ray if method == "ray" else sphere_thickness(shape, pts, nrm, ray, diag)
    out = {"method": method, "count": int(len(pts)), "misses": int(np.count_nonzero(~np.isfinite(val)))}
    if p.get("out_path"):
        path = store.absolute_path(p["out_path"], (".wal",))
        np.ascontiguousarray(val, dtype="<f4").tofile(path)
        out["path"] = path
    else:
        out["thickness"] = [None if not math.isfinite(x) else float(x) for x in val]
        out["ray"] = [None if not math.isfinite(x) else float(x) for x in ray]
        out["points"] = pts.tolist()
        out["normals"] = nrm.tolist()
        out["faces"] = owner.tolist() if owner is not None else []
    return out


def kind_name(ad):
    t = ad.GetType()
    return {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone"}.get(t, "other")


def pl_inspect(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    maps = store.maps_of(ident)
    pull = unit(tup3(p.get("pull") or (0.0, 0.0, 1.0), "pull"))
    grid = int(num(p, "grid", 7, 3, 25))
    faces = []
    nfaces = maps["faces"].Extent()
    if nfaces > 4000:
        raise RuntimeError("The body has too many faces for the plastic checks (limit 4000).")
    for i in range(1, nfaces + 1):
        f = TopoDS.Face(maps["faces"].FindKey(i))
        ad = BRepAdaptor_Surface(f)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        angles = []
        for a in range(grid):
            for b in range(grid):
                u = u0 + (u1 - u0) * (a + 0.5) / grid
                v = v0 + (v1 - v0) * (b + 0.5) / grid
                got = face_normal(f, u, v)
                if got is None:
                    continue
                pt, nv = got
                if not inside_face(f, pt, 1e-7):
                    continue
                s = max(-1.0, min(1.0, dot(nv, pull)))
                angles.append(math.degrees(math.asin(s)))
        row = {"face": i - 1, "kind": kind_name(ad), "area": area_of(f), "centre": list(face_centre(f)), "samples": len(angles)}
        if angles:
            row["draft_min"], row["draft_max"] = min(angles), max(angles)
            row["draft_abs_min"] = min(abs(x) for x in angles)
        if ad.GetType() == GeomAbs_Plane:
            _o, nn, _x = plane_frame(f)
            row["normal"] = list(nn)
        if ad.GetType() == GeomAbs_Cylinder:
            cyl = ad.Cylinder()
            row["radius"] = cyl.Radius()
            ax = cyl.Axis()
            row["axis"] = [ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()]
            loc = ax.Location()
            row["axis_point"] = [loc.X(), loc.Y(), loc.Z()]
            row["span_deg"] = math.degrees(u1 - u0)
            mid = face_normal(f, (u0 + u1) / 2.0, (v0 + v1) / 2.0)
            if mid is not None:
                pt, nv = mid
                rel = sub(pt, (loc.X(), loc.Y(), loc.Z()))
                radial = sub(rel, mul((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()), dot(rel, (ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()))))
                row["concave"] = bool(dot(nv, radial) < 0.0)
        faces.append(row)
    corners = []
    anc = feat.adjacency(ident)
    for ei, fl in enumerate(anc):
        if len(fl) != 2:
            continue
        e = TopoDS.Edge(maps["edges"].FindKey(ei + 1))
        ty, ad, p0, p1 = edge_info(e)
        if ty != GeomAbs_Line:
            continue
        f1 = TopoDS.Face(maps["faces"].FindKey(fl[0] + 1))
        f2 = TopoDS.Face(maps["faces"].FindKey(fl[1] + 1))
        if BRepAdaptor_Surface(f1).GetType() != GeomAbs_Plane or BRepAdaptor_Surface(f2).GetType() != GeomAbs_Plane:
            continue
        o1, n1, _ = plane_frame(f1)
        o2, n2, _ = plane_frame(f2)
        if abs(dot(n1, n2)) > 0.9999:
            continue
        mid = mul(add(p0, p1), 0.5)
        t = unit(sub(p1, p0))
        d = cross(n2, t)
        step = 1e-3 * max(1.0, norm(sub(p1, p0)))
        pick = None
        for sgn in (1.0, -1.0):
            q = add(mid, mul(d, sgn * step))
            if inside_face(f2, q, 1e-5):
                pick = mul(d, sgn)
                break
        if pick is None:
            continue
        if dot(pick, n1) > 1e-6:
            corners.append({"edge": ei, "faces": [fl[0], fl[1]], "mid": list(mid), "length": norm(sub(p1, p0)), "angle": math.degrees(math.acos(max(-1.0, min(1.0, -dot(n1, n2)))))})
    summary = store.summarize(shape)
    vol = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vol)
    return {"faces": faces, "sharp_edges": corners, "adjacency": anc, "volume": vol.Mass(), "area": sum(r["area"] for r in faces), "bbox": summary["bbox"], "solids": summary["solids"]}


METHODS = {"pl_boss": pl_boss, "pl_rib": pl_rib, "pl_snap_hook": pl_snap_hook, "pl_lip": pl_lip, "pl_groove": pl_groove, "pl_wall": pl_wall, "pl_inspect": pl_inspect}
