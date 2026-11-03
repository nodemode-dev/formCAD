import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Vertex
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as AncestorMap
from OCP.gp import gp_Pnt, gp_Pnt2d, gp_Vec

import kernel_store as store

TAU = 2.0 * math.pi
KIND_NAMES = {GeomAbs_Cone: "cone", GeomAbs_Sphere: "sphere", GeomAbs_Torus: "torus"}


class UnfoldError(RuntimeError):
    pass


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n == 0:
        raise UnfoldError("A zero length direction was met while unfolding.")
    return (a[0] / n, a[1] / n, a[2] / n)


def pt(p):
    return (p.X(), p.Y(), p.Z())


def wrap(a):
    return (a + math.pi) % TAU - math.pi


class Face:
    def __init__(self, idx, face):
        self.idx = idx
        self.face = face
        ad = BRepAdaptor_Surface(face)
        self.ad = ad
        kind = ad.GetType()
        self.reversed = face.Orientation() == TopAbs_REVERSED
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        self.area = props.Mass()
        self.centroid = pt(props.CentreOfMass())
        self.kind = "plane" if kind == GeomAbs_Plane else "cylinder" if kind == GeomAbs_Cylinder else KIND_NAMES.get(kind, "freeform")
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
        self.uv = (umin, umax, vmin, vmax)
        if self.kind == "plane":
            pos = ad.Plane().Position()
            n = pt(pos.Direction())
            self.n = mul(n, -1.0) if self.reversed else n
            self.o = self.centroid
            self.ex = pt(pos.XDirection())
            self.ey = cross(self.n, self.ex)
        elif self.kind == "cylinder":
            cyl = ad.Cylinder()
            ax = cyl.Axis()
            self.c = pt(ax.Location())
            self.a = unit(pt(ax.Direction()))
            self.R = cyl.Radius()
            um, vm = (umin + umax) / 2.0, (vmin + vmax) / 2.0
            self.span = umax - umin
            p = pt(ad.Value(um, vm))
            d = sub(p, self.c)
            radial = unit(sub(d, mul(self.a, dot(d, self.a))))
            pp, vu, vv = gp_Pnt(), gp_Vec(), gp_Vec()
            ad.D1(um, vm, pp, vu, vv)
            nrm = unit(cross((vu.X(), vu.Y(), vu.Z()), (vv.X(), vv.Y(), vv.Z())))
            if self.reversed:
                nrm = mul(nrm, -1.0)
            self.sg = 1.0 if dot(nrm, radial) > 0 else -1.0
            self.u0 = radial
            self.v0 = cross(self.a, radial)
            ts = [dot(sub(pt(ad.Value(um, v)), self.c), self.a) for v in (vmin, vmax)]
            self.t0, self.t1 = min(ts), max(ts)

    def normal_at(self, p):
        if self.kind == "plane":
            return self.n
        d = sub(p, self.c)
        radial = unit(sub(d, mul(self.a, dot(d, self.a))))
        return mul(radial, self.sg)

    def surface_point(self, ang, t):
        r = add(mul(self.u0, math.cos(ang)), mul(self.v0, math.sin(ang)))
        return add(add(self.c, mul(r, self.R)), mul(self.a, t))


class Dev:
    def __init__(self, f, scale=1.0):
        self.f = f
        self.scale = scale

    def __call__(self, p):
        f = self.f
        if f.kind == "plane":
            d = sub(p, f.o)
            return (dot(d, f.ex), dot(d, f.ey))
        d = sub(p, f.c)
        ang = math.atan2(dot(d, f.v0), dot(d, f.u0))
        return (f.sg * f.R * self.scale * ang, dot(d, f.a))


class Rigid:
    def __init__(self, psi=0.0, tx=0.0, ty=0.0):
        self.psi, self.tx, self.ty = psi, tx, ty
        self.c, self.s = math.cos(psi), math.sin(psi)

    def __call__(self, q):
        return (self.c * q[0] - self.s * q[1] + self.tx, self.s * q[0] + self.c * q[1] + self.ty)

    def rot(self, q):
        return (self.c * q[0] - self.s * q[1], self.s * q[0] + self.c * q[1])


def surface_normal(f, p):
    sa = ShapeAnalysis_Surface(BRep_Tool.Surface_s(f.face))
    uv = sa.ValueOfUV(gp_Pnt(*p), 1e-6)
    pp, vu, vv = gp_Pnt(), gp_Vec(), gp_Vec()
    f.ad.D1(uv.X(), uv.Y(), pp, vu, vv)
    n = unit(cross((vu.X(), vu.Y(), vu.Z()), (vv.X(), vv.Y(), vv.Z())))
    return mul(n, -1.0) if f.reversed else n


def classify(face, point, tol):
    cl = BRepClass_FaceClassifier()
    if len(point) == 2:
        cl.Perform(face, gp_Pnt2d(point[0], point[1]), tol)
    else:
        cl.Perform(face, gp_Pnt(*point), tol)
    return cl.State() in (TopAbs_IN, TopAbs_ON)


