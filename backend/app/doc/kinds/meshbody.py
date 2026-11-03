from dataclasses import dataclass, field
from typing import ClassVar

from app.doc.entities import Entity, entity_kind

MAX_TRIANGLES = 20_000_000


def _o() -> list:
    return [0.0, 0.0, 0.0]


@entity_kind
@dataclass
class MeshBody(Entity):
    kind: ClassVar[str] = "meshbody"
    name: str = ""
    source: dict = field(default_factory=dict)
    blob: str = ""
    version: int = 1
    rgb: list = field(default_factory=list)
    face_ids: list = field(default_factory=list)
    edge_ids: list = field(default_factory=list)
    lineage: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    offset: list = field(default_factory=_o)
    extent: list = field(default_factory=list)
    points_only: bool = False

    def move_by(self, d) -> None:
        self.offset = [self.offset[0] + d[0], self.offset[1] + d[1], self.offset[2] + (d[2] if len(d) > 2 else 0.0)]

    def bounds(self):
        if len(self.extent) != 4:
            return None
        ox, oy = self.offset[0], self.offset[1]
        return self.extent[0] + ox, self.extent[1] + oy, self.extent[2] + ox, self.extent[3] + oy

    def snap_points(self):
        return []

    def valid(self):
        return super().valid() and bool(self.blob) and int(self.summary.get("triangles", 0)) <= MAX_TRIANGLES
