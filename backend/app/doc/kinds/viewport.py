import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

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
    vp_id: int = 0
    frozen: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    clip: Any = None
    clip_source: int = 0
    anno_scale: str = ""

    @property
    def display_locked(self) -> bool:
        return self.locked

    @display_locked.setter
    def display_locked(self, value) -> None:
        self.locked = bool(value)

    @property
    def view_height(self) -> float:
        return self.height * self.scale

    def corners(self) -> list:
        cx, cy = self.center[0], self.center[1]
        w, h = self.width / 2.0, self.height / 2.0
        return [[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h]]

    def outline(self) -> list:
        if self.clip:
            return [{"p": [v["p"][0], v["p"][1]], "bulge": float(v.get("bulge", 0.0) or 0.0)} for v in self.clip]
        return [{"p": c, "bulge": 0.0} for c in self.corners()]

    def outline_points(self) -> list:
        from app.display import flatten

        verts = [[v["p"][0], v["p"][1], v["bulge"], 0.0, 0.0] for v in self.outline()]
        return [[p[0], p[1]] for p in flatten.poly_pts(verts, True)]

    def outline_box(self):
        if not self.clip:
            return geom.bounds_of_points(self.corners())
        box = None
        n = len(self.clip)
        for i, v in enumerate(self.clip):
            a, b = v["p"], self.clip[(i + 1) % n]["p"]
            arc = geom.bulge_to_arc(a, b, float(v.get("bulge", 0.0) or 0.0))
            seg = geom.arc_bounds(arc[0], arc[1], arc[2], arc[3]) if arc else geom.bounds_of_points([a, b])
            box = geom.union_bounds(box, seg)
        return box

    def fit_to_outline(self) -> None:
        if not self.clip:
            return
        box = self.outline_box()
        self.recentre([(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0, 0.0])
        self.width = box[2] - box[0]
        self.height = box[3] - box[1]

    def recentre(self, centre) -> None:
        keep = self.to_model(centre)
        self.center = [centre[0], centre[1], 0.0]
        self.view_center = keep

    def to_model(self, p) -> list:
        return [self.view_center[0] + (p[0] - self.center[0]) * self.scale, self.view_center[1] + (p[1] - self.center[1]) * self.scale, 0.0]

    def to_paper(self, p) -> list:
        return [self.center[0] + (p[0] - self.view_center[0]) / self.scale, self.center[1] + (p[1] - self.view_center[1]) / self.scale, 0.0]

    def contains(self, p) -> bool:
        x, y = p[0], p[1]
        cx, cy = self.center[0], self.center[1]
        if abs(x - cx) > self.width / 2.0 + geom.EPS or abs(y - cy) > self.height / 2.0 + geom.EPS:
            return False
        if not self.clip:
            return True
        pts = self.outline_points()
        inside = False
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
                inside = not inside
        return inside

    def move_by(self, d) -> None:
        self.center = [self.center[0] + d[0], self.center[1] + d[1], self.center[2] if len(self.center) > 2 else 0.0]
        if self.clip:
            for v in self.clip:
                v["p"] = [v["p"][0] + d[0], v["p"][1] + d[1]]

    def bounds(self):
        return self.outline_box()

    def snap_points(self):
        pts = [self.center]
        if self.clip:
            pts += [[v["p"][0], v["p"][1], 0.0] for v in self.clip]
        else:
            pts += self.corners()
        return pts

    def grip_points(self) -> list:
        if self.clip:
            return [("c", self.center, "center")] + [("v%d" % i, [v["p"][0], v["p"][1]], "vertex") for i, v in enumerate(self.clip)]
        c = self.corners()
        return [("c", self.center, "center")] + [("k%d" % i, c[i], "corner") for i in range(4)]

    def stretch_grip(self, gid: str, t) -> None:
        if gid == "c":
            self.move_by([t[0] - self.center[0], t[1] - self.center[1]])
            return
        if self.clip and gid.startswith("v"):
            self.clip[int(gid[1:])]["p"] = [t[0], t[1]]
            self.fit_to_outline()
            return
        i = int(gid[1:])
        c = self.corners()
        opp = c[(i + 2) % 4]
        x0, x1 = sorted((opp[0], t[0]))
        y0, y1 = sorted((opp[1], t[1]))
        if x1 - x0 < geom.EPS or y1 - y0 < geom.EPS:
            from app.cmd.grips import GripError

            raise GripError("The viewport would have no size.")
        self.recentre([(x0 + x1) / 2.0, (y0 + y1) / 2.0, 0.0])
        self.width, self.height = x1 - x0, y1 - y0

    def apply_transform(self, xf) -> None:
        from app.cmd.grips import GripError

        mode = xf.mode
        if mode == "scale":
            self.center = xf.pt(self.center)
            self.width *= xf.k
            self.height *= xf.k
            if self.clip:
                for v in self.clip:
                    v["p"] = list(xf.pt(v["p"]))[:2]
            return
        if mode == "mirror":
            self.center = xf.pt(self.center)
            if self.clip:
                for v in self.clip:
                    v["p"] = list(xf.pt(v["p"]))[:2]
                    v["bulge"] = -float(v.get("bulge", 0.0) or 0.0)
            return
        turns = xf.angle / (math.pi / 2.0)
        if abs(turns - round(turns)) > 1e-9:
            raise GripError("A viewport only turns by quarter turns.")
        quarter = int(round(turns)) % 4
        self.center = xf.pt(self.center)
        if quarter % 2 == 1:
            self.width, self.height = self.height, self.width
        if self.clip:
            for v in self.clip:
                v["p"] = list(xf.pt(v["p"]))[:2]

    def valid(self):
        return super().valid() and self.width > geom.EPS and self.height > geom.EPS and self.scale > geom.EPS and (not self.clip or len(self.clip) >= 2)
