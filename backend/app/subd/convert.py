import math
import os
import tempfile

import numpy as np

from app.subd import limit
from app.subd.cage import Cage
from app.subd.cc import INF, SubdError, refine

MAX_PATCHES = 20000
MAX_PATCHES_AGENT = 5000
MEASURE_LIMIT = 6000
MAX_TOTAL_LEVELS = 5


def level_plan(cage: Cage, levels: int):
    levels = int(levels)
    if levels < 1 or levels > 4:
        raise SubdError("The conversion level must be 1 to 4.")
    finite = [w for w in cage.crease.values() if w < INF]
    need = int(math.ceil(max(finite))) if finite else 0
    total = min(max(levels, need), MAX_TOTAL_LEVELS)
    leftover = max(0.0, max(finite) - total) if finite else 0.0
    return total, need, leftover


def patch_count(cage: Cage, total: int) -> int:
    corners = sum(len(f) for f in cage.f)
    return corners * 4 ** (total - 1)


def bern(t, n):
    return np.stack([math.comb(n, i) * t ** i * (1 - t) ** (n - i) for i in range(n + 1)], axis=-1)


def samples(ctrl, u, v):
    du = 3.0 * (ctrl[:, 1:, :, :] - ctrl[:, :-1, :, :])
    dv = 3.0 * (ctrl[:, :, 1:, :] - ctrl[:, :, :-1, :])
    pos = np.einsum("ni,fijk,nj->fnk", bern(u, 3), ctrl, bern(v, 3))
    su = np.einsum("ni,fijk,nj->fnk", bern(u, 2), du, bern(v, 3))
    sv = np.einsum("ni,fijk,nj->fnk", bern(u, 3), dv, bern(v, 2))
    n = np.cross(su, sv)
    return pos, n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-300)


def patch_bbox(ctrl):
    g = np.linspace(0.0, 1.0, 9)
    U, V = np.meshgrid(g, g, indexing="ij")
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for start in range(0, len(ctrl), 4096):
        pos, _ = samples(ctrl[start:start + 4096], U.ravel(), V.ravel())
        lo = np.minimum(lo, pos.reshape(-1, 3).min(axis=0))
        hi = np.maximum(hi, pos.reshape(-1, 3).max(axis=0))
    return [float(x) for x in (*lo, *hi)]


def continuity(lv, ctrl, regular, sharp):
    quads = lv.quads()
    nf = len(quads)
    nv = len(lv.v)
    t = np.array([0.25, 0.5, 0.75])
    zero, one = np.zeros(3), np.ones(3)
    sides = [(t, zero), (one, t), (1.0 - t, one), (zero, 1.0 - t)]
    pos = np.zeros((nf, 4, 3, 3))
    nrm = np.zeros((nf, 4, 3, 3))
    for c, (uu, vv) in enumerate(sides):
        pos[:, c], nrm[:, c] = samples(ctrl, uu, vv)
    a = quads
    b = np.roll(quads, -1, axis=1)
    key = (a * nv + b).ravel()
    rkey = (b * nv + a).ravel()
    order = np.argsort(key)
    sk = key[order]
    at = np.clip(np.searchsorted(sk, rkey), 0, len(sk) - 1)
    match = sk[at] == rkey
    other = order[at]
    flat_pos = pos.reshape(-1, 3, 3)
    flat_nrm = nrm.reshape(-1, 3, 3)
    idx = np.nonzero(match)[0]
    jdx = other[idx]
    keep = idx < jdx
    idx, jdx = idx[keep], jdx[keep]
    gap = float(np.abs(flat_pos[idx] - flat_pos[jdx][:, ::-1]).max()) if len(idx) else 0.0
    cosv = (flat_nrm[idx] * flat_nrm[jdx][:, ::-1]).sum(axis=2)
    ang = np.degrees(np.arccos(np.clip(cosv, -1.0, 1.0))).max(axis=1) if len(idx) else np.zeros(0)
    lo = np.minimum(a, b).ravel()
    hi = np.maximum(a, b).ravel()
    sharp_keys = np.array(sorted(x * nv + y for x, y in sharp), dtype=np.int64)
    creased = np.isin(lo[idx] * nv + hi[idx], sharp_keys) if len(sharp_keys) else np.zeros(len(idx), dtype=bool)
    smooth = ~creased
    reg_flat = np.repeat(regular, 4)
    both_reg = reg_flat[idx] & reg_flat[jdx]
    a_s = ang[smooth]
    reg_ang = ang[smooth & both_reg]
    irr_ang = ang[smooth & ~both_reg]
    return {
        "max_gap": gap, "edges_checked": int(smooth.sum()), "sharp_edges_skipped": int(creased.sum()),
        "max_normal_angle_deg": float(a_s.max()) if len(a_s) else 0.0, "regular_edges_angle_deg": float(reg_ang.max()) if len(reg_ang) else 0.0,
        "extraordinary_edges_angle_deg": float(irr_ang.max()) if len(irr_ang) else 0.0, "edges_over_half_degree": int((a_s > 0.5).sum()),
    }


