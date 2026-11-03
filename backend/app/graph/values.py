import math
from dataclasses import dataclass
from typing import Optional

EPS = 1e-12


class ValueError3(ValueError):
    pass


def _f(v) -> float:
    return float(v)


@dataclass(frozen=True, slots=True)
class Vector3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, o):
        return Vector3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o):
        return Vector3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __neg__(self):
        return Vector3(-self.x, -self.y, -self.z)

    def __mul__(self, k):
        return Vector3(self.x * k, self.y * k, self.z * k)

    __rmul__ = __mul__

    def __truediv__(self, k):
        return Vector3(self.x / k, self.y / k, self.z / k)

    def dot(self, o) -> float:
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o):
        return Vector3(self.y * o.z - self.z * o.y, self.z * o.x - self.x * o.z, self.x * o.y - self.y * o.x)

    @property
    def length(self) -> float:
        return math.sqrt(self.dot(self))

    def unit(self):
        n = self.length
        if n < EPS:
            raise ValueError3("a zero vector has no direction")
        return Vector3(self.x / n, self.y / n, self.z / n)

    def angle(self, o) -> float:
        a, b = self.length, o.length
        if a < EPS or b < EPS:
            raise ValueError3("a zero vector has no angle")
        return math.acos(max(-1.0, min(1.0, self.dot(o) / (a * b))))

    def to_point(self):
        return Point3(self.x, self.y, self.z)

    def to_list(self) -> list:
        return [self.x, self.y, self.z]


@dataclass(frozen=True, slots=True)
class Point3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, v):
        return Point3(self.x + v.x, self.y + v.y, self.z + v.z)

    def __sub__(self, o):
        if isinstance(o, Point3):
            return Vector3(self.x - o.x, self.y - o.y, self.z - o.z)
        return Point3(self.x - o.x, self.y - o.y, self.z - o.z)

    def distance(self, o) -> float:
        return math.sqrt((self.x - o.x) ** 2 + (self.y - o.y) ** 2 + (self.z - o.z) ** 2)

    def to_vector(self):
        return Vector3(self.x, self.y, self.z)

    def to_list(self) -> list:
        return [self.x, self.y, self.z]


@dataclass(frozen=True, slots=True)
class Domain:
    t0: float = 0.0
    t1: float = 1.0

    @property
    def length(self) -> float:
        return self.t1 - self.t0

    @property
    def mid(self) -> float:
        return 0.5 * (self.t0 + self.t1)

    @property
    def lo(self) -> float:
        return min(self.t0, self.t1)

    @property
    def hi(self) -> float:
        return max(self.t0, self.t1)

    def contains(self, t: float, tol: float = 0.0) -> bool:
        return self.lo - tol <= t <= self.hi + tol

    def at(self, u: float) -> float:
        return self.t0 + u * (self.t1 - self.t0)

    def normalise(self, t: float) -> float:
        if abs(self.length) < EPS:
            raise ValueError3("a zero length domain cannot normalise")
        return (t - self.t0) / self.length

    def remap(self, t: float, other):
        return other.at(self.normalise(t))

    def to_list(self) -> list:
        return [self.t0, self.t1]