def uv_samples(f, n=6):
    umin, umax, vmin, vmax = f.uv
    out = []
    for i in range(n):
        for j in range(n):
            u = umin + (umax - umin) * (i + 0.5) / n
            v = vmin + (vmax - vmin) * (j + 0.5) / n
            if classify(f.face, (u, v), 1e-7):
                out.append((u, v))
    return out


def opposing(fa, fb, thick, tol):
    if fa.kind != fb.kind or fa.kind not in ("plane", "cylinder"):
        return False
    if fa.kind == "plane":
        if dot(fa.n, fb.n) > -1.0 + 1e-8:
            return False
        if abs(dot(sub(fb.o, fa.o), fa.n) + thick) > tol:
            return False
        small, big = (fa, fb) if fa.area <= fb.area else (fb, fa)
        step = mul(small.n, -thick)
        for u, v in uv_samples(small):
            p = pt(small.ad.Value(u, v))
            if classify(big.face, add(p, step), 1e-6):
                return True
        return False
    if abs(dot(fa.a, fb.a)) < 1.0 - 1e-9:
        return False
    d = sub(fb.c, fa.c)
    if norm(sub(d, mul(fa.a, dot(d, fa.a)))) > tol:
        return False
    if not (fa.sg > 0 > fb.sg):
        return False
    if abs(fa.R - fb.R - thick) > tol:
        return False
    for u, v in uv_samples(fa):
        p = pt(fa.ad.Value(u, v))
        d = sub(p, fa.c)
        ax = mul(fa.a, dot(d, fa.a))
        radial = unit(sub(d, ax))
        q = add(add(fa.c, ax), mul(radial, fb.R))
        if classify(fb.face, q, 1e-6):
            return True
    return False


def estimate_thickness(faces):
    votes = {}
    planes = [f for f in faces if f.kind == "plane"]
    for i, fa in enumerate(planes):
        for fb in planes[i + 1:]:
            if dot(fa.n, fb.n) > -1.0 + 1e-8:
                continue
            d = -dot(sub(fb.o, fa.o), fa.n)
            if d <= 1e-6:
                continue
            key = round(d, 4)
            votes[key] = votes.get(key, 0.0) + min(fa.area, fb.area)
    if not votes:
        return None
    return max(votes.items(), key=lambda kv: kv[1])[0]


def edge_info(edge, maps):
    ad = BRepAdaptor_Curve(edge)
    f, l = ad.FirstParameter(), ad.LastParameter()
    a, b = pt(ad.Value(f)), pt(ad.Value(l))
    v1, v2 = TopoDS_Vertex(), TopoDS_Vertex()
    TopExp.Vertices_s(edge, v1, v2, False)
    k1, k2 = maps["vertices"].FindIndex(v1), maps["vertices"].FindIndex(v2)
    p1 = pt(BRep_Tool.Pnt_s(v1))
    if norm(sub(p1, a)) > norm(sub(p1, b)):
        k1, k2 = k2, k1
    return ad, f, l, a, b, k1, k2


def sample_curve(ad, f, l, n):
    return [pt(ad.Value(f + (l - f) * i / n)) for i in range(n + 1)]


def arc_from_points(a, m, b):
    ax, ay = a
    bx, by = m
    cx, cy = b
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-14:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    ccw = (bx - ax) * (cy - by) - (by - ay) * (cx - bx) > 0
    return (ux, uy), r, ccw


def make_arc(a, m, b):
    got = arc_from_points(a, m, b)
    if got is None:
        return {"t": "line", "a": list(a), "b": list(b)}
    c, r, ccw = got
    a0 = math.atan2(a[1] - c[1], a[0] - c[0])
    a1 = math.atan2(b[1] - c[1], b[0] - c[0])
    if not ccw:
        a0, a1 = a1, a0
    return {"t": "arc", "a": list(a), "b": list(b), "c": list(c), "r": r, "ccw": ccw, "a0": a0, "a1": a1}


def sweep_of(seg):
    d = (seg["a1"] - seg["a0"]) % TAU
    return d if d > 0 else TAU


def seg_length(seg):
    t = seg["t"]
    if t == "line":
        return math.hypot(seg["b"][0] - seg["a"][0], seg["b"][1] - seg["a"][1])
    if t == "arc":
        return seg["r"] * sweep_of(seg)
    if t == "circle":
        return TAU * seg["r"]
    return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(seg["pts"], seg["pts"][1:]))


