import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools
from OCP.GC import GC_MakeArcOfCircle
from OCP.GProp import GProp_GProps
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.collections import List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Trsf, gp_Vec

import kernel_feat as feat
import kernel_ops as ops
import kernel_store as store

EPS = 1e-9
MAX_EDGES = 200
MAX_PATH = 400
MAX_ANGLE = math.radians(330.0)
POSITIONS = ("material_inside", "material_outside", "bend_outside")
DATUMS = ("outside", "inside", "tangent")


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n < 1e-12:
        raise RuntimeError("A direction has zero length.")
    return (a[0] / n, a[1] / n, a[2] / n)


def tup(p):
    return (p.X(), p.Y(), p.Z())


def num(p, key, default=None, lo=None, hi=None):
    v = p.get(key)
    if v is None:
        v = default
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        raise RuntimeError("%s must be a finite number." % key)
    if lo is not None and v < lo:
        raise RuntimeError("%s must be at least %g." % (key, lo))
    if hi is not None and v > hi:
        raise RuntimeError("%s must be at most %g." % (key, hi))
    return v


class Frame:
    def __init__(self, origin, u, v):
        self.o = tuple(float(x) for x in origin)
        self.u = unit(u)
        self.v = unit(sub(v, mul(self.u, dot(v, self.u))))
        self.w = cross(self.u, self.v)

    def pt(self, a, b, c=0.0):
        return add(self.o, add(add(mul(self.u, a), mul(self.v, b)), mul(self.w, c)))

    def dr(self, a, b, c=0.0):
        return add(add(mul(self.u, a), mul(self.v, b)), mul(self.w, c))

    def local(self, p):
        d = sub(p, self.o)
        return (dot(d, self.u), dot(d, self.v), dot(d, self.w))

    def data(self):
        return {"origin": list(self.o), "u": list(self.u), "v": list(self.v), "w": list(self.w)}


def box_in(frame, u0, u1, v0, v1, w0, w1):
    ax = gp_Ax2(gp_Pnt(*frame.pt(u0, v0, w0)), gp_Dir(*frame.w), gp_Dir(*frame.u))
    mk = BRepPrimAPI_MakeBox(ax, u1 - u0, v1 - v0, w1 - w0)
    return mk.Shape()


def cylinder_v(frame, cu, cw, radius, v0, v1):
    ax = gp_Ax2(gp_Pnt(*frame.pt(cu, v0, cw)), gp_Dir(*frame.v), gp_Dir(*frame.u))
    return BRepPrimAPI_MakeCylinder(ax, radius, v1 - v0).Shape()


def line_edge(a, b):
    return BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge()


def arc_edge(a, m, b):
    arc = GC_MakeArcOfCircle(gp_Pnt(*a), gp_Pnt(*m), gp_Pnt(*b))
    if not arc.IsDone():
        raise RuntimeError("A bend arc is degenerate; check the radius and angle.")
    return BRepBuilderAPI_MakeEdge(arc.Value()).Edge()


def edge_mid(edge):
    c = BRepAdaptor_Curve(edge)
    return tup(c.Value((c.FirstParameter() + c.LastParameter()) / 2.0))


def rot2(p, c, ang):
    ca, sa = math.cos(ang), math.sin(ang)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * ca - y * sa, c[1] + x * sa + y * ca)


class Section:
    def __init__(self, frame, thickness, start, heading, side=-1, path_is_ref=True, seg0=0, bend0=0):
        self.f = frame
        self.t = float(thickness)
        self.side = side
        self.pref = path_is_ref
        self.p = (float(start[0]), float(start[1]))
        self.h = float(heading)
        self.start = self.p
        self.start_h = self.h
        self.parts = []
        self.seg = seg0
        self.bend_no = bend0

    def left(self, h):
        return (-math.sin(h), math.cos(h))

    def flat(self, length):
        if length < 1e-9:
            return
        if len(self.parts) >= MAX_PATH:
            raise RuntimeError("The sheet path has too many parts.")
        nl = self.left(self.h)
        a = self.p
        b = (a[0] + length * math.cos(self.h), a[1] + length * math.sin(self.h))
        k = self.side * self.t
        self.parts.append({"t": "flat", "a": a, "b": b, "oa": (a[0] + k * nl[0], a[1] + k * nl[1]), "ob": (b[0] + k * nl[0], b[1] + k * nl[1]), "h": self.h, "len": length, "i": self.seg})
        self.seg += 1
        self.p = b

    def bend(self, r_in, angle, turn):
        if r_in <= EPS:
            raise RuntimeError("The inside radius must be above zero.")
        if angle <= EPS or angle > MAX_ANGLE:
            raise RuntimeError("A bend angle must be above 0 and at most 330 degrees.")
        s, T = self.side, self.t
        rp = r_in + (T if s * turn == 1 else 0.0)
        ro = rp - s * turn * T
        h = self.h
        nl = self.left(h)
        a = self.p
        c = (a[0] + turn * rp * nl[0], a[1] + turn * rp * nl[1])
        sweep = turn * angle
        m = rot2(a, c, sweep / 2.0)
        b = rot2(a, c, sweep)
        h_m = h + sweep / 2.0
        h_e = h + sweep
        nm, ne = self.left(h_m), self.left(h_e)
        k = s * T
        self.bend_no += 1
        self.parts.append({
            "t": "bend", "a": a, "m": m, "b": b, "oa": (a[0] + k * nl[0], a[1] + k * nl[1]), "om": (m[0] + k * nm[0], m[1] + k * nm[1]), "ob": (b[0] + k * ne[0], b[1] + k * ne[1]),
            "c": c, "rp": rp, "ro": ro, "r_in": r_in, "angle": angle, "turn": turn, "h": h, "h_end": h_e, "j": self.bend_no, "ref_inner": s * turn == -1,
        })
        self.p = b
        self.h = h_e

    def end_pose(self):
        return self.p, self.h

    def ref_role(self, part):
        return "seg%d:ref" % part["i"] if self.pref else "seg%d:opp" % part["i"]

    def other_role(self, part):
        return "seg%d:opp" % part["i"] if self.pref else "seg%d:ref" % part["i"]

    def normal_of(self, h):
        nl = self.left(h)
        sign = -self.side if self.pref else self.side
        return self.f.dr(sign * nl[0], sign * nl[1])

    def path_summary(self):
        out = []
        for part in self.parts:
            if part["t"] == "flat":
                out.append({"t": "flat", "a": list(part["a"]), "b": list(part["b"]), "len": part["len"]})
            else:
                out.append({"t": "bend", "j": part["j"], "centre": list(part["c"]), "r_in": part["r_in"], "angle": part["angle"], "turn": part["turn"]})
        return out

    def bend_infos(self, w0, w1):
        out = []
        f = self.f
        for k, part in enumerate(self.parts):
            if part["t"] != "bend":
                continue
            prev = self.parts[k - 1] if k > 0 and self.parts[k - 1]["t"] == "flat" else None
            nxt = self.parts[k + 1] if k + 1 < len(self.parts) and self.parts[k + 1]["t"] == "flat" else None
            up = part["ref_inner"] if self.pref else not part["ref_inner"]
            c = part["c"]
            out.append({
                "j": part["j"], "radius": part["r_in"], "thickness": self.t, "angle": part["angle"], "direction": "up" if up else "down", "turn": part["turn"],
                "axis": {"origin": list(f.pt(c[0], c[1], (w0 + w1) / 2.0)), "dir": list(f.w), "length": w1 - w0},
                "ref_normal_parent": list(self.normal_of(part["h"])), "ref_normal_child": list(self.normal_of(part["h_end"])),
                "flat_parent": prev["len"] if prev else None, "flat_child": nxt["len"] if nxt else None,
                "labels": {"inner": "bend%d:%s" % (part["j"], "in"), "outer": "bend%d:%s" % (part["j"], "out"), "parent": "seg%d:ref" % prev["i"] if prev else None, "child": "seg%d:ref" % nxt["i"] if nxt else None},
            })
        return out

    def solid(self, w0, w1):
        if not self.parts:
            raise RuntimeError("The sheet path is empty.")
        f = self.f
        pairs = []
        marks = []
        for part in self.parts:
            if part["t"] == "flat":
                er = line_edge(f.pt(*part["a"], w0), f.pt(*part["b"], w0))
                eo = line_edge(f.pt(*part["oa"], w0), f.pt(*part["ob"], w0))
                mr = f.pt(*[(part["a"][i] + part["b"][i]) / 2.0 for i in (0, 1)], w0)
                mo = f.pt(*[(part["oa"][i] + part["ob"][i]) / 2.0 for i in (0, 1)], w0)
                marks.append((mr, self.ref_role(part)))
                marks.append((mo, self.other_role(part)))
            else:
                er = arc_edge(f.pt(*part["a"], w0), f.pt(*part["m"], w0), f.pt(*part["b"], w0))
                eo = arc_edge(f.pt(*part["oa"], w0), f.pt(*part["om"], w0), f.pt(*part["ob"], w0))
                inner = "bend%d:in" % part["j"]
                outer = "bend%d:out" % part["j"]
                marks.append((f.pt(*part["m"], w0), inner if part["ref_inner"] else outer))
                marks.append((f.pt(*part["om"], w0), outer if part["ref_inner"] else inner))
            pairs.append((er, eo))
        first, last = self.parts[0], self.parts[-1]
        e_start = line_edge(f.pt(*first["oa"], w0), f.pt(*first["a"], w0))
        e_end = line_edge(f.pt(*last["b"], w0), f.pt(*last["ob"], w0))
        marks.append((tuple((x + y) / 2.0 for x, y in zip(f.pt(*first["oa"], w0), f.pt(*first["a"], w0))), "end:start"))
        marks.append((tuple((x + y) / 2.0 for x, y in zip(f.pt(*last["b"], w0), f.pt(*last["ob"], w0))), "end:end"))
        mk = BRepBuilderAPI_MakeWire()
        for er, eo in pairs:
            mk.Add(er)
        mk.Add(e_end)
        for er, eo in reversed(pairs):
            mk.Add(eo)
        mk.Add(e_start)
        if not mk.IsDone():
            raise RuntimeError("The sheet cross section could not be closed; check the lengths and radii.")
        face = BRepBuilderAPI_MakeFace(mk.Wire(), True)
        if not face.IsDone():
            raise RuntimeError("The sheet cross section is not planar or self-intersects.")
        face = face.Face()
        prism = BRepPrimAPI_MakePrism(face, gp_Vec(*mul(f.w, w1 - w0)))
        if not prism.IsDone():
            raise RuntimeError("The sheet section could not be extruded.")
        solid = prism.Shape()
        roles = []
        emap = store.build_maps(face)["edges"]
        cands = []
        for i in range(1, emap.Extent() + 1):
            e = TopoDS.Edge(emap.FindKey(i))
            cands.append((e, edge_mid(e)))
        used = set()
        for pos, role in marks:
            best, bd = None, None
            for k, (e, m) in enumerate(cands):
                if k in used:
                    continue
                d = norm(sub(m, pos))
                if bd is None or d < bd:
                    best, bd = k, d
            if best is None or bd > 1e-5:
                raise RuntimeError("The sheet section edges could not be labelled.")
            used.add(best)
            for g in prism.Generated(cands[best][0]):
                if g.ShapeType() == TopAbs_FACE:
                    roles.append((TopoDS.Face(g), role))
        fs, ls = prism.FirstShape(), prism.LastShape()
        if fs.ShapeType() == TopAbs_FACE:
            roles.append((TopoDS.Face(fs), "cap:w0"))
        if ls.ShapeType() == TopAbs_FACE:
            roles.append((TopoDS.Face(ls), "cap:w1"))
        return solid, roles


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def compose(a, b):
    out = {}
    for key in ("faces", "edges"):
        res = {}
        for old, row in a[key].items():
            to = []
            for m in row["to"]:
                nxt = b[key].get(str(m))
                if nxt:
                    for x in nxt["to"]:
                        if x not in to:
                            to.append(x)
            res[old] = {"to": to, "deleted": not to}
        out[key] = res
    return out


