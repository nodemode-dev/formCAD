import math
import struct
import time

import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepLib import BRepLib
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_CylindricalSurface
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shape
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shell
from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt

import kernel_store as store

MAX_TRIANGLES = 60000
MIN_CYLINDER_TRIANGLES = 8
SEED_FLOOR = math.cos(math.radians(3.0))


def read_fcm(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 16 or data[:4] != b"FCM1":
        raise RuntimeError("The mesh file has the wrong header.")
    nv, nt, _flags = struct.unpack("<III", data[4:16])
    if len(data) != 16 + nv * 24 + nt * 12:
        raise RuntimeError("The mesh file is truncated.")
    v = np.frombuffer(data, dtype="<f8", count=nv * 3, offset=16).reshape(nv, 3).copy()
    t = np.frombuffer(data, dtype="<i4", count=nt * 3, offset=16 + nv * 24).reshape(nt, 3).astype(np.int64)
    return v, t


def adjacency(t):
    n = len(t)
    a = np.concatenate([t[:, 0], t[:, 1], t[:, 2]])
    b = np.concatenate([t[:, 1], t[:, 2], t[:, 0]])
    face = np.concatenate([np.arange(n)] * 3)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    base = int(max(a.max(), b.max())) + 1
    key = lo * base + hi
    order = np.argsort(key, kind="stable")
    k, f = key[order], face[order]
    same = np.nonzero(k[1:] == k[:-1])[0]
    i, j = f[same], f[same + 1]
    src = np.concatenate([i, j])
    dst = np.concatenate([j, i])
    o = np.argsort(src, kind="stable")
    src, dst = src[o], dst[o]
    ptr = np.searchsorted(src, np.arange(n + 1))
    return ptr, dst


def tri_geometry(v, t):
    p = v[t]
    cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nrm = cr / np.maximum(2.0 * area, 1e-300)[:, None]
    return p, nrm, area


def fit_plane(pts, weights):
    c = (pts * weights[:, None]).sum(axis=0) / weights.sum()
    q = pts - c
    cov = (q * weights[:, None]).T @ q
    w, vec = np.linalg.eigh(cov)
    return c, vec[:, 0]


def noise_slack(v, t, area, tol):
    p = v[t]
    longest = np.maximum.reduce([np.linalg.norm(p[:, 0] - p[:, 1], axis=1), np.linalg.norm(p[:, 1] - p[:, 2], axis=1), np.linalg.norm(p[:, 2] - p[:, 0], axis=1)])
    altitude = 2.0 * area / np.maximum(longest, 1e-300)
    return np.minimum(np.degrees(np.arctan(tol / np.maximum(altitude, 1e-300))), 30.0)


def grow_planes(v, t, nrm, area, ptr, dst, free, tol, angle_deg, label, next_id):
    cos_lim = np.cos(np.radians(angle_deg + noise_slack(v, t, area, tol)))
    order = np.argsort(-area, kind="stable")
    first = next_id
    planes = {}
    for s in order.tolist():
        if not free[s] or label[s] >= 0:
            continue
        members = [s]
        label[s] = next_id
        c = v[t[s]].mean(axis=0)
        n = nrm[s].copy()
        queue = [s]
        refit_at = 4
        while queue:
            cur = queue.pop()
            for j in dst[ptr[cur] : ptr[cur + 1]].tolist():
                if label[j] >= 0 or not free[j]:
                    continue
                if float(nrm[j] @ n) < cos_lim[j]:
                    continue
                if np.abs((v[t[j]] - c) @ n).max() > tol:
                    continue
                label[j] = next_id
                members.append(j)
                queue.append(j)
                if len(members) >= refit_at:
                    m = np.array(members)
                    pts = v[t[m]].reshape(-1, 3)
                    w = np.repeat(area[m], 3)
                    c, nn = fit_plane(pts, w)
                    if nn @ n < 0:
                        nn = -nn
                    n = nn
                    refit_at = len(members) * 2
        planes[next_id] = (c, n)
        next_id += 1
    sizes = {}
    for lab in label[label >= first].tolist():
        sizes[lab] = sizes.get(lab, 0) + 1
    for _ in range(3):
        moved = 0
        for ti in np.nonzero(label >= first)[0].tolist():
            if not free[ti] or sizes.get(int(label[ti]), 0) > 2:
                continue
            best, best_d = None, tol
            for j in dst[ptr[ti] : ptr[ti + 1]].tolist():
                lj = int(label[j])
                if lj < first or sizes.get(lj, 0) < 6 or lj not in planes:
                    continue
                c, n = planes[lj]
                if float(nrm[ti] @ n) < 0.9:
                    continue
                d = float(np.abs((v[t[ti]] - c) @ n).max())
                if d <= best_d:
                    best, best_d = lj, d
            if best is not None:
                sizes[int(label[ti])] -= 1
                label[ti] = best
                sizes[best] += 1
                moved += 1
        if not moved:
            break
    return next_id


def fit_circle(pts2):
    x, y = pts2[:, 0], pts2[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r2 = sol[2] + cx * cx + cy * cy
    return cx, cy, math.sqrt(max(r2, 0.0))


def axis_frame(axis):
    a = axis / np.linalg.norm(axis)
    h = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(h, a)
    x /= np.linalg.norm(x)
    y = np.cross(a, x)
    return a, x, y


def cylinder_from_region(v, t, members, axis, tol):
    a, x, y = axis_frame(axis)
    pts = np.unique(t[members].ravel())
    P = v[pts]
    cx, cy, r = fit_circle(np.column_stack([P @ x, P @ y]))
    if not (r > 1e-9):
        return None
    along = P @ a
    centre = x * cx + y * cy + a * float(along.mean())
    rad = np.hypot(P @ x - cx, P @ y - cy)
    return centre, a, r, np.abs(rad - r)


def grow_cylinders(v, t, nrm, area, ptr, dst, free, tol, angle_deg, label, next_id, diag):
    n = len(t)
    cos_adj = math.cos(math.radians(max(angle_deg, 1.0)))
    sin_perp = np.sin(np.radians(6.0 + noise_slack(v, t, area, tol)))
    cyl = {}
    seeds = []
    tried = np.zeros(n, dtype=bool)
    for i in range(n):
        if not free[i]:
            continue
        for j in dst[ptr[i] : ptr[i + 1]].tolist():
            if j <= i or not free[j]:
                continue
            d = float(nrm[i] @ nrm[j])
            if cos_adj <= d < SEED_FLOOR:
                seeds.append((i, j))
    for i, j in seeds:
        if label[i] >= 0 or label[j] >= 0 or tried[i] or tried[j]:
            continue
        ax = np.cross(nrm[i], nrm[j])
        ln = np.linalg.norm(ax)
        if ln < 1e-6:
            continue
        ax /= ln
        region = [i, j]
        label[i] = label[j] = -2
        queue = [i, j]
        while queue:
            cur = queue.pop()
            for k in dst[ptr[cur] : ptr[cur + 1]].tolist():
                if label[k] != -1 or not free[k]:
                    continue
                if abs(float(nrm[k] @ ax)) > sin_perp[k]:
                    continue
                if float(nrm[k] @ nrm[cur]) < cos_adj:
                    continue
                label[k] = -2
                region.append(k)
                queue.append(k)
        for m in region:
            label[m] = -1
            tried[m] = True
        if len(region) < MIN_CYLINDER_TRIANGLES:
            continue
        m = np.array(region)
        ax2 = None
        for _ in range(3):
            fit = cylinder_from_region(v, t, m, ax if ax2 is None else ax2, tol)
            if fit is None:
                break
            centre, a, r, err = fit
            pts = np.unique(t[m].ravel())
            vert_err = dict(zip(pts.tolist(), err.tolist()))
            keep = np.array([max(vert_err[x] for x in t[q]) <= tol for q in m])
            if keep.all():
                break
            m = m[keep]
            if len(m) < MIN_CYLINDER_TRIANGLES:
                fit = None
                break
        if fit is None or len(m) < MIN_CYLINDER_TRIANGLES:
            continue
        centre, a, r, err = fit
        if not (r < 20.0 * diag and r > 1e-4 * diag):
            continue
        nm = nrm[m]
        spread = float(np.degrees(np.arccos(np.clip(nm @ nm[0], -1.0, 1.0))).max())
        if spread < 12.0:
            continue
        keep_connected = connected_part(m, ptr, dst)
        if len(keep_connected) < MIN_CYLINDER_TRIANGLES:
            continue
        for q in keep_connected:
            label[q] = next_id
        cyl[next_id] = (centre, a, r)
        next_id += 1
    return next_id, cyl


def connected_part(members, ptr, dst):
    inside = set(members.tolist())
    seen = set()
    best = []
    for s in members.tolist():
        if s in seen:
            continue
        comp = [s]
        seen.add(s)
        stack = [s]
        while stack:
            cur = stack.pop()
            for k in dst[ptr[cur] : ptr[cur + 1]].tolist():
                if k in inside and k not in seen:
                    seen.add(k)
                    comp.append(k)
                    stack.append(k)
        if len(comp) > len(best):
            best = comp
    return best


def segment(v, t, tol, angle, merge_planar, merge_cyl):
    n = len(t)
    p, nrm, area = tri_geometry(v, t)
    label = np.full(n, -1, dtype=np.int64)
    cyl = {}
    info = {"cylinders_found": 0}
    if merge_planar or merge_cyl:
        ptr, dst = adjacency(t)
        diag = float(np.linalg.norm(v.max(axis=0) - v.min(axis=0)))
        next_id = 0
        free = np.ones(n, dtype=bool)
        if merge_cyl:
            next_id, cyl = grow_cylinders(v, t, nrm, area, ptr, dst, free, tol, 30.0, label, next_id, diag)
            info["cylinders_found"] = len(cyl)
        if merge_planar:
            free = label < 0
            next_id = grow_planes(v, t, nrm, area, ptr, dst, free, tol, angle, label, next_id)
    rest = np.nonzero(label < 0)[0]
    base = int(label.max()) + 1 if n else 0
    label[rest] = base + np.arange(len(rest))
    return label, cyl, nrm, area


class Shapes:
    def __init__(self, v, tol):
        self.v = v
        self.vtx = {}
        self.edges = {}
        self.tol = tol

    def vertex(self, i):
        got = self.vtx.get(i)
        if got is None:
            p = self.v[i]
            got = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))).Vertex()
            self.vtx[i] = got
        return got

    def edge(self, a, b):
        lo, hi = (a, b) if a < b else (b, a)
        got = self.edges.get((lo, hi))
        if got is None:
            if np.linalg.norm(self.v[lo] - self.v[hi]) < 1e-9:
                raise RuntimeError("A triangle edge has no length; repair the mesh first.")
            got = BRepBuilderAPI_MakeEdge(self.vertex(lo), self.vertex(hi)).Edge()
            self.edges[(lo, hi)] = got
        return got if a == lo else TopoDS.Edge(got.Reversed())

    def wire(self, loop):
        mw = BRepBuilderAPI_MakeWire()
        for k in range(len(loop)):
            mw.Add(self.edge(loop[k], loop[(k + 1) % len(loop)]))
        if not mw.IsDone():
            raise RuntimeError("A boundary loop could not be closed into a wire.")
        return mw.Wire()


