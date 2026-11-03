import math

import numpy as np

AXIS_NAMES = {"x": 0, "y": 1, "z": 2}
PLANE_NAMES = {"xy": (0, 1), "yx": (0, 1), "yz": (1, 2), "zy": (1, 2), "zx": (2, 0), "xz": (2, 0)}
IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


class FrameError(ValueError):
    pass


def vec(raw, name="vector") -> np.ndarray:
    try:
        v = np.asarray([float(c) for c in raw], dtype=np.float64)
    except (TypeError, ValueError):
        raise FrameError("The %s needs three numbers." % name)
    if v.shape != (3,) or not np.all(np.isfinite(v)):
        raise FrameError("The %s needs three finite numbers." % name)
    return v


def unit(raw, name="direction") -> np.ndarray:
    v = vec(raw, name)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise FrameError("The %s has no length." % name)
    return v / n


def frame_from(x, z) -> list:
    z = unit(z, "z axis")
    x = np.asarray(x, dtype=np.float64)
    x = x - float(np.dot(x, z)) * z
    n = float(np.linalg.norm(x))
    if n < 1e-9:
        ref = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        x = ref - float(np.dot(ref, z)) * z
        n = float(np.linalg.norm(x))
    x = x / n
    y = np.cross(z, x)
    return [x.tolist(), y.tolist(), z.tolist()]


def axis_index(raw) -> int:
    if isinstance(raw, str):
        w = raw.strip().lower()
        if w in AXIS_NAMES:
            return AXIS_NAMES[w]
        raise FrameError("The axis is x, y or z.")
    try:
        i = int(raw)
    except (TypeError, ValueError):
        raise FrameError("The axis is x, y or z.")
    if i not in (0, 1, 2):
        raise FrameError("The axis is x, y or z.")
    return i


def rotation_matrix(axis: np.ndarray, degrees: float) -> np.ndarray:
    a = unit(axis, "rotation axis")
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    k = np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])
    return np.eye(3) * c + s * k + (1.0 - c) * np.outer(a, a)


def scale_matrix(axes: list, factors) -> np.ndarray:
    f = np.asarray(axes, dtype=np.float64)
    return f.T @ np.diag(factors) @ f


class Affine:
    def __init__(self, matrix: np.ndarray, origin: np.ndarray, shift: np.ndarray, kind: str, axis=None, degrees: float = 0.0, factor: float = 1.0):
        self.m = matrix
        self.o = origin
        self.t = shift
        self.kind = kind
        self.axis = axis
        self.degrees = degrees
        self.factor = factor

    def point(self, p) -> list:
        q = np.asarray([float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0])
        r = self.m @ (q - self.o) + self.o + self.t
        return [float(r[0]), float(r[1]), float(r[2])]

    def vector(self, v) -> list:
        r = self.m @ np.asarray([float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0])
        return [float(r[0]), float(r[1]), float(r[2])]

    def translation(self) -> np.ndarray:
        return self.o - self.m @ self.o + self.t

    def rows12(self) -> list:
        t = self.translation()
        return [float(self.m[0][0]), float(self.m[0][1]), float(self.m[0][2]), float(t[0]), float(self.m[1][0]), float(self.m[1][1]), float(self.m[1][2]), float(t[1]), float(self.m[2][0]), float(self.m[2][1]), float(self.m[2][2]), float(t[2])]

    def about_z(self) -> bool:
        return abs(self.m[2][0]) < 1e-12 and abs(self.m[2][1]) < 1e-12 and abs(self.m[0][2]) < 1e-12 and abs(self.m[1][2]) < 1e-12

    def conformal_xy(self) -> bool:
        a = self.m[:2, :2]
        k = math.sqrt(abs(float(np.linalg.det(a))))
        return k > 1e-12 and float(np.linalg.det(a)) > 0 and np.allclose(a @ a.T, k * k * np.eye(2), atol=1e-9)


def build(op: dict, frame: list, origin: np.ndarray) -> Affine:
    if not isinstance(op, dict):
        raise FrameError("The operation needs a type: move, rotate or scale.")
    kind = str(op.get("type", op.get("op", ""))).lower()
    ident = np.eye(3)
    zero = np.zeros(3)
    if kind == "move":
        if op.get("vector") is not None:
            v = vec(op["vector"], "move vector")
        elif op.get("plane") is not None:
            pair = PLANE_NAMES.get(str(op["plane"]).lower())
            if pair is None:
                raise FrameError("The plane is xy, yz or zx.")
            v = np.zeros(3)
            for k, name in zip(pair, ("u", "v")):
                v += np.asarray(frame[k]) * float(op.get(name, 0.0))
        elif op.get("axis") is not None:
            i = axis_index(op["axis"])
            d = float(op.get("distance", 0.0))
            v = np.asarray(frame[i]) * d
        else:
            raise FrameError("Give a vector, an axis with a distance, or a plane with u and v.")
        if not np.all(np.isfinite(v)):
            raise FrameError("The move distance must be finite.")
        return Affine(ident, origin, v, "move")
    if kind == "rotate":
        axis = np.asarray(frame[axis_index(op["axis"])]) if not isinstance(op.get("axis"), (list, tuple)) else unit(op["axis"], "rotation axis")
        deg = float(op.get("degrees", 0.0))
        if not math.isfinite(deg):
            raise FrameError("The rotation angle must be finite.")
        pivot = vec(op["origin"], "rotation origin") if op.get("origin") is not None else origin
        return Affine(rotation_matrix(axis, deg), pivot, zero, "rotate", axis=axis, degrees=deg)
    if kind == "scale":
        pivot = vec(op["origin"], "scale origin") if op.get("origin") is not None else origin
        if op.get("factors") is not None:
            f = vec(op["factors"], "scale factors")
        else:
            k = float(op.get("factor", 1.0))
            f = np.ones(3)
            if op.get("axes") is not None:
                pair = PLANE_NAMES.get(str(op["axes"]).lower())
                if pair is None:
                    raise FrameError("The scale axes are xy, yz or zx.")
                f[list(pair)] = k
            elif op.get("axis") is not None:
                f[axis_index(op["axis"])] = k
            else:
                f[:] = k
        if np.any(f <= 0) or not np.all(np.isfinite(f)):
            raise FrameError("Scale factors must be positive numbers.")
        uniform = bool(np.allclose(f, f[0]))
        m = np.eye(3) * f[0] if uniform else scale_matrix(frame, f)
        return Affine(m, pivot, zero, "scale", factor=float(f[0]) if uniform else 0.0)
    raise FrameError("The operation is move, rotate or scale.")