def seg_points(seg, per=24):
    t = seg["t"]
    if t == "line":
        return [tuple(seg["a"]), tuple(seg["b"])]
    if t == "poly":
        return [tuple(p) for p in seg["pts"]]
    if t == "circle":
        return [(seg["c"][0] + seg["r"] * math.cos(TAU * i / (4 * per)), seg["c"][1] + seg["r"] * math.sin(TAU * i / (4 * per))) for i in range(4 * per)]
    sw = sweep_of(seg)
    n = max(4, int(math.ceil(per * sw / (math.pi / 2.0))))
    pts = [(seg["c"][0] + seg["r"] * math.cos(seg["a0"] + sw * i / n), seg["c"][1] + seg["r"] * math.sin(seg["a0"] + sw * i / n)) for i in range(n + 1)]
    if not seg["ccw"]:
        pts.reverse()
    return pts


def reverse_seg(seg):
    t = seg["t"]
    out = dict(seg)
    if t in ("line", "arc"):
        out["a"], out["b"] = seg["b"], seg["a"]
        if t == "arc":
            out["ccw"] = not seg["ccw"]
    elif t == "poly":
        out["pts"] = list(reversed(seg["pts"]))
    elif t == "circle":
        out["ccw"] = not seg["ccw"]
    return out


def seg_start(seg):
    return tuple(seg["pts"][0]) if seg["t"] == "poly" else tuple(seg["a"])


def transform_seg(seg, rg):
    out = dict(seg)
    t = seg["t"]
    if t in ("line", "arc"):
        out["a"], out["b"] = list(rg(seg["a"])), list(rg(seg["b"]))
    if t in ("arc", "circle"):
        out["c"] = list(rg(seg["c"]))
    if t == "arc":
        out["a0"] = wrap(seg["a0"] + rg.psi)
        out["a1"] = wrap(seg["a1"] + rg.psi)
    if t == "poly":
        out["pts"] = [list(rg(p)) for p in seg["pts"]]
    return out


def loop_polygon(segs):
    pts = []
    for s in segs:
        sp = seg_points(s)
        if pts and sp:
            sp = sp[1:]
        pts.extend(sp)
    return pts


def poly_area(pts):
    return 0.5 * sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))


def loop_area(segs):
    pts = []
    for s in segs:
        if s["t"] == "circle":
            return (1.0 if s["ccw"] else -1.0) * math.pi * s["r"] ** 2
        pts.append(seg_start(s))
        if s["t"] == "poly":
            pts.extend(tuple(p) for p in s["pts"][1:-1])
    area = poly_area(pts)
    for s in segs:
        if s["t"] == "arc":
            sw = sweep_of(s)
            area += (1.0 if s["ccw"] else -1.0) * 0.5 * s["r"] ** 2 * (sw - math.sin(sw))
    return area