def region_loops(t, members, in_region):
    directed = {}
    for ti in members:
        a, b, c = t[ti]
        for u, w in ((a, b), (b, c), (c, a)):
            directed[(u, w)] = ti
    boundary = [(u, w) for (u, w) in directed if (w, u) not in directed]
    nxt = {}
    for u, w in boundary:
        nxt.setdefault(u, []).append(w)
    used = set()
    loops = []
    for u, w in boundary:
        if (u, w) in used:
            continue
        loop = [u]
        cur, step = u, w
        while True:
            used.add((cur, step))
            if step == loop[0]:
                break
            loop.append(step)
            options = [x for x in nxt.get(step, []) if (step, x) not in used]
            if not options:
                break
            cur, step = step, options[0]
        if len(loop) >= 3 and step == loop[0]:
            loops.append(loop)
    return loops


def loop_area(v, loop, n):
    p = v[loop]
    return float(np.dot(np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0), n)) / 2.0


def face_normal_dot(face, want):
    try:
        gf = BRepGProp_Face(face)
        u0, u1, v0, v1 = gf.Bounds()
        pnt = gp_Pnt()
        from OCP.gp import gp_Vec

        vec = gp_Vec()
        gf.Normal((u0 + u1) / 2.0, (v0 + v1) / 2.0, pnt, vec)
        return vec.X() * want[0] + vec.Y() * want[1] + vec.Z() * want[2]
    except Exception:
        return 1.0


