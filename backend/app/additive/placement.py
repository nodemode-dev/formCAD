import math

import numpy as np


class PlacementError(ValueError):
    pass


IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def rotation_of(values) -> np.ndarray:
    if values is None:
        return np.eye(3)
    try:
        r = np.asarray([float(x) for x in values], dtype=np.float64).reshape(3, 3)
    except (TypeError, ValueError):
        raise PlacementError("An orientation is nine numbers, a 3 by 3 rotation by rows.")
    if not np.isfinite(r).all() or np.abs(r @ r.T - np.eye(3)).max() > 1e-6 or abs(np.linalg.det(r) - 1.0) > 1e-6:
        raise PlacementError("An orientation must be a proper rotation.")
    return r


def rot_z(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def align_down(normal) -> np.ndarray:
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    target = np.array([0.0, 0.0, -1.0])
    v = np.cross(n, target)
    c = float(np.dot(n, target))
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    k = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    return np.eye(3) + k + k @ k * (1.0 / (1.0 + c))


def transform(v: np.ndarray, item: dict):
    ro = rotation_of(item.get("orient"))
    r = rot_z(float(item.get("rot_z", 0.0) or 0.0)) @ ro
    c0 = (v.min(axis=0) + v.max(axis=0)) / 2.0
    w = (v - c0) @ r.T
    lo, hi = w.min(axis=0), w.max(axis=0)
    shift = np.array([float(item.get("x", 0.0)) - (lo[0] + hi[0]) / 2.0, float(item.get("y", 0.0)) - (lo[1] + hi[1]) / 2.0, float(item.get("lift", 0.0)) - lo[2]])
    out = w + shift
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = shift - r @ c0
    return out, m


def footprint(v: np.ndarray, orient, rz: float = 0.0) -> np.ndarray:
    r = rot_z(rz) @ rotation_of(orient)
    c0 = (v.min(axis=0) + v.max(axis=0)) / 2.0
    w = (v - c0) @ r.T
    return w[:, :2]


def hull(points: np.ndarray) -> np.ndarray:
    from scipy.spatial import ConvexHull, QhullError

    pts = np.unique(np.round(points, 5), axis=0)
    if len(pts) < 3:
        return pts
    try:
        return pts[ConvexHull(pts).vertices]
    except QhullError:
        return pts[[int(np.argmin(pts[:, 0])), int(np.argmax(pts[:, 0]))]]
