import math

from app.text import codes, place
from app.text.model import Sink, affine, compose, rotation


class Laid:
    def __init__(self, prims, box, bounds, origin, width, height):
        self.prims = prims
        self.box = box
        self.bounds = bounds
        self.origin = origin
        self.width = width
        self.height = height


def _run(fs, chars, h, wf, shear, fill):
    sink = Sink()
    cursor = 0.0
    ink_lo = 0.0
    ink_hi = 0.0
    last_trail = 0.0
    spans = []
    for ch, ul, ol, sk in chars:
        g = fs.glyph(ch)
        if g is None:
            continue
        place.emit(sink, fs, g, cursor, 0.0, h, wf, shear, 1.0, 1.0, None, fill)
        step = g.adv * h * wf
        if g.box[3] > g.box[1]:
            ink_lo = min(ink_lo, g.box[1] * h)
            ink_hi = max(ink_hi, g.box[3] * h)
        if ul or ol or sk:
            spans.append((cursor, cursor + step, ul, ol, sk))
        cursor += step
        last_trail = g.trail * h * wf
    width = max(cursor - last_trail, 0.0)
    merged = []
    for x0, x1, ul, ol, sk in spans:
        if merged and abs(merged[-1][1] - x0) < 1e-9 and merged[-1][2:] == (ul, ol, sk):
            merged[-1] = (merged[-1][0], x1, ul, ol, sk)
        else:
            merged.append((x0, x1, ul, ol, sk))
    ident = affine()
    for x0, x1, ul, ol, sk in merged:
        x1 = min(x1, width)
        for on, level in ((ul, place.UNDERLINE), (ol, place.OVERLINE), (sk, place.STRIKE)):
            if on:
                y = level * h
                sink.segment(x0, y, x1, y, None, ident)
                ink_lo = min(ink_lo, y)
                ink_hi = max(ink_hi, y)
    return sink, width, ink_lo, ink_hi


def layout(fs, text, height, wf, oblique, back, upside, halign, valign, position, align_point, rot, fill):
    chars = codes.decode(text)
    shear = place.shear_of(oblique)
    sink, width, lo, hi = _run(fs, chars, height, wf, shear, fill)
    h = height
    fitted = halign in (3, 5) and align_point is not None and width > 1e-12
    if fitted:
        dx = align_point[0] - position[0]
        dy = align_point[1] - position[1]
        dist = math.hypot(dx, dy)
        if dist > 1e-12:
            factor = dist / width
            if halign == 3:
                h = height * factor
            else:
                wf = wf * factor
            sink, width, lo, hi = _run(fs, chars, h, wf, shear, fill)
            rot = math.atan2(dy, dx)
        origin = (position[0], position[1])
        anchor = (0.0, 0.0)
    else:
        if halign in (1, 4):
            ax = width / 2.0
        elif halign == 2:
            ax = width
        else:
            ax = 0.0
        if halign == 4:
            ay = (lo + hi) / 2.0
        elif valign == 1:
            ay = -fs.desc * h
        elif valign == 2:
            ay = h / 2.0
        elif valign == 3:
            ay = h
        else:
            ay = 0.0
        anchor = (ax, ay)
        justified = halign != 0 or valign != 0
        pt = align_point if (justified and align_point is not None) else position
        origin = (pt[0], pt[1])
    mirror = affine(-1.0 if back else 1.0, 0.0, 0.0, -1.0 if upside else 1.0, 0.0, 0.0)
    m = compose(rotation(rot, origin[0], origin[1]), compose(mirror, affine(1, 0, 0, 1, -anchor[0], -anchor[1])))
    ys = [0.0, h, lo, hi]
    y_lo, y_hi = min(ys), max(ys)
    corners = [(0.0, y_lo), (width, y_lo), (width, y_hi), (0.0, y_hi)]
    box = [[m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] for x, y in corners]
    base = [m[4], m[5]]
    return Laid(sink.prims(m), box, sink.bounds(m), base, width, h)
