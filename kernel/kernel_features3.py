import math

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.BRepFill import BRepFill
from OCP.BRepGProp import BRepGProp_Face
from OCP.BRepLib import BRepLib
from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Tool
from OCP.Geom import Geom_CylindricalSurface
from OCP.Geom2d import Geom2d_Line
from OCP.GeomAbs import GeomAbs_C0, GeomAbs_Cylinder, GeomAbs_G1, GeomAbs_Intersection, GeomAbs_Shape
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds, ShapeAnalysis_Surface
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax3, gp_Dir2d, gp_Pnt, gp_Pnt2d, gp_Vec

import kernel_feat as feat
import kernel_features2 as f2
import kernel_ops as ops
import kernel_store as store

THREAD_DEPTH = 5.0 * math.sqrt(3.0) / 16.0
TAN30 = math.tan(math.radians(30.0))
SPILL = 0.05
MAX_TURNS = 600
SEW_TOL = 1e-6
PATCH_TOL = 1e-4


def cylinder_of(face):
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() != GeomAbs_Cylinder:
        raise RuntimeError("A thread needs a cylindrical face; the chosen face is not a cylinder.")
    return ad.Cylinder()


def outward(face, cyl):
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    pnt, nrm = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal(0.5 * (umin + umax), 0.5 * (vmin + vmax), pnt, nrm)
    ax = cyl.Axis()
    d = gp_Vec(ax.Direction())
    w = gp_Vec(ax.Location(), pnt)
    radial = w.Subtracted(d.Multiplied(w.Dot(d)))
    return nrm.Dot(radial) > 0.0, vmin, vmax


def start_end(shape, cyl, vmin, vmax, flip, hint):
    pos = cyl.Position()
    o, d = pos.Location(), gp_Vec(pos.Direction())
    if hint:
        t = gp_Vec(o, ops.pnt(hint)).Dot(d)
        first = 0 if abs(t - vmin) <= abs(t - vmax) else 1
    else:
        b = store.bbox_of(shape)
        proj = [gp_Vec(o, gp_Pnt(x, y, z)).Dot(d) for x in (b[0], b[3]) for y in (b[1], b[4]) for z in (b[2], b[5])]
        lo, hi = min(proj), max(proj)
        gap0 = min(abs(vmin - lo), abs(vmin - hi))
        gap1 = min(abs(vmax - lo), abs(vmax - hi))
        first = 0 if gap0 < gap1 - 1e-9 else 1
    if flip:
        first = 1 - first
    return (vmin, 1.0) if first == 0 else (vmax, -1.0)


def turn_bounds(turns):
    whole = int(math.floor(turns))
    out = list(range(whole + 1))
    if whole == 0:
        return [0.0, turns]
    if turns - whole > 0.05:
        out.append(turns)
    else:
        out[-1] = turns
    return out


def helix_rail(ax3, radius, pitch, bounds, z, hand):
    surf = Geom_CylindricalSurface(ax3, radius)
    line = Geom2d_Line(gp_Pnt2d(0.0, z), gp_Dir2d(hand * 2.0 * math.pi, pitch))
    per = math.hypot(2.0 * math.pi, pitch)
    out = []
    for a, b in zip(bounds, bounds[1:]):
        e = BRepBuilderAPI_MakeEdge(line, surf, per * a, per * b).Edge()
        BRepLib.BuildCurves3d_s(e, 1e-7, GeomAbs_Shape.GeomAbs_C1, 14, 200)
        out.append(e)
    return out


def ends_of(edge):
    return BRep_Tool.Pnt_s(TopExp.FirstVertex_s(edge)), BRep_Tool.Pnt_s(TopExp.LastVertex_s(edge))


def first_of(shape, kind):
    ex = TopExp_Explorer(shape, kind)
    return ex.Current() if ex.More() else None


def closed_solid(shell, what):
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell(shell)).Solid()
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    solid = fix.Solid()
    if f2.volume_of(solid) < 0:
        solid = solid.Reversed()
    if not f2.valid_solid(solid):
        raise RuntimeError("The %s did not close into a valid solid." % what)
    return solid


