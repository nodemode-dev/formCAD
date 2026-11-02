import math
import os
import re

MAX_USER = 512
MAX_FAMILIES = 1024
MAX_DASHES = 256
MAX_LINE = 4096
MAX_MAGNITUDE = 1_000_000.0
METRIC_FACTOR = 25.4
NAME_RE = re.compile(r"^[A-Za-z0-9_$\-]{1,64}$")


def fam(angle, ox, oy, dx, dy, dashes=()):
    return {"angle": float(angle), "origin": [float(ox), float(oy)], "offset": [float(dx), float(dy)], "dashes": [float(d) for d in dashes]}


def _n45(k):
    return (-k * math.sqrt(0.5), k * math.sqrt(0.5))


def _ansi34():
    out = []
    for i in range(4):
        nx, ny = _n45(0.1875 * i)
        out.append(fam(45, nx, ny, 0, 0.75))
    return out


def _honey():
    a = 0.1875
    dy = a * math.sqrt(3.0) / 2.0
    dx = 1.5 * a
    dash = [a, -2.0 * a]
    return [
        fam(0, a, 0, dx, dy, dash),
        fam(60, a * math.cos(math.radians(60)), a * math.sin(math.radians(60)), dx, dy, dash),
        fam(120, a * math.cos(math.radians(120)), a * math.sin(math.radians(120)), dx, dy, dash),
    ]


def _zig():
    s = 0.125 * math.sqrt(2.0)
    return [fam(45, 0, 0, s, -s, [s, -3.0 * s]), fam(-45, 0.125, 0.125, s, s, [s, -3.0 * s])]


def _ansi32():
    nx, ny = _n45(0.125)
    return [fam(45, 0, 0, 0, 0.375), fam(45, nx, ny, 0, 0.375)]


def _ansi33():
    nx, ny = _n45(0.125)
    return [fam(45, 0, 0, 0, 0.25), fam(45, nx, ny, 0, 0.25, [0.1875, -0.0625])]


def _ansi35():
    nx, ny = _n45(0.125)
    return [fam(45, 0, 0, 0, 0.25), fam(45, nx, ny, 0, 0.25, [0.3125, -0.0625, 0, -0.0625])]


def _earth():
    return [
        fam(0, 0, 0, 0, 0.375, [0.5, -0.25]),
        fam(0, 0.25, 0.125, 0, 0.375, [0.5, -0.25]),
        fam(0, 0.5, 0.25, 0, 0.375, [0.5, -0.25]),
        fam(90, 0.125, 0.0, 0.0, 0.75, [0.125, -0.625]),
    ]


def _grass():
    return [
        fam(90, 0, 0, 0.25, 0.25, [0.125, -0.375]),
        fam(60, 0.0625, 0, 0.25, 0.25, [0.125, -0.375]),
        fam(120, -0.0625, 0, 0.25, 0.25, [0.125, -0.375]),
    ]


def _conc():
    return [
        fam(50, 0, 0, 0.2, -0.1, [0.06, -0.43]),
        fam(355, 0.1, 0.07, 0.31, 0.21, [0.045, -0.5]),
        fam(100.4, 0.18, 0.12, -0.17, 0.27, [0.05, -0.41]),
        fam(0, 0, 0, 0.19, 0.31, [0.0, -0.37]),
    ]


def _sand():
    return [
        fam(37.5, 0, 0, 0.0905, -0.0675, [0, -0.17]),
        fam(7.5, 0, 0, 0.1033, 0.0577, [0, -0.19]),
        fam(127.5, 0.0, 0.0, 0.0905, 0.0675, [0, -0.17]),
    ]


LIBRARY = {
    "SOLID": [],
    "ANSI31": [fam(45, 0, 0, 0, 0.125)],
    "ANSI32": _ansi32(),
    "ANSI33": _ansi33(),
    "ANSI34": _ansi34(),
    "ANSI35": _ansi35(),
    "ANSI36": [fam(45, 0, 0, 0.25, 0.1875, [0.5, -0.125])],
    "ANSI37": [fam(45, 0, 0, 0, 0.125), fam(135, 0, 0, 0, 0.125)],
    "ANSI38": [fam(45, 0, 0, 0, 0.125), fam(135, 0, 0, 0, 0.375, [0.25, -0.125])],
    "LINE": [fam(0, 0, 0, 0, 0.125)],
    "NET": [fam(0, 0, 0, 0, 0.125), fam(90, 0, 0, 0, 0.125)],
    "NET3": [fam(0, 0, 0, 0, 0.125), fam(60, 0, 0, 0, 0.125), fam(120, 0, 0, 0, 0.125)],
    "DOTS": [fam(0, 0, 0, 0, 0.125, [0, -0.125])],
    "DASH": [fam(0, 0, 0, 0.125, 0.125, [0.125, -0.125])],
    "BRICK": [fam(0, 0, 0, 0, 0.25), fam(90, 0, 0, 0.25, 0.5, [0.25, -0.25])],
    "SQUARE": [fam(0, 0, 0, 0, 0.25, [0.125, -0.125]), fam(90, 0, 0, 0, 0.25, [0.125, -0.125])],
    "CROSS": [fam(0, -0.0625, 0, 0, 0.25, [0.125, -0.125]), fam(90, 0, -0.0625, 0, 0.25, [0.125, -0.125])],
    "EARTH": _earth(),
    "GRASS": _grass(),
    "HONEY": _honey(),
    "ZIGZAG": _zig(),
    "AR-CONC": _conc(),
    "AR-SAND": _sand(),
}

