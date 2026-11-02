import math

from app.dim import numfmt


class Block:
    def __init__(self):
        self.parts = []
        self.lines = []
        self.arcs = []
        self.width = 0.0
        self.top = 0.0
        self.bottom = 0.0
        self.height = 0.0
        self.center = (0.0, 0.0)
        self.rot = 0.0
        self.empty = True

    def half_height(self) -> float:
        return max(self.top, -self.bottom)

    def to_world(self, x: float, y: float):
        c, s = math.cos(self.rot), math.sin(self.rot)
        return (self.center[0] + x * c - y * s, self.center[1] + x * s + y * c)

    def corners(self):
        hw = self.width / 2.0
        return [self.to_world(-hw, self.bottom), self.to_world(hw, self.bottom), self.to_world(hw, self.top), self.to_world(-hw, self.top)]


def _merge(pieces):
    out = []
    for p in pieces:
        if p[0] == "t":
            if not p[1]:
                continue
            if out and out[-1][0] == "t":
                out[-1] = ("t", out[-1][1] + p[1])
                continue
        out.append(p)
    return out


def _row(parts, rules, pieces, x, y, height, frac_h, measure):
    prev_text = False
    for p in _merge(pieces):
        if p[0] == "t":
            w = measure(p[1], height)
            parts.append((p[1], x + w / 2.0, y, height))
            x += w
            prev_text = True
            continue
        num, den, diag = p[1], p[2], p[3]
        if prev_text:
            x += height * 0.2
        nw = measure(num, frac_h)
        dw = measure(den, frac_h)
        if diag:
            slash = frac_h * 0.3
            parts.append((num, x + nw / 2.0, y + frac_h * 0.45, frac_h))
            rules.append((x + nw - slash * 0.2, y - frac_h * 0.5, x + nw + slash, y + frac_h * 0.5))
            parts.append((den, x + nw + slash + dw / 2.0, y - frac_h * 0.45, frac_h))
            x += nw + slash + dw
        else:
            w = max(nw, dw) + height * 0.1
            parts.append((num, x + w / 2.0, y + frac_h * 0.6, frac_h))
            parts.append((den, x + w / 2.0, y - frac_h * 0.6, frac_h))
            rules.append((x, y, x + w, y))
            x += w
        prev_text = False
    return x


