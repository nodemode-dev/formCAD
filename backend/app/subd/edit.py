import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from app.subd import sym as symmetry
from app.subd.cage import Cage, rotate
from app.subd.cc import SubdError

FALLOFFS = ("smooth", "linear", "sharp", "constant")


def falloff_value(t, kind):
    t = np.clip(t, 0.0, 1.0)
    if kind == "linear":
        return 1.0 - t
    if kind == "sharp":
        return (1.0 - t) ** 2
    if kind == "constant":
        return np.ones_like(t)
    if kind == "smooth":
        return 1.0 - (3.0 * t ** 2 - 2.0 * t ** 3)
    raise SubdError("The falloff must be one of %s." % ", ".join(FALLOFFS))


def graph(cage: Cage):
    edges = cage.edge_list()
    if not edges:
        return None
    a = np.array([e[0] for e in edges])
    b = np.array([e[1] for e in edges])
    w = np.linalg.norm(cage.v[a] - cage.v[b], axis=1)
    w = np.maximum(w, 1e-12)
    n = len(cage.v)
    m = coo_matrix((np.concatenate([w, w]), (np.concatenate([a, b]), np.concatenate([b, a]))), shape=(n, n)).tocsr()
    return m


def selection_vertices(cage: Cage, vertices=None, edges=None, faces=None):
    out = set()
    nv = len(cage.v)
    for v in vertices or []:
        v = int(v)
        if not 0 <= v < nv:
            raise SubdError("Vertex %d does not exist." % v)
        out.add(v)
    for e in edges or []:
        a, b = int(e[0]), int(e[1])
        if not (0 <= a < nv and 0 <= b < nv):
            raise SubdError("Edge %d,%d does not exist." % (a, b))
        out.update((a, b))
    for f in faces or []:
        f = int(f)
        if not 0 <= f < len(cage.f):
            raise SubdError("Face %d does not exist." % f)
        out.update(cage.f[f])
    return out


def soft_weights(cage: Cage, selected, radius: float, kind: str = "smooth"):
    n = len(cage.v)
    w = np.zeros(n)
    sel = sorted(selected)
    if not sel:
        return w
    w[sel] = 1.0
    if not radius or radius <= 0:
        return w
    if kind not in FALLOFFS:
        raise SubdError("The falloff must be one of %s." % ", ".join(FALLOFFS))
    m = graph(cage)
    if m is None:
        return w
    d = dijkstra(m, directed=False, indices=sel, min_only=True, limit=radius * 1.0000001)
    near = np.isfinite(d)
    t = np.where(near, d / radius, 1.0)
    vals = falloff_value(t, kind)
    vals[~near] = 0.0
    vals[sel] = 1.0
    return vals


def pivot_of(cage, sel, pivot):
    if pivot is not None:
        return np.asarray(pivot, dtype=np.float64)
    return cage.v[sorted(sel)].mean(axis=0)


def apply_transform(cage: Cage, sel, weights, fn, use_symmetry, sym):
    old = cage.v
    idx = np.nonzero(weights > 0)[0]
    new = old.copy()
    moved_pos = fn(old[idx])
    new[idx] = old[idx] + (moved_pos - old[idx]) * weights[idx, None]
    pl = symmetry.perms(cage, sym) if use_symmetry and symmetry.active(sym) else []
    result = symmetry.project(old, new, set(int(i) for i in idx), pl)
    cage.v = result
    return int(len(idx))


def move(cage, sel, weights, delta, use_symmetry, sym):
    d = np.asarray(delta, dtype=np.float64)
    if d.shape != (3,) or not np.all(np.isfinite(d)):
        raise SubdError("The move needs three finite numbers.")
    return apply_transform(cage, sel, weights, lambda p: p + d, use_symmetry, sym)


def rot(cage, sel, weights, axis, angle_deg, pivot, use_symmetry, sym):
    pv = pivot_of(cage, sel, pivot)
    ang = math.radians(float(angle_deg))
    return apply_transform(cage, sel, weights, lambda p: rotate(p, axis, ang, pv), use_symmetry, sym)


def scale(cage, sel, weights, factor, pivot, use_symmetry, sym):
    pv = pivot_of(cage, sel, pivot)
    f = np.asarray(factor, dtype=np.float64)
    if f.ndim == 0:
        f = np.array([float(f)] * 3)
    if f.shape != (3,) or not np.all(np.isfinite(f)):
        raise SubdError("The scale factor needs one number or three.")
    return apply_transform(cage, sel, weights, lambda p: pv + (p - pv) * f, use_symmetry, sym)