def rows_by(old_shape, new_shape, fn):
    om, nm = store.build_maps(old_shape), store.build_maps(new_shape)
    out = {}
    for key in ("faces", "edges"):
        rows = {}
        for i in range(1, om[key].Extent() + 1):
            sub_shape = om[key].FindKey(i)
            to = []
            for s in fn(sub_shape, key):
                k = nm[key].FindIndex(s)
                if k > 0 and k - 1 not in to:
                    to.append(k - 1)
            rows[str(i - 1)] = {"to": to, "deleted": not to}
        out[key] = rows
    return out


def advance(maker, faces):
    out = []
    for f in faces:
        if maker.IsDeleted(f):
            continue
        mods = [TopoDS.Face(m) for m in maker.Modified(f) if m.ShapeType() == TopAbs_FACE]
        out.extend(mods if mods else [f])
    return out


class Build:
    def __init__(self, base_id, base):
        self.base_id = base_id
        self.cur = base
        self.rows = None
        self.tracks = {}
        self.warnings = []
        self.v0 = volume_of(base) if base is not None else 0.0

    def op(self, kind, tool, labels=None):
        maker = feat.run_boolean("fuse" if kind == "fuse" else "cut", self.cur, tool)
        res = maker.Shape()
        feat.check_result(res, "sheet metal feature")
        rows = feat.history_rows(maker, self.cur, store.build_maps(self.cur), store.build_maps(res))
        self.rows = rows if self.rows is None else compose(self.rows, rows)
        for key in list(self.tracks):
            self.tracks[key] = advance(maker, self.tracks[key])
        for key, face in (labels or {}).items():
            self.tracks.setdefault(key, [])
            self.tracks[key] = self.tracks[key] + advance(maker, [face])
        self.cur = res

    def first_solid_check(self):
        if store.count_of(self.cur, TopAbs_SOLID) > 1:
            self.warnings.append("The result has more than one solid.")

    def result(self, bends, extra=None):
        res = self.cur
        feat.check_result(res, "sheet metal feature")
        ident = store.put(res)
        om = store.maps_of(ident)
        created = {}
        index_of = {}
        for label, faces in self.tracks.items():
            for k, face in enumerate(faces):
                i = om["faces"].FindIndex(face)
                if i > 0:
                    if not label.startswith("_"):
                        created.setdefault(str(i - 1), label if k == 0 else "%s#%d" % (label, k))
                    index_of.setdefault(label, i - 1)
        rows = self.rows or {"faces": {}, "edges": {}}
        out = {"ok": True, "id": ident, "summary": store.summarize(res), "history": {"inputs": [{"id": self.base_id, **rows}] if self.base_id else []}, "created": {"faces": created, "edges": {}}, "adjacency": feat.adjacency(ident), "warnings": list(self.warnings), "errors": []}
        for b in bends:
            labels = b.pop("labels", {})
            faces = {}
            for slot in ("inner", "outer", "parent", "child"):
                lab = labels.get(slot)
                if isinstance(lab, int):
                    faces[slot] = lab
                else:
                    faces[slot] = index_of.get(lab) if lab else None
            b["faces"] = faces
            for slot in list(faces):
                if "base_" + slot in b:
                    idx = b.pop("base_" + slot)
                    faces[slot] = self.base_to_final(idx) if idx is not None else faces[slot]
        out["bends"] = bends
        out["volume"] = volume_of(res)
        out["volume_before"] = self.v0
        if extra:
            out.update(extra)
        return out

    def base_to_final(self, idx):
        if self.rows is None:
            return idx
        row = self.rows["faces"].get(str(idx))
        if not row or not row["to"]:
            return None
        return row["to"][0]


def face_of(base_id, idx):
    maps = store.maps_of(base_id)
    if idx is None or not 0 <= int(idx) < maps["faces"].Extent():
        raise RuntimeError("Face %s is not in the body." % idx)
    return TopoDS.Face(maps["faces"].FindKey(int(idx) + 1))


def normal_at(face, p):
    surf = BRep_Tool.Surface_s(face)
    proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*p), surf)
    if proj.NbPoints() == 0:
        return None
    u, v = proj.LowerDistanceParameters()
    props = GeomLProp_SLProps(surf, u, v, 1, 1e-9)
    if not props.IsNormalDefined():
        return None
    n = props.Normal()
    vec = (n.X(), n.Y(), n.Z())
    if face.Orientation() == TopAbs_REVERSED:
        vec = (-vec[0], -vec[1], -vec[2])
    return vec


def plane_normal(face):
    v = feat.face_plane_dir(face)
    return None if v is None else unit((v.X(), v.Y(), v.Z()))


def surface_kind(face):
    return BRepAdaptor_Surface(face).GetType()


def face_edges(base_id):
    adj = feat.adjacency(base_id)
    out = {}
    for e, faces in enumerate(adj):
        for f in faces:
            out.setdefault(f, []).append(e)
    return adj, out


