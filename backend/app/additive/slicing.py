import numpy as np

from app.additive import regions as rg

PLANE_EPS = 1.37e-6
MAX_PAIRS = 40_000_000
AGENT_PAIRS = 8_000_000


class SliceError(Exception):
    pass


def weld(v: np.ndarray, t: np.ndarray):
    key = np.rint(v * 1e5).astype(np.int64)
    uniq, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    nv = v[first]
    nt = inv[t]
    ok = (nt[:, 0] != nt[:, 1]) & (nt[:, 1] != nt[:, 2]) & (nt[:, 0] != nt[:, 2])
    return nv, nt[ok].astype(np.int64)


def layer_stack(height: float, first: float, h: float) -> list:
    if height <= 0:
        raise SliceError("The model has no height.")
    rest = max(0.0, height - first)
    n = 1 + int(round(rest / h))
    tops, heights = [], []
    z = 0.0
    for i in range(n):
        lh = first if i == 0 else h
        z += lh
        tops.append(z)
        heights.append(lh)
    return list(zip(tops, heights))


def signed_volume(v: np.ndarray, t: np.ndarray) -> float:
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def slice_planes(v: np.ndarray, t: np.ndarray, planes: np.ndarray, activity, pair_cap: int, stats: dict) -> list:
    nv = len(v)
    tz = v[t][:, :, 2]
    zmin, zmax = tz.min(axis=1), tz.max(axis=1)
    i0 = np.searchsorted(planes, zmin, side="left")
    i1 = np.searchsorted(planes, zmax, side="right") - 1
    counts = np.maximum(i1 - i0 + 1, 0)
    total = int(counts.sum())
    if total > pair_cap:
        raise SliceError("The model needs %d triangle and layer pairs; the limit is %d. Use thicker layers or a coarser mesh." % (total, pair_cap))
    tri = np.repeat(np.arange(len(t)), counts)
    base = np.cumsum(counts) - counts
    layer = np.repeat(i0, counts) + (np.arange(total) - np.repeat(base, counts))
    per_layer = [[] for _ in planes]
    order = np.argsort(layer, kind="stable")
    tri, layer = tri[order], layer[order]
    edges = np.searchsorted(layer, np.arange(len(planes) + 1), side="left")
    out = []
    for li in range(len(planes)):
        activity.check()
        sel = tri[edges[li]:edges[li + 1]]
        out.append(_layer_loops(v, t, sel, float(planes[li]), nv, stats, li))
        if li % 8 == 0:
            activity.step("slice", 0.02 + 0.2 * li / max(1, len(planes)))
    return out


def _layer_loops(v, t, sel, z, nv, stats, li):
    if not len(sel):
        return []
    tv = t[sel]
    p = v[tv]
    above = p[:, :, 2] > z
    na = above.sum(axis=1)
    keep = (na == 1) | (na == 2)
    if not keep.any():
        return []
    tv, p, above, na = tv[keep], p[keep], above[keep], na[keep]
    lone_is_above = na == 1
    idx = np.arange(len(tv))
    lone = np.where(lone_is_above, np.argmax(above, axis=1), np.argmax(~above, axis=1))
    nxt = (lone + 1) % 3
    prv = (lone + 2) % 3
    ia, ib, ic = tv[idx, lone], tv[idx, nxt], tv[idx, prv]

    def cross_pt(i, j):
        lo = np.minimum(i, j)
        hi = np.maximum(i, j)
        a, b = v[lo], v[hi]
        dz = b[:, 2] - a[:, 2]
        dz = np.where(np.abs(dz) < 1e-15, 1e-15, dz)
        s = (z - a[:, 2]) / dz
        xy = a[:, :2] + s[:, None] * (b[:, :2] - a[:, :2])
        return xy, lo.astype(np.int64) * nv + hi.astype(np.int64)

    pa, ka = cross_pt(ia, ib)
    pb, kb = cross_pt(ia, ic)
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    d = pb - pa
    dot = d[:, 0] * (-n[:, 1]) + d[:, 1] * n[:, 0]
    flip = dot < 0
    sx = np.where(flip[:, None], pb, pa)
    ex = np.where(flip[:, None], pa, pb)
    sk = np.where(flip, kb, ka)
    ek = np.where(flip, ka, kb)
    good = (np.abs(n[:, 0]) + np.abs(n[:, 1]) > 1e-18) & (sk != ek)
    sx, ex, sk, ek = sx[good], ex[good], sk[good], ek[good]
    m = len(sk)
    if m < 3:
        return []
    order = np.argsort(sk, kind="stable")
    sks = sk[order]
    pos = np.searchsorted(sks, ek)
    pos = np.minimum(pos, m - 1)
    found = sks[pos] == ek
    nxt_seg = np.where(found, order[pos], -1)
    visited = np.zeros(m, dtype=bool)
    loops = []
    nl = nxt_seg.tolist()
    for s0 in range(m):
        if visited[s0]:
            continue
        chain = []
        cur = s0
        closed = False
        while cur != -1 and not visited[cur]:
            visited[cur] = True
            chain.append(cur)
            cur = nl[cur]
            if cur == s0:
                closed = True
                break
        if len(chain) < 3:
            continue
        pts = sx[chain]
        if not closed:
            gap = np.hypot(*(ex[chain[-1]] - sx[chain[0]]))
            if gap > 0.5:
                stats["open"] = stats.get("open", 0) + 1
                stats.setdefault("open_layers", []).append(li)
                continue
            stats["closed_gap"] = stats.get("closed_gap", 0) + 1
        loops.append(rg.ints(pts))
    return loops


def to_regions(loops_per_layer: list, simplify: float = 0.002) -> list:
    out = []
    for loops in loops_per_layer:
        if not loops:
            out.append([])
            continue
        r = rg.union(rg.clean(loops, simplify))
        out.append(rg.clean(r, simplify))
    return out