@dataclass(frozen=True, slots=True)
class Colour:
    r: int = 0
    g: int = 0
    b: int = 0
    a: int = 255

    def __post_init__(self):
        for name in ("r", "g", "b", "a"):
            v = int(round(getattr(self, name)))
            object.__setattr__(self, name, max(0, min(255, v)))

    def hex(self) -> str:
        if self.a == 255:
            return "#%02x%02x%02x" % (self.r, self.g, self.b)
        return "#%02x%02x%02x%02x" % (self.r, self.g, self.b, self.a)

    @staticmethod
    def from_hex(text: str):
        s = str(text).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) not in (6, 8):
            raise ValueError3("a colour is #rgb, #rrggbb or #rrggbbaa")
        try:
            vals = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
        except ValueError:
            raise ValueError3("a colour is #rgb, #rrggbb or #rrggbbaa")
        return Colour(*vals)

    @staticmethod
    def from_hsv(h: float, s: float, v: float, a: int = 255):
        import colorsys

        r, g, b = colorsys.hsv_to_rgb((h % 1.0), max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
        return Colour(round(r * 255), round(g * 255), round(b * 255), a)

    def to_hsv(self) -> tuple:
        import colorsys

        return colorsys.rgb_to_hsv(self.r / 255.0, self.g / 255.0, self.b / 255.0)

    def to_list(self) -> list:
        return [self.r, self.g, self.b, self.a]


@dataclass(frozen=True, slots=True)
class PlaneF:
    origin: Point3 = Point3()
    x: Vector3 = Vector3(1.0, 0.0, 0.0)
    y: Vector3 = Vector3(0.0, 1.0, 0.0)
    z: Vector3 = Vector3(0.0, 0.0, 1.0)

    @staticmethod
    def world_xy(origin: Optional[Point3] = None):
        return PlaneF(origin or Point3())

    @staticmethod
    def world_xz(origin: Optional[Point3] = None):
        return PlaneF(origin or Point3(), Vector3(1, 0, 0), Vector3(0, 0, 1), Vector3(0, -1, 0))

    @staticmethod
    def world_yz(origin: Optional[Point3] = None):
        return PlaneF(origin or Point3(), Vector3(0, 1, 0), Vector3(0, 0, 1), Vector3(1, 0, 0))

    @staticmethod
    def from_origin_normal(origin: Point3, normal: Vector3, x_hint: Optional[Vector3] = None):
        z = normal.unit()
        x = None
        if x_hint is not None:
            x = x_hint - z * x_hint.dot(z)
            if x.length < 1e-9:
                x = None
        if x is None:
            x = Vector3(0, 0, 1).cross(z)
            if x.length < 1e-9:
                x = Vector3(1, 0, 0)
        x = x.unit()
        return PlaneF(origin, x, z.cross(x), z)

    @staticmethod
    def from_origin_axes(origin: Point3, x_axis: Vector3, y_axis: Vector3):
        x = x_axis.unit()
        y = y_axis - x * y_axis.dot(x)
        if y.length < 1e-9:
            raise ValueError3("the two axes are parallel")
        y = y.unit()
        return PlaneF(origin, x, y, x.cross(y))

    @staticmethod
    def from_3_points(o: Point3, px: Point3, py: Point3):
        return PlaneF.from_origin_axes(o, px - o, py - o)

    def point_at(self, u: float, v: float, w: float = 0.0) -> Point3:
        return self.origin + self.x * u + self.y * v + self.z * w

    def local(self, p: Point3) -> tuple:
        d = p - self.origin
        return (d.dot(self.x), d.dot(self.y), d.dot(self.z))

    def project(self, p: Point3) -> Point3:
        u, v, _ = self.local(p)
        return self.point_at(u, v, 0.0)

    def distance_to(self, p: Point3) -> float:
        return self.local(p)[2]

    def to_list(self) -> list:
        return [self.origin.to_list(), self.x.to_list(), self.y.to_list(), self.z.to_list()]


@dataclass(frozen=True, slots=True)
class Line3:
    a: Point3
    b: Point3

    @property
    def length(self) -> float:
        return self.a.distance(self.b)

    @property
    def direction(self) -> Vector3:
        return self.b - self.a

    def point_at(self, t: float) -> Point3:
        return self.a + (self.b - self.a) * t

    def flipped(self):
        return Line3(self.b, self.a)


@dataclass(frozen=True, slots=True)
class Polyline3:
    points: tuple
    closed: bool = False

    def __post_init__(self):
        object.__setattr__(self, "points", tuple(self.points))
        if len(self.points) < 2:
            raise ValueError3("a polyline needs at least two points")

    def segments(self) -> list:
        n = len(self.points)
        out = [Line3(self.points[i], self.points[i + 1]) for i in range(n - 1)]
        if self.closed and n > 2:
            out.append(Line3(self.points[-1], self.points[0]))
        return out

    @property
    def length(self) -> float:
        return sum(s.length for s in self.segments())


@dataclass(frozen=True, slots=True)
class Circle3:
    plane: PlaneF
    radius: float

    def __post_init__(self):
        if not self.radius > 0:
            raise ValueError3("a circle needs a positive radius")

    @property
    def length(self) -> float:
        return 2.0 * math.pi * self.radius

    @property
    def area(self) -> float:
        return math.pi * self.radius * self.radius

    def point_at(self, t: float) -> Point3:
        a = t * 2.0 * math.pi
        return self.plane.point_at(self.radius * math.cos(a), self.radius * math.sin(a))


@dataclass(frozen=True, slots=True)
class Arc3:
    plane: PlaneF
    radius: float
    start: float
    end: float

    def __post_init__(self):
        if not self.radius > 0:
            raise ValueError3("an arc needs a positive radius")
        if abs(self.end - self.start) < EPS:
            raise ValueError3("an arc needs a nonzero sweep")

    @property
    def sweep(self) -> float:
        return self.end - self.start

    @property
    def length(self) -> float:
        return abs(self.sweep) * self.radius

    def point_at(self, t: float) -> Point3:
        a = self.start + t * self.sweep
        return self.plane.point_at(self.radius * math.cos(a), self.radius * math.sin(a))

    @staticmethod
    def from_3_points(p0: Point3, p1: Point3, p2: Point3):
        a, b = p1 - p0, p2 - p0
        n = a.cross(b)
        d = 2.0 * n.dot(n)
        if d < EPS:
            raise ValueError3("the three points are collinear")
        off = (b * a.dot(a) - a * b.dot(b)).cross(n) / d
        c = p0 + off
        plane = PlaneF.from_origin_normal(c, n, p0 - c)
        u, v, _ = plane.local(p2)
        end = math.atan2(v, u)
        if end <= 0:
            end += 2 * math.pi
        return Arc3(plane, c.distance(p0), 0.0, end)


@dataclass(frozen=True, slots=True)
class Transform:
    m: tuple = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

    def __post_init__(self):
        m = tuple(float(v) for v in self.m)
        if len(m) != 16:
            raise ValueError3("a transform has 16 numbers")
        object.__setattr__(self, "m", m)

    @staticmethod
    def identity():
        return Transform()

    @staticmethod
    def translation(v: Vector3):
        return Transform((1, 0, 0, v.x, 0, 1, 0, v.y, 0, 0, 1, v.z, 0, 0, 0, 1))

    @staticmethod
    def rotation(angle: float, axis: Vector3 = Vector3(0, 0, 1), centre: Point3 = Point3()):
        k = axis.unit()
        c, s = math.cos(angle), math.sin(angle)
        t = 1.0 - c
        r = (
            t * k.x * k.x + c, t * k.x * k.y - s * k.z, t * k.x * k.z + s * k.y,
            t * k.x * k.y + s * k.z, t * k.y * k.y + c, t * k.y * k.z - s * k.x,
            t * k.x * k.z - s * k.y, t * k.y * k.z + s * k.x, t * k.z * k.z + c,
        )
        cx, cy, cz = centre.x, centre.y, centre.z
        tx = cx - (r[0] * cx + r[1] * cy + r[2] * cz)
        ty = cy - (r[3] * cx + r[4] * cy + r[5] * cz)
        tz = cz - (r[6] * cx + r[7] * cy + r[8] * cz)
        return Transform((r[0], r[1], r[2], tx, r[3], r[4], r[5], ty, r[6], r[7], r[8], tz, 0, 0, 0, 1))

    @staticmethod
    def scaling(sx: float, sy: Optional[float] = None, sz: Optional[float] = None, centre: Point3 = Point3()):
        sy = sx if sy is None else sy
        sz = sx if sz is None else sz
        return Transform((sx, 0, 0, centre.x * (1 - sx), 0, sy, 0, centre.y * (1 - sy), 0, 0, sz, centre.z * (1 - sz), 0, 0, 0, 1))

    @staticmethod
    def mirror(plane: PlaneF):
        n = plane.z.unit()
        d = n.dot(plane.origin.to_vector())
        return Transform((
            1 - 2 * n.x * n.x, -2 * n.x * n.y, -2 * n.x * n.z, 2 * d * n.x,
            -2 * n.y * n.x, 1 - 2 * n.y * n.y, -2 * n.y * n.z, 2 * d * n.y,
            -2 * n.z * n.x, -2 * n.z * n.y, 1 - 2 * n.z * n.z, 2 * d * n.z,
            0, 0, 0, 1,
        ))

    @staticmethod
    def plane_to_plane(a: PlaneF, b: PlaneF):
        fa = Transform.from_plane(a).inverse()
        return Transform.from_plane(b).compose(fa)

    @staticmethod
    def from_plane(p: PlaneF):
        return Transform((p.x.x, p.y.x, p.z.x, p.origin.x, p.x.y, p.y.y, p.z.y, p.origin.y, p.x.z, p.y.z, p.z.z, p.origin.z, 0, 0, 0, 1))

    def compose(self, other):
        a, b = self.m, other.m
        out = []
        for i in range(4):
            for j in range(4):
                out.append(sum(a[i * 4 + k] * b[k * 4 + j] for k in range(4)))
        return Transform(tuple(out))

    __matmul__ = compose

    def determinant(self) -> float:
        import numpy as np

        return float(np.linalg.det(np.array(self.m).reshape(4, 4)))

    def inverse(self):
        import numpy as np

        mat = np.array(self.m).reshape(4, 4)
        if abs(np.linalg.det(mat)) < 1e-14:
            raise ValueError3("this transform cannot be inverted")
        return Transform(tuple(np.linalg.inv(mat).reshape(16).tolist()))

    def point(self, p: Point3) -> Point3:
        m = self.m
        x = m[0] * p.x + m[1] * p.y + m[2] * p.z + m[3]
        y = m[4] * p.x + m[5] * p.y + m[6] * p.z + m[7]
        z = m[8] * p.x + m[9] * p.y + m[10] * p.z + m[11]
        w = m[12] * p.x + m[13] * p.y + m[14] * p.z + m[15]
        if abs(w - 1.0) > 1e-12 and abs(w) > EPS:
            return Point3(x / w, y / w, z / w)
        return Point3(x, y, z)

    def vector(self, v: Vector3) -> Vector3:
        m = self.m
        return Vector3(m[0] * v.x + m[1] * v.y + m[2] * v.z, m[4] * v.x + m[5] * v.y + m[6] * v.z, m[8] * v.x + m[9] * v.y + m[10] * v.z)

    def plane(self, p: PlaneF) -> PlaneF:
        x = self.vector(p.x)
        y = self.vector(p.y)
        scale = x.length
        o = self.point(p.origin)
        xu = x.unit()
        yo = y - xu * y.dot(xu)
        if yo.length < 1e-12:
            raise ValueError3("the transform collapses the plane")
        yu = yo.unit()
        z = xu.cross(yu)
        if self.determinant() < 0:
            z = -z
        return PlaneF(o, xu, yu, z) if scale > 0 else p

    def apply(self, value):
        if isinstance(value, Point3):
            return self.point(value)
        if isinstance(value, Vector3):
            return self.vector(value)
        if isinstance(value, PlaneF):
            return self.plane(value)
        if isinstance(value, Line3):
            return Line3(self.point(value.a), self.point(value.b))
        if isinstance(value, Polyline3):
            return Polyline3(tuple(self.point(p) for p in value.points), value.closed)
        if isinstance(value, Circle3):
            return Circle3(self.plane(value.plane), value.radius * self.vector(value.plane.x).length)
        if isinstance(value, Arc3):
            return Arc3(self.plane(value.plane), value.radius * self.vector(value.plane.x).length, value.start, value.end)
        if isinstance(value, Transform):
            return self.compose(value)
        raise ValueError3("this value cannot be transformed here")

    def to_rows(self) -> list:
        return [list(self.m[i * 4:i * 4 + 4]) for i in range(4)]


@dataclass(frozen=True, slots=True)
class Shape:
    kind: str
    sid: str
    bbox: Optional[tuple] = None


GEOMETRY_TYPES = (Point3, Vector3, PlaneF, Line3, Polyline3, Circle3, Arc3, Shape)
VALUE_TYPES = {c.__name__: c for c in (Point3, Vector3, PlaneF, Domain, Colour, Line3, Polyline3, Arc3, Circle3, Transform, Shape)}


def encode(value):
    t = type(value).__name__
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Point3) or isinstance(value, Vector3):
        return {"$": t, "v": [value.x, value.y, value.z]}
    if isinstance(value, Domain):
        return {"$": t, "v": [value.t0, value.t1]}
    if isinstance(value, Colour):
        return {"$": t, "v": value.hex()}
    if isinstance(value, PlaneF):
        return {"$": t, "v": value.to_list()}
    if isinstance(value, Line3):
        return {"$": t, "v": [value.a.to_list(), value.b.to_list()]}
    if isinstance(value, Polyline3):
        return {"$": t, "v": [p.to_list() for p in value.points], "closed": value.closed}
    if isinstance(value, Circle3):
        return {"$": t, "plane": encode(value.plane)["v"], "r": value.radius}
    if isinstance(value, Arc3):
        return {"$": t, "plane": encode(value.plane)["v"], "r": value.radius, "a0": value.start, "a1": value.end}
    if isinstance(value, Transform):
        return {"$": t, "v": list(value.m)}
    if isinstance(value, Shape):
        return {"$": t, "kind": value.kind, "sid": value.sid, "bbox": list(value.bbox) if value.bbox else None}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    stored = getattr(value, "to_stored", None)
    if callable(stored):
        return stored()
    raise ValueError3("a %s cannot be stored in a data tree" % t)


