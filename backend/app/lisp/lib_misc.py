import math
import os

from app.lisp import reader, support
from app.lisp.printer import prin1, princ
from app.lisp.registry import bad_type, bad_value, fn, lst, num, string, symbol, truth
from app.lisp.types import AutoStub, Cons, ERR_MARK, FileObj, LispAbort, LispError, MISSING, NULL, T, from_list, point_of, sym, to_list

TOL = 1e-9


def pt_arg(x, allow3=True):
    p = point_of(x)
    if p is None:
        raise bad_type("2D/3D point", x)
    return p


@fn("polar", 3, 3)
def f_polar(L, p, a, d):
    pt = pt_arg(p)
    num(a)
    num(d)
    out = [pt[0] + d * math.cos(a), pt[1] + d * math.sin(a)]
    if len(pt) > 2:
        out.append(pt[2])
    return from_list(out)


@fn("distance", 2, 2)
def f_distance(L, p, q):
    a = pt_arg(p)
    b = pt_arg(q)
    d2 = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
    if len(a) > 2 and len(b) > 2:
        d2 += (a[2] - b[2]) ** 2
    return math.sqrt(d2)


@fn("angle", 2, 2)
def f_angle(L, p, q):
    a = pt_arg(p)
    b = pt_arg(q)
    r = math.atan2(b[1] - a[1], b[0] - a[0]) % (2 * math.pi)
    return 0.0 if r >= 2 * math.pi else r


@fn("inters", 4, 5)
def f_inters(L, p1, p2, p3, p4, onseg=MISSING):
    a, b, c, d = pt_arg(p1), pt_arg(p2), pt_arg(p3), pt_arg(p4)
    restrict = onseg is MISSING or onseg is not None
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    scale = math.hypot(rx, ry) * math.hypot(sx, sy)
    if scale == 0 or abs(den) <= 1e-12 * scale:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    if restrict:
        eps = 1e-9
        if t < -eps or t > 1 + eps or u < -eps or u > 1 + eps:
            return None
    out = [a[0] + t * rx, a[1] + t * ry]
    if len(a) > 2 and len(b) > 2 and len(c) > 2 and len(d) > 2:
        out.append(a[2] + t * (b[2] - a[2]))
    return from_list(out)


def sink(L, f):
    if f is None:
        return None
    if type(f) is not FileObj or f.closed or f.mode == "r":
        raise bad_type("streamp", f)
    return f


def emit(L, text: str, f) -> None:
    if f is None:
        L.out.write(text)
        return
    f.size += len(text)
    if f.size > support.MAX_WRITE:
        raise LispAbort("out of memory: file output over the limit", "limit")
    f.out.append(text)


@fn("princ", 0, 2)
def f_princ(L, *args):
    if not args:
        return NULL
    emit(L, princ(args[0]), sink(L, args[1] if len(args) > 1 else None))
    return args[0]


@fn("prin1", 0, 2)
def f_prin1(L, *args):
    if not args:
        return NULL
    emit(L, prin1(args[0]), sink(L, args[1] if len(args) > 1 else None))
    return args[0]


@fn("print", 0, 2)
def f_print(L, *args):
    if not args:
        return NULL
    f = sink(L, args[1] if len(args) > 1 else None)
    emit(L, "\n" + prin1(args[0]) + " ", f)
    return args[0]


@fn("prompt", 1, 1)
def f_prompt(L, s):
    L.out.write(string(s))
    return None


@fn("terpri", 0, 0)
def f_terpri(L):
    L.out.write("\n")
    return None


@fn("alert", 1, 1)
def f_alert(L, s):
    L.out.write("\n" + princ(s) + "\n")
    return None


def file_arg(x, mode=None):
    if type(x) is not FileObj:
        raise bad_type("streamp", x)
    if x.closed:
        raise bad_type("streamp", x)
    return x