def thread_tool(ax3, spec, pitch, turns, hand, tip_role):
    bounds = turn_bounds(turns)
    rails = [helix_rail(ax3, r, pitch, bounds, z, hand) for r, z in spec]
    names = ("flank1", tip_role, "flank2", "base")
    sew = BRepBuilderAPI_Sewing(SEW_TOL)
    made = []
    for i in range(4):
        for k, (a, b) in enumerate(zip(rails[i], rails[(i + 1) % 4])):
            f = BRepFill.Face_s(a, b)
            sew.Add(f)
            made.append((f, "thread:%s.%d" % (names[i], k)))
    for end, idx, role in ((0, 0, "thread:start"), (1, -1, "thread:end")):
        poly = BRepBuilderAPI_MakePolygon()
        for rail in rails:
            poly.Add(ends_of(rail[idx])[end])
        poly.Close()
        f = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
        sew.Add(f)
        made.append((f, role))
    sew.Perform()
    shell = first_of(sew.SewedShape(), TopAbs_SHELL)
    if shell is None:
        raise RuntimeError("The thread profile could not be swept along the helix.")
    solid = closed_solid(shell, "thread tool")
    roles = [(TopoDS.Face(sew.Modified(f)), role) for f, role in made]
    return solid, roles


def thread(p, sid):
    base = store.shape_of(sid)
    face = f2.sub_items(sid, "faces", [int(p.get("face"))], "Face")[0]
    cyl = cylinder_of(face)
    external, vmin, vmax = outward(face, cyl)
    op = "add" if str(p.get("op", "cut")) == "add" else "cut"
    r = cyl.Radius()
    outer = external == (op == "cut")
    cand = (p.get("candidates") or {}).get("major" if outer else "minor") or {}
    pitch = p.get("pitch") or cand.get("pitch")
    if not pitch:
        raise RuntimeError("No thread size in the hole table has a %s diameter of %.4g mm; choose a size or type the pitch." % ("major" if outer else "minor", 2.0 * r))
    pitch = float(pitch)
    if not math.isfinite(pitch) or pitch <= ops.MIN_SIZE or pitch > r:
        raise RuntimeError("The pitch must be positive and smaller than the radius of the face.")
    h = THREAD_DEPTH * pitch
    nominal = float(cand["nominal"]) if cand.get("nominal") else (2.0 * r if outer else 2.0 * r + 2.0 * h)
    tip = nominal / 2.0 - h if outer else nominal / 2.0
    sign = -1.0 if outer else 1.0
    if (tip - r) * sign < 0.05 * h:
        raise RuntimeError("The face diameter %.4g mm does not fit a thread of nominal %.4g mm and pitch %.4g mm made by %s on an %s face." % (2.0 * r, nominal, pitch, "cutting" if op == "cut" else "adding", "outside" if external else "inside"))
    wt = pitch / 4.0 if outer else pitch / 8.0
    rf = r - sign * SPILL * pitch
    wf = wt + 2.0 * abs(tip - rf) * TAN30
    if wf >= 0.98 * pitch:
        raise RuntimeError("The thread would be deeper than the pitch allows (%.4g mm deep at pitch %.4g mm); check the size against the face diameter." % (abs(tip - r), pitch))
    avail = vmax - vmin
    offset = float(p.get("offset") or 0.0)
    if offset < 0.0 or offset >= avail:
        raise RuntimeError("The start offset must be between 0 and the face length (%.4g mm)." % avail)
    length = p.get("length") or cand.get("depth")
    length = avail - offset if not length else float(length)
    if length > avail - offset + 1e-6:
        if p.get("length"):
            raise RuntimeError("The thread is %.4g mm long but only %.4g mm of the face is left after the start offset." % (length, avail - offset))
        length = avail - offset
    lead = wf / 2.0 if op == "add" else 0.0
    run = length - wf / 2.0 - lead
    if run < 0.25 * pitch:
        raise RuntimeError("The thread length must be at least about one pitch (%.4g mm)." % pitch)
    turns = run / pitch
    if turns > MAX_TURNS:
        raise RuntimeError("The thread would have %d turns; the most is %d. Use a shorter length or a larger pitch." % (int(turns), MAX_TURNS))
    start, s = start_end(base, cyl, vmin, vmax, bool(p.get("flip")), p.get("start_point") or cand.get("start_point"))
    pos = cyl.Position()
    d = pos.Direction()
    z0 = start + s * (offset + lead)
    loc = pos.Location()
    origin = gp_Pnt(loc.X() + d.X() * z0, loc.Y() + d.Y() * z0, loc.Z() + d.Z() * z0)
    ax3 = gp_Ax3(origin, d if s > 0 else d.Reversed(), pos.XDirection())
    hand = -1.0 if str(p.get("hand", "right")) == "left" else 1.0
    spec = [(rf, -wf / 2.0), (tip, -wt / 2.0), (tip, wt / 2.0), (rf, wf / 2.0)]
    tool, roles = thread_tool(ax3, spec, pitch, turns, hand, "root" if op == "cut" else "crest")
    out = feat.combine(sid, base, tool, roles, op, "thread")()
    out["thread"] = {"internal": not external, "op": op, "nominal": nominal, "pitch": pitch, "length": length, "offset": offset, "turns": turns, "size": cand.get("id") or "", "note": cand.get("note") or "", "hand": "left" if hand < 0 else "right", "depth": abs(tip - r), "from_hole": bool(cand.get("from_hole"))}
    out["kind"] = "thread"
    return out