def skin_set(base_id, ref_idx):
    maps = store.maps_of(base_id)
    adj, fedges = face_edges(base_id)
    seen = {int(ref_idx)}
    queue = [int(ref_idx)]
    while queue:
        f = queue.pop()
        ff = face_of(base_id, f)
        for e in fedges.get(f, []):
            if len(adj[e]) != 2:
                continue
            g = adj[e][0] if adj[e][1] == f else adj[e][1]
            if g in seen:
                continue
            gf = face_of(base_id, g)
            if surface_kind(gf) not in (GeomAbs_Plane, GeomAbs_Cylinder) or surface_kind(ff) not in (GeomAbs_Plane, GeomAbs_Cylinder):
                continue
            m = edge_mid(TopoDS.Edge(maps["edges"].FindKey(e + 1)))
            n1, n2 = normal_at(ff, m), normal_at(gf, m)
            if n1 is None or n2 is None:
                continue
            if dot(n1, n2) > 0.9999:
                seen.add(g)
                queue.append(g)
    return seen


def inside_face(face, p):
    return BRepClass_FaceClassifier(face, gp_Pnt(*p), 1e-7).State() in (TopAbs_IN, TopAbs_ON)


def strip_here(face, n, t, mid, thickness):
    step = unit(cross(n, t))
    for sign in (1.0, -1.0):
        d = mul(step, sign)
        if inside_face(face, add(mid, mul(d, 0.5 * thickness))):
            return inside_face(face, add(mid, mul(d, 0.95 * thickness))) and not inside_face(face, add(mid, mul(d, 1.2 * thickness)))
    return False


def opposite_skin(base_id, skin_idx, point, thickness):
    n = plane_normal(face_of(base_id, skin_idx))
    if n is None:
        return None
    maps = store.maps_of(base_id)
    target = sub(point, mul(n, thickness))
    for i in range(maps["faces"].Extent()):
        if i == skin_idx:
            continue
        face = TopoDS.Face(maps["faces"].FindKey(i + 1))
        if surface_kind(face) != GeomAbs_Plane:
            continue
        m = plane_normal(face)
        if m is None or dot(m, n) > -1.0 + 1e-6:
            continue
        pl = BRepAdaptor_Surface(face).Plane()
        origin = tup(pl.Location())
        if abs(dot(sub(target, origin), m)) > 1e-5:
            continue
        surf = BRep_Tool.Surface_s(face)
        proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*target), surf)
        if proj.NbPoints() == 0:
            continue
        u, v = proj.LowerDistanceParameters()
        cl = BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-6)
        if cl.State() in (TopAbs_IN, TopAbs_ON):
            return i
    return None


def edge_context(base_id, base, idx, thickness, adj):
    maps = store.maps_of(base_id)
    if not 0 <= idx < maps["edges"].Extent():
        raise RuntimeError("Edge %d is not in the body." % idx)
    edge = TopoDS.Edge(maps["edges"].FindKey(idx + 1))
    c = BRepAdaptor_Curve(edge)
    if c.GetType() != GeomAbs_Line:
        raise RuntimeError("A flange needs a straight edge of the sheet.")
    a, b = tup(c.Value(c.FirstParameter())), tup(c.Value(c.LastParameter()))
    t = unit(sub(b, a))
    if len(adj[idx]) != 2:
        raise RuntimeError("The edge is not shared by exactly two faces.")
    ends, skins = [], []
    mid = tup(c.Value((c.FirstParameter() + c.LastParameter()) / 2.0))
    for fi in adj[idx]:
        face = face_of(base_id, fi)
        n = plane_normal(face)
        if n is None:
            raise RuntimeError("A flange edge must lie between flat faces.")
        (ends if strip_here(face, n, t, mid, thickness) else skins).append((fi, n))
    if len(ends) != 1 or len(skins) != 1:
        raise RuntimeError("Pick an edge between the thickness face and a face of the sheet; the sheet thickness is %.6g." % thickness)
    d = ends[0][1]
    ns = skins[0][1]
    if abs(dot(d, t)) > 1e-6 or abs(dot(d, ns)) > 1e-6:
        raise RuntimeError("The edge is not square to the sheet; only square edges take a flange.")
    return {"idx": idx, "a": a, "b": b, "t": t, "d": d, "ns": ns, "skin": skins[0][0], "end": ends[0][0], "len": norm(sub(b, a))}


def tan_half(angle):
    if angle >= math.pi - 1e-6:
        raise RuntimeError("A flange angle must be under 180 degrees.")
    return math.tan(angle / 2.0)


def position_u(position, r_in, thickness, angle, offset):
    if position == "material_inside":
        return -(r_in + thickness) * tan_half(angle) + offset
    if position == "material_outside":
        return -r_in * tan_half(angle) + offset
    if position == "bend_outside":
        return offset
    raise RuntimeError("The flange position is material_inside, material_outside or bend_outside.")


def straight_length(h, angle, r_in, thickness, datum):
    if datum == "outside":
        return h - (r_in + thickness) * tan_half(angle)
    if datum == "inside":
        return h - r_in * tan_half(angle)
    if datum == "tangent":
        return h
    raise RuntimeError("The length reference is outside, inside or tangent.")


def width_range(p, ctx, frame):
    wa, wb = frame.local(ctx["a"])[2], frame.local(ctx["b"])[2]
    lo, hi = min(wa, wb), max(wa, wb)
    mode = str(p.get("width_mode") or "full")
    if mode == "full":
        return lo, hi, lo, hi
    if mode == "centered":
        w = num(p, "width", None, 1e-6)
        if w is None or w > hi - lo + 1e-9:
            raise RuntimeError("The flange width must be positive and not longer than the edge.")
        mid = (lo + hi) / 2.0
        return mid - w / 2.0, mid + w / 2.0, lo, hi
    if mode == "offsets":
        a = lo + (num(p, "offset1", 0.0, 0.0) or 0.0)
        b = hi - (num(p, "offset2", 0.0, 0.0) or 0.0)
        if b - a < 1e-6:
            raise RuntimeError("The flange offsets leave no width.")
        return a, b, lo, hi
    raise RuntimeError("The width mode is full, centered or offsets.")


def relief_tools(p, frame, thickness, u_t, a, b, lo, hi, info):
    spec = p.get("relief") or {}
    kind = str(spec.get("type") or "rect")
    if kind == "none" or not spec.get("auto", True) or u_t >= -1e-9:
        return []
    ratio = float(spec.get("width_ratio", 0.5))
    extra = float(spec.get("extra", 0.5))
    remnant = float(spec.get("remnant", 0.0))
    gap = float(spec.get("gap", thickness / 10.0))
    width = gap if kind == "tear" else max(ratio * thickness, 1e-3)
    m = max(0.25 * thickness, 0.05)
    depth_u = u_t - extra
    tools = []
    for end, room in (("start", a - lo), ("end", hi - b)):
        if room <= 1e-6:
            continue
        wr = min(width, room)
        if room - wr < max(remnant, 0.0) + 1e-9 and room - wr > 0:
            wr = room
        w0, w1 = (a - wr, a) if end == "start" else (b, b + wr)
        if kind == "obround" and wr > 1e-6:
            r = wr / 2.0
            tools.append(box_in(frame, depth_u + r, m, -thickness - m, m, w0, w1))
            tools.append(cylinder_v(frame, depth_u + r, (w0 + w1) / 2.0, r, -thickness - m, m))
        else:
            tools.append(box_in(frame, depth_u, m, -thickness - m, m, w0, w1))
        info.append({"type": kind, "at": end, "width": wr, "depth": -depth_u, "centre": list(frame.pt(depth_u / 2.0, -thickness / 2.0, (w0 + w1) / 2.0))})
    return tools


def sheet_params(p):
    T = num(p, "thickness", None, 1e-4)
    if T is None:
        raise RuntimeError("The sheet thickness is missing.")
    R = num(p, "radius", None, 1e-6)
    if R is None:
        raise RuntimeError("The inside radius is missing.")
    return T, R


