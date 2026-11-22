import math
import os
import re

from app import __version__
from app.cmd.context import Context
from app.doc import attribs, blockdefs, curves2d, curvepath, geom
from app.doc import measure as M
from app.doc import tables as TB
from app.doc.entities import Arc, Circle, Ellipse, LwPolyline, MText, Point, Polyline3d, Ray, Text, XLine, Line, entity_from_dict
from app.doc.model import SPACE_MODEL, layout_space
from app.lisp import lib_list
from app.lisp.lib_ent import doc_of, edit
from app.lisp.printer import prin1
from app.lisp.registry import BUILTIN, CONSTANTS, fn, special
from app.lisp.types import Cons, EName, LispError, MISSING, Subr, Sym, T, from_list, is_num, sym, to_list
from app.sysvars import registry as sv

VT_EMPTY, VT_NULL, VT_I2, VT_I4, VT_R4, VT_R8, VT_BSTR, VT_DISPATCH, VT_BOOL, VT_VARIANT, VT_ARRAY = 0, 1, 2, 3, 4, 5, 8, 9, 11, 12, 0x2000
VTRUE = sym(":VLAX-TRUE")
VFALSE = sym(":VLAX-FALSE")
MAX_OBJECTS = 1_000_000
MAX_ARRAY = 1_000_000
BAD_LAYER_CHARS = set('<>/\\":;?*|,=`')

TABLE_IFACE = {"layers": ("Layers", "Layer"), "linetypes": ("Linetypes", "Linetype"), "textstyles": ("TextStyles", "TextStyle"), "dimstyles": ("DimStyles", "DimStyle"), "blocks": ("Blocks", "Block"), "layouts": ("Layouts", "Layout")}
OBJECT_NAMES = {"line": "AcDbLine", "point": "AcDbPoint", "circle": "AcDbCircle", "arc": "AcDbArc", "ellipse": "AcDbEllipse", "lwpolyline": "AcDbPolyline", "polyline3d": "AcDb3dPolyline", "spline": "AcDbSpline", "ray": "AcDbRay", "xline": "AcDbXline", "text": "AcDbText", "mtext": "AcDbMText", "attdef": "AcDbAttributeDefinition", "insert": "AcDbBlockReference", "hatch": "AcDbHatch", "solid": "AcDbSolid", "dimension": "AcDbDimension", "leader": "AcDbLeader", "mleader": "AcDbMLeader", "table": "AcDbTable", "wipeout": "AcDbWipeout", "region": "AcDbRegion", "helix": "AcDbHelix", "mline": "AcDbMline", "viewport": "AcDbViewport"}


class VlaObject:
    __slots__ = ("kind", "key", "serial", "label")

    def __init__(self, kind, key, serial, label):
        self.kind = kind
        self.key = key
        self.serial = serial
        self.label = label

    def __str__(self):
        return "#<VLA-OBJECT %s %08x>" % (self.label, self.serial)


class Boxed:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class SafeArray:
    __slots__ = ("vt", "bounds", "data")

    def __init__(self, vt, bounds, data):
        self.vt = vt
        self.bounds = bounds
        self.data = data

    def __str__(self):
        return "#<safearray...>"


class Variant:
    __slots__ = ("vt", "value")

    def __init__(self, vt, value):
        self.vt = vt
        self.value = value

    def __str__(self):
        if self.vt & VT_ARRAY:
            return "#<variant %d ...>" % self.vt
        return "#<variant %d %s>" % (self.vt, prin1(self.value) if self.value is not None else "")


class Pt(list):
    pass


class Dbl(list):
    pass


class Objs(list):
    pass


lib_list.TYPES[VlaObject] = "VLA-OBJECT"
lib_list.TYPES[SafeArray] = "SAFEARRAY"
lib_list.TYPES[Variant] = "VARIANT"

PROPS: dict = {}
SETS: dict = {}
METHODS: dict = {}
NAMES: dict = {}


def shown(name: str) -> str:
    return NAMES.get(name, name.capitalize())


def prop(groups, name):
    NAMES[name.upper()] = name

    def wrap(f):
        for g in groups.split():
            PROPS[(g, name.upper())] = f
        return f

    return wrap


def put(groups, name):
    def wrap(f):
        for g in groups.split():
            SETS[(g, name.upper())] = f
        return f

    return wrap


def method(groups, name):
    NAMES[name.upper()] = name

    def wrap(f):
        for g in groups.split():
            METHODS[(g, name.upper())] = f
        return f

    return wrap


def objects(L) -> dict:
    c = getattr(L, "vla_objects", None)
    if c is None:
        c = {}
        L.vla_objects = c
    return c


def obj(L, kind, key=None) -> VlaObject:
    c = objects(L)
    k = (kind, key)
    o = c.get(k)
    if o is None:
        if len(c) >= MAX_OBJECTS:
            raise LispError("too many ActiveX objects in one session")
        label = iface(kind, key)
        if kind == "ent":
            e = drawing(L).get(key)
            label = OBJECT_NAMES.get(e.kind, "AcDb" + e.kind.capitalize())[4:] if e is not None else "Entity"
        o = VlaObject(kind, key, 0x2A000 + len(c), label)
        c[k] = o
    return o


def drawing(L):
    return doc_of(L).drawing


def ent(L, o):
    e = drawing(L).get(o.key)
    if e is None:
        raise LispError("Automation Error. Object was erased")
    return e


def iface(k, key) -> str:
    if k == "space":
        return "ModelSpace" if key == SPACE_MODEL else ("PaperSpace" if key.startswith("layout:") else "Block")
    if k == "table":
        return TABLE_IFACE[key][0]
    if k == "rec":
        return TABLE_IFACE[key[0]][1]
    return {"app": "Application", "doc": "Document", "docs": "Documents", "utility": "Utility", "attrib": "Attribute", "ent": "Entity"}.get(k, k)


def groups_of(L, o) -> list:
    k = o.kind
    if k == "ent":
        return ["ent:" + ent(L, o).kind, "ent", "any"]
    if k == "rec":
        return ["rec:" + o.key[0], "rec", "any"]
    if k == "space":
        return ["space", "any"]
    if k == "table":
        return ["table:" + o.key, "table", "any"]
    return [k, "any"]


def vobj(x, what="VLA-OBJECT") -> VlaObject:
    if type(x) is not VlaObject:
        raise LispError("bad argument type: %s %s" % (what, prin1(x)))
    return x


def pname(x) -> str:
    if type(x) is Sym:
        return x.name
    if type(x) is str and x:
        return x.upper()
    raise LispError("bad argument type: symbolp %s" % prin1(x))


def to_vla(v):
    if type(v) is Boxed:
        inner = to_vla(v.value)
        return inner if type(inner) is Variant else Variant(infer_vt(inner), inner)
    if isinstance(v, bool):
        return VTRUE if v else VFALSE
    if type(v) in (Pt, Dbl):
        return Variant(VT_ARRAY | VT_R8, SafeArray(VT_R8, [(0, len(v) - 1)], [float(x) for x in v]))
    if type(v) is Objs:
        return Variant(VT_ARRAY | VT_DISPATCH, SafeArray(VT_DISPATCH, [(0, len(v) - 1)], list(v)))
    return v


def to_plain(v):
    if type(v) is Boxed:
        return to_plain(v.value)
    if isinstance(v, bool):
        return -1 if v else 0
    if type(v) in (Pt, Dbl):
        return from_list([float(x) for x in v])
    if type(v) is Objs:
        return from_list(list(v))
    return v


def unwrap(v):
    if type(v) is Variant:
        v = v.value
    if type(v) is SafeArray:
        return [unwrap(x) for x in v.data]
    if v is VTRUE:
        return True
    if v is VFALSE:
        return False
    if type(v) is Cons:
        return [unwrap(x) for x in to_list(v)]
    return v


def need_num(v) -> float:
    u = unwrap(v)
    if isinstance(u, bool) or not is_num(u) or not math.isfinite(u):
        raise LispError("bad argument type: numberp %s" % prin1(v))
    return float(u)


def need_int(v) -> int:
    u = unwrap(v)
    if type(u) is float and u.is_integer():
        u = int(u)
    if type(u) is not int:
        raise LispError("bad argument type: fixnump %s" % prin1(v))
    return u


def need_str(v) -> str:
    u = unwrap(v)
    if type(u) is not str:
        raise LispError("bad argument type: stringp %s" % prin1(v))
    return u


def need_bool(v) -> bool:
    u = unwrap(v)
    if isinstance(u, bool):
        return u
    if type(u) is int:
        return u != 0
    if u is None:
        return False
    if u is T:
        return True
    raise LispError("bad argument type: %s" % prin1(v))


def need_pt(v) -> list:
    u = unwrap(v)
    if not isinstance(u, list) or not 2 <= len(u) <= 3 or not all(is_num(c) and not isinstance(c, bool) and math.isfinite(c) for c in u):
        raise LispError("bad argument type: point %s" % prin1(v))
    return [float(u[0]), float(u[1]), float(u[2]) if len(u) > 2 else 0.0]