def _pt(v):
    return Point3(*[float(c) for c in v])


def _vec(v):
    return Vector3(*[float(c) for c in v])


def _plane(v):
    return PlaneF(_pt(v[0]), _vec(v[1]), _vec(v[2]), _vec(v[3]))


def decode(obj):
    if isinstance(obj, list):
        return [decode(v) for v in obj]
    if not isinstance(obj, dict):
        return obj
    t = obj.get("$")
    if t not in VALUE_TYPES:
        raise ValueError3("unknown stored value type %r" % (t,))
    if t == "Point3":
        return _pt(obj["v"])
    if t == "Vector3":
        return _vec(obj["v"])
    if t == "Domain":
        return Domain(float(obj["v"][0]), float(obj["v"][1]))
    if t == "Colour":
        return Colour.from_hex(obj["v"])
    if t == "PlaneF":
        return _plane(obj["v"])
    if t == "Line3":
        return Line3(_pt(obj["v"][0]), _pt(obj["v"][1]))
    if t == "Polyline3":
        return Polyline3(tuple(_pt(p) for p in obj["v"]), bool(obj.get("closed", False)))
    if t == "Circle3":
        return Circle3(_plane(obj["plane"]), float(obj["r"]))
    if t == "Arc3":
        return Arc3(_plane(obj["plane"]), float(obj["r"]), float(obj["a0"]), float(obj["a1"]))
    if t == "Transform":
        return Transform(tuple(obj["v"]))
    return Shape(str(obj["kind"]), str(obj["sid"]), tuple(obj["bbox"]) if obj.get("bbox") else None)