def flange_job(p, planner, kind):
    base_id = p.get("id")
    if not base_id:
        raise RuntimeError("A flange needs a sheet body.")
    base = store.shape_of(base_id)
    T, R = sheet_params(p)
    edges = [int(i) for i in (p.get("edges") or [])]
    if not edges:
        raise RuntimeError("Choose at least one edge.")
    if len(edges) > MAX_EDGES:
        raise RuntimeError("Too many edges.")
    if len(edges) > 1 and str(p.get("width_mode") or "full") != "full":
        raise RuntimeError("Several edges take the full edge width.")
    flip = bool(p.get("flip"))
    adj = feat.adjacency(base_id)
    ref_idx = p.get("ref_face")
    ref_set = skin_set(base_id, ref_idx) if ref_idx is not None else None
    build = Build(base_id, base)
    cuts, fuses = [], []
    bends, paths, reliefs = [], [], []
    seg_no, bend_no = 0, 0
    placed = []
    gap = float((p.get("relief") or {}).get("gap", T / 10.0))
    for idx in edges:
        ctx = edge_context(base_id, base, idx, T, adj)
        concave_is_skin = not flip
        v = ctx["ns"] if not flip else mul(ctx["ns"], -1.0)
        origin = ctx["a"] if not flip else sub(ctx["a"], mul(ctx["ns"], T))
        frame = Frame(origin, ctx["d"], v)
        elements, u_t, tags = planner(p, T, R)
        a, b, lo, hi = width_range(p, ctx, frame)
        if len(edges) > 1:
            for prev in placed:
                shared = None
                for q in (ctx["a"], ctx["b"]):
                    for r in (prev["ctx"]["a"], prev["ctx"]["b"]):
                        if norm(sub(q, r)) < 1e-6:
                            shared = q
                if shared is None or prev["inward"] <= 1e-9 or max(0.0, -u_t) <= 1e-9:
                    continue
                wl = frame.local(shared)[2]
                trim = prev["inward"] + gap
                if abs(wl - lo) < 1e-6:
                    a = max(a, lo + trim)
                elif abs(wl - hi) < 1e-6:
                    b = min(b, hi - trim)
        if b - a < 1e-6:
            raise RuntimeError("The flange on edge %d has no width left after the corner clearance." % idx)
        u_s = min(u_t, 0.0)
        sec = Section(frame, T, (u_s, 0.0), 0.0, -1, (ref_set is None and concave_is_skin) or (ref_set is not None and ((ctx["skin"] in ref_set) == concave_is_skin)), seg_no, bend_no)
        if u_t > 1e-9:
            sec.flat(u_t)
        for el in elements:
            if el[0] == "flat":
                sec.flat(el[1])
            else:
                sec.bend(el[1], el[2], +1)
        tool, roles = sec.solid(a, b)
        seg_no, bend_no = sec.seg, sec.bend_no
        if u_t < -1e-9:
            cuts.append(box_in(frame, u_t, max(0.25 * T, 0.05), -T - max(0.25 * T, 0.05), max(0.25 * T, 0.05), a, b))
        relief_info = []
        cuts.extend(relief_tools(p, frame, T, u_t, a, b, lo, hi, relief_info))
        reliefs.extend(relief_info)
        fuses.append((tool, roles))
        opp = opposite_skin(base_id, ctx["skin"], mul(add(ctx["a"], ctx["b"]), 0.5), T)
        concave_skin = opp if flip else ctx["skin"]
        other_skin = ctx["skin"] if flip else opp
        parent = concave_skin if sec.pref else other_skin
        infos = sec.bend_infos(a, b)
        for k, info in enumerate(infos):
            info["type"] = tags.get(info["j"] - (bend_no - len(infos)), "bend")
            info["edge"] = idx
            if k == 0 and info["labels"]["parent"] is None and parent is not None:
                info["base_parent"] = parent
        bends.extend(infos)
        paths.append({"frame": frame.data(), "w": [a, b], "path": sec.path_summary(), "edge": idx})
        placed.append({"ctx": ctx, "inward": max(0.0, -u_t)})
    for tool in cuts:
        build.op("cut", tool)
    for tool, roles in fuses:
        labels = {}
        for face, role in roles:
            labels.setdefault(role, face)
        build.op("fuse", tool, labels)
    build.first_solid_check()
    return build.result(bends, {"sections": paths, "reliefs": reliefs, "kind": kind})


def edge_flange_plan(p, T, R):
    angle = math.radians(num(p, "angle", 90.0, 0.5, 175.0))
    h = num(p, "length", None, 1e-6)
    if h is None:
        raise RuntimeError("The flange length is missing.")
    s = straight_length(h, angle, R, T, str(p.get("length_ref") or "outside"))
    if s < -1e-9:
        raise RuntimeError("The flange is shorter than its bend; make it longer than %.4g." % (h - s))
    u_t = position_u(str(p.get("position") or "material_inside"), R, T, angle, num(p, "offset", 0.0) or 0.0)
    return [("bend", R, angle), ("flat", max(s, 0.0))], u_t, {}


def hem_plan(p, T, R):
    kind = str(p.get("hem") or "closed")
    gap = num(p, "gap", None, 0.0)
    min_gap = num(p, "min_gap", T / 10.0, 1e-4) or T / 10.0
    leg = num(p, "length", 0.0, 0.0) or 0.0
    if kind == "closed":
        g = max(min_gap, 1e-3)
        r_h, angle, tag = g / 2.0, math.pi, "hem"
    elif kind == "open":
        g = gap if gap else T
        if g <= 1e-6:
            raise RuntimeError("An open hem needs a gap above zero.")
        r_h, angle, tag = g / 2.0, math.pi, "hem"
    elif kind in ("teardrop", "rolled"):
        r_h = num(p, "hem_radius", R, 1e-6)
        angle = math.radians(num(p, "angle", 215.0 if kind == "teardrop" else 270.0, 181.0, 330.0))
        tag = kind
    else:
        raise RuntimeError("A hem is closed, open, teardrop or rolled.")
    if kind != "rolled" and leg <= 1e-6:
        raise RuntimeError("The hem needs a return length above zero.")
    pos = str(p.get("position") or "bend_outside")
    off = num(p, "offset", 0.0) or 0.0
    if pos == "material_inside":
        u_t = -(r_h + T) + off
    elif pos == "material_outside":
        u_t = -r_h + off
    elif pos == "bend_outside":
        u_t = off
    else:
        raise RuntimeError("The hem position is material_inside, material_outside or bend_outside.")
    elements = [("bend", r_h, angle)]
    if kind != "rolled":
        elements.append(("flat", leg))
    return elements, u_t, {1: tag}


def sm_edge_flange(p):
    return flange_job(p, edge_flange_plan, "edge_flange")


def sm_hem(p):
    return flange_job(p, hem_plan, "hem")