def need_doubles(v, step: int, least: int) -> list:
    u = unwrap(v)
    if not isinstance(u, list) or len(u) % step or len(u) < step * least or len(u) > MAX_ARRAY:
        raise LispError("bad argument value: coordinates %s" % prin1(v))
    flat = []
    for c in u:
        if isinstance(c, bool) or not is_num(c) or not math.isfinite(c):
            raise LispError("bad argument value: coordinates %s" % prin1(v))
        flat.append(float(c))
    return flat


def get_prop(L, o, name: str):
    for g in groups_of(L, o):
        f = PROPS.get((g, name))
        if f is not None:
            return f(L, o)
    raise LispError("ActiveX Server returned the error: unknown name: %s" % name)


def put_prop(L, o, name: str, value) -> None:
    for g in groups_of(L, o):
        f = SETS.get((g, name))
        if f is not None:
            f(L, o, value)
            return
    for g in groups_of(L, o):
        if (g, name) in PROPS:
            raise LispError("ActiveX Server returned the error: %s is read only" % name)
    raise LispError("ActiveX Server returned the error: unknown name: %s" % name)


def call_method(L, o, name: str, args: list):
    for g in groups_of(L, o):
        f = METHODS.get((g, name))
        if f is not None:
            return f(L, o, *args)
    raise LispError("ActiveX Server returned the error: unknown name: %s" % name)


def has_prop(L, o, name: str, writable: bool) -> bool:
    gs = groups_of(L, o)
    table = SETS if writable else PROPS
    return any((g, name) in table for g in gs)


def change(L, o, fn_) -> None:
    doc = doc_of(L)
    d = doc.drawing
    e = ent(L, o)
    if Context(L.ctx.runner, doc).locked(e):
        raise LispError("Automation Error. On locked layer")
    snap = e.to_dict()
    good = False
    with edit(L):
        m = d.modify(e.handle)
        try:
            fn_(m)
            good = m.valid()
        except (ValueError, ZeroDivisionError, TypeError):
            good = False
        if not good:
            d.ents[e.handle] = entity_from_dict(snap)
    if not good:
        raise LispError("Automation Error. Invalid argument")


def setter(attr, conv):
    def f(L, o, v):
        val = conv(v)
        change(L, o, lambda m: setattr(m, attr, val))

    return f


def positive(v) -> float:
    x = need_num(v)
    if x <= 0:
        raise LispError("Automation Error. Invalid argument %s" % prin1(v))
    return x


def nonzero(v) -> float:
    x = need_num(v)
    if abs(x) < 1e-12:
        raise LispError("Automation Error. Invalid argument %s" % prin1(v))
    return x


def add_to(L, o, e):
    doc = doc_of(L)
    space = o.key
    if not (space == SPACE_MODEL or space.startswith("layout:")):
        raise LispError("Adding to a block definition is not supported here; build blocks with entmake BLOCK and ENDBLK.")
    Context(L.ctx.runner, doc).stamp(e)
    return e


def commit_new(L, o, e) -> VlaObject:
    if not e.valid():
        raise LispError("Automation Error. Invalid argument")
    with edit(L):
        h = drawing(L).add_entity(e, o.key)
    return obj(L, "ent", h)


def items(L, o) -> list:
    d = drawing(L)
    k = o.kind
    if k == "space":
        return [obj(L, "ent", e.handle) for e in d.entities(o.key)]
    if k == "table":
        if o.key == "blocks":
            return [obj(L, "space", "model")] + [obj(L, "space", "block:" + n) for n in d.tables["blocks"].names()]
        if o.key == "layouts":
            return [obj(L, "rec", ("layouts", "Model"))] + [obj(L, "rec", ("layouts", n)) for n in d.tables["layouts"].names()]
        return [obj(L, "rec", (o.key, n)) for n in d.tables[o.key].names()]
    if k == "docs":
        return [obj(L, "doc")]
    raise LispError("bad argument type: collection %s" % prin1(o))


def record(L, o) -> dict:
    table, name = o.key
    if table == "layouts" and name == "Model":
        return {"name": "Model"}
    rec = drawing(L).table_get(table, name)
    if rec is None:
        raise LispError("Automation Error. Object was erased")
    return rec


def change_record(L, o, fn_) -> None:
    table, name = o.key
    record(L, o)
    with edit(L):
        fn_(drawing(L).modify_record(table, name))


def length_of(e) -> float:
    if e.kind == "line":
        return math.dist(G3(e.start), G3(e.end))
    p = curvepath.build(e)
    return p.length if p is not None else 0.0


def G3(p) -> list:
    return [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]


def area_of(e) -> float:
    try:
        return float(M.entity_measure(e)[0])
    except Exception:
        pass
    p = curvepath.build(e)
    if p is None or p.length <= 0:
        return 0.0
    n = 720
    pts = [p.at(p.length * i / n)[0] for i in range(n + 1)]
    s = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s += a[0] * b[1] - b[0] * a[1]
    return abs(s) / 2.0


@prop("any", "Application")
def p_application(L, o):
    return obj(L, "app")


@prop("app", "ActiveDocument")
def p_active_document(L, o):
    return obj(L, "doc")


@prop("app", "Documents")
def p_documents(L, o):
    return obj(L, "docs")


@prop("app", "Name")
def p_app_name(L, o):
    return "FormCAD"


@prop("app", "Version")
def p_app_version(L, o):
    return __version__


@method("app", "ZoomExtents")
def m_zoom_extents(L, o):
    from app.lisp.lib_cmd import f_command

    f_command(L, "_.ZOOM", "_E")
    return None


@method("app", "ZoomAll")
def m_zoom_all(L, o):
    from app.lisp.lib_cmd import f_command

    f_command(L, "_.ZOOM", "_A")
    return None


@method("app", "Update")
def m_app_update(L, o):
    return None


@prop("docs", "Count")
def p_docs_count(L, o):
    return 1


@method("docs", "Item")
def m_docs_item(L, o, i):
    if unwrap(i) not in (0, doc_of(L).name):
        raise LispError("Automation Error. Invalid index")
    return obj(L, "doc")


@prop("doc", "Name")
def p_doc_name(L, o):
    doc = doc_of(L)
    return os.path.basename(doc.path) if doc.path else (doc.name or "Drawing1.dwg")


@prop("doc", "FullName")
def p_doc_fullname(L, o):
    return doc_of(L).path or ""


@prop("doc", "Path")
def p_doc_path(L, o):
    p = doc_of(L).path
    return os.path.dirname(p) if p else ""


@prop("doc", "Saved")
def p_doc_saved(L, o):
    return not doc_of(L).dirty


@prop("doc", "ModelSpace")
def p_modelspace(L, o):
    return obj(L, "space", SPACE_MODEL)


@prop("doc", "PaperSpace")
def p_paperspace(L, o):
    doc = doc_of(L)
    cur = doc.current_space
    if cur.startswith("layout:"):
        return obj(L, "space", cur)
    names = doc.drawing.tables["layouts"].names()
    if not names:
        raise LispError("Automation Error. The drawing has no layout")
    return obj(L, "space", layout_space(names[0]))


@prop("doc", "ActiveSpace")
def p_active_space(L, o):
    return 1 if doc_of(L).current_space == SPACE_MODEL else 0


@prop("doc", "Utility")
def p_utility(L, o):
    return obj(L, "utility")


@prop("doc", "Document")
def p_doc_self(L, o):
    return obj(L, "doc")


for _table, _prop in (("layers", "Layers"), ("linetypes", "Linetypes"), ("textstyles", "TextStyles"), ("dimstyles", "DimStyles"), ("blocks", "Blocks"), ("layouts", "Layouts")):
    PROPS[("doc", _prop.upper())] = (lambda t: lambda L, o: obj(L, "table", t))(_table)

for _var, _table, _prop in (("CLAYER", "layers", "ActiveLayer"), ("CELTYPE", "linetypes", "ActiveLinetype"), ("TEXTSTYLE", "textstyles", "ActiveTextStyle"), ("DIMSTYLE", "dimstyles", "ActiveDimStyle")):

    def _get(L, o, var=_var, table=_table):
        name = str(drawing(L).header.get(var, "0" if var == "CLAYER" else "Standard"))
        rec = drawing(L).table_get(table, name)
        if rec is None:
            raise LispError("Automation Error. %s is not set" % var)
        return obj(L, "rec", (table, rec["name"]))

    def _put(L, o, v, var=_var, table=_table):
        r = vobj(v)
        if r.kind != "rec" or r.key[0] != table:
            raise LispError("bad argument type: %s object %s" % (table, prin1(v)))
        try:
            sv.set_var(doc_of(L), var, r.key[1], radians=True, create=False)
        except sv.SysvarError as err:
            raise LispError("Automation Error. %s" % err)

    PROPS[("doc", _prop.upper())] = _get
    SETS[("doc", _prop.upper())] = _put


@prop("doc", "ActiveLayout")
def p_active_layout(L, o):
    cur = doc_of(L).current_space
    return obj(L, "rec", ("layouts", cur[7:] if cur.startswith("layout:") else "Model"))


@method("doc", "StartUndoMark")
def m_start_undo(L, o):
    return None


@method("doc", "EndUndoMark")
def m_end_undo(L, o):
    return None


@method("doc", "Regen")
def m_regen(L, o, which=None):
    return None