def planar_face(sh, v, t, members, loops, nrm, area):
    m = np.array(members)
    pts = v[t[m]].reshape(-1, 3)
    c, n = fit_plane(pts, np.repeat(area[m], 3))
    mean = (nrm[m] * area[m][:, None]).sum(axis=0)
    if n @ mean < 0:
        n = -n
    plane = gp_Pln(gp_Pnt(float(c[0]), float(c[1]), float(c[2])), gp_Dir(float(n[0]), float(n[1]), float(n[2])))
    areas = [loop_area(v, lp, n) for lp in loops]
    order = np.argsort([-abs(a) for a in areas])
    outer = loops[order[0]]
    if areas[order[0]] < 0:
        outer = outer[::-1]
    mf = BRepBuilderAPI_MakeFace(plane, sh.wire(outer), True)
    for k in order[1:]:
        hole = loops[k]
        if areas[k] > 0:
            hole = hole[::-1]
        mf.Add(sh.wire(hole))
    if not mf.IsDone():
        raise RuntimeError("A flat region could not be made into a face.")
    face = mf.Face()
    return face, n, float(np.abs((v[np.unique(t[m].ravel())] - c) @ n).max())


def cylinder_face(sh, v, t, members, loops, centre, axis, radius, nrm, area):
    m = np.array(members)
    mean = (nrm[m] * area[m][:, None]).sum(axis=0)
    ax = gp_Ax3(gp_Pnt(float(centre[0]), float(centre[1]), float(centre[2])), gp_Dir(float(axis[0]), float(axis[1]), float(axis[2])))
    surf = Geom_CylindricalSurface(ax, float(radius))
    ordered = sorted(loops, key=lambda lp: -len(lp))
    mf = BRepBuilderAPI_MakeFace(surf, sh.wire(ordered[0]), True)
    for lp in ordered[1:]:
        mf.Add(sh.wire(lp))
    face = mf.Face()
    fixer = ShapeFix_Face(face)
    fixer.SetPrecision(max(sh.tol, 1e-6))
    fixer.SetMaxTolerance(max(sh.tol * 20.0, 1e-3))
    fixer.Perform()
    face = fixer.Face()
    return face, mean