def sm_miter_flange(p):
    base_id = p.get("id")
    if not base_id:
        raise RuntimeError("A flange needs a sheet body.")
    base = store.shape_of(base_id)
    T, R = sheet_params(p)
    edges = [int(i) for i in (p.get("edges") or [])]
    if not edges:
        raise RuntimeError("Choose the chain of edges.")
    flip = bool(p.get("flip"))
    adj = feat.adjacency(base_id)
    ref_idx = p.get("ref_face")
    ref_set = skin_set(base_id, ref_idx) if ref_idx is not None else None
    gap = num(p, "gap", None, 0.0)
    if gap is None:
        gap = T / 10.0
    ctxs = [edge_context(base_id, base, i, T, adj) for i in edges]
    elements, u_t, _tags = edge_flange_plan(p, T, R)
    reach = sum(el[1] if el[0] == "flat" else (R + T) * 3.0 for el in elements) + abs(u_t) + 4.0 * (R + T)
    first_skin = ctxs[0]["skin"]
    for c in ctxs[1:]:
        if c["skin"] != first_skin:
            raise RuntimeError("The edges of a miter flange must lie on one face.")
    ends_taken = []
    for i in range(len(ctxs) - 1):
        c, n = ctxs[i], ctxs[i + 1]
        link = None
        for q in (c["a"], c["b"]):
            for r in (n["a"], n["b"]):
                if norm(sub(q, r)) < 1e-6:
                    link = q
        if link is None:
            raise RuntimeError("Edge %d does not meet edge %d; a miter flange follows a connected chain." % (c["idx"], n["idx"]))
        ends_taken.append(link)
    build = Build(base_id, base)
    cuts, fuses, bends, paths = [], [], [], []
    seg_no, bend_no = 0, 0
    big = 50.0 * (reach + T + max(c["len"] for c in ctxs))
    for k, ctx in enumerate(ctxs):
        v = ctx["ns"] if not flip else mul(ctx["ns"], -1.0)
        origin = ctx["a"] if not flip else sub(ctx["a"], mul(ctx["ns"], T))
        frame = Frame(origin, ctx["d"], v)
        wa, wb = frame.local(ctx["a"])[2], frame.local(ctx["b"])[2]
        lo, hi = min(wa, wb), max(wa, wb)
        w_lo, w_hi = lo, hi
        trims = []
        for pos in (k - 1, k):
            if 0 <= pos < len(ends_taken):
                other = ctxs[pos] if pos == k - 1 else ctxs[k + 1]
                link = ends_taken[pos]
                wl = frame.local(link)[2]
                if abs(wl - lo) < 1e-6:
                    w_lo = lo - reach
                else:
                    w_hi = hi + reach
                away = unit(sub(ctx["b"], ctx["a"])) if norm(sub(link, ctx["a"])) < 1e-6 else unit(sub(ctx["a"], ctx["b"]))
                bis = add(ctx["d"], other["d"])
                if norm(bis) < 1e-6:
                    continue
                bis = unit(bis)
                m = unit(cross(v, bis))
                if dot(m, away) < 0:
                    m = mul(m, -1.0)
                trims.append((link, m, bis))
        sec = Section(frame, T, (min(u_t, 0.0), 0.0), 0.0, -1, (ref_set is None and not flip) or (ref_set is not None and ((ctx["skin"] in ref_set) == (not flip))), seg_no, bend_no)
        if u_t > 1e-9:
            sec.flat(u_t)
        for el in elements:
            if el[0] == "flat":
                sec.flat(el[1])
            else:
                sec.bend(el[1], el[2], +1)
        tool, roles = sec.solid(w_lo, w_hi)
        seg_no, bend_no = sec.seg, sec.bend_no
        for link, m, bis in trims:
            ydir = cross(m, bis)
            ax = gp_Ax2(gp_Pnt(*sub(sub(add(link, mul(m, gap / 2.0 - big)), mul(bis, big / 2.0)), mul(ydir, big / 2.0))), gp_Dir(*m), gp_Dir(*bis))
            half = BRepPrimAPI_MakeBox(ax, big, big, big).Shape()
            cut = BRepAlgoAPI_Cut(tool, half)
            if not cut.IsDone():
                raise RuntimeError("The miter cut could not be made.")
            kept = cut.Shape()
            fmap = store.build_maps(kept)["faces"]
            moved = []
            for face, role in roles:
                if cut.IsDeleted(face):
                    continue
                mods = [TopoDS.Face(x) for x in cut.Modified(face) if x.ShapeType() == TopAbs_FACE]
                moved.extend((x, role) for x in (mods if mods else [face]))
            tool, roles = kept, moved
        if u_t < -1e-9:
            mpad = max(0.25 * T, 0.05)
            cuts.append(box_in(frame, u_t, mpad, -T - mpad, mpad, lo, hi))
        opp = opposite_skin(base_id, ctx["skin"], mul(add(ctx["a"], ctx["b"]), 0.5), T)
        concave_skin = opp if flip else ctx["skin"]
        other_skin = ctx["skin"] if flip else opp
        parent = concave_skin if sec.pref else other_skin
        for k, info in enumerate(sec.bend_infos(w_lo, w_hi)):
            info["type"] = "bend"
            info["edge"] = ctx["idx"]
            if k == 0 and info["labels"]["parent"] is None and parent is not None:
                info["base_parent"] = parent
            bends.append(info)
        paths.append({"frame": frame.data(), "w": [w_lo, w_hi], "path": sec.path_summary(), "edge": ctx["idx"]})
        fuses.append((tool, roles))
    for tool in cuts:
        build.op("cut", tool)
    for tool, roles in fuses:
        labels = {}
        for face, role in roles:
            labels.setdefault(role, face)
        build.op("fuse", tool, labels)
    build.first_solid_check()
    return build.result(bends, {"sections": paths, "reliefs": [], "kind": "miter_flange"})


def path_elements(segs, T, R, side):
    n = len(segs)
    info = []
    for s in segs:
        a, b = s["a"], s["b"]
        chord = math.atan2(b[1] - a[1], b[0] - a[0])
        if s.get("t") == "line" or abs(float(s.get("bulge", 0.0) or 0.0)) < 1e-12:
            info.append({"kind": "line", "len": math.hypot(b[0] - a[0], b[1] - a[1]), "h0": chord, "h1": chord})
        else:
            bulge = float(s["bulge"])
            sweep = 4.0 * math.atan(bulge)
            c = math.hypot(b[0] - a[0], b[1] - a[1])
            rho = c / (2.0 * math.sin(abs(sweep) / 2.0))
            info.append({"kind": "arc", "sweep": sweep, "rho": rho, "len": c, "h0": chord - sweep / 2.0, "h1": chord + sweep / 2.0})
    def wrap(x):
        while x > math.pi:
            x -= 2.0 * math.pi
        while x < -math.pi:
            x += 2.0 * math.pi
        return x
    corners = []
    trims = [[0.0, 0.0] for _ in info]
    for i in range(1, n):
        d = wrap(info[i]["h0"] - info[i - 1]["h1"])
        if abs(d) < 1e-4:
            corners.append(None)
            continue
        if info[i]["kind"] == "arc" or info[i - 1]["kind"] == "arc":
            raise RuntimeError("Arcs in a base flange profile must join their neighbours tangentially.")
        if abs(d) > math.radians(175.0):
            raise RuntimeError("A corner of the profile turns back on itself.")
        tau = 1 if d > 0 else -1
        rp = R + (T if side * tau == 1 else 0.0)
        tl = rp * math.tan(abs(d) / 2.0)
        trims[i - 1][1] = tl
        trims[i][0] = tl
        corners.append((tau, abs(d)))
    elements = []
    for i, s in enumerate(info):
        if s["kind"] == "line":
            ln = s["len"] - trims[i][0] - trims[i][1]
            if ln < -1e-9:
                raise RuntimeError("Segment %d of the profile is too short for the bends at its ends." % (i + 1))
            elements.append(("flat", max(ln, 0.0)))
        else:
            tau = 1 if s["sweep"] > 0 else -1
            r_in = s["rho"] - (T if side * tau == 1 else 0.0)
            if r_in <= 1e-9:
                raise RuntimeError("An arc of the profile is smaller than the sheet thickness.")
            elements.append(("bend", r_in, abs(s["sweep"]), tau))
        if i < n - 1 and corners[i] is not None:
            tau, ang = corners[i]
            elements.append(("bend", R, ang, tau))
    return elements, info[0]["h0"]


def sm_base_flange(p):
    base_id = p.get("id")
    base = store.shape_of(base_id) if base_id else None
    T, R = sheet_params(p)
    profile = p.get("profile") or {}
    side = str(p.get("side") or "side1")
    if profile.get("regions"):
        flip = side == "side2"
        mid = side == "mid"
        q = {"id": base_id, "op": "add", "profile": profile, "flip": flip, "end1": {"type": "mid" if mid else "blind", "depth": T}, "depth1": T}
        out = feat.extrude(q)
        rename = {"cap:end": "seg0:ref", "cap:end2": "seg0:opp"} if mid else {"cap:start": "seg0:ref", "cap:end": "seg0:opp"}
        faces = {}
        for idx, role in out["created"]["faces"].items():
            head, sep, tail = role.partition("#")
            faces[idx] = rename.get(head, head) + sep + tail
        out["created"]["faces"] = faces
        out["bends"] = []
        out["sections"] = []
        out["reliefs"] = []
        out["ref_role"] = "seg0:ref"
        out["kind"] = "plate"
        return out
    opened = profile.get("open") or []
    if not opened:
        raise RuntimeError("The sketch has no profile; draw a closed shape for a plate or an open path for a bent section.")
    if len(opened) > 1:
        raise RuntimeError("An open profile must be one connected path.")
    if side == "mid":
        raise RuntimeError("An open profile puts its thickness on one side of the path; choose side 1 or side 2.")
    s_sign = 1 if side == "side1" else -1
    elements, h0 = path_elements(opened[0]["segs"], T, R, s_sign)
    depth = num(p, "depth", None, 1e-6)
    if depth is None:
        raise RuntimeError("The sheet width is missing.")
    fr = profile.get("frame") or {}
    ax = feat.frame_ax2(fr)
    xd, nd = tup(ax.XDirection()), tup(ax.Direction())
    yd = cross(nd, xd)
    frame = Frame(tup(ax.Location()), xd, yd)
    first = opened[0]["segs"][0]
    sec = Section(frame, T, (first["a"][0], first["a"][1]), h0, s_sign, True)
    for el in elements:
        if el[0] == "flat":
            sec.flat(el[1])
        else:
            sec.bend(el[1], el[2], el[3])
    last = opened[0]["segs"][-1]
    pe, _he = sec.end_pose()
    if math.hypot(pe[0] - last["b"][0], pe[1] - last["b"][1]) > 1e-4 * max(1.0, depth):
        raise RuntimeError("The bent path does not end where the sketch ends; check for very short segments.")
    mode = str(p.get("depth_mode") or "blind")
    if mode == "mid":
        w0, w1 = -depth / 2.0, depth / 2.0
    elif bool(p.get("flip_depth")):
        w0, w1 = -depth, 0.0
    else:
        w0, w1 = 0.0, depth
    tool, roles = sec.solid(w0, w1)
    build = Build(base_id, base)
    labels = {}
    for face, role in roles:
        labels.setdefault(role, face)
    if base is None:
        feat.check_result(tool, "base flange")
        ident = store.put(tool)
        om = store.maps_of(ident)
        created, index_of = {}, {}
        for role, face in labels.items():
            i = om["faces"].FindIndex(face)
            if i > 0:
                created[str(i - 1)] = role
                index_of[role] = i - 1
        bends = sec.bend_infos(w0, w1)
        for b in bends:
            lab = b.pop("labels")
            b["faces"] = {k: (index_of.get(v) if v else None) for k, v in lab.items()}
            b["type"] = "bend"
        out = {"ok": True, "id": ident, "summary": store.summarize(tool), "history": {"inputs": []}, "created": {"faces": created, "edges": {}}, "adjacency": feat.adjacency(ident), "warnings": [], "errors": [], "bends": bends, "volume": volume_of(tool), "volume_before": 0.0}
    else:
        build.op("fuse", tool, labels)
        bends = sec.bend_infos(w0, w1)
        for b in bends:
            b["type"] = "bend"
        out = build.result(bends)
    out["sections"] = [{"frame": frame.data(), "w": [w0, w1], "path": sec.path_summary()}]
    out["reliefs"] = []
    out["ref_role"] = next((sec.ref_role(pt) for pt in sec.parts if pt["t"] == "flat"), None)
    out["kind"] = "open"
    return out