DESCRIPTIONS = {
    "SOLID": "Solid fill",
    "ANSI31": "Iron, brick, stone masonry",
    "ANSI32": "Steel",
    "ANSI33": "Bronze, brass, copper",
    "ANSI34": "Plastic, rubber",
    "ANSI35": "Fire brick, refractory material",
    "ANSI36": "Marble, slate, glass",
    "ANSI37": "Lead, zinc, magnesium, sound or heat or electric insulation",
    "ANSI38": "Aluminum",
    "LINE": "Horizontal lines",
    "NET": "Horizontal and vertical grid",
    "NET3": "Triangular grid at 60 degrees",
    "DOTS": "Dot grid",
    "DASH": "Staggered dashes",
    "BRICK": "Brick running bond",
    "SQUARE": "Dashed square grid",
    "CROSS": "Small crosses",
    "EARTH": "Earth or ground",
    "GRASS": "Grass tufts",
    "HONEY": "Honeycomb",
    "ZIGZAG": "Zigzag rows",
    "AR-CONC": "Concrete",
    "AR-SAND": "Sand",
}

NAMES = tuple(LIBRARY.keys())
USER: dict = {}
INFO = "These pattern definitions are FormCAD's own: original line families written for this program, not copies of any other product's pattern files."


class PatternError(Exception):
    pass


def lookup(name):
    n = str(name or "").strip().upper()
    if n in LIBRARY:
        return n, LIBRARY[n]
    if n in USER:
        return n, USER[n]["families"]
    return None, None


def is_solid(name) -> bool:
    return str(name or "").strip().upper() == "SOLID"


def known(name) -> bool:
    return lookup(name)[0] is not None


def families_of(hatch):
    if getattr(hatch, "pattern_lines", None):
        return [f for f in hatch.pattern_lines if isinstance(f, dict)]
    n, fams = lookup(hatch.pattern)
    if fams is None:
        return LIBRARY["ANSI31"]
    return fams


def parse_text(text):
    defs = {}
    order = []
    warnings = []
    cur = None
    for raw in str(text).splitlines():
        line = raw.strip()
        if len(raw) > MAX_LINE:
            warnings.append("A line longer than %d characters was skipped." % MAX_LINE)
            continue
        if not line or line.startswith(";"):
            continue
        if line.startswith("*"):
            head = line[1:]
            name, _, desc = head.partition(",")
            name = name.strip().upper()
            if not NAME_RE.match(name):
                warnings.append("Pattern name %r is not valid and was skipped." % name)
                cur = None
                continue
            cur = name
            if len(order) >= 4096:
                warnings.append("More than 4096 definitions; the rest were skipped.")
                cur = None
                continue
            defs[name] = {"description": desc.strip(), "families": []}
            if name not in order:
                order.append(name)
            continue
        if cur is None:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            warnings.append("Pattern %s: a line family needs angle, origin, offset: %r skipped." % (cur, line[:40]))
            continue
        try:
            vals = [float(p) for p in parts if p != ""]
        except ValueError:
            warnings.append("Pattern %s: a line has a value that is not a number and was skipped." % cur)
            continue
        if any(not math.isfinite(v) or abs(v) > MAX_MAGNITUDE for v in vals):
            warnings.append("Pattern %s: a value is out of range and the line was skipped." % cur)
            continue
        if len(defs[cur]["families"]) >= MAX_FAMILIES:
            warnings.append("Pattern %s has more than %d line families; the rest were skipped." % (cur, MAX_FAMILIES))
            continue
        dashes = vals[5:]
        if len(dashes) > MAX_DASHES:
            warnings.append("Pattern %s: a line family has more than %d dashes and was skipped." % (cur, MAX_DASHES))
            continue
        if abs(vals[4]) < 1e-12:
            warnings.append("Pattern %s: a line family with no perpendicular spacing was skipped." % cur)
            continue
        defs[cur]["families"].append(fam(vals[0], vals[1], vals[2], vals[3], vals[4], dashes))
    return defs, order, warnings


def load(source):
    text = source
    if "\n" not in source and "*" not in source[:2] and os.path.isfile(source):
        try:
            with open(source, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError as err:
            raise PatternError("The pattern file could not be read: %s" % err.strerror)
    defs, order, warnings = parse_text(text)
    added = []
    for name in order:
        rec = defs[name]
        if name in LIBRARY:
            warnings.append("%s is a built-in pattern; the built-in is kept." % name)
            continue
        if not rec["families"]:
            warnings.append("Pattern %s has no usable line families and was skipped." % name)
            continue
        if name not in USER and len(USER) >= MAX_USER:
            warnings.append("The limit of %d user patterns is reached; %s was skipped." % (MAX_USER, name))
            continue
        USER[name] = rec
        added.append(name)
    if not order:
        raise PatternError("No pattern definitions were found.")
    return {"added": added, "warnings": warnings}


def clear():
    n = len(USER)
    USER.clear()
    return n


def listing():
    return {"standard": list(NAMES), "descriptions": dict(DESCRIPTIONS), "user": sorted(USER.keys()), "info": INFO}


def scale_unit(metric: bool) -> float:
    return METRIC_FACTOR if metric else 1.0
