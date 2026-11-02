import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepFeat import BRepFeat_MakePrism, BRepFeat_MakeRevol
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.BRep import BRep_Builder
from OCP.GC import GC_MakeArcOfCircle
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Intersection, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.LocOpe import LocOpe_DPrism
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_ON, TopAbs_REVERSED, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Face
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as AncestorMap
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Lin, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec

import kernel_ops as ops
import kernel_store as store

TOL = 1e-7
MATCH = 1e-5
MAX_SEGMENTS = 20000
MAX_ROLE_SEARCH = 400

PLUGINS = ()


def number(p, key, default=None):
    v = p.get(key, default)
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        raise RuntimeError("%s must be a finite number." % key)
    return v


def frame_ax2(frame):
    if not frame:
        raise RuntimeError("The sketch has no plane.")
    origin = ops.pnt(frame.get("origin") or [0, 0, 0])
    normal = ops.direction(frame.get("normal"))
    xdir = frame.get("xdir")
    return gp_Ax2(origin, normal, ops.direction(xdir)) if xdir else gp_Ax2(origin, normal)


def to3(ax, u, v):
    loc, xd, yd = ax.Location(), ax.XDirection(), ax.YDirection()
    return gp_Pnt(loc.X() + u * xd.X() + v * yd.X(), loc.Y() + u * xd.Y() + v * yd.Y(), loc.Z() + u * xd.Z() + v * yd.Z())


def uv_of(ax, pt):
    loc = ax.Location()
    d = gp_Vec(loc, pt)
    return d.Dot(gp_Vec(ax.XDirection())), d.Dot(gp_Vec(ax.YDirection()))


def curve_mid(edge):
    c = BRepAdaptor_Curve(edge)
    return c.Value((c.FirstParameter() + c.LastParameter()) / 2.0)


def loop_area(segs):
    pts = []
    extra = 0.0
    for s in segs:
        if s["t"] == "circle":
            r = float(s["r"])
            return math.pi * r * r
        a, b = s["a"], s["b"]
        pts.append(a)
        bulge = float(s.get("bulge", 0.0) or 0.0)
        if abs(bulge) > 1e-12:
            chord = math.hypot(b[0] - a[0], b[1] - a[1])
            theta = 4.0 * math.atan(abs(bulge))
            r = chord / (2.0 * math.sin(theta / 2.0)) if chord > 0 else 0.0
            extra += math.copysign(0.5 * r * r * (theta - math.sin(theta)), bulge)
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area / 2.0 + extra


def reverse_segs(segs):
    out = []
    for s in reversed(segs):
        if s["t"] == "circle":
            out.append(s)
        else:
            out.append({"t": s["t"], "a": s["b"], "b": s["a"], "bulge": -float(s.get("bulge", 0.0) or 0.0), "role": s.get("role", "")})
    return out


def seg_edge(ax, s, flip=False):
    if s["t"] == "circle":
        c = s["c"]
        r = float(s["r"])
        if r <= ops.MIN_SIZE:
            raise RuntimeError("A circle in the profile has no radius.")
        circ = gp_Circ(gp_Ax2(to3(ax, float(c[0]), float(c[1])), ax.Direction(), ax.XDirection()), r)
        edge = BRepBuilderAPI_MakeEdge(circ).Edge()
        return TopoDS.Edge(edge.Reversed()) if flip else edge
    a, b = s["a"], s["b"]
    pa = to3(ax, float(a[0]), float(a[1]))
    pb = to3(ax, float(b[0]), float(b[1]))
    if pa.Distance(pb) <= ops.MIN_SIZE:
        return None
    bulge = float(s.get("bulge", 0.0) or 0.0)
    if abs(bulge) > 1e-12:
        chord = pa.Distance(pb)
        sag = abs(bulge) * chord / 2.0
        mx, my = (float(a[0]) + float(b[0])) / 2.0, (float(a[1]) + float(b[1])) / 2.0
        dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
        ln = math.hypot(dx, dy)
        sign = 1.0 if bulge > 0 else -1.0
        mid = to3(ax, mx + sign * dy / ln * sag, my - sign * dx / ln * sag)
        arc = GC_MakeArcOfCircle(pa, mid, pb)
        if not arc.IsDone():
            raise RuntimeError("An arc segment of the profile is degenerate.")
        return BRepBuilderAPI_MakeEdge(arc.Value()).Edge()
    return BRepBuilderAPI_MakeEdge(pa, pb).Edge()