def strip_job(p, kind):
    base_id = p.get("id")
    if not base_id:
        raise RuntimeError("A bend needs a sheet body.")
    base = store.shape_of(base_id)
    T, R = sheet_params(p)
    face = face_of(base_id, p.get("face"))
    ns = plane_normal(face)
    if ns is None:
        raise RuntimeError("Sketch the bend line on a flat face of the sheet.")
    line = p.get("line") or {}
    pa, pb = tuple(float(x) for x in line["a"]), tuple(float(x) for x in line["b"])
    pl = BRepAdaptor_Surface(face).Plane()
    origin_pl = tup(pl.Location())
    pa = sub(pa, mul(ns, dot(sub(pa, origin_pl), ns)))
    pb = sub(pb, mul(ns, dot(sub(pb, origin_pl), ns)))
    ldir = unit(sub(pb, pa))
    flip = bool(p.get("flip"))
    v = ns if not flip else mul(ns, -1.0)
    u = unit(cross(v, ldir))
    if bool(p.get("flip_side")):
        u = mul(u, -1.0)
    origin = pa if not flip else sub(pa, mul(ns, T))
    frame = Frame(origin, u, v)
    angle = math.radians(num(p, "angle", 90.0, 0.5, 175.0))
    ba = num(p, "ba", None, 1e-9)
    if ba is None:
        raise RuntimeError("The bend allowance is missing.")
    ref_idx = p.get("ref_face")
    ref_set = skin_set(base_id, ref_idx) if ref_idx is not None else None
    pref = (ref_set is None and not flip) or (ref_set is not None and ((int(p["face"]) in ref_set) == (not flip)))
    if kind == "jog":
        h = num(p, "offset", None, 1e-6)
        if h is None:
            raise RuntimeError("The jog offset is missing.")
        sr = (h - (2.0 * R + T) * (1.0 - math.cos(angle))) / math.sin(angle)
        if sr < -1e-9:
            raise RuntimeError("The jog offset %.4g is too small for the bend radius and angle; it must exceed %.4g." % (h, (2.0 * R + T) * (1.0 - math.cos(angle))))
        flat_len = 2.0 * ba + max(sr, 0.0)
        elements = [("bend", R, angle, +1), ("flat", max(sr, 0.0)), ("bend", R, angle, -1)]
    else:
        flat_len = ba
        elements = [("bend", R, angle, +1)]
    half = flat_len / 2.0
    box = base_bbox_local(base, frame)
    pad = 4.0 * (norm(sub(box[1], box[0])) + 1.0)
    slab = box_in(frame, -half, half, -pad, pad, box[0][2] - pad, box[1][2] + pad)
    common = BRepAlgoAPI_Common(base, slab)
    if not common.IsDone():
        raise RuntimeError("The bend strip could not be isolated.")
    strip = common.Shape()
    sv = volume_of(strip)
    if sv <= 1e-9:
        raise RuntimeError("The bend line does not cross the sheet.")
    verts = store.build_maps(strip)["vertices"]
    ws, us, vs = [], [], []
    for i in range(1, verts.Extent() + 1):
        lp = frame.local(tup(BRep_Tool.Pnt_s(TopoDS.Vertex(verts.FindKey(i)))))
        us.append(lp[0])
        vs.append(lp[1])
        ws.append(lp[2])
    w0, w1 = min(ws), max(ws)
    tol = 1e-5 * max(1.0, T)
    if max(vs) > tol or min(vs) < -T - tol or abs(sv - T * flat_len * (w1 - w0)) > 1e-4 * sv:
        raise RuntimeError("The bend strip is not plain flat sheet; the line crosses holes, bends or a stepped outline. Move the line or bend before cutting features.")
    sec = Section(frame, T, (-half, 0.0), 0.0, -1, pref)
    for el in elements:
        if el[0] == "flat":
            sec.flat(el[1])
        else:
            sec.bend(el[1], el[2], el[3])
    (eu, ev), eh = sec.end_pose()
    cut = BRepAlgoAPI_Cut(base, slab)
    cut.SetToFillHistory(True)
    cut.Build()
    if not cut.IsDone():
        raise RuntimeError("The sheet could not be split at the bend line.")
    pieces = []
    exp = store.ShapeMap()
    TopExp.MapShapes_s(cut.Shape(), TopAbs_SOLID, exp)
    for i in range(1, exp.Extent() + 1):
        pieces.append(exp.FindKey(i))
    if len(pieces) != 2:
        raise RuntimeError("The bend line must run across the whole sheet and split it in two; it made %d pieces." % len(pieces))
    cents = []
    for s in pieces:
        pr = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, pr)
        cents.append(frame.local(tup(pr.CentreOfMass()))[0])
    fixed, moving = (pieces[0], pieces[1]) if cents[0] < cents[1] else (pieces[1], pieces[0])
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(*frame.pt(half, 0.0, 0.0)), gp_Dir(*frame.w)), eh)
    shift = gp_Trsf()
    shift.SetTranslation(gp_Vec(*frame.dr(eu - half, ev - 0.0)))
    full = gp_Trsf()
    full = shift.Multiplied(trsf)
    tr = BRepBuilderAPI_Transform(moving, full, True)
    moved = tr.Shape()
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    bld.Add(comp, fixed)
    bld.Add(comp, moved)
    rows_a = feat.history_rows(cut, base, store.build_maps(base), store.build_maps(cut.Shape()))

    mov_maps = store.build_maps(moving)

    def second(shape, key):
        if mov_maps[key].FindIndex(shape) > 0:
            return [tr.ModifiedShape(shape)]
        return [shape]

    rows_b = rows_by(cut.Shape(), comp, second)
    tool, roles = sec.solid(w0, w1)
    fuse = BRepAlgoAPI_Fuse()
    a = ops.ShapeList()
    a.Append(fixed)
    a.Append(moved)
    t = ops.ShapeList()
    t.Append(tool)
    fuse.SetArguments(a)
    fuse.SetTools(t)
    fuse.SetRunParallel(True)
    fuse.SetNonDestructive(True)
    fuse.SetToFillHistory(True)
    fuse.Build()
    if not fuse.IsDone():
        raise RuntimeError("The bend could not be joined to the sheet.")
    fuse.SimplifyResult(True, True, 1e-6)
    res = fuse.Shape()
    feat.check_result(res, "bend")
    if store.count_of(res, TopAbs_SOLID) != 1:
        raise RuntimeError("The bend left more than one solid.")
    rows_c = feat.history_rows(fuse, comp, store.build_maps(comp), store.build_maps(res))
    rows = compose(compose(rows_a, rows_b), rows_c)
    build = Build(base_id, base)
    build.rows = rows
    build.cur = res
    labels = {}
    for face_, role in roles:
        labels.setdefault(role, face_)
    for key, f_ in labels.items():
        build.tracks[key] = advance(fuse, [f_])
    bends = sec.bend_infos(w0, w1)
    spr = GProp_GProps()
    BRepGProp.VolumeProperties_s(strip, spr)
    top_pt = add(tup(spr.CentreOfMass()), mul(ns, T / 2.0))
    face_idx = int(p["face"])
    ref_base = face_idx if (ref_set is None or face_idx in ref_set) else opposite_skin(base_id, face_idx, top_pt, T)
    cutmaps = store.build_maps(cut.Shape())
    pf, cf = [], []
    row = rows_a["faces"].get(str(ref_base)) if ref_base is not None else None
    for ci in (row["to"] if row else []):
        f_ = TopoDS.Face(cutmaps["faces"].FindKey(ci + 1))
        if mov_maps["faces"].FindIndex(f_) > 0:
            cf.append(TopoDS.Face(tr.ModifiedShape(f_)))
        else:
            pf.append(f_)
    build.tracks["_parent"] = advance(fuse, pf)
    build.tracks["_child"] = advance(fuse, cf)
    for b in bends:
        b["type"] = "sketched" if kind == "sketched_bend" else "jog"
    if bends[0]["labels"]["parent"] is None:
        bends[0]["labels"]["parent"] = "_parent"
    if bends[-1]["labels"]["child"] is None:
        bends[-1]["labels"]["child"] = "_child"
    out = build.result(bends, {"sections": [{"frame": frame.data(), "w": [w0, w1], "path": sec.path_summary()}], "reliefs": [], "kind": kind, "flat_consumed": flat_len})
    return out