@fn("open", 2, 2)
def f_open(L, path, mode):
    string(path)
    string(mode)
    m = mode.lower()
    if m not in ("r", "w", "a"):
        raise bad_value(mode)
    if len(L.files) >= 128:
        raise LispError("too many open files")
    if m == "r":
        real = support.resolve_read(path)
        if real is None:
            if support.resolve_write(path) is None and os.path.isabs(path.replace("\\", "/")):
                L.out.write("\n; open: files outside the support folders are not available\n")
            return None
        text = support.read_text(real)
        if text is None:
            return None
        f = FileObj(L.file_seq + 1, real, "r")
        f.lines = text.splitlines()
    else:
        real = support.resolve_write(path)
        if real is None:
            L.out.write("\n; open: writing is limited to the support folders\n")
            return None
        f = FileObj(L.file_seq + 1, real, m)
    L.file_seq += 1
    L.files[f.num] = f
    return f


def flush_file(f: FileObj) -> None:
    if f.closed:
        return
    f.closed = True
    if f.mode in ("w", "a"):
        try:
            with open(f.path, "w" if f.mode == "w" else "a", encoding="utf-8", newline="") as fh:
                fh.write("".join(f.out))
        except OSError:
            pass
    f.out = []
    f.lines = []


@fn("close", 1, 1)
def f_close(L, f):
    if type(f) is not FileObj:
        raise bad_type("streamp", f)
    flush_file(f)
    L.files.pop(f.num, None)
    return None


@fn("read-line", 0, 1)
def f_read_line(L, f=None):
    if f is None:
        return None
    file_arg(f)
    if f.mode != "r":
        raise bad_type("streamp", f)
    if f.pos >= len(f.lines):
        return None
    s = f.lines[f.pos]
    f.pos += 1
    return s


@fn("write-line", 1, 2)
def f_write_line(L, s, f=None):
    string(s)
    emit(L, s + "\n", sink(L, f))
    return s


@fn("findfile", 1, 1)
def f_findfile(L, name):
    string(name)
    real = support.resolve_read(name)
    if real is None and L.session is not None:
        real = L.session.granted(name)
    return real.replace("\\", "/") if real else None


def load_depth_ok(L) -> bool:
    return getattr(L, "load_depth", 0) < 16


def do_load(L, name, onfail, strict):
    if type(name) is not str:
        raise bad_type("stringp", name)
    base = name if os.path.splitext(name.replace("\\", "/"))[1] else name + ".lsp"
    real = None
    if L.session is not None:
        real = L.session.granted(base)
    if real is None:
        real = support.resolve_read(base)
    text = support.read_text(real) if real else None
    if text is None:
        if onfail is not MISSING:
            return onfail
        raise LispError('LOAD failed: "%s"' % name)
    depth = getattr(L, "load_depth", 0)
    if depth >= 16:
        raise LispError("load nested too deeply")
    L.load_depth = depth + 1
    try:
        return run_text(L, text)
    finally:
        L.load_depth = depth


def run_text(L, text: str):
    pos = 0
    value = None
    while True:
        form, pos = reader.read_one(text, pos)
        if reader.is_eof(form):
            return value
        value = L.ev(form)


@fn("load", 1, 2)
def f_load(L, name, onfail=MISSING):
    return do_load(L, name, onfail, True)


@fn("autoload", 2, 2)
def f_autoload(L, file, cmds):
    string(file)
    for c in to_list(cmds):
        string(c)
        key = sym("C:" + c.upper())
        L.syms[key] = AutoStub("C:" + c.upper(), file, c)
    return None


@fn("ver", 0, 0)
def f_ver(L):
    return "FormCAD LISP 0.6 (en)"


@fn("vl-load-com", 0, 0)
def f_vl_load_com(L):
    return None


@fn("gc", 0, 0)
def f_gc(L):
    return None


@fn("redraw", 0, 4)
def f_redraw(L, *args):
    return None