def free_edge_count(shape):
    fb = ShapeAnalysis_FreeBounds(shape, 1e-6, False, False)
    total = 0
    for w in (fb.GetClosedWires(), fb.GetOpenWires()):
        if w is None or w.IsNull():
            continue
        ex = TopExp_Explorer(w, TopAbs_EDGE)
        while ex.More():
            total += 1
            ex.Next()
    return total


def build_shape(v, t, label, cyl, nrm, area, tol, report):
    sh = Shapes(v, tol)
    groups = {}
    for ti, lab in enumerate(label.tolist()):
        groups.setdefault(lab, []).append(ti)
    b = BRep_Builder()
    shell = TopoDS_Shell()
    b.MakeShell(shell)
    planar_faces = cyl_faces = failed = 0
    for lab, members in groups.items():
        loops = region_loops(t, members, None)
        if not loops:
            raise RuntimeError("A group of triangles has no closed boundary; the mesh is not a clean surface.")
        face = None
        if lab in cyl:
            centre, axis, radius = cyl[lab]
            try:
                f, mean = cylinder_face(sh, v, t, members, loops, centre, axis, radius, nrm, area)
                if face_normal_dot(f, mean) < 0:
                    f = TopoDS.Face(f.Reversed())
                face = f
                cyl_faces += 1
            except Exception:
                failed += 1
                face = None
        if face is None and len(members) > 1 and lab not in cyl:
            try:
                f, n, dev = planar_face(sh, v, t, members, loops, nrm, area)
                face = f
                planar_faces += 1
            except Exception:
                face = None
        if face is None:
            for ti in members:
                a, c, d = t[ti]
                p = v[[a, c, d]]
                nn = np.cross(p[1] - p[0], p[2] - p[0])
                ln = np.linalg.norm(nn)
                if ln < 1e-14:
                    raise RuntimeError("A triangle has no area; repair the mesh first.")
                nn /= ln
                plane = gp_Pln(gp_Pnt(float(p[0][0]), float(p[0][1]), float(p[0][2])), gp_Dir(float(nn[0]), float(nn[1]), float(nn[2])))
                mf = BRepBuilderAPI_MakeFace(plane, sh.wire([int(a), int(c), int(d)]), True)
                if not mf.IsDone():
                    raise RuntimeError("A triangle could not be made into a face.")
                b.Add(shell, mf.Face())
            continue
        b.Add(shell, face)
    report["planar_faces"] = planar_faces
    report["cylinder_faces"] = cyl_faces
    report["cylinder_failed"] = failed
    return shell


