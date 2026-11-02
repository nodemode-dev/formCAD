import math

STANDARD = (
    "closed filled", "closed blank", "closed", "dot", "small dot", "blank dot", "oblique", "architectural tick", "open",
    "right-angle", "30-degree open", "origin indicator", "origin indicator 2", "small", "filled box", "blank box",
    "filled datum triangle", "blank datum triangle", "integral", "none",
)

BLOCK_NAMES = {
    "closed filled": "_CLOSEDFILLED", "closed blank": "_CLOSEDBLANK", "closed": "_CLOSED", "dot": "_DOT", "small dot": "_DOTSMALL",
    "blank dot": "_DOTBLANK", "oblique": "_OBLIQUE", "architectural tick": "_ARCHTICK", "open": "_OPEN", "right-angle": "_OPEN90",
    "30-degree open": "_OPEN30", "origin indicator": "_ORIGIN", "origin indicator 2": "_ORIGIN2", "small": "_SMALL",
    "filled box": "_BOXFILLED", "blank box": "_BOXBLANK", "filled datum triangle": "_DATUMFILLED", "blank datum triangle": "_DATUMBLANK",
    "integral": "_INTEGRAL", "none": "_NONE",
}

_ALIASES = {
    "dot small": "small dot", "dotsmall": "small dot", "dot blank": "blank dot", "dotblank": "blank dot", "box filled": "filled box",
    "boxfilled": "filled box", "box blank": "blank box", "boxblank": "blank box", "datum filled": "filled datum triangle",
    "datumfilled": "filled datum triangle", "datum blank": "blank datum triangle", "datumblank": "blank datum triangle",
    "archtick": "architectural tick", "open90": "right-angle", "right angle": "right-angle", "rightangle": "right-angle",
    "open30": "30-degree open", "30 degree open": "30-degree open", "origin": "origin indicator", "origin2": "origin indicator 2",
    "closedfilled": "closed filled", "closedblank": "closed blank",
}

_BY_BLOCK = {v.lstrip("_").lower(): k for k, v in BLOCK_NAMES.items()}


def canonical(name) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "closed filled"
    low = raw.lstrip("_").replace("_", " ").strip().lower()
    if low in BLOCK_NAMES:
        return low
    if low in _ALIASES:
        return _ALIASES[low]
    squeezed = low.replace(" ", "")
    if squeezed in _BY_BLOCK:
        return _BY_BLOCK[squeezed]
    if squeezed in _ALIASES:
        return _ALIASES[squeezed]
    return "closed filled"


def block_name(name) -> str:
    return BLOCK_NAMES[canonical(name)]


class Arrow:
    def __init__(self):
        self.fills = []
        self.polys = []
        self.circles = []
        self.segs = []
        self.trim = 0.0
        self.width = 0.0
        self.stroke = False


def _add(p, v, k):
    return (p[0] + v[0] * k, p[1] + v[1] * k)


def _mix(p, d, a, n, b):
    return (p[0] + d[0] * a + n[0] * b, p[1] + d[1] * a + n[1] * b)


def build(name, tip, direction, size, tick=False) -> Arrow:
    out = Arrow()
    d = direction
    n = (-d[1], d[0])
    s = float(size)
    kind = "oblique" if tick else canonical(name)
    if kind == "none" or s <= 0:
        return out
    out.width = s
    if kind in ("closed filled", "closed blank", "closed"):
        a = _mix(tip, d, -s, n, s / 6.0)
        b = _mix(tip, d, -s, n, -s / 6.0)
        if kind == "closed filled":
            out.fills.append([tip, a, b])
        else:
            out.polys.append(([tip, a, b], True))
        if kind == "closed blank":
            out.trim = s
        elif kind == "closed":
            out.segs.append((tip, _add(tip, d, -s)))
    elif kind in ("dot", "small dot", "blank dot"):
        r = s / 2.0 if kind != "small dot" else s / 4.0
        out.circles.append((tip, r, kind != "blank dot"))
        out.width = 2 * r
    elif kind in ("oblique", "architectural tick"):
        r = ((d[0] + n[0]) / math.sqrt(2.0), (d[1] + n[1]) / math.sqrt(2.0))
        half = s if tick else s / 2.0
        a = _add(tip, r, -half)
        b = _add(tip, r, half)
        out.stroke = True
        out.width = 0.0
        if kind == "architectural tick":
            w = max(s * 0.08, 1e-9)
            rn = (-r[1], r[0])
            out.fills.append([_add(a, rn, w), _add(b, rn, w), _add(b, rn, -w), _add(a, rn, -w)])
        else:
            out.segs.append((a, b))
    elif kind == "open":
        out.segs.append((tip, _mix(tip, d, -s, n, s / 6.0)))
        out.segs.append((tip, _mix(tip, d, -s, n, -s / 6.0)))
        out.segs.append((tip, _add(tip, d, -s)))
    elif kind == "right-angle":
        k = s / math.sqrt(2.0) / math.sqrt(2.0)
        out.segs.append((tip, _mix(tip, d, -k, n, k)))
        out.segs.append((tip, _mix(tip, d, -k, n, -k)))
    elif kind == "30-degree open":
        ang = math.radians(15.0)
        out.segs.append((tip, _mix(tip, d, -s * math.cos(ang), n, s * math.sin(ang))))
        out.segs.append((tip, _mix(tip, d, -s * math.cos(ang), n, -s * math.sin(ang))))
        out.segs.append((tip, _add(tip, d, -s)))
    elif kind in ("origin indicator", "origin indicator 2"):
        out.circles.append((tip, s / 2.0, False))
        if kind.endswith("2"):
            out.circles.append((tip, s / 4.0, False))
        else:
            out.segs.append((_add(tip, n, -s / 2.0), _add(tip, n, s / 2.0)))
        out.width = s
    elif kind == "small":
        out.circles.append((tip, s / 4.0, False))
        out.width = s / 2.0
    elif kind in ("filled box", "blank box"):
        h = s / 2.0
        pts = [_mix(tip, d, -h, n, -h), _mix(tip, d, h, n, -h), _mix(tip, d, h, n, h), _mix(tip, d, -h, n, h)]
        if kind == "filled box":
            out.fills.append(pts)
        else:
            out.polys.append((pts, True))
        out.trim = 0.0
    elif kind in ("filled datum triangle", "blank datum triangle"):
        pts = [_add(tip, n, s / 2.0), _add(tip, n, -s / 2.0), _add(tip, d, -s * 0.8660254)]
        if kind.startswith("filled"):
            out.fills.append(pts)
        else:
            out.polys.append((pts, True))
        out.trim = s * 0.8660254
    elif kind == "integral":
        pts = []
        for i in range(0, 13):
            t = i / 12.0
            along = (t - 0.5) * s
            side = 0.18 * s * math.sin(2.0 * math.pi * (t - 0.5))
            pts.append(_mix(tip, n, along, d, side))
        out.polys.append((pts, False))
        out.width = s * 0.4
    return out


def fit_width(name, size, tick=False) -> float:
    kind = "oblique" if tick else canonical(name)
    if kind in ("none", "oblique", "architectural tick", "integral") or size <= 0:
        return 0.0
    return float(size)
