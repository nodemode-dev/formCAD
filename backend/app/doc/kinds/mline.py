import math
from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind

MAX_VERTICES = 100000
MAX_CUTS = 1000
MITRE_LIMIT = 6.0
EPS = 1e-12


def _style() -> dict:
    return {"name": "STANDARD", "description": "", "elements": [{"offset": 0.5, "color": 256, "linetype": "BYLAYER"}, {"offset": -0.5, "color": 256, "linetype": "BYLAYER"}], "start_cap": {"line": False, "outer_arc": False, "inner_arcs": False, "angle": 90.0}, "end_cap": {"line": False, "outer_arc": False, "inner_arcs": False, "angle": 90.0}, "joints": False, "fill": None}


@entity_kind
@dataclass
class MLine(Entity):
    kind: ClassVar[str] = "mline"
    VERTEX_LISTS: ClassVar[tuple] = ("vertices",)
    style: str = "STANDARD"
    style_def: dict = field(default_factory=_style)
    scale: float = 1.0
    justification: int = 0
    closed: bool = False
    no_start_cap: bool = False
    no_end_cap: bool = False
    vertices: list = field(default_factory=list)

    def elements(self) -> list:
        return sorted(self.style_def.get("elements", []), key=lambda e: -float(e.get("offset", 0.0)))

    def reference(self) -> float:
        offs = [float(e.get("offset", 0.0)) for e in self.style_def.get("elements", [])]
        if not offs:
            return 0.0
        if self.justification == 0:
            return max(offs)
        if self.justification == 2:
            return min(offs)
        return 0.0

    def count(self) -> int:
        return len(self.vertices)

    def segment_count(self) -> int:
        n = len(self.vertices)
        return n if self.closed and n > 2 else max(n - 1, 0)

    def pts(self) -> list:
        return [v["p"] for v in self.vertices]

    def bounds(self):
        pts = [p for k in range(len(self.elements())) for p in (element_point(self, k, i) for i in range(len(self.vertices)))]
        return geom.bounds_of_points(pts or self.pts())

    def snap_points(self):
        return self.pts()

    def valid(self):
        n = len(self.vertices)
        if n < 2 or n > MAX_VERTICES or not self.style_def.get("elements"):
            return False
        if len(self.style_def["elements"]) > 16:
            return False
        if any(len(v.get("cuts", [])) > MAX_CUTS for v in self.vertices):
            return False
        if not all(geom.dist(self.vertices[i]["p"], self.vertices[(i + 1) % n]["p"]) > geom.EPS for i in range(self.segment_count())):
            return False
        return super().valid()


def seg_dirs(ent: MLine) -> list:
    n = len(ent.vertices)
    out = []
    for i in range(ent.segment_count()):
        a, b = ent.vertices[i]["p"], ent.vertices[(i + 1) % n]["p"]
        d = geom.dist(a, b)
        out.append(((b[0] - a[0]) / d, (b[1] - a[1]) / d, d) if d > 0 else (1.0, 0.0, 0.0))
    return out


def mitre(ent: MLine, i: int, dirs=None) -> list:
    dirs = dirs or seg_dirs(ent)
    n = len(ent.vertices)
    segs = len(dirs)
    closed = ent.closed and n > 2
    if closed:
        d_in, d_out = dirs[(i - 1) % segs], dirs[i % segs]
    elif i == 0:
        d_in = d_out = dirs[0]
    elif i == n - 1:
        d_in = d_out = dirs[-1]
    else:
        d_in, d_out = dirs[i - 1], dirs[i]
    n_in = (-d_in[1], d_in[0])
    n_out = (-d_out[1], d_out[0])
    mx, my = n_in[0] + n_out[0], n_in[1] + n_out[1]
    m = math.hypot(mx, my)
    if m < 1e-9:
        return [n_in[0], n_in[1]]
    mx, my = mx / m, my / m
    c = mx * n_in[0] + my * n_in[1]
    f = 1.0 / c if c > 1.0 / MITRE_LIMIT else MITRE_LIMIT
    return [mx * f, my * f]


def lateral(ent: MLine, k: int) -> float:
    off = float(ent.elements()[k].get("offset", 0.0))
    return (off - ent.reference()) * ent.scale


def cap_of(ent: MLine, end: bool) -> dict:
    return ent.style_def.get("end_cap" if end else "start_cap") or {}


def cap_active(ent: MLine, end: bool) -> bool:
    if ent.closed and len(ent.vertices) > 2:
        return False
    if (ent.no_end_cap if end else ent.no_start_cap):
        return False
    c = cap_of(ent, end)
    return bool(c.get("line") or c.get("outer_arc") or c.get("inner_arcs"))


def element_point(ent: MLine, k: int, i: int, dirs=None, cache=None) -> list:
    p = ent.vertices[i]["p"]
    m = cache[i] if cache is not None else mitre(ent, i, dirs)
    lat = lateral(ent, k)
    x, y = p[0] + m[0] * lat, p[1] + m[1] * lat
    n = len(ent.vertices)
    if not (ent.closed and n > 2) and i in (0, n - 1):
        end = i == n - 1
        if cap_active(ent, end):
            ang = float(cap_of(ent, end).get("angle", 90.0))
            if abs(ang - 90.0) > 1e-9:
                d = (dirs or seg_dirs(ent))[-1 if end else 0]
                els = len(ent.elements())
                mid = (lateral(ent, 0) + lateral(ent, els - 1)) / 2.0
                sh = (lat - mid) / math.tan(math.radians(ang))
                s = 1.0 if end else -1.0
                x += d[0] * sh * s
                y += d[1] * sh * s
    return [x, y]


