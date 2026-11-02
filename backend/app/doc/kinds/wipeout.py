from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind


@entity_kind
@dataclass
class Wipeout(Entity):
    kind: ClassVar[str] = "wipeout"
    POINT_LISTS: ClassVar[tuple] = ("points",)
    points: list = field(default_factory=list)
    frame: Any = None

    def bounds(self):
        return geom.bounds_of_points(self.points)

    def snap_points(self):
        return list(self.points)

    def area(self) -> float:
        pts = self.points
        s = 0.0
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            s += a[0] * b[1] - b[0] * a[1]
        return s / 2.0

    def valid(self):
        return super().valid() and len(self.points) >= 3 and abs(self.area()) > geom.EPS
