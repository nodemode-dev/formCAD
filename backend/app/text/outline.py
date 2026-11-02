import logging
import math
import threading

import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from app.text import tri
from app.text.model import Glyph, box_of

logging.getLogger("fontTools").setLevel(logging.ERROR)
LOCK = threading.RLock()
FLATNESS = 0.0007
MAX_POINTS = 16384


class FlatPen(BasePen):
    def __init__(self, glyph_set, tol):
        super().__init__(glyph_set)
        self.tol = tol
        self.rings = []
        self.cur = None

    def _moveTo(self, pt):
        self.cur = [pt]

    def _lineTo(self, pt):
        self.cur.append(pt)

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        dev = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1]) / 4.0
        n = max(1, min(32, int(math.ceil(math.sqrt(dev / self.tol)))))
        for i in range(1, n + 1):
            t = i / n
            u = 1 - t
            self.cur.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        d1 = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
        d2 = math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1])
        dev = 0.75 * max(d1, d2)
        n = max(1, min(40, int(math.ceil(math.sqrt(dev / self.tol)))))
        for i in range(1, n + 1):
            t = i / n
            u = 1 - t
            a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
            self.cur.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))

    def _closePath(self):
        if self.cur and len(self.cur) >= 3:
            self.rings.append(self.cur)
        self.cur = None

    def _endPath(self):
        self._closePath()


def _norm(text):
    return "".join(c for c in str(text).lower() if c.isalnum())


class OutlineFont:
    is_stroke = False

    def __init__(self, path, index=0):
        self.path = str(path)
        self.index = index
        with LOCK:
            self.ttf = TTFont(self.path, fontNumber=index, lazy=True) if self.path.lower().endswith((".ttc", ".otc")) else TTFont(self.path, lazy=True)
            self.cmap = self.ttf.getBestCmap() or {}
            self.upem = float(self.ttf["head"].unitsPerEm)
            self.glyph_set = self.ttf.getGlyphSet()
            self.hmtx = self.ttf["hmtx"]
            self.cap = self._cap_height()
            hhea = self.ttf["hhea"]
            self.desc = abs(float(hhea.descent)) / self.cap
            style = int(getattr(self.ttf["head"], "macStyle", 0))
            self.bold = bool(style & 1)
            self.italic = bool(style & 2)
        self.em_over_cap = self.upem / self.cap
        self.cache = {}
        self.id_cache = {}
        self._hb = None
        self.name = _norm(self.family())

    def family(self):
        try:
            names = self.ttf["name"]
            for nid in (16, 1):
                rec = names.getName(nid, 3, 1, 0x409) or names.getName(nid, 1, 0, 0)
                if rec is not None:
                    return str(rec)
        except Exception:
            pass
        return ""

    def _cap_height(self):
        try:
            os2 = self.ttf["OS/2"]
            v = float(getattr(os2, "sCapHeight", 0) or 0)
            if v > 0:
                return v
        except Exception:
            pass
        name = self.cmap.get(ord("H"))
        if name:
            pen = FlatPen(self.glyph_set, self.upem * FLATNESS)
            try:
                self.glyph_set[name].draw(pen)
                ys = [p[1] for r in pen.rings for p in r]
                if ys and max(ys) > 0:
                    return float(max(ys))
            except Exception:
                pass
        return self.upem * 0.7

    def has(self, ch):
        return ord(ch) in self.cmap

    def glyph(self, ch):
        g = self.cache.get(ch)
        if g is not None:
            return g
        name = self.cmap.get(ord(ch))
        if name is None:
            return None
        with LOCK:
            pen = FlatPen(self.glyph_set, self.cap * FLATNESS)
            try:
                self.glyph_set[name].draw(pen)
            except Exception:
                pen.rings = []
            try:
                adv = float(self.hmtx[name][0])
            except Exception:
                adv = self.upem * 0.5
        k = 1.0 / self.cap
        total = sum(len(r) for r in pen.rings)
        rings = pen.rings if total <= MAX_POINTS else []
        contours = [np.array(r, dtype=float) * k for r in rings]
        g = Glyph(adv * k, 0.0, contours=contours, box=box_of(contours), build_tris=_build)
        g.src = (self, self.ttf.getGlyphID(name))
        self.cache[ch] = g
        return g

    def missing(self):
        return None

    def shaper(self):
        if self._hb is None:
            import uharfbuzz as hb

            with LOCK:
                blob = hb.Blob.from_file_path(self.path)
                face = hb.Face(blob, self.index)
                self._hb = hb.Font(face)
        return self._hb

    def glyph_by_id(self, gid):
        g = self.id_cache.get(gid)
        if g is not None:
            return g
        with LOCK:
            order = self.ttf.getGlyphOrder()
            name = order[gid] if 0 <= gid < len(order) else None
            pen = FlatPen(self.glyph_set, self.cap * FLATNESS)
            if name is not None:
                try:
                    self.glyph_set[name].draw(pen)
                except Exception:
                    pen.rings = []
        k = 1.0 / self.cap
        total = sum(len(r) for r in pen.rings)
        rings = pen.rings if total <= MAX_POINTS else []
        contours = [np.array(r, dtype=float) * k for r in rings]
        g = Glyph(0.0, 0.0, contours=contours, box=box_of(contours), build_tris=_build)
        g.src = (self, int(gid))
        self.id_cache[gid] = g
        return g


def _build(contours):
    return tri.triangulate([c.tolist() for c in contours])
