import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line, GeomAbs_Plane
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.TopoDS import TopoDS_Compound
from OCP.BRep import BRep_Builder

import kernel_ops as ops
import kernel_store as store

MAX_COMPONENTS = 20000
MAX_HOLES = 20000
SAMPLES = 24


def board_solid(p):
    loops = p.get("loops") or []
    thickness = float(p.get("thickness", 1.6))
    if thickness <= 0:
        raise RuntimeError("The board thickness must be positive.")
    shape = ops.make_extrude({"loops": loops, "plane": {"origin": [0, 0, 0], "normal": [0, 0, 1], "xdir": [1, 0, 0]}, "height": thickness})
    holes = p.get("holes") or []
    if len(holes) > MAX_HOLES:
        raise RuntimeError("The board has more holes than the limit of %d." % MAX_HOLES)
    cutters = []
    for h in holes:
        r = float(h["d"]) / 2.0
        if r <= 1e-6:
            continue
        slot = float(h.get("slot") or 0.0)
        cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(float(h["x"]), float(h["y"]), -0.5), gp_Dir(0, 0, 1)), r, thickness + 1.0).Shape()
        if slot > 2 * r + 1e-6:
            half = (slot - 2 * r) / 2.0
            ang = math.radians(float(h.get("rot", 0.0)))
            box =BRepPrimAPI_MakeBox(gp_Pnt(-half, -r, -0.5), 2 * half, 2 * r, thickness + 1.0).Shape()
            rot = gp_Trsf()
            rot.SetRotation(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)).Axis(), ang)
            mv = gp_Trsf()
            mv.SetTranslation(gp_Vec(float(h["x"]), float(h["y"]), 0.0))
            box = BRepBuilderAPI_Transform(BRepBuilderAPI_Transform(box, rot, True).Shape(), mv, True).Shape()
            cyl = BRepAlgoAPI_Fuse(cyl, box).Shape()
        cutters.append(cyl)
    for c in cutters:
        shape = BRepAlgoAPI_Cut(shape, c).Shape()
    return shape


def component_shape(c, thickness):
    w, d, h = float(c["w"]), float(c["d"]), float(c["h"])
    if min(w, d, h) <= 1e-6:
        return None
    z0 = float(c.get("z0", 0.0))
    bottom = c.get("side", "top") == "bottom"
    zbase = -(z0 + h) if bottom else thickness + z0
    if c.get("shape") == "cyl":
        solid = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, zbase), gp_Dir(0, 0, 1)), w / 2.0, h).Shape()
    else:
        solid = BRepPrimAPI_MakeBox(gp_Pnt(-w / 2.0, -d / 2.0, zbase), w, d, h).Shape()
    rot = gp_Trsf()
    rot.SetRotation(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)).Axis(), math.radians(float(c.get("rot", 0.0))))
    mv = gp_Trsf()
    mv.SetTranslation(gp_Vec(float(c["wx"]), float(c["wy"]), 0.0))
    return BRepBuilderAPI_Transform(BRepBuilderAPI_Transform(solid, rot, True).Shape(), mv, True).Shape()


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def ecad_board_body(p):
    thickness = float(p.get("thickness", 1.6))
    board = board_solid(p)
    comps = p.get("components") or []
    if len(comps) > MAX_COMPONENTS:
        raise RuntimeError("The board has more components than the limit of %d." % MAX_COMPONENTS)
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    count = 0
    for c in comps:
        s = component_shape(c, thickness)
        if s is not None:
            builder.Add(compound, s)
            count += 1
    board_id = store.put(board)
    comp_id = store.put(compound) if count else None
    return {"board": board_id, "components": comp_id, "board_summary": store.summarize(board), "component_count": count, "board_volume": volume_of(board), "component_volume": volume_of(compound) if count else 0.0}


