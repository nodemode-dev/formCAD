import numpy as np

from app.meshes import core
from app.meshes.core import Mesh, MeshError
from app.meshes.jobs import QUIET, SELFX_MAX_PAIRS

MAX_CANDIDATES = 40_000_000
MAX_BIG = 3000
CHUNK = 400_000


def diagonal(m: Mesh) -> float:
    if not len(m.v):
        return 0.0
    return float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0)))


def remove_tiny(m: Mesh, rel: float = 1e-5) -> tuple:
    if not len(m.t):
        return m, {"removed": 0}
    ar = core.areas(m)
    floor = max(1e-18, rel * float(np.median(ar)))
    keep = ar > floor
    if keep.all():
        return m, {"removed": 0}
    return core.compact(Mesh(m.v, m.t[keep])), {"removed": int((~keep).sum())}


def remove_duplicates(m: Mesh) -> tuple:
    if not len(m.t):
        return m, {"removed": 0}
    key = np.sort(m.t.astype(np.int64), axis=1)
    _u, first = np.unique(key, axis=0, return_index=True)
    if len(first) == len(m.t):
        return m, {"removed": 0}
    keep = np.zeros(len(m.t), dtype=bool)
    keep[first] = True
    return core.compact(Mesh(m.v, m.t[keep])), {"removed": int((~keep).sum())}


