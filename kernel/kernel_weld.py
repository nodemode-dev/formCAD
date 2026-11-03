import math

from OCP.BRep import BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec

import kernel_feat as feat
import kernel_ops as ops
import kernel_store as store

MAX_MEMBERS = 400
MAX_PARTS = 800
EPS = 1e-9


def vec(v):
    return [float(v[0]), float(v[1]), float(v[2])]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def unit(a):
    n = math.sqrt(dot(a, a))
    if n < 1e-12:
        raise RuntimeError("A direction has zero length.")
    return [a[0] / n, a[1] / n, a[2] / n]


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def cut(shape, tool, what):
    maker = BRepAlgoAPI_Cut(shape, tool)
    if not maker.IsDone():
        raise RuntimeError("The %s could not be cut; the shapes touch in a way the kernel cannot resolve." % what)
    out = maker.Shape()
    if store.count_of(out, TopAbs_SOLID) == 0:
        raise RuntimeError("The %s has nothing left after the cut." % what)
    return out


def half_space(point, normal, big):
    n = gp_Dir(*unit(normal))
    base = gp_Ax2(gp_Pnt(*vec(point)), n)
    x, y = base.XDirection(), base.YDirection()
    p = gp_Pnt(point[0] - x.X() * big / 2.0 - y.X() * big / 2.0, point[1] - x.Y() * big / 2.0 - y.Y() * big / 2.0, point[2] - x.Z() * big / 2.0 - y.Z() * big / 2.0)
    return BRepPrimAPI_MakeBox(gp_Ax2(p, n, x), big, big, big).Shape()


def member_frame(m):
    return feat.frame_ax2({"origin": m["origin"], "normal": m["axis"], "xdir": m["u"]})


def prism(m, regions, length):
    ax = member_frame(m)
    faces = [feat.region_face(ax, r) for r in regions]
    if not faces:
        raise RuntimeError("The profile of member %s has no closed region." % m["id"])
    axis = unit(m["axis"])
    shapes = []
    for f in faces:
        shapes.append(BRepPrimAPI_MakePrism(f, gp_Vec(axis[0] * length, axis[1] * length, axis[2] * length)).Shape())
    return feat.compound_of(shapes) if len(shapes) > 1 else shapes[0]


def outer_only(regions):
    return [{"outer": r["outer"], "holes": []} for r in regions]


def build_member(m, outer):
    big = 4.0 * (float(m["length"]) + float(m.get("extent", 100.0))) + 200.0
    regions = outer_only(m["regions"]) if outer else m["regions"]
    shape = prism(m, regions, float(m["length"]))
    for c in m.get("cuts") or []:
        shape = cut(shape, half_space(c["p"], c["n"], big), "member %s" % m["id"])
    return shape


def projection_range(shape, axis, origin):
    mp = store.ShapeMap()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, mp)
    lo, hi = None, None
    for i in range(1, mp.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex(mp.FindKey(i)))
        t = (p.X() - origin[0]) * axis[0] + (p.Y() - origin[1]) * axis[1] + (p.Z() - origin[2]) * axis[2]
        lo = t if lo is None else min(lo, t)
        hi = t if hi is None else max(hi, t)
    return lo, hi


def build_cap(c):
    ax = feat.frame_ax2({"origin": c["origin"], "normal": c["axis"], "xdir": c["u"]})
    regions = c["regions"]
    faces = [feat.region_face(ax, r) for r in regions]
    axis = unit(c["axis"])
    t = float(c["thickness"])
    shapes = [BRepPrimAPI_MakePrism(f, gp_Vec(axis[0] * t, axis[1] * t, axis[2] * t)).Shape() for f in faces]
    return feat.compound_of(shapes) if len(shapes) > 1 else shapes[0]


def build_gusset(g):
    pts = [vec(p) for p in g["tri"]]
    n = unit(g["normal"])
    t = float(g["thickness"])
    mk = BRepBuilderAPI_MakePolygon()
    for p in pts:
        mk.Add(gp_Pnt(*[p[i] - n[i] * t / 2.0 for i in range(3)]))
    mk.Close()
    face = BRepBuilderAPI_MakeFace(mk.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(n[0] * t, n[1] * t, n[2] * t)).Shape()