def seg_mid_uv(s):
    if s["t"] == "circle":
        c = s["c"]
        return (float(c[0]) + float(s["r"]), float(c[1])), (0.0, 1.0)
    a, b = s["a"], s["b"]
    bulge = float(s.get("bulge", 0.0) or 0.0)
    dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    ln = math.hypot(dx, dy) or 1.0
    mx, my = (float(a[0]) + float(b[0])) / 2.0, (float(a[1]) + float(b[1])) / 2.0
    if abs(bulge) > 1e-12:
        sag = abs(bulge) * ln / 2.0
        sign = 1.0 if bulge > 0 else -1.0
        mx, my = mx + sign * dy / ln * sag, my - sign * dx / ln * sag
    return (mx, my), (dx / ln, dy / ln)


def labels_of(loop):
    out = []
    for s in loop["segs"]:
        mid, tan = seg_mid_uv(s)
        lab = {"uv": mid, "tan": tan, "role": str(s.get("role") or "")}
        if s["t"] == "circle":
            lab["circ"] = (float(s["c"][0]), float(s["c"][1]), float(s["r"]))
        out.append(lab)
    return out


def build_wire(ax, loop, want_ccw):
    segs = list(loop["segs"])
    if not segs:
        raise RuntimeError("A profile loop has no segments.")
    if len(segs) > MAX_SEGMENTS:
        raise RuntimeError("A profile loop has too many segments.")
    flip = False
    if want_ccw is not None and loop.get("closed", True):
        area = loop_area(segs)
        if abs(area) <= TOL:
            raise RuntimeError("A profile loop encloses no area.")
        if (area > 0) != want_ccw:
            segs = reverse_segs(segs)
            flip = len(segs) == 1 and segs[0]["t"] == "circle"
    mk = BRepBuilderAPI_MakeWire()
    count = 0
    for s in segs:
        edge = seg_edge(ax, s, flip)
        if edge is None:
            continue
        mk.Add(edge)
        count += 1
    if count == 0 or not mk.IsDone():
        raise RuntimeError("A profile loop could not be joined into a wire; check that its segments meet end to end.")
    return mk.Wire(), {"segs": segs, "closed": loop.get("closed", True)}


def fix_face(face):
    fixer = ShapeFix_Face(face)
    fixer.FixOrientation()
    fixer.Perform()
    return fixer.Face()


def region_face(ax, region):
    plane = gp_Pln(ax.Location(), ax.Direction())
    wire, _ = build_wire(ax, region["outer"], True)
    mk = BRepBuilderAPI_MakeFace(plane, wire)
    for hole in region.get("holes") or []:
        hw, _ = build_wire(ax, hole, False)
        mk.Add(hw)
    if not mk.IsDone():
        raise RuntimeError("The profile does not make a face.")
    return fix_face(mk.Face())


def offset_wire(wire, dist, open_wire):
    if abs(dist) <= TOL:
        return wire
    mk = BRepOffsetAPI_MakeOffset(wire, GeomAbs_Intersection, bool(open_wire))
    mk.Perform(float(dist))
    shape = mk.Shape()
    if shape.IsNull():
        raise RuntimeError("The thin offset of the profile failed.")
    if shape.ShapeType().name.endswith("COMPOUND"):
        from OCP.TopAbs import TopAbs_WIRE
        from OCP.TopExp import TopExp_Explorer

        ex = TopExp_Explorer(shape, TopAbs_WIRE)
        if not ex.More():
            raise RuntimeError("The thin offset of the profile failed.")
        return TopoDS.Wire(ex.Current())
    return TopoDS.Wire(shape)


def thin_split(thin):
    t1 = float(thin.get("t1") or 0.0)
    t2 = float(thin.get("t2") or 0.0)
    mode = str(thin.get("mode") or "one")
    if t1 <= ops.MIN_SIZE:
        raise RuntimeError("The thin wall thickness must be positive.")
    if mode == "mid":
        return t1 / 2.0, t1 / 2.0
    if mode == "two":
        if t2 <= ops.MIN_SIZE:
            t2 = t1
        return t1, t2
    return t1, 0.0