def to_wire(value, kind: str):
    if value is None or kind in ("number", "integer", "boolean", "text"):
        return value
    if kind in ("point", "vector") and isinstance(value, (Point3, Vector3)):
        return value.to_list()
    if kind == "plane" and isinstance(value, PlaneF):
        return {"origin": value.origin.to_list(), "x": value.x.to_list(), "y": value.y.to_list()}
    if kind == "domain" and isinstance(value, Domain):
        return value.to_list()
    if kind == "colour" and isinstance(value, Colour):
        return value.hex()
    if kind == "transform" and isinstance(value, Transform):
        return list(value.m)
    if isinstance(value, Shape):
        return {"handle": value.sid, "type": value.kind, "bbox": list(value.bbox) if value.bbox else None}
    return encode(value)


def from_wire(obj, kind: str):
    if obj is None:
        return None
    if kind == "number":
        return float(obj)
    if kind == "integer":
        return int(obj)
    if kind == "boolean":
        return bool(obj)
    if kind == "text":
        return str(obj)
    if kind == "point":
        return _pt(obj)
    if kind == "vector":
        return _vec(obj)
    if kind == "plane":
        return PlaneF.from_origin_axes(_pt(obj["origin"]), _vec(obj["x"]), _vec(obj["y"]))
    if kind == "domain":
        return Domain(float(obj[0]), float(obj[1]))
    if kind == "colour":
        return Colour.from_hex(obj)
    if kind == "transform":
        return Transform(tuple(obj))
    if isinstance(obj, dict) and "handle" in obj:
        return Shape(str(obj.get("type", kind)), str(obj["handle"]), tuple(obj["bbox"]) if obj.get("bbox") else None)
    return decode(obj)


