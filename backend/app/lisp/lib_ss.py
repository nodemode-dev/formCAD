from app.cmd import snaps
from app.doc import curveops, geom
from app.lisp import groups as G
from app.lisp.lib_ent import doc_of
from app.lisp.lib_str import wc_match
from app.lisp.registry import bad_type, fn, integer
from app.lisp.types import Cons, EName, LispError, PickSet, from_list, is_num, point_of, to_list

MAX_FILTER_DEPTH = 32
OPS = ("=", "!=", "/=", "<>", "<", "<=", ">", ">=", "&", "&=", "*")
BAD = "bad ssget filter"


def parse_filter(x):
    items = []
    while type(x) is Cons:
        it = x.a
        if type(it) is not Cons or type(it.a) is not int:
            raise LispError(BAD)
        items.append((it.a, G.py_value(it.d)))
        x = x.d
    node, i = _block(items, 0, None, 0)
    return ("and", node)


def _block(items, i, end, depth):
    if depth > MAX_FILTER_DEPTH:
        raise LispError(BAD + ": nested too deeply")
    out = []
    pending = None
    while i < len(items):
        code, val = items[i]
        i += 1
        if code == -4:
            s = str(val).upper()
            if s in ("<AND", "<OR", "<XOR", "<NOT"):
                child, i = _block(items, i, s[1:] + ">", depth + 1)
                out.append((s[1:].lower(), child))
                continue
            if s in ("AND>", "OR>", "XOR>", "NOT>"):
                if end != s:
                    raise LispError(BAD)
                return out, i
            if str(val).split(",")[0] in OPS or "," in str(val):
                pending = str(val)
                continue
            raise LispError(BAD)
        out.append(("test", code, pending or "=", val))
        pending = None
    if end is not None:
        raise LispError(BAD)
    return out, i


def _cmp(op, a, b):
    if op in ("=", "*"):
        return a == b
    if op in ("!=", "/=", "<>"):
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    return False


def _num_eq(a, b):
    return abs(a - b) <= 1e-9 * (1.0 + abs(b))


def _one(op, have, want):
    if isinstance(want, str):
        if not isinstance(have, str):
            return False
        if op in ("=",):
            return wc_match(have, want, True)
        if op in ("!=", "/=", "<>"):
            return not wc_match(have, want, True)
        return _cmp(op, have.lower(), want.lower())
    if isinstance(want, list) and want and all(is_num(v) for v in want):
        if not isinstance(have, list):
            return False
        ops = op.split(",")
        n = min(len(want), len(have))
        if len(ops) == 1:
            ops = ops * n
        res = []
        for i in range(n):
            o = ops[i] if i < len(ops) else "*"
            if o == "*":
                res.append(True)
            elif o in ("=",):
                res.append(_num_eq(have[i], want[i]))
            else:
                res.append(_cmp(o, have[i], want[i]))
        if op in ("!=", "/=", "<>"):
            return not all(_num_eq(have[i], want[i]) for i in range(n))
        return all(res)
    if is_num(want):
        if not is_num(have):
            return False
        if op == "&":
            return (int(have) & int(want)) != 0
        if op == "&=":
            return (int(have) & int(want)) == int(want)
        if op == "=":
            return _num_eq(have, want)
        if op in ("!=", "/=", "<>"):
            return not _num_eq(have, want)
        return _cmp(op, have, want)
    return False


def _eval(node, gm):
    kind = node[0]
    if kind == "test":
        _k, code, op, want = node
        vals = gm.get(code)
        if vals is None:
            if code == 8:
                vals = ["0"]
            elif code == 62:
                vals = [256]
            else:
                return op in ("!=", "/=", "<>")
        if op in ("!=", "/=", "<>"):
            return all(_one(op, v, want) for v in vals)
        return any(_one(op, v, want) for v in vals)
    kids = node[1]
    if kind == "and":
        return all(_eval(k, gm) for k in kids)
    if kind == "or":
        return any(_eval(k, gm) for k in kids)
    if kind == "xor":
        return sum(1 for k in kids if _eval(k, gm)) % 2 == 1
    return not all(_eval(k, gm) for k in kids)


def filter_handles(L, ents, flt) -> list:
    tree = parse_filter(flt)
    out = []
    for e in ents:
        L.tick()
        if _eval(tree, G.groups_map(e)):
            out.append(e.handle)
    return out


def cands(L):
    doc = doc_of(L)
    d = doc.drawing
    return [e for e in d.entities(doc.current_space) if d.visible(e)]


def _pts(x, need):
    p = point_of(x)
    if p is None:
        raise bad_type("2D/3D point", x)
    return p


def _poly(x):
    out = []
    for p in to_list(x):
        q = point_of(p)
        if q is None:
            raise bad_type("2D/3D point", p)
        out.append([q[0], q[1]])
    return out


def window(L, a, b, kind):
    box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    rect = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]
    out = []
    for e in cands(L):
        bb = e.bounds()
        if kind == "window":
            if bb is not None and geom.box_inside(bb, box):
                out.append(e)
        elif bb is None:
            if e.kind in ("xline", "ray") and curveops.hit_by_polygon(e, rect, "cross"):
                out.append(e)
        elif geom.boxes_overlap(bb, box):
            if geom.box_inside(bb, box) or curveops.hit_by_polygon(e, rect, "cross"):
                out.append(e)
    return out


