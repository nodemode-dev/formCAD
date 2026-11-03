import math

import numpy as np

MAX_PAIRS = 60_000_000
MAX_FILL_EDGES = 400


class MeshError(Exception):
    pass


class Mesh:
    __slots__ = ("v", "t")

    def __init__(self, v, t):
        self.v = np.ascontiguousarray(np.asarray(v, dtype=np.float64).reshape(-1, 3))
        self.t = np.ascontiguousarray(np.asarray(t, dtype=np.int32).reshape(-1, 3))
        if len(self.t) and (self.t.min() < 0 or self.t.max() >= len(self.v)):
            raise MeshError("A triangle refers to a vertex that does not exist.")
        if len(self.v) and not np.isfinite(self.v).all():
            raise MeshError("The mesh holds coordinates that are not finite.")

    def copy(self):
        return Mesh(self.v.copy(), self.t.copy())

    def bbox(self):
        if not len(self.v):
            return [0.0] * 6
        lo, hi = self.v.min(axis=0), self.v.max(axis=0)
        return [float(x) for x in (*lo, *hi)]


def compact(m: Mesh) -> Mesh:
    if not len(m.t):
        return Mesh(m.v[:0], m.t)
    used = np.unique(m.t)
    remap = np.full(len(m.v), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return Mesh(m.v[used], remap[m.t])


def edge_keys(t):
    a = np.concatenate([t[:, 0], t[:, 1], t[:, 2]]).astype(np.int64)
    b = np.concatenate([t[:, 1], t[:, 2], t[:, 0]]).astype(np.int64)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    n = int(max(a.max(), b.max())) + 1 if len(a) else 1
    return a, b, lo * n + hi


def edge_classes(m: Mesh) -> dict:
    if not len(m.t):
        return {"naked": np.zeros((0, 2), dtype=np.int64), "nonmanifold": 0, "edges": 0}
    a, b, key = edge_keys(m.t)
    uniq, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    single = counts[inverse] == 1
    naked = np.stack([a[single], b[single]], axis=1)
    return {"naked": naked, "nonmanifold": int((counts > 2).sum()), "edges": int(len(uniq))}


def naked_loops(naked) -> tuple:
    nxt = {}
    for a, b in naked.tolist():
        nxt.setdefault(a, []).append(b)
    used = set()
    loops, chains = [], []
    for a0, b0 in naked.tolist():
        if (a0, b0) in used:
            continue
        seq = [a0, b0]
        used.add((a0, b0))
        closed = False
        while True:
            cur = seq[-1]
            options = [x for x in nxt.get(cur, []) if (cur, x) not in used]
            if not options:
                break
            x = options[0]
            used.add((cur, x))
            if x == seq[0]:
                closed = True
                break
            seq.append(x)
            if len(seq) > len(naked) + 2:
                break
        (loops if closed else chains).append(seq)
    return loops, chains


def components(m: Mesh):
    n = len(m.t)
    if not n:
        return np.zeros(0, dtype=np.int64), 0
    a, b, key = edge_keys(m.t)
    face = np.concatenate([np.arange(n)] * 3)
    order = np.argsort(key, kind="stable")
    k, f = key[order], face[order]
    same = k[1:] == k[:-1]
    i, j = f[:-1][same], f[1:][same]
    label = np.arange(n)
    for _ in range(64):
        low = np.minimum(label[i], label[j])
        before = label.copy()
        np.minimum.at(label, i, low)
        np.minimum.at(label, j, low)
        label = label[label]
        if (label == before).all():
            break
    uniq, comp = np.unique(label, return_inverse=True)
    return comp, len(uniq)


def areas(m: Mesh):
    if not len(m.t):
        return np.zeros(0)
    p = m.v[m.t]
    return 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)


def signed_volume(m: Mesh, mask=None) -> float:
    if not len(m.t):
        return 0.0
    p = m.v[m.t if mask is None else m.t[mask]]
    return float(np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])).sum() / 6.0)


def triangle_normals(m: Mesh):
    p = m.v[m.t]
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    return n / ln[:, None]


def vertex_normals(m: Mesh):
    p = m.v[m.t]
    fn = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    out = np.zeros_like(m.v)
    for k in range(3):
        np.add.at(out, m.t[:, k], fn)
    ln = np.linalg.norm(out, axis=1)
    ln[ln == 0] = 1.0
    return out / ln[:, None]


