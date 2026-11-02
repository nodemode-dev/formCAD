import json
import math
from pathlib import Path

import numpy as np

from app.text.model import Glyph, box_of

DATA = Path(__file__).resolve().parents[1] / "data" / "fonts" / "formcad-stroke.json"
ARC_STEP = 12.0


def _arc(token):
    cx, cy, rx, ry, a0, a1 = (float(v) for v in token[1:].split(","))
    n = max(2, int(math.ceil(abs(a1 - a0) / ARC_STEP)))
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        out.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return out


def parse_stroke(text):
    pts = []
    for token in text.split():
        if token[0] == "@":
            pts.extend(_arc(token))
        else:
            x, y = token.split(",")
            pts.append((float(x), float(y)))
    clean = []
    for p in pts:
        if not clean or abs(p[0] - clean[-1][0]) > 1e-9 or abs(p[1] - clean[-1][1]) > 1e-9:
            clean.append(p)
    if len(clean) == 1:
        clean.append((clean[0][0] + 0.001, clean[0][1]))
    return clean


class StrokeFont:
    is_stroke = True
    name = "formcad-stroke"

    def __init__(self, path=DATA):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.cap = float(raw["cap"])
        self.gap = float(raw["gap"])
        self.desc = float(raw["descent"]) / self.cap
        self.glyphs = {}
        self.raw = raw["glyphs"]
        self.em_over_cap = 1.0

    def has(self, ch):
        return ch in self.raw

    def glyph(self, ch):
        g = self.glyphs.get(ch)
        if g is not None:
            return g
        rec = self.raw.get(ch)
        if rec is None:
            return None
        k = 1.0 / self.cap
        strokes = [np.array(parse_stroke(s), dtype=float) * k for s in rec["s"]]
        g = Glyph((rec["w"] + self.gap) * k, self.gap * k, strokes=strokes, box=box_of(strokes))
        self.glyphs[ch] = g
        return g

    def missing(self):
        g = self.glyphs.get("\0")
        if g is None:
            w, h = 0.5, 0.7
            box = np.array([[0.08, 0.0], [0.08 + w, 0.0], [0.08 + w, h], [0.08, h], [0.08, 0.0]], dtype=float)
            g = Glyph(0.8, 0.0, strokes=[box], box=box_of([box]))
            self.glyphs["\0"] = g
        return g


_default = None


def default():
    global _default
    if _default is None:
        _default = StrokeFont()
    return _default
