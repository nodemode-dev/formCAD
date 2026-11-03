from dataclasses import dataclass, field
from typing import ClassVar

from app.doc.entities import Entity, entity_kind


def _z() -> list:
    return [0.0, 0.0, 0.0]


def _p() -> list:
    return [0.0, 0.0]


def _show() -> dict:
    return {"hidden": True, "tangent": False, "silhouette": True, "seam": False, "hatch": True, "label": True}


def _source() -> dict:
    return {"doc": "", "component": "", "config": ""}


def _state() -> dict:
    return {"status": "empty", "message": "", "sig": "", "ms": 0.0, "mode_used": "", "built_rev": 0}


@entity_kind
@dataclass
class DrawView(Entity):
    kind: ClassVar[str] = "drawview"
    name: str = ""
    label: str = ""
    vtype: str = "base"
    source: dict = field(default_factory=_source)
    vnormal: list = field(default_factory=lambda: [0.0, -1.0, 0.0])
    vup: list = field(default_factory=lambda: [0.0, 0.0, 1.0])
    scale: float = 1.0
    scale_text: str = "1:1"
    position: list = field(default_factory=_p)
    origin: list = field(default_factory=_z)
    unit_mm: float = 1.0
    parent: int = 0
    align: str = ""
    section: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)
    broken: dict = field(default_factory=dict)
    crop: dict = field(default_factory=dict)
    show: dict = field(default_factory=_show)
    style: dict = field(default_factory=dict)
    mode: str = "exact"
    auto: bool = True
    flat: bool = False
    state: dict = field(default_factory=_state)
    cache: dict = field(default_factory=dict)

    def move_by(self, d) -> None:
        self.position = [self.position[0] + d[0], self.position[1] + d[1]]

    def half_size(self):
        b = (self.cache or {}).get("bounds")
        if not b:
            return [0.0, 0.0]
        k = float(self.scale) / (self.unit_mm or 1.0)
        return [(b[2] - b[0]) * k / 2.0, (b[3] - b[1]) * k / 2.0]

    def bounds(self):
        b = (self.cache or {}).get("bounds")
        k = float(self.scale) / (self.unit_mm or 1.0)
        if not b:
            return self.position[0], self.position[1], self.position[0], self.position[1]
        px, py = self.position[0], self.position[1]
        return px + b[0] * k, py + b[1] * k, px + b[2] * k, py + b[3] * k

    def snap_points(self):
        b = self.bounds()
        return [[(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0, 0.0]]

    def valid(self):
        return super().valid() and self.scale > 0.0 and self.vtype in ("base", "projected", "auxiliary", "section", "detail", "broken", "crop")
