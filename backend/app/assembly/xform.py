import math

import numpy as np

EPS = 1e-6
MAX_COORD = 1e12


class TransformError(ValueError):
    pass


def identity() -> np.ndarray:
    return np.eye(4)


def to_list(m) -> list:
    return [float(v) for v in np.asarray(m, dtype=float).reshape(16)]


def _orthonormalise(m: np.ndarray) -> np.ndarray:
    u, _s, vt = np.linalg.svd(m[:3, :3])
    r = u @ vt
    out = np.eye(4)
    out[:3, :3] = r
    out[:3, 3] = m[:3, 3]
    return out


def check(m: np.ndarray) -> np.ndarray:
    if m.shape != (4, 4) or not np.all(np.isfinite(m)):
        raise TransformError("A transform must be a finite 4 by 4 matrix.")
    if np.max(np.abs(m[:3, 3])) > MAX_COORD:
        raise TransformError("The translation is out of range.")
    if np.max(np.abs(m[3] - np.array([0.0, 0.0, 0.0, 1.0]))) > 1e-9:
        raise TransformError("The last row of a transform must be 0, 0, 0, 1.")
    r = m[:3, :3]
    if np.max(np.abs(r.T @ r - np.eye(3))) > EPS:
        raise TransformError("The rotation part is not orthonormal; a component may be moved and turned but not scaled or sheared.")
    if np.linalg.det(r) < 0:
        raise TransformError("The transform mirrors the component; a mirrored copy is a different part, not a placement.")
    return _orthonormalise(m)


def as_matrix(value) -> np.ndarray:
    if value is None:
        return identity()
    if isinstance(value, dict):
        return from_parts(value)
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        raise TransformError("A transform is 16 numbers (row by row) or a 4 by 4 list.")
    if arr.size != 16:
        raise TransformError("A transform is 16 numbers (row by row) or a 4 by 4 list.")
    return check(arr.reshape(4, 4))


def vec(v, name="vector") -> np.ndarray:
    try:
        a = np.asarray(v, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        raise TransformError("%s must be three numbers." % name)
    if a.size == 2:
        a = np.append(a, 0.0)
    if a.size != 3 or not np.all(np.isfinite(a)):
        raise TransformError("%s must be three numbers." % name)
    return a


def unit(v, name="direction") -> np.ndarray:
    a = vec(v, name)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise TransformError("%s must not be zero." % name)
    return a / n


def translation(v) -> np.ndarray:
    m = identity()
    m[:3, 3] = vec(v, "translation")
    return m


def rotation(axis, degrees: float, origin=(0.0, 0.0, 0.0)) -> np.ndarray:
    k = unit(axis, "axis")
    t = math.radians(float(degrees))
    c, s = math.cos(t), math.sin(t)
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    r = np.eye(3) * c + (1 - c) * np.outer(k, k) + s * kx
    o = vec(origin, "origin")
    m = identity()
    m[:3, :3] = r
    m[:3, 3] = o - r @ o
    return m


def from_parts(spec: dict) -> np.ndarray:
    if "matrix" in spec:
        return as_matrix(spec["matrix"])
    m = identity()
    if spec.get("frame"):
        f = spec["frame"]
        x = unit(f.get("x", (1, 0, 0)), "x direction")
        z = unit(f.get("z", np.cross(x, f.get("y", (0, 1, 0)))), "z direction")
        y = np.cross(z, x)
        y = y / max(np.linalg.norm(y), 1e-12)
        x = np.cross(y, z)
        m[:3, 0], m[:3, 1], m[:3, 2] = x, y, z
        m[:3, 3] = vec(f.get("origin", (0, 0, 0)), "origin")
        return check(m)
    rot = spec.get("rotate")
    if rot:
        rots = rot if isinstance(rot, list) else [rot]
        for r in rots:
            m = rotation(r.get("axis", (0, 0, 1)), r.get("degrees", 0.0), r.get("origin", (0, 0, 0))) @ m
    if spec.get("translate") is not None:
        m = translation(spec["translate"]) @ m
    return check(m)


def compose(*ms) -> np.ndarray:
    out = identity()
    for m in ms:
        out = out @ np.asarray(m, dtype=float)
    return out


def inverse(m) -> np.ndarray:
    m = np.asarray(m, dtype=float)
    out = identity()
    out[:3, :3] = m[:3, :3].T
    out[:3, 3] = -(m[:3, :3].T @ m[:3, 3])
    return out


def apply_points(m, pts) -> np.ndarray:
    a = np.asarray(pts, dtype=float).reshape(-1, 3)
    return a @ np.asarray(m, dtype=float)[:3, :3].T + np.asarray(m, dtype=float)[:3, 3]


def apply_vectors(m, vecs) -> np.ndarray:
    a = np.asarray(vecs, dtype=float).reshape(-1, 3)
    return a @ np.asarray(m, dtype=float)[:3, :3].T


def frame_of(m) -> dict:
    m = np.asarray(m, dtype=float)
    return {"origin": [float(v) for v in m[:3, 3]], "x": [float(v) for v in m[:3, 0]], "y": [float(v) for v in m[:3, 1]], "z": [float(v) for v in m[:3, 2]]}


def axis_angle(m) -> dict:
    r = np.asarray(m, dtype=float)[:3, :3]
    cos = max(-1.0, min(1.0, (np.trace(r) - 1.0) / 2.0))
    ang = math.acos(cos)
    if ang < 1e-9:
        return {"axis": [0.0, 0.0, 1.0], "degrees": 0.0}
    if abs(math.pi - ang) < 1e-6:
        w, v = np.linalg.eigh((r + r.T) / 2.0)
        k = v[:, int(np.argmax(w))]
    else:
        k = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]]) / (2.0 * math.sin(ang))
    k = k / max(np.linalg.norm(k), 1e-12)
    return {"axis": [float(v) for v in k], "degrees": math.degrees(ang)}


def aligning(z_from, z_to) -> np.ndarray:
    a = unit(z_from)
    b = unit(z_to)
    c = float(np.dot(a, b))
    if c > 1 - 1e-12:
        return identity()
    if c < -1 + 1e-12:
        side = np.cross(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0))
        return rotation(side, 180.0)
    axis = np.cross(a, b)
    return rotation(axis, math.degrees(math.acos(c)))


def placement(origin, z) -> np.ndarray:
    z = unit(z)
    helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(helper, z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    m = identity()
    m[:3, 0], m[:3, 1], m[:3, 2] = x, y, z
    m[:3, 3] = vec(origin, "origin")
    return m
