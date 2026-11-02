import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind

MAX_ROWS = 2000
MAX_COLS = 200
MAX_CELLS = 1_000_000
MAX_PARTS = 1000
DIRECTIONS = ("right", "left", "down")


def _z() -> list:
    return [0.0, 0.0, 0.0]


def new_cell() -> dict:
    return {"text": "", "formula": "", "type": "text", "span": [1, 1], "style": "", "height": None, "align": None, "format": None, "fill": None, "borders": {}}


@entity_kind
@dataclass
class TableObject(Entity):
    kind: ClassVar[str] = "table"
    POINTS: ClassVar[tuple] = ("position",)
    position: list = field(default_factory=_z)
    style: str = "Standard"
    col_widths: list = field(default_factory=list)
    row_heights: list = field(default_factory=list)
    title: bool = True
    header: bool = True
    cells: list = field(default_factory=list)
    row_styles: list = field(default_factory=list)
    text_height: Any = None
    text_scale: float = 1.0
    rotation: float = 0.0
    breaks: dict = field(default_factory=dict)
    link: Any = None

    def rows(self) -> int:
        return len(self.row_heights)

    def cols(self) -> int:
        return len(self.col_widths)

    def width(self) -> float:
        return float(sum(self.col_widths))

    def height(self) -> float:
        return float(sum(self.row_heights))

    def apply_transform(self, xf) -> None:
        self.position = xf.pt(self.position)
        if xf.mode == "rotate":
            self.rotation += xf.angle
        if xf.k != 1.0:
            self.col_widths = [w * xf.k for w in self.col_widths]
            self.row_heights = [h * xf.k for h in self.row_heights]
            self.text_scale *= xf.k

    def cover(self) -> dict:
        out = {}
        for r, row in enumerate(self.cells):
            for c, cell in enumerate(row):
                rs, cs = cell.get("span", [1, 1])
                if rs > 1 or cs > 1:
                    for rr in range(r, min(r + rs, len(self.cells))):
                        for cc in range(c, min(c + cs, len(row))):
                            if (rr, cc) != (r, c):
                                out[(rr, cc)] = (r, c)
        return out

    def cut_rows(self) -> set:
        blocked = set()
        for r, row in enumerate(self.cells):
            for cell in row:
                rs = cell.get("span", [1, 1])[0]
                for k in range(r + 1, min(r + rs, len(self.cells))):
                    blocked.add(k)
        return {r for r in range(1, self.rows()) if r not in blocked}

    def parts(self) -> list:
        n = self.rows()
        b = self.breaks or {}
        full = [{"rows": list(range(n)), "dx": 0.0, "dy": 0.0}]
        limit = float(b.get("max_height") or 0.0)
        manual = [float(h) for h in (b.get("heights") or []) if float(h) > 0]
        if not b.get("enabled") or n < 2 or (limit <= 0 and not manual):
            return full
        top = (1 if self.title else 0) + (1 if self.header else 0)
        top = min(top, n - 1)
        repeat_top = bool(b.get("repeat_top")) and top > 0
        repeat_bottom = bool(b.get("repeat_bottom"))
        cuts = self.cut_rows()
        hs = self.row_heights
        groups = []
        start = 0
        while start < n and len(groups) < MAX_PARTS:
            cap = manual[len(groups)] if len(groups) < len(manual) else (limit or 1e300)
            extra = 0.0
            if groups and repeat_top:
                extra += sum(hs[:top])
            end = start
            used = extra
            last_cut = None
            while end < n:
                need = hs[end]
                reserve = hs[n - 1] if repeat_bottom and end < n - 1 else 0.0
                if end > start and (used + need + reserve > cap + 1e-9):
                    break
                used += need
                end += 1
                if end in cuts or end == n:
                    last_cut = end
            if end < n and last_cut is not None and last_cut < end and last_cut > start:
                end = last_cut
            if end <= start:
                end = start + 1
            groups.append((start, end))
            start = end
        if len(groups) < 2:
            return full
        out = []
        offsets = [list(o) for o in (b.get("offsets") or [])]
        spacing = float(b.get("spacing") or 0.0)
        direction = b.get("direction") if b.get("direction") in DIRECTIONS else "right"
        shift_y = 0.0
        for k, (a, z) in enumerate(groups):
            rows = list(range(a, z))
            if k > 0 and repeat_top:
                rows = list(range(top)) + rows
            if repeat_bottom and z < n:
                rows = rows + [n - 1]
            ph = sum(hs[r] for r in rows)
            if direction == "right":
                dx, dy = k * (self.width() + spacing), 0.0
            elif direction == "left":
                dx, dy = -k * (self.width() + spacing), 0.0
            else:
                dx, dy = 0.0, -shift_y
                shift_y += ph + spacing
            if k < len(offsets):
                dx += float(offsets[k][0])
                dy += float(offsets[k][1])
            out.append({"rows": rows, "dx": dx, "dy": dy})
        return out

    def frame_corners(self) -> list:
        pts = []
        px, py = self.position[0], self.position[1]
        w = self.width()
        for part in self.parts():
            h = sum(self.row_heights[r] for r in part["rows"])
            x0, y0 = px + part["dx"], py + part["dy"]
            pts.extend([[x0, y0], [x0 + w, y0], [x0 + w, y0 - h], [x0, y0 - h]])
        if self.rotation:
            c, s = math.cos(self.rotation), math.sin(self.rotation)
            pts = [[px + (p[0] - px) * c - (p[1] - py) * s, py + (p[0] - px) * s + (p[1] - py) * c] for p in pts]
        return pts

    def bounds(self):
        return geom.bounds_of_points(self.frame_corners())

    def snap_points(self):
        out = []
        pts = self.frame_corners()
        for i in range(0, len(pts), 4):
            out.extend(pts[i : i + 4])
        return out

    def valid(self):
        n, m = self.rows(), self.cols()
        if not (1 <= n <= MAX_ROWS and 1 <= m <= MAX_COLS) or n * m > MAX_CELLS:
            return False
        if len(self.cells) != n or any(len(r) != m for r in self.cells):
            return False
        if any(not (w > 0) or not (h > 0) for w, h in [(w, 1.0) for w in self.col_widths] + [(1.0, h) for h in self.row_heights]):
            return False
        return super().valid()
