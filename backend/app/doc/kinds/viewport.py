from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind


def _z() -> list:
    return [0.0, 0.0, 0.0]


@entity_kind
@dataclass
class Viewport(Entity):
    kind: ClassVar[str] = "viewport"
    POINTS: ClassVar[tuple] = ("center",)
    center: list = field(default_factory=_z)
    width: float = 100.0
    height: float = 80.0
    view_center: list = field(default_factory=_z)
    scale: float = 1.0
    on: bool = True
    locked: bool = False

    def corners(self) -> list:
        cx, cy = self.center[0], self.center[1]
        w, h = self.width / 2.0, self.height / 2.0
        return [[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h]]

    def bounds(self):
        return geom.bounds_of_points(self.corners())

    def snap_points(self):
        return [self.center] + self.corners()

    def valid(self):
        return super().valid() and self.width > geom.EPS and self.height > geom.EPS and self.scale > geom.EPS