def _filter_arg(x) -> bool:
    return type(x) is Cons and type(x.a) is Cons and type(x.a.a) is int


@fn("ssget", 0, 4)
def f_ssget(L, *args):
    doc = doc_of(L)
    d = doc.drawing
    args = list(args)
    flt = None
    mode = None
    if args and type(args[0]) is str:
        mode = args.pop(0)
    elif args and _filter_arg(args[0]):
        flt = args.pop(0)
        mode = ":S"
    elif args and point_of(args[0]) is not None:
        mode = "PT"
    if args and _filter_arg(args[-1]) and flt is None:
        flt = args.pop()
    m = (mode or ":S").strip().upper().lstrip("_")
    ents = None
    if m == "X":
        ents = list(d.ordered_entities())
        ents = [e for e in ents if e.owner == "model" or e.owner.startswith("layout:")]
    elif m == "L":
        c = cands(L)
        ents = [c[-1]] if c else []
    elif m == "P":
        ents = [d.get(h) for h in doc.prev_selection if d.get(h) is not None]
    elif m == "I":
        ents = [d.get(h) for h in doc.selection if d.get(h) is not None]
    elif m in ("W", "C"):
        if len(args) < 2:
            raise LispError("too few arguments")
        ents = window(L, _pts(args[0], 2), _pts(args[1], 2), "window" if m == "W" else "crossing")
    elif m == "F":
        poly = _poly(args[0]) if args else []
        ents = [e for e in cands(L) if curveops.hit_by_fence(e, poly)] if len(poly) >= 2 else []
    elif m in ("WP", "CP"):
        poly = _poly(args[0]) if args else []
        if len(poly) < 3:
            ents = []
        elif m == "WP":
            ents = [e for e in cands(L) if e.bounds() is not None and curveops.hit_by_polygon(e, poly, "window")]
        else:
            ents = [e for e in cands(L) if curveops.hit_by_polygon(e, poly, "cross")]
    elif m in (":S", "A", "S", "PT"):
        pt = point_of(args[0]) if args else None
        if pt is not None:
            ap = float(doc.view.get("height", 100.0)) * 0.02
            e = snaps.nearest_curve(cands(L), [pt[0], pt[1], 0.0], ap)
            ents = [e] if e is not None else []
        else:
            implied = [d.get(h) for h in doc.selection if d.get(h) is not None]
            if implied:
                ents = implied
            else:
                from app.cmd.prompts import Prompt

                inp = L.ctx.ask(Prompt("Select objects", ("select",), select=True, hint="raw"))
                if inp is None or inp.kind != "selection":
                    return None
                ents = [d.get(h) for h in inp.value if d.get(h) is not None]
    else:
        raise LispError("bad argument value: ssget mode %s" % (mode,))
    if flt is not None:
        hs = set(filter_handles(L, ents, flt))
        ents = [e for e in ents if e.handle in hs]
    if not ents:
        return None
    return PickSet([e.handle for e in ents])


def ss_arg(x):
    if type(x) is not PickSet:
        raise bad_type("pickp", x)
    return x


@fn("ssadd", 0, 2)
def f_ssadd(L, name=None, ss=None):
    if name is None and ss is None:
        return PickSet()
    if type(name) is not EName:
        raise bad_type("enamep", name)
    if ss is None:
        return PickSet([name.handle])
    ss_arg(ss)
    if name.handle not in ss.handles:
        ss.handles.append(name.handle)
    return ss


@fn("ssdel", 2, 2)
def f_ssdel(L, name, ss):
    if type(name) is not EName:
        raise bad_type("enamep", name)
    ss_arg(ss)
    if name.handle not in ss.handles:
        return None
    ss.handles.remove(name.handle)
    return ss


@fn("sslength", 1, 1)
def f_sslength(L, ss):
    return len(ss_arg(ss).handles)


@fn("ssname", 2, 2)
def f_ssname(L, ss, i):
    ss_arg(ss)
    integer(i)
    if 0 <= i < len(ss.handles):
        return EName(ss.handles[i])
    return None


@fn("ssmemb", 2, 2)
def f_ssmemb(L, name, ss):
    if type(name) is not EName:
        raise bad_type("enamep", name)
    return name if name.handle in ss_arg(ss).handles else None


@fn("sssetfirst", 1, 2)
def f_sssetfirst(L, grips, ss=None):
    doc = doc_of(L)
    target = ss if ss is not None else grips
    if target is None:
        doc.selection = []
    else:
        ss_arg(target)
        vis = {e.handle for e in cands(L)}
        doc.selection = [h for h in target.handles if h in vis]
    doc.announce("selection")
    return target


@fn("ssgetfirst", 0, 0)
def f_ssgetfirst(L):
    doc = doc_of(L)
    sel = [h for h in doc.selection if doc.drawing.get(h) is not None]
    return from_list([None, PickSet(sel) if sel else None])
