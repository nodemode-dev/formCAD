import math
import time

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Ax3, gp_Dir, gp_GTrsf, gp_Lin, gp_Pln, gp_Pnt, gp_Trsf

import kernel_feat as feat
import kernel_plastic as pl
import kernel_store as store
from kernel_sheet import add, dot, mul, norm, num, sub, unit

MAX_FACES = 1500
MAX_SAMPLES = 24000
VERTICAL = math.sin(math.radians(0.01))
BIG = 1.0e9
CHAIN_TOL = 1.0e-4
VOLUME_TOL = 1.0e-6


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1.0e-9, False, False)
    return props.Mass()


def edge_length(e):
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(e, props)
    return props.Mass()


def pull_of(p):
    return unit(pl.tup3(p.get("pull") or (0.0, 0.0, 1.0), "pull"))


def diag_of(shape):
    b = store.bbox_of(shape)
    if not b:
        raise RuntimeError("The body is empty.")
    return math.sqrt((b[3] - b[0]) ** 2 + (b[4] - b[1]) ** 2 + (b[5] - b[2]) ** 2), b


def sample_face(f, grid):
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    out = []
    for a in range(grid):
        for b in range(grid):
            u = u0 + (u1 - u0) * (a + 0.5) / grid
            v = v0 + (v1 - v0) * (b + 0.5) / grid
            got = pl.face_normal(f, u, v)
            if got is None:
                continue
            if not pl.inside_face(f, got[0], 1e-7):
                continue
            out.append(got)
    return out


def classify(ident, d, min_draft, grid, undercut):
    shape = store.shape_of(ident)
    maps = store.maps_of(ident)
    nf = maps["faces"].Extent()
    if nf > MAX_FACES:
        raise RuntimeError("The body has %d faces; the mold analysis takes at most %d." % (nf, MAX_FACES))
    if nf * grid * grid > MAX_SAMPLES:
        grid = max(2, int(math.sqrt(MAX_SAMPLES / max(nf, 1))))
    diag, _b = diag_of(shape)
    eps = max(1.0e-4 * diag, 1.0e-5)
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1.0e-7)

    def blocked(pt, nv, sgn):
        o = add(add(pt, mul(nv, eps)), mul(d, sgn * eps))
        inter.Perform(gp_Lin(gp_Pnt(*o), gp_Dir(*mul(d, sgn))), 0.0, BIG)
        if not inter.IsDone():
            return False
        for k in range(1, inter.NbPnt() + 1):
            if inter.WParameter(k) > 2.0 * eps:
                return True
        return False

    rows = []
    samples = []
    for i in range(1, nf + 1):
        f = TopoDS.Face(maps["faces"].FindKey(i))
        ad = BRepAdaptor_Surface(f)
        pts = sample_face(f, grid)
        row = {"face": i - 1, "kind": pl.kind_name(ad), "area": pl.area_of(f), "samples": len(pts), "steep": 0, "undercut": 0, "ok": 0}
        sv = []
        for pt, nv in pts:
            s = max(-1.0, min(1.0, dot(nv, d)))
            ang = math.degrees(math.asin(s))
            if s > VERTICAL:
                cls_side = 1
            elif s < -VERTICAL:
                cls_side = -1
            else:
                cls_side = 0
            if undercut:
                if cls_side == 0:
                    under = blocked(pt, nv, 1.0) and blocked(pt, nv, -1.0)
                else:
                    under = blocked(pt, nv, float(cls_side))
            else:
                under = False
            if under:
                row["undercut"] += 1
                k = "undercut"
            elif abs(ang) < min_draft - 1e-9:
                row["steep"] += 1
                k = "steep"
            else:
                row["ok"] += 1
                k = "ok"
            sv.append((pt, s, ang, k))
        samples.append(sv)
        if sv:
            angs = [x[2] for x in sv]
            row["draft_min"], row["draft_max"] = min(angs), max(angs)
            row["draft_abs_min"] = min(abs(a) for a in angs)
            signs = [1 if x[1] > VERTICAL else (-1 if x[1] < -VERTICAL else 0) for x in sv]
            if 1 in signs and -1 in signs:
                row["side"] = "straddle"
            elif 1 in signs:
                row["side"] = "cavity"
            elif -1 in signs:
                row["side"] = "core"
            else:
                row["side"] = "vertical"
        else:
            row["side"] = "none"
        row["class"] = "undercut" if row["undercut"] else ("steep" if row["steep"] else ("ok" if row["samples"] else "none"))
        rows.append(row)
    return rows, samples, grid, eps