def thin_faces(ax, profile, thin):
    plane = gp_Pln(ax.Location(), ax.Direction())
    a, b = thin_split(thin)
    flip = bool(thin.get("flip"))
    if flip:
        a, b = b, a
    faces = []
    loops = []
    for region in profile.get("regions") or []:
        loops.append(region["outer"])
        loops.extend(region.get("holes") or [])
    for lp in loops:
        wire, _ = build_wire(ax, lp, True)
        outer = offset_wire(wire, a, False)
        inner = offset_wire(wire, -b, False)
        mk = BRepBuilderAPI_MakeFace(plane, outer)
        mk.Add(TopoDS.Wire(inner.Reversed()))
        if not mk.IsDone():
            raise RuntimeError("The thin wall could not be made from the profile.")
        faces.append(fix_face(mk.Face()))
    for lp in profile.get("open") or []:
        wire, _ = build_wire(ax, lp, None)
        right = offset_wire(wire, a, True)
        left = offset_wire(wire, -b, True)
        if abs(a) <= TOL:
            right = wire
        if abs(b) <= TOL:
            left = wire
        segs = lp["segs"]
        p_start = to3(ax, float(segs[0]["a"][0]), float(segs[0]["a"][1]))
        p_end = to3(ax, float(segs[-1]["b"][0]), float(segs[-1]["b"][1]))

        def ends(w):
            mp = store.ShapeMap()
            TopExp.MapShapes_s(w, TopAbs_VERTEX, mp)
            pts = [BRep_Tool.Pnt_s(TopoDS.Vertex(mp.FindKey(i))) for i in range(1, mp.Extent() + 1)]
            return min(pts, key=lambda q: q.Distance(p_start)), min(pts, key=lambda q: q.Distance(p_end))

        r1, r2 = ends(right)
        l1, l2 = ends(left)
        pieces = ops.ShapeList()
        for w in (right, left):
            mp = store.ShapeMap()
            TopExp.MapShapes_s(w, TopAbs_EDGE, mp)
            for i in range(1, mp.Extent() + 1):
                pieces.Append(mp.FindKey(i))
        if r2.Distance(l2) > TOL:
            pieces.Append(BRepBuilderAPI_MakeEdge(r2, l2).Edge())
        if l1.Distance(r1) > TOL:
            pieces.Append(BRepBuilderAPI_MakeEdge(l1, r1).Edge())
        band = BRepBuilderAPI_MakeWire()
        band.Add(pieces)
        if not band.IsDone():
            raise RuntimeError("The thin band could not be closed.")
        mk = BRepBuilderAPI_MakeFace(plane, band.Wire())
        if not mk.IsDone():
            raise RuntimeError("The thin band does not make a face.")
        faces.append(fix_face(mk.Face()))
    if not faces:
        raise RuntimeError("The thin feature has no profile.")
    return faces


def source_labels(profile):
    out = []
    for region in profile.get("regions") or []:
        out.extend(labels_of(region["outer"]))
        for h in region.get("holes") or []:
            out.extend(labels_of(h))
    for lp in profile.get("open") or []:
        out.extend(labels_of(lp))
    return out


def edge_roles_for(ax, face, labels, suffix_side):
    mp = store.ShapeMap()
    TopExp.MapShapes_s(face, TopAbs_EDGE, mp)
    out = []
    for i in range(1, mp.Extent() + 1):
        e = TopoDS.Edge(mp.FindKey(i))
        mid = uv_of(ax, curve_mid(e))
        best, bd = None, None
        for lab in labels[:MAX_ROLE_SEARCH * 50]:
            if "circ" in lab:
                cx, cy, cr = lab["circ"]
                off = abs(math.hypot(mid[0] - cx, mid[1] - cy) - cr)
                d = off if off <= 1e-6 * max(1.0, cr) else 1e18
            else:
                d = math.hypot(mid[0] - lab["uv"][0], mid[1] - lab["uv"][1])
            if bd is None or d < bd:
                best, bd = lab, d
        role = best["role"] if best else ""
        if suffix_side and best:
            cross = (mid[0] - best["uv"][0]) * best["tan"][1] - (mid[1] - best["uv"][1]) * best["tan"][0]
            dot = (mid[0] - best["uv"][0]) * best["tan"][0] + (mid[1] - best["uv"][1]) * best["tan"][1]
            if abs(dot) > abs(cross) + 1e-9:
                role += ":end"
            else:
                role += ":l" if cross > 0 else ":r"
        out.append((e, "side:" + role))
    return out


def profile_faces(ax, profile, thin):
    labels = source_labels(profile)
    if thin:
        faces = thin_faces(ax, profile, thin)
    else:
        regions = profile.get("regions") or []
        if not regions:
            raise RuntimeError("The profile has no closed region; close the sketch outline or use a thin feature.")
        faces = [region_face(ax, r) for r in regions]
    items = []
    for f in faces:
        items.append((f, edge_roles_for(ax, f, labels, bool(thin))))
    return items


def face_plane_dir(face):
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() != GeomAbs_Plane:
        return None
    d = ad.Plane().Axis().Direction()
    v = gp_Vec(d)
    if face.Orientation() == TopAbs_REVERSED:
        v.Reverse()
    return v


