import zlib

from app.doc.entities import Arc, Circle, Ellipse, Insert, Line, LwPolyline, MText, Point, Ray, Solid, Text, XLine, AttDef
from app.lisp.types import Cons, EName, from_list, point_of

DXF_NAME = {"polyline3d": "POLYLINE", "lwpolyline": "LWPOLYLINE"}
KIND_OF = {"LINE": "line", "POINT": "point", "CIRCLE": "circle", "ARC": "arc", "ELLIPSE": "ellipse", "LWPOLYLINE": "lwpolyline", "TEXT": "text", "MTEXT": "mtext", "INSERT": "insert", "SOLID": "solid", "RAY": "ray", "XLINE": "xline", "ATTDEF": "attdef"}
CLASS_OF = {"line": Line, "point": Point, "circle": Circle, "arc": Arc, "ellipse": Ellipse, "lwpolyline": LwPolyline, "text": Text, "mtext": MText, "insert": Insert, "solid": Solid, "ray": Ray, "xline": XLine, "attdef": AttDef}

SIMPLE = {
    "line": {10: ("start", "pt"), 11: ("end", "pt")},
    "point": {10: ("position", "pt"), 50: ("angle", "f")},
    "circle": {10: ("center", "pt"), 40: ("radius", "f")},
    "arc": {10: ("center", "pt"), 40: ("radius", "f"), 50: ("start_angle", "f"), 51: ("end_angle", "f")},
    "ellipse": {10: ("center", "pt"), 11: ("major", "pt"), 40: ("ratio", "f"), 41: ("start_param", "f"), 42: ("end_param", "f")},
    "text": {10: ("position", "pt"), 40: ("height", "f"), 1: ("text", "s"), 50: ("rotation", "f"), 41: ("width_factor", "f"), 51: ("oblique", "f"), 7: ("style", "s"), 72: ("halign", "i"), 11: ("align_point", "pt"), 73: ("valign", "i")},
    "mtext": {10: ("position", "pt"), 40: ("height", "f"), 41: ("width", "f"), 71: ("attachment", "i"), 1: ("contents", "s"), 50: ("rotation", "f"), 7: ("style", "s")},
    "insert": {2: ("block", "s"), 10: ("position", "pt"), 50: ("rotation", "f")},
    "ray": {10: ("base", "pt"), 11: ("direction", "pt")},
    "xline": {10: ("base", "pt"), 11: ("direction", "pt")},
    "attdef": {10: ("position", "pt"), 40: ("height", "f"), 1: ("default", "s"), 3: ("prompt", "s"), 2: ("tag", "s"), 50: ("rotation", "f"), 7: ("style", "s")},
    "solid": {},
    "lwpolyline": {},
}
REQUIRED = {"line": (10, 11), "point": (10,), "circle": (10, 40), "arc": (10, 40, 50, 51), "ellipse": (10, 11, 40), "text": (10, 40, 1), "mtext": (10, 1), "insert": (2, 10), "ray": (10, 11), "xline": (10, 11), "attdef": (10, 2), "solid": (10, 11, 12), "lwpolyline": (10,)}


def dxf_type(e) -> str:
    if e.kind == "unknown":
        return (getattr(e, "type_name", "") or "UNKNOWN").upper()
    return DXF_NAME.get(e.kind, e.kind.upper())


def owner_ename(owner: str) -> EName:
    if owner == "model":
        return EName(0x1F)
    return EName(0x20000 + (zlib.crc32(owner.encode("utf-8")) & 0xFFFFF))


def layout_name(owner: str):
    if owner == "model":
        return "Model"
    if owner.startswith("layout:"):
        return owner[7:]
    return None


def p3(p):
    return [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]