def inside_poly(p, poly):
    x, y = p
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def seg_bounds(seg):
    t = seg["t"]
    if t == "circle":
        return [seg["c"][0] - seg["r"], seg["c"][1] - seg["r"], seg["c"][0] + seg["r"], seg["c"][1] + seg["r"]]
    pts = list(seg_points(seg, 1)) if t != "arc" else [tuple(seg["a"]), tuple(seg["b"])]
    box = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
    if t == "arc":
        sw = sweep_of(seg)
        for k in range(4):
            ang = k * math.pi / 2.0
            if (ang - seg["a0"]) % TAU <= sw:
                x, y = seg["c"][0] + seg["r"] * math.cos(ang), seg["c"][1] + seg["r"] * math.sin(ang)
                box = [min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
    return box


def union_box(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def hull(points):
    pts = sorted(set((round(p[0], 9), round(p[1], 9)) for p in points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out

    lo, up = half(pts), half(reversed(pts))
    return lo[:-1] + up[:-1]


def min_rect_angle(points):
    h = hull(points)
    if len(h) < 3:
        return 0.0
    best = None
    for p, q in zip(h, h[1:] + h[:1]):
        ang = math.atan2(q[1] - p[1], q[0] - p[0])
        c, s = math.cos(-ang), math.sin(-ang)
        xs = [c * x - s * y for x, y in h]
        ys = [s * x + c * y for x, y in h]
        w, hgt = max(xs) - min(xs), max(ys) - min(ys)
        key = (round(w * hgt, 7), ang)
        if best is None or key < best[0]:
            best = (key, ang, w, hgt)
    ang, w, hgt = best[1], best[2], best[3]
    return -ang if w >= hgt else -ang + math.pi / 2.0


def unfold_solid(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    maps = store.maps_of(ident)
    nfaces = maps["faces"].Extent()
    if nfaces == 0:
        raise UnfoldError("The body has no faces.")
    k_default = float(p.get("k", 0.44))
    bend_k = {str(a): float(b) for a, b in (p.get("bend_k") or {}).items()}
    align = str(p.get("align", "bbox"))
    warnings = []
    faces = [Face(i, TopoDS.Face(maps["faces"].FindKey(i + 1))) for i in range(nfaces)]
    thick = p.get("thickness")
    if thick is None:
        thick = estimate_thickness(faces)
        if thick is None:
            raise UnfoldError("No pair of parallel faces gives a sheet thickness; give the thickness.")
        warnings.append("The thickness %.6g mm was found from the faces." % thick)
    thick = float(thick)
    if thick <= 0:
        raise UnfoldError("The thickness must be above zero.")
    tol = max(1e-5, 1e-3 * thick)
    anc = AncestorMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, anc)
    edge_faces = {}
    for i in range(1, maps["edges"].Extent() + 1):
        e = maps["edges"].FindKey(i)
        j = anc.FindIndex(e)
        got = []
        if j > 0:
            for f in anc.FindFromIndex(j):
                k = maps["faces"].FindIndex(f) - 1
                got.append(k)
        edge_faces[i - 1] = got

    bad = [f for f in faces if f.kind not in ("plane", "cylinder")]
    partners = {f.idx: [] for f in faces}
    cand = [f for f in faces if f.kind in ("plane", "cylinder")]
    for i, fa in enumerate(cand):
        for fb in cand[i + 1:]:
            if opposing(fa, fb, thick, tol) or opposing(fb, fa, thick, tol):
                partners[fa.idx].append(fb.idx)
                partners[fb.idx].append(fa.idx)
    skin = {i for i, v in partners.items() if v}
    for f in cand:
        if f.kind == "cylinder" and f.idx not in skin and f.sg > 0 and abs(f.R - thick) <= tol:
            for e, fl in edge_faces.items():
                other = [g for g in set(fl) if g != f.idx and g in skin and faces[g].kind == "plane"]
                if f.idx in fl and other:
                    edge = TopoDS.Edge(maps["edges"].FindKey(e + 1))
                    ad, f0, l0, a0, b0, k1, k2 = edge_info(edge, maps)
                    mid = pt(ad.Value((f0 + l0) / 2.0))
                    if dot(f.normal_at(mid), faces[other[0]].n) > 1.0 - 1e-6:
                        skin.add(f.idx)
                        break
    if not skin:
        raise UnfoldError("No face has a matching face one thickness (%.6g mm) away, so this is not a constant thickness sheet." % thick)
    skin_planes = [faces[i] for i in sorted(skin) if faces[i].kind == "plane"]
    fixed = p.get("fixed_face")
    if fixed is not None:
        fixed = int(fixed)
        if fixed not in skin or faces[fixed].kind != "plane":
            raise UnfoldError("Face %d is not a flat sheet face, so it cannot be the fixed face." % fixed)
        root = faces[fixed]
    else:
        if not skin_planes:
            raise UnfoldError("The sheet has no flat face to hold fixed.")
        root = sorted(skin_planes, key=lambda f: (-round(f.area, 6), f.idx))[0]
    if p.get("flip"):
        opp = [faces[i] for i in partners[root.idx] if faces[i].kind == "plane"]
        if opp:
            root = sorted(opp, key=lambda f: (-round(f.area, 6), f.idx))[0]

    adj = {}
    for e, fl in edge_faces.items():
        u = sorted(set(fl))
        if len(u) == 2 and u[0] in skin and u[1] in skin and not (u[1] in partners[u[0]]):
            adj.setdefault(u[0], []).append((e, u[1]))
            adj.setdefault(u[1], []).append((e, u[0]))
        elif len(u) > 2 and sum(1 for g in u if g in skin) > 1:
            raise UnfoldError("An edge is shared by more than two faces; the sheet is not a clean solid.")
    order = [root.idx]
    parent_edge = {root.idx: None}
    queue = [root.idx]
    while queue:
        cur = queue.pop(0)
        for e, g in sorted(adj.get(cur, []), key=lambda t: (t[1], t[0])):
            if g in parent_edge:
                continue
            parent_edge[g] = (cur, e)
            order.append(g)
            queue.append(g)
    group = set(order)
    for i in sorted(group):
        if faces[i].kind not in ("plane", "cylinder"):
            raise UnfoldError("Face %d is a %s face, which cannot be flattened." % (i, faces[i].kind))
    for e, fl in sorted(edge_faces.items()):
        touching = [g for g in set(fl) if g in group]
        for idx in sorted(set(fl)):
            if touching and faces[idx].kind not in ("plane", "cylinder") and idx not in group:
                edge = TopoDS.Edge(maps["edges"].FindKey(e + 1))
                ad, f0, l0, a0, b0, k1, k2 = edge_info(edge, maps)
                mid = pt(ad.Value((f0 + l0) / 2.0))
                other = faces[touching[0]].normal_at(mid)
                if dot(other, surface_normal(faces[idx], mid)) > 1.0 - 1e-4:
                    raise UnfoldError("Face %d is a %s face joined smoothly to the sheet surface; it cannot be developed." % (idx, faces[idx].kind))

    cyl_in = [i for i in sorted(group) if faces[i].kind == "cylinder"]
    for i in cyl_in:
        if faces[i].span >= TAU - 1e-6:
            raise UnfoldError("Cylindrical face %d is a full tube; a rip is needed before it can be flattened." % i)
    uf = {i: i for i in cyl_in}

    def find(x):
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    for e, fl in edge_faces.items():
        u = sorted(set(g for g in fl if g in group and faces[g].kind == "cylinder"))
        if len(u) == 2:
            fa, fb = faces[u[0]], faces[u[1]]
            dd = sub(fb.c, fa.c)
            if abs(dot(fa.a, fb.a)) > 1 - 1e-9 and abs(fa.R - fb.R) < tol and fa.sg == fb.sg and norm(sub(dd, mul(fa.a, dot(dd, fa.a)))) < tol:
                uf[find(u[0])] = find(u[1])
    groups = {}
    for i in cyl_in:
        groups.setdefault(find(i), []).append(i)
    face_scale = {}
    face_group = {}
    group_info = {}
    for members in groups.values():
        members.sort()
        key = members[0]
        f0 = faces[members[0]]
        concave = f0.sg < 0
        inner = f0.R if concave else f0.R - thick
        if inner < -tol:
            raise UnfoldError("Cylindrical face %d has radius %.6g, smaller than the sheet thickness; it cannot be a bend." % (key, f0.R))
        inner = max(inner, 0.0)
        k = bend_k.get(str(key), k_default)
        rn = inner + k * thick
        group_info[key] = {"members": members, "concave": concave, "inner": inner, "k": k, "rn": rn}
        for m in members:
            face_scale[m] = rn / faces[m].R
            face_group[m] = key

    placed = {}
    devs = {}
    sharp_bends = []
    placed[root.idx] = Rigid()
    devs[root.idx] = Dev(root)

    def flat_of(fidx, point):
        return placed[fidx](devs[fidx](point))

    def straight_edge(e):
        edge = TopoDS.Edge(maps["edges"].FindKey(e + 1))
        ad, f, l, a, b, k1, k2 = edge_info(edge, maps)
        if ad.GetType() != GeomAbs_Line:
            raise UnfoldError("The fold between two sheet faces (edge %d) is not a straight line." % e)
        return a, b

    for fidx in order[1:]:
        par, e = parent_edge[fidx]
        f = faces[fidx]
        pf = faces[par]
        a3, b3 = straight_edge(e)
        mid3 = mul(add(a3, b3), 0.5)
        n1, n2 = pf.normal_at(mid3), f.normal_at(mid3)
        smooth = dot(n1, n2) > 1.0 - 1e-6
        sharp = False
        if not smooth:
            if pf.kind != "plane" or f.kind != "plane":
                raise UnfoldError("Faces %d and %d meet at a corner instead of a bend." % (par, fidx))
            if dot(sub(f.centroid, mid3), pf.n) < 0:
                raise UnfoldError("Faces %d and %d meet at a sharp outside corner; choose the other side as the reference or give the bend a radius." % (par, fidx))
            sharp = True
        scale = face_scale.get(fidx, 1.0)
        dev = Dev(f, scale)
        devs[fidx] = dev
        q0, q1 = flat_of(par, a3), flat_of(par, b3)
        c0, c1 = dev(a3), dev(b3)
        lq, lc = math.hypot(q1[0] - q0[0], q1[1] - q0[1]), math.hypot(c1[0] - c0[0], c1[1] - c0[1])
        if abs(lq - lc) > 1e-5 * (1.0 + lq):
            raise UnfoldError("The fold edge %d does not keep its length between faces %d and %d." % (e, par, fidx))
        psi = math.atan2(q1[1] - q0[1], q1[0] - q0[0]) - math.atan2(c1[1] - c0[1], c1[0] - c0[0])
        rg = Rigid(psi)
        r0 = rg.rot(c0)
        rg.tx, rg.ty = q0[0] - r0[0], q0[1] - r0[1]
        side_p = flat_of(par, pf.centroid)
        ex_, ey_ = (q1[0] - q0[0]) / lq, (q1[1] - q0[1]) / lq
        sp = ex_ * (side_p[1] - q0[1]) - ey_ * (side_p[0] - q0[0])
        away = (-ey_, ex_) if sp < 0 else (ey_, -ex_)
        if sharp:
            ang = math.acos(max(-1.0, min(1.0, dot(n1, n2))))
            kk = bend_k.get("s%d_%d" % (par, fidx), k_default)
            wdt = ang * kk * thick
            rg.tx += away[0] * wdt
            rg.ty += away[1] * wdt
            sharp_bends.append({"par": par, "face": fidx, "edge": e, "angle": ang, "k": kk, "w": wdt, "a3": a3, "b3": b3, "away": away, "q0": q0, "q1": q1, "key": "s%d_%d" % (par, fidx)})
        placed[fidx] = rg
        side_c = flat_of(fidx, f.centroid)
        sc = ex_ * (side_c[1] - q0[1]) - ey_ * (side_c[0] - q0[0])
        if sp * sc > 0:
            warnings.append("Face %d may fold onto face %d; check the flat pattern." % (fidx, par))

    for e, fl in edge_faces.items():
        u = sorted(set(g for g in fl if g in group))
        if len(u) == 2 and (parent_edge.get(u[0]) is None or parent_edge[u[0]][1] != e) and (parent_edge.get(u[1]) is None or parent_edge[u[1]][1] != e):
            if any(sb["edge"] == e for sb in sharp_bends):
                continue
            try:
                a3, b3 = straight_edge(e)
            except UnfoldError:
                continue
            for pnt in (a3, b3):
                x, y = flat_of(u[0], pnt), flat_of(u[1], pnt)
                if math.hypot(x[0] - y[0], x[1] - y[1]) > 1e-4 * (1.0 + thick):
                    raise UnfoldError("The sheet closes on itself at edge %d (between faces %d and %d); a rip is needed before it can be flattened." % (e, u[0], u[1]))

    raw = []
    for fidx in sorted(group):
        f = faces[fidx]
        seen = {}
        explorer = TopExp_Explorer(f.face, TopAbs_EDGE)
        while explorer.More():
            edge = TopoDS.Edge(explorer.Current())
            ei = maps["edges"].FindIndex(edge) - 1
            seen[ei] = seen.get(ei, 0) + 1
            explorer.Next()
        for ei, cnt in sorted(seen.items()):
            if cnt > 1:
                continue
            edge = TopoDS.Edge(maps["edges"].FindKey(ei + 1))
            if BRep_Tool.Degenerated_s(edge):
                continue
            others = [g for g in set(edge_faces[ei]) if g != fidx and g in group]
            if others:
                continue
            raw.append(map_edge(f, fidx, ei, edge, maps, flat_of, thick))

    loops = chain_loops(raw)
    if not loops:
        raise UnfoldError("The flat pattern has no outline.")

    bends = []
    for key, info in sorted(group_info.items()):
        members = info["members"]
        f0 = faces[members[0]]
        corners = []
        axial = []
        for m in members:
            fm = faces[m]
            sgn = 1.0 if dot(fm.a, f0.a) > 0 else -1.0
            shift = dot(sub(fm.c, f0.c), f0.a)
            axial.extend([shift + sgn * fm.t0, shift + sgn * fm.t1])
            for ang in (-fm.span / 2.0, fm.span / 2.0):
                for t in (fm.t0, fm.t1):
                    corners.append(flat_of(m, fm.surface_point(ang, t)))
        e0 = flat_of(members[0], f0.surface_point(0.0, 1.0))
        o0 = flat_of(members[0], f0.surface_point(0.0, 0.0))
        ev = unit((e0[0] - o0[0], e0[1] - o0[1], 0.0))
        ev = (ev[0], ev[1])
        wv = (-ev[1], ev[0])
        ws = [c[0] * wv[0] + c[1] * wv[1] for c in corners]
        ts = [c[0] * ev[0] + c[1] * ev[1] for c in corners]
        wc = (min(ws) + max(ws)) / 2.0
        t0, t1 = min(ts), max(ts)
        a = (t0 * ev[0] + wc * wv[0], t0 * ev[1] + wc * wv[1])
        b = (t1 * ev[0] + wc * wv[0], t1 * ev[1] + wc * wv[1])
        angle = sum(faces[m].span for m in members)
        bends.append({"key": str(key), "faces": members, "angle": angle, "radius": info["inner"], "k": info["k"], "neutral_radius": info["rn"], "direction": "up" if info["concave"] else "down", "a": a, "b": b, "strip": [min(ws), max(ws)], "sharp": False, "axis": {"origin": list(f0.c), "dir": list(f0.a), "t0": min(axial), "t1": max(axial)}})
    for sb in sharp_bends:
        away = sb["away"]
        a = (sb["q0"][0] + away[0] * sb["w"] / 2.0, sb["q0"][1] + away[1] * sb["w"] / 2.0)
        b = (sb["q1"][0] + away[0] * sb["w"] / 2.0, sb["q1"][1] + away[1] * sb["w"] / 2.0)
        bends.append({"key": sb["key"], "faces": [sb["par"], sb["face"]], "angle": sb["angle"], "radius": 0.0, "k": sb["k"], "neutral_radius": sb["k"] * thick, "direction": "up", "a": a, "b": b, "strip": [0.0, sb["w"]], "sharp": True, "axis": {"origin": list(sb["a3"]), "dir": list(unit(sub(sb["b3"], sb["a3"]))), "t0": 0.0, "t1": norm(sub(sb["b3"], sb["a3"]))}})

    areas = [loop_area(l) for l in loops]
    polys = [loop_polygon(l) for l in loops]
    depth = []
    for i, l in enumerate(loops):
        d = 0
        sp = seg_start(l[0]) if l[0]["t"] != "circle" else (l[0]["c"][0] + l[0]["r"], l[0]["c"][1])
        for j, pl in enumerate(polys):
            if i != j and abs(areas[j]) > abs(areas[i]) and inside_poly(sp, pl):
                d += 1
        depth.append(d)
    out_loops = []
    for l, a, d in zip(loops, areas, depth):
        outer = d % 2 == 0
        want_ccw = outer
        if (a > 0) != want_ccw:
            l = [reverse_seg(s) for s in reversed(l)]
            a = -a
        out_loops.append({"outer": outer, "segs": l, "area": abs(a), "length": sum(seg_length(s) for s in l), "depth": d})

    psi = 0.0
    if align == "bbox":
        pts = []
        for lp in out_loops:
            if lp["outer"]:
                pts.extend(loop_polygon(lp["segs"]))
        psi = min_rect_angle(pts)
    rg = Rigid(psi)
    out_loops = [{**lp, "segs": [transform_seg(s, rg) for s in lp["segs"]]} for lp in out_loops]
    bends = [{**b, "a": rg(b["a"]), "b": rg(b["b"])} for b in bends]
    box = union_box([seg_bounds(s) for lp in out_loops for s in lp["segs"] if lp["outer"]])
    cen = [0.0, 0.0]
    tot = 0.0
    for lp in out_loops:
        if lp["outer"]:
            pl = loop_polygon(lp["segs"])
            cen[0] += sum(q[0] for q in pl) / len(pl) * lp["area"]
            cen[1] += sum(q[1] for q in pl) / len(pl) * lp["area"]
            tot += lp["area"]
    flip180 = align == "bbox" and tot > 0 and cen[0] / tot > (box[0] + box[2]) / 2.0 + 1e-6
    if flip180:
        rg2 = Rigid(math.pi, 0.0, 0.0)
        out_loops = [{**lp, "segs": [transform_seg(s, rg2) for s in lp["segs"]]} for lp in out_loops]
        bends = [{**b, "a": rg2(b["a"]), "b": rg2(b["b"])} for b in bends]
        box = union_box([seg_bounds(s) for lp in out_loops for s in lp["segs"] if lp["outer"]])
    if align == "bbox":
        shift = Rigid(0.0, -box[0], -box[1])
        out_loops = [{**lp, "segs": [transform_seg(s, shift) for s in lp["segs"]]} for lp in out_loops]
        bends = [{**b, "a": shift(b["a"]), "b": shift(b["b"])} for b in bends]
        box = [0.0, 0.0, box[2] - box[0], box[3] - box[1]]
    bends.sort(key=lambda b: (round((b["a"][0] + b["b"][0]) / 2.0, 4), round((b["a"][1] + b["b"][1]) / 2.0, 4)))
    for i, b in enumerate(bends):
        b["id"] = "B%d" % (i + 1)
        b["length"] = math.hypot(b["b"][0] - b["a"][0], b["b"][1] - b["a"][1])
        pa, pb = tuple(b["a"]), tuple(b["b"])
        if (round(pa[0], 6), round(pa[1], 6)) > (round(pb[0], 6), round(pb[1], 6)):
            pa, pb = pb, pa
        b["a"], b["b"] = list(pa), list(pb)

    outer_area = sum(lp["area"] for lp in out_loops if lp["outer"])
    hole_area = sum(lp["area"] for lp in out_loops if not lp["outer"])
    blank = outer_area - hole_area
    expected = sum(faces[i].area for i in group if faces[i].kind == "plane") + sum(faces[i].area * face_scale[i] for i in group if faces[i].kind == "cylinder")
    for sb in sharp_bends:
        expected += sb["w"] * norm(sub(sb["b3"], sb["a3"]))
    rel = abs(blank - expected) / expected if expected else 0.0
    if rel > 1e-3:
        warnings.append("The flat area differs from the sum of the developed faces by %.3g percent." % (rel * 100.0))
    if self_overlap(out_loops):
        warnings.append("The flat outline crosses itself; the sheet may overlap when flattened.")
    return {
        "ok": True,
        "thickness": thick,
        "k": k_default,
        "reference": {"face": root.idx, "faces": sorted(group)},
        "loops": out_loops,
        "bends": bends,
        "bbox": box,
        "blank_area": blank,
        "area_check": {"flat": blank, "expected": expected, "relative": rel},
        "cut_outer": sum(lp["length"] for lp in out_loops if lp["outer"]),
        "cut_inner": sum(lp["length"] for lp in out_loops if not lp["outer"]),
        "cutouts": sum(1 for lp in out_loops if not lp["outer"]),
        "rotation": psi + (math.pi if flip180 else 0.0),
        "warnings": warnings,
    }


def map_edge(f, fidx, ei, edge, maps, flat_of, thick):
    ad, first, last, a, b, k1, k2 = edge_info(edge, maps)
    kind = ad.GetType()
    fa = flat_of(fidx, a)
    fb = flat_of(fidx, b)
    length = BRepGProp_length(edge)
    closed = k1 == k2
    seg = None
    if kind == GeomAbs_Line:
        seg = {"t": "line", "a": list(fa), "b": list(fb)}
    elif kind == GeomAbs_Circle and f.kind == "plane":
        circ = ad.Circle()
        if closed:
            c3 = pt(circ.Location())
            seg = {"t": "circle", "c": list(flat_of(fidx, c3)), "r": circ.Radius(), "ccw": True}
            m3 = pt(ad.Value(first + (last - first) / 4.0))
            m2 = flat_of(fidx, m3)
            sgn = (m2[0] - seg["c"][0]) * (fa[1] - seg["c"][1]) - (m2[1] - seg["c"][1]) * (fa[0] - seg["c"][0])
            seg["ccw"] = sgn < 0
        else:
            m3 = pt(ad.Value((first + last) / 2.0))
            seg = make_arc(fa, flat_of(fidx, m3), fb)
    elif kind == GeomAbs_Circle and f.kind == "cylinder":
        circ = ad.Circle()
        if abs(dot(unit(pt(circ.Axis().Direction())), f.a)) > 1 - 1e-9 and not closed:
            seg = {"t": "line", "a": list(fa), "b": list(fb)}
    if seg is None:
        n = max(16, min(400, int(math.ceil(length / 0.5))))
        pts = [list(flat_of(fidx, q)) for q in sample_curve(ad, first, last, n)]
        seg = {"t": "poly", "pts": pts}
    seg["va"], seg["vb"] = k1, k2
    seg["edge"] = ei
    return seg


def BRepGProp_length(edge):
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return props.Mass()


def chain_loops(raw):
    by_v = {}
    for i, s in enumerate(raw):
        by_v.setdefault(s["va"], []).append(i)
        by_v.setdefault(s["vb"], []).append(i)
    used = set()
    loops = []
    for i in range(len(raw)):
        if i in used:
            continue
        used.add(i)
        s = raw[i]
        if s["t"] == "circle" or s["va"] == s["vb"]:
            loops.append([clean(s)])
            continue
        loop = [s]
        start = s["va"]
        cur = s["vb"]
        guard = 0
        while cur != start and guard < len(raw) + 2:
            guard += 1
            nxt = None
            for j in by_v.get(cur, []):
                if j not in used:
                    nxt = j
                    break
            if nxt is None:
                break
            used.add(nxt)
            t = raw[nxt]
            if t["va"] != cur:
                t = reverse_seg(t)
                t["va"], t["vb"] = raw[nxt]["vb"], raw[nxt]["va"]
            loop.append(t)
            cur = t["vb"]
        if cur != start:
            raise UnfoldError("The outline of the flat pattern does not close (open edge chain at vertex %s)." % cur)
        loops.append([clean(x) for x in loop])
    return [merge_collinear(l) for l in loops]


def clean(seg):
    out = dict(seg)
    for k in ("va", "vb", "edge"):
        out.pop(k, None)
    return out


def merge_collinear(loop):
    if len(loop) < 3:
        return loop
    out = [loop[0]]
    for s in loop[1:]:
        last = out[-1]
        if last["t"] == "line" and s["t"] == "line":
            d1 = (last["b"][0] - last["a"][0], last["b"][1] - last["a"][1])
            d2 = (s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
            l1, l2 = math.hypot(*d1), math.hypot(*d2)
            if l1 > 0 and l2 > 0 and abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-9 * l1 * l2 and d1[0] * d2[0] + d1[1] * d2[1] > 0:
                out[-1] = {"t": "line", "a": last["a"], "b": s["b"]}
                continue
        out.append(s)
    if len(out) > 2 and out[0]["t"] == "line" and out[-1]["t"] == "line":
        last, s = out[-1], out[0]
        d1 = (last["b"][0] - last["a"][0], last["b"][1] - last["a"][1])
        d2 = (s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
        l1, l2 = math.hypot(*d1), math.hypot(*d2)
        if l1 > 0 and l2 > 0 and abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-9 * l1 * l2 and d1[0] * d2[0] + d1[1] * d2[1] > 0:
            out[0] = {"t": "line", "a": last["a"], "b": s["b"]}
            out.pop()
    return out


def self_overlap(loops):
    edges = []
    for li, lp in enumerate(loops):
        pl = loop_polygon(lp["segs"])
        for a, b in zip(pl, pl[1:] + pl[:1]):
            edges.append((li, a, b))
    if len(edges) > 1500:
        return False
    for i in range(len(edges)):
        la, a, b = edges[i]
        for j in range(i + 1, len(edges)):
            lb, c, d = edges[j]
            if la == lb and (j == i + 1 or (i == 0 and j == len(edges) - 1)):
                continue
            if seg_cross(a, b, c, d):
                return True
    return False


def seg_cross(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    eps = 1e-9
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < -eps and o3 * o4 < -eps


METHODS = {"unfold_solid": unfold_solid}