def face_centre(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.CentreOfMass(), props.Mass()


def compound_of(shapes):
    if len(shapes) == 1:
        return shapes[0]
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    for s in shapes:
        bld.Add(comp, s)
    return comp


def faces_in(shape):
    mp = store.ShapeMap()
    TopExp.MapShapes_s(shape, TopAbs_FACE, mp)
    return [TopoDS.Face(mp.FindKey(i)) for i in range(1, mp.Extent() + 1)]


def make_prism_tool(items, vec, draft, caps):
    shapes = []
    roles = []
    for face, edge_roles in items:
        length = vec.Magnitude()
        if abs(draft) > 1e-9:
            ang = math.radians(abs(draft))
            normal = face_plane_dir(face)
            spine = face
            if normal is not None and normal.Dot(vec) < 0:
                spine = TopoDS.Face(face.Reversed())
            sign = 1.0 if draft > 0 else -1.0
            dp = LocOpe_DPrism(spine, length / math.cos(ang), sign * ang)
            tool = dp.Shape()
            for e, role in edge_roles:
                for g in dp.Shapes(e):
                    if g.ShapeType() == TopAbs_FACE:
                        roles.append((TopoDS.Face(g), role))
            shapes.append(tool)
            continue
        mk = BRepPrimAPI_MakePrism(face, vec)
        if not mk.IsDone():
            raise RuntimeError("The extrusion could not be made.")
        tool = mk.Shape()
        for e, role in edge_roles:
            for g in mk.Generated(e):
                if g.ShapeType() == TopAbs_FACE:
                    roles.append((TopoDS.Face(g), role))
        first, last = mk.FirstShape(), mk.LastShape()
        if first.ShapeType() == TopAbs_FACE:
            roles.append((TopoDS.Face(first), caps[0]))
        if last.ShapeType() == TopAbs_FACE:
            roles.append((TopoDS.Face(last), caps[1]))
        shapes.append(tool)
    tool = compound_of(shapes)
    return tool, roles


def label_rest(tool, roles, vec_dir, start, caps, items):
    have = set()
    mp = store.ShapeMap()
    TopExp.MapShapes_s(tool, TopAbs_FACE, mp)
    for f, _r in roles:
        have.add(mp.FindIndex(f))
    out = list(roles)
    planar = []
    for i in range(1, mp.Extent() + 1):
        if i in have:
            continue
        f = TopoDS.Face(mp.FindKey(i))
        n = face_plane_dir(f)
        if n is not None and abs(abs(n.Dot(gp_Vec(vec_dir))) - 1.0) < 1e-7:
            c, _a = face_centre(f)
            planar.append((gp_Vec(start, c).Dot(gp_Vec(vec_dir)), f))
    if planar:
        planar.sort(key=lambda t: t[0])
        out.append((planar[0][1], caps[0]))
        if len(planar) > 1:
            out.append((planar[-1][1], caps[1]))
    return label_orphans(tool, out, items)


def label_orphans(tool, roles, items):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    mp = store.ShapeMap()
    TopExp.MapShapes_s(tool, TopAbs_FACE, mp)
    have = {mp.FindIndex(f) for f, _r in roles}
    marks = []
    for _face, edge_roles in items:
        for e, role in edge_roles:
            marks.append((BRepBuilderAPI_MakeVertex(curve_mid(e)).Vertex(), role))
    out = list(roles)
    if not marks or len(marks) > MAX_ROLE_SEARCH:
        return out
    for i in range(1, mp.Extent() + 1):
        if i in have:
            continue
        f = TopoDS.Face(mp.FindKey(i))
        best, bd = None, None
        for v, role in marks:
            ds = BRepExtrema_DistShapeShape(v, f)
            if ds.IsDone() and (bd is None or ds.Value() < bd):
                best, bd = role, ds.Value()
        if best is not None and bd < 1e-4:
            out.append((f, best))
    return out


def bbox_diag(shape):
    b = store.bbox_of(shape)
    if not b:
        return 0.0
    return math.dist(b[:3], b[3:])


def run_boolean(op, base, tool):
    cls = BRepAlgoAPI_Fuse if op == "fuse" else BRepAlgoAPI_Cut
    maker = cls()
    a = ops.ShapeList()
    a.Append(base)
    t = ops.ShapeList()
    t.Append(tool)
    maker.SetArguments(a)
    maker.SetTools(t)
    maker.SetRunParallel(True)
    maker.SetNonDestructive(True)
    maker.SetToFillHistory(True)
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The feature could not be combined with the body; the new shape may touch it in a way the kernel cannot resolve.")
    maker.SimplifyResult(True, True, 1e-6)
    return maker


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def box_key(shape):
    b = store.bbox_of(shape)
    if not b:
        return (0.0, 0.0, 0.0)
    return (round((b[0] + b[3]) / 2.0, 6), round((b[1] + b[4]) / 2.0, 6), round((b[2] + b[5]) / 2.0, 6))


def history_rows(maker, in_shape, in_maps, out_maps):
    out = {}
    for key, kind in (("faces", TopAbs_FACE), ("edges", TopAbs_EDGE)):
        rows = {}
        src = in_maps[key]
        dst = out_maps[key]
        for i in range(1, src.Extent() + 1):
            sub = src.FindKey(i)
            deleted = bool(maker.IsDeleted(sub))
            to = []
            if not deleted:
                to = ops.index_list(dst, list(maker.Modified(sub)))
                if not to:
                    idx = dst.FindIndex(sub)
                    if idx > 0:
                        to = [idx - 1]
            for g in ops.index_list(dst, list(maker.Generated(sub))):
                if g not in to:
                    to.append(g)
            if len(to) > 1:
                shapes = {t: dst.FindKey(t + 1) for t in to}
                to = sorted(to, key=lambda t: (box_key(shapes[t]), t))
            rows[str(i - 1)] = {"to": to, "deleted": deleted and not to}
        out[key] = rows
    return out


def tool_created(maker, tool, roles, out_maps):
    tool_maps = store.build_maps(tool)
    created = {}
    for face, role in roles:
        idx = tool_maps["faces"].FindIndex(face)
        if idx <= 0:
            continue
        src = tool_maps["faces"].FindKey(idx)
        if maker.IsDeleted(src):
            continue
        targets = ops.index_list(out_maps["faces"], list(maker.Modified(src)))
        if not targets:
            hit = out_maps["faces"].FindIndex(src)
            if hit > 0:
                targets = [hit - 1]
        for g in ops.index_list(out_maps["faces"], list(maker.Generated(src))):
            if g not in targets:
                targets.append(g)
        for k, t in enumerate(sorted(targets)):
            created.setdefault(str(t), role if k == 0 else "%s#%d" % (role, k))
    return created


def adjacency(ident):
    shape = store.shape_of(ident)
    maps = store.maps_of(ident)
    anc = AncestorMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, anc)
    out = []
    for i in range(1, maps["edges"].Extent() + 1):
        e = maps["edges"].FindKey(i)
        j = anc.FindIndex(e)
        faces = []
        if j > 0:
            for f in anc.FindFromIndex(j):
                k = maps["faces"].FindIndex(f) - 1
                if k >= 0 and k not in faces:
                    faces.append(k)
        out.append(sorted(faces))
    return out


