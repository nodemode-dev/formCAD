import copy
import math
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

from app.doc import geom

KINDS: dict = {}

MAX_VERTICES = 1_000_000
MAX_SPLINE_DEGREE = 64


def entity_kind(cls):
    KINDS[cls.kind] = cls
    return cls


def _z() -> list:
    return [0.0, 0.0, 0.0]


def _n() -> list:
    return [0.0, 0.0, 1.0]


@dataclass
class Entity:
    kind: ClassVar[str] = "entity"
    POINTS: ClassVar[tuple] = ()
    POINT_LISTS: ClassVar[tuple] = ()
    VERTEX_LISTS: ClassVar[tuple] = ()

    handle: int = 0
    owner: str = "model"
    layer: str = "0"
    color: Any = 256
    linetype: str = "ByLayer"
    lineweight: int = -1
    ltscale: float = 1.0
    transparency: Any = "ByLayer"
    visible: bool = True
    thickness: float = 0.0
    normal: list = field(default_factory=_n)
    plot_style: str = "ByLayer"
    annotation_scales: list = field(default_factory=list)
    xdata: dict = field(default_factory=dict)
    reactors: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"kind": self.kind}
        for f in fields(self):
            out[f.name] = copy.deepcopy(getattr(self, f.name))
        return out

    @classmethod
    def from_dict(cls, data: dict):
        names = {f.name for f in fields(cls)}
        kwargs = {k: copy.deepcopy(v) for k, v in data.items() if k in names}
        obj = cls(**kwargs)
        stray = {k: copy.deepcopy(v) for k, v in data.items() if k not in names and k != "kind"}
        if stray:
            obj.extra = {**obj.extra, **stray}
        return obj

    def bounds(self):
        return None

    def move_by(self, d) -> None:
        for name in self.POINTS:
            v = getattr(self, name)
            if v is not None:
                setattr(self, name, _shift(v, d))
        for name in self.POINT_LISTS:
            setattr(self, name, [_shift(p, d) for p in getattr(self, name)])
        for name in self.VERTEX_LISTS:
            for v in getattr(self, name):
                v["p"] = _shift(v["p"], d)

    def copy_as_new(self):
        clone = self.from_dict(self.to_dict())
        clone.handle = 0
        return clone

    def snap_points(self) -> list:
        return []

    def valid(self) -> bool:
        return geom.finite_tree(self.to_dict())


def _shift(p, d) -> list:
    out = list(p)
    out[0] = p[0] + d[0]
    out[1] = p[1] + d[1]
    if len(p) > 2:
        out[2] = p[2] + (d[2] if len(d) > 2 else 0.0)
    return out


@entity_kind
@dataclass
class Line(Entity):
    kind: ClassVar[str] = "line"
    POINTS: ClassVar[tuple] = ("start", "end")
    start: list = field(default_factory=_z)
    end: list = field(default_factory=_z)

    def bounds(self):
        return geom.bounds_of_points([self.start, self.end])

    def snap_points(self):
        return [self.start, self.end, geom.midpoint(self.start, self.end)]

    def valid(self):
        return super().valid() and geom.dist(self.start, self.end) > geom.EPS


@entity_kind
@dataclass
class Point(Entity):
    kind: ClassVar[str] = "point"
    POINTS: ClassVar[tuple] = ("position",)
    position: list = field(default_factory=_z)
    angle: float = 0.0

    def bounds(self):
        return geom.bounds_of_points([self.position])

    def snap_points(self):
        return [self.position]


@entity_kind
@dataclass
class Circle(Entity):
    kind: ClassVar[str] = "circle"
    POINTS: ClassVar[tuple] = ("center",)
    center: list = field(default_factory=_z)
    radius: float = 1.0

    def bounds(self):
        c, r = self.center, self.radius
        return c[0] - r, c[1] - r, c[0] + r, c[1] + r

    def snap_points(self):
        return [self.center] + [geom.polar(self.center, self.radius, k * math.pi / 2) for k in range(4)]

    def valid(self):
        return super().valid() and self.radius > geom.EPS


