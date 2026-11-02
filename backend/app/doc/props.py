import math
import re

from app.doc import curvepath, geom, measure
from app.doc import tables as T


class PropError(Exception):
    pass


COMMON = ("layer", "color", "linetype", "lineweight", "ltscale", "thickness", "transparency", "visible", "plot_style")
COLOR_WORDS = {"red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5, "magenta": 6, "white": 7}
LW_FLAGS = {"bylayer": -1, "byblock": -2, "default": -3}


def lw_text(v) -> object:
    if v == -1:
        return "ByLayer"
    if v == -2:
        return "ByBlock"
    if v == -3 or v is None:
        return "Default"
    return round(float(v) / 100.0, 2)


def color_text(c):
    if c == 256:
        return "ByLayer"
    if c == 0:
        return "ByBlock"
    return c


def parse_color(value):
    if isinstance(value, bool):
        raise PropError("bad colour")
    if isinstance(value, (int, float)):
        if float(value) != int(value) or not 0 <= int(value) <= 256:
            raise PropError("bad colour")
        return int(value)
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            vals = [int(v) for v in value]
        except (TypeError, ValueError):
            raise PropError("bad colour")
        if any(v < 0 or v > 255 for v in vals):
            raise PropError("bad colour")
        return "#%02X%02X%02X" % tuple(vals)
    s = str(value).strip().lower()
    if s in ("bylayer", "by layer"):
        return 256
    if s in ("byblock", "by block"):
        return 0
    if s in COLOR_WORDS:
        return COLOR_WORDS[s]
    if re.fullmatch(r"\d{1,3}", s):
        return parse_color(int(s))
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if m:
        return "#" + m.group(1).upper()
    m = re.fullmatch(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", s)
    if m:
        return parse_color([int(m.group(i)) for i in (1, 2, 3)])
    raise PropError("bad colour")


def parse_typed_color(text: str):
    s = str(text).strip().lower()
    if re.fullmatch(r"\d+", s):
        n = int(s)
        if n < 1 or n > 255:
            raise PropError("Invalid color number.")
        return n
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        raise PropError("Invalid color number.")
    try:
        return parse_color(s)
    except PropError:
        raise PropError("Invalid color name or number.")


def parse_triple(text: str):
    m = re.fullmatch(r"\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*", str(text))
    if not m or any(int(m.group(i)) > 255 for i in (1, 2, 3)):
        raise PropError("Requires three integers from 0 to 255, separated by commas.")
    return "#%02X%02X%02X" % tuple(int(m.group(i)) for i in (1, 2, 3))


def snap_lineweight(hundredths: float):
    best = min(T.LINEWEIGHTS, key=lambda v: (abs(v - hundredths), v))
    return best, best != int(round(hundredths))


def parse_lineweight(value):
    if isinstance(value, bool):
        raise PropError("bad lineweight")
    if isinstance(value, str):
        s = value.strip().lower().replace("mm", "").strip()
        if s in LW_FLAGS:
            return LW_FLAGS[s], False
        try:
            value = float(s)
        except ValueError:
            raise PropError("bad lineweight")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PropError("bad lineweight")
    if isinstance(value, int) and value in (-1, -2, -3):
        return value, False
    if value < 0 or value > 2.11 + 1e-9:
        raise PropError("bad lineweight")
    return snap_lineweight(value * 100.0)


def parse_transparency(value):
    if isinstance(value, bool):
        raise PropError("bad transparency")
    if isinstance(value, str):
        s = value.strip().lower().rstrip("%").strip()
        if s == "bylayer":
            return "ByLayer"
        if s == "byblock":
            return "ByBlock"
        try:
            value = float(s)
        except ValueError:
            raise PropError("bad transparency")
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 90:
        raise PropError("bad transparency")
    return int(value) if float(value) == int(value) else float(value)


def standard_linetype(d, name):
    low = str(name).casefold()
    for rec in T.standard_linetypes(d.metric):
        if rec["name"].casefold() == low:
            return rec
    return None


def ensure_linetype(d, name) -> str:
    s = str(name).strip()
    if not s:
        raise PropError('Cannot find linetype "%s".' % name)
    rec = d.table_get("linetypes", s)
    if rec is not None:
        return rec["name"]
    std = standard_linetype(d, s)
    if std is None:
        raise PropError('Cannot find linetype "%s".' % s)
    d.table_set("linetypes", std)
    return std["name"]


def check_layer(d, name) -> str:
    rec = d.table_get("layers", str(name))
    if rec is None:
        raise PropError('Cannot find layer "%s".' % name)
    return rec["name"]


def finite(name, v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise PropError("%s must be a finite number" % name)
    return float(v)


def positive(name, v) -> float:
    f = finite(name, v)
    if f <= 0:
        raise PropError("%s must be positive" % name)
    return f


def point_value(name, v, old):
    if not isinstance(v, (list, tuple)) or len(v) not in (2, 3):
        raise PropError("%s must be [x, y]" % name)
    vals = [finite(name, x) for x in v]
    z = vals[2] if len(vals) == 3 else (old[2] if old is not None and len(old) > 2 else 0.0)
    return [vals[0], vals[1], z]


class Field:
    def __init__(self, name, typ, get, setter=None, options=None, label=None):
        self.name = name
        self.type = typ
        self.get = get
        self.set = setter
        self.options = options
        self.label = label or name


def _plain(name, typ="number", attr=None, pos=False, deg=False, nonneg=False, integer=False, minimum=None):
    attr = attr or name

    def get(e, d):
        v = getattr(e, attr)
        return round(math.degrees(v), 10) if deg else v

    def put(e, d, v):
        if typ == "string":
            setattr(e, attr, str(v))
            return
        if typ == "bool":
            if not isinstance(v, bool):
                raise PropError("%s must be true or false" % name)
            setattr(e, attr, v)
            return
        f = positive(name, v) if pos else finite(name, v)
        if nonneg and f < 0:
            raise PropError("%s must not be negative" % name)
        if integer:
            if f != int(f):
                raise PropError("%s must be a whole number" % name)
            f = int(f)
        if minimum is not None and f < minimum:
            raise PropError("%s must be at least %s" % (name, minimum))
        setattr(e, attr, math.radians(f) if deg else f)

    return Field(name, "angle" if deg else typ, get, put)


def _pt(name, attr=None):
    attr = attr or name

    def get(e, d):
        v = getattr(e, attr)
        return [v[0], v[1]] if v else None

    def put(e, d, v):
        setattr(e, attr, point_value(name, v, getattr(e, attr)))

    return Field(name, "point", get, put)


def _ro(name, fn, typ="number"):
    return Field(name, typ, lambda e, d: fn(e), None)


def _style_field(table, label, missing):
    def get(e, d):
        return e.style

    def put(e, d, v):
        if d.table_get(table, str(v)) is None:
            raise PropError(missing % v)
        e.style = d.table_get(table, str(v))["name"]

    return Field("style", "string", get, put, options=lambda d: d.tables[table].names(), label=label)


def _length(e):
    cur = curvepath.build(e)
    return cur.length if cur else 0.0


def _poly_area(e):
    return measure.polygon_measure(e.vertices, True)[0] if e.closed else None


def _line_length_set(e, d, v):
    new = finite("length", v)
    if new < 0:
        raise PropError("length must not be negative")
    cur = geom.dist(e.start, e.end)
    if cur > 0:
        k = new / cur
        e.end = [e.start[0] + (e.end[0] - e.start[0]) * k, e.start[1] + (e.end[1] - e.start[1]) * k, e.end[2]]
    else:
        e.end = [e.start[0] + new, e.start[1], e.end[2]]


def _line_angle_set(e, d, v):
    a = math.radians(finite("angle", v))
    n = geom.dist(e.start, e.end)
    e.end = [e.start[0] + n * math.cos(a), e.start[1] + n * math.sin(a), e.end[2]]


def _circumference_set(e, d, v):
    e.radius = positive("circumference", v) / (2 * math.pi)


def _area_set(e, d, v):
    f = finite("area", v)
    if f <= 0:
        raise PropError("The area must be greater than zero.")
    e.radius = math.sqrt(f / math.pi)


def _diameter_get(e, d):
    return e.radius * 2.0


def _diameter_set(e, d, v):
    e.radius = positive("diameter", v) / 2.0


def _scale_get(i):
    def get(e, d):
        return e.scale[i] if len(e.scale) > i else 1.0

    return get


def _scale_set(i):
    def put(e, d, v):
        f = finite("scale", v)
        if abs(f) < geom.EPS:
            raise PropError("scale must be nonzero")
        sc = list(e.scale) + [1.0] * (3 - len(e.scale))
        sc[i] = f
        e.scale = sc

    return put


def _dim_style_get(e, d):
    return e.style


def _dim_style_set(e, d, v):
    rec = d.table_get("dimstyles", str(v))
    if rec is None:
        raise PropError('dimension style "%s" not found' % v)
    e.style = rec["name"]


def _dim_var(key, label, typ="number", check=None):
    def get(e, d):
        if key in e.overrides:
            return e.overrides[key]
        rec = d.table_get("dimstyles", e.style)
        return rec["vars"].get(key) if rec else None

    def put(e, d, v):
        val = check(v)
        e.overrides = dict(e.overrides)
        e.overrides[key] = val

    return Field(label, typ, get, put)


def _prec(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not 0 <= int(v) <= 8:
        raise PropError("precision must be 0 to 8")
    return int(v)


def _dim_text_get(e, d):
    return e.text_override


def _dim_text_set(e, d, v):
    e.text_override = str(v)


def _mtext_text_get(e, d):
    return e.contents


def _mtext_text_set(e, d, v):
    e.contents = str(v)


def _count_field(name, attr, minimum=1):
    return _plain(name, "integer", attr, integer=True, minimum=minimum)


def _array_fields():
    out = [
        Field("shape", "string", lambda e, d: e.shape, None),
        _count_field("columns", "columns"),
        _count_field("rows", "rows"),
        _count_field("levels", "levels"),
        _plain("column_spacing"),
        _plain("row_spacing"),
        _plain("level_spacing"),
        _plain("row_elevation"),
        _plain("axis_angle", deg=True),
        _count_field("items", "items"),
        _plain("fill_angle", deg=True),
        _plain("rotate_items", "bool"),
        _plain("align", "bool"),
        _ro("item_count", lambda e: e.count(), "integer"),
    ]
    return out


FIELDS = {
    "line": [_pt("start"), _pt("end"), Field("length", "number", lambda e, d: geom.dist(e.start, e.end), _line_length_set), Field("angle", "angle", lambda e, d: round(math.degrees(geom.angle_of(e.start, e.end)) % 360.0, 10), _line_angle_set)],
    "circle": [_pt("center"), _plain("radius", pos=True), Field("diameter", "number", _diameter_get, _diameter_set), Field("circumference", "number", lambda e, d: 2 * math.pi * e.radius, _circumference_set), Field("area", "number", lambda e, d: math.pi * e.radius * e.radius, _area_set)],
    "arc": [_pt("center"), _plain("radius", pos=True), _plain("start_angle", deg=True), _plain("end_angle", deg=True), _ro("length", _length)],
    "ellipse": [_pt("center"), _plain("ratio", pos=True), _ro("length", _length)],
    "lwpolyline": [_plain("closed", "bool"), _plain("const_width", nonneg=True), _plain("elevation"), _ro("vertices", lambda e: len(e.vertices), "integer"), _ro("length", _length), _ro("area", _poly_area)],
    "polyline3d": [_plain("closed", "bool"), _ro("vertices", lambda e: len(e.points), "integer"), _ro("length", _length)],
    "spline": [_ro("degree", lambda e: e.degree, "integer"), _plain("closed", "bool"), _ro("length", _length)],
    "point": [_pt("position")],
    "ray": [_pt("base")],
    "xline": [_pt("base")],
    "text": [Field("text", "string", lambda e, d: e.text, lambda e, d, v: setattr(e, "text", str(v))), _pt("position"), _plain("height", pos=True), _plain("rotation", deg=True), Field("style", "string", lambda e, d: e.style, None), _plain("width_factor", pos=True), _plain("oblique", deg=True)],
    "mtext": [Field("text", "string", _mtext_text_get, _mtext_text_set), _pt("position"), _plain("height", pos=True), _plain("rotation", deg=True), _plain("width", nonneg=True), Field("style", "string", lambda e, d: e.style, None)],
    "attdef": [_plain("tag", "string"), _plain("prompt", "string"), _plain("default", "string"), _pt("position"), _plain("height", pos=True), _plain("rotation", deg=True), Field("style", "string", lambda e, d: e.style, None)],
    "insert": [_ro("block", lambda e: e.block, "string"), _pt("position"), _plain("rotation", deg=True), Field("scale_x", "number", _scale_get(0), _scale_set(0)), Field("scale_y", "number", _scale_get(1), _scale_set(1)), Field("scale_z", "number", _scale_get(2), _scale_set(2))],
    "hatch": [_plain("pattern", "string"), _plain("pattern_scale", pos=True), _plain("pattern_angle", deg=True), _plain("solid", "bool"), _ro("associative", lambda e: e.associative, "bool")],
    "solid": [],
    "dimension": [Field("text_override", "string", _dim_text_get, _dim_text_set), Field("style", "string", _dim_style_get, _dim_style_set), _dim_var("DIMTXT", "text_height", check=lambda v: positive("text height", v)), _dim_var("DIMASZ", "arrow_size", check=lambda v: positive("arrow size", v)), _dim_var("DIMSCALE", "scale", check=lambda v: positive("scale", v)), _dim_var("DIMDEC", "precision", "integer", _prec), _ro("measurement", lambda e: e.measurement)],
    "helix": [_pt("center"), _plain("turns", pos=True), _plain("height", pos=True), _plain("base_radius", pos=True), _plain("top_radius", nonneg=True)],
    "mline": [_plain("scale"), _plain("justification", "integer", integer=True, minimum=0), _plain("closed", "bool")],
    "wipeout": [],
    "assoc_array": _array_fields(),
    "leader": [_plain("arrowhead", "bool"), _plain("spline", "bool"), _plain("arrow_size", nonneg=True), _ro("style", lambda e: e.style, "string"), _ro("vertices", lambda e: len(e.points), "integer"), _ro("length", lambda e: sum(geom.dist(e.points[i], e.points[i + 1]) for i in range(len(e.points) - 1)))],
    "mleader": [_plain("text", "string"), _ro("content_type", lambda e: e.content_type, "string"), _ro("leader_type", lambda e: e.leader_type, "string"), _ro("style", lambda e: e.style, "string"), _ro("leader_lines", lambda e: len(e.leaders), "integer"), _plain("size_scale", pos=True), _pt("content_pos")],
    "table": [_pt("position"), _plain("rotation", deg=True), _ro("style", lambda e: e.style, "string"), _ro("table_rows", lambda e: e.rows(), "integer"), _ro("table_columns", lambda e: e.cols(), "integer"), _ro("table_width", lambda e: e.width())],
    "viewport": [_pt("center"), _plain("width", pos=True), _plain("height", pos=True), _plain("scale", pos=True), _plain("on", "bool"), _plain("locked", "bool"), _plain("anno_scale", "string"), _ro("viewport_id", lambda e: e.vp_id, "integer"), _ro("view_height", lambda e: e.view_height)],
}


def _fix_style_fields():
    for kind in ("text", "mtext", "attdef"):
        for i, f in enumerate(FIELDS[kind]):
            if f.name == "style":
                def put(e, d, v):
                    rec = d.table_get("textstyles", str(v))
                    if rec is None:
                        raise PropError('Style "%s" not defined - use STYLE command.' % v)
                    e.style = rec["name"]

                FIELDS[kind][i] = Field("style", "string", f.get, put, options=lambda d: d.tables["textstyles"].names())


_fix_style_fields()


def fields_for(kind):
    return FIELDS.get(kind, [])


def common_fields():
    def lw_get(e, d):
        return lw_text(e.lineweight)

    def lw_set(e, d, v):
        e.lineweight = parse_lineweight(v)[0]

    def tr_get(e, d):
        t = e.transparency
        return t if isinstance(t, (int, float)) and not isinstance(t, bool) else ("ByBlock" if str(t).casefold() == "byblock" else "ByLayer")

    def thick_set(e, d, v):
        e.thickness = finite("thickness", v)

    return [
        Field("layer", "string", lambda e, d: e.layer, lambda e, d, v: setattr(e, "layer", check_layer(d, v)), options=lambda d: d.tables["layers"].names()),
        Field("color", "color", lambda e, d: color_text(e.color), lambda e, d, v: setattr(e, "color", parse_color(v)), options=lambda d: ["ByLayer", "ByBlock"]),
        Field("linetype", "string", lambda e, d: e.linetype, lambda e, d, v: setattr(e, "linetype", ensure_linetype(d, v)), options=lambda d: ["ByLayer", "ByBlock"] + [n for n in d.tables["linetypes"].names() if n not in ("ByLayer", "ByBlock")]),
        Field("lineweight", "lineweight", lw_get, lw_set, options=lambda d: ["ByLayer", "ByBlock", "Default"] + [v / 100.0 for v in T.LINEWEIGHTS]),
        Field("ltscale", "number", lambda e, d: e.ltscale, lambda e, d, v: setattr(e, "ltscale", positive("linetype scale", v))),
        Field("thickness", "number", lambda e, d: e.thickness, thick_set),
        Field("transparency", "transparency", tr_get, lambda e, d, v: setattr(e, "transparency", parse_transparency(v))),
        Field("visible", "bool", lambda e, d: e.visible, lambda e, d, v: setattr(e, "visible", _bool(v))),
        Field("plot_style", "string", lambda e, d: e.plot_style, lambda e, d, v: setattr(e, "plot_style", str(v))),
    ]


def _bool(v):
    if not isinstance(v, bool):
        raise PropError("visibility must be true or false")
    return v


COMMON_FIELDS = {f.name: f for f in common_fields()}

ALIASES = {"colour": "color", "linetype_scale": "ltscale", "lt_scale": "ltscale", "ltype": "linetype", "lweight": "lineweight", "line_weight": "lineweight", "plotstyle": "plot_style", "center_point": "center"}


def _freeze(v):
    return repr(v)


def _entities(d, handles):
    out = []
    for h in handles:
        e = d.get(int(h))
        if e is not None:
            out.append(e)
    return out


def _describe(field, ents, d):
    values = []
    for e in ents:
        try:
            values.append(field.get(e, d))
        except Exception:
            values.append(None)
    first = values[0] if values else None
    varies = len({_freeze(v) for v in values}) > 1
    out = {"value": None if varies else first, "varies": varies, "type": field.type, "readonly": field.set is None}
    if field.options is not None:
        out["options"] = field.options(d)
    return out


def inspect(d, handles) -> dict:
    ents = _entities(d, handles)
    out = {"handles": [e.handle for e in ents], "count": len(ents), "general": {}, "kinds": {}}
    if not ents:
        return out
    for f in common_fields():
        out["general"][f.name] = _describe(f, ents, d)
    groups = {}
    for e in ents:
        groups.setdefault(e.kind, []).append(e)
    for kind, es in groups.items():
        props = {}
        for f in fields_for(kind):
            props[f.name] = _describe(f, es, d)
        out["kinds"][kind] = {"count": len(es), "handles": [e.handle for e in es], "props": props}
    return out


def _canon(name):
    low = str(name).strip().lower().replace(" ", "_")
    return ALIASES.get(low, low)


def apply_changes(d, ents, changes, kind=None) -> int:
    if not ents:
        raise PropError("nothing selected")
    if not changes:
        raise PropError("no properties given")
    names = {}
    for k, v in changes.items():
        names[_canon(k)] = v
    unknown = []
    for name in names:
        if name in COMMON_FIELDS:
            continue
        if not any(any(f.name == name for f in fields_for(e.kind)) for e in ents):
            unknown.append(name)
    if unknown:
        raise PropError("unknown property: %s" % ", ".join(sorted(unknown)))
    count = 0
    for e in ents:
        if kind is not None and e.kind != kind and any(n not in COMMON_FIELDS for n in names):
            targets = {n: v for n, v in names.items() if n in COMMON_FIELDS}
        else:
            targets = names
        if not targets:
            continue
        live = d.modify(e.handle)
        touched = False
        for name, value in targets.items():
            f = COMMON_FIELDS.get(name)
            if f is None:
                f = next((x for x in fields_for(live.kind) if x.name == name), None)
            if f is None:
                continue
            if f.set is None:
                raise PropError("%s is read only" % name)
            f.set(live, d, value)
            touched = True
        if touched:
            if not live.valid():
                raise PropError("the change would make an object invalid")
            count += 1
    return count


def snapshot_values(d, ents, names) -> dict:
    out = {}
    for name in names:
        f = COMMON_FIELDS.get(name)
        if f is None:
            continue
        vals = {_freeze(f.get(e, d)) for e in ents}
        out[name] = ents and f.get(ents[0], d) if len(vals) == 1 else "varies"
    return out