@method("doc", "GetVariable")
def m_getvar(L, o, name):
    from app.lisp.lib_tbl import f_getvar

    v = f_getvar(L, need_str(name))
    return Boxed(Pt(to_list(v)) if type(v) is Cons else v)


@method("doc", "SetVariable")
def m_setvar(L, o, name, value):
    from app.lisp.lib_tbl import f_setvar

    u = value.value if type(value) is Variant else value
    if type(u) is SafeArray:
        u = from_list(unwrap(u))
    f_setvar(L, need_str(name), u)
    return None


@method("doc", "HandleToObject")
def m_handle_to_object(L, o, h):
    try:
        v = int(need_str(h).strip(), 16)
    except ValueError:
        raise LispError("Automation Error. Invalid object handle")
    if drawing(L).get(v) is None:
        raise LispError("Automation Error. Invalid object handle")
    return obj(L, "ent", v)


@method("doc", "SendCommand")
def m_send_command(L, o, text):
    from app.lisp.lib_cmd import f_command

    words = re.split(r"[ \n\r]", need_str(text))
    if words and words[-1] == "":
        words.pop()
    if words:
        f_command(L, *words)
    return None


@prop("table", "Count")
def p_table_count(L, o):
    return len(items(L, o))


@prop("space", "Count")
def p_space_count(L, o):
    return len(drawing(L).spaces.get(o.key, ()))


@method("table space", "Item")
def m_item(L, o, i):
    u = unwrap(i)
    found = items(L, o)
    if type(u) is int:
        if 0 <= u < len(found):
            return found[u]
        raise LispError("Automation Error. Invalid index")
    if type(u) is str and o.kind == "table":
        low = u.casefold()
        for it in found:
            if record_name(L, it).casefold() == low:
                return it
        raise LispError("Automation Error. Key not found")
    raise LispError("bad argument type: index %s" % prin1(i))


def record_name(L, it) -> str:
    if it.kind == "rec":
        return it.key[1]
    if it.key == SPACE_MODEL:
        return "*Model_Space"
    return it.key.split(":", 1)[1]


@method("table:layers", "Add")
def m_layers_add(L, o, name):
    n = need_str(name)
    if not n or len(n) > 255 or any(c in BAD_LAYER_CHARS for c in n):
        raise LispError("Automation Error. Invalid layer name %s" % prin1(name))
    d = drawing(L)
    rec = d.table_get("layers", n)
    if rec is None:
        with edit(L):
            d.table_set("layers", TB.new_layer(n))
        rec = d.table_get("layers", n)
    return obj(L, "rec", ("layers", rec["name"]))


@prop("rec space", "Name")
def p_rec_name(L, o):
    if o.kind == "space":
        return record_name(L, o)
    return record(L, o)["name"]


@prop("space", "Origin")
def p_space_origin(L, o):
    if not o.key.startswith("block:"):
        return Pt([0.0, 0.0, 0.0])
    rec = drawing(L).table_get("blocks", o.key[6:])
    return Pt(G3(rec["base"])) if rec else Pt([0.0, 0.0, 0.0])


@prop("rec:layouts", "Block")
def p_layout_block(L, o):
    name = o.key[1]
    return obj(L, "space", SPACE_MODEL if name == "Model" else layout_space(name))


def layer_prop(key, conv_get, conv_put):
    NAMES[key[0].upper()] = key[0]
    PROPS[("rec:layers", key[0].upper())] = lambda L, o: conv_get(record(L, o).get(key[1]))

    def f(L, o, v):
        val = conv_put(L, o, v)
        change_record(L, o, lambda r: r.__setitem__(key[1], val))

    SETS[("rec:layers", key[0].upper())] = f


def _layer_color(L, o, v):
    c = need_int(v)
    if not 1 <= c <= 255:
        raise LispError("Automation Error. Invalid color %d" % c)
    return c


def _layer_ltype(L, o, v):
    n = need_str(v)
    rec = drawing(L).table_get("linetypes", n)
    if rec is None:
        raise LispError("Automation Error. Key not found")
    return rec["name"]


def _layer_freeze(L, o, v):
    b = need_bool(v)
    if b and drawing(L).current_layer().casefold() == o.key[1].casefold():
        raise LispError("Automation Error. The current layer cannot be frozen")
    return b


layer_prop(("Color", "color"), lambda c: int(c) if isinstance(c, int) else 7, _layer_color)
layer_prop(("LayerOn", "on"), bool, lambda L, o, v: need_bool(v))
layer_prop(("Freeze", "frozen"), bool, _layer_freeze)
layer_prop(("Lock", "locked"), bool, lambda L, o, v: need_bool(v))
layer_prop(("Plottable", "plot"), bool, lambda L, o, v: need_bool(v))
layer_prop(("Linetype", "linetype"), lambda s: s or "Continuous", _layer_ltype)
layer_prop(("Lineweight", "lineweight"), lambda w: int(w) if isinstance(w, (int, float)) else -3, lambda L, o, v: need_int(v))
layer_prop(("Description", "description"), lambda s: s or "", lambda L, o, v: need_str(v))


@prop("rec:textstyles", "Height")
def p_style_height(L, o):
    return float(record(L, o).get("height", 0.0))


@prop("rec:textstyles", "Width")
def p_style_width(L, o):
    return float(record(L, o).get("width_factor", 1.0))


@prop("rec:textstyles", "FontFile")
def p_style_font(L, o):
    return str(record(L, o).get("font", ""))


@prop("rec:linetypes", "Description")
def p_ltype_desc(L, o):
    return str(record(L, o).get("description", ""))


@prop("ent attrib", "Document")
def p_ent_doc(L, o):
    return obj(L, "doc")


@prop("ent", "Handle")
def p_handle(L, o):
    return "%X" % ent(L, o).handle


@prop("ent", "ObjectID")
def p_object_id(L, o):
    return int(ent(L, o).handle)


@prop("ent", "ObjectName")
def p_object_name(L, o):
    e = ent(L, o)
    return OBJECT_NAMES.get(e.kind, "AcDb" + e.kind.capitalize())


PROPS[("ent", "ENTITYNAME")] = p_object_name


@prop("ent", "Layer")
def p_layer(L, o):
    return ent(L, o).layer or "0"


@put("ent", "Layer")
def s_layer(L, o, v):
    n = need_str(v)
    rec = drawing(L).table_get("layers", n)
    if rec is None:
        raise LispError("Automation Error. Key not found")
    change(L, o, lambda m: setattr(m, "layer", rec["name"]))


@prop("ent", "Color")
def p_color(L, o):
    c = ent(L, o).color
    return int(c) if isinstance(c, int) else 256


@put("ent", "Color")
def s_color(L, o, v):
    c = need_int(v)
    if not 0 <= c <= 256:
        raise LispError("Automation Error. Invalid color %d" % c)
    change(L, o, lambda m: setattr(m, "color", c))


@prop("ent", "Linetype")
def p_linetype(L, o):
    return ent(L, o).linetype or "ByLayer"


@put("ent", "Linetype")
def s_linetype(L, o, v):
    n = need_str(v)
    if n.casefold() in ("bylayer", "byblock"):
        name = "ByLayer" if n.casefold() == "bylayer" else "ByBlock"
    else:
        rec = drawing(L).table_get("linetypes", n)
        if rec is None:
            raise LispError("Automation Error. Key not found")
        name = rec["name"]
    change(L, o, lambda m: setattr(m, "linetype", name))


@prop("ent", "LinetypeScale")
def p_ltscale(L, o):
    return float(ent(L, o).ltscale)


SETS[("ent", "LINETYPESCALE")] = setter("ltscale", positive)


@prop("ent", "Lineweight")
def p_lineweight(L, o):
    w = ent(L, o).lineweight
    return int(w) if isinstance(w, (int, float)) else -1


@put("ent", "Lineweight")
def s_lineweight(L, o, v):
    w = need_int(v)
    if not (w in (-1, -2, -3) or 0 <= w <= 211):
        raise LispError("Automation Error. Invalid lineweight %d" % w)
    change(L, o, lambda m: setattr(m, "lineweight", w))


@prop("ent", "Visible")
def p_visible(L, o):
    return bool(ent(L, o).visible)


SETS[("ent", "VISIBLE")] = setter("visible", need_bool)


@prop("ent", "Thickness")
def p_thickness(L, o):
    return float(getattr(ent(L, o), "thickness", 0.0) or 0.0)


SETS[("ent", "THICKNESS")] = setter("thickness", need_num)


@prop("ent", "Normal")
def p_normal(L, o):
    return Pt(G3(ent(L, o).normal or [0.0, 0.0, 1.0]))


def point_prop(groups, name, attr):
    NAMES[name.upper()] = name
    PROPS.update({(g, name.upper()): (lambda a: lambda L, o: Pt(G3(getattr(ent(L, o), a))))(attr) for g in groups.split()})
    SETS.update({(g, name.upper()): setter(attr, need_pt) for g in groups.split()})


def number_prop(groups, name, attr, conv=need_num):
    NAMES[name.upper()] = name
    PROPS.update({(g, name.upper()): (lambda a: lambda L, o: float(getattr(ent(L, o), a)))(attr) for g in groups.split()})
    SETS.update({(g, name.upper()): setter(attr, conv) for g in groups.split()})