def flat_numbers(value) -> Optional[tuple]:
    if isinstance(value, (Point3, Vector3)):
        return (value.x, value.y, value.z)
    if isinstance(value, Domain):
        return (value.t0, value.t1)
    if isinstance(value, Colour):
        return tuple(value.to_list())
    if isinstance(value, PlaneF):
        return tuple(c for row in value.to_list() for c in row)
    if isinstance(value, Line3):
        return flat_numbers(value.a) + flat_numbers(value.b)
    if isinstance(value, Polyline3):
        return tuple(c for p in value.points for c in flat_numbers(p)) + (1.0 if value.closed else 0.0,)
    if isinstance(value, Circle3):
        return flat_numbers(value.plane) + (value.radius,)
    if isinstance(value, Arc3):
        return flat_numbers(value.plane) + (value.radius, value.start, value.end)
    if isinstance(value, Transform):
        return value.m
    return None


def close(a, b, tol: float = 1e-9) -> bool:
    if type(a) is not type(b):
        return False
    fa, fb = flat_numbers(a), flat_numbers(b)
    if fa is None:
        return a == b
    return len(fa) == len(fb) and all(abs(p - q) <= tol for p, q in zip(fa, fb))


KINDS = ("any", "number", "integer", "boolean", "text", "point", "vector", "plane", "domain", "colour", "curve", "surface", "brep", "mesh", "geometry", "transform", "docref")
CURVE_TYPES = (Line3, Polyline3, Arc3, Circle3)