def report(m: Mesh) -> dict:
    cls = edge_classes(m)
    loops, chains = naked_loops(cls["naked"]) if len(cls["naked"]) else ([], [])
    comp, ncomp = components(m)
    ar = areas(m)
    conflicts = orientation_conflicts(m)
    closed = len(cls["naked"]) == 0 and cls["nonmanifold"] == 0 and len(m.t) > 0
    used = np.zeros(len(m.v), dtype=bool)
    used[m.t.ravel()] = True
    return {
        "vertices": int(len(m.v)), "triangles": int(len(m.t)), "components": int(ncomp), "edges": cls["edges"],
        "naked_edges": int(len(cls["naked"])), "nonmanifold_edges": cls["nonmanifold"], "naked_loops": len(loops), "open_chains": len(chains),
        "degenerate_triangles": int((ar <= 1e-18).sum()), "unused_vertices": int((~used).sum()), "inconsistent_edges": conflicts,
        "closed": bool(closed), "area": float(ar.sum()), "volume": signed_volume(m) if closed else None, "bbox": m.bbox(),
    }


def union_pairs(v, tol):
    cells = np.floor(v / tol).astype(np.int64)
    c = cells - cells.min(axis=0) + 1
    d1, d2 = int(c[:, 1].max()) + 3, int(c[:, 2].max()) + 3
    key = (c[:, 0] * d1 + c[:, 1]) * d2 + c[:, 2]
    order = np.argsort(key, kind="stable")
    sk = key[order]
    uniq, start, cnt = np.unique(sk, return_index=True, return_counts=True)
    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) >= (0, 0, 0)]
    pi, pj = [], []
    total = 0
    for dx, dy, dz in offsets:
        shift = (dx * d1 + dy) * d2 + dz
        target = uniq + shift
        pos = np.searchsorted(uniq, target)
        pos[pos >= len(uniq)] = len(uniq) - 1
        hit = uniq[pos] == target
        ia = np.nonzero(hit)[0]
        ib = pos[hit]
        for ca, cb in ((ia, ib),):
            na, nb = cnt[ca], cnt[cb]
            pairs = na * nb
            total += int(pairs.sum())
            if total > MAX_PAIRS:
                raise MeshError("The weld tolerance is too large for this mesh: too many vertices share a cell.")
            rep_a = np.repeat(np.arange(len(ca)), pairs)
            within = np.arange(int(pairs.sum())) - np.repeat(np.cumsum(pairs) - pairs, pairs)
            ra = within // np.repeat(nb, pairs)
            rb = within % np.repeat(nb, pairs)
            i = order[start[ca][rep_a] + ra]
            j = order[start[cb][rep_a] + rb]
            if (dx, dy, dz) == (0, 0, 0):
                keep = i < j
                i, j = i[keep], j[keep]
            pi.append(i)
            pj.append(j)
    i = np.concatenate(pi) if pi else np.zeros(0, dtype=np.int64)
    j = np.concatenate(pj) if pj else np.zeros(0, dtype=np.int64)
    close = np.linalg.norm(v[i] - v[j], axis=1) <= tol
    return i[close], j[close]


def weld(m: Mesh, tol: float) -> tuple:
    if not (tol > 0 and math.isfinite(tol)):
        raise MeshError("The weld tolerance must be positive.")
    n = len(m.v)
    if not n:
        return m, {"merged": 0, "removed_triangles": 0}
    i, j = union_pairs(m.v, tol)
    label = np.arange(n)
    for _ in range(200):
        before = label.copy()
        low = np.minimum(label[i], label[j])
        np.minimum.at(label, i, low)
        np.minimum.at(label, j, low)
        label = label[label]
        if (label == before).all():
            break
    t = label[m.t]
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    out = compact(Mesh(m.v, t[keep]))
    return out, {"merged": int(n - len(np.unique(label))), "removed_triangles": int((~keep).sum()), "vertices": int(len(out.v))}


