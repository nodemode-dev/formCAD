import math

import numpy as np

EYE = np.eye(3)


def skew(v) -> np.ndarray:
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def expm(w) -> np.ndarray:
    th = math.sqrt(float(w[0]) ** 2 + float(w[1]) ** 2 + float(w[2]) ** 2)
    if th < 1e-12:
        return EYE + skew(w)
    k = skew(np.asarray(w, dtype=float) / th)
    return EYE + math.sin(th) * k + (1.0 - math.cos(th)) * (k @ k)


def logm(r: np.ndarray) -> np.ndarray:
    c = max(-1.0, min(1.0, (float(np.trace(r)) - 1.0) / 2.0))
    th = math.acos(c)
    v = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    if th < 1e-9:
        return v / 2.0
    if math.pi - th < 1e-6:
        m = (r + EYE) / 2.0
        i = int(np.argmax(np.diag(m)))
        axis = m[:, i] / math.sqrt(max(m[i, i], 1e-30))
        axis = axis / np.linalg.norm(axis)
        if float(axis @ v) < 0.0:
            axis = -axis
        return axis * th
    return v * (th / (2.0 * math.sin(th)))


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-14:
        raise ValueError("A direction of zero length cannot be used.")
    return v / n


def perp(v) -> np.ndarray:
    v = unit(v)
    a = np.array([1.0, 0.0, 0.0]) if abs(v[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    return unit(np.cross(v, a))


def matrix(r: np.ndarray, t) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = t
    return m


def split(m) -> tuple:
    m = np.asarray(m, dtype=float).reshape(4, 4)
    return m[:3, :3].copy(), m[:3, 3].copy()


def orthonormal(r: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(r)
    q = u @ vt
    if np.linalg.det(q) < 0:
        u[:, -1] = -u[:, -1]
        q = u @ vt
    return q


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def signed_angle(a, b, k) -> float:
    k = unit(k)
    pa = a - (a @ k) * k
    pb = b - (b @ k) * k
    na, nb = float(np.linalg.norm(pa)), float(np.linalg.norm(pb))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    pa, pb = pa / na, pb / nb
    return math.atan2(float(k @ np.cross(pa, pb)), float(pa @ pb))
