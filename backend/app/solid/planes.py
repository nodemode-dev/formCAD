import math

WORLD = {
    "top": ("Top", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "bottom": ("Bottom", (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    "front": ("Front", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ("Back", (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ("Right", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ("Left", (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
}
COLLINEAR = 1e-9
PARALLEL = 0.95


class PlaneError(ValueError):
    pass


def vec(value, name: str = "point") -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise PlaneError("The %s needs three numbers." % name)
    try:
        out = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        raise PlaneError("The %s needs three numbers." % name)
    if not all(math.isfinite(v) for v in out):
        raise PlaneError("The %s needs finite numbers." % name)
    return out


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a) -> float:
    return math.sqrt(dot(a, a))


def unit(a):
    n = length(a)
    if n == 0.0:
        raise PlaneError("A direction has no length.")
    return (a[0] / n, a[1] / n, a[2] / n)


def make(name: str, origin, x, y, z) -> dict:
    return {"name": name, "origin": list(origin), "x": list(x), "y": list(y), "z": list(z)}


def world(plane_id: str, origin=(0.0, 0.0, 0.0)) -> dict:
    row = WORLD.get(str(plane_id).lower())
    if row is None:
        raise PlaneError("Choose one of: %s." % ", ".join(WORLD))
    label, x, y = row
    return make(label, origin, x, y, cross(x, y))


def through_points(a, b, c) -> dict:
    ab, ac = sub(b, a), sub(c, a)
    n = cross(ab, ac)
    if length(n) < COLLINEAR * max(1.0, length(ab) * length(ac)):
        raise PlaneError("The three points are on one line.")
    x, z = unit(ab), unit(n)
    return make("Three points", a, x, cross(z, x), z)


def on_face(point, normal) -> dict:
    z = unit(normal)
    ref = (1.0, 0.0, 0.0)
    if abs(dot(ref, z)) > PARALLEL:
        ref = (0.0, 1.0, 0.0)
    d = dot(ref, z)
    x = unit((ref[0] - d * z[0], ref[1] - d * z[1], ref[2] - d * z[2]))
    return make("Face", point, x, cross(z, x), z)


def frame(data) -> dict:
    if not isinstance(data, dict):
        raise PlaneError("The plane needs origin, x, y and z.")
    o, x, y, z = (vec(data.get(k), k) for k in ("origin", "x", "y", "z"))
    return make(str(data.get("name", "Plane")), o, unit(x), unit(y), unit(z))


def to_local(plane: dict, w):
    r = sub(w, plane["origin"])
    return (dot(r, plane["x"]), dot(r, plane["y"]), dot(r, plane["z"]))


def from_local(plane: dict, u: float, v: float):
    o, x, y = plane["origin"], plane["x"], plane["y"]
    return (o[0] + x[0] * u + y[0] * v, o[1] + x[1] * u + y[1] * v, o[2] + x[2] * u + y[2] * v)


def nice_step(visible: float) -> float:
    raw = max(visible, 1e-9) / 12.0
    return 10.0 ** math.floor(math.log10(raw))


def grid_lines(plane: dict, target, visible: float, radius: float) -> dict:
    u, v, _ = to_local(plane, target)
    off = math.hypot(u, v)
    extent = max(visible * 3.0, radius * 2.0, off * 2.0, 1.0)
    return {"step": nice_step(visible), "extent": extent, "center": [u, v], "major": 10}


def quantise(plane: dict, point, step: float):
    if not (math.isfinite(step) and step > 0.0):
        raise PlaneError("The grid step must be a positive number.")
    u, v, _ = to_local(plane, point)
    return from_local(plane, math.floor(u / step + 0.5) * step, math.floor(v / step + 0.5) * step)