def orientation_relations(t):
    n = len(t)
    a, b, key = edge_keys(t)
    face = np.concatenate([np.arange(n)] * 3)
    order = np.argsort(key, kind="stable")
    k, f, da, db = key[order], face[order], a[order], b[order]
    same = np.nonzero(k[1:] == k[:-1])[0]
    count = np.diff(np.concatenate([[0], np.nonzero(np.diff(k))[0] + 1, [len(k)]]))
    run_start = np.repeat(np.concatenate([[0], np.nonzero(np.diff(k))[0] + 1]), count)
    run_len = np.repeat(count, count)
    pair = same[(run_len[same] == 2) & (run_len[same + 1] == 2)] if len(same) else same
    i, j = f[pair], f[pair + 1]
    rel = ((da[pair] == da[pair + 1]) & (db[pair] == db[pair + 1])).astype(np.int8)
    return i, j, rel


def orientation_conflicts(m: Mesh) -> int:
    if not len(m.t):
        return 0
    i, j, rel = orientation_relations(m.t)
    return int(rel.sum()) if len(i) else 0


def bfs_parity(n, i, j, rel):
    src = np.concatenate([i, j])
    dst = np.concatenate([j, i])
    rr = np.concatenate([rel, rel])
    order = np.argsort(src, kind="stable")
    src, dst, rr = src[order], dst[order], rr[order]
    ptr = np.searchsorted(src, np.arange(n + 1))
    parity = np.full(n, -1, dtype=np.int8)
    comp = np.full(n, -1, dtype=np.int64)
    cid = 0
    for root in range(n):
        if parity[root] >= 0:
            continue
        parity[root] = 0
        comp[root] = cid
        frontier = np.array([root])
        while len(frontier):
            starts, ends = ptr[frontier], ptr[frontier + 1]
            cnt = ends - starts
            if cnt.sum() == 0:
                break
            idx = np.repeat(starts, cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
            from_f = np.repeat(frontier, cnt)
            nb = dst[idx]
            want = parity[from_f] ^ rr[idx]
            fresh = parity[nb] < 0
            nb_f, want_f = nb[fresh], want[fresh]
            _, first = np.unique(nb_f, return_index=True)
            nb_u, want_u = nb_f[first], want_f[first]
            parity[nb_u] = want_u
            comp[nb_u] = cid
            frontier = nb_u
        cid += 1
    return parity, comp


def unify(m: Mesh) -> tuple:
    n = len(m.t)
    if not n:
        return m, {"flipped": 0, "components": 0, "reversed_components": 0, "conflicts": 0}
    i, j, rel = orientation_relations(m.t)
    parity, comp = bfs_parity(n, i, j, rel)
    t = m.t.copy()
    flip = parity == 1
    t[flip] = t[flip][:, [0, 2, 1]]
    out = Mesh(m.v, t)
    cls = edge_classes(out)
    naked_faces = np.zeros(n, dtype=bool)
    if len(cls["naked"]):
        a, b, key = edge_keys(out.t)
        uniq, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
        single = (counts[inverse] == 1)
        naked_faces[np.concatenate([np.arange(n)] * 3)[single]] = True
    reversed_components = 0
    for c in np.unique(comp):
        sel = comp == c
        if naked_faces[sel].any():
            continue
        if signed_volume(out, sel) < 0:
            tt = out.t.copy()
            tt[sel] = tt[sel][:, [0, 2, 1]]
            out = Mesh(out.v, tt)
            reversed_components += 1
    bad = int((((parity[i] ^ parity[j]) != rel)).sum())
    return out, {"flipped": int(flip.sum()), "components": int(comp.max()) + 1, "reversed_components": reversed_components, "conflicts": bad}


def tri_normal(p, q, r):
    n = np.cross(q - p, r - p)
    ln = np.linalg.norm(n)
    return n / ln if ln > 0 else n


def dihedral(n1, n2):
    return math.acos(max(-1.0, min(1.0, float(np.dot(n1, n2)))))


def triangulate_loop(pts, side_normals):
    n = len(pts)
    if n < 3:
        raise MeshError("A hole needs at least three edges.")
    if n == 3:
        return [(0, 1, 2)]
    worst = np.full((n, n), np.inf)
    area = np.zeros((n, n))
    shape = np.zeros((n, n))
    pick = np.zeros((n, n), dtype=np.int64)
    for i in range(n - 1):
        worst[i, i + 1] = 0.0
    nrm = {}

    def tri_info(i, k, j):
        p, q, r = pts[i], pts[k], pts[j]
        cr = np.cross(q - p, r - p)
        return 0.5 * np.linalg.norm(cr), tri_normal(p, q, r)

    for span in range(2, n):
        for i in range(0, n - span):
            j = i + span
            best = (np.inf, np.inf, np.inf)
            bk = -1
            best_total = best_shape = 0.0
            for k in range(i + 1, j):
                if not (np.isfinite(worst[i, k]) and np.isfinite(worst[k, j])):
                    continue
                a, nn = tri_info(i, k, j)
                w = max(worst[i, k], worst[k, j])
                if k - i == 1:
                    sn = side_normals.get((i, k))
                    if sn is not None:
                        w = max(w, dihedral(nn, sn))
                elif (i, k) in nrm:
                    w = max(w, dihedral(nn, nrm[(i, k)]))
                if j - k == 1:
                    sn = side_normals.get((k, j))
                    if sn is not None:
                        w = max(w, dihedral(nn, sn))
                elif (k, j) in nrm:
                    w = max(w, dihedral(nn, nrm[(k, j)]))
                if i == 0 and j == n - 1:
                    sn = side_normals.get((j, i))
                    if sn is not None:
                        w = max(w, dihedral(nn, sn))
                total = area[i, k] + area[k, j] + a
                per = np.linalg.norm(pts[k] - pts[i]) + np.linalg.norm(pts[j] - pts[k]) + np.linalg.norm(pts[j] - pts[i])
                shape_cost = shape[i, k] + shape[k, j] + (per * per / a if a > 0 else 1e18)
                cand = (round(w, 5), float("%.9g" % total), shape_cost)
                if cand < best:
                    best, bk = cand, k
                    best_total, best_shape = total, shape_cost
            worst[i, j], area[i, j], pick[i, j] = best[0], best_total if bk >= 0 else 0.0, bk
            shape[i, j] = best_shape if bk >= 0 else 0.0
            if bk >= 0:
                nrm[(i, j)] = tri_info(i, bk, j)[1]
    out = []
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        k = int(pick[i, j])
        if k < 0:
            raise MeshError("A hole could not be triangulated.")
        out.append((i, k, j))
        stack.append((i, k))
        stack.append((k, j))
    return out


def fill_holes(m: Mesh, max_edges: int = 32, max_size: float = 0.0) -> tuple:
    max_edges = max(3, min(int(max_edges), MAX_FILL_EDGES))
    cls = edge_classes(m)
    loops, chains = naked_loops(cls["naked"]) if len(cls["naked"]) else ([], [])
    owner = {}
    p = m.v[m.t]
    for fi in range(len(m.t)):
        a, b, c = m.t[fi]
        owner[(int(a), int(b))] = fi
        owner[(int(b), int(c))] = fi
        owner[(int(c), int(a))] = fi
    fn = triangle_normals(m)
    new_t = []
    filled, skipped = 0, []
    for lp in loops:
        n = len(lp)
        if len(set(lp)) != n:
            skipped.append({"edges": n, "reason": "the boundary touches itself"})
            continue
        if n > max_edges:
            skipped.append({"edges": n, "reason": "more than %d edges" % max_edges})
            continue
        pts = m.v[lp]
        size = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        if max_size > 0 and size > max_size:
            skipped.append({"edges": n, "reason": "larger than %g" % max_size})
            continue
        rev = lp[::-1]
        pr = m.v[rev]
        side = {}
        for k in range(n):
            a, b = rev[k], rev[(k + 1) % n]
            f = owner.get((b, a))
            if f is not None:
                side[(k, (k + 1) % n) if k + 1 < n else (n - 1, 0)] = fn[f]
        try:
            tris = triangulate_loop(pr, side)
        except MeshError as err:
            skipped.append({"edges": n, "reason": str(err)})
            continue
        for i, k, j in tris:
            new_t.append((rev[i], rev[k], rev[j]))
        filled += 1
    if not new_t:
        return m, {"filled": 0, "triangles_added": 0, "skipped": skipped, "open_chains": len(chains)}
    out = Mesh(m.v, np.vstack([m.t, np.array(new_t, dtype=np.int32)]))
    return out, {"filled": filled, "triangles_added": len(new_t), "skipped": skipped, "open_chains": len(chains)}


def flip_all(m: Mesh) -> Mesh:
    return Mesh(m.v, m.t[:, [0, 2, 1]])


def remove_degenerate(m: Mesh) -> tuple:
    ar = areas(m)
    keep = ar > 1e-18
    out = compact(Mesh(m.v, m.t[keep]))
    return out, {"removed": int((~keep).sum())}