def free_intervals(cuts: list, k: int, length: float) -> list:
    spans = sorted((max(0.0, float(c["start"])), min(length, float(c["end"]))) for c in cuts if int(c["element"]) == k and float(c["end"]) > float(c["start"]))
    out = []
    pos = 0.0
    for a, b in spans:
        if a > pos + EPS:
            out.append((pos / length, a / length))
        pos = max(pos, b)
    if pos < length - EPS:
        out.append((pos / length, 1.0))
    return out


def element_runs(ent: MLine) -> list:
    dirs = seg_dirs(ent)
    n = len(ent.vertices)
    cache = [mitre(ent, i, dirs) for i in range(n)]
    out = []
    for k in range(len(ent.elements())):
        runs = []
        cur = None
        tail = False
        first_zero = False
        for i in range(len(dirs)):
            a = element_point(ent, k, i, dirs, cache)
            b = element_point(ent, k, (i + 1) % n, dirs, cache)
            length = dirs[i][2]
            ivs = free_intervals(ent.vertices[i].get("cuts", []), k, length)
            ended = False
            for t0, t1 in ivs:
                pa = [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0]
                pb = [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1]
                if t0 <= EPS and tail and cur is not None:
                    cur.append(pb)
                else:
                    cur = [pa, pb]
                    runs.append(cur)
                    if i == 0 and t0 <= EPS:
                        first_zero = True
                ended = t1 >= 1.0 - EPS
                tail = ended
            if not ivs:
                tail = False
        closed = False
        if ent.closed and n > 2:
            has_cuts = any(int(c["element"]) == k for v in ent.vertices for c in v.get("cuts", []))
            if not has_cuts and len(runs) == 1:
                closed = True
                runs[0].pop()
            elif len(runs) > 1 and first_zero and tail:
                last = runs.pop()
                runs[0] = last + runs[0][1:]
        out.append([{"pts": r, "closed": closed and len(runs) == 1} for r in runs])
    return out


def cap_shapes(ent: MLine) -> list:
    out = []
    n = len(ent.vertices)
    els = len(ent.elements())
    if n < 2 or els < 2:
        return out
    dirs = seg_dirs(ent)
    cache = [mitre(ent, i, dirs) for i in range(n)]
    for end in (False, True):
        if not cap_active(ent, end):
            continue
        spec = cap_of(ent, end)
        i = n - 1 if end else 0
        d = dirs[-1 if end else 0]
        pts = [element_point(ent, k, i, dirs, cache) for k in range(els)]
        if spec.get("line"):
            out.append(("line", pts[0], pts[-1], 0.0))
        pairs = []
        if spec.get("outer_arc"):
            pairs.append((0, els - 1))
        if spec.get("inner_arcs"):
            a, b = 1, els - 2
            while a < b:
                pairs.append((a, b))
                a += 1
                b -= 1
        for a, b in pairs:
            v = (pts[b][0] - pts[a][0], pts[b][1] - pts[a][1])
            right = (v[1], -v[0])
            out_dir = (d[0], d[1]) if end else (-d[0], -d[1])
            sign = 1.0 if right[0] * out_dir[0] + right[1] * out_dir[1] > 0 else -1.0
            out.append(("arc", pts[a], pts[b], sign))
    return out


def joint_lines(ent: MLine) -> list:
    if not ent.style_def.get("joints"):
        return []
    n = len(ent.vertices)
    els = len(ent.elements())
    if els < 2:
        return []
    dirs = seg_dirs(ent)
    cache = [mitre(ent, i, dirs) for i in range(n)]
    rng = range(n) if ent.closed and n > 2 else range(1, n - 1)
    return [(element_point(ent, 0, i, dirs, cache), element_point(ent, els - 1, i, dirs, cache)) for i in rng]


def fill_ring(ent: MLine):
    fill = ent.style_def.get("fill")
    if fill is None or fill == "":
        return None
    n = len(ent.vertices)
    els = len(ent.elements())
    if n < 2 or els < 2:
        return None
    dirs = seg_dirs(ent)
    cache = [mitre(ent, i, dirs) for i in range(n)]
    top = [element_point(ent, 0, i, dirs, cache) for i in range(n)]
    bot = [element_point(ent, els - 1, i, dirs, cache) for i in range(n)]
    if ent.closed and n > 2:
        return [top + [top[0]], bot + [bot[0]]]
    return [top + bot[::-1]]


def locate(ent: MLine, pt) -> tuple:
    n = len(ent.vertices)
    best = None
    pos = 0.0
    for i, (dx, dy, length) in enumerate(seg_dirs(ent)):
        a = ent.vertices[i]["p"]
        t = ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy)
        tc = min(max(t, 0.0), length)
        q = [a[0] + dx * tc, a[1] + dy * tc]
        d = math.hypot(pt[0] - q[0], pt[1] - q[1])
        if best is None or d < best[0]:
            best = (d, i, tc, q, pos + tc)
        pos += length
    return best