def text_prop(groups, name, attr):
    NAMES[name.upper()] = name
    PROPS.update({(g, name.upper()): (lambda a: lambda L, o: str(getattr(ent(L, o), a) or ""))(attr) for g in groups.split()})
    SETS.update({(g, name.upper()): setter(attr, need_str) for g in groups.split()})


point_prop("ent:line", "StartPoint", "start")
point_prop("ent:line", "EndPoint", "end")
point_prop("ent:circle ent:arc ent:ellipse", "Center", "center")
point_prop("ent:point", "Coordinates", "position")
point_prop("ent:text ent:mtext ent:attdef", "InsertionPoint", "position")
point_prop("ent:insert", "InsertionPoint", "position")
point_prop("ent:ray ent:xline", "BasePoint", "base")
point_prop("ent:ray ent:xline", "DirectionVector", "direction")
point_prop("ent:ellipse", "MajorAxis", "major")
number_prop("ent:circle ent:arc", "Radius", "radius", positive)
number_prop("ent:arc", "StartAngle", "start_angle")
number_prop("ent:arc", "EndAngle", "end_angle")
number_prop("ent:ellipse", "StartParameter", "start_param")
number_prop("ent:ellipse", "EndParameter", "end_param")
number_prop("ent:text ent:mtext ent:attdef", "Height", "height", positive)
number_prop("ent:text ent:mtext ent:attdef ent:insert", "Rotation", "rotation")
number_prop("ent:text", "ScaleFactor", "width_factor", positive)
number_prop("ent:text", "ObliqueAngle", "oblique")
number_prop("ent:mtext", "Width", "width")
number_prop("ent:lwpolyline", "ConstantWidth", "const_width")
number_prop("ent:lwpolyline", "Elevation", "elevation")
text_prop("ent:text", "TextString", "text")
text_prop("ent:mtext", "TextString", "contents")
text_prop("ent:attdef", "TextString", "default")
text_prop("ent:attdef", "TagString", "tag")
text_prop("ent:attdef", "PromptString", "prompt")


@prop("ent:text ent:mtext ent:attdef", "StyleName")
def p_style_name(L, o):
    return str(ent(L, o).style or "Standard")


@put("ent:text ent:mtext ent:attdef", "StyleName")
def s_style_name(L, o, v):
    rec = drawing(L).table_get("textstyles", need_str(v))
    if rec is None:
        raise LispError("Automation Error. Key not found")
    change(L, o, lambda m: setattr(m, "style", rec["name"]))


@prop("ent:mtext", "AttachmentPoint")
def p_attachment(L, o):
    return int(ent(L, o).attachment)


@put("ent:mtext", "AttachmentPoint")
def s_attachment(L, o, v):
    a = need_int(v)
    if not 1 <= a <= 9:
        raise LispError("Automation Error. Invalid attachment point %d" % a)
    change(L, o, lambda m: setattr(m, "attachment", a))


@prop("ent:line", "Length")
def p_line_length(L, o):
    e = ent(L, o)
    return math.dist(G3(e.start), G3(e.end))


@prop("ent:line", "Angle")
def p_line_angle(L, o):
    e = ent(L, o)
    return geom.norm_angle(math.atan2(e.end[1] - e.start[1], e.end[0] - e.start[0]))


@prop("ent:line", "Delta")
def p_line_delta(L, o):
    e = ent(L, o)
    a, b = G3(e.start), G3(e.end)
    return Pt([b[i] - a[i] for i in range(3)])


@prop("ent:circle", "Diameter")
def p_diameter(L, o):
    return 2.0 * float(ent(L, o).radius)


@put("ent:circle", "Diameter")
def s_diameter(L, o, v):
    r = positive(v) / 2.0
    change(L, o, lambda m: setattr(m, "radius", r))


@prop("ent:circle", "Circumference")
def p_circumference(L, o):
    return 2.0 * math.pi * float(ent(L, o).radius)


@prop("ent:circle ent:arc ent:ellipse ent:lwpolyline ent:polyline3d ent:spline ent:hatch ent:region ent:solid", "Area")
def p_area(L, o):
    return area_of(ent(L, o))


@prop("ent:arc ent:lwpolyline ent:polyline3d ent:spline ent:ellipse", "Length")
def p_curve_length(L, o):
    return length_of(ent(L, o))


PROPS[("ent:arc", "ARCLENGTH")] = p_curve_length


@prop("ent:arc", "TotalAngle")
def p_total_angle(L, o):
    e = ent(L, o)
    return geom.ccw_sweep(e.start_angle, e.end_angle)


@prop("ent:arc ent:ellipse", "StartPoint")
def p_start_point(L, o):
    return Pt(curve_point(L, ent(L, o), 0.0))


@prop("ent:arc ent:ellipse", "EndPoint")
def p_end_point(L, o):
    e = ent(L, o)
    return Pt(curve_point(L, e, length_of(e)))


@prop("ent:ellipse", "RadiusRatio")
def p_ratio(L, o):
    return float(ent(L, o).ratio)


@put("ent:ellipse", "RadiusRatio")
def s_ratio(L, o, v):
    r = need_num(v)
    if not 0.0 < r <= 1.0:
        raise LispError("Automation Error. Invalid argument %s" % prin1(v))
    change(L, o, lambda m: setattr(m, "ratio", r))


@prop("ent:ellipse", "MinorAxis")
def p_minor(L, o):
    e = ent(L, o)
    return Pt([-e.major[1] * e.ratio, e.major[0] * e.ratio, 0.0])


@prop("ent:ray ent:xline", "SecondPoint")
def p_second(L, o):
    e = ent(L, o)
    b, d = G3(e.base), G3(e.direction)
    return Pt([b[i] + d[i] for i in range(3)])


@put("ent:ray ent:xline", "SecondPoint")
def s_second(L, o, v):
    p = need_pt(v)

    def f(m):
        b = G3(m.base)
        m.direction = [p[i] - b[i] for i in range(3)]

    change(L, o, f)


@prop("ent:lwpolyline", "Coordinates")
def p_lw_coords(L, o):
    return Dbl([c for v in ent(L, o).vertices for c in (float(v["p"][0]), float(v["p"][1]))])


@put("ent:lwpolyline", "Coordinates")
def s_lw_coords(L, o, v):
    flat = need_doubles(v, 2, 2)

    def f(m):
        old = m.vertices
        out = []
        for i in range(0, len(flat), 2):
            k = i // 2
            base = dict(old[k]) if k < len(old) else {"bulge": 0.0, "sw": 0.0, "ew": 0.0}
            base["p"] = [flat[i], flat[i + 1]]
            out.append(base)
        m.vertices = out

    change(L, o, f)


@prop("ent:polyline3d", "Coordinates")
def p_3d_coords(L, o):
    return Dbl([c for p in ent(L, o).points for c in G3(p)])


@put("ent:polyline3d", "Coordinates")
def s_3d_coords(L, o, v):
    flat = need_doubles(v, 3, 2)
    change(L, o, lambda m: setattr(m, "points", [flat[i : i + 3] for i in range(0, len(flat), 3)]))


@prop("ent:lwpolyline ent:polyline3d ent:spline", "Closed")
def p_closed(L, o):
    return bool(ent(L, o).closed)


SETS[("ent:lwpolyline", "CLOSED")] = setter("closed", need_bool)
SETS[("ent:polyline3d", "CLOSED")] = setter("closed", need_bool)


def vertex_index(e, i) -> int:
    k = need_int(i)
    if not 0 <= k < len(e.vertices):
        raise LispError("Automation Error. Invalid index")
    return k


@method("ent:lwpolyline", "GetBulge")
def m_get_bulge(L, o, i):
    e = ent(L, o)
    return float(e.vertices[vertex_index(e, i)].get("bulge", 0.0) or 0.0)


@method("ent:lwpolyline", "SetBulge")
def m_set_bulge(L, o, i, b):
    k = vertex_index(ent(L, o), i)
    val = need_num(b)
    change(L, o, lambda m: m.vertices[k].__setitem__("bulge", val))
    return None


