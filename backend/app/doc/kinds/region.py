import math
from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom
from app.doc import planar
from app.doc.entities import Entity, _shift, entity_kind

MAX_LOOPS = 10000


@entity_kind
@dataclass
class Region(Entity):
    kind: ClassVar[str] = "region"
    loops: list = field(default_factory=list)

    def move_by(self, d):
        for loop in self.loops:
            for v in loop.get("vertices", []):
                v["p"] = _shift(v["p"], d)

    def rings(self):
        return [planar.flatten_loop(loop.get("vertices", [])) for loop in self.loops]

    def bounds(self):
        pts = [p for ring in self.rings() for p in ring]
        return geom.bounds_of_points(pts)

    def area(self) -> float:
        total = 0.0
        for loop in self.loops:
            a = abs(planar.loop_area(loop.get("vertices", [])))
            total += a if loop.get("outer", True) else -a
        return total

    def perimeter(self) -> float:
        return sum(planar.loop_perimeter(loop.get("vertices", [])) for loop in self.loops)

    def centroid(self):
        sx = sy = tot = 0.0
        for loop in self.loops:
            verts = loop.get("vertices", [])
            a = abs(planar.loop_area(verts))
            sign = 1.0 if loop.get("outer", True) else -1.0
            ring = planar.flatten_loop(verts)
            cx = cy = 0.0
            twice = 0.0
            n = len(ring)
            for i in range(n):
                p, q = ring[i], ring[(i + 1) % n]
                w = p[0] * q[1] - q[0] * p[1]
                twice += w
                cx += (p[0] + q[0]) * w
                cy += (p[1] + q[1]) * w
            if abs(twice) < 1e-300:
                continue
            cx /= 3.0 * twice
            cy /= 3.0 * twice
            sx += sign * a * cx
            sy += sign * a * cy
            tot += sign * a
        if abs(tot) < 1e-300:
            return None
        return [sx / tot, sy / tot]

    def contains(self, x, y) -> bool:
        hit = False
        for ring in self.rings():
            if planar.point_in_ring(x, y, ring):
                hit = not hit
        return hit

    def snap_points(self):
        out = []
        for loop in self.loops:
            for v in loop.get("vertices", []):
                out.append([v["p"][0], v["p"][1], 0.0])
        return out

    def valid(self):
        if not super().valid() or not self.loops or len(self.loops) > MAX_LOOPS:
            return False
        if any(len(loop.get("vertices", [])) < 2 for loop in self.loops):
            return False
        return math.isfinite(self.area()) and self.area() > geom.EPS