def frame_of(face):
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_Plane:
        raise RuntimeError("The chosen face is not flat; the board outline needs a flat face.")
    pl = surf.Plane()
    n = pl.Axis().Direction()
    if face.Orientation() == TopAbs_REVERSED:
        n = n.Reversed()
    nv = (n.X(), n.Y(), n.Z())
    ref = (1.0, 0.0, 0.0) if abs(nv[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = sum(ref[i] * nv[i] for i in range(3))
    x = [ref[i] - d * nv[i] for i in range(3)]
    ln = math.sqrt(sum(c * c for c in x))
    x = [c / ln for c in x]
    y = [nv[1] * x[2] - nv[2] * x[1], nv[2] * x[0] - nv[0] * x[2], nv[0] * x[1] - nv[1] * x[0]]
    o = pl.Location()
    return {"origin": [o.X(), o.Y(), o.Z()], "normal": list(nv), "xdir": x, "ydir": y}


def to_uv(fr, pnt):
    o, x, y = fr["origin"], fr["xdir"], fr["ydir"]
    v = (pnt.X() - o[0], pnt.Y() - o[1], pnt.Z() - o[2])
    return (v[0] * x[0] + v[1] * x[1] + v[2] * x[2], v[0] * y[0] + v[1] * y[1] + v[2] * y[2])


def edge_vertices(edge, fr, tol):
    curve = BRepAdaptor_Curve(edge)
    f, l = curve.FirstParameter(), curve.LastParameter()
    reversed_ = edge.Orientation() == TopAbs_REVERSED
    a_par, b_par = (l, f) if reversed_ else (f, l)
    ctype = curve.GetType()
    pa = to_uv(fr, curve.Value(a_par))
    pb = to_uv(fr, curve.Value(b_par))
    if ctype == GeomAbs_Line:
        return [[pa[0], pa[1], 0.0]], False
    if ctype == GeomAbs_Circle:
        pm = to_uv(fr, curve.Value((a_par + b_par) / 2.0))
        circ = curve.Circle()
        c = to_uv(fr, circ.Location())
        r = circ.Radius()
        a0 = math.atan2(pa[1] - c[1], pa[0] - c[0])
        a1 = math.atan2(pb[1] - c[1], pb[0] - c[0])
        cross = (pm[0] - pa[0]) * (pb[1] - pm[1]) - (pm[1] - pa[1]) * (pb[0] - pm[0])
        ccw = cross > 0
        full = math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 1e-9
        if full:
            sweep = (2.0 * math.pi) if ccw else -2.0 * math.pi
            if abs(cross) < 1e-12:
                sweep = 2.0 * math.pi
                ccw = True
            half = [c[0] + (c[0] - pa[0]), c[1] + (c[1] - pa[1])]
            s = 1.0 if ccw else -1.0
            return [[pa[0], pa[1], s], [half[0], half[1], s]], False
        sweep = (a1 - a0) % (2.0 * math.pi) if ccw else -((a0 - a1) % (2.0 * math.pi))
        return [[pa[0], pa[1], math.tan(sweep / 4.0)]], False
    n = SAMPLES
    out = []
    for i in range(n):
        t = a_par + (b_par - a_par) * i / n
        q = to_uv(fr, curve.Value(t))
        out.append([q[0], q[1], 0.0])
    return out, True


def wire_loop(wire, face, fr, tol):
    verts = []
    approx = False
    exp = BRepTools_WireExplorer(wire, face)
    while exp.More():
        pts, a = edge_vertices(exp.Current(), fr, tol)
        verts.extend(pts)
        approx = approx or a
        exp.Next()
    clean = []
    for v in verts:
        if clean and math.hypot(v[0] - clean[-1][0], v[1] - clean[-1][1]) < 1e-9:
            if abs(v[2]) > abs(clean[-1][2]):
                clean[-1][2] = v[2]
            continue
        clean.append(v)
    if len(clean) > 1 and math.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) < 1e-9:
        clean.pop()
    return clean, approx


def loop_circle(verts):
    if len(verts) == 2 and abs(abs(verts[0][2]) - 1.0) < 1e-6 and abs(abs(verts[1][2]) - 1.0) < 1e-6:
        a, b = verts[0], verts[1]
        return {"c": [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0], "r": math.hypot(a[0] - b[0], a[1] - b[1]) / 2.0}
    return None


def faces_of(shape):
    out = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        out.append(TopoDS.Face(exp.Current()))
        exp.Next()
    return out


def face_area(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def ecad_face_outline(p):
    shape = store.shape_of(p.get("id"))
    maps = store.maps_of(p.get("id"))
    tol = float(p.get("tolerance", 0.01))
    if p.get("face") is not None:
        idx = int(p["face"])
        fm = maps["faces"]
        if idx < 0 or idx >= fm.Extent():
            raise RuntimeError("The part has no face number %d." % idx)
        face = TopoDS.Face(fm.FindKey(idx + 1))
    else:
        want = p.get("normal") or [0.0, 0.0, 1.0]
        best = None
        for f in faces_of(shape):
            surf = BRepAdaptor_Surface(f)
            if surf.GetType() != GeomAbs_Plane:
                continue
            fr = frame_of(f)
            dot = sum(fr["normal"][i] * float(want[i]) for i in range(3))
            if dot < 0.99:
                continue
            key = (fr["origin"][0] * float(want[0]) + fr["origin"][1] * float(want[1]) + fr["origin"][2] * float(want[2]), face_area(f))
            if p.get("which") == "lowest":
                key = (-key[0], key[1])
            if best is None or key > best[0]:
                best = (key, f)
        if best is None:
            raise RuntimeError("No flat face points along the requested direction.")
        face = best[1]
    fr = frame_of(face)
    outer = BRepTools.OuterWire_s(face)
    loops = []
    approx = False
    verts, a = wire_loop(outer, face, fr, tol)
    approx = approx or a
    loops.append({"outer": True, "verts": verts, "circle": loop_circle(verts)})
    exp = TopExp_Explorer(face, TopAbs_WIRE)
    while exp.More():
        w = TopoDS.Wire(exp.Current())
        if not w.IsSame(outer):
            verts, a = wire_loop(w, face, fr, tol)
            approx = approx or a
            loops.append({"outer": False, "verts": verts, "circle": loop_circle(verts)})
        exp.Next()
    return {"frame": fr, "loops": loops, "approximated": approx, "area": face_area(face)}


def ecad_face_list(p):
    shape = store.shape_of(p.get("id"))
    maps = store.maps_of(p.get("id"))
    fm = maps["faces"]
    rows = []
    for i in range(fm.Extent()):
        f = TopoDS.Face(fm.FindKey(i + 1))
        surf = BRepAdaptor_Surface(f)
        if surf.GetType() != GeomAbs_Plane:
            continue
        fr = frame_of(f)
        rows.append({"index": i, "normal": fr["normal"], "origin": fr["origin"], "area": face_area(f)})
    return {"faces": rows}


METHODS = {"ecad_board_body": ecad_board_body, "ecad_face_outline": ecad_face_outline, "ecad_face_list": ecad_face_list}