def package(result, source_id, rows_by_input, created, warnings=None, extra=None):
    ident = store.put(result)
    out_maps = store.maps_of(ident)
    out = {"ok": True, "id": ident, "summary": store.summarize(result), "history": {"inputs": rows_by_input(out_maps)}, "created": {"faces": created(out_maps) if callable(created) else created, "edges": {}}, "adjacency": adjacency(ident), "warnings": warnings or [], "errors": []}
    if extra:
        out.update(extra)
    return out


def check_result(result, what):
    if result is None or result.IsNull() or store.count_of(result, TopAbs_SOLID) == 0:
        raise RuntimeError("The %s produced no solid." % what)
    summary = store.summarize(result)
    if not summary["valid"]:
        raise RuntimeError("The %s produced an invalid solid; change the sizes or the profile." % what)
    return summary


def combine(base_id, base, tool, roles, op, what):
    if base is None:
        if op == "cut":
            raise RuntimeError("There is no body to cut yet.")
        check_result(tool, what)
        return lambda: package(tool, None, lambda om: [], lambda om: tool_created_new(tool, roles, om))
    v0 = volume_of(base)
    maker = run_boolean("fuse" if op == "add" else "cut", base, tool)
    result = maker.Shape()
    check_result(result, what)
    v1 = volume_of(result)
    warnings = []
    if op == "add" and v1 <= v0 + 1e-9:
        raise RuntimeError("The %s adds no material; it may lie inside the body." % what)
    if op == "cut" and v1 >= v0 - 1e-9:
        raise RuntimeError("The %s removes no material; it may miss the body." % what)
    if op == "add" and store.count_of(result, TopAbs_SOLID) > store.count_of(base, TopAbs_SOLID):
        warnings.append("The new material does not touch the body, so it forms a separate solid.")

    def rows(om):
        return [{"id": base_id, **history_rows(maker, base, store.maps_of(base_id), om)}]

    def created(om):
        return tool_created(maker, tool, roles, om)

    return lambda: package(result, base_id, rows, created, warnings, {"tool": store.put(tool)})


def tool_created_new(tool, roles, out_maps):
    out = {}
    for face, role in roles:
        idx = out_maps["faces"].FindIndex(face)
        if idx > 0:
            out.setdefault(str(idx - 1), role)
    return out


def transform_item(item, trsf):
    face, edge_roles = item
    mk = BRepBuilderAPI_Transform(face, trsf, True)
    nf = TopoDS.Face(mk.Shape())
    out = []
    for e, role in edge_roles:
        m = mk.ModifiedShape(e)
        if not m.IsNull():
            out.append((TopoDS.Edge(m), role))
    return nf, out


