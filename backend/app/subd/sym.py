import math

import numpy as np
from scipy.spatial import cKDTree

from app.subd.cc import SubdError

MAX_GROUP = 64
AXES = "xyz"


def default_sym() -> dict:
    return {"mirror": [], "radial": None, "tol": 1e-6}


def clean(sym) -> dict:
    out = default_sym()
    if not isinstance(sym, dict):
        return out
    seen = set()
    for m in sym.get("mirror") or []:
        ax = str(m.get("axis", "")).lower()
        if ax in AXES and ax not in seen:
            seen.add(ax)
            out["mirror"].append({"axis": ax, "at": float(m.get("at", 0.0))})
    rad = sym.get("radial")
    if isinstance(rad, dict) and str(rad.get("axis", "")).lower() in AXES:
        n = int(rad.get("count", 0))
        if n < 2 or n > MAX_GROUP:
            raise SubdError("The radial count must be 2 to %d." % MAX_GROUP)
        c = rad.get("center") or [0.0, 0.0]
        out["radial"] = {"axis": str(rad["axis"]).lower(), "count": n, "center": [float(c[0]), float(c[1])]}
    tol = float(sym.get("tol", 1e-6))
    out["tol"] = tol if tol > 0 else 1e-6
    size = (2 ** len(out["mirror"])) * (out["radial"]["count"] if out["radial"] else 1)
    if size > MAX_GROUP:
        raise SubdError("The symmetry has %d copies; the limit is %d." % (size, MAX_GROUP))
    return out


def active(sym) -> bool:
    return bool(sym) and (bool(sym.get("mirror")) or bool(sym.get("radial")))


def elements(sym):
    sym = clean(sym)
    mats = []
    mir = []
    for m in sym["mirror"]:
        a = AXES.index(m["axis"])
        M = np.eye(4)
        M[a, a] = -1.0
        M[a, 3] = 2.0 * m["at"]
        mir.append(M)
    rots = [np.eye(4)]
    rad = sym["radial"]
    if rad:
        a = AXES.index(rad["axis"])
        i1, i2 = [i for i in range(3) if i != a]
        c = rad["center"]
        for k in range(1, rad["count"]):
            t = 2 * math.pi * k / rad["count"]
            R = np.eye(4)
            R[i1, i1], R[i1, i2] = math.cos(t), -math.sin(t)
            R[i2, i1], R[i2, i2] = math.sin(t), math.cos(t)
            off = np.zeros(3)
            off[i1], off[i2] = c[0], c[1]
            R[:3, 3] = off - R[:3, :3] @ off
            rots.append(R)
    subsets = [np.eye(4)]
    for M in mir:
        subsets = subsets + [M @ S for S in subsets]
    for S in subsets:
        for R in rots:
            G = R @ S
            if not np.allclose(G, np.eye(4)):
                mats.append(G)
    return mats


def apply(G, pts):
    pts = np.asarray(pts, dtype=np.float64)
    return pts @ G[:3, :3].T + G[:3, 3]


def perms(cage, sym):
    mats = elements(sym)
    if not mats:
        return []
    tol = clean(sym)["tol"]
    scale = max(1.0, float(np.abs(cage.v).max())) if len(cage.v) else 1.0
    tree = cKDTree(cage.v)
    out = []
    for G in mats:
        d, idx = tree.query(apply(G, cage.v))
        idx = np.where(d <= tol * scale, idx, -1)
        out.append((G, idx))
    return out


def image_set(perm_list, verts):
    out = set(verts)
    for _, idx in perm_list:
        for v in verts:
            w = int(idx[v])
            if w >= 0:
                out.add(w)
    return out


def image_faces(cage, perm_list, faces):
    keyed = {frozenset(f): i for i, f in enumerate(cage.f)}
    out = set(faces)
    for _, idx in perm_list:
        for fi in faces:
            mapped = [int(idx[v]) for v in cage.f[fi]]
            if min(mapped) >= 0 and frozenset(mapped) in keyed:
                out.add(keyed[frozenset(mapped)])
    return out


def image_edges(perm_list, edges):
    out = set((min(a, b), max(a, b)) for a, b in edges)
    for _, idx in perm_list:
        for a, b in edges:
            wa, wb = int(idx[a]), int(idx[b])
            if wa >= 0 and wb >= 0 and wa != wb:
                out.add((min(wa, wb), max(wa, wb)))
    return out


def project(old, new, moved, perm_list):
    if not perm_list:
        return new
    new = new.copy()
    affected = set(moved)
    for G, idx in perm_list:
        for v in list(moved):
            w = int(idx[v])
            if w >= 0 and w not in moved:
                new[w] = apply(G, new[v][None])[0]
                affected.add(w)
    group = [(np.eye(4), np.arange(len(old)))] + perm_list
    inv = []
    for G, idx in group:
        R = np.linalg.inv(G)
        inv.append((R, idx))
    result = new.copy()
    for v in affected:
        acc = np.zeros(3)
        cnt = 0
        for R, idx in inv:
            w = int(idx[v])
            if w < 0:
                continue
            acc += apply(R, new[w][None])[0]
            cnt += 1
        if cnt:
            result[v] = acc / cnt
    return result


def check(cage, sym) -> float:
    if not len(cage.v):
        return 0.0
    tree = cKDTree(cage.v)
    worst = 0.0
    for G in elements(sym):
        d, _ = tree.query(apply(G, cage.v))
        worst = max(worst, float(d.max()))
    return worst
