import numpy as np

from app.meshes import core
from app.meshes.core import Mesh, MeshError

COLLINEAR = 1e-7


def frame(normal):
    n = np.asarray(normal, dtype=np.float64)
    ln = float(np.linalg.norm(n))
    if not ln > 1e-12:
        raise MeshError("The section plane needs a normal direction.")
    n = n / ln
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(helper, n)
    x /= np.linalg.norm(x)
    y = np.cross(n, x)
    return x, y, n


def chain(segments):
    adj = {}
    for k, (a, b) in enumerate(segments):
        adj.setdefault(a, []).append((b, k))
        adj.setdefault(b, []).append((a, k))
    used = [False] * len(segments)
    out = []
    starts = [n for n, lst in adj.items() if len(lst) == 1] + list(adj)
    for s in starts:
        for first in list(adj[s]):
            if used[first[1]]:
                continue
            line = [s]
            step = first
            while True:
                nb, k = step
                used[k] = True
                line.append(nb)
                more = [e for e in adj[nb] if not used[e[1]]]
                if not more:
                    break
                step = more[0]
            out.append(line)
    return out


def simplify_line(pts, closed):
    pts = [np.asarray(p) for p in pts]
    if len(pts) < 3:
        return pts
    keep = []
    n = len(pts)
    for i in range(n):
        if not closed and (i == 0 or i == n - 1):
            keep.append(pts[i])
            continue
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        ab, bc = b - a, c - b
        cr = np.linalg.norm(np.cross(ab, bc))
        la, lb = np.linalg.norm(ab), np.linalg.norm(bc)
        if la < 1e-12 or lb < 1e-12 or cr / max(la, 1e-300) > COLLINEAR:
            keep.append(b)
    return keep


def section_own(m: Mesh, origin, normal) -> list:
    x, y, n = frame(normal)
    d = (m.v - np.asarray(origin)) @ n
    eps = 1e-12 * max(1.0, float(np.abs(d).max()) if len(d) else 1.0)
    d = np.where(np.abs(d) <= eps, eps, d)
    pos = d > 0
    tri = m.t
    mixed = pos[tri].any(axis=1) & ~pos[tri].all(axis=1)
    idx = np.nonzero(mixed)[0]
    node_of = {}
    pts = []
    segs = []

    def node(a, b):
        k = (a, b) if a < b else (b, a)
        got = node_of.get(k)
        if got is None:
            t = d[a] / (d[a] - d[b])
            p = m.v[a] + (m.v[b] - m.v[a]) * t
            got = len(pts)
            node_of[k] = got
            pts.append(p)
        return got

    for ti in idx.tolist():
        a, b, c = tri[ti].tolist()
        crossing = [(u, v) for u, v in ((a, b), (b, c), (c, a)) if pos[u] != pos[v]]
        if len(crossing) == 2:
            segs.append((node(*crossing[0]), node(*crossing[1])))
    lines = chain(segs)
    out = []
    for ln in lines:
        closed = len(ln) > 2 and ln[0] == ln[-1]
        ids = ln[:-1] if closed else ln
        poly = simplify_line([pts[i] for i in ids], closed)
        if len(poly) >= 2:
            out.append({"points": np.array(poly), "closed": bool(closed)})
    return out


def section_manifold(m: Mesh, origin, normal):
    import manifold3d as mf

    x, y, n = frame(normal)
    rot = np.stack([x, y, n])
    local = (m.v - np.asarray(origin)) @ rot.T
    mesh = mf.Mesh64(local, m.t.astype(np.uint64))
    solid = mf.Manifold(mesh)
    if solid.status() != mf.Error.NoError or solid.is_empty():
        return None
    cs = solid.slice(0.0)
    out = []
    for poly in cs.to_polygons():
        arr = np.asarray(poly)
        if len(arr) < 3:
            continue
        p3 = np.column_stack([arr, np.zeros(len(arr))]) @ rot + np.asarray(origin)
        out.append({"points": np.array(simplify_line(list(p3), True)), "closed": True})
    return out


def section(m: Mesh, origin, normal, prefer_manifold: bool = True) -> tuple:
    if not len(m.t):
        raise MeshError("The mesh has no triangles.")
    lines = None
    route = "segments"
    if prefer_manifold:
        r = core.report(m)
        if r["closed"] and r["volume"] is not None and r["volume"] > 0:
            try:
                lines = section_manifold(m, origin, normal)
                route = "manifold"
            except Exception:
                lines = None
    if lines is None:
        lines = section_own(m, origin, normal)
        route = "segments"
    return lines, route


def length_of(line) -> float:
    p = line["points"]
    if len(p) < 2:
        return 0.0
    total = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    if line["closed"]:
        total += float(np.linalg.norm(p[0] - p[-1]))
    return total


def area_of(line, normal) -> float:
    p = line["points"]
    if len(p) < 3 or not line["closed"]:
        return 0.0
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    c = np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)
    return abs(float(np.dot(c, n))) / 2.0