def weld_frame(p):
    members = p.get("members") or []
    caps = p.get("caps") or []
    gussets = p.get("gussets") or []
    if not members:
        raise RuntimeError("The frame has no members.")
    if len(members) > MAX_MEMBERS or len(members) + len(caps) + len(gussets) > MAX_PARTS:
        raise RuntimeError("The frame has too many parts (limit %d members, %d parts)." % (MAX_MEMBERS, MAX_PARTS))
    solid_of, env_of = {}, {}
    ids = {m["id"] for m in members}
    needed = set()
    for m in members:
        for t in m.get("trims") or []:
            if t not in ids:
                raise RuntimeError("Member %s is trimmed to %s, which is not in the frame." % (m["id"], t))
            needed.add(t)
    for g in gussets:
        for t in g.get("cut_members") or []:
            needed.add(t)
    for m in members:
        solid_of[m["id"]] = build_member(m, False)
        if m["id"] in needed:
            env_of[m["id"]] = build_member(m, True)
    for m in members:
        for t in m.get("trims") or []:
            solid_of[m["id"]] = cut(solid_of[m["id"]], env_of[t], "member %s" % m["id"])
    pieces = []
    info = {"members": [], "parts": []}
    for m in members:
        shape = solid_of[m["id"]]
        axis = unit(m["axis"])
        lo, hi = projection_range(shape, axis, m["origin"])
        info["members"].append({"id": m["id"], "length": hi - lo, "volume": volume(shape), "solids": store.count_of(shape, TopAbs_SOLID), "start": lo, "end": hi})
        pieces.append((m["id"], shape, m))
    for c in caps:
        shape = build_cap(c)
        info["parts"].append({"id": c["id"], "kind": "end_cap", "volume": volume(shape)})
        pieces.append((c["id"], shape, None))
    for g in gussets:
        shape = build_gusset(g)
        for t in g.get("cut_members") or []:
            shape = cut(shape, env_of[t], "gusset %s" % g["id"])
        info["parts"].append({"id": g["id"], "kind": "gusset", "volume": volume(shape), "solids": store.count_of(shape, TopAbs_SOLID)})
        pieces.append((g["id"], shape, None))
    compound = feat.compound_of([s for _, s, _ in pieces])
    summary = feat.check_result(compound, "weldment")

    def created(out_maps):
        roles = {}
        for pid, shape, m in pieces:
            faces = feat.faces_in(shape)
            keyed = {}
            if m is not None:
                axis = unit(m["axis"])
                for end, cutn in (("start", m.get("start_normal")), ("end", m.get("end_normal"))):
                    if cutn is None:
                        continue
                    best, bd = None, None
                    for f in faces:
                        d = feat.face_plane_dir(f)
                        if d is None:
                            continue
                        n = [d.X(), d.Y(), d.Z()]
                        if abs(abs(dot(n, unit(cutn))) - 1.0) > 1e-6:
                            continue
                        c, _ = feat.face_centre(f)
                        pos = (c.X() - m["origin"][0]) * axis[0] + (c.Y() - m["origin"][1]) * axis[1] + (c.Z() - m["origin"][2]) * axis[2]
                        score = pos if end == "start" else -pos
                        if bd is None or score < bd:
                            best, bd = f, score
                    if best is not None:
                        keyed[id(best)] = end
            for k, f in enumerate(faces):
                idx = out_maps["faces"].FindIndex(f)
                if idx <= 0:
                    continue
                role = keyed.get(id(f))
                roles[str(idx - 1)] = "%s:%s" % (pid, role) if role else "%s:f%d" % (pid, k)
        return roles

    out = feat.package(compound, None, lambda om: [], created, [], {"info": info})
    out["summary"] = summary if out.get("summary") is None else out["summary"]
    return out


METHODS = {"weld_frame": weld_frame}