def feat_thread(p):
    sid = p.get("id")
    if not sid:
        return f2.failure("A thread needs a body with a cylindrical face.")
    try:
        return thread(p, sid)
    except RuntimeError as err:
        return f2.failure(str(err), failed={"edges": [], "faces": [int(p.get("face", -1))]})


def offset_of(shape, dist, thick):
    mo = BRepOffset_MakeOffset()
    try:
        mo.Initialize(shape, dist, 1e-5, BRepOffset_Skin, True, False, GeomAbs_Intersection, thick, True)
        mo.MakeOffsetShape()
    except Exception:
        return None
    return mo if mo.IsDone() else None


def sheet_pieces(p, sid):
    shapes = []
    if p.get("faces"):
        sew = BRepBuilderAPI_Sewing(SEW_TOL)
        for f in f2.sub_items(sid, "faces", p["faces"], "Face"):
            sew.Add(BRepBuilderAPI_Copy(f).Shape())
        sew.Perform()
        shapes.append(sew.SewedShape())
    for wid in p.get("sheets") or []:
        s = store.shape_of(wid)
        if store.count_of(s, TopAbs_SOLID):
            raise RuntimeError("A chosen body is a solid; thicken takes faces or a sheet (surface) body.")
        shapes.append(s)
    pieces = []
    for s in shapes:
        if s.ShapeType() == TopAbs_FACE:
            pieces.append(s)
            continue
        pieces.extend(f2.sub_shapes(s, TopAbs_SHELL))
        ex = TopExp_Explorer(s, TopAbs_FACE, TopAbs_SHELL)
        while ex.More():
            pieces.append(ex.Current())
            ex.Next()
    if not pieces:
        raise RuntimeError("Choose the faces or the sheet bodies to thicken.")
    return pieces


def slab_of(piece, t, side, tag):
    if side == "both":
        half = offset_of(piece, -t / 2.0, False)
        src = half.Shape() if half is not None else None
        mo = offset_of(src, t, True) if src is not None else None
    else:
        src = piece
        mo = offset_of(piece, t if side == "first" else -t, True)
    slab = mo.Shape() if mo is not None else None
    if slab is not None and slab.ShapeType() != TopAbs_SOLID:
        slab = first_of(slab, TopAbs_SOLID)
    if slab is None or not f2.valid_solid(slab):
        raise RuntimeError("The kernel could not thicken the sheet by %.4g mm; the thickness may be larger than the tightest bend radius of the surface, or the faces may not join into one smooth sheet." % t)
    smap = store.build_maps(slab)["faces"]
    roles, have = [], set()
    for f in f2.sub_shapes(src, TopAbs_FACE):
        if smap.FindIndex(f) > 0:
            roles.append((TopoDS.Face(f), "thicken:back%s" % tag))
            have.add(smap.FindIndex(f))
        for g in mo.Generated(f):
            if g.ShapeType() == TopAbs_FACE and smap.FindIndex(g) > 0:
                roles.append((TopoDS.Face(g), "thicken:front%s" % tag))
                have.add(smap.FindIndex(g))
    for i in range(1, smap.Extent() + 1):
        if i not in have:
            roles.append((TopoDS.Face(smap.FindKey(i)), "thicken:side%s" % tag))
    return slab, roles


