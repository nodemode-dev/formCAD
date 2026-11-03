import hashlib
import math
import os
import tempfile
import threading

import numpy as np

from app.cam import geom, limits
from app.cam.limits import CamError
from app.doc.model import SPACE_MODEL
from app.param.units import mm_per_unit
from app.solid import scene as scene_mod
from app.solid import work

TABLE = "cam"
MESH_CACHE: dict = {}
_cache_lock = threading.Lock()
ORIGINS = ("stock_top_min", "stock_top_center", "stock_bottom_min", "model", "custom")


def table(d):
    return d.tables.get(TABLE)


def rows(d, kind: str) -> list:
    t = table(d)
    if t is None:
        return []
    out = [r for r in t.values() if r.get("kind") == kind]
    return sorted(out, key=lambda r: (len(str(r["id"])), str(r["id"])))


def setups(d) -> list:
    return rows(d, "setup")


def ops(d) -> list:
    return rows(d, "op")


def tool_rows(d) -> list:
    return sorted(rows(d, "tool"), key=lambda r: r["number"])


def get_setup(d, sid: str) -> dict:
    t = table(d)
    rec = t.get("setup:%s" % sid) if t is not None else None
    if rec is None:
        raise CamError("There is no setup %s." % sid)
    return rec


def get_op(d, oid: str) -> dict:
    t = table(d)
    rec = t.get("op:%s" % oid) if t is not None else None
    if rec is None:
        raise CamError("There is no operation %s." % oid)
    return rec


def get_tool(d, number) -> dict:
    t = table(d)
    rec = t.get("tool:T%d" % int(number)) if t is not None else None
    if rec is None:
        raise CamError("Tool T%s is not in this document; import it from the library first." % number)
    return rec


def next_id(d, kind: str, prefix: str) -> str:
    used = {r["id"] for r in rows(d, kind)}
    n = 1
    while "%s%d" % (prefix, n) in used:
        n += 1
    return "%s%d" % (prefix, n)


def rot_from(setup) -> np.ndarray:
    w = setup["wcs"]
    z = np.asarray(w.get("z") or [0, 0, 1], dtype=float)
    x = np.asarray(w.get("x") or [1, 0, 0], dtype=float)
    z = z / np.linalg.norm(z)
    x = x - z * float(np.dot(x, z))
    nx = np.linalg.norm(x)
    if nx < 1e-9:
        raise CamError("The WCS x axis cannot be parallel to its z axis.")
    x = x / nx
    y = np.cross(z, x)
    return np.stack([x, y, z], axis=1)


def to_wcs(setup) -> np.ndarray:
    r = rot_from(setup)
    o = np.asarray(setup["wcs"]["origin"], dtype=float)
    m = np.eye(4)
    m[:3, :3] = r.T
    m[:3, 3] = -r.T @ o
    return m