@entity_kind
@dataclass
class Arc(Entity):
    kind: ClassVar[str] = "arc"
    POINTS: ClassVar[tuple] = ("center",)
    center: list = field(default_factory=_z)
    radius: float = 1.0
    start_angle: float = 0.0
    end_angle: float = math.pi

    def bounds(self):
        return geom.arc_bounds(self.center, self.radius, self.start_angle, self.end_angle)

    def snap_points(self):
        a0, a1 = self.start_angle, self.end_angle
        mid = a0 + geom.ccw_sweep(a0, a1) / 2.0
        return [geom.polar(self.center, self.radius, a0), geom.polar(self.center, self.radius, mid), geom.polar(self.center, self.radius, a1), self.center]

    def valid(self):
        return super().valid() and self.radius > geom.EPS


@entity_kind
@dataclass
class Ellipse(Entity):
    kind: ClassVar[str] = "ellipse"
    POINTS: ClassVar[tuple] = ("center",)
    center: list = field(default_factory=_z)
    major: list = field(default_factory=lambda: [1.0, 0.0, 0.0])
    ratio: float = 0.5
    start_param: float = 0.0
    end_param: float = geom.TAU

    def sample(self, n: int = 96) -> list:
        sweep = geom.ccw_sweep(self.start_param, self.end_param) if abs(self.end_param - self.start_param) < geom.TAU - 1e-12 else geom.TAU
        ux, uy = self.major[0], self.major[1]
        vx, vy = -uy * self.ratio, ux * self.ratio
        out = []
        for i in range(n + 1):
            t = self.start_param + sweep * i / n
            out.append([self.center[0] + ux * math.cos(t) + vx * math.sin(t), self.center[1] + uy * math.cos(t) + vy * math.sin(t), 0.0])
        return out

    def bounds(self):
        return geom.bounds_of_points(self.sample())

    def valid(self):
        return super().valid() and math.hypot(self.major[0], self.major[1]) > geom.EPS and 0 < self.ratio <= 1.0


@entity_kind
@dataclass
class LwPolyline(Entity):
    kind: ClassVar[str] = "lwpolyline"
    VERTEX_LISTS: ClassVar[tuple] = ("vertices",)
    vertices: list = field(default_factory=list)
    closed: bool = False
    const_width: float = 0.0
    elevation: float = 0.0
    linetype_gen: bool = False

    def segments(self):
        n = len(self.vertices)
        count = n if self.closed else n - 1
        for i in range(max(count, 0)):
            a = self.vertices[i]
            b = self.vertices[(i + 1) % n]
            yield a["p"], b["p"], a.get("bulge", 0.0)

    def bounds(self):
        box = geom.bounds_of_points([v["p"] for v in self.vertices])
        for p0, p1, bulge in self.segments():
            arc = geom.bulge_to_arc(p0, p1, bulge)
            if arc:
                center, r, a0, a1, _ccw = arc
                box = geom.union_bounds(box, geom.arc_bounds(center, r, a0, a1))
        return box

    def snap_points(self):
        out = []
        for v in self.vertices:
            out.append(v["p"])
        for p0, p1, _b in self.segments():
            out.append(geom.midpoint(p0, p1))
        return out

    def valid(self):
        return super().valid() and len(self.vertices) >= 2

    @classmethod
    def from_points(cls, points, closed=False, bulges=None, **kw):
        verts = []
        for i, p in enumerate(points):
            verts.append({"p": [float(p[0]), float(p[1])], "bulge": float(bulges[i]) if bulges else 0.0, "sw": 0.0, "ew": 0.0})
        return cls(vertices=verts, closed=closed, **kw)


@entity_kind
@dataclass
class Polyline3d(Entity):
    kind: ClassVar[str] = "polyline3d"
    POINT_LISTS: ClassVar[tuple] = ("points",)
    points: list = field(default_factory=list)
    closed: bool = False

    def bounds(self):
        return geom.bounds_of_points(self.points)

    def snap_points(self):
        return list(self.points)


