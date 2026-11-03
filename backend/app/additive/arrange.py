import math

import numpy as np
from scipy.signal import fftconvolve

from app.additive import placement
from app.additive import regions as rg
from app.additive.jobs import AdditiveError

MARGIN = 5.0
DEFAULT_ROTATIONS = (0.0, 90.0, 180.0, 270.0)


def inflated_hull(v: np.ndarray, orient, rz: float, grow: float) -> np.ndarray:
    pts = placement.footprint(v, orient, rz)
    h = placement.hull(pts)
    if len(h) < 3:
        raise AdditiveError("A body has no footprint to place.")
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    centre = (lo + hi) / 2.0
    paths = rg.offset([rg.ints(h)], grow) if grow > 0 else [rg.ints(h)]
    if not paths:
        raise AdditiveError("A body has no footprint to place.")
    poly = rg.floats(max(paths, key=lambda p: abs(rg.pc.Area(p))))
    return poly, centre


def raster(poly: np.ndarray, res: float):
    lo = poly.min(axis=0)
    hi = poly.max(axis=0)
    w = int(math.ceil((hi[0] - lo[0]) / res)) + 1
    h = int(math.ceil((hi[1] - lo[1]) / res)) + 1
    xs = lo[0] + (np.arange(w) + 0.5) * res
    ys = lo[1] + (np.arange(h) + 0.5) * res
    gx, gy = np.meshgrid(xs, ys)
    inside = np.ones(gx.shape, dtype=bool)
    sign = 1.0 if rg.pc.Area(rg.ints(poly)) > 0 else -1.0
    for a, b in zip(poly, np.roll(poly, -1, axis=0)):
        cross = (b[0] - a[0]) * (gy - a[1]) - (b[1] - a[1]) * (gx - a[0])
        inside &= cross * sign >= -1e-9
    return inside, lo


def arrange(parts: list, items: list, bed, spacing: float, rotations=None, activity=None) -> tuple:
    rots = list(rotations) if rotations else list(DEFAULT_ROTATIONS)
    res = 0.5 if max(bed) <= 450 else 1.0
    W = int(round(bed[0] / res))
    H = int(round(bed[1] / res))
    occ = np.zeros((H, W), dtype=np.float32)
    mar = int(round(MARGIN / res))
    occ[:mar, :] = 1.0
    occ[-mar:, :] = 1.0
    occ[:, :mar] = 1.0
    occ[:, -mar:] = 1.0
    grow = spacing / 2.0 + res * 0.5
    order = sorted(range(len(items)), key=lambda i: -float(np.ptp(parts[i].v[:, 0]) * np.ptp(parts[i].v[:, 1])))
    out = [dict(it) for it in items]
    placed, unplaced = 0, []
    used = 0.0
    for n, i in enumerate(order):
        if activity is not None:
            activity.step("arrange", (n + 1) / max(1, len(order)))
        best = None
        for rz in rots:
            poly, centre = inflated_hull(parts[i].v, items[i].get("orient"), rz, grow)
            mask, lo = raster(poly, res)
            h, w = mask.shape
            if h > H or w > W:
                continue
            over = fftconvolve(occ, mask[::-1, ::-1].astype(np.float32), mode="valid")
            free = np.argwhere(over < 0.5)
            if not len(free):
                continue
            y, x = free[0]
            top = (y + h) * res
            key = (round(top, 3), x)
            if best is None or key < best[0]:
                best = (key, rz, int(y), int(x), mask, lo, centre)
        if best is None:
            unplaced.append(items[i]["body"])
            continue
        _k, rz, y, x, mask, lo, centre = best
        h, w = mask.shape
        occ[y:y + h, x:x + w] = np.maximum(occ[y:y + h, x:x + w], mask.astype(np.float32))
        origin = np.array([x * res, y * res])
        out[i]["rot_z"] = float(rz)
        out[i]["x"] = float(origin[0] + (centre[0] - lo[0]))
        out[i]["y"] = float(origin[1] + (centre[1] - lo[1]))
        pts = placement.footprint(parts[i].v, items[i].get("orient"), rz)
        hh = placement.hull(pts)
        a = 0.5 * abs(float(np.dot(hh[:, 0], np.roll(hh[:, 1], -1)) - np.dot(hh[:, 1], np.roll(hh[:, 0], -1)))) if len(hh) >= 3 else 0.0
        used += a
        placed += 1
    return out, {"placed": placed, "unplaced": unplaced, "utilisation": round(used / (bed[0] * bed[1]), 4)}