def grid_pairs(lo, hi, act):
    n = len(lo)
    ext = (hi - lo).max(axis=1)
    h = float(max(2.0 * np.median(ext), 1e-9))
    ilo = np.floor(lo / h).astype(np.int64)
    ihi = np.floor(hi / h).astype(np.int64)
    span = ihi - ilo
    small = (span <= 1).all(axis=1)
    base = ilo.min(axis=0)
    dims = (ihi.max(axis=0) - base + 3).astype(np.int64)
    entries_k, entries_t = [], []
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                ok = small & (span[:, 0] >= dx) & (span[:, 1] >= dy) & (span[:, 2] >= dz)
                idx = np.nonzero(ok)[0]
                c = ilo[idx] - base + np.array([dx, dy, dz]) + 1
                entries_k.append((c[:, 0] * dims[1] + c[:, 1]) * dims[2] + c[:, 2])
                entries_t.append(idx)
    keys = np.concatenate(entries_k)
    tris = np.concatenate(entries_t)
    order = np.argsort(keys, kind="stable")
    keys, tris = keys[order], tris[order]
    _u, start, cnt = np.unique(keys, return_index=True, return_counts=True)
    multi = cnt > 1
    start, cnt = start[multi], cnt[multi]
    total = int((cnt * (cnt - 1) // 2).sum())
    if total > MAX_CANDIDATES:
        raise MeshError("The triangles are too uneven in size for a self-intersection check (%d candidate pairs)." % total)
    pi, pj = [], []
    for g in np.unique(cnt):
        sel = start[cnt == g]
        a_idx, b_idx = np.triu_indices(int(g), 1)
        rows = sel[:, None] + a_idx[None, :]
        cols = sel[:, None] + b_idx[None, :]
        pi.append(tris[rows].ravel())
        pj.append(tris[cols].ravel())
        act.check()
    i = np.concatenate(pi) if pi else np.zeros(0, dtype=np.int64)
    j = np.concatenate(pj) if pj else np.zeros(0, dtype=np.int64)
    big = np.nonzero(~small)[0]
    if len(big) > MAX_BIG:
        raise MeshError("%d triangles are much larger than the rest; the self-intersection check cannot grid them." % len(big))
    bi, bj = [], []
    for b in big:
        hit = np.nonzero((lo <= hi[b]).all(axis=1) & (hi >= lo[b]).all(axis=1))[0]
        hit = hit[hit != b]
        bi.append(np.full(len(hit), b, dtype=np.int64))
        bj.append(hit)
    if bi:
        i = np.concatenate([i] + bi)
        j = np.concatenate([j] + bj)
    lo_i = np.minimum(i, j).astype(np.int64)
    hi_i = np.maximum(i, j).astype(np.int64)
    code = np.unique(lo_i * n + hi_i)
    return code // n, code % n


def segment_hits(p, q, a, b, c, tol):
    n = np.cross(b - a, c - a)
    sp = np.einsum("ij,ij->i", p - a, n)
    sq = np.einsum("ij,ij->i", q - a, n)
    nn = np.linalg.norm(n, axis=1) * tol
    opposite = ((sp > nn) & (sq < -nn)) | ((sp < -nn) & (sq > nn))
    d = q - p
    pa, pb, pc = a - p, b - p, c - p
    w1 = np.einsum("ij,ij->i", np.cross(pa, pb), d)
    w2 = np.einsum("ij,ij->i", np.cross(pb, pc), d)
    w3 = np.einsum("ij,ij->i", np.cross(pc, pa), d)
    inside = ((w1 > 0) & (w2 > 0) & (w3 > 0)) | ((w1 < 0) & (w2 < 0) & (w3 < 0))
    hit = opposite & inside
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(hit, sp / (sp - sq), 0.0)
    return hit, p + d * t[:, None]


def self_intersections(m: Mesh, max_pairs: int = 1000, act=QUIET) -> dict:
    max_pairs = max(1, min(int(max_pairs), SELFX_MAX_PAIRS))
    n = len(m.t)
    empty = {"pairs": 0, "triangles_involved": 0, "sample": [], "points": [], "capped": False, "pair_array": np.zeros((0, 2), dtype=np.int64)}
    if n < 2:
        return empty
    act.step("Finding candidate triangle pairs", 0.1)
    p = m.v[m.t]
    lo, hi = p.min(axis=1), p.max(axis=1)
    diag = max(diagonal(m), 1e-12)
    pad = diag * 1e-9
    lo, hi = lo - pad, hi + pad
    i, j = grid_pairs(lo, hi, act)
    ov = (lo[i] <= hi[j]).all(axis=1) & (lo[j] <= hi[i]).all(axis=1)
    i, j = i[ov], j[ov]
    ti, tj = m.t[i], m.t[j]
    share = (ti[:, :, None] == tj[:, None, :]).any(axis=(1, 2))
    i, j = i[~share], j[~share]
    act.step("Testing %d triangle pairs" % len(i), 0.3)
    found_i, found_j, found_pt = [], [], []
    tol = 1e-9
    for s in range(0, len(i), CHUNK):
        ci, cj = i[s : s + CHUNK], j[s : s + CHUNK]
        A, B = p[ci], p[cj]
        hit = np.zeros(len(ci), dtype=bool)
        where = np.zeros((len(ci), 3))
        for e in range(3):
            h, pt = segment_hits(A[:, e], A[:, (e + 1) % 3], B[:, 0], B[:, 1], B[:, 2], tol)
            new = h & ~hit
            where[new] = pt[new]
            hit |= h
        for e in range(3):
            h, pt = segment_hits(B[:, e], B[:, (e + 1) % 3], A[:, 0], A[:, 1], A[:, 2], tol)
            new = h & ~hit
            where[new] = pt[new]
            hit |= h
        found_i.append(ci[hit])
        found_j.append(cj[hit])
        found_pt.append(where[hit])
        act.step("Testing %d triangle pairs" % len(i), 0.3 + 0.7 * min(1.0, (s + CHUNK) / max(1, len(i))))
    fi = np.concatenate(found_i) if found_i else np.zeros(0, dtype=np.int64)
    fj = np.concatenate(found_j) if found_j else np.zeros(0, dtype=np.int64)
    fp = np.concatenate(found_pt) if found_pt else np.zeros((0, 3))
    pairs = np.stack([fi, fj], axis=1)
    involved = int(len(np.unique(pairs))) if len(pairs) else 0
    capped = len(pairs) > max_pairs
    return {"pairs": int(len(pairs)), "triangles_involved": involved, "sample": pairs[:20].tolist(), "points": fp[:max_pairs].tolist(), "capped": bool(capped), "pair_array": pairs}


def remove_intersecting(m: Mesh, fill_edges: int, act=QUIET, rounds: int = 2) -> tuple:
    removed = 0
    filled = 0
    cur = m
    for _ in range(rounds):
        res = self_intersections(cur, SELFX_MAX_PAIRS, act)
        if not res["pairs"]:
            break
        bad = np.unique(res["pair_array"])
        keep = np.ones(len(cur.t), dtype=bool)
        keep[bad] = False
        removed += int(len(bad))
        cur = core.compact(Mesh(cur.v, cur.t[keep]))
        cur, info = core.fill_holes(cur, max(3, fill_edges), 0.0)
        filled += info["filled"]
    return cur, {"triangles_removed": removed, "holes_filled": filled}


def summary_counts(m: Mesh) -> dict:
    r = core.report(m)
    return {k: r[k] for k in ("triangles", "vertices", "naked_edges", "naked_loops", "open_chains", "nonmanifold_edges", "degenerate_triangles", "inconsistent_edges", "components", "closed")}


def repair(m: Mesh, weld=0.0, degenerate=True, duplicates=True, unify=True, fill_edges=32, self_check=True, resolve=False, act=QUIET) -> tuple:
    steps = []
    before = summary_counts(m)
    cur = m
    act.step("Welding vertices", 0.05)
    if weld and weld > 0:
        cur, info = core.weld(cur, weld)
        steps.append({"step": "weld", **info})
    if degenerate:
        act.step("Removing degenerate triangles", 0.2)
        cur, info = remove_tiny(cur)
        steps.append({"step": "degenerate", **info})
    if duplicates:
        act.step("Removing duplicate triangles", 0.3)
        cur, info = remove_duplicates(cur)
        steps.append({"step": "duplicates", **info})
    if unify:
        act.step("Unifying normals", 0.45)
        cur, info = core.unify(cur)
        steps.append({"step": "unify", **info})
    if fill_edges and fill_edges >= 3:
        act.step("Filling holes", 0.6)
        cur, info = core.fill_holes(cur, int(fill_edges), 0.0)
        steps.append({"step": "fill", "filled": info["filled"], "triangles_added": info["triangles_added"], "skipped": info["skipped"], "open_chains": info["open_chains"]})
        if info["filled"] and unify:
            cur, info2 = core.unify(cur)
            if info2["flipped"]:
                steps.append({"step": "unify_after_fill", **info2})
    sx = None
    if resolve:
        act.step("Removing self-intersecting triangles", 0.75)
        cur, info = remove_intersecting(cur, int(fill_edges or 32), act)
        steps.append({"step": "resolve_intersections", **info})
        if info["triangles_removed"] and unify:
            cur, _ = core.unify(cur)
    if self_check:
        act.step("Checking self-intersections", 0.85)
        res = self_intersections(cur, 1000, act)
        sx = {"pairs": res["pairs"], "triangles_involved": res["triangles_involved"], "sample": res["sample"], "capped": res["capped"]}
    after = summary_counts(cur)
    return cur, {"before": before, "after": after, "steps": steps, "self_intersections": sx}