def build(content, V, height, measure, inspect=None, frame=False, gap=0.0) -> Block:
    blk = Block()
    if content is None or (not content.get("main") and not content.get("tol")):
        return blk
    blk.empty = False
    tfac = float(V.get("DIMTFAC", 1.0) or 1.0)
    frac_h = height * tfac if tfac > 0 else height
    parts, rules = [], []
    tol = content.get("tol")
    x = 0.0
    if tol and tol[0] == "lim":
        up = numfmt.plain(tol[1])
        lo = numfmt.plain(tol[2])
        w = max(measure(up, height), measure(lo, height))
        tg = height * 0.2
        parts.append((up, w / 2.0, height / 2.0 + tg / 2.0, height))
        parts.append((lo, w / 2.0, -height / 2.0 - tg / 2.0, height))
        x = w
    else:
        x = _row(parts, rules, content["main"], 0.0, 0.0, height, frac_h, measure)
        if tol and tol[0] == "sym":
            th = height * tfac if tfac > 0 else height
            txt = tol[1]
            w = measure(txt, th)
            x += height * 0.1
            parts.append((txt, x + w / 2.0, 0.0, th))
            x += w
        elif tol and tol[0] == "dev":
            th = height * tfac if tfac > 0 else height
            pt, mt = tol[1], tol[2]
            w = max(measure(pt, th), measure(mt, th))
            tg = th * 0.2
            just = int(V.get("DIMTOLJ", 1))
            if just == 0:
                low = -height / 2.0 + th / 2.0
                up = low + th + tg
            elif just == 2:
                up = height / 2.0 - th / 2.0
                low = up - th - tg
            else:
                up = (th + tg) / 2.0
                low = -up
            x += height * 0.1
            parts.append((pt, x + w / 2.0, up, th))
            parts.append((mt, x + w / 2.0, low, th))
            x += w
    alt = content.get("alt")
    if alt:
        x += height * 0.3
        x = _row(parts, rules, alt, x, 0.0, height, frac_h, measure)
    sym = content.get("arcsym")
    width = x
    if sym == "before":
        sw = height * 0.9
        parts_shift = sw + height * 0.2
        parts = [(t, cx + parts_shift, cy, h) for (t, cx, cy, h) in parts]
        rules = [(a + parts_shift, b, c + parts_shift, d) for (a, b, c, d) in rules]
        blk.arcs.append((sw / 2.0, -height * 0.05, sw * 0.62, math.radians(35), math.radians(145)))
        width += parts_shift
    elif sym == "above":
        sw = height * 0.9
        blk.arcs.append((width / 2.0, height * 0.55 - sw * 0.5 + height * 0.2, sw * 0.62, math.radians(35), math.radians(145)))
    ys_hi = [cy + h / 2.0 for (_t, _x, cy, h) in parts] + [0.0]
    ys_lo = [cy - h / 2.0 for (_t, _x, cy, h) in parts] + [0.0]
    top, bottom = max(ys_hi), min(ys_lo)
    if sym == "above":
        top = max(top, height * 0.9)
    shift = width / 2.0
    blk.parts = [(t, cx - shift, cy, h) for (t, cx, cy, h) in parts]
    blk.lines = [(a - shift, b, c - shift, d) for (a, b, c, d) in rules]
    blk.arcs = [(cx - shift, cy, r, a0, a1) for (cx, cy, r, a0, a1) in blk.arcs]
    blk.width = width
    blk.top = top
    blk.bottom = bottom
    blk.height = top - bottom
    pad = abs(gap)
    hw = width / 2.0
    if inspect and inspect.get("shape") in ("round", "angular", "none"):
        _inspect(blk, inspect, height, measure, pad)
    elif frame:
        l, r, t, b = -hw - pad, hw + pad, top + pad, bottom - pad
        blk.lines += [(l, b, r, b), (r, b, r, t), (r, t, l, t), (l, t, l, b)]
        blk.width = r - l - 2 * pad
    return blk


def _inspect(blk, ins, height, measure, pad):
    hw = blk.width / 2.0
    top, bottom = blk.top + pad, blk.bottom - pad
    mid = (top + bottom) / 2.0
    half = (top - bottom) / 2.0
    label = str(ins.get("label") or "")
    rate = str(ins.get("rate") or "")
    left = -hw - pad
    right = hw + pad
    cells = []
    if label:
        lw = measure(label, height) + 2 * pad
        cells.append(("label", left - lw, left, label))
        left -= lw
    if rate:
        rw = measure(rate, height) + 2 * pad
        cells.append(("rate", right, right + rw, rate))
        right += rw
    for kind, x0, x1, txt in cells:
        blk.parts.append((txt, (x0 + x1) / 2.0, 0.0, height))
        blk.lines.append((x0 if kind == "rate" else x1, bottom, x0 if kind == "rate" else x1, top))
    if ins["shape"] == "round":
        blk.lines += [(left, bottom, right, bottom), (left, top, right, top)]
        blk.arcs.append((left, mid, half, math.pi / 2.0, 3.0 * math.pi / 2.0))
        blk.arcs.append((right, mid, half, -math.pi / 2.0, math.pi / 2.0))
    elif ins["shape"] == "angular":
        blk.lines += [(left, mid, left + half, top), (left + half, top, right - half, top), (right - half, top, right, mid), (right, mid, right - half, bottom), (right - half, bottom, left + half, bottom), (left + half, bottom, left, mid)]
    else:
        blk.lines += [(left, bottom, right, bottom), (right, bottom, right, top), (right, top, left, top), (left, top, left, bottom)]
    blk.width = right - left - 2 * pad
