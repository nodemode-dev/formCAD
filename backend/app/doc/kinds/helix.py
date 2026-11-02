import math
from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom, nurbs
from app.doc.entities import Entity, entity_kind

POINTS_PER_TURN = 40
MIN_POINTS_PER_TURN = 6
FIT_BUDGET = 1900
MAX_TURNS = 500.0


def _z() -> list:
    return [0.0, 0.0, 0.0]


@entity_kind
@dataclass
class Helix(Entity):
    kind: ClassVar[str] = "helix"
    POINTS: ClassVar[tuple] = ("center",)
    POINT_LISTS: ClassVar[tuple] = ("control_points",)
    center: list = field(default_factory=_z)
    base_radius: float = 1.0
    top_radius: float = 1.0
    height: float = 1.0
    turns: float = 3.0
    start_angle: float = 0.0
    ccw: bool = True
    constrain: str = "turns"
    degree: int = 3
    knots: list = field(default_factory=list)
    control_points: list = field(default_factory=list)

    def rebuild(self) -> None:
        per = min(POINTS_PER_TURN, max(MIN_POINTS_PER_TURN, FIT_BUDGET // max(int(math.ceil(self.turns)), 1)))
        n = max(int(math.ceil(self.turns * per)), 2)
        sgn = 1.0 if self.ccw else -1.0
        cz = self.center[2] if len(self.center) > 2 else 0.0
        pts = []
        for i in range(n + 1):
            f = i / n
            a = self.start_angle + sgn * geom.TAU * self.turns * f
            r = self.base_radius + (self.top_radius - self.base_radius) * f
            pts.append([self.center[0] + r * math.cos(a), self.center[1] + r * math.sin(a), cz + self.height * f])
        da = sgn * geom.TAU * self.turns
        dr = self.top_radius - self.base_radius

        def tangent(f):
            a = self.start_angle + da * f
            r = self.base_radius + dr * f
            return [dr * math.cos(a) - r * da * math.sin(a), dr * math.sin(a) + r * da * math.cos(a), self.height]

        curve, _flat = nurbs.fit(pts, nurbs.KNOT_UNIFORM, False, tangent(0.0), tangent(1.0))
        self.degree = curve.degree
        self.knots = list(curve.knots)
        self.control_points = [list(p) for p in curve.ctrl]

    def curve(self) -> nurbs.Curve:
        return nurbs.Curve(self.degree, list(self.knots), [list(p) for p in self.control_points], [], False)

    def turn_height(self) -> float:
        return self.height / self.turns if self.turns else 0.0

    def bounds(self):
        r = max(abs(self.base_radius), abs(self.top_radius))
        return self.center[0] - r, self.center[1] - r, self.center[0] + r, self.center[1] + r

    def snap_points(self):
        pts = self.control_points
        return [pts[0], pts[-1]] if pts else []

    def valid(self):
        return super().valid() and self.base_radius > 0 and self.top_radius >= 0 and 0 < self.turns <= MAX_TURNS and bool(self.control_points)