def vtx_groups(e):
    out = [(90, len(e.vertices)), (70, 1 if e.closed else 0)]
    if e.const_width:
        out.append((43, float(e.const_width)))
    if e.elevation:
        out.append((38, float(e.elevation)))
    for v in e.vertices:
        out.append((10, [float(v["p"][0]), float(v["p"][1])]))
        if v.get("sw"):
            out.append((40, float(v["sw"])))
        if v.get("ew"):
            out.append((41, float(v["ew"])))
        if v.get("bulge"):
            out.append((42, float(v["bulge"])))
    return out


def body(e) -> list:
    k = e.kind
    spec = SIMPLE.get(k)
    out = []
    if k == "lwpolyline":
        return vtx_groups(e)
    if k == "solid":
        for i, c in enumerate(e.corners[:4]):
            out.append((10 + i, p3(c)))
        return out
    if k == "insert":
        out = [(2, e.block), (10, p3(e.position)), (41, float(e.scale[0])), (42, float(e.scale[1])), (43, float(e.scale[2] if len(e.scale) > 2 else 1.0)), (50, float(e.rotation))]
        return out
    if k == "spline":
        out = [(70, 1 if e.closed else 0), (71, int(e.degree)), (72, len(e.knots)), (73, len(e.control_points))]
        out += [(40, float(v)) for v in e.knots]
        out += [(10, p3(p)) for p in e.control_points]
        out += [(11, p3(p)) for p in e.fit_points]
        return out
    if k == "polyline3d":
        return [(70, 8 + (1 if e.closed else 0))] + [(10, p3(p)) for p in e.points]
    if spec is None:
        return out
    for code, (attr, conv) in spec.items():
        val = getattr(e, attr, None)
        if val is None:
            continue
        if conv == "pt":
            out.append((code, p3(val)))
        elif conv == "f":
            out.append((code, float(val)))
        elif conv == "i":
            out.append((code, int(val)))
        else:
            out.append((code, str(val)))
    if k == "attdef":
        m = e.modes
        flags = (1 if m.get("invisible") else 0) | (2 if m.get("constant") else 0) | (4 if m.get("verify") else 0) | (8 if m.get("preset") else 0)
        out.append((70, flags))
    return out


def rgb_value(c):
    if isinstance(c, str) and c.startswith("#") and len(c) == 7:
        try:
            return int(c[1:], 16)
        except ValueError:
            return None
    return None


def pairs_of(e) -> list:
    g = [(-1, EName(e.handle)), (0, dxf_type(e)), (5, "%X" % e.handle), (330, owner_ename(e.owner)), (8, e.layer or "0")]
    if e.linetype and e.linetype.lower() != "bylayer":
        g.append((6, e.linetype))
    if isinstance(e.color, int) and e.color != 256:
        g.append((62, int(e.color)))
    else:
        rgb = rgb_value(e.color)
        if rgb is not None:
            g.append((420, rgb))
    if e.ltscale != 1.0:
        g.append((48, float(e.ltscale)))
    if isinstance(e.lineweight, (int, float)) and e.lineweight != -1:
        g.append((370, int(e.lineweight)))
    if e.thickness:
        g.append((39, float(e.thickness)))
    if not e.visible:
        g.append((60, 1))
    lay = layout_name(e.owner)
    if lay is not None:
        g.append((410, lay))
    g.extend(body(e))
    return g


def value_to_lisp(v):
    if isinstance(v, list):
        return from_list([float(x) for x in v])
    return v


def alist(e) -> Cons:
    return from_list([Cons(code, value_to_lisp(val)) for code, val in pairs_of(e)])


def py_value(v):
    if type(v) is Cons:
        p = point_of(v)
        if p is not None:
            return p
        out = []
        while type(v) is Cons:
            out.append(py_value(v.a))
            v = v.d
        return out
    return v


def lisp_pairs(x) -> list:
    out = []
    while type(x) is Cons:
        item = x.a
        if type(item) is Cons and type(item.a) is int:
            out.append((item.a, py_value(item.d)))
        x = x.d
    return out


def groups_map(e) -> dict:
    m: dict = {}
    for code, val in pairs_of(e):
        m.setdefault(code, []).append(val)
    return m
