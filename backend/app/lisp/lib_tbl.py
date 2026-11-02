from app.cmd import units
from app.lisp.lib_ent import doc_of
from app.lisp.printer import prin1
from app.lisp.registry import bad_type, bad_value, fn, integer, num, string
from app.lisp.types import Cons, LispError, from_list, is_num
from app.sysvars import registry as sv

TABLES = {"LAYER": "layers", "LTYPE": "linetypes", "STYLE": "textstyles", "BLOCK": "blocks", "DIMSTYLE": "dimstyles", "APPID": "appid", "VIEW": "views", "UCS": "ucs", "VPORT": "vports"}


def pair(code, val):
    return Cons(code, from_list([float(v) for v in val]) if isinstance(val, list) else val)


def record_groups(name: str, rec: dict) -> Cons:
    g = [(0, name), (2, rec["name"])]
    if name == "LAYER":
        flags = (1 if rec.get("frozen") else 0) | (2 if rec.get("new_vp_freeze") else 0) | (4 if rec.get("locked") else 0)
        col = rec.get("color", 7)
        col = int(col) if isinstance(col, int) else 7
        g += [(70, flags), (62, col if rec.get("on", True) else -abs(col) or -7), (6, rec.get("linetype", "Continuous")), (290, 1 if rec.get("plot", True) else 0)]
        lw = rec.get("lineweight", -3)
        if isinstance(lw, (int, float)):
            g.append((370, int(lw)))
    elif name == "LTYPE":
        els = rec.get("elements", [])
        g += [(70, 0), (3, rec.get("description", "")), (72, 65), (73, len(els)), (40, float(rec.get("pattern_length", 0.0)))]
        g += [(49, float(e.get("length", 0.0))) for e in els]
    elif name == "STYLE":
        flags = (2 if rec.get("backwards") else 0) | (4 if rec.get("upside_down") else 0)
        g += [(70, 1 if rec.get("vertical") else 0), (40, float(rec.get("height", 0.0))), (41, float(rec.get("width_factor", 1.0))), (50, float(rec.get("oblique", 0.0))), (71, flags), (42, float(rec.get("height", 0.0))), (3, rec.get("font", "")), (4, rec.get("big_font", ""))]
    elif name == "BLOCK":
        flags = (1 if rec.get("anonymous") else 0) | (4 if rec.get("xref") else 0)
        g += [(70, flags), (10, list(rec.get("base", [0.0, 0.0, 0.0])) + [0.0] * (3 - len(rec.get("base", [0, 0, 0]))))]
        g.append((4, rec.get("description", "")))
    elif name == "DIMSTYLE":
        v = rec.get("vars", {})
        g += [(70, 0), (3, v.get("DIMPOST", "")), (40, float(v.get("DIMSCALE", 1.0))), (41, float(v.get("DIMASZ", 0.18))), (42, float(v.get("DIMEXO", 0.0625))), (44, float(v.get("DIMEXE", 0.18))), (140, float(v.get("DIMTXT", 0.18)))]
    elif name == "APPID":
        g.append((70, 0))
    return from_list([pair(c, v) for c, v in g])


def table_records(L, key: str) -> list:
    d = doc_of(L).drawing
    if key == "appid":
        names = ["ACAD"]
        seen = {"ACAD"}
        for e in d.ents.values():
            for k in e.xdata or {}:
                if k not in seen:
                    seen.add(k)
                    names.append(k)
        return [{"name": n} for n in names]
    tbl = d.tables.get(key)
    if tbl is None:
        return []
    return [r for r in tbl.values() if not str(r.get("name", "")).startswith("*V:")]


def table_key(name):
    if type(name) is not str:
        raise bad_type("stringp", name)
    key = TABLES.get(name.upper())
    if key is None:
        raise bad_value(name)
    return name.upper(), key


