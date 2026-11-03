import math

CATEGORIES = ("form", "profile", "orientation", "location", "runout")


def _arrow(tip, d, size, half):
    ux, uy = d
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    return [tip, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)]


def _straightness():
    return [("l", -0.42, 0, 0.42, 0)]


def _flatness():
    return [("p", [(-0.42, -0.2), (0.18, -0.2), (0.42, 0.2), (-0.18, 0.2)], True)]


def _circularity():
    return [("c", 0, 0, 0.36)]


def _cylindricity():
    return [("c", 0, 0, 0.24), ("l", -0.46, -0.28, -0.16, 0.28), ("l", 0.16, -0.28, 0.46, 0.28)]


def _profile_line():
    return [("a", 0, -0.12, 0.4, 0.0, math.pi)]


def _profile_surface():
    return [("a", 0, -0.12, 0.4, 0.0, math.pi), ("l", -0.4, -0.12, 0.4, -0.12)]


def _angularity():
    a = math.radians(30.0)
    return [("l", -0.42, -0.28, 0.42, -0.28), ("l", -0.42, -0.28, -0.42 + 0.84 * math.cos(a), -0.28 + 0.84 * math.sin(a))]


def _perpendicularity():
    return [("l", -0.42, -0.3, 0.42, -0.3), ("l", 0, -0.3, 0, 0.4)]


def _parallelism():
    return [("l", -0.32, -0.3, -0.04, 0.3), ("l", 0.04, -0.3, 0.32, 0.3)]


def _position():
    return [("c", 0, 0, 0.3), ("l", -0.46, 0, 0.46, 0), ("l", 0, -0.46, 0, 0.46)]


def _concentricity():
    return [("c", 0, 0, 0.15), ("c", 0, 0, 0.32)]


def _symmetry():
    return [("l", -0.28, 0.22, 0.28, 0.22), ("l", -0.42, 0, 0.42, 0), ("l", -0.28, -0.22, 0.28, -0.22)]


def _circular_runout():
    d = (math.sqrt(0.5), math.sqrt(0.5))
    return [("l", -0.36, -0.36, 0.2, 0.2), ("f", _arrow((0.4, 0.4), d, 0.3, 0.1))]


def _total_runout():
    d = (math.sqrt(0.5), math.sqrt(0.5))
    perp = (-d[1], d[0])
    out = []
    for off in (-0.17, 0.17):
        bx, by = perp[0] * off, perp[1] * off
        out.append(("l", -0.3 + bx, -0.3 + by, 0.12 + bx, 0.12 + by))
        out.append(("f", _arrow((0.36 + bx, 0.36 + by), d, 0.28, 0.1)))
    out.append(("l", perp[0] * -0.17, perp[1] * -0.17, perp[0] * 0.17, perp[1] * 0.17))
    return out


CHARACTERISTICS = {
    "straightness": {"name": "Straightness", "category": "form", "glyph": _straightness},
    "flatness": {"name": "Flatness", "category": "form", "glyph": _flatness},
    "circularity": {"name": "Circularity", "category": "form", "glyph": _circularity},
    "cylindricity": {"name": "Cylindricity", "category": "form", "glyph": _cylindricity},
    "profile_line": {"name": "Profile of a line", "category": "profile", "glyph": _profile_line},
    "profile_surface": {"name": "Profile of a surface", "category": "profile", "glyph": _profile_surface},
    "angularity": {"name": "Angularity", "category": "orientation", "glyph": _angularity},
    "perpendicularity": {"name": "Perpendicularity", "category": "orientation", "glyph": _perpendicularity},
    "parallelism": {"name": "Parallelism", "category": "orientation", "glyph": _parallelism},
    "position": {"name": "Position", "category": "location", "glyph": _position},
    "concentricity": {"name": "Concentricity", "category": "location", "glyph": _concentricity},
    "symmetry": {"name": "Symmetry", "category": "location", "glyph": _symmetry},
    "circular_runout": {"name": "Circular runout", "category": "runout", "glyph": _circular_runout},
    "total_runout": {"name": "Total runout", "category": "runout", "glyph": _total_runout},
}

ALIASES = {"parallel": "parallelism", "perpendicular": "perpendicularity", "angular": "angularity", "flat": "flatness", "straight": "straightness", "round": "circularity", "roundness": "circularity", "cylindrical": "cylindricity", "line profile": "profile_line", "surface profile": "profile_surface", "profile of a line": "profile_line", "profile of a surface": "profile_surface", "true position": "position", "runout": "circular_runout", "circular runout": "circular_runout", "total runout": "total_runout", "profile_of_a_line": "profile_line", "profile_of_a_surface": "profile_surface"}

MODIFIERS = {"": "", "m": "M", "l": "L", "none": "", "mmc": "M", "lmc": "L"}
ZONES = ("none", "dia", "sdia")
DATUM_LETTERS_EXCLUDED = "IOQ"


class GlyphError(Exception):
    pass


def key_of(name) -> str:
    raw = str(name or "").strip().lower().replace("-", "_")
    if raw in CHARACTERISTICS:
        return raw
    spaced = raw.replace("_", " ")
    if spaced in ALIASES:
        return ALIASES[spaced]
    if raw in ALIASES:
        return ALIASES[raw]
    under = spaced.replace(" ", "_")
    if under in CHARACTERISTICS:
        return under
    for k, v in CHARACTERISTICS.items():
        if v["name"].lower() == spaced:
            return k
    raise GlyphError("Characteristic %s is not known." % name)


def modifier_of(value) -> str:
    key = str(value or "").strip().lower()
    if key not in MODIFIERS:
        raise GlyphError("The material condition modifier is M, L or none.")
    return MODIFIERS[key]


def zone_of(value) -> str:
    key = str(value or "none").strip().lower()
    if key in ("", "none", "no"):
        return "none"
    if key in ("dia", "diameter", "d"):
        return "dia"
    if key in ("sdia", "sphere", "spherical", "s"):
        return "sdia"
    raise GlyphError("The tolerance zone is none, dia or sdia.")


def datum_letter(value) -> str:
    s = str(value or "").strip().upper()
    if not s or len(s) > 2 or not s.isalpha():
        raise GlyphError("A datum is one or two letters.")
    if any(c in DATUM_LETTERS_EXCLUDED for c in s):
        raise GlyphError("Datum letters leave out I, O and Q.")
    return s


def scaled(strokes, size, cx=0.0, cy=0.0):
    out = []
    for s in strokes:
        t = s[0]
        if t == "l":
            out.append(("l", cx + s[1] * size, cy + s[2] * size, cx + s[3] * size, cy + s[4] * size))
        elif t == "c":
            out.append(("c", cx + s[1] * size, cy + s[2] * size, s[3] * size))
        elif t == "a":
            out.append(("a", cx + s[1] * size, cy + s[2] * size, s[3] * size, s[4], s[5]))
        elif t == "p":
            out.append(("p", [(cx + x * size, cy + y * size) for x, y in s[1]], s[2]))
        elif t == "f":
            out.append(("f", [(cx + x * size, cy + y * size) for x, y in s[1]]))
    return out


def glyph(key, size, cx=0.0, cy=0.0):
    return scaled(CHARACTERISTICS[key]["glyph"](), size, cx, cy)


def listing() -> list:
    return [{"key": k, "name": v["name"], "category": v["category"]} for k, v in CHARACTERISTICS.items()]