def raise_tolerances(shell, tol):
    from OCP.ShapeFix import ShapeFix_ShapeTolerance

    ShapeFix_ShapeTolerance().LimitTolerance(shell, 1e-7, float(tol) * 1.05)


def mesh_to_brep(p):
    began = time.time()
    path = store.absolute_path(p.get("path"), (".fcm",), True)
    v, t = read_fcm(path)
    if len(t) > MAX_TRIANGLES:
        raise RuntimeError("The mesh has %d triangles; the worker converts at most %d. Reduce it first." % (len(t), MAX_TRIANGLES))
    tol = float(p.get("tolerance") or 1e-3)
    if not (tol > 0):
        raise RuntimeError("The tolerance must be positive.")
    angle = float(p.get("angle") or 4.0)
    merge_planar = bool(p.get("merge_planar", True))
    merge_cyl = bool(p.get("merge_cylinders", False))
    out = convert(v, t, tol, angle, merge_planar, merge_cyl)
    if merge_cyl and out["report"]["cylinder_faces"] and not (out["report"]["valid"] and out["report"]["closed"]):
        store.free([out["id"]])
        out = convert(v, t, tol, angle, merge_planar, False)
        out["report"]["cylinder_dropped"] = "the solid with round faces was not valid, so the flat-face result is given"
    out["report"]["seconds"] = round(time.time() - began, 3)
    return out


def convert(v, t, tol, angle, merge_planar, merge_cyl):
    report = {"triangles": int(len(t))}
    label, cyl, nrm, area = segment(v, t, tol, angle, merge_planar, merge_cyl)
    report["regions"] = int(len(np.unique(label)))
    report["cylinders_found"] = len(cyl)
    shell = build_shape(v, t, label, cyl, nrm, area, tol, report)
    if merge_planar or merge_cyl:
        raise_tolerances(shell, tol)
    BRepLib.SameParameter_s(shell, 1e-7, True)
    free = free_edge_count(shell)
    solid_made = False
    shape = shell
    if free == 0:
        shell.Closed(True)
        ms = BRepBuilderAPI_MakeSolid(shell)
        if ms.IsDone():
            solid = ms.Solid()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, props)
            if props.Mass() < 0:
                solid = TopoDS.Solid(solid.Reversed())
            shape = solid
            solid_made = True
    if merge_planar and solid_made:
        try:
            uni = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
            uni.SetLinearTolerance(max(tol, 1e-7))
            uni.SetAngularTolerance(math.radians(min(angle, 5.0)) * 0.1)
            uni.Build()
            cand = uni.Shape()
            if free_edge_count(cand) == 0 and BRepCheck_Analyzer(cand).IsValid():
                shape = cand
        except Exception:
            pass
    summary = store.summarize(shape)
    if solid_made and not summary["valid"]:
        healed = ShapeFix_Shape(shape)
        healed.Perform()
        again = store.summarize(healed.Shape())
        if again["valid"]:
            shape, summary = healed.Shape(), again
    ident = store.put(shape)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    report["volume"] = float(props.Mass()) if solid_made else None
    report["free_edges"] = int(free_edge_count(shape))
    summary["closed"] = bool(solid_made and report["free_edges"] == 0)
    report["valid"] = bool(summary["valid"])
    report["closed"] = bool(summary["closed"])
    report["solid"] = bool(solid_made)
    report["faces"] = int(summary["faces"])
    return {"id": ident, "summary": summary, "report": report}


METHODS = {"mesh_to_brep": mesh_to_brep}
