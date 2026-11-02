import math
import re


class QSelectError(Exception):
    pass


COLOR_NAMES = ["", "Red", "Yellow", "Green", "Cyan", "Blue", "Magenta", "White"]
BASIC_COLORS = ["ByLayer", "ByBlock", "Red", "Yellow", "Green", "Cyan", "Blue", "Magenta", "White"]
OPERATORS = ("=", "<>", ">", "<", "*")


def color_name(c):
    if c == 256:
        return "ByLayer"
    if c == 0:
        return "ByBlock"
    if isinstance(c, int) and not isinstance(c, bool):
        return COLOR_NAMES[c] if 0 < c < len(COLOR_NAMES) else str(c)
    return c if isinstance(c, str) else ""


def _lineweight(e):
    v = e.lineweight
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    return {-1: "ByLayer", -2: "ByBlock", -3: "Default"}.get(v, v / 100.0)


def _scalar(v):
    return v if isinstance(v, (int, float, str, bool)) else None


def _plain(field):
    return lambda e: _scalar(getattr(e, field, None))


def _axis(field, i):
    def get(e):
        v = getattr(e, field, None)
        return float(v[i]) if isinstance(v, (list, tuple)) and len(v) > i else None

    return get


def _deg(field):
    def get(e):
        v = getattr(e, field, None)
        return round(math.degrees(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    return get


def _line_length(e):
    return math.hypot(e.end[0] - e.start[0], e.end[1] - e.start[1])


def _line_angle(e):
    return round(math.degrees(math.atan2(e.end[1] - e.start[1], e.end[0] - e.start[0])) % 360.0, 9)


def _circle(fn):
    return lambda e: fn(e.radius) if isinstance(e.radius, (int, float)) else None


def _poly_area(e):
    from app.doc import measure

    return measure.polygon_measure(e.vertices, True)[0] if e.closed else None


COMMON = [
    ("color", "Color", lambda e: color_name(e.color), "color"),
    ("layer", "Layer", _plain("layer"), "values"),
    ("linetype", "Linetype", _plain("linetype"), "values"),
    ("ltscale", "Linetype scale", _plain("ltscale"), None),
    ("lineweight", "Lineweight", _lineweight, None),
    ("thickness", "Thickness", _plain("thickness"), None),
    ("kind", "Type", lambda e: e.kind, "values"),
]

BY_KIND = {
    "line": [
        ("start_x", "Start X", _axis("start", 0), None), ("start_y", "Start Y", _axis("start", 1), None),
        ("end_x", "End X", _axis("end", 0), None), ("end_y", "End Y", _axis("end", 1), None),
        ("length", "Length", _line_length, None), ("angle", "Angle", _line_angle, None),
    ],
    "circle": [
        ("center_x", "Center X", _axis("center", 0), None), ("center_y", "Center Y", _axis("center", 1), None),
        ("radius", "Radius", _plain("radius"), None),
        ("diameter", "Diameter", _circle(lambda r: r * 2), None),
        ("circumference", "Circumference", _circle(lambda r: 2 * math.pi * r), None),
        ("area", "Area", _circle(lambda r: math.pi * r * r), None),
    ],
    "arc": [
        ("center_x", "Center X", _axis("center", 0), None), ("center_y", "Center Y", _axis("center", 1), None),
        ("radius", "Radius", _plain("radius"), None),
        ("start_angle", "Start angle", _deg("start_angle"), None), ("end_angle", "End angle", _deg("end_angle"), None),
    ],
    "ellipse": [("center_x", "Center X", _axis("center", 0), None), ("center_y", "Center Y", _axis("center", 1), None), ("ratio", "Ratio", _plain("ratio"), None)],
    "lwpolyline": [("closed", "Closed", _plain("closed"), None), ("const_width", "Global width", _plain("const_width"), None), ("elevation", "Elevation", _plain("elevation"), None), ("area", "Area", _poly_area, None)],
    "text": [
        ("text", "Contents", _plain("text"), None), ("height", "Height", _plain("height"), None), ("rotation", "Rotation", _deg("rotation"), None),
        ("width_factor", "Width factor", _plain("width_factor"), None), ("style", "Style", _plain("style"), None),
        ("position_x", "Position X", _axis("position", 0), None), ("position_y", "Position Y", _axis("position", 1), None),
    ],
    "mtext": [
        ("contents", "Contents", _plain("contents"), None), ("height", "Text height", _plain("height"), None), ("width", "Defined width", _plain("width"), None),
        ("rotation", "Rotation", _deg("rotation"), None), ("style", "Style", _plain("style"), None),
    ],
    "insert": [("block", "Name", _plain("block"), None), ("rotation", "Rotation", _deg("rotation"), None), ("position_x", "Position X", _axis("position", 0), None), ("position_y", "Position Y", _axis("position", 1), None)],
    "hatch": [("pattern", "Pattern", _plain("pattern"), None), ("pattern_scale", "Scale", _plain("pattern_scale"), None), ("pattern_angle", "Angle", _deg("pattern_angle"), None)],
    "dimension": [("text_override", "Text override", _plain("text_override"), None), ("style", "Dim style", _plain("style"), None)],
    "assoc_array": [("shape", "Shape", _plain("shape"), None), ("columns", "Columns", _plain("columns"), None), ("rows", "Rows", _plain("rows"), None), ("levels", "Levels", _plain("levels"), None), ("items", "Items", _plain("items"), None)],
    "point": [("position_x", "Position X", _axis("position", 0), None), ("position_y", "Position Y", _axis("position", 1), None)],
}


def props_for(kind):
    return COMMON + BY_KIND.get(kind, []) if kind else list(COMMON)


def _glob(pattern):
    return re.compile("^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$", re.IGNORECASE)


def matches(value, op, typed):
    if op == "*":
        return value is not None and _glob(typed).match(str(value)) is not None
    if value is None:
        return op == "<>"
    number = None
    if typed.strip() != "":
        try:
            number = float(typed)
        except ValueError:
            number = None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and number is not None and math.isfinite(number):
        same = abs(value - number) <= 1e-9 * max(1.0, abs(number))
        if op == "=":
            return same
        if op == "<>":
            return not same
        return (value > number and not same) if op == ">" else (value < number and not same)
    a, b = str(value).lower(), typed.lower()
    if op == "=":
        return a == b
    if op == "<>":
        return a != b
    return a > b if op == ">" else a < b


def scoped(ents, scope, selected):
    if scope == "sel":
        keep = set(selected)
        return [e for e in ents if e.handle in keep]
    return list(ents)


def info(ents, scope, selected, kind):
    pool = scoped(ents, scope, selected)
    counts = {}
    for e in pool:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    of_type = [e for e in pool if not kind or e.kind == kind]
    props = []
    for pid, label, get, source in props_for(kind or None):
        row = {"id": pid, "label": label, "choices": None}
        if source == "color":
            row["choices"] = list(BASIC_COLORS)
        elif source:
            seen = set()
            for e in of_type:
                v = get(e)
                if v is not None:
                    seen.add(str(v))
            row["choices"] = sorted(seen)
        props.append(row)
    return {"kinds": [{"kind": k, "count": counts[k]} for k in sorted(counts)], "props": props}


def run(ents, selected, req):
    scope = req.get("scope", "all")
    kind = req.get("kind") or None
    op = req.get("operator", "=")
    if op not in OPERATORS:
        raise QSelectError("The operator must be =, <>, >, < or *.")
    how = req.get("how", "include")
    if how not in ("include", "exclude"):
        raise QSelectError("How to apply must be include or exclude.")
    typed = str(req.get("value", "")).strip()
    pool = scoped(ents, scope, selected)
    of_type = [e for e in pool if not kind or e.kind == kind]
    prop = None
    pid = req.get("property")
    if pid:
        prop = next((p for p in props_for(kind) if p[0] == pid), None)
        if prop is None:
            raise QSelectError("Unknown property: %s." % pid)
    use = prop is not None and (typed != "" or op == "*")
    hit = {e.handle for e in of_type if not use or matches(prop[2](e), op, typed)}
    if how == "include":
        result = [e.handle for e in pool if e.handle in hit]
    else:
        result = [e.handle for e in pool if e.handle not in hit]
    if req.get("append"):
        order = [e.handle for e in ents]
        merged = set(selected) | set(result)
        result = [h for h in order if h in merged]
    return result
