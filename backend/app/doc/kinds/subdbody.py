from dataclasses import dataclass, field
from typing import ClassVar

from app.doc.entities import Entity, entity_kind

MAX_FACES = 20000
MAX_VERTICES = 60000
DISPLAYS = ("smooth", "box", "both")


def _o() -> list:
    return [0.0, 0.0, 0.0]


def _sym() -> dict:
    return {"mirror": [], "radial": None, "tol": 1e-6}


@entity_kind
@dataclass
class SubdBody(Entity):
    kind: ClassVar[str] = "subdbody"
    name: str = ""
    source: dict = field(default_factory=dict)
    v: list = field(default_factory=list)
    f: list = field(default_factory=list)
    crease: list = field(default_factory=list)
    sym: dict = field(default_factory=_sym)
    display: str = "both"
    level: int = 3
    version: int = 1
    rgb: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    offset: list = field(default_factory=_o)
    extent: list = field(default_factory=list)

    @property
    def face_ids(self) -> list:
        return list(range(1, len(self.f) + 1))

    @property
    def edge_ids(self) -> list:
        return list(range(1, int(self.summary.get("edges", 0)) + 1))

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
        return super().valid() and len(self.f) <= MAX_FACES and len(self.v) <= MAX_VERTICES and self.display in DISPLAYS and 1 <= int(self.level) <= 4