def point_triangle_distance(p, a, b, c):
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = p - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = p - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = 1.0 / (va + vb + vc)
        v = vb * denom
        w = vc * denom
    q = a + ab * v[..., None] + ac * w[..., None]
    q = np.where(((d1 <= 0) & (d2 <= 0))[..., None], a, q)
    q = np.where(((d3 >= 0) & (d4 <= d3))[..., None], b, q)
    q = np.where(((d6 >= 0) & (d5 <= d6))[..., None], c, q)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_ab = d1 / (d1 - d3)
        t_ac = d2 / (d2 - d6)
        t_bc = (d4 - d3) / ((d4 - d3) + (d5 - d6))
    on_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    on_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    on_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    q = np.where(on_ab[..., None], a + ab * t_ab[..., None], q)
    q = np.where(on_ac[..., None], a + ac * t_ac[..., None], q)
    q = np.where(on_bc[..., None], b + (c - b) * t_bc[..., None], q)
    return np.linalg.norm(p - q, axis=-1)


def deviation(cage: Cage, ctrl, total):
    from scipy.spatial import cKDTree

    corners = sum(len(f) for f in cage.f)
    ref_levels = total + 1
    while ref_levels < min(total + 3, 6) and corners * 4 ** (ref_levels) <= 250000:
        ref_levels += 1
    chain = refine(cage.v, cage.f, cage.crease, ref_levels)
    ref = chain[-1]
    quads = ref.quads()
    tris = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
    A, B, C = ref.v[tris[:, 0]], ref.v[tris[:, 1]], ref.v[tris[:, 2]]
    tree = cKDTree((A + B + C) / 3.0)
    g = np.linspace(0.0, 1.0, 5)
    U, V = np.meshgrid(g, g, indexing="ij")
    pts = limit.bezier_points(ctrl[:, None, None], U[None], V[None]).reshape(-1, 3)
    _, nearest = tree.query(pts, k=8)
    best = np.full(len(pts), np.inf)
    for j in range(nearest.shape[1]):
        t = nearest[:, j]
        best = np.minimum(best, point_triangle_distance(pts, A[t], B[t], C[t]))
    return float(best.max()), float(np.sqrt((best ** 2).mean())), ref_levels


class Quiet:
    def step(self, phase, progress=None):
        return None


def build(cage: Cage, levels: int, agent: bool = False, measure: bool = True, act=None) -> dict:
    act = act or Quiet()
    act.step("checking the cage", 0.02)
    cage.validate(agent)
    an = cage.analysis()
    if not an["manifold"]:
        raise SubdError("The cage is not a manifold surface: %d non-manifold edges and %d edges with mismatched direction." % (an["nonmanifold_edges"], an["inconsistent_edges"]))
    total, need, leftover = level_plan(cage, levels)
    cap = MAX_PATCHES_AGENT if agent else MAX_PATCHES
    n = patch_count(cage, total)
    if n > cap:
        raise SubdError("The conversion would make %d patches; the limit is %d%s. Lower the level or simplify the cage." % (n, cap, " for macros and agents" if agent else ""))
    act.step("subdividing", 0.05)
    chain = refine(cage.v, cage.f, cage.crease, total)
    lv = chain[-1]
    act.step("building patches", 0.1)
    ctrl, regular, topo, kinds = limit.build_patches(lv)
    act.step("checking the joins", 0.3)
    notes = []
    if not an["closed"]:
        notes.append("The cage has %d open boundary edges; the result is a shell, not a solid." % an["boundary_edges"])
    if leftover > 0:
        notes.append("A crease weight above %d needs more than %d levels; the remaining sharpness is treated as fully sharp." % (total, MAX_TOTAL_LEVELS))
    irregular = int((~regular).sum())
    report = {
        "levels": total, "requested_levels": int(levels), "patches": int(len(ctrl)), "regular_patches": int(regular.sum()), "irregular_patches": irregular,
        "cage_extraordinary": an["extraordinary_count"], "cage_closed": an["closed"], "notes": notes,
    }
    report.update(continuity(lv, ctrl, regular, topo.sharp))
    measure = bool(measure) and len(ctrl) <= MEASURE_LIMIT
    if not measure:
        report["deviation_note"] = "Not measured above %d patches." % MEASURE_LIMIT
    if measure:
        act.step("measuring the deviation", 0.4)
        mx, rms, ref_levels = deviation(cage, ctrl, total)
        diag = float(np.linalg.norm(np.array(cage.bbox()[3:]) - np.array(cage.bbox()[:3])))
        report["deviation_max"] = mx
        report["deviation_rms"] = rms
        report["deviation_relative_to_diagonal"] = mx / diag if diag > 0 else 0.0
        report["deviation_note"] = "Largest distance from 25 sample points per patch to the triangles of the level %d subdivided mesh." % ref_levels
    report["continuity_note"] = "Patches are exact bicubic B-spline pieces where the cage is regular (smooth, position and curvature continuous). At extraordinary vertices and next to creases they are matched-boundary bicubic patches: the shared edges coincide, the tangent planes agree only at the vertex itself, so the surface is positionally continuous (G0) across the edges around those vertices and the largest normal jump is reported above."
    return {"ctrl": ctrl, "regular": regular, "report": report, "level": lv, "bbox": patch_bbox(ctrl)}


def write_patches(ctrl: np.ndarray) -> str:
    folder = tempfile.mkdtemp(prefix="fcsubd_")
    path = os.path.join(folder, "patches.bez")
    with open(path, "wb") as fh:
        fh.write(np.ascontiguousarray(ctrl, dtype="<f8").tobytes())
    return path