def base_bbox_local(shape, frame):
    verts = store.build_maps(shape)["vertices"]
    lo = [1e300, 1e300, 1e300]
    hi = [-1e300, -1e300, -1e300]
    for i in range(1, verts.Extent() + 1):
        lp = frame.local(tup(BRep_Tool.Pnt_s(TopoDS.Vertex(verts.FindKey(i)))))
        for k in range(3):
            lo[k] = min(lo[k], lp[k])
            hi[k] = max(hi[k], lp[k])
    return lo, hi


def sm_sketched_bend(p):
    return strip_job(p, "sketched_bend")


def sm_jog(p):
    return strip_job(p, "jog")


def sm_bend_relief(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    T = num(p, "thickness", None, 1e-4)
    kind = str(p.get("type") or "rect")
    if kind == "none":
        raise RuntimeError("Choose a relief type.")
    ratio = num(p, "width_ratio", 0.5, 1e-3)
    extra = num(p, "extra", 0.5, 0.0)
    gap = num(p, "gap", T / 10.0, 1e-4)
    width = gap if kind == "tear" else max(ratio * T, 1e-3)
    build = Build(base_id, base)
    count = 0
    m = max(0.25 * T, 0.05)
    for b in p.get("bends") or []:
        w = unit(b["axis"]["dir"])
        n_p = unit(b["ref_normal_parent"])
        r = float(b["radius"])
        up = b["direction"] == "up"
        r_ref = r if up else r + T
        r0 = mul(n_p, -1.0) if up else n_p
        centre = tuple(float(x) for x in b["axis"]["origin"])
        tan_pt = add(centre, mul(r0, r_ref))
        pd = mul(cross(w, r0), float(b["turn"]))
        frame = Frame(tan_pt, pd, n_p)
        half = float(b["axis"]["length"]) / 2.0
        mid_w = frame.local(centre)[2]
        depth = (r + T) + extra
        ends = str(p.get("ends") or "both")
        for sign, name in ((-1, "start"), (1, "end")):
            if ends not in ("both", name):
                continue
            if sign < 0:
                w0, w1 = mid_w - half - width, mid_w - half
            else:
                w0, w1 = mid_w + half, mid_w + half + width
            if kind == "obround":
                rr = width / 2.0
                tool = box_in(frame, -extra, depth + 0.0 - rr, -T - m, m, w0, w1)
                build.op("cut", tool)
                build.op("cut", cylinder_v(frame, depth - rr, (w0 + w1) / 2.0, rr, -T - m, m))
            else:
                build.op("cut", box_in(frame, -extra, depth, -T - m, m, w0, w1))
            count += 1
    if count == 0:
        raise RuntimeError("Choose the bends to relieve.")
    if volume_of(build.cur) >= build.v0 - 1e-9:
        raise RuntimeError("The relief removes no material; the bend ends may have no neighbouring sheet.")
    return build.result([], {"kind": "bend_relief"})


def sm_corner_relief(p):
    base_id = p.get("id")
    base = store.shape_of(base_id)
    T = num(p, "thickness", None, 1e-4)
    size = num(p, "size", None, 1e-3)
    kind = str(p.get("type") or "round")
    build = Build(base_id, base)
    count = 0
    for c in p.get("corners") or []:
        n = unit(c["normal"])
        centre = tuple(float(x) for x in c["point"])
        ref = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = unit(cross(n, ref))
        frame = Frame(centre, u, cross(n, u))
        reach = float(p.get("reach") or (T + size * 2.0))
        if kind == "round":
            ax = gp_Ax2(gp_Pnt(*sub(centre, mul(n, reach))), gp_Dir(*n))
            tool = BRepPrimAPI_MakeCylinder(ax, size / 2.0, 2.0 * reach).Shape()
        elif kind in ("square", "tear"):
            side = size if kind == "square" else max(size, 1e-3)
            tool = box_in(Frame(sub(centre, mul(n, reach)), u, cross(n, u)), -side / 2.0, side / 2.0, -side / 2.0, side / 2.0, 0.0, 0.0 + 1.0) if False else box_in(Frame(sub(sub(centre, mul(n, reach)), add(mul(u, side / 2.0), mul(cross(n, u), side / 2.0))), u, cross(n, u)), 0.0, side, 0.0, side, 0.0, 2.0 * reach)
        else:
            raise RuntimeError("A corner relief is round, square or tear.")
        build.op("cut", tool)
        count += 1
    if count == 0:
        raise RuntimeError("Choose the corners to relieve.")
    if volume_of(build.cur) >= build.v0 - 1e-9:
        raise RuntimeError("The corner relief removes no material.")
    return build.result([], {"kind": "corner_relief"})


def cylinder_info(face):
    ad = BRepAdaptor_Surface(face)
    cyl = ad.Cylinder()
    ax = cyl.Axis()
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    loc = tup(ax.Location())
    d = tup(ax.Direction())
    mid = tup(ad.Value((u0 + u1) / 2.0, (v0 + v1) / 2.0))
    nrm = normal_at(face, mid)
    inward = nrm is not None and dot(nrm, sub(mid, add(loc, mul(d, dot(sub(mid, loc), d))))) < 0
    return {"radius": cyl.Radius(), "axis": loc, "dir": d, "span": u1 - u0, "u": (u0, u1), "v": (v0, v1), "inner": inward, "mid": mid}


def point_to_axis(p, loc, d):
    t = dot(sub(p, loc), d)
    return norm(sub(p, add(loc, mul(d, t))))


def same_axis(a, b, tol):
    if abs(abs(dot(a["dir"], b["dir"])) - 1.0) > 1e-7:
        return False
    return point_to_axis(b["axis"], a["axis"], a["dir"]) <= tol


def thickness_at(ident, shape, face, p, n):
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-7)
    inter.Perform(gp_Lin(gp_Pnt(*add(p, mul(n, -1e-4))), gp_Dir(*mul(n, -1.0))), 0.0, 1e12)
    best = None
    if inter.IsDone():
        for i in range(1, inter.NbPnt() + 1):
            t = inter.WParameter(i)
            if t > 2e-4 and (best is None or t < best):
                best = t
    return None if best is None else best + 1e-4


def interior_points(face, count=3):
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    surf = BRep_Tool.Surface_s(face)
    out = []
    for fu, fv in ((0.5, 0.5), (0.3, 0.4), (0.65, 0.3), (0.4, 0.7), (0.8, 0.6), (0.2, 0.2), (0.7, 0.8)):
        u, v = u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv
        cl = BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-7)
        if cl.State() == TopAbs_IN:
            pt = surf.Value(u, v)
            out.append((tup(pt), u, v))
            if len(out) >= count:
                break
    return out


