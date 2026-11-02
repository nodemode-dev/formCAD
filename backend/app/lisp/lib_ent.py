from contextlib import contextmanager

from app.cmd.context import Context
from app.doc import blockdefs, tables as T
from app.doc.document import CommandFailed
from app.doc.entities import entity_from_dict
from app.doc.model import layout_space
from app.lisp import groups as G
from app.lisp.registry import bad_type, fn
from app.lisp.types import EName, LispError, is_num

MAX_PENDING = 1_000_000


def doc_of(L):
    return L.ctx.runner.doc


@contextmanager
def edit(L):
    doc = doc_of(L)
    if doc.in_tx():
        yield
        return
    try:
        with doc.transaction("LISP"):
            yield
    except CommandFailed as err:
        raise LispError(str(err))


def ent_of(L, x, strict: bool = True):
    if type(x) is not EName:
        raise bad_type("enamep", x)
    return doc_of(L).drawing.get(x.handle)


def to_pt(v):
    if isinstance(v, list) and 2 <= len(v) <= 3 and all(is_num(c) for c in v):
        return G.p3(v)
    return None


def conv(kind, v):
    if kind == "pt":
        return to_pt(v)
    if kind == "f":
        return float(v) if is_num(v) else None
    if kind == "i":
        return int(v) if is_num(v) else None
    return v if isinstance(v, str) else None


def apply_common(L, e, pairs) -> bool:
    d = doc_of(L).drawing
    for code, val in pairs:
        if code == 8:
            if not isinstance(val, str) or not val:
                return False
            if not d.tables["layers"].has(val):
                d.table_set("layers", T.new_layer(val))
            e.layer = d.tables["layers"].get(val)["name"]
        elif code == 6 and isinstance(val, str):
            e.linetype = val
        elif code == 62 and type(val) is int:
            if 0 <= abs(val) <= 256:
                e.color = abs(val)
        elif code == 420 and type(val) is int:
            e.color = "#%06X" % (val & 0xFFFFFF)
        elif code == 48 and is_num(val):
            e.ltscale = float(val)
        elif code == 370 and type(val) is int:
            e.lineweight = val
        elif code == 39 and is_num(val):
            e.thickness = float(val)
        elif code == 60 and type(val) is int:
            e.visible = val == 0
    return True