def md_analyze(p):
    t0 = time.time()
    ident = p.get("id")
    d = pull_of(p)
    min_draft = num(p, "min_draft", 1.0, 0.0, 45.0)
    grid = int(num(p, "grid", 5, 2, 12))
    rows, _samples, used, _eps = classify(ident, d, min_draft, grid, bool(p.get("undercut", True)))
    total = sum(r["area"] for r in rows) or 1.0
    by = {"ok": 0.0, "steep": 0.0, "undercut": 0.0, "none": 0.0}
    cnt = {"ok": 0, "steep": 0, "undercut": 0, "none": 0}
    for r in rows:
        by[r["class"]] += r["area"]
        cnt[r["class"]] += 1
    return {"faces": rows, "pull": list(d), "min_draft": min_draft, "grid": used, "area": total, "area_by_class": by, "faces_by_class": cnt, "undercut_faces": [r["face"] for r in rows if r["class"] == "undercut"], "steep_faces": [r["face"] for r in rows if r["class"] == "steep"], "straddle_faces": [r["face"] for r in rows if r["side"] == "straddle"], "ms": int((time.time() - t0) * 1000)}


def edge_points(e):
    ad = BRepAdaptor_Curve(e)
    f, l = ad.FirstParameter(), ad.LastParameter()
    k = 1 if ad.GetType().name == "GeomAbs_Line" else 32
    out = []
    for i in range(k + 1):
        q = ad.Value(f + (l - f) * i / k)
        out.append((q.X(), q.Y(), q.Z()))
    return out


def chain(polys, lengths):
    n = len(polys)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    ends = {}
    for i, pts in enumerate(polys):
        for q in (pts[0], pts[-1]):
            key = tuple(int(round(c / CHAIN_TOL)) for c in q)
            ends.setdefault(key, []).append(i)
    for lst in ends.values():
        for j in lst[1:]:
            parent[find(j)] = find(lst[0])
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    wires = []
    for g in groups.values():
        deg = {}
        for i in g:
            for q in (polys[i][0], polys[i][-1]):
                key = tuple(int(round(c / CHAIN_TOL)) for c in q)
                deg[key] = deg.get(key, 0) + 1
        closed = all(v % 2 == 0 for v in deg.values())
        length = sum(lengths[i] for i in g)
        wires.append({"edges": len(g), "closed": closed, "length": length, "polylines": [[list(q) for q in polys[i]] for i in g]})
    wires.sort(key=lambda w: -w["length"])
    return wires


def plane_face(d, h, big):
    pln = gp_Pln(gp_Pnt(*mul(d, h)), gp_Dir(*d))
    mk = BRepBuilderAPI_MakeFace(pln, -big, big, -big, big)
    if not mk.IsDone():
        raise RuntimeError("The parting plane could not be built.")
    return mk.Face()


def section_loops(shape, d, h, big):
    common = BRepAlgoAPI_Common(plane_face(d, h, big), shape)
    if not common.IsDone():
        raise RuntimeError("The part could not be cut by the parting plane.")
    loops = []
    ex = TopExp_Explorer(common.Shape(), TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current())
        outer = BRepTools.OuterWire_s(f)
        wx = TopExp_Explorer(f, TopAbs_WIRE)
        while wx.More():
            w = wx.Current()
            polys = []
            length = 0.0
            ex2 = TopExp_Explorer(w, TopAbs_EDGE)
            while ex2.More():
                ee = TopoDS.Edge(ex2.Current())
                polys.append(edge_points(ee))
                length += edge_length(ee)
                ex2.Next()
            kind = "outer" if w.IsSame(outer) else "hole"
            wf = BRepBuilderAPI_MakeFace(TopoDS.Wire(w), True)
            area = pl.area_of(wf.Face()) if wf.IsDone() else 0.0
            c = pl.face_centre(wf.Face()) if wf.IsDone() else (0.0, 0.0, 0.0)
            loops.append({"kind": kind, "area": area, "length": length, "centre": list(c), "equivalent_diameter": 2.0 * math.sqrt(max(area, 0.0) / math.pi), "polylines": polys})
            wx.Next()
        ex.Next()
    return loops


