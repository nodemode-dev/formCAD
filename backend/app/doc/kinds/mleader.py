import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind

MAX_LEADERS = 1000
MAX_POINTS = 100
LEADER_TYPES = ("straight", "spline", "none")
CONTENT_TYPES = ("mtext", "block", "none")


def _z() -> list:
    return [0.0, 0.0, 0.0]


def _pair(p) -> list:
    return [float(p[0]), float(p[1])]


@entity_kind
@dataclass
class MLeader(Entity):
    kind: ClassVar[str] = "mleader"
    POINTS: ClassVar[tuple] = ("landing", "content_pos")
    style: str = "Standard"
    leaders: list = field(default_factory=list)
    landing: list = field(default_factory=_z)
    dogleg_dir: float = 1.0
    has_landing: bool = True
    leader_type: str = "straight"
    content_type: str = "mtext"
    text: str = ""
    content_pos: list = field(default_factory=_z)
    block: str = ""
    block_scale: float = 1.0
    block_rotation: float = 0.0
    block_attach: str = "extents"
    more_blocks: list = field(default_factory=list)
    arrow: Any = None
    arrow_size: Any = None
    text_height: Any = None
    landing_gap: Any = None
    dogleg_length: Any = None
    text_style: Any = None
    size_scale: float = 1.0

    def move_by(self, d) -> None:
        dx, dy = float(d[0]), float(d[1])
        self.landing = [self.landing[0] + dx, self.landing[1] + dy, 0.0]
        self.content_pos = [self.content_pos[0] + dx, self.content_pos[1] + dy, 0.0]
        for ld in self.leaders:
            ld["pts"] = [[p[0] + dx, p[1] + dy] for p in ld["pts"]]
        for mb in self.more_blocks:
            mb["pos"] = [mb["pos"][0] + dx, mb["pos"][1] + dy]

    def apply_transform(self, xf) -> None:
        self.landing = xf.pt(self.landing)
        self.content_pos = xf.pt(self.content_pos)
        for ld in self.leaders:
            ld["pts"] = [_pair(xf.pt(p)) for p in ld["pts"]]
        for mb in self.more_blocks:
            mb["pos"] = _pair(xf.pt(mb["pos"]))
        if xf.flip or xf.mode == "rotate":
            probe = xf.vec([self.dogleg_dir, 0.0])
            self.dogleg_dir = 1.0 if probe[0] >= 0 else -1.0
        self.size_scale *= xf.k
        self.block_scale *= xf.k
        if xf.mode == "rotate":
            self.block_rotation += xf.angle

    def size_of(self, name: str, style: dict, factor: float = 1.0) -> float:
        own = getattr(self, name)
        factor = factor * self.size_scale
        if own is not None:
            return float(own) * factor
        key = {"dogleg_length": "dogleg"}.get(name, name)
        return float((style or {}).get(key, 1.0)) * factor

    def leader_points(self) -> list:
        return [p for ld in self.leaders for p in ld["pts"]]

    def next_leader_id(self) -> int:
        return max([int(ld.get("id", 0)) for ld in self.leaders] + [0]) + 1

    def bounds(self):
        pts = self.leader_points() + [self.landing, self.content_pos]
        if self.has_landing and self.leaders:
            pts.append([self.landing[0] + self.dogleg_dir * float(self.dogleg_length or 0.0), self.landing[1]])
        return geom.bounds_of_points(pts)

    def snap_points(self):
        return [ld["pts"][0] for ld in self.leaders if ld["pts"]] + [self.content_pos]

    def valid(self):
        if len(self.leaders) > MAX_LEADERS or self.leader_type not in LEADER_TYPES or self.content_type not in CONTENT_TYPES:
            return False
        if any(len(ld["pts"]) < 2 or len(ld["pts"]) > MAX_POINTS for ld in self.leaders):
            return False
        if not self.leaders and self.content_type == "none":
            return False
        if self.leaders and self.leader_type == "none":
            return False
        return super().valid()


def landing_end(e: MLeader, style: dict, factor: float = 1.0) -> list:
    if not e.has_landing:
        return [e.landing[0], e.landing[1]]
    return [e.landing[0] + e.dogleg_dir * e.size_of("dogleg_length", style, factor), e.landing[1]]


def nearest_leader(e: MLeader, p) -> tuple:
    best, bi, bd = None, -1, float("inf")
    for i, ld in enumerate(e.leaders):
        pts = ld["pts"]
        for a, b in zip(pts, pts[1:]):
            d = seg_distance(p, a, b)
            if d < bd:
                best, bi, bd = ld, i, d
    return best, bi, bd


def seg_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    if n < 1e-18:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