def feat_thicken(p):
    sid = p.get("id")
    try:
        t = f2.positive_number(p, "thickness")
        side = str(p.get("side", "first"))
        if side not in ("first", "second", "both"):
            raise RuntimeError("The side is first, second or both.")
        op = "cut" if str(p.get("op", "add")) == "cut" else "add"
        slabs, roles = [], []
        for i, piece in enumerate(sheet_pieces(p, sid)):
            slab, r = slab_of(piece, t, side, "" if i == 0 else ".%d" % i)
            slabs.append(slab)
            roles.extend(r)
        tool = slabs[0] if len(slabs) == 1 else feat.compound_of(slabs)
        base = store.shape_of(sid) if sid else None
        out = feat.combine(sid, base, tool, roles, op, "thicken")()
        if base is not None:
            moved = abs(f2.volume_of(store.shape_of(out["id"])) - f2.volume_of(base))
            if moved < 1e-6 * max(f2.volume_of(tool), 1e-9):
                store.free([out["id"], out.get("tool")])
                raise RuntimeError("The thickened sheet lies inside the body and %s; choose the other side or the other combine mode." % ("adds no material" if op == "add" else "removes no material"))
    except RuntimeError as err:
        return f2.failure(str(err), failed={"edges": [], "faces": [int(i) for i in p.get("faces") or []]})
    out.update({"kind": "thicken", "slabs": len(slabs)})
    return out


def bucket(sig):
    return (sig["k"], tuple(round(v, 3) for v in sig["c"]))


def same_sig(a, b, tol):
    if a["k"] != b["k"] or math.dist(a["c"], b["c"]) > tol:
        return False
    key = "a" if "a" in a else "l"
    return abs(a.get(key, 0.0) - b.get(key, 0.0)) <= 1e-6 * max(abs(a.get(key, 0.0)), 1.0)


def match_rows(src, dst, sigfn, cast, drop, tol):
    sigs = [sigfn(cast(dst.FindKey(j + 1))) for j in range(dst.Extent())]
    index = {}
    for j, s in enumerate(sigs):
        index.setdefault(bucket(s), []).append(j)
    used, rows = set(), {}
    for i in range(src.Extent()):
        if i in drop:
            rows[str(i)] = {"to": [], "deleted": True}
            continue
        s = sigfn(cast(src.FindKey(i + 1)))
        hit = next((j for j in index.get(bucket(s), []) if j not in used and same_sig(s, sigs[j], tol)), None)
        if hit is None:
            hit = next((j for j in range(len(sigs)) if j not in used and same_sig(s, sigs[j], tol)), None)
        if hit is not None:
            used.add(hit)
        rows[str(i)] = {"to": [] if hit is None else [hit], "deleted": hit is None}
    return rows, used


def heal(sid, faces):
    shape = store.shape_of(sid)
    items = f2.sub_items(sid, "faces", faces, "Face")
    maker = BRepAlgoAPI_Defeaturing()
    maker.SetShape(shape)
    for f in items:
        maker.AddFaceToRemove(f)
    maker.SetRunParallel(True)
    maker.SetToFillHistory(True)
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The kernel could not heal the gap left by face(s) %s. Use Delete and patch, or delete the neighbouring faces too." % ", ".join(map(str, faces)))
    result = maker.Shape()
    om = store.build_maps(result)["faces"]
    stuck = [i for i, f in zip(faces, items) if om.FindIndex(f) > 0]
    if stuck:
        raise RuntimeError("The kernel could not heal the gap left by face(s) %s: the neighbouring faces cannot be extended to meet and close it. Use Delete and patch, or delete the neighbouring faces too." % ", ".join(map(str, stuck)))
    out, bad = f2.finish(maker, sid, result)
    if out is None:
        raise RuntimeError("Healing the gap did not give a valid solid. Use Delete and patch, or choose other faces.")
    out.update({"kind": "delete_face", "mode": "heal", "removed_faces": faces})
    return out


def normal_at(face, pnt):
    uv = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face)).ValueOfUV(pnt, 1e-6)
    p, n = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal(uv.X(), uv.Y(), p, n)
    return n.Normalized() if n.Magnitude() > 1e-12 else None


def smooth_join(edge, kept, banc, removed):
    j = banc.FindIndex(edge)
    if j <= 0:
        return False
    gone = next((f for f in banc.FindFromIndex(j) if any(f.IsSame(r) for r in removed)), None)
    if gone is None:
        return False
    c = BRepAdaptor_Curve(edge)
    mid = c.Value(0.5 * (c.FirstParameter() + c.LastParameter()))
    a, b = normal_at(TopoDS.Face(gone), mid), normal_at(kept, mid)
    return a is not None and b is not None and abs(a.Dot(b)) > 0.996


