import copy
import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_from_dict, entity_kind

HARD_LIMIT = 10_000_000
DISPLAY_LIMIT = 20000
SHAPES = ("rect", "polar", "path")


def _z() -> list:
    return [0.0, 0.0, 0.0]


def frame_matrix(d, rot, about):
    if not rot or about is None:
        return (1.0, 0.0, 0.0, 1.0, float(d[0]), float(d[1]))
    c, s = math.cos(rot), math.sin(rot)
    ex = about[0] - (c * about[0] - s * about[1])
    ey = about[1] - (s * about[0] + c * about[1])
    return (c, s, -s, c, ex + c * d[0] - s * d[1], ey + s * d[0] + c * d[1])


def key_text(key) -> str:
    return "%d,%d,%d" % tuple(int(v) for v in key)


def key_of(value) -> tuple:
    if isinstance(value, str):
        parts = [p for p in value.replace(" ", "").split(",") if p != ""]
    else:
        parts = list(value)
    nums = [int(p) for p in parts]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _xf_dicts(dicts, xf):
    from app.cmd import grips

    out = []
    for data in dicts:
        e = entity_from_dict(data)
        grips.transform(e, xf)
        out.append(e.to_dict())
    return out


@entity_kind
@dataclass
class AssocArray(Entity):
    kind: ClassVar[str] = "assoc_array"
    POINTS: ClassVar[tuple] = ("base", "center")
    shape: str = "rect"
    source: list = field(default_factory=list)
    base: list = field(default_factory=_z)
    columns: int = 4
    rows: int = 3
    levels: int = 1
    column_spacing: float = 1.0
    row_spacing: float = 1.0
    level_spacing: float = 1.0
    row_elevation: float = 0.0
    axis_angle: float = 0.0
    center: list = field(default_factory=_z)
    axis: list = field(default_factory=list)
    items: int = 6
    fill_angle: float = geom.TAU
    rotate_items: bool = True
    path: dict = field(default_factory=dict)
    path_method: str = "count"
    path_spacing: float = 1.0
    align: bool = True
    replacements: list = field(default_factory=list)
    overrides: list = field(default_factory=list)
    editing: Any = None

    def move_by(self, d) -> None:
        super().move_by(d)
        v = [d[0], d[1], d[2] if len(d) > 2 else 0.0]
        self.axis = [_shift(p, v) for p in self.axis]
        for data in self.source:
            _shift_dict(data, v)
        for rep in self.replacements:
            rep["base"] = _shift(rep["base"], v)
            for data in rep["objects"]:
                _shift_dict(data, v)
        if self.path.get("entity"):
            _shift_dict(self.path["entity"], v)

    def apply_xf(self, xf) -> None:
        self.base = xf.pt(self.base)
        self.center = xf.pt(self.center)
        self.axis = [xf.pt(p) for p in self.axis]
        self.source = _xf_dicts(self.source, xf)
        for rep in self.replacements:
            rep["base"] = xf.pt(rep["base"])
            rep["objects"] = _xf_dicts(rep["objects"], xf)
        if self.path.get("entity"):
            self.path["entity"] = _xf_dicts([self.path["entity"]], xf)[0]
            self.path["length"] = self.path.get("length", 0.0) * xf.k
        self.axis_angle = xf.ang(self.axis_angle)
        k = xf.k
        self.column_spacing *= k
        self.row_spacing *= k
        self.level_spacing *= k
        self.row_elevation *= k
        self.path_spacing *= k
        if xf.flip:
            self.row_spacing = -self.row_spacing
            self.fill_angle = -self.fill_angle

    def grip_points(self) -> list:
        out = [("base", self.base, "base")]
        if self.shape == "polar":
            out.append(("center", self.center, "center"))
        return out

    def stretch_grip(self, gid, t) -> None:
        if gid == "base":
            self.base = [t[0], t[1], self.base[2] if len(self.base) > 2 else 0.0]
        elif gid == "center":
            self.center = [t[0], t[1], self.center[2] if len(self.center) > 2 else 0.0]

    def source_entities(self) -> list:
        return [entity_from_dict(copy.deepcopy(d)) for d in self.source]

    def replacement_for(self, key):
        for rep in self.replacements:
            if tuple(rep["item"]) == tuple(key):
                return rep
        return None

    def override_for(self, key):
        for ov in self.overrides:
            if tuple(ov["item"]) == tuple(key):
                return ov
        return None

    def path_count(self) -> int:
        if self.path_method == "spacing":
            length = float(self.path.get("length", 0.0))
            sp = abs(float(self.path_spacing))
            return int(length / sp + 1e-9) + 1 if sp > geom.EPS else 1
        return max(int(self.items), 1)

    def count(self) -> int:
        lv = max(int(self.levels), 1)
        if self.shape == "rect":
            return max(int(self.columns), 1) * max(int(self.rows), 1) * lv
        if self.shape == "polar":
            return max(int(self.items), 1) * max(int(self.rows), 1) * lv
        return self.path_count() * lv

    def total_objects(self) -> int:
        return self.count() * max(len(self.source), 1)

    def keys(self):
        lv = max(int(self.levels), 1)
        if self.shape == "rect":
            ni, nj = max(int(self.columns), 1), max(int(self.rows), 1)
        elif self.shape == "polar":
            ni, nj = max(int(self.items), 1), max(int(self.rows), 1)
        else:
            ni, nj = self.path_count(), 1
        for k in range(lv):
            for j in range(nj):
                for i in range(ni):
                    yield (i, j, k)

    def frames(self):
        if self.shape == "polar":
            yield from self._polar_frames()
        elif self.shape == "path":
            yield from self._path_frames()
        else:
            yield from self._rect_frames()

    def _rect_frames(self):
        ca, sa = math.cos(self.axis_angle), math.sin(self.axis_angle)
        cs, rs, ls, el = self.column_spacing, self.row_spacing, self.level_spacing, self.row_elevation
        for key in self.keys():
            i, j, k = key
            yield key, [i * cs * ca - j * rs * sa, i * cs * sa + j * rs * ca, k * ls + j * el], 0.0, None

    def polar_step(self) -> float:
        n = max(int(self.items), 1)
        if n == 1:
            return 0.0
        full = abs(abs(self.fill_angle) - geom.TAU) < 1e-9
        return self.fill_angle / n if full else self.fill_angle / (n - 1)

    def _polar_frames(self):
        step = self.polar_step()
        bx, by = self.base[0], self.base[1]
        cx, cy = self.center[0], self.center[1]
        vx, vy = bx - cx, by - cy
        r = math.hypot(vx, vy)
        ux, uy = (vx / r, vy / r) if r > geom.EPS else (1.0, 0.0)
        rs, ls, el = self.row_spacing, self.level_spacing, self.row_elevation
        for key in self.keys():
            i, j, k = key
            bjx, bjy = bx + j * rs * ux, by + j * rs * uy
            dz = k * ls + j * el
            th = i * step
            if self.rotate_items:
                yield key, [bjx - bx, bjy - by, dz], th, [cx, cy]
            else:
                c, s = math.cos(th), math.sin(th)
                px = cx + c * (bjx - cx) - s * (bjy - cy)
                py = cy + s * (bjx - cx) + c * (bjy - cy)
                yield key, [px - bx, py - by, dz], 0.0, None

    def _path_frames(self):
        from app.doc import curvepath

        data = self.path.get("entity")
        cur = curvepath.build(entity_from_dict(copy.deepcopy(data))) if data else None
        n = self.path_count()
        bx, by = self.base[0], self.base[1]
        if cur is None or cur.length <= 0:
            return
        closed = bool(cur.closed)
        if self.path_method == "spacing":
            step = abs(float(self.path_spacing))
        elif n <= 1:
            step = 0.0
        else:
            step = cur.length / n if closed else cur.length / (n - 1)
        first_tan = None
        for key in self.keys():
            i, _j, k = key
            pt, tan = cur.at(min(i * step, cur.length))
            if first_tan is None:
                first_tan = tan
            rot = (tan - first_tan) if self.align else 0.0
            yield key, [pt[0] - bx, pt[1] - by, k * self.level_spacing], rot, [pt[0], pt[1]]

    def item_objects(self, key) -> list:
        rep = self.replacement_for(key)
        if rep is not None:
            return [entity_from_dict(copy.deepcopy(d)) for d in rep["objects"]]
        return self.source_entities()

    def frame_of(self, key):
        want = tuple(key)
        for k, d, rot, about in self.frames():
            if k == want:
                return d, rot, about
        return None

    def realize(self, objs, d, rot, about) -> list:
        from app.cmd import grips

        out = []
        for e in objs:
            e.move_by(d)
            if rot and about is not None:
                grips.transform(e, grips.Xf("rotate", about, rot))
            out.append(e)
        return out

    def unrealize(self, objs, d, rot, about) -> list:
        from app.cmd import grips

        out = []
        for e in objs:
            if rot and about is not None:
                grips.transform(e, grips.Xf("rotate", about, -rot))
            e.move_by([-d[0], -d[1], -d[2] if len(d) > 2 else 0.0])
            out.append(e)
        return out

    def explode_entities(self, limit: int = DISPLAY_LIMIT) -> list:
        out = []
        n = 0
        for key, d, rot, about in self.frames():
            if self.editing and tuple(self.editing.get("item", ())) == tuple(key):
                continue
            ov = self.override_for(key)
            if ov is not None and ov.get("visible") is False:
                continue
            n += 1
            if n > limit:
                break
            for e in self.realize(self.item_objects(key), d, rot, about):
                if ov:
                    apply_override(e, ov)
                out.append(e)
        return out

    def bounds(self):
        srcs = self.source_entities()
        box = None
        for e in srcs:
            box = geom.union_bounds(box, e.bounds())
        if box is None:
            return None
        corners = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]
        out = None
        if self.shape == "rect":
            frames = self._rect_extremes()
        else:
            frames = [(k, d, r, a) for k, d, r, a in self.frames()]
        for _k, d, rot, about in frames:
            m = frame_matrix(d, rot, about)
            pts = [[m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5]] for p in corners]
            out = geom.union_bounds(out, geom.bounds_of_points(pts))
        for rep in self.replacements:
            fr = self.frame_of(rep["item"])
            if fr is None:
                continue
            for data in rep["objects"]:
                eb = entity_from_dict(copy.deepcopy(data)).bounds()
                if eb is None:
                    continue
                m = frame_matrix(*fr)
                pts = [[m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] for x, y in ((eb[0], eb[1]), (eb[2], eb[1]), (eb[2], eb[3]), (eb[0], eb[3]))]
                out = geom.union_bounds(out, geom.bounds_of_points(pts))
        return out

    def _rect_extremes(self):
        ca, sa = math.cos(self.axis_angle), math.sin(self.axis_angle)
        ci = {0, max(int(self.columns), 1) - 1}
        rj = {0, max(int(self.rows), 1) - 1}
        out = []
        for i in ci:
            for j in rj:
                out.append(((i, j, 0), [i * self.column_spacing * ca - j * self.row_spacing * sa, i * self.column_spacing * sa + j * self.row_spacing * ca, 0.0], 0.0, None))
        return out

    def snap_points(self):
        out = []
        for n, (_k, d, rot, about) in enumerate(self.frames()):
            if n >= 2000:
                break
            m = frame_matrix(d, rot, about)
            out.append([m[0] * self.base[0] + m[2] * self.base[1] + m[4], m[1] * self.base[0] + m[3] * self.base[1] + m[5], 0.0])
        return out

    def valid(self):
        if not super().valid():
            return False
        if self.shape not in SHAPES or not self.source:
            return False
        if self.count() > HARD_LIMIT:
            return False
        if self.shape == "path" and not self.path.get("entity"):
            return False
        return True


def _shift(p, d) -> list:
    out = list(p)
    out[0] = p[0] + d[0]
    out[1] = p[1] + d[1]
    if len(p) > 2:
        out[2] = p[2] + (d[2] if len(d) > 2 else 0.0)
    return out


def _shift_dict(data, vec) -> None:
    e = entity_from_dict(data)
    e.move_by(vec)
    data.clear()
    data.update(e.to_dict())


def apply_override(e, ov) -> None:
    for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency"):
        if name in ov:
            setattr(e, name, ov[name])
