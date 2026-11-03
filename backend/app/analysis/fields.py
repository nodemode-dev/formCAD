import math

import numpy as np

MEASURES = ("gaussian", "mean", "max", "min", "absolute", "rms")
STRIPE_STYLES = ("zebra", "isophote")


class FieldError(ValueError):
    pass


def unit_vector(v, name: str = "direction") -> np.ndarray:
    try:
        a = np.asarray([float(c) for c in v], dtype=np.float64)
    except (TypeError, ValueError):
        raise FieldError("The %s needs three numbers." % name)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise FieldError("The %s needs three finite numbers." % name)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise FieldError("The %s has no length." % name)
    return a / n


def perpendicular_basis(axis: np.ndarray) -> tuple:
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = ref - float(np.dot(ref, axis)) * axis
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(axis, e1)


def reflect(normals: np.ndarray, view: np.ndarray) -> np.ndarray:
    n = normals.astype(np.float64)
    nn = np.einsum("ij,ij->i", n, n)
    nn = np.where(nn < 1e-24, np.nan, nn)
    nv = n @ view
    return (2.0 * nv / nn)[:, None] * n - view[None, :]


def zebra(normals: np.ndarray, view, axis, band_deg: float) -> np.ndarray:
    v, a = unit_vector(view, "view direction"), unit_vector(axis, "stripe axis")
    if not 0.05 <= band_deg <= 180.0:
        raise FieldError("The stripe width is from 0.05 to 180 degrees.")
    r = reflect(normals, v)
    d = r - (r @ a)[:, None] * a[None, :]
    e1, e2 = perpendicular_basis(a)
    theta = np.degrees(np.arctan2(d @ e2, d @ e1))
    theta = np.where(np.linalg.norm(d, axis=1) < 1e-9 * np.maximum(np.linalg.norm(r, axis=1), 1e-30), np.nan, theta)
    return (theta / band_deg).astype(np.float32)


def isophote(normals: np.ndarray, light, band_deg: float) -> np.ndarray:
    d = unit_vector(light, "light direction")
    if not 0.05 <= band_deg <= 180.0:
        raise FieldError("The band width is from 0.05 to 180 degrees.")
    n = normals.astype(np.float64)
    ln = np.linalg.norm(n, axis=1)
    cos = np.clip((n @ d) / np.where(ln < 1e-12, np.nan, ln), -1.0, 1.0)
    return (np.degrees(np.arccos(cos)) / band_deg).astype(np.float32)


def draft(normals: np.ndarray, pull) -> np.ndarray:
    d = unit_vector(pull, "pull direction")
    n = normals.astype(np.float64)
    ln = np.linalg.norm(n, axis=1)
    s = np.clip((n @ d) / np.where(ln < 1e-12, np.nan, ln), -1.0, 1.0)
    return np.degrees(np.arcsin(s)).astype(np.float32)


def curvature(data: np.ndarray, measure: str, mm_per_unit: float) -> tuple:
    if measure not in MEASURES:
        raise FieldError("Choose a curvature measure: %s." % ", ".join(MEASURES))
    k_gauss, k_mean, k1, k2 = (data[:, 3 + i].astype(np.float64) for i in range(4))
    f = float(mm_per_unit)
    if measure == "gaussian":
        out, unit = k_gauss * f * f, "1/unit^2"
    elif measure == "mean":
        out, unit = k_mean * f, "1/unit"
    elif measure == "max":
        out, unit = k1 * f, "1/unit"
    elif measure == "min":
        out, unit = k2 * f, "1/unit"
    elif measure == "absolute":
        out, unit = (np.abs(k1) + np.abs(k2)) * f, "1/unit"
    else:
        out, unit = np.sqrt(k1 * k1 + k2 * k2) * f, "1/unit"
    return out.astype(np.float32), unit


def summary(values: np.ndarray) -> dict:
    v = values[np.isfinite(values)].astype(np.float64)
    if not len(v):
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "std": None}
    return {"count": int(len(v)), "min": float(v.min()), "max": float(v.max()), "mean": float(v.mean()), "median": float(np.median(v)), "std": float(v.std())}


def value_range(values: np.ndarray, ramp: dict, signed: bool) -> tuple:
    v = values[np.isfinite(values)]
    lo = ramp.get("min")
    hi = ramp.get("max")
    if ramp.get("kind") == "zones":
        return float(lo), float(hi)
    if lo is None or hi is None:
        if not len(v):
            return 0.0, 1.0
        vmin, vmax = float(v.min()), float(v.max())
        if ramp.get("symmetric") or (signed and ramp.get("center") is not None):
            c = float(ramp.get("center") or 0.0)
            span = max(abs(vmin - c), abs(vmax - c), 1e-12)
            auto = (c - span, c + span)
        else:
            auto = (vmin, vmax if vmax > vmin else vmin + 1.0)
        lo = auto[0] if lo is None else lo
        hi = auto[1] if hi is None else hi
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def zone_stops(ramp: dict) -> list:
    lo, hi = float(ramp["min"]), float(ramp["max"])
    cols = [c for _t, c in ramp["stops"]]
    if len(cols) != 3:
        return ramp["stops"]
    a, b = ramp.get("limits") or [-3.0, 3.0]
    ta = min(max((a - lo) / (hi - lo), 0.0), 1.0)
    tb = min(max((b - lo) / (hi - lo), 0.0), 1.0)
    return [[0.0, cols[0]], [ta, cols[0]], [ta, cols[1]], [tb, cols[1]], [tb, cols[2]], [1.0, cols[2]]]


def deviation_stats(dist: np.ndarray, good: float | None = None, bad: float | None = None) -> dict:
    out = summary(dist)
    v = dist[np.isfinite(dist)]
    if good is not None:
        out["within_good"] = int(np.count_nonzero(np.abs(v) <= good))
    if bad is not None:
        out["beyond_bad"] = int(np.count_nonzero(np.abs(v) > bad))
    return out


def finite_or_none(x):
    return None if x is None or not math.isfinite(x) else float(x)