def kind_of(value) -> str:
    if value is None:
        return "any"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, Point3):
        return "point"
    if isinstance(value, Vector3):
        return "vector"
    if isinstance(value, PlaneF):
        return "plane"
    if isinstance(value, Domain):
        return "domain"
    if isinstance(value, Colour):
        return "colour"
    if isinstance(value, CURVE_TYPES):
        return "curve"
    if isinstance(value, Transform):
        return "transform"
    if isinstance(value, Shape):
        return value.kind if value.kind in ("curve", "surface", "brep", "mesh") else "geometry"
    return "any"


def convert(value, kind: str):
    if value is None or kind in ("any", "docref"):
        return value
    got = kind_of(value)
    if got == kind:
        return value
    if kind == "number" and got == "integer":
        return float(value)
    if kind == "integer" and got == "number" and float(value).is_integer():
        return int(value)
    if kind == "number" and got == "boolean":
        return 1.0 if value else 0.0
    if kind == "boolean" and got in ("number", "integer"):
        return bool(value)
    if kind == "vector" and got == "point":
        return value.to_vector()
    if kind == "point" and got == "vector":
        return value.to_point()
    if kind == "domain" and got in ("number", "integer"):
        return Domain(0.0, float(value))
    if kind == "number" and got == "domain":
        return value.length
    if kind == "text" and got in ("number", "integer", "boolean"):
        return str(value).lower() if got == "boolean" else str(value)
    if kind == "geometry" and (got in ("curve", "surface", "brep", "mesh", "point", "plane", "geometry")):
        return value
    if kind == "geometry" and isinstance(value, (Line3, Polyline3, Arc3, Circle3)):
        return value
    if kind == "curve" and isinstance(value, Shape) and value.kind == "curve":
        return value
    raise ValueError3("a %s cannot be used as a %s" % (got, kind))