def parse_vertices(pairs):
    verts = []
    for code, val in pairs:
        if code == 10:
            p = to_pt(val)
            if p is None:
                return None
            verts.append({"p": [p[0], p[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0})
        elif code in (40, 41, 42) and verts and is_num(val):
            verts[-1][{40: "sw", 41: "ew", 42: "bulge"}[code]] = float(val)
    return verts


def apply_kind(L, e, pairs, making: bool) -> bool:
    kind = e.kind
    spec = G.SIMPLE.get(kind, {})
    codes = {c for c, _ in pairs}
    if making:
        for need in G.REQUIRED.get(kind, ()):
            if need not in codes:
                return False
    if kind == "lwpolyline":
        if 10 in codes:
            verts = parse_vertices(pairs)
            if verts is None:
                return False
            e.vertices = verts
        for code, val in pairs:
            if code == 70 and type(val) is int:
                e.closed = bool(val & 1)
            elif code == 43 and is_num(val):
                e.const_width = float(val)
            elif code == 38 and is_num(val):
                e.elevation = float(val)
        return True
    if kind == "solid":
        corners = {}
        for code, val in pairs:
            if code in (10, 11, 12, 13):
                p = to_pt(val)
                if p is None:
                    return False
                corners[code - 10] = p
        if corners:
            cur = list(e.corners) if e.corners else []
            for i, p in corners.items():
                while len(cur) <= i:
                    cur.append(list(cur[-1]) if cur else [0.0, 0.0, 0.0])
                cur[i] = p
            if making and 3 not in corners and len(cur) == 4:
                cur = cur[:3]
            e.corners = cur
        return True
    for code, val in pairs:
        if kind == "insert" and code in (41, 42, 43):
            if not is_num(val):
                return False
            s = list(e.scale) if e.scale else [1.0, 1.0, 1.0]
            while len(s) < 3:
                s.append(1.0)
            s[code - 41] = float(val)
            e.scale = s
            continue
        if kind == "attdef" and code == 70 and type(val) is int:
            e.modes = {"invisible": bool(val & 1), "constant": bool(val & 2), "verify": bool(val & 4), "preset": bool(val & 8), "lock_position": e.modes.get("lock_position", False)}
            continue
        if code in spec:
            attr, k = spec[code]
            v = conv(k, val)
            if v is None:
                return False
            setattr(e, attr, v)
    return True


def target_space(L, pairs):
    doc = doc_of(L)
    for code, val in pairs:
        if code == 410 and isinstance(val, str):
            if val.lower() == "model":
                return "model"
            rec = doc.drawing.table_get("layouts", val)
            if rec is not None:
                return layout_space(rec["name"])
    return doc.current_space


def build_entity(L, kind: str, pairs):
    cls = G.CLASS_OF.get(kind)
    if cls is None:
        return None
    e = cls()
    runner = L.ctx.runner
    Context(runner, runner.doc).stamp(e)
    if not apply_common(L, e, pairs) or not apply_kind(L, e, pairs, True):
        return None
    return e


@fn("entget", 1, 2)
def f_entget(L, name, applist=None):
    e = ent_of(L, name)
    if e is None:
        return None
    return G.alist(e)


@fn("entmake", 1, 1)
def f_entmake(L, elist):
    pairs = G.lisp_pairs(elist)
    typ = ""
    for c, v in pairs:
        if c == 0 and isinstance(v, str):
            typ = v.upper()
            break
    d = doc_of(L).drawing
    if typ == "BLOCK":
        if L.blockdef is not None:
            return None
        name = next((v for c, v in pairs if c == 2 and isinstance(v, str)), "")
        flags = next((v for c, v in pairs if c == 70 and type(v) is int), 0)
        base = next((to_pt(v) for c, v in pairs if c == 10), None) or [0.0, 0.0, 0.0]
        if flags & (4 | 8 | 32 | 64) or (not name and not flags & 1):
            return None
        L.blockdef = {"name": name, "flags": flags, "base": base, "ents": []}
        return elist
    if typ == "ENDBLK":
        bd = L.blockdef
        if bd is None:
            return None
        L.blockdef = None
        try:
            with edit(L):
                if bd["flags"] & 1:
                    n = 1
                    while d.tables["blocks"].has("*U%d" % n):
                        n += 1
                    name = "*U%d" % n
                    if blockdefs.would_self_reference(d, name, bd["ents"]):
                        return None
                    d.define_block(name, bd["base"])
                    blockdefs._fill(d, name, bd["ents"])
                else:
                    blockdefs.define(d, bd["name"], bd["ents"], bd["base"])
        except blockdefs.BlockError:
            return None
        return elist
    kind = G.KIND_OF.get(typ)
    if kind is None:
        return None
    e = build_entity(L, kind, pairs)
    if e is None:
        return None
    if L.blockdef is not None:
        if len(L.blockdef["ents"]) >= MAX_PENDING:
            return None
        L.blockdef["ents"].append(e)
        return elist
    space = target_space(L, pairs)
    try:
        with edit(L):
            d.add_entity(e, space)
    except ValueError:
        return None
    return elist


@fn("entmod", 1, 1)
def f_entmod(L, elist):
    pairs = G.lisp_pairs(elist)
    handle = None
    x = elist
    while hasattr(x, "a"):
        it = x.a
        if hasattr(it, "a") and it.a == -1 and type(it.d) is EName:
            handle = it.d.handle
            break
        x = x.d
    if handle is None:
        return None
    d = doc_of(L).drawing
    e = d.get(handle)
    if e is None:
        return None
    snap = e.to_dict()
    body = [(c, v) for c, v in pairs if c not in (-1, 0, 5, 330, 100)]
    try:
        with edit(L):
            d.modify(handle)
            ok = apply_common(L, e, body) and apply_kind(L, e, body, False) and e.valid()
            if not ok:
                d.ents[handle] = entity_from_dict(snap)
                return None
    except ValueError:
        return None
    return elist


@fn("entdel", 1, 1)
def f_entdel(L, name):
    if type(name) is not EName:
        raise bad_type("enamep", name)
    d = doc_of(L).drawing
    if name.handle in L.deleted:
        e = L.deleted.pop(name.handle)
        with edit(L):
            d.restore_entity(e)
        return name
    if d.get(name.handle) is None:
        return None
    with edit(L):
        e = d.erase_entity(name.handle)
    L.deleted[name.handle] = e
    return name


def _top_level(L):
    d = doc_of(L).drawing
    return [e for e in d.ents.values() if e.owner == "model" or e.owner.startswith("layout:")]


@fn("entlast", 0, 0)
def f_entlast(L):
    best = None
    for e in _top_level(L):
        if best is None or e.handle > best:
            best = e.handle
    return EName(best) if best is not None else None


@fn("entnext", 0, 1)
def f_entnext(L, name=None):
    hs = sorted(e.handle for e in _top_level(L))
    if name is None:
        return EName(hs[0]) if hs else None
    if type(name) is not EName:
        raise bad_type("enamep", name)
    for h in hs:
        if h > name.handle:
            return EName(h)
    return None


@fn("entupd", 1, 1)
def f_entupd(L, name):
    if type(name) is not EName:
        raise bad_type("enamep", name)
    return name


@fn("handent", 1, 1)
def f_handent(L, h):
    if type(h) is not str:
        raise bad_type("stringp", h)
    try:
        v = int(h.strip(), 16)
    except ValueError:
        return None
    return EName(v) if doc_of(L).drawing.get(v) is not None else None
