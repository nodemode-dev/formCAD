from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind


def _z() -> list:
    return [0.0, 0.0, 0.0]


class Annotation(Entity):
    kind: ClassVar[str] = "annotation"

    def bounds(self):
        from app.drawann import build

        prims, _info = build.build(self)
        b = build.bounds_of(prims)
        return tuple(b) if b else geom.bounds_of_points([self.position]) if hasattr(self, "position") else None

    def snap_points(self):
        return [self.position] if hasattr(self, "position") else []


def _size_xf(self, xf, names):
    for n in names:
        v = getattr(self, n)
        if v:
            setattr(self, n, v * xf.k)


@entity_kind
@dataclass
class GdtFrame(Annotation):
    kind: ClassVar[str] = "gdtframe"
    POINTS: ClassVar[tuple] = ("position",)
    POINT_LISTS: ClassVar[tuple] = ("leader",)
    position: list = field(default_factory=_z)
    rotation: float = 0.0
    char: str = "position"
    tolerance: str = "0.1"
    zone: str = "none"
    modifier: str = ""
    projected: bool = False
    datums: list = field(default_factory=list)
    order: list = field(default_factory=list)
    text_height: float = 0.0
    leader: list = field(default_factory=list)
    leader_side: str = ""
    leader_link: dict = field(default_factory=dict)
    arrow: bool = True
    note_above: str = ""
    note_below: str = ""

    def apply_transform(self, xf) -> None:
        self.position = xf.pt(self.position)
        self.leader = [xf.pt(p) for p in self.leader]
        if xf.mode == "rotate":
            self.rotation += xf.angle
        _size_xf(self, xf, ("text_height",))
        self.leader_link = {}

    def valid(self):
        return super().valid() and self.char != ""


@entity_kind
@dataclass
class DatumSymbol(Annotation):
    kind: ClassVar[str] = "datumsym"
    POINTS: ClassVar[tuple] = ("position", "tip")
    position: list = field(default_factory=_z)
    letter: str = "A"
    tip: Any = None
    tip_link: dict = field(default_factory=dict)
    text_height: float = 0.0
    filled: bool = True

    def apply_transform(self, xf) -> None:
        self.position = xf.pt(self.position)
        if self.tip:
            self.tip = xf.pt(self.tip)
        _size_xf(self, xf, ("text_height",))
        self.tip_link = {}


@entity_kind
@dataclass
class Balloon(Annotation):
    kind: ClassVar[str] = "balloon"
    POINTS: ClassVar[tuple] = ("position", "tip")
    position: list = field(default_factory=_z)
    text: str = "1"
    tip: Any = None
    tip_link: dict = field(default_factory=dict)
    diameter: float = 0.0
    end: str = ""
    item: str = ""
    part_key: str = ""

    def apply_transform(self, xf) -> None:
        self.position = xf.pt(self.position)
        if self.tip:
            self.tip = xf.pt(self.tip)
        _size_xf(self, xf, ("diameter",))
        self.tip_link = {}


@entity_kind
@dataclass
class FinishMark(Annotation):
    kind: ClassVar[str] = "finishmark"
    POINTS: ClassVar[tuple] = ("position",)
    position: list = field(default_factory=_z)
    value: str = "Ra 3.2"
    height: float = 0.0
    rotation: float = 0.0
    tip_link: dict = field(default_factory=dict)

    def apply_transform(self, xf) -> None:
        self.position = xf.pt(self.position)
        if xf.mode == "rotate":
            self.rotation += xf.angle
        _size_xf(self, xf, ("height",))
        self.tip_link = {}


@entity_kind
@dataclass
class CenterMark(Annotation):
    kind: ClassVar[str] = "centermark"
    POINTS: ClassVar[tuple] = ("center", "a", "b")
    center: list = field(default_factory=_z)
    radius: float = 1.0
    mode: str = "circle"
    a: Any = None
    b: Any = None
    link: dict = field(default_factory=dict)
    a_link: dict = field(default_factory=dict)
    b_link: dict = field(default_factory=dict)
    view: int = 0
    edge: str = ""

    def apply_transform(self, xf) -> None:
        self.center = xf.pt(self.center)
        if self.a:
            self.a = xf.pt(self.a)
        if self.b:
            self.b = xf.pt(self.b)
        self.radius *= xf.k
        self.link, self.a_link, self.b_link = {}, {}, {}

    def snap_points(self):
        return [self.center] if self.mode == "circle" else [p for p in (self.a, self.b) if p]

    def valid(self):
        if self.mode == "axis":
            return super().valid() and self.a is not None and self.b is not None
        return super().valid() and self.radius > geom.EPS
