import math

import numpy as np

from app.additive import placement
from app.additive.jobs import AdditiveError

PRESETS = {
    "balanced": {"support_volume_mm3": 0.35, "support_area_mm2": 0.0, "height_mm": 0.15, "staircase": 0.15, "overhang_area_mm2": 0.2, "bed_contact_mm2": -0.1, "cog_height_mm": 0.05},
    "quality": {"support_volume_mm3": 0.2, "support_area_mm2": 0.0, "height_mm": 0.05, "staircase": 0.4, "overhang_area_mm2": 0.3, "bed_contact_mm2": -0.05, "cog_height_mm": 0.0},
    "speed": {"support_volume_mm3": 0.3, "support_area_mm2": 0.0, "height_mm": 0.5, "staircase": 0.0, "overhang_area_mm2": 0.1, "bed_contact_mm2": -0.1, "cog_height_mm": 0.0},
    "strength": {"support_volume_mm3": 0.15, "support_area_mm2": 0.0, "height_mm": 0.2, "staircase": 0.05, "overhang_area_mm2": 0.1, "bed_contact_mm2": -0.3, "cog_height_mm": 0.2},
    "metal": {"support_volume_mm3": 0.15, "support_area_mm2": 0.25, "height_mm": 0.15, "staircase": 0.05, "overhang_area_mm2": 0.4, "bed_contact_mm2": -0.1, "cog_height_mm": 0.0},
}
MAX_SAMPLE = 60_000
GRID = 96
TERMS = ("support_volume_mm3", "support_area_mm2", "height_mm", "staircase", "overhang_area_mm2", "bed_contact_mm2", "cog_height_mm")


def fibonacci(n: int) -> np.ndarray:
    i = np.arange(n) + 0.5
    phi = math.pi * (3.0 - math.sqrt(5.0))
    z = 1.0 - 2.0 * i / n
    r = np.sqrt(1.0 - z * z)
    return np.stack([r * np.cos(phi * i), r * np.sin(phi * i), z], axis=1)


def prepare(v: np.ndarray, t: np.ndarray):
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cr = np.cross(b - a, c - a)
    area = np.linalg.norm(cr, axis=1) / 2.0
    ok = area > 1e-12
    cr, area, a, b, c = cr[ok], area[ok], a[ok], b[ok], c[ok]
    n = cr / (2.0 * area)[:, None]
    cen = (a + b + c) / 3.0
    if len(area) > MAX_SAMPLE:
        rng = np.random.default_rng(20261103)
        p = area / area.sum()
        idx = rng.choice(len(area), MAX_SAMPLE, replace=False, p=p)
        scale = area.sum() / area[idx].sum()
        n, cen, area = n[idx], cen[idx], area[idx] * scale
    return n, cen, area


def candidates(n: np.ndarray, area: np.ndarray) -> list:
    out = []
    for axis, name in (((0, 0, 1), "Top face down"), ((0, 0, -1), "Bottom face down"), ((1, 0, 0), "Right face down"), ((-1, 0, 0), "Left face down"), ((0, 1, 0), "Back face down"), ((0, -1, 0), "Front face down")):
        out.append((np.array(axis, dtype=np.float64), name))
    key = np.rint(n * 20.0).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    sums = np.bincount(inv, weights=area)
    for k in np.argsort(-sums)[:12]:
        mean = (n[inv == k] * area[inv == k][:, None]).sum(axis=0)
        if np.linalg.norm(mean) > 1e-9:
            out.append((mean / np.linalg.norm(mean), "Large flat face down"))
    for k, d in enumerate(fibonacci(64)):
        out.append((d, "Sampled direction %d" % (k + 1)))
    keep = []
    for d, name in out:
        if all(float(np.dot(d, e)) < math.cos(math.radians(3.0)) for e, _ in keep):
            keep.append((d, name))
    return keep


def evaluate(n, cen, area, vz_range, R, theta_deg, layer_h):
    nn = n @ R.T
    cc = cen @ R.T
    nz = nn[:, 2]
    zmin, zmax = vz_range
    cz = cc[:, 2] - zmin
    s = math.sin(math.radians(theta_deg))
    down = nz < -s
    on_bed = (nz < -0.999) & (cz <= 0.05)
    sup = down & ~on_bed
    proj = area * np.abs(nz)
    support_area = float(proj[sup].sum())
    overhang = float(area[sup].sum())
    contact = float(area[on_bed].sum())
    height = float(zmax - zmin)
    vol = 0.0
    if sup.any():
        up = nz > 0.1
        xy = cc[:, :2]
        lo = xy.min(axis=0)
        span = max(float((xy.max(axis=0) - lo).max()), 1e-6)
        cell = span / GRID
        ij = np.minimum(((xy - lo) / cell).astype(np.int64), GRID - 1)
        cid = ij[:, 0] * GRID + ij[:, 1]
        big = (height + 1.0) * 2.0
        keys_up = cid[up] * big + cz[up]
        order = np.argsort(keys_up)
        ku = keys_up[order]
        zu = cz[up][order]
        cu = cid[up][order]
        q = cid[sup] * big + cz[sup] - 1e-6
        j = np.searchsorted(ku, q) - 1
        valid = j >= 0
        jj = np.where(valid, j, 0)
        same = valid & (cu[jj] == cid[sup])
        floor = np.where(same, zu[jj], 0.0)
        drop = np.maximum(cz[sup] - floor, 0.0)
        vol = float((proj[sup] * drop).sum())
    flat = np.abs(nz) < 0.99
    stair = float((area[flat] * np.abs(nz[flat])).sum() * layer_h)
    cog = float((area * cz).sum() / area.sum())
    return {"support_volume_mm3": vol, "support_area_mm2": support_area, "height_mm": height, "staircase": stair, "overhang_area_mm2": overhang, "bed_contact_mm2": contact, "cog_height_mm": cog}


def study(v: np.ndarray, t: np.ndarray, preset: str, theta: float, top: int, layer_h: float, activity) -> dict:
    if preset not in PRESETS:
        raise AdditiveError("A preset is one of: %s." % ", ".join(PRESETS))
    if not len(t):
        raise AdditiveError("The body has no triangles.")
    n, cen, area = prepare(v, t)
    if not len(area):
        raise AdditiveError("The body has no area.")
    cands = candidates(n, area)
    rows = []
    for k, (d, name) in enumerate(cands):
        activity.check()
        R = placement.align_down(d)
        vz = v @ R.T[:, 2]
        terms = evaluate(n, cen, area, (float(vz.min()), float(vz.max())), R, theta, layer_h)
        rows.append({"rotation": [float(x) for x in R.reshape(-1)], "label": name, "terms": terms})
        activity.step("orient", (k + 1) / len(cands))
    weights = PRESETS[preset]
    norm = {k: max((r["terms"][k] for r in rows), default=0.0) for k in TERMS}
    for r in rows:
        score = 0.0
        for k in TERMS:
            w = weights[k]
            if w == 0.0 or norm[k] <= 1e-12:
                continue
            score += w * r["terms"][k] / norm[k]
        r["score"] = score
        r["terms"] = {k: round(x, 4) for k, x in r["terms"].items()}
    rows.sort(key=lambda r: r["score"])
    for i, r in enumerate(rows[:top]):
        r["rank"] = i + 1
        r["score"] = round(r["score"], 5)
    return {"candidates": rows[:top], "evaluated": len(rows), "preset": preset, "weights": weights}