@fn("exit", 0, 0)
def f_exit(L):
    raise LispAbort("quit / exit abort", "quit")


@fn("quit", 0, 0)
def f_quit(L):
    raise LispAbort("quit / exit abort", "quit")


@fn("apply", 2, 2)
def f_apply(L, f, args):
    lst(args)
    return L.call(f, to_list(args))


@fn("mapcar", 2)
def f_mapcar(L, f, *lists):
    cols = []
    for a in lists:
        if type(a) is not Cons:
            return None
        cols.append(to_list(a))
    func = L.function_of(f)
    n = min(len(c) for c in cols)
    out = []
    for i in range(n):
        out.append(L.apply(func, [c[i] for c in cols]))
    return from_list(out)


@fn("eval", 1, 1)
def f_eval(L, x):
    return L.ev(x)


@fn("set", 2, 2)
def f_set(L, s, v):
    symbol(s)
    if s is T or s is NULL:
        raise bad_type("symbolp", s)
    L.syms[s] = v
    return v


@fn("boundp", 1, 1)
def f_boundp(L, s):
    symbol(s)
    return truth(L.get(s) is not None)


@fn("vl-symbol-value", 1, 1)
def f_symbol_value(L, s):
    symbol(s)
    return L.get(s)


def _sorted(L, items: list, less) -> list:
    n = len(items)
    if n < 2:
        return list(items)
    src = list(items)
    width = 1
    while width < n:
        dst = []
        for lo in range(0, n, 2 * width):
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            i, j = lo, mid
            while i < mid and j < hi:
                if L.callback(less, [src[j], src[i]]) is not None:
                    dst.append(src[j])
                    j += 1
                else:
                    dst.append(src[i])
                    i += 1
            dst.extend(src[i:mid])
            dst.extend(src[j:hi])
        src = dst
        width *= 2
    return src


@fn("vl-sort", 2, 2)
def f_vl_sort(L, a, less):
    lst(a)
    return from_list(_sorted(L, to_list(a), less))


@fn("vl-remove-if", 2, 2)
def f_remove_if(L, pred, a):
    lst(a)
    return from_list([v for v in to_list(a) if L.callback(pred, [v]) is None])


@fn("vl-remove-if-not", 2, 2)
def f_remove_if_not(L, pred, a):
    lst(a)
    return from_list([v for v in to_list(a) if L.callback(pred, [v]) is not None])


@fn("vl-member-if", 2, 2)
def f_member_if(L, pred, a):
    lst(a)
    x = a
    while type(x) is Cons:
        if L.callback(pred, [x.a]) is not None:
            return x
        x = x.d
    return None


def _columns(lists):
    cols = []
    for a in lists:
        lst(a)
        cols.append(to_list(a))
    return cols


@fn("vl-every", 2)
def f_every(L, pred, *lists):
    cols = _columns(lists)
    n = min(len(c) for c in cols)
    for i in range(n):
        if L.callback(pred, [c[i] for c in cols]) is None:
            return None
    return T


@fn("vl-some", 2)
def f_some(L, pred, *lists):
    cols = _columns(lists)
    n = min(len(c) for c in cols)
    for i in range(n):
        r = L.callback(pred, [c[i] for c in cols])
        if r is not None:
            return r
    return None


@fn("vl-catch-all-apply", 2, 2)
def f_catch_all(L, f, args):
    lst(args)
    argv = to_list(args)
    depth, cb = L.depth, L.cb_depth
    try:
        return L.call(f, argv)
    except LispError as err:
        L.depth, L.cb_depth = depth, cb
        return Cons(ERR_MARK, err.msg)


@fn("vl-catch-all-error-p", 1, 1)
def f_catch_error_p(L, x):
    return truth(type(x) is Cons and x.a is ERR_MARK)


@fn("vl-catch-all-error-message", 1, 1)
def f_catch_error_message(L, x):
    if type(x) is Cons and x.a is ERR_MARK:
        return x.d
    return None