@fn("tblsearch", 2, 3)
def f_tblsearch(L, table, name, setnext=None):
    tname, key = table_key(table)
    string(name)
    recs = table_records(L, key)
    low = name.lower()
    for i, r in enumerate(recs):
        if str(r["name"]).lower() == low:
            if setnext is not None:
                L.tbl_pos[key] = i + 1
            return record_groups(tname, r)
    return None


@fn("tblnext", 1, 2)
def f_tblnext(L, table, rewind=None):
    tname, key = table_key(table)
    if rewind is not None:
        L.tbl_pos[key] = 0
    pos = L.tbl_pos.get(key, 0)
    recs = table_records(L, key)
    if pos >= len(recs):
        return None
    L.tbl_pos[key] = pos + 1
    return record_groups(tname, recs[pos])


def header(L):
    return doc_of(L).drawing.header


def dimzin(L) -> int:
    try:
        return int(sv.get_var(doc_of(L), "DIMZIN"))
    except Exception:
        return 0


@fn("rtos", 1, 3)
def f_rtos(L, n, mode=None, prec=None):
    num(n)
    h = header(L)
    m = int(h.get("LUNITS", 2)) if mode is None else integer(mode)
    p = int(h.get("LUPREC", 4)) if prec is None else integer(prec)
    if m < 1 or m > 5:
        raise LispError("bad argument value: rtos mode %d" % m)
    p = max(0, min(8, p))
    v = float(n)
    s = units.format_distance(v, m, p)
    if m == 2:
        z = dimzin(L)
        if z & 8 and "." in s:
            s = s.rstrip("0").rstrip(".")
        if z & 4:
            if s.startswith("0."):
                s = s[1:]
            elif s.startswith("-0."):
                s = "-" + s[2:]
        if s in ("-0", "-"):
            s = "0"
    return s


@fn("angtos", 1, 3)
def f_angtos(L, a, mode=None, prec=None):
    num(a)
    h = header(L)
    m = int(h.get("AUNITS", 0)) if mode is None else integer(mode)
    p = int(h.get("AUPREC", 0)) if prec is None else integer(prec)
    if m < 0 or m > 4:
        raise LispError("bad argument value: angtos mode %d" % m)
    shown = units.angle_for_display(float(a), float(h.get("ANGBASE", 0.0)), int(h.get("ANGDIR", 0)))
    return units.format_angle(shown, m, max(0, min(8, p)))


@fn("distof", 1, 2)
def f_distof(L, s, mode=None):
    string(s)
    if mode is not None:
        m = integer(mode)
        if m < 1 or m > 5:
            return None
    return units.parse_distance(s)


@fn("angtof", 1, 2)
def f_angtof(L, s, mode=None):
    string(s)
    h = header(L)
    au = int(h.get("AUNITS", 0))
    if mode is not None:
        au = integer(mode)
        if au < 0 or au > 4:
            return None
    try:
        a = units.parse_angle(s, au)
    except ValueError:
        return None
    if a is None:
        return None
    return units.direction_from_angle(a, float(h.get("ANGBASE", 0.0)), int(h.get("ANGDIR", 0)))


@fn("trans", 3, 4)
def f_trans(L, pt, frm, to, disp=None):
    return pt


def to_py(v):
    if isinstance(v, Cons):
        out = []
        while isinstance(v, Cons):
            out.append(to_py(v.a))
            v = v.d
        return out
    return v


def from_py(v):
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (list, tuple)):
        return from_list([from_py(x) for x in v])
    return v


@fn("getvar", 1, 1)
def f_getvar(L, name):
    string(name)
    try:
        v = sv.get_var(doc_of(L), name, radians=True)
    except sv.SysvarError:
        return None
    return from_py(v)


@fn("setvar", 2, 2)
def f_setvar(L, name, value):
    string(name)
    if value is not None and not (is_num(value) or type(value) is str or isinstance(value, Cons)):
        raise bad_type("numberp", value)
    py = to_py(value)
    try:
        out = sv.set_var(doc_of(L), name, py, radians=True, create=False)
    except sv.SysvarError:
        raise LispError("variable setting rejected: %s %s" % (name.upper(), prin1(value)))
    return from_py(out)