@entity_kind
@dataclass
class Spline(Entity):
    kind: ClassVar[str] = "spline"
    POINT_LISTS: ClassVar[tuple] = ("control_points", "fit_points")
    degree: int = 3
    knots: list = field(default_factory=list)
    control_points: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    fit_points: list = field(default_factory=list)
    closed: bool = False
    fit_method: int = 0
    start_tangent: Any = None
    end_tangent: Any = None
    fit_tolerance: float = 0.0

    def bounds(self):
        return geom.bounds_of_points(self.control_points or self.fit_points)

    def snap_points(self):
        pts = self.fit_points or self.control_points
        return [pts[0], pts[-1]] if pts else []

    def valid(self):
        return super().valid() and 1 <= self.degree <= MAX_SPLINE_DEGREE


@entity_kind
@dataclass
class Ray(Entity):
    kind: ClassVar[str] = "ray"
    POINTS: ClassVar[tuple] = ("base",)
    base: list = field(default_factory=_z)
    direction: list = field(default_factory=lambda: [1.0, 0.0, 0.0])

    def snap_points(self):
        return [self.base]


@entity_kind
@dataclass
class XLine(Entity):
    kind: ClassVar[str] = "xline"
    POINTS: ClassVar[tuple] = ("base",)
    base: list = field(default_factory=_z)
    direction: list = field(default_factory=lambda: [1.0, 0.0, 0.0])


@entity_kind
@dataclass
class Text(Entity):
    kind: ClassVar[str] = "text"
    POINTS: ClassVar[tuple] = ("position", "align_point")
    position: list = field(default_factory=_z)
    align_point: Any = None
    height: float = 2.5
    text: str = ""
    rotation: float = 0.0
    width_factor: float = 1.0
    oblique: float = 0.0
    style: str = "Standard"
    halign: int = 0
    valign: int = 0

    def bounds(self):
        w = self.height * 0.6 * self.width_factor * max(len(self.text), 1)
        x, y = self.position[0], self.position[1]
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        pts = [[x, y], [x + w * c, y + w * s], [x - self.height * s, y + self.height * c], [x + w * c - self.height * s, y + w * s + self.height * c]]
        return geom.bounds_of_points(pts)

    def snap_points(self):
        return [self.align_point or self.position]


@entity_kind
@dataclass
class MText(Entity):
    kind: ClassVar[str] = "mtext"
    POINTS: ClassVar[tuple] = ("position",)
    position: list = field(default_factory=_z)
    height: float = 2.5
    width: float = 0.0
    attachment: int = 1
    rotation: float = 0.0
    style: str = "Standard"
    contents: str = ""
    line_spacing: float = 1.0
    line_spacing_style: int = 1
    columns: dict = field(default_factory=dict)

    def bounds(self):
        lines = self.contents.split("\n") if self.contents else [""]
        w = self.width or self.height * 0.6 * max((len(s) for s in lines), default=1)
        h = self.height * 1.5 * len(lines)
        x, y = self.position[0], self.position[1]
        return x, y - h, x + w, y

    def snap_points(self):
        return [self.position]


@entity_kind
@dataclass
class AttDef(Entity):
    kind: ClassVar[str] = "attdef"
    POINTS: ClassVar[tuple] = ("position", "align_point")
    position: list = field(default_factory=_z)
    tag: str = ""
    prompt: str = ""
    default: str = ""
    height: float = 2.5
    rotation: float = 0.0
    style: str = "Standard"
    modes: dict = field(default_factory=lambda: {"invisible": False, "constant": False, "verify": False, "preset": False, "lock_position": False})
    align_point: Any = None
    halign: int = 0
    valign: int = 0
    width_factor: float = 1.0
    oblique: float = 0.0

    def bounds(self):
        w = self.height * 0.6 * self.width_factor * max(len(self.tag), 1)
        x, y = self.position[0], self.position[1]
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        pts = [[x, y], [x + w * c, y + w * s], [x - self.height * s, y + self.height * c], [x + w * c - self.height * s, y + w * s + self.height * c]]
        return geom.bounds_of_points(pts)

    def snap_points(self):
        return [self.align_point or self.position]