def md_parting(p):
    t0 = time.time()
    ident = p.get("id")
    shape = store.shape_of(ident)
    d = pull_of(p)
    min_draft = num(p, "min_draft", 1.0, 0.0, 45.0)
    grid = int(num(p, "grid", 5, 2, 12))
    rows, samples, used, _eps = classify(ident, d, min_draft, grid, False)
    maps = store.maps_of(ident)
    anc = feat.adjacency(ident)
    diag, bb = diag_of(shape)
    side = [r["side"] for r in rows]
    edges = []
    polys = []
    lens = []
    for ei, fl in enumerate(anc):
        if len(fl) != 2:
            continue
        a, b = side[fl[0]], side[fl[1]]
        if a in ("none", "vertical") or b in ("none", "vertical"):
            continue
        if a == b:
            continue
        ee = TopoDS.Edge(maps["edges"].FindKey(ei + 1))
        pts = edge_points(ee)
        mid = pts[len(pts) // 2]
        edges.append({"edge": ei, "faces": [fl[0], fl[1]], "height": dot(mid, d)})
        polys.append(pts)
        lens.append(edge_length(ee))
    notes = []
    corner = [dot((bb[0 if i == 0 else 3], bb[1 if j == 0 else 4], bb[2 if k == 0 else 5]), d) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    lo, hi = min(corner), max(corner)
    given = p.get("height")
    heights = sorted(e["height"] for e in edges)
    if given is not None:
        height = float(given)
        source = "given"
    elif heights:
        height = heights[len(heights) // 2]
        source = "silhouette"
    else:
        height = (lo + hi) / 2.0
        source = "middle"
        notes.append("No edge joins a face seen from the cavity side to one seen from the core side; the parting height is the middle of the part along the pull.")
    spread = (heights[-1] - heights[0]) if heights else 0.0
    planar = spread <= max(1.0e-4 * diag, 1.0e-4)
    if not planar:
        notes.append("The silhouette edges do not lie in one plane (spread %.4g mm); this version parts with a flat plane at the chosen height and reports the faces left on the wrong side." % spread)
    wrong = []
    tol = max(1.0e-4 * diag, 1.0e-4)
    for r, sv in zip(rows, samples):
        bad = 0
        for pt, s, ang, k in sv:
            z = dot(pt, d)
            if s > VERTICAL and z < height - tol:
                bad += 1
            elif s < -VERTICAL and z > height + tol:
                bad += 1
        if bad:
            wrong.append({"face": r["face"], "samples": bad})
    if not (lo + tol < height < hi - tol):
        raise RuntimeError("The parting height %.4g lies outside the part (%.4g to %.4g along the pull)." % (height, lo, hi))
    loops = section_loops(shape, d, height, diag * 2.0 + 10.0)
    outer = [l for l in loops if l["kind"] == "outer"]
    holes = [l for l in loops if l["kind"] == "hole"]
    return {"pull": list(d), "height": height, "height_source": source, "planar": planar, "spread": spread, "range": [lo, hi], "edges": edges, "wires": chain(polys, lens), "section_outer": outer, "through_holes": holes, "wrong_side": wrong, "notes": notes, "sides": side, "ms": int((time.time() - t0) * 1000)}


def md_shrink(p):
    ident = p.get("id")
    src = store.shape_of(ident)
    f = [float(c) for c in (p.get("factors") or [])]
    if len(f) != 3 or not all(math.isfinite(c) and c > 0 for c in f):
        raise RuntimeError("The shrinkage scale needs three positive factors.")
    o = pl.tup3(p.get("origin") or (0.0, 0.0, 0.0), "origin")
    if abs(f[0] - f[1]) < 1e-15 and abs(f[1] - f[2]) < 1e-15:
        t = gp_Trsf()
        t.SetScale(gp_Pnt(*o), f[0])
        maker = BRepBuilderAPI_Transform(src, t, True)
        result = maker.Shape()
    else:
        g = gp_GTrsf()
        for r in range(3):
            g.SetValue(r + 1, r + 1, f[r])
            g.SetValue(r + 1, 4, o[r] - f[r] * o[r])
        maker = BRepBuilderAPI_GTransform(src, g, True)
        if not maker.IsDone():
            raise RuntimeError("The shrinkage scale could not be applied to this shape.")
        result = maker.Shape()
    new_id = store.put(result)
    return {"id": new_id, "summary": store.summarize(result), "volume": volume(result), "volume_before": volume(src)}


def world_trsf(d):
    t = gp_Trsf()
    t.SetTransformation(gp_Ax3(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(*d)))
    return t


def compound_of(shapes):
    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for s in shapes:
        b.Add(comp, s)
    return comp


def piece_info(ident, shape):
    s = store.summarize(shape)
    return {"id": ident, "summary": s, "volume": volume(shape) if s["solids"] else 0.0}


def block_frame(p):
    part = store.shape_of(p.get("id"))
    d = pull_of(p)
    margin = num(p, "margin", 10.0, 0.0)
    top_margin = num(p, "cavity_margin", 15.0, 0.0)
    bottom_margin = num(p, "core_margin", 15.0, 0.0)
    t = world_trsf(d)
    local = BRepBuilderAPI_Transform(part, t, True).Shape()
    b = store.bbox_of(local)
    if not b:
        raise RuntimeError("The part is empty.")
    if abs(volume(local)) < 1e-9:
        raise RuntimeError("The part has no volume; the mold block needs a closed solid.")
    box = (b[0] - margin, b[1] - margin, b[2] - bottom_margin, b[3] + margin, b[4] + margin, b[5] + top_margin)
    return part, d, t, local, b, box


def md_block(p):
    part, d, t, local, b, box = block_frame(p)
    x0, y0, z0, x1, y1, z1 = box
    block = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), x1 - x0, y1 - y0, z1 - z0).Shape()
    block_w = BRepBuilderAPI_Transform(block, t.Inverted(), True).Shape()
    out = piece_info(store.put(block_w), block_w)
    out["size"] = [x1 - x0, y1 - y0, z1 - z0]
    out["part_volume"] = volume(part)
    out["part_range"] = [b[2], b[5]]
    return out


def md_split(p):
    t0 = time.time()
    ident = p.get("id")
    height = num(p, "height", None)
    if height is None:
        raise RuntimeError("The core and cavity split needs the parting height.")
    part, d, t, local, b, box = block_frame(p)
    tinv = t.Inverted()
    if not (b[2] + 1e-6 < height < b[5] - 1e-6):
        raise RuntimeError("The parting height %.4g lies outside the part (%.4g to %.4g along the pull)." % (height, b[2], b[5]))
    x0, y0, z0, x1, y1, z1 = box
    block = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), x1 - x0, y1 - y0, z1 - z0).Shape()
    void = BRepAlgoAPI_Cut(block, local)
    if not void.IsDone():
        raise RuntimeError("The part could not be cut out of the block.")
    void_shape = void.Shape()
    upper = BRepPrimAPI_MakeBox(gp_Pnt(x0 - 1.0, y0 - 1.0, height), x1 - x0 + 2.0, y1 - y0 + 2.0, z1 - height + 1.0).Shape()
    lower = BRepPrimAPI_MakeBox(gp_Pnt(x0 - 1.0, y0 - 1.0, z0 - 1.0), x1 - x0 + 2.0, y1 - y0 + 2.0, height - z0 + 1.0).Shape()
    cav = BRepAlgoAPI_Common(void_shape, upper)
    core = BRepAlgoAPI_Common(void_shape, lower)
    if not cav.IsDone() or not core.IsDone():
        raise RuntimeError("The block could not be split at the parting height.")
    plane = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0.0, 0.0, height), gp_Dir(0.0, 0.0, 1.0)), x0, x1, y0, y1).Face()
    sect = BRepAlgoAPI_Common(plane, void_shape)
    if not sect.IsDone():
        raise RuntimeError("The parting surface could not be built.")
    parting, shut = [], []
    ex = TopExp_Explorer(sect.Shape(), TopAbs_FACE)
    edge_tol = 1.0e-6 * max(1.0, x1 - x0)
    while ex.More():
        f = TopoDS.Face(ex.Current())
        fb = store.bbox_of(f)
        touches = fb[0] <= x0 + edge_tol or fb[3] >= x1 - edge_tol or fb[1] <= y0 + edge_tol or fb[4] >= y1 - edge_tol
        (parting if touches else shut).append(f)
        ex.Next()

    def world(shape):
        return BRepBuilderAPI_Transform(shape, tinv, True).Shape()

    block_w, core_w, cav_w, part_w = world(block), world(core.Shape()), world(cav.Shape()), part
    out = {}
    out["block"] = piece_info(store.put(block_w), block_w)
    out["core"] = piece_info(store.put(core_w), core_w)
    out["cavity"] = piece_info(store.put(cav_w), cav_w)
    ps = world(compound_of(parting)) if parting else None
    sh = world(compound_of(shut)) if shut else None
    out["parting_surface"] = piece_info(store.put(ps), ps) if ps is not None else None
    out["shut_offs"] = piece_info(store.put(sh), sh) if sh is not None else None
    v_block, v_part, v_core, v_cav = out["block"]["volume"], volume(part_w), out["core"]["volume"], out["cavity"]["volume"]
    overlap = BRepAlgoAPI_Common(core_w, cav_w)
    v_overlap = volume(overlap.Shape()) if overlap.IsDone() else float("nan")
    residual = v_block - v_part - v_core - v_cav
    tol = VOLUME_TOL * min(v_block, 10.0 * v_part)
    out["check"] = {"block": v_block, "part": v_part, "core": v_core, "cavity": v_cav, "sum": v_part + v_core + v_cav, "residual": residual, "relative": residual / v_block if v_block else None, "tolerance": VOLUME_TOL, "overlap": v_overlap, "ok": bool(abs(residual) <= tol and abs(v_overlap) <= tol)}
    out["shut_off_faces"] = [{"area": pl.area_of(f), "equivalent_diameter": 2.0 * math.sqrt(pl.area_of(f) / math.pi), "centre": list(pl.face_centre(f))} for f in shut]
    out["parting_faces"] = len(parting)
    out["block_size"] = [x1 - x0, y1 - y0, z1 - z0]
    out["height"] = height
    out["ms"] = int((time.time() - t0) * 1000)
    return out


METHODS = {"md_analyze": md_analyze, "md_parting": md_parting, "md_shrink": md_shrink, "md_block": md_block, "md_split": md_split}