def apply_m(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    a = np.asarray(pts, dtype=float)
    shape = a.shape
    flat = a.reshape(-1, 3)
    return (flat @ m[:3, :3].T + m[:3, 3]).reshape(shape)


def _body_ents(d, setup=None) -> list:
    out = []
    for e in d.ordered_entities():
        if e.kind not in ("solidbody", "meshbody") or e.owner != SPACE_MODEL or not d.visible(e):
            continue
        out.append(e)
    return out


def _ent_triangles(d, e) -> np.ndarray:
    k = mm_per_unit(d)
    if e.kind == "meshbody":
        from app.meshes import store as mesh_store

        raw = mesh_store.scene_bytes(d, e)
    else:
        raw = work.mesh_for(d, e, 1.0)
    m = scene_mod.parse(raw)
    pos = m["pos"].astype(np.float64) + np.asarray(e.offset, dtype=float) * k
    idx = m["idx"].astype(np.int64).reshape(-1, 3)
    return pos[idx]


def _assembly_triangles(doc, comp: str) -> dict:
    from app.views import sources

    items = sources._assembly_items(doc, comp, True)
    out = {}
    for it in items:
        with tempfile.TemporaryDirectory(prefix="fccam_") as tmp:
            path = os.path.join(tmp, "b.mesh")
            linear, angular = work.detail_params(it.body.summary, 1.0)
            work.kcall("tessellate", {"id": it.wid, "linear": linear, "angular": angular, "path": path}, work.LONG)
            with open(path, "rb") as fh:
                raw = fh.read()
        m = scene_mod.parse(raw)
        pos = m["pos"].astype(np.float64)
        mat = np.asarray(it.matrix, dtype=float).reshape(3, 4)
        pos = pos @ mat[:, :3].T + mat[:, 3]
        out[it.key] = pos[m["idx"].astype(np.int64).reshape(-1, 3)]
    return out


def _sig_of(parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
    return h.hexdigest()[:20]


def source_signature(doc) -> str:
    d = doc.drawing
    from app.assembly import store as astore

    parts = [mm_per_unit(d)]
    if astore.is_assembly(d):
        from app.views import sources

        try:
            parts.append(sources.current_signature(doc, {}))
        except Exception:
            parts.append("asm")
    else:
        for e in _body_ents(d):
            parts.append((e.handle, getattr(e, "blob", ""), int(getattr(e, "version", 0) or 0), tuple(round(float(v), 9) for v in e.offset)))
    return _sig_of(parts)


def model_triangles(doc, handles=None, exclude=None) -> np.ndarray:
    d = doc.drawing
    from app.assembly import store as astore

    sig = (doc.id, source_signature(doc))
    with _cache_lock:
        hit = MESH_CACHE.get(sig)
    if hit is None:
        per = {}
        if astore.is_assembly(d):
            per = _assembly_triangles(doc, "")
        else:
            for e in _body_ents(d):
                per[str(e.handle)] = _ent_triangles(d, e)
        if not per:
            raise CamError("There is no solid or mesh body to machine in this document.")
        hit = per
        with _cache_lock:
            for k in [k for k in MESH_CACHE if k[0] == doc.id]:
                MESH_CACHE.pop(k, None)
            MESH_CACHE[sig] = hit
    keys = list(hit)
    if handles:
        want = {str(h) for h in handles}
        keys = [k for k in keys if k in want]
    if exclude:
        drop = {str(h) for h in exclude}
        keys = [k for k in keys if k not in drop]
    if not keys:
        raise CamError("The setup's bodies are not in the document.")
    tris = np.concatenate([hit[k] for k in keys], axis=0)
    limits.need(len(tris), "triangles", "Model")
    return tris


def setup_triangles(doc, setup) -> np.ndarray:
    tris = model_triangles(doc, setup.get("bodies") or None, setup.get("fixtures") or None)
    return apply_m(to_wcs_setup(doc, setup), tris)


def fixture_triangles(doc, setup):
    fx = setup.get("fixtures") or []
    if not fx:
        return None
    tris = model_triangles(doc, fx, None)
    return apply_m(to_wcs_setup(doc, setup), tris)


def model_bounds_mm(doc, setup) -> tuple:
    tris = model_triangles(doc, setup.get("bodies") or None, setup.get("fixtures") or None)
    a = tris.reshape(-1, 3)
    return a.min(axis=0), a.max(axis=0)


def _box_corners(lo, hi):
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])


def stock_extent_model(doc, setup) -> tuple:
    st = setup["stock"]
    kind = st.get("kind", "from_model")
    off = st.get("offsets") or {}
    lo, hi = model_bounds_mm(doc, setup)
    ox = np.asarray(setup["wcs"].get("origin_model_hint") or [0, 0, 0], dtype=float)
    if kind == "from_model":
        lo = lo - np.array([off.get("xmin", 0), off.get("ymin", 0), off.get("zmin", 0)], dtype=float)
        hi = hi + np.array([off.get("xmax", 0), off.get("ymax", 0), off.get("zmax", 0)], dtype=float)
        return lo, hi
    dims = st.get("dims") or [0, 0, 0]
    c = (lo + hi) / 2.0
    pos = st.get("position")
    if kind == "box":
        base = np.asarray(pos, dtype=float) if pos else np.array([c[0] - dims[0] / 2.0, c[1] - dims[1] / 2.0, hi[2] - dims[2]])
        return base, base + np.asarray(dims, dtype=float)
    dia = float(st.get("diameter") or max(dims[0], dims[1]))
    ln = float(st.get("length") or dims[2])
    base = np.asarray(pos, dtype=float) if pos else np.array([c[0] - dia / 2.0, c[1] - dia / 2.0, hi[2] - ln])
    return base, base + np.array([dia, dia, ln])


def stock_origin(doc, setup) -> list:
    w = setup["wcs"]
    on = w.get("origin_on", "custom")
    if on == "custom":
        return list(w["origin"])
    if on == "model":
        lo, hi = model_bounds_mm(doc, setup)
        return [float(lo[0]), float(lo[1]), float(hi[2])]
    lo, hi = stock_extent_model(doc, setup)
    if on == "stock_top_min":
        return [float(lo[0]), float(lo[1]), float(hi[2])]
    if on == "stock_top_center":
        return [float((lo[0] + hi[0]) / 2.0), float((lo[1] + hi[1]) / 2.0), float(hi[2])]
    return [float(lo[0]), float(lo[1]), float(lo[2])]