def find_skface(base, ax, items):
    if base is None:
        return TopoDS_Face()
    plane = ax.Direction()
    loc = ax.Location()
    for face in faces_in(base):
        n = face_plane_dir(face)
        if n is None or abs(abs(n.Dot(gp_Vec(plane))) - 1.0) > 1e-7:
            continue
        pl = BRepAdaptor_Surface(face).Plane()
        if abs(gp_Vec(loc, pl.Location()).Dot(gp_Vec(plane))) > 1e-6:
            continue
        c, _a = face_centre(items[0][0])
        cls = BRepClass_FaceClassifier(face, c, 1e-6)
        if cls.State() in (TopAbs_IN, TopAbs_ON):
            return face
    return TopoDS_Face()


def nearest_face_along(base, origin, direction, skip):
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(base, 1e-6)
    inter.Perform(gp_Lin(origin, direction), 1e-6, 1e12)
    if not inter.IsDone():
        return None
    best = None
    for i in range(1, inter.NbPnt() + 1):
        w = inter.WParameter(i)
        f = inter.Face(i)
        if w > 1e-6 and not (not skip.IsNull() and f.IsSame(skip)):
            if best is None or w < best[0]:
                best = (w, f)
    return best[1] if best else None


def end_spec(p, which):
    spec = p.get("end" + which) or {}
    if isinstance(spec, str):
        spec = {"type": spec}
    return spec


def feature_extrude_feat(p, base_id, base, ax, items, op, dir1, spec):
    kind = spec.get("type")
    skface = find_skface(base, ax, items)
    if kind == "next":
        c, _a = face_centre(items[0][0])
        target = nearest_face_along(base, c, gp_Dir(dir1), skface)
        if target is None:
            raise RuntimeError("No face lies ahead of the profile to stop at.")
        until = target
    else:
        idx = int(spec.get("face"))
        until = TopoDS.Face(store.maps_of(base_id)["faces"].FindKey(idx + 1))
    face0 = items[0][0]
    if len(items) > 1:
        raise RuntimeError("Up to a face works on one closed region at a time; select the contours or split the sketch.")
    mk = BRepFeat_MakePrism(base, face0, skface, gp_Dir(dir1), 1 if op == "add" else 0, True)
    mk.Perform(until)
    if not mk.IsDone():
        raise RuntimeError("The extrusion could not reach that face; it may be parallel to the direction or behind the profile.")
    result = mk.Shape()
    check_result(result, "extrusion")
    v0 = volume_of(base)
    v1 = volume_of(result)
    if (op == "add" and v1 <= v0 + 1e-9) or (op == "cut" and v1 >= v0 - 1e-9):
        raise RuntimeError("The extrusion changes nothing; the face may be on the wrong side.")
    roles = []
    for e, role in items[0][1]:
        for g in mk.Generated(e):
            if g.ShapeType() == TopAbs_FACE:
                roles.append((TopoDS.Face(g), role))

    def rows(om):
        return [{"id": base_id, **history_rows(mk, base, store.maps_of(base_id), om)}]

    def created(om):
        out = {}
        for f, role in roles:
            i = om["faces"].FindIndex(f)
            if i > 0:
                out.setdefault(str(i - 1), role)
        touched = set()
        for row in rows(om)[0]["faces"].values():
            touched.update(row["to"])
        extra = [i for i in range(om["faces"].Extent()) if i not in touched and str(i) not in out]
        for k, i in enumerate(extra):
            out[str(i)] = "cap:end" if k == 0 else "cap:end#%d" % k
        return out

    return package(result, base_id, rows, created)


