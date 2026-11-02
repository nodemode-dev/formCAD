from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind


@entity_kind
@dataclass
class Leader(Entity):
    kind: ClassVar[str] = "leader"
    POINT_LISTS: ClassVar[tuple] = ("points",)
    points: list = field(default_factory=list)
    arrowhead: bool = True
    spline: bool = False
    style: str = "Standard"
    arrow_size: float = 0.0

    def apply_transform(self, xf) -> None:
        self.points = [xf.pt(p) for p in self.points]
        self.arrow_size *= xf.k

    def bounds(self):
        return geom.bounds_of_points(self.points)

    def snap_points(self):
        return list(self.points)

    def valid(self):
        return super().valid() and len(self.points) >= 2 and any(geom.dist(self.points[i], self.points[i + 1]) > geom.EPS for i in range(len(self.points) - 1))