def resolve_wcs(doc, setup) -> dict:
    out = dict(setup)
    w = dict(setup["wcs"])
    if w.get("origin_on", "custom") != "custom":
        w["origin"] = stock_origin(doc, setup)
    out["wcs"] = w
    return out


def to_wcs_setup(doc, setup) -> np.ndarray:
    return to_wcs(resolve_wcs(doc, setup))


def stock_box(doc, setup) -> dict:
    full = resolve_wcs(doc, setup)
    lo, hi = stock_extent_model(doc, setup)
    m = to_wcs(full)
    c = apply_m(m, _box_corners(lo, hi))
    st = setup["stock"]
    return {"min": c.min(axis=0).tolist(), "max": c.max(axis=0).tolist(), "kind": st.get("kind", "from_model"), "origin": full["wcs"]["origin"]}


def stock_polygon(doc, setup) -> list:
    sb = stock_box(doc, setup)
    st = setup["stock"]
    lo, hi = sb["min"], sb["max"]
    if st.get("kind") in ("cylinder", "tube"):
        cx, cy = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0
        r = (hi[0] - lo[0]) / 2.0
        rings = [geom.circle_ring(cx, cy, r, 0.01, True)]
        if st.get("kind") == "tube" and st.get("inner"):
            rings.append(geom.circle_ring(cx, cy, float(st["inner"]) / 2.0, 0.01, False))
        return rings
    return [geom.rect_ring(lo[0], lo[1], hi[0], hi[1])]


def section_loops(tris: np.ndarray, zc: float, tol: float = 0.002) -> list:
    z = tris[:, :, 2]
    below = z < zc + 1e-7
    cross = below.any(axis=1) & ~below.all(axis=1)
    t = tris[cross]
    if not len(t):
        return []
    zz = t[:, :, 2]
    bb = zz < zc + 1e-7
    pts = []
    masks = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        m = bb[:, i] != bb[:, j]
        dz = zz[:, j] - zz[:, i]
        dz = np.where(np.abs(dz) < 1e-12, 1e-12, dz)
        tt = (zc + 1e-7 - zz[:, i]) / dz
        p = t[:, i, :2] + tt[:, None] * (t[:, j, :2] - t[:, i, :2])
        pts.append(p)
        masks.append(m)
    P = np.stack(pts, axis=1)
    M = np.stack(masks, axis=1)
    keep = M.sum(axis=1) == 2
    seg = P[keep][M[keep]].reshape(-1, 2, 2)
    if not len(seg):
        return []
    q = np.round(seg / tol).astype(np.int64)
    adj: dict = {}
    for i in range(len(seg)):
        a, b = tuple(q[i, 0]), tuple(q[i, 1])
        if a == b:
            continue
        adj.setdefault(a, []).append((b, i))
        adj.setdefault(b, []).append((a, i))
    used = np.zeros(len(seg), dtype=bool)
    loops = []
    for i in range(len(seg)):
        if used[i]:
            continue
        a, b = tuple(q[i, 0]), tuple(q[i, 1])
        if a == b:
            used[i] = True
            continue
        used[i] = True
        chain = [a, b]
        while True:
            nxt = None
            for nb, si in adj.get(chain[-1], []):
                if not used[si]:
                    nxt = (nb, si)
                    break
            if nxt is None:
                break
            used[nxt[1]] = True
            chain.append(nxt[0])
            if chain[-1] == chain[0]:
                break
        if len(chain) >= 4 and chain[-1] == chain[0]:
            loops.append([(c[0] * tol, c[1] * tol) for c in chain[:-1]])
    return loops


def section_region(tris: np.ndarray, zc: float) -> list:
    loops = section_loops(tris, zc)
    limits.need(geom.vertex_count(loops), "region_vertices", "Section outline")
    return geom.normalize(loops)


def circle_fit(ring, tol=0.02):
    a = np.asarray(ring, dtype=float)
    if len(a) < 8:
        return None
    A = np.c_[2 * a[:, 0], 2 * a[:, 1], np.ones(len(a))]
    b = (a ** 2).sum(axis=1)
    try:
        sol = np.linalg.lstsq(A, b, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0], sol[1]
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    dev = np.abs(np.hypot(a[:, 0] - cx, a[:, 1] - cy) - r).max()
    if dev > max(tol, r * 0.01):
        return None
    return float(cx), float(cy), float(r)


def holes_of(region_rings) -> list:
    out = []
    for r in region_rings:
        if not geom.is_ccw(r):
            c = circle_fit(r)
            if c:
                out.append({"x": c[0], "y": c[1], "diameter": 2.0 * c[2]})
    return out