@method("ent:lwpolyline", "AddVertex")
def m_add_vertex(L, o, i, p):
    e = ent(L, o)
    k = need_int(i)
    if not 0 <= k <= len(e.vertices):
        raise LispError("Automation Error. Invalid index")
    q = need_doubles(p, 2, 1)
    change(L, o, lambda m: m.vertices.insert(k, {"p": [q[0], q[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0}))
    return None


@prop("ent:spline", "Degree")
def p_degree(L, o):
    return int(ent(L, o).degree)


@prop("ent:spline", "NumberOfControlPoints")
def p_ncp(L, o):
    return len(ent(L, o).control_points)


@prop("ent:spline", "NumberOfFitPoints")
def p_nfp(L, o):
    return len(ent(L, o).fit_points)


@prop("ent:spline", "ControlPoints")
def p_cps(L, o):
    return Dbl([c for p in ent(L, o).control_points for c in G3(p)])


@prop("ent:spline", "FitPoints")
def p_fps(L, o):
    return Dbl([c for p in ent(L, o).fit_points for c in G3(p)])


@prop("ent:insert", "Name")
def p_insert_name(L, o):
    return ent(L, o).block


PROPS[("ent:insert", "EFFECTIVENAME")] = lambda L, o: str(ent(L, o).extra.get("effective_name") or ent(L, o).block)


@put("ent:insert", "Name")
def s_insert_name(L, o, v):
    rec = blockdefs.lookup(drawing(L), need_str(v))
    if rec is None:
        raise LispError("Automation Error. Key not found")
    d = drawing(L)

    def f(m):
        m.block = rec["name"]
        attribs.sync_insert(d, m)

    change(L, o, f)


for _i, _axis in enumerate("XYZ"):

    def _scale_get(L, o, i=_i):
        s = list(ent(L, o).scale) + [1.0, 1.0, 1.0]
        return float(s[i])

    def _scale_put(L, o, v, i=_i):
        k = nonzero(v)

        def f(m):
            s = (list(m.scale) + [1.0, 1.0, 1.0])[:3]
            s[i] = k
            m.scale = s

        change(L, o, f)

    PROPS[("ent:insert", _axis + "SCALEFACTOR")] = _scale_get
    SETS[("ent:insert", _axis + "SCALEFACTOR")] = _scale_put


@prop("ent:insert", "HasAttributes")
def p_has_attributes(L, o):
    return bool(ent(L, o).attributes)


@method("ent:insert", "GetAttributes")
def m_get_attributes(L, o):
    e = ent(L, o)
    return Objs([obj(L, "attrib", (e.handle, str(a.get("tag", "")).casefold())) for a in (e.attributes or [])])


def attribute(L, o):
    h, tag = o.key
    e = drawing(L).get(h)
    if e is None:
        raise LispError("Automation Error. Object was erased")
    for i, a in enumerate(e.attributes or []):
        if str(a.get("tag", "")).casefold() == tag:
            return e, i
    raise LispError("Automation Error. Object was erased")


@prop("attrib", "TagString")
def p_att_tag(L, o):
    e, i = attribute(L, o)
    return str(e.attributes[i].get("tag", ""))


@prop("attrib", "TextString")
def p_att_text(L, o):
    e, i = attribute(L, o)
    return str(e.attributes[i].get("value", ""))


@put("attrib", "TextString")
def s_att_text(L, o, v):
    e, i = attribute(L, o)
    text = attribs.check_value(need_str(v))
    d = drawing(L)

    def f(m):
        m.attributes[i]["value"] = text
        attribs.refresh_cache(d, m)

    change(L, obj(L, "ent", e.handle), f)


@prop("attrib", "Invisible")
def p_att_invisible(L, o):
    e, i = attribute(L, o)
    return not e.attributes[i].get("vis", True)


@put("attrib", "Invisible")
def s_att_invisible(L, o, v):
    e, i = attribute(L, o)
    hide = need_bool(v)
    change(L, obj(L, "ent", e.handle), lambda m: m.attributes[i].__setitem__("vis", not hide))


@prop("attrib", "ObjectName")
def p_att_name(L, o):
    return "AcDbAttribute"


@method("ent", "Delete")
def m_delete(L, o):
    doc = doc_of(L)
    e = ent(L, o)
    if Context(L.ctx.runner, doc).locked(e):
        raise LispError("Automation Error. On locked layer")
    with edit(L):
        doc.drawing.erase_entity(e.handle)
    return None


@method("ent", "Update")
def m_update(L, o):
    ent(L, o)
    return None


@method("ent", "Highlight")
def m_highlight(L, o, flag):
    ent(L, o)
    return None


@method("ent", "Move")
def m_move(L, o, a, b):
    p, q = need_pt(a), need_pt(b)
    vec = [q[i] - p[i] for i in range(3)]
    change(L, o, lambda m: m.move_by(vec))
    return None


def transformed(L, o, fn_, copy: bool):
    from app.cmd import grips

    doc = doc_of(L)
    d = doc.drawing
    e = ent(L, o)
    if not copy and Context(L.ctx.runner, doc).locked(e):
        raise LispError("Automation Error. On locked layer")
    c = e.copy_as_new()
    try:
        fn_(c)
    except (grips.GripError, ValueError, ZeroDivisionError):
        raise LispError("Automation Error. The object cannot be changed that way")
    if not c.valid():
        raise LispError("Automation Error. Invalid argument")
    with edit(L):
        if copy:
            return obj(L, "ent", d.add_entity(c, e.owner))
        grips._assign(d.modify(e.handle), c)
    return None


@method("ent", "Copy")
def m_copy(L, o):
    return transformed(L, o, lambda c: None, True)


@method("ent", "Rotate")
def m_rotate(L, o, base, angle):
    from app.cmd.commands.modify_transform import rotate_fn

    return transformed(L, o, rotate_fn(need_pt(base), need_num(angle)), False)


@method("ent", "ScaleEntity")
def m_scale(L, o, base, k):
    from app.cmd.commands.modify_transform import scale_fn

    b = need_pt(base)
    return transformed(L, o, scale_fn(b, positive(k), b[2]), False)


@method("ent", "Mirror")
def m_mirror(L, o, a, b):
    from app.cmd.commands.modify_transform import mirror_fn

    p, q = need_pt(a), need_pt(b)
    if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-12:
        raise LispError("Automation Error. Invalid argument")
    mirrtext = bool(drawing(L).header.get("MIRRTEXT", 0))
    return transformed(L, o, mirror_fn(p, q, mirrtext), True)


def set_out(L, target, value) -> None:
    if type(target) is not Sym or target is T:
        raise LispError("bad argument type: symbolp %s" % prin1(target))
    L.syms[target] = value


@method("ent", "GetBoundingBox")
def m_bbox(L, o, lo, hi):
    e = ent(L, o)
    b = e.bounds()
    if not b:
        raise LispError("Automation Error. The object has no extents")
    z = G3(getattr(e, "position", None) or getattr(e, "center", None) or getattr(e, "start", None) or [0.0, 0.0, 0.0])[2]
    set_out(L, lo, to_vla(Pt([b[0], b[1], z])).value)
    set_out(L, hi, to_vla(Pt([b[2], b[3], z])).value)
    return None


def extended_prims(e, extend: bool):
    if extend and e.kind == "line":
        d = math.hypot(e.end[0] - e.start[0], e.end[1] - e.start[1])
        if d < 1e-12:
            return []
        ux, uy = (e.end[0] - e.start[0]) / d, (e.end[1] - e.start[1]) / d
        reach = 1e6 + d
        return [curves2d.line_prim((e.start[0] - ux * reach, e.start[1] - uy * reach), (e.start[0] + ux * reach, e.start[1] + uy * reach), e.handle, 0)]
    if extend and e.kind == "arc":
        return [curves2d.arc_prim(e.center, e.radius, 0.0, geom.TAU, e.handle, 0)]
    return curves2d.prims_of(e)


@method("ent", "IntersectWith")
def m_intersect(L, o, other, mode=0):
    a = ent(L, o)
    b = ent(L, vobj(other))
    k = need_int(mode)
    if not 0 <= k <= 3:
        raise LispError("Automation Error. Invalid argument %s" % prin1(mode))
    pa = extended_prims(a, k in (1, 3))
    pb = extended_prims(b, k in (2, 3))
    out = []
    for x in pa:
        for y in pb:
            for t, _u in curves2d.intersections(x, y, 1e-9):
                px, py = x.at(t)
                if not any(abs(px - q[0]) < 1e-9 and abs(py - q[1]) < 1e-9 for q in out):
                    out.append((px, py))
                if len(out) > MAX_ARRAY // 3:
                    raise LispError("too many intersections")
    return Dbl([c for p in out for c in (float(p[0]), float(p[1]), 0.0)])


def space_add(name):
    def wrap(f):
        def run(L, o, *args):
            return commit_new(L, o, add_to(L, o, f(L, *args)))

        METHODS[("space", name.upper())] = run
        return f

    return wrap


@space_add("AddLine")
def a_line(L, p, q):
    return Line(start=need_pt(p), end=need_pt(q))


@space_add("AddCircle")
def a_circle(L, c, r):
    return Circle(center=need_pt(c), radius=positive(r))


@space_add("AddArc")
def a_arc(L, c, r, sa, ea):
    return Arc(center=need_pt(c), radius=positive(r), start_angle=need_num(sa), end_angle=need_num(ea))


@space_add("AddPoint")
def a_point(L, p):
    return Point(position=need_pt(p))


@space_add("AddText")
def a_text(L, s, p, h):
    return Text(text=need_str(s), position=need_pt(p), height=positive(h))


@space_add("AddMText")
def a_mtext(L, p, w, s):
    return MText(position=need_pt(p), width=need_num(w), contents=need_str(s), height=float(drawing(L).header.get("TEXTSIZE", 2.5)))


def lw_from(flat2, closed=False, elevation=0.0):
    verts = [{"p": [flat2[i], flat2[i + 1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0} for i in range(0, len(flat2), 2)]
    return LwPolyline(vertices=verts, closed=closed, elevation=elevation)


@space_add("AddLightWeightPolyline")
def a_lwpoly(L, coords):
    return lw_from(need_doubles(coords, 2, 2))


@space_add("AddPolyline")
def a_poly(L, coords):
    flat = need_doubles(coords, 3, 2)
    return lw_from([c for i in range(0, len(flat), 3) for c in flat[i : i + 2]], False, flat[2])


@space_add("Add3DPoly")
def a_3dpoly(L, coords):
    flat = need_doubles(coords, 3, 2)
    return Polyline3d(points=[flat[i : i + 3] for i in range(0, len(flat), 3)])


@space_add("AddEllipse")
def a_ellipse(L, c, major, ratio):
    r = need_num(ratio)
    if not 0.0 < r <= 1.0:
        raise LispError("Automation Error. Invalid argument %s" % prin1(ratio))
    return Ellipse(center=need_pt(c), major=need_pt(major), ratio=r, start_param=0.0, end_param=geom.TAU)


@space_add("AddXline")
def a_xline(L, p, q):
    a, b = need_pt(p), need_pt(q)
    return XLine(base=a, direction=[b[i] - a[i] for i in range(3)])


@space_add("AddRay")
def a_ray(L, p, q):
    a, b = need_pt(p), need_pt(q)
    return Ray(base=a, direction=[b[i] - a[i] for i in range(3)])


@space_add("InsertBlock")
def a_insert(L, p, name, xs, ys, zs, rot):
    try:
        return blockdefs.new_insert(drawing(L), need_str(name), need_pt(p), [nonzero(xs), nonzero(ys), nonzero(zs)], need_num(rot))
    except blockdefs.BlockError as err:
        raise LispError("Automation Error. %s" % err)


def ask_args(base, msg) -> list:
    text = need_str(msg) if msg is not None else None
    if unwrap(base) in (None, []):
        return [text]
    return [from_list(need_pt(base)), text]


@method("utility", "GetPoint")
def u_getpoint(L, o, base=None, msg=None):
    from app.lisp.lib_input import f_getpoint

    p = f_getpoint(L, *ask_args(base, msg))
    if p is None:
        raise LispError("Automation Error. No point was given")
    return Pt(to_list(p))


@method("utility", "GetEntity")
def u_getentity(L, o, osym, psym, msg=None):
    from app.lisp.lib_input import f_entsel

    r = f_entsel(L, need_str(msg) if msg is not None else None)
    if r is None:
        raise LispError("Automation Error. No object was selected")
    set_out(L, osym, obj(L, "ent", r.a.handle))
    set_out(L, psym, to_vla(Pt(to_list(r.d.a))).value)
    return None


@method("utility", "GetString")
def u_getstring(L, o, spaces, msg=None):
    from app.lisp.lib_input import f_getstring

    return f_getstring(L, T if need_bool(spaces) else None, need_str(msg) if msg is not None else "") or ""


def utility_number(fname, label):
    def run(L, o, msg=None):
        from app.lisp import lib_input

        v = getattr(lib_input, fname)(L, need_str(msg) if msg is not None else None)
        if v is None:
            raise LispError("Automation Error. No %s was given" % label)
        return v

    return run


METHODS[("utility", "GETREAL")] = utility_number("f_getreal", "number")
METHODS[("utility", "GETINTEGER")] = utility_number("f_getint", "integer")
METHODS[("utility", "GETKEYWORD")] = utility_number("f_getkword", "keyword")


@method("utility", "GetDistance")
def u_getdist(L, o, base=None, msg=None):
    from app.lisp.lib_input import f_getdist

    v = f_getdist(L, *ask_args(base, msg))
    if v is None:
        raise LispError("Automation Error. No distance was given")
    return v


@method("utility", "GetAngle")
def u_getangle(L, o, base=None, msg=None):
    from app.lisp.lib_input import f_getangle

    v = f_getangle(L, *ask_args(base, msg))
    if v is None:
        raise LispError("Automation Error. No angle was given")
    return v


@method("utility", "InitializeUserInput")
def u_initget(L, o, bits, kw=None):
    from app.lisp.lib_input import f_initget

    f_initget(L, need_int(bits), *([need_str(kw)] if kw is not None else []))
    return None


@method("utility", "Prompt")
def u_prompt(L, o, msg):
    from app.lisp.lib_misc import f_prompt

    f_prompt(L, need_str(msg))
    return None


@method("utility", "PolarPoint")
def u_polar(L, o, p, ang, dist):
    b = need_pt(p)
    a, d = need_num(ang), need_num(dist)
    return Pt([b[0] + d * math.cos(a), b[1] + d * math.sin(a), b[2]])


@method("utility", "AngleFromXAxis")
def u_angle_x(L, o, p, q):
    a, b = need_pt(p), need_pt(q)
    return geom.norm_angle(math.atan2(b[1] - a[1], b[0] - a[0]))


def register() -> None:
    for (_g, name) in list(PROPS):
        key = "VLA-GET-" + name
        if sym(key) not in BUILTIN:
            BUILTIN[sym(key)] = Subr(key, (lambda n: lambda L, o: to_vla(get_prop(L, vobj(o), n)))(name), 1, 1)
    for (_g, name) in list(SETS):
        key = "VLA-PUT-" + name
        if sym(key) not in BUILTIN:
            BUILTIN[sym(key)] = Subr(key, (lambda n: lambda L, o, v: put_prop(L, vobj(o), n, v))(name), 2, 2)
    for (_g, name) in list(METHODS):
        key = "VLA-" + name
        if sym(key) not in BUILTIN:
            BUILTIN[sym(key)] = Subr(key, (lambda n: lambda L, o, *a: to_vla(call_method(L, vobj(o), n, list(a))))(name), 1, None)


@fn("vlax-get-acad-object", 0, 0)
def f_acad(L):
    return obj(L, "app")


@fn("vlax-get-property", 2, 2)
def f_get_property(L, o, p):
    return to_vla(get_prop(L, vobj(o), pname(p)))


@fn("vlax-put-property", 3, 3)
def f_put_property(L, o, p, v):
    put_prop(L, vobj(o), pname(p), v)
    return None


@fn("vlax-invoke-method", 2, None)
def f_invoke_method(L, o, m, *args):
    return to_vla(call_method(L, vobj(o), pname(m), list(args)))


@fn("vlax-get", 2, 2)
def f_get(L, o, p):
    return to_plain(get_prop(L, vobj(o), pname(p)))


@fn("vlax-put", 3, 3)
def f_put(L, o, p, v):
    put_prop(L, vobj(o), pname(p), v)
    return None


@fn("vlax-invoke", 2, None)
def f_invoke(L, o, m, *args):
    r = call_method(L, vobj(o), pname(m), list(args))
    if type(r) is Dbl and not r:
        return None
    return to_plain(r)


@fn("vlax-ename->vla-object", 1, 1)
def f_ename_to_obj(L, en):
    if type(en) is not EName:
        raise LispError("bad argument type: lentityp %s" % prin1(en))
    if drawing(L).get(en.handle) is None:
        raise LispError("Automation Error. Object was erased")
    return obj(L, "ent", en.handle)


@fn("vlax-vla-object->ename", 1, 1)
def f_obj_to_ename(L, o):
    o = vobj(o)
    if o.kind != "ent":
        raise LispError("bad argument type: entity object %s" % prin1(o))
    return EName(o.key)


@fn("vlax-property-available-p", 2, 3)
def f_prop_available(L, o, p, check=None):
    o = vobj(o)
    if o.kind == "ent" and drawing(L).get(o.key) is None:
        return None
    return T if has_prop(L, o, pname(p), check is not None) else None


@fn("vlax-method-applicable-p", 2, 2)
def f_method_applicable(L, o, m):
    o = vobj(o)
    if o.kind == "ent" and drawing(L).get(o.key) is None:
        return None
    n = pname(m)
    return T if any((g, n) in METHODS for g in groups_of(L, o)) else None


@fn("vlax-release-object", 1, 1)
def f_release(L, o):
    return None


@fn("vlax-object-released-p", 1, 1)
def f_released_p(L, o):
    vobj(o)
    return None


@fn("vlax-erased-p", 1, 1)
def f_erased_p(L, o):
    o = vobj(o)
    if o.kind == "ent":
        return T if drawing(L).get(o.key) is None else None
    return None


@fn("vlax-read-enabled-p", 1, 1)
def f_read_enabled(L, o):
    o = vobj(o)
    return None if o.kind == "ent" and drawing(L).get(o.key) is None else T


@fn("vlax-write-enabled-p", 1, 1)
def f_write_enabled(L, o):
    o = vobj(o)
    if o.kind != "ent":
        return T
    e = drawing(L).get(o.key)
    return T if e is not None and not Context(L.ctx.runner, doc_of(L)).locked(e) else None


@fn("vlax-typeinfo-available-p", 1, 1)
def f_typeinfo(L, o):
    vobj(o)
    return T


@fn("vlax-dump-object", 1, 2)
def f_dump(L, o, methods=None):
    from app.lisp.lib_misc import f_princ

    o = vobj(o)
    gs = groups_of(L, o)
    lines = ["; %s object" % o.label]
    seen = set()
    for (g, n) in PROPS:
        if g in gs and n not in seen:
            seen.add(n)
            try:
                v = to_vla(get_prop(L, o, n))
                text = str(v) if type(v) in (Variant, VlaObject) else prin1(v)
            except LispError as err:
                text = "Exception occurred: %s" % err.msg
            ro = "" if any((x, n) in SETS for x in gs) else " (RO)"
            lines.append(";   %s%s = %s" % (shown(n), ro, text))
    if methods is not None:
        lines.append("; Methods supported:")
        for (g, n) in METHODS:
            if g in gs:
                lines.append(";   %s" % shown(n))
    f_princ(L, "\n".join(lines) + "\n")
    return T


@fn("vlax-map-collection", 2, 2)
def f_map_collection(L, o, f):
    for it in items(L, vobj(o)):
        L.callback(f, [it])
    return o


@special("vlax-for")
def sf_vlax_for(L, a):
    if a is None or a.d is None:
        raise LispError("too few arguments")
    var = a.a
    if type(var) is not Sym:
        raise LispError("bad argument type: symbolp %s" % prin1(var))
    coll = vobj(L.ev(a.d.a), "collection")
    body = a.d.d
    syms = L.syms
    old = syms.get(var, MISSING)
    last = None
    try:
        for it in items(L, coll):
            syms[var] = it
            b = body
            while type(b) is Cons:
                last = L.ev(b.a)
                b = b.d
            L.tick()
    finally:
        if old is MISSING:
            syms.pop(var, None)
        else:
            syms[var] = old
    return last


@fn("vlax-create-object", 1, 1)
def f_create_object(L, name):
    raise LispError("Only the drawing's own objects are available; other ActiveX programs are not.")


BUILTIN[sym("VLAX-GET-OBJECT")] = BUILTIN[sym("VLAX-CREATE-OBJECT")]
BUILTIN[sym("VLAX-GET-OR-CREATE-OBJECT")] = BUILTIN[sym("VLAX-CREATE-OBJECT")]


def safearray(x) -> SafeArray:
    if type(x) is Variant and type(x.value) is SafeArray:
        return x.value
    if type(x) is not SafeArray:
        raise LispError("bad argument type: safearrayp %s" % prin1(x))
    return x


def empty_value(vt):
    if vt in (VT_R8, VT_R4):
        return 0.0
    if vt in (VT_I2, VT_I4):
        return 0
    if vt == VT_BSTR:
        return ""
    if vt == VT_VARIANT:
        return Variant(VT_EMPTY, None)
    return None


def coerce(vt, v):
    if vt in (VT_R8, VT_R4):
        return need_num(v)
    if vt in (VT_I2, VT_I4):
        return need_int(v)
    if vt == VT_BSTR:
        return need_str(v)
    if vt == VT_BOOL:
        return VTRUE if need_bool(v) else VFALSE
    if vt == VT_DISPATCH:
        return vobj(v) if v is not None else None
    return v


@fn("vlax-make-safearray", 2, None)
def f_make_safearray(L, vt, *dims):
    t = need_int(vt)
    if t not in (VT_I2, VT_I4, VT_R4, VT_R8, VT_BSTR, VT_DISPATCH, VT_BOOL, VT_VARIANT):
        raise LispError("bad argument value: %s" % prin1(vt))
    bounds = []
    size = 1
    for d in dims:
        if type(d) is not Cons or type(d.a) is not int or type(d.d) is not int or d.d < d.a - 1:
            raise LispError("bad argument type: bounds %s" % prin1(d))
        bounds.append((d.a, d.d))
        size *= d.d - d.a + 1
    if not bounds or len(bounds) > 2 or size > MAX_ARRAY:
        raise LispError("bad argument value: safearray dimensions")
    return SafeArray(t, bounds, [empty_value(t) for _ in range(size)])


@fn("vlax-safearray-fill", 2, 2)
def f_safearray_fill(L, sa, values):
    a = safearray(sa)
    vals = to_list(values)
    if len(a.bounds) == 2:
        vals = [x for row in vals for x in to_list(row)]
    if len(vals) > len(a.data):
        raise LispError("bad argument value: too many elements")
    for i, v in enumerate(vals):
        a.data[i] = coerce(a.vt, v)
    return sa


@fn("vlax-safearray->list", 1, 1)
def f_safearray_to_list(L, sa):
    a = safearray(sa)
    if not a.data:
        raise LispError("bad argument value: the array is empty")
    if len(a.bounds) == 2:
        w = a.bounds[1][1] - a.bounds[1][0] + 1
        return from_list([from_list(a.data[i : i + w]) for i in range(0, len(a.data), w)])
    return from_list(list(a.data))


def flat_index(a: SafeArray, idx) -> int:
    if len(idx) != len(a.bounds):
        raise LispError("bad argument value: wrong number of indexes")
    pos = 0
    for (lo, hi), i in zip(a.bounds, idx):
        i = need_int(i)
        if not lo <= i <= hi:
            raise LispError("bad argument value: index %d out of range" % i)
        pos = pos * (hi - lo + 1) + (i - lo)
    return pos


@fn("vlax-safearray-get-element", 2, 3)
def f_safearray_get(L, sa, *idx):
    a = safearray(sa)
    return a.data[flat_index(a, idx)]


@fn("vlax-safearray-put-element", 3, 4)
def f_safearray_put(L, sa, *rest):
    a = safearray(sa)
    v = rest[-1]
    a.data[flat_index(a, rest[:-1])] = coerce(a.vt, v)
    return v


@fn("vlax-safearray-get-dim", 1, 1)
def f_safearray_dim(L, sa):
    return len(safearray(sa).bounds)


def bound(sa, dim, which):
    a = safearray(sa)
    k = need_int(dim)
    if not 1 <= k <= len(a.bounds):
        raise LispError("bad argument value: dimension %d" % k)
    return a.bounds[k - 1][which]


@fn("vlax-safearray-get-l-bound", 2, 2)
def f_safearray_lbound(L, sa, dim):
    return bound(sa, dim, 0)


@fn("vlax-safearray-get-u-bound", 2, 2)
def f_safearray_ubound(L, sa, dim):
    return bound(sa, dim, 1)


@fn("vlax-safearray-type", 1, 1)
def f_safearray_type(L, sa):
    return safearray(sa).vt


def infer_vt(v) -> int:
    if v is None:
        return VT_EMPTY
    if type(v) is int:
        return VT_I4
    if type(v) is float:
        return VT_R8
    if type(v) is str:
        return VT_BSTR
    if type(v) is VlaObject:
        return VT_DISPATCH
    if v is VTRUE or v is VFALSE or v is T:
        return VT_BOOL
    if type(v) is SafeArray:
        return VT_ARRAY | v.vt
    if type(v) is Variant:
        return v.vt
    raise LispError("bad argument type: variant value %s" % prin1(v))


def convert(v, vt):
    base = vt & ~VT_ARRAY
    if vt & VT_ARRAY:
        a = safearray(v)
        return SafeArray(base, list(a.bounds), [coerce(base, x) for x in a.data])
    if vt == VT_EMPTY:
        return None
    if vt in (VT_R8, VT_R4):
        return need_num(v)
    if vt in (VT_I2, VT_I4):
        x = unwrap(v)
        if type(x) is str:
            try:
                x = float(x)
            except ValueError:
                raise LispError("bad argument value: %s" % prin1(v))
        if is_num(x) and not isinstance(x, bool):
            return int(round(x))
        raise LispError("bad argument value: %s" % prin1(v))
    if vt == VT_BSTR:
        x = unwrap(v)
        return x if type(x) is str else prin1(x)
    if vt == VT_BOOL:
        return VTRUE if need_bool(v) else VFALSE
    if vt == VT_DISPATCH:
        return vobj(v)
    return v


@fn("vlax-make-variant", 0, 2)
def f_make_variant(L, v=None, vt=None):
    if type(v) is Variant and vt is None:
        return Variant(v.vt, v.value)
    if v is T:
        v = VTRUE
    t = infer_vt(v) if vt is None else need_int(vt)
    return Variant(t, convert(v, t))


@fn("vlax-variant-value", 1, 1)
def f_variant_value(L, v):
    if type(v) is not Variant:
        raise LispError("bad argument type: variantp %s" % prin1(v))
    return v.value


@fn("vlax-variant-type", 1, 1)
def f_variant_type(L, v):
    if type(v) is not Variant:
        raise LispError("bad argument type: variantp %s" % prin1(v))
    return v.vt


@fn("vlax-variant-change-type", 2, 2)
def f_variant_change(L, v, vt):
    if type(v) is not Variant:
        raise LispError("bad argument type: variantp %s" % prin1(v))
    t = need_int(vt)
    try:
        return Variant(t, convert(v.value, t))
    except LispError:
        return None


@fn("vlax-3d-point", 1, 3)
def f_3d_point(L, x, y=None, z=None):
    p = need_pt(x) if y is None else [need_num(x), need_num(y), need_num(z) if z is not None else 0.0]
    return to_vla(Pt(p))


class Curve:
    def __init__(self, e):
        self.e = e
        k = e.kind
        self.path = curvepath.build(e) if k in curvepath.KINDS else None
        if self.path is None:
            raise LispError("bad argument type: curve %s" % OBJECT_NAMES.get(k, k))
        self.length = self.path.length
        self.lens = None
        if k == "line":
            self.p0, self.p1 = 0.0, self.length
        elif k == "arc":
            self.p0 = e.start_angle
            self.p1 = e.start_angle + geom.ccw_sweep(e.start_angle, e.end_angle)
        elif k == "circle":
            self.p0, self.p1 = 0.0, geom.TAU
        elif k in ("lwpolyline", "polyline3d"):
            if k == "lwpolyline":
                segs = curvepath.poly_segs(e.vertices, bool(e.closed))
            else:
                pts = e.points
                segs = [curvepath._line_seg(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts) if e.closed and len(pts) > 2 else len(pts) - 1)]
            self.lens = [s.length for s in segs]
            self.p0, self.p1 = 0.0, float(len(segs))
        elif k == "ellipse":
            self.p0 = e.start_param
            self.p1 = e.start_param + (geom.TAU if abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 else geom.ccw_sweep(e.start_param, e.end_param))
        elif k == "spline" and e.knots:
            self.p0, self.p1 = float(e.knots[0]), float(e.knots[-1])
        else:
            self.p0, self.p1 = 0.0, self.length

    def dist(self, p: float) -> float:
        if p < self.p0 - 1e-9 or p > self.p1 + 1e-9:
            return None
        p = min(max(p, self.p0), self.p1)
        if self.lens is not None:
            i = min(int(p), len(self.lens) - 1) if self.lens else 0
            return sum(self.lens[:i]) + (p - i) * (self.lens[i] if self.lens else 0.0)
        span = self.p1 - self.p0
        return 0.0 if span <= 0 else (p - self.p0) / span * self.length

    def param(self, s: float) -> float:
        if s < -1e-9 or s > self.length + 1e-9:
            return None
        s = min(max(s, 0.0), self.length)
        if self.lens is not None:
            acc = 0.0
            for i, n in enumerate(self.lens):
                if n > 0 and s <= acc + n + 1e-12:
                    return i + (s - acc) / n
                acc += n
            return self.p1
        return self.p0 + (s / self.length * (self.p1 - self.p0) if self.length > 0 else 0.0)

    def point(self, s: float) -> list:
        e = self.e
        if e.kind == "line":
            a, b = G3(e.start), G3(e.end)
            t = s / self.length if self.length else 0.0
            return [a[i] + (b[i] - a[i]) * t for i in range(3)]
        p = G3(self.path.at(s)[0])
        if e.kind == "lwpolyline":
            p[2] = float(e.elevation or 0.0)
        elif e.kind in ("arc", "circle", "ellipse"):
            p[2] = G3(e.center)[2]
        return p

    def deriv(self, s: float) -> list:
        ang = self.path.at(s)[1]
        if self.lens is not None:
            i = min(int(self.param(s)), len(self.lens) - 1)
            k = self.lens[i] if self.lens else 0.0
        else:
            span = self.p1 - self.p0
            k = self.length / span if span > 0 else 0.0
        return [math.cos(ang) * k, math.sin(ang) * k, 0.0]


def curve_of(L, x) -> Curve:
    if type(x) is EName:
        e = drawing(L).get(x.handle)
    elif type(x) is VlaObject and x.kind == "ent":
        e = drawing(L).get(x.key)
    else:
        raise LispError("bad argument type: curve %s" % prin1(x))
    if e is None:
        raise LispError("Automation Error. Object was erased")
    return Curve(e)


def curve_point(L, e, s):
    return Curve(e).point(s)


def lp(p):
    return from_list([float(v) for v in p])


def near(c: Curve, pt, extend=False):
    if c.e.kind == "line" and extend:
        a, b = G3(c.e.start), G3(c.e.end)
        d = [b[i] - a[i] for i in range(3)]
        n = sum(v * v for v in d)
        t = 0.0 if n == 0 else sum((pt[i] - a[i]) * d[i] for i in range(3)) / n
        return [a[i] + d[i] * t for i in range(3)], None
    s = c.path.locate(pt)
    return c.point(s), s


def on_curve(c: Curve, pt):
    q, s = near(c, pt)
    tol = 1e-6 * max(1.0, c.length)
    return s if math.hypot(q[0] - pt[0], q[1] - pt[1]) <= tol else None


@fn("vlax-curve-getStartParam", 1, 1)
def f_c_start_param(L, c):
    return float(curve_of(L, c).p0)


@fn("vlax-curve-getEndParam", 1, 1)
def f_c_end_param(L, c):
    return float(curve_of(L, c).p1)


@fn("vlax-curve-getStartPoint", 1, 1)
def f_c_start_point(L, c):
    return lp(curve_of(L, c).point(0.0))


@fn("vlax-curve-getEndPoint", 1, 1)
def f_c_end_point(L, c):
    cv = curve_of(L, c)
    return lp(cv.point(cv.length))


@fn("vlax-curve-getDistAtParam", 2, 2)
def f_c_dist_at_param(L, c, p):
    return curve_of(L, c).dist(need_num(p))


@fn("vlax-curve-getParamAtDist", 2, 2)
def f_c_param_at_dist(L, c, s):
    return curve_of(L, c).param(need_num(s))


@fn("vlax-curve-getPointAtParam", 2, 2)
def f_c_point_at_param(L, c, p):
    cv = curve_of(L, c)
    s = cv.dist(need_num(p))
    return lp(cv.point(s)) if s is not None else None


@fn("vlax-curve-getPointAtDist", 2, 2)
def f_c_point_at_dist(L, c, s):
    cv = curve_of(L, c)
    d = need_num(s)
    if d < -1e-9 or d > cv.length + 1e-9:
        return None
    return lp(cv.point(min(max(d, 0.0), cv.length)))


@fn("vlax-curve-getDistAtPoint", 2, 2)
def f_c_dist_at_point(L, c, p):
    cv = curve_of(L, c)
    return on_curve(cv, need_pt(p))


@fn("vlax-curve-getParamAtPoint", 2, 2)
def f_c_param_at_point(L, c, p):
    cv = curve_of(L, c)
    s = on_curve(cv, need_pt(p))
    return cv.param(s) if s is not None else None


@fn("vlax-curve-getClosestPointTo", 2, 3)
def f_c_closest(L, c, p, extend=None):
    return lp(near(curve_of(L, c), need_pt(p), extend is not None)[0])


@fn("vlax-curve-getFirstDeriv", 2, 2)
def f_c_first_deriv(L, c, p):
    cv = curve_of(L, c)
    s = cv.dist(need_num(p))
    if s is None:
        return None
    return lp(cv.deriv(s))


@fn("vlax-curve-getArea", 1, 1)
def f_c_area(L, c):
    return area_of(curve_of(L, c).e)


@fn("vlax-curve-isClosed", 1, 1)
def f_c_closed(L, c):
    cv = curve_of(L, c)
    return T if cv.path.closed or cv.e.kind == "circle" else None


@fn("vlax-curve-isPeriodic", 1, 1)
def f_c_periodic(L, c):
    cv = curve_of(L, c)
    return T if cv.e.kind in ("circle",) or (cv.e.kind == "ellipse" and cv.path.closed) else None


@fn("vlax-curve-isPlanar", 1, 1)
def f_c_planar(L, c):
    cv = curve_of(L, c)
    if cv.e.kind != "polyline3d":
        return T
    zs = {round(G3(p)[2], 9) for p in cv.e.points}
    return T if len(zs) <= 1 else None


NAMES.update({n.upper(): n for n in "Layers Linetypes TextStyles DimStyles Blocks Layouts ActiveLayer ActiveLinetype ActiveTextStyle ActiveDimStyle EntityName ArcLength EffectiveName XScaleFactor YScaleFactor ZScaleFactor LinetypeScale Visible Thickness Closed GetReal GetInteger GetKeyword AddLine AddCircle AddArc AddPoint AddText AddMText AddLightWeightPolyline AddPolyline Add3DPoly AddEllipse AddXline AddRay InsertBlock".split()})
CONSTANTS.update({VTRUE: VTRUE, VFALSE: VFALSE, sym("VLAX-VBEMPTY"): VT_EMPTY, sym("VLAX-VBNULL"): VT_NULL, sym("VLAX-VBINTEGER"): VT_I2, sym("VLAX-VBLONG"): VT_I4, sym("VLAX-VBSINGLE"): VT_R4, sym("VLAX-VBDOUBLE"): VT_R8, sym("VLAX-VBSTRING"): VT_BSTR, sym("VLAX-VBOBJECT"): VT_DISPATCH, sym("VLAX-VBBOOLEAN"): VT_BOOL, sym("VLAX-VBVARIANT"): VT_VARIANT, sym("VLAX-VBARRAY"): VT_ARRAY})
CONSTANTS.update({sym("ACMODELSPACE"): 1, sym("ACPAPERSPACE"): 0, sym("ACBYLAYER"): 256, sym("ACBYBLOCK"): 0, sym("ACRED"): 1, sym("ACYELLOW"): 2, sym("ACGREEN"): 3, sym("ACCYAN"): 4, sym("ACBLUE"): 5, sym("ACMAGENTA"): 6, sym("ACWHITE"): 7, sym("ACEXTENDNONE"): 0, sym("ACEXTENDTHISENTITY"): 1, sym("ACEXTENDOTHERENTITY"): 2, sym("ACEXTENDBOTH"): 3})
register()
