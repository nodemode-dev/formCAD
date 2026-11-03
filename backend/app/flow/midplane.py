import numpy as np

from app.flow.limits import FlowError, restricted

RAY_PAIRS = (40_000_000, 8_000_000)
MIN_COS = 0.5
LABEL = "Midplane taken half the local thickness below the skin that faces the mould opening direction; thickness measured along that direction to the opposite skin."


def outward_normals(mesh, facets: np.ndarray) -> tuple:
    tri = mesh.facets[:, facets].T
    p = mesh.p.T
    a, b, c = p[tri[:, 0]], p[tri[:, 1]], p[tri[:, 2]]
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    n = cross / np.maximum(2.0 * area, 1e-300)[:, None]
    owner = mesh.f2t[0, facets]
    centre = p[mesh.t[:4, owner]].mean(axis=0)
    flip = np.einsum("ij,ij->i", n, (a + b + c) / 3.0 - centre) < 0
    n[flip] = -n[flip]
    tri = tri.copy()
    tri[flip, 1], tri[flip, 2] = tri[flip, 2].copy(), tri[flip, 1].copy()
    return tri, n, area


def default_pull(points: np.ndarray) -> np.ndarray:
    cov = np.cov((points - points.mean(axis=0)).T)
    vals, vecs = np.linalg.eigh(cov)
    return vecs[:, 0]


def ray_distance(origins: np.ndarray, direction: np.ndarray, tris: np.ndarray, points: np.ndarray, runner=None, check=None) -> np.ndarray:
    limit = RAY_PAIRS[1] if restricted(runner) else RAY_PAIRS[0]
    if len(origins) * len(tris) > limit:
        raise FlowError("The thickness measurement needs %d ray and triangle pairs, above the limit of %d. Use a coarser mesh." % (len(origins) * len(tris), limit))
    a, b, c = points[tris[:, 0]], points[tris[:, 1]], points[tris[:, 2]]
    e1, e2 = b - a, c - a
    pv = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, pv)
    ok = np.abs(det) > 1e-18
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    best = np.full(len(origins), np.inf)
    chunk = max(1, int(2_000_000 // max(len(tris), 1)))
    for s in range(0, len(origins), chunk):
        if check:
            check()
        o = origins[s : s + chunk]
        t = o[:, None, :] - a[None, :, :]
        u = np.einsum("ijk,jk->ij", t, pv) * inv[None, :]
        q = np.cross(t, e1[None, :, :])
        v = np.einsum("k,ijk->ij", direction, q) * inv[None, :]
        d = np.einsum("jk,ijk->ij", e2, q) * inv[None, :]
        hit = ok[None, :] & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1.0 + 1e-9) & (d > 1e-9)
        d = np.where(hit, d, np.inf)
        best[s : s + chunk] = d.min(axis=1)
    return best


def extract(mesh, gate_facets: np.ndarray, pull=None, runner=None, check=None) -> dict:
    every = np.asarray(mesh.boundary_facets(), dtype=np.int64)
    tri, normals, area = outward_normals(mesh, every)
    p = mesh.p.T
    if pull is None:
        pull = default_pull(p[np.unique(tri)])
    pull = np.asarray(pull, dtype=float)
    pull = pull / np.linalg.norm(pull)
    cosine = normals @ pull
    top = tri[cosine > MIN_COS]
    bottom = tri[cosine < -MIN_COS]
    if len(top) < 4 or len(bottom) < 4:
        raise FlowError("The part has no two opposite skins along the opening direction, so it is not a thin walled part this model can fill.")
    ids = np.unique(top)
    local = np.searchsorted(ids, top)
    thick = ray_distance(p[ids], -pull, bottom, p, runner, check)
    bad = ~np.isfinite(thick)
    if bad.all():
        raise FlowError("The thickness could not be measured; check the mould opening direction.")
    if bad.any():
        thick[bad] = np.median(thick[~bad])
    points = p[ids] - pull[None, :] * (thick / 2.0)[:, None]
    gate_tri = mesh.facets[:, np.asarray(gate_facets, dtype=np.int64)].T
    gate_pts = p[np.unique(gate_tri)]
    from scipy.spatial import cKDTree

    d, _ = cKDTree(gate_pts).query(p[ids])
    edges = np.concatenate([local[:, [0, 1]], local[:, [1, 2]], local[:, [2, 0]]])
    med = float(np.median(np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)))
    near = d <= float(d.min()) + 0.5 * med
    return {
        "points": points,
        "tris": local,
        "thickness": thick,
        "gates": np.nonzero(near)[0],
        "volume_ids": ids,
        "pull": pull,
        "label": LABEL,
        "edge_length": med,
        "skin_points": p[ids],
    }


def spread_to_nodes(mesh_points: np.ndarray, plane: dict, values: np.ndarray, pull: np.ndarray) -> np.ndarray:
    from scipy.spatial import cKDTree

    helper = np.array([1.0, 0, 0]) if abs(pull[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(pull, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(pull, e1)
    src = np.stack([plane["skin_points"] @ e1, plane["skin_points"] @ e2], axis=1)
    dst = np.stack([mesh_points @ e1, mesh_points @ e2], axis=1)
    _, idx = cKDTree(src).query(dst)
    return values[idx]