def extrude(p):
    base_id = p.get("id")
    base = store.shape_of(base_id) if base_id else None
    op = str(p.get("op") or "add")
    if op not in ("add", "cut"):
        raise RuntimeError("An extrusion adds or cuts.")
    profile = p.get("profile") or {}
    ax = frame_ax2(profile.get("frame"))
    offset = number(p, "start_offset", 0.0) or 0.0
    if offset:
        ax = gp_Ax2(to3(ax, 0, 0).Translated(gp_Vec(ax.Direction()).Multiplied(offset)), ax.Direction(), ax.XDirection())
    flip = bool(p.get("flip"))
    dir1 = gp_Vec(ax.Direction())
    if flip:
        dir1.Reverse()
    unit1 = gp_Dir(dir1)
    thin = p.get("thin") or None
    items = profile_faces(ax, profile, thin)
    span = bbox_diag(base) if base is not None else 0.0
    reach = 4.0 * span + 10.0 + abs(offset)
    spec1 = end_spec(p, "1")
    kind1 = spec1.get("type") or "blind"
    two = bool(p.get("two"))
    spec2 = end_spec(p, "2") if two else {}
    kind2 = spec2.get("type") or "blind"
    draft1 = number(p, "draft1", 0.0) or 0.0
    draft2 = number(p, "draft2", 0.0) or 0.0
    if abs(draft1) >= 89.0 or abs(draft2) >= 89.0:
        raise RuntimeError("A draft angle must be smaller than 89 degrees.")
    if base is not None and kind1 in ("face", "next"):
        if two:
            raise RuntimeError("Up to a face cannot be combined with a second direction.")
        build = feature_extrude_feat(p, base_id, base, ax, items, op, dir1, spec1)
        return build
    d1 = reach if kind1 == "through" else number(spec1, "depth", number(p, "depth1", 0.0)) or 0.0
    if kind1 == "mid":
        d1 = number(spec1, "depth", number(p, "depth1", 0.0)) / 2.0
    if d1 <= ops.MIN_SIZE:
        raise RuntimeError("The extrusion depth must be positive.")
    d2 = 0.0
    if kind1 == "mid":
        d2 = d1
    elif two:
        d2 = reach if kind2 == "through" else number(spec2, "depth", number(p, "depth2", 0.0)) or 0.0
        if d2 <= ops.MIN_SIZE:
            raise RuntimeError("The second direction depth must be positive.")
    tools = []
    roles = []
    sep = abs(draft1) > 1e-9 or abs(draft2) > 1e-9
    if d2 > 0 and not sep:
        back = gp_Trsf()
        back.SetTranslation(dir1.Reversed().Multiplied(d2))
        moved = [transform_item(it, back) for it in items]
        tool, rl = make_prism_tool(moved, dir1.Multiplied(d1 + d2), 0.0, ("cap:end2", "cap:end"))
        tools.append(tool)
        roles.extend(rl)
        roles = label_rest(tool, roles, unit1, to3(ax, 0, 0).Translated(dir1.Reversed().Multiplied(d2)), ("cap:end2", "cap:end"), moved)
    else:
        if d2 > 0:
            raise RuntimeError("A draft angle with a second direction is not supported yet; use one direction.")
        tool, rl = make_prism_tool(items, dir1.Multiplied(d1), draft1, ("cap:start", "cap:end"))
        roles = label_rest(tool, rl, unit1, to3(ax, 0, 0), ("cap:start", "cap:end"), items)
        tools.append(tool)
    return combine(base_id, base, tools[0], roles, op, "extrusion")()


def revolve_axis(spec):
    origin = ops.pnt(spec.get("origin") or [0, 0, 0])
    return gp_Ax1(origin, ops.direction(spec.get("dir")))


def revolve(p):
    base_id = p.get("id")
    base = store.shape_of(base_id) if base_id else None
    op = str(p.get("op") or "add")
    if op not in ("add", "cut"):
        raise RuntimeError("A revolve adds or cuts.")
    profile = p.get("profile") or {}
    ax = frame_ax2(profile.get("frame"))
    axis = revolve_axis(p.get("axis") or {})
    a1 = number(p, "angle1", 360.0)
    a2 = number(p, "angle2", 0.0) or 0.0
    mid = bool(p.get("mid"))
    if a1 <= 1e-6 or a1 > 360.0 + 1e-9:
        raise RuntimeError("The revolve angle must be between 0 and 360 degrees.")
    if bool(p.get("flip")):
        axis = gp_Ax1(axis.Location(), axis.Direction().Reversed())
    thin = p.get("thin") or None
    items = profile_faces(ax, profile, thin)
    total = a1
    pre = 0.0
    if mid:
        pre = a1 / 2.0
    elif a2 > 0:
        pre = a2
        total = a1 + a2
    if total >= 360.0 - 1e-9:
        total = 360.0
        pre = 0.0
    if pre:
        back = gp_Trsf()
        back.SetRotation(axis, -math.radians(pre))
        items = [transform_item(it, back) for it in items]
    shapes = []
    roles = []
    full = total >= 360.0 - 1e-9
    for face, edge_roles in items:
        mk = BRepPrimAPI_MakeRevol(face, axis) if full else BRepPrimAPI_MakeRevol(face, axis, math.radians(total))
        if not mk.IsDone():
            raise RuntimeError("The revolve could not be made; check that the profile does not cross the axis.")
        shapes.append(mk.Shape())
        for e, role in edge_roles:
            for g in mk.Generated(e):
                if g.ShapeType() == TopAbs_FACE:
                    roles.append((TopoDS.Face(g), role))
        if not full:
            first, last = mk.FirstShape(), mk.LastShape()
            if first.ShapeType() == TopAbs_FACE:
                roles.append((TopoDS.Face(first), "cap:end2" if pre else "cap:start"))
            if last.ShapeType() == TopAbs_FACE:
                roles.append((TopoDS.Face(last), "cap:end"))
    tool = compound_of(shapes)
    roles = label_orphans(tool, roles, items)
    check_tool = store.summarize(tool)
    if not check_tool["valid"] or check_tool["solids"] == 0:
        raise RuntimeError("The revolve produced an invalid solid; the profile may cross or touch the axis along an edge.")
    return combine(base_id, base, tool, roles, op, "revolve")()