def patch(sid, faces, tangent):
    shape = store.shape_of(sid)
    maps = store.maps_of(sid)
    drop = set(faces)
    sew = BRepBuilderAPI_Sewing(SEW_TOL)
    for i in range(maps["faces"].Extent()):
        if i not in drop:
            sew.Add(maps["faces"].FindKey(i + 1))
    sew.Perform()
    open_shell = sew.SewedShape()
    anc = f2.ancestors(open_shell, TopAbs_EDGE, TopAbs_FACE)
    banc = f2.ancestors(shape, TopAbs_EDGE, TopAbs_FACE)
    removed = [TopoDS.Face(maps["faces"].FindKey(i + 1)) for i in faces]
    gap = 1e-3 * max(feat.bbox_diag(shape), 1.0)
    bounds = ShapeAnalysis_FreeBounds(open_shell, SEW_TOL, False, False)
    wires = f2.sub_shapes(bounds.GetClosedWires(), TopAbs_WIRE)
    if not wires:
        raise RuntimeError("Deleting these faces leaves no closed gap to patch.")
    patches, warnings = [], []
    for w in wires:
        mk = BRepOffsetAPI_MakeFilling()
        for e in f2.sub_shapes(w, TopAbs_EDGE):
            edge = TopoDS.Edge(e)
            j = anc.FindIndex(edge) if tangent else 0
            kept = TopoDS.Face(anc.FindFromIndex(j).First()) if j > 0 else None
            if kept is not None and smooth_join(edge, kept, banc, removed):
                mk.Add(edge, kept, GeomAbs_G1, True)
            else:
                mk.Add(edge, GeomAbs_C0, True)
        try:
            mk.Build()
        except Exception:
            raise RuntimeError("The kernel could not build a patch surface over the gap; choose fewer faces or use Delete and heal.")
        if not mk.IsDone():
            raise RuntimeError("The kernel could not build a patch surface over the gap; choose fewer faces or use Delete and heal.")
        if mk.G0Error() > 10.0 * gap:
            raise RuntimeError("The patch surface could not follow the edges of the gap (off by %.3g mm); turn tangency off, choose fewer faces or use Delete and heal." % mk.G0Error())
        if mk.G0Error() > gap:
            warnings.append(f2.issue("A patch deviates from the edges of the gap by up to %.3g mm." % mk.G0Error(), code="patch_gap"))
        patches.append(mk.Shape())
    sew2 = BRepBuilderAPI_Sewing(PATCH_TOL)
    sew2.Add(open_shell)
    for pa in patches:
        sew2.Add(pa)
    sew2.Perform()
    shells = f2.sub_shapes(sew2.SewedShape(), TopAbs_SHELL)
    if len(shells) != 1:
        raise RuntimeError("The patch does not close the body into one solid.")
    solid = closed_solid(shells[0], "patched body")
    ident = store.put(solid)
    om = store.maps_of(ident)
    tol = 1e-5 * max(feat.bbox_diag(shape), 1.0)
    frows, fused = match_rows(maps["faces"], om["faces"], feat.surface_sig, TopoDS.Face, drop, tol)
    erows, _eused = match_rows(maps["edges"], om["edges"], feat.edge_sig, TopoDS.Edge, set(), tol)
    created = {}
    for k, pa in enumerate(patches):
        for f in f2.sub_shapes(pa, TopAbs_FACE):
            j = om["faces"].FindIndex(sew2.Modified(f)) - 1
            if j >= 0 and j not in fused:
                created[str(j)] = "patch.%d" % k
    return {"ok": True, "id": ident, "summary": store.summarize(solid), "history": {"inputs": [{"id": sid, "faces": frows, "edges": erows}]}, "created": {"faces": created, "edges": {}}, "errors": [], "warnings": warnings, "failed": {"edges": [], "faces": []}, "kind": "delete_face", "mode": "patch", "removed_faces": faces, "patch_faces": sorted(int(k) for k in created)}


def feat_delete_face(p):
    sid = p.get("id")
    faces = sorted({int(i) for i in p.get("faces") or []})
    if not sid or not faces:
        return f2.failure("Choose the faces to delete.")
    try:
        if len(faces) >= store.maps_of(sid)["faces"].Extent():
            raise RuntimeError("Deleting every face leaves nothing.")
        if str(p.get("mode", "heal")) == "patch":
            return patch(sid, faces, bool(p.get("tangent")))
        return heal(sid, faces)
    except RuntimeError as err:
        return f2.failure(str(err), failed={"edges": [], "faces": faces})


METHODS = {"feat_thread": feat_thread, "feat_thicken": feat_thicken, "feat_delete_face": feat_delete_face}
