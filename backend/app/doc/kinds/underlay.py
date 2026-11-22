from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind


def _corners():
    return [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


@entity_kind
@dataclass
class Underlay(Entity):
    kind: ClassVar[str] = "underlay"
    POINT_LISTS: ClassVar[tuple] = ("corners",)
    source: str = "image"
    path: str = ""
    name: str = ""
    page: int = 1
    pixels: list = field(default_factory=lambda: [1, 1])
    corners: list = field(default_factory=_corners)
    clip: list = field(default_factory=list)
    clip_on: bool = True
    fade: int = 0
    show: bool = True

    def u(self):
        o, r = self.corners[0], self.corners[1]
        return [r[0] - o[0], r[1] - o[1]]

    def v(self):
        o, t = self.corners[0], self.corners[2]
        return [t[0] - o[0], t[1] - o[1]]

    def at(self, s, t):
        o = self.corners[0]
        u, v = self.u(), self.v()
        return [o[0] + u[0] * s + v[0] * t, o[1] + u[1] * s + v[1] * t]

    def outline(self):
        return [self.at(0.0, 0.0), self.at(1.0, 0.0), self.at(1.0, 1.0), self.at(0.0, 1.0)]

    def clip_ring(self):
        if not self.clip or not self.clip_on:
            return None
        return [self.at(float(p[0]), float(p[1])) for p in self.clip]

    def to_local(self, p):
        o = self.corners[0]
        u, v = self.u(), self.v()
        det = u[0] * v[1] - u[1] * v[0]
        if abs(det) < 1e-300:
            return None
        dx, dy = p[0] - o[0], p[1] - o[1]
        return [(dx * v[1] - dy * v[0]) / det, (u[0] * dy - u[1] * dx) / det]

    def bounds(self):
        return geom.bounds_of_points(self.clip_ring() or self.outline())

    def snap_points(self):
        return [[p[0], p[1], 0.0] for p in self.outline()]

    def valid(self):
        if not super().valid() or len(self.corners) != 3 or self.source not in ("image", "pdf"):
            return False
        u, v = self.u(), self.v()
        if abs(u[0] * v[1] - u[1] * v[0]) <= geom.EPS:
            return False
        if self.clip and (len(self.clip) < 3 or any(len(p) < 2 for p in self.clip)):
            return False
        return 0 <= int(self.fade) <= 100 and int(self.page) >= 1