def surface_sig(face):
    ad = BRepAdaptor_Surface(face)
    t = ad.GetType()
    c, area = face_centre(face)
    sig = {"k": int(t.value) if hasattr(t, "value") else int(t), "c": [c.X(), c.Y(), c.Z()], "a": area}
    if t == GeomAbs_Plane:
        n = face_plane_dir(face)
        sig["n"] = [n.X(), n.Y(), n.Z()]
    elif t == GeomAbs_Cylinder:
        d = ad.Cylinder().Axis().Direction()
        sig["n"] = [d.X(), d.Y(), d.Z()]
        sig["r"] = ad.Cylinder().Radius()
    elif t == GeomAbs_Cone:
        d = ad.Cone().Axis().Direction()
        sig["n"] = [d.X(), d.Y(), d.Z()]
        sig["r"] = ad.Cone().RefRadius()
    elif t == GeomAbs_Sphere:
        sig["r"] = ad.Sphere().Radius()
    elif t == GeomAbs_Torus:
        d = ad.Torus().Axis().Direction()
        sig["n"] = [d.X(), d.Y(), d.Z()]
        sig["r"] = ad.Torus().MajorRadius()
    return sig


def edge_sig(edge):
    ad = BRepAdaptor_Curve(edge)
    t = ad.GetType()
    mid = ad.Value((ad.FirstParameter() + ad.LastParameter()) / 2.0)
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    sig = {"k": int(t.value) if hasattr(t, "value") else int(t), "c": [mid.X(), mid.Y(), mid.Z()], "l": props.Mass()}
    name = str(t).split(".")[-1]
    if name.endswith("Line"):
        a, b = ad.Value(ad.FirstParameter()), ad.Value(ad.LastParameter())
        v = gp_Vec(a, b)
        if v.Magnitude() > 0:
            v.Normalize()
            sig["n"] = [v.X(), v.Y(), v.Z()]
    elif name.endswith("Circle"):
        d = ad.Circle().Axis().Direction()
        sig["n"] = [d.X(), d.Y(), d.Z()]
        sig["r"] = ad.Circle().Radius()
    return sig


def signatures(p):
    ident = p.get("id")
    maps = store.maps_of(ident)
    out = {}
    for key, fn in (("faces", surface_sig), ("edges", edge_sig)):
        want = p.get(key)
        if want is None:
            want = []
        idx = range(maps[key].Extent()) if want == "all" else [int(i) for i in want]
        rows = {}
        for i in idx:
            if 0 <= i < maps[key].Extent():
                shape = maps[key].FindKey(i + 1)
                rows[str(i)] = fn(TopoDS.Face(shape) if key == "faces" else TopoDS.Edge(shape))
        out[key] = rows
    want_v = p.get("vertices")
    if want_v:
        rows = {}
        m = maps["vertices"]
        idx = range(m.Extent()) if want_v == "all" else [int(i) for i in want_v]
        for i in idx:
            if 0 <= i < m.Extent():
                pt = BRep_Tool.Pnt_s(TopoDS.Vertex(m.FindKey(i + 1)))
                rows[str(i)] = {"p": [pt.X(), pt.Y(), pt.Z()]}
        out["vertices"] = rows
    return out


def topology(p):
    ident = p.get("id")
    maps = store.maps_of(ident)
    return {"faces": maps["faces"].Extent(), "edges": maps["edges"].Extent(), "vertices": maps["vertices"].Extent(), "adjacency": adjacency(ident), "summary": store.summarize(store.shape_of(ident))}


def ray_hits(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-6)
    inter.Perform(gp_Lin(ops.pnt(p.get("origin")), ops.direction(p.get("dir"))), -1e12, 1e12)
    maps = store.maps_of(ident)
    out = []
    if inter.IsDone():
        for i in range(1, inter.NbPnt() + 1):
            out.append({"t": inter.WParameter(i), "face": maps["faces"].FindIndex(inter.Face(i)) - 1})
    return {"hits": sorted(out, key=lambda r: r["t"])}


METHODS = {"feat_extrude": extrude, "feat_revolve": revolve, "feat_signatures": signatures, "feat_topology": topology, "feat_rays": ray_hits}


def load_plugins() -> None:
    import importlib

    for name in PLUGINS:
        try:
            METHODS.update(importlib.import_module(name).METHODS)
        except Exception:
            pass
