import math

from app.lisp.types import AutoStub, Cons, EName, FileObj, NULL, PickSet, QUOTE, Subr, Sym, Usubr

MAX_ELEMENTS = 1_000_000
MAX_OUTPUT = 64 * 1024 * 1024


def fmt_real(x: float) -> str:
    if x != x:
        return "-1.#IND"
    if x == math.inf:
        return "1.#INF"
    if x == -math.inf:
        return "-1.#INF"
    if x == 0.0:
        return "0.0"
    m, _, e = ("%.5e" % x).partition("e")
    exp10 = int(e)
    if -5 <= exp10 < 6:
        s = "%.*f" % (max(5 - exp10, 0), x)
        if "." in s:
            s = s.rstrip("0")
            if s.endswith("."):
                s += "0"
        else:
            s += ".0"
        return s
    m = m.rstrip("0")
    if m.endswith("."):
        m += "0"
    return "%se%s%03d" % (m, "-" if exp10 < 0 else "+", abs(exp10))


ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\x1b": "\\e"}


def quote_string(s: str) -> str:
    out = ['"']
    for ch in s:
        r = ESCAPES.get(ch)
        if r is not None:
            out.append(r)
        elif ord(ch) < 32:
            out.append("\\%03o" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def atom_text(x, quote: bool) -> str:
    t = type(x)
    if x is None:
        return "nil"
    if t is str:
        return quote_string(x) if quote else x
    if t is int:
        return str(x)
    if t is float:
        return fmt_real(x)
    if t is Sym:
        return x.name
    if t is EName:
        return "<Entity name: %x>" % x.handle
    if t is PickSet:
        return "<Selection set: %x>" % x.ident
    if t is FileObj:
        return "#<FILE %d>" % x.num
    if t is Subr:
        return "#<SUBR @0 %s>" % x.name
    if t is Usubr or t is AutoStub:
        return "#<USUBR %s>" % (x.name or "-lambda-")
    return str(x)


def render(x, quote: bool) -> str:
    if type(x) is not Cons:
        return atom_text(x, quote)
    out: list = []
    size = 0
    count = 0
    stack: list = [("v", x)]
    while stack:
        kind, item = stack.pop()
        if kind == "s":
            out.append(item)
            size += len(item)
            continue
        if type(item) is not Cons:
            s = atom_text(item, quote)
            out.append(s)
            size += len(s)
            continue
        if item.a is QUOTE and type(item.d) is Cons and item.d.d is None:
            out.append("'")
            stack.append(("v", item.d.a))
            continue
        out.append("(")
        parts: list = []
        cur = item
        first = True
        while type(cur) is Cons:
            count += 1
            if count > MAX_ELEMENTS:
                parts.append(("s", "..."))
                cur = None
                break
            if not first:
                parts.append(("s", " "))
            parts.append(("v", cur.a))
            first = False
            cur = cur.d
        if cur is not None:
            parts.append(("s", " . "))
            parts.append(("v", cur))
        parts.append(("s", ")"))
        stack.extend(reversed(parts))
        if size > MAX_OUTPUT:
            out.append("...")
            break
    return "".join(out)


def prin1(x) -> str:
    return render(x, True)


def princ(x) -> str:
    return render(x, False)


def is_null_sym(x) -> bool:
    return x is NULL