def sm_verify(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    T = num(p, "thickness", None, 1e-6)
    R = num(p, "radius", None, 0.0)
    maps = store.maps_of(ident)
    n = maps["faces"].Extent()
    skins, ends, bad, radii = [], [], [], []
    worst = 0.0
    adj, fedges = face_edges(ident)
    kinds = {}
    for i in range(n):
        face = TopoDS.Face(maps["faces"].FindKey(i + 1))
        kinds[i] = surface_kind(face)
        pts = interior_points(face)
        ds = []
        for pt, _u, _v in pts:
            nrm = normal_at(face, pt)
            if nrm is None:
                continue
            d = thickness_at(ident, shape, face, pt, nrm)
            if d is not None:
                ds.append(d)
        if kinds[i] == GeomAbs_Cylinder:
            info = cylinder_info(face)
            radii.append({"face": i, "radius": info["radius"], "inner": info["inner"], "angle": info["span"]})
        if ds and all(abs(d - T) <= 1e-6 * max(1.0, T) + 1e-7 for d in ds):
            skins.append(i)
            worst = max(worst, max(abs(d - T) for d in ds))
        else:
            ends.append(i)
    ends_ok = True
    skin_set_ = set(skins)
    radii = [r for r in radii if r["face"] in skin_set_]
    for i in ends:
        if kinds[i] not in (GeomAbs_Plane, GeomAbs_Cylinder):
            ends_ok = False
            bad.append(i)
            continue
        face = TopoDS.Face(maps["faces"].FindKey(i + 1))
        axis = cylinder_info(face)["dir"] if kinds[i] == GeomAbs_Cylinder else None
        ni = plane_normal(face) if axis is None else None
        for e in fedges.get(i, []):
            for g in adj[e]:
                if g in skins:
                    m = edge_mid(TopoDS.Edge(maps["edges"].FindKey(e + 1)))
                    ng = normal_at(face_of(ident, g), m)
                    if ng is None:
                        bad_end = True
                    elif axis is not None:
                        bad_end = abs(abs(dot(axis, ng)) - 1.0) > 1e-6
                    else:
                        bad_end = abs(dot(ni, ng)) > 1e-6
                    if bad_end:
                        ends_ok = False
                        bad.append(i)
    radius_ok = True
    allowed = [float(x) for x in (p.get("radii") or ([] if R is None else [R]))]
    if allowed:
        want = [w for r0 in allowed for w in (r0, r0 + T)]
        radius_ok = all(any(abs(r["radius"] - w) <= 1e-6 * max(1.0, w) for w in want) for r in radii)
    return {"ok": True, "skin_faces": skins, "skins": len(skins), "ends": len(ends), "max_deviation": worst, "ends_ok": ends_ok and not bad, "bad": sorted(set(bad)), "cylinders": radii, "radius_ok": radius_ok, "all_cylinders_paired": len([r for r in radii if r["inner"]]) == len([r for r in radii if not r["inner"]])}


def depth_map(base_id, ref_idx):
    adj, fedges = face_edges(base_id)
    maps = store.maps_of(base_id)
    order = skin_set(base_id, ref_idx)
    dist = {int(ref_idx): 0}
    queue = [int(ref_idx)]
    while queue:
        f = queue.pop(0)
        for e in fedges.get(f, []):
            if len(adj[e]) != 2:
                continue
            g = adj[e][0] if adj[e][1] == f else adj[e][1]
            if g in order and g not in dist:
                dist[g] = dist[f] + 1
                queue.append(g)
    return dist, adj, fedges, maps


def sm_analyze(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    fixed = int(p.get("face"))
    fixed_face = face_of(ident, fixed)
    n = plane_normal(fixed_face)
    if n is None:
        raise RuntimeError("The fixed face must be flat.")
    pts = interior_points(fixed_face, 3)
    if not pts:
        raise RuntimeError("The fixed face could not be sampled.")
    ds = [thickness_at(ident, shape, fixed_face, pt, normal_at(fixed_face, pt)) for pt, _u, _v in pts]
    if any(d is None for d in ds):
        raise RuntimeError("The solid is not closed behind the fixed face.")
    T = ds[0]
    if max(ds) - min(ds) > 1e-6 * max(1.0, T):
        raise RuntimeError("The thickness is not constant behind the fixed face.")
    check = sm_verify({"id": ident, "thickness": T})
    if not check["ends_ok"] or check["skins"] < 2:
        raise RuntimeError("The solid is not constant-thickness sheet: %d faces are neither skin nor square thickness faces." % len(check["bad"]))
    if check["ends"] == 0:
        raise RuntimeError("The body has no thickness faces, so it is not a sheet.")
    fb = store.bbox_of(fixed_face)
    ext = sorted([fb[3] - fb[0], fb[4] - fb[1], fb[5] - fb[2]])
    if ext[1] < 2.0 * T - 1e-9:
        raise RuntimeError("The fixed face is %.4g wide against a thickness of %.4g; the body is too thick to be sheet metal." % (ext[1], T))
    dist, adj, fedges, maps = depth_map(ident, fixed)
    cyl = {}
    for i in range(maps["faces"].Extent()):
        face = TopoDS.Face(maps["faces"].FindKey(i + 1))
        if surface_kind(face) == GeomAbs_Cylinder and i in check["skin_faces"]:
            cyl[i] = cylinder_info(face)
    inner = {i: c for i, c in cyl.items() if c["inner"]}
    outer = {i: c for i, c in cyl.items() if not c["inner"]}
    bends = []
    used = set()
    for i, ci in sorted(inner.items()):
        mate = None
        for j, cj in outer.items():
            if j in used:
                continue
            if abs(cj["radius"] - ci["radius"] - T) > 1e-6 * max(1.0, T) or not same_axis(ci, cj, 1e-5 * max(1.0, T)):
                continue
            if abs(cj["span"] - ci["span"]) > 1e-6:
                continue
            mate = j
            break
        if mate is None:
            raise RuntimeError("Bend face %d has no outer partner at radius + thickness." % i)
        used.add(mate)
        co = outer[mate]
        a = ci["dir"]
        v0, v1 = ci["v"]
        axis_pt = add(ci["axis"], mul(a, (v0 + v1) / 2.0 - dot(sub(ci["axis"], ci["axis"]), a)))
        ref_on_inner = i in dist
        ref_cyl = i if ref_on_inner else mate
        if ref_cyl not in dist:
            raise RuntimeError("Bend %d is not connected to the fixed face over tangent faces." % i)
        nb = []
        for e in fedges.get(ref_cyl, []):
            if len(adj[e]) == 2:
                g = adj[e][0] if adj[e][1] == ref_cyl else adj[e][1]
                if g in dist and kinds_planar(ident, g):
                    nb.append((dist[g], g, e))
        if not nb:
            raise RuntimeError("Bend %d has no flat neighbour on the reference skin." % i)
        nb.sort()
        parent_d, parent, pe = nb[0]
        child = None
        for dd, g, e in nb[1:]:
            if dd > parent_d:
                child = g
        pn = plane_normal(face_of(ident, parent))
        pface = face_of(ident, parent)
        em = edge_mid(TopoDS.Edge(maps["edges"].FindKey(pe + 1)))
        pc, _ = feat.face_centre(pface)
        pcent = tup(pc)
        pd = unit(cross(a, pn))
        if dot(sub(em, pcent), pd) < 0:
            pd = mul(pd, -1.0)
        r_ref = ci["radius"] if ref_on_inner else co["radius"]
        rad = sub(em, add(ci["axis"], mul(a, dot(sub(em, ci["axis"]), a))))
        r0 = unit(rad)
        turn = 1 if dot(pd, cross(a, r0)) > 0 else -1
        ang = ci["span"]
        bends.append({
            "radius": round(ci["radius"], 9), "thickness": round(T, 9), "angle": ang, "direction": "up" if ref_on_inner else "down", "turn": turn,
            "axis": {"origin": list(axis_pt), "dir": list(a), "length": v1 - v0},
            "ref_normal_parent": list(pn),
            "flat_parent": None, "flat_child": None, "type": "converted",
            "faces": {"inner": i, "outer": mate, "parent": parent, "child": child},
        })
    return {"ok": True, "thickness": T, "bends": bends, "verify": check, "skin": sorted(dist)}


def kinds_planar(ident, idx):
    return surface_kind(face_of(ident, idx)) == GeomAbs_Plane


def sm_convert(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    info = sm_analyze({"id": ident, "face": p.get("face")})
    want = num(p, "thickness", None)
    if want is not None and abs(want - info["thickness"]) > 1e-4 * max(1.0, want):
        raise RuntimeError("The solid is %.6g thick, not %.6g." % (info["thickness"], want))
    new_id = store.put(shape)
    nm = store.maps_of(new_id)
    rows = {"faces": {str(i): {"to": [i], "deleted": False} for i in range(nm["faces"].Extent())}, "edges": {str(i): {"to": [i], "deleted": False} for i in range(nm["edges"].Extent())}}
    out = {"ok": True, "id": new_id, "summary": store.summarize(shape), "history": {"inputs": [{"id": ident, **rows}]}, "created": {"faces": {}, "edges": {}}, "adjacency": feat.adjacency(new_id), "warnings": [], "errors": [], "bends": info["bends"], "thickness": info["thickness"], "verify": info["verify"], "sections": [], "reliefs": [], "kind": "convert"}
    return out


METHODS = {
    "sm_base_flange": sm_base_flange,
    "sm_edge_flange": sm_edge_flange,
    "sm_miter_flange": sm_miter_flange,
    "sm_hem": sm_hem,
    "sm_jog": sm_jog,
    "sm_sketched_bend": sm_sketched_bend,
    "sm_bend_relief": sm_bend_relief,
    "sm_corner_relief": sm_corner_relief,
    "sm_convert": sm_convert,
    "sm_analyze": sm_analyze,
    "sm_verify": sm_verify,
}