def _entity_rings(d, handles, m) -> list:
    from app.doc import planar as P

    k = mm_per_unit(d)
    rings = []
    for h in handles:
        e = d.ents.get(int(h))
        if e is None:
            raise CamError("There is no entity %s." % h)
        elev = 0.0
        if e.kind == "circle":
            pts = geom.circle_ring(e.center[0] * k, e.center[1] * k, e.radius * k, 0.01)
            elev = (e.center[2] if len(e.center) > 2 else 0.0) * k
        elif e.kind == "lwpolyline" and e.closed:
            ring = P.flatten_loop(e.vertices, 0.05)
            pts = [(p[0] * k, p[1] * k) for p in ring]
        else:
            raise CamError("Entity %s must be a circle or a closed polyline." % h)
        a = apply_m(m, np.array([[p[0], p[1], elev] for p in pts]))
        rings.append([(float(p[0]), float(p[1])) for p in a])
    return rings


def _poly_rings(paths, z, m) -> list:
    rings = []
    for p in paths:
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            raise CamError("Each outline needs at least three points.")
        a = apply_m(m, np.array([[float(q[0]), float(q[1]), float(z)] for q in p]))
        rings.append([(float(q[0]), float(q[1])) for q in a])
    limits.need(geom.vertex_count(rings), "region_vertices", "Outline")
    return rings


def build_region(doc, setup, geometry, tool_radius=0.0, section_z=None, tris=None) -> list:
    d = doc.drawing
    g = geometry or {}
    kind = g.get("kind")
    m = to_wcs_setup(doc, setup)
    if kind == "polygons":
        return geom.normalize(_poly_rings(g.get("paths") or [], g.get("z", 0.0), m))
    if kind == "rect":
        a, b = g["min"], g["max"]
        return geom.normalize(_poly_rings([[[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]], g.get("z", 0.0), m))
    if kind == "entities":
        return geom.normalize(_entity_rings(d, g.get("handles") or [], m))
    if kind == "stock":
        return geom.normalize(stock_polygon(doc, setup))
    if kind in ("section", "removal"):
        z = g.get("z", section_z)
        if z is None:
            raise CamError("Give the height of the section.")
        if tris is None:
            tris = setup_triangles(doc, setup)
        solid = section_region(tris, float(z))
        part = g.get("part", "removal" if kind == "removal" else "all")
        if part == "all":
            out = solid
        elif part == "outer":
            out = geom.normalize([r for r in solid if geom.is_ccw(r)])
        elif part == "holes":
            out = geom.difference(geom.union([r for r in solid if geom.is_ccw(r)]), solid)
        else:
            margin = tool_radius * 1.1 + float(g.get("margin", 1.0))
            out = geom.difference(geom.offset(stock_polygon(doc, setup), margin), solid)
        clip = g.get("clip")
        if clip:
            a, b = clip["min"], clip["max"]
            box = _poly_rings([[[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]], g.get("clip_z", 0.0), m)
            out = geom.intersection(out, box)
        return out
    raise CamError("Geometry kind must be polygons, rect, entities, stock, section or removal.")


def build_points(doc, setup, geometry, tris=None) -> list:
    g = geometry or {}
    kind = g.get("kind")
    m = to_wcs_setup(doc, setup)
    if kind == "points":
        pts = g.get("points") or []
        limits.need(len(pts), "holes", "Hole list")
        a = apply_m(m, np.array([[float(p[0]), float(p[1]), float(g.get("z", 0.0)) if len(p) < 3 else float(p[2])] for p in pts])) if pts else np.zeros((0, 3))
        return [{"x": float(p[0]), "y": float(p[1]), "diameter": None} for p in a]
    if kind == "model_holes":
        z = g.get("z")
        if z is None:
            raise CamError("Give the height at which to find holes.")
        if tris is None:
            tris = setup_triangles(doc, setup)
        solid = section_region(tris, float(z))
        found = holes_of(solid)
        lo = g.get("min_diameter")
        hi = g.get("max_diameter")
        found = [h for h in found if (lo is None or h["diameter"] >= lo) and (hi is None or h["diameter"] <= hi)]
        limits.need(len(found), "holes", "Holes found")
        return found
    if kind == "entities":
        d = doc.drawing
        k = mm_per_unit(d)
        out = []
        for h in g.get("handles") or []:
            e = d.ents.get(int(h))
            if e is None or e.kind != "circle":
                raise CamError("Entity %s must be a circle." % h)
            a = apply_m(m, np.array([[e.center[0] * k, e.center[1] * k, (e.center[2] if len(e.center) > 2 else 0.0) * k]]))[0]
            out.append({"x": float(a[0]), "y": float(a[1]), "diameter": 2.0 * e.radius * k})
        return out
    raise CamError("Hole geometry kind must be points, model_holes or entities.")