@entity_kind
@dataclass
class Insert(Entity):
    kind: ClassVar[str] = "insert"
    POINTS: ClassVar[tuple] = ("position",)
    block: str = ""
    position: list = field(default_factory=_z)
    scale: list = field(default_factory=lambda: [1.0, 1.0, 1.0])
    rotation: float = 0.0
    attributes: list = field(default_factory=list)
    array: dict = field(default_factory=dict)

    def bounds(self):
        box = self.extra.get("box")
        if box:
            return (box[0], box[1], box[2], box[3])
        return geom.bounds_of_points([self.position])

    def move_by(self, d) -> None:
        Entity.move_by(self, d)
        box = self.extra.get("box")
        if box:
            self.extra = {**self.extra, "box": [box[0] + d[0], box[1] + d[1], box[2] + d[0], box[3] + d[1]]}

    def snap_points(self):
        return [self.position]


@entity_kind
@dataclass
class Hatch(Entity):
    kind: ClassVar[str] = "hatch"
    pattern: str = "ANSI31"
    solid: bool = False
    loops: list = field(default_factory=list)
    pattern_scale: float = 1.0
    pattern_angle: float = 0.0
    associative: bool = False
    style: int = 0
    elevation: float = 0.0
    gradient: Any = None
    origin: list = field(default_factory=lambda: [0.0, 0.0])
    background: Any = None
    pattern_lines: list = field(default_factory=list)
    origin_mode: str = "current"
    gap: float = 0.0
    annotative: bool = False

    def move_by(self, d):
        for loop in self.loops:
            for v in loop.get("vertices", []):
                v["p"] = _shift(v["p"], d)
        self.origin = _shift(self.origin, d)

    def bounds(self):
        from app.doc import planar

        pts = [p for loop in self.loops for p in planar.flatten_loop(loop.get("vertices", []))]
        return geom.bounds_of_points(pts)


@entity_kind
@dataclass
class Solid(Entity):
    kind: ClassVar[str] = "solid"
    POINT_LISTS: ClassVar[tuple] = ("corners",)
    corners: list = field(default_factory=list)

    def bounds(self):
        return geom.bounds_of_points(self.corners)


@entity_kind
@dataclass
class Dimension(Entity):
    kind: ClassVar[str] = "dimension"
    POINTS: ClassVar[tuple] = ("def_point", "text_point", "p13", "p14", "p15", "p16")
    dim_type: str = "linear"
    def_point: list = field(default_factory=_z)
    text_point: list = field(default_factory=_z)
    p13: Any = None
    p14: Any = None
    p15: Any = None
    p16: Any = None
    text_override: str = ""
    style: str = "Standard"
    measurement: float = 0.0
    rotation: float = 0.0
    text_moved: bool = False
    block: str = ""
    overrides: dict = field(default_factory=dict)
    associativity: dict = field(default_factory=dict)
    marks: dict = field(default_factory=dict)

    def bounds(self):
        pts = [p for p in (self.def_point, self.text_point, self.p13, self.p14, self.p15, self.p16) if p]
        return geom.bounds_of_points(pts)


@entity_kind
@dataclass
class Unknown(Entity):
    kind: ClassVar[str] = "unknown"
    type_name: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"kind": self.type_name or "unknown"}
        for name in BASE_FIELDS:
            out[name] = copy.deepcopy(getattr(self, name))
        out.update(copy.deepcopy(self.raw))
        return out


BASE_FIELDS = tuple(f.name for f in fields(Entity))


def entity_from_dict(data: dict) -> Entity:
    kind = data.get("kind")
    cls = KINDS.get(kind)
    if cls is None or cls is Unknown:
        rest = {k: copy.deepcopy(v) for k, v in data.items() if k not in ("kind",)}
        common = {k: v for k, v in rest.items() if k in BASE_FIELDS}
        ent = Unknown(**common)
        ent.type_name = str(kind or "")
        ent.raw = {k: v for k, v in rest.items() if k not in BASE_FIELDS}
        return ent
    return cls.from_dict(data)


from app.doc import kinds  # noqa: E402,F401
