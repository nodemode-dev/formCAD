import itertools
import math

INT_MIN = -2147483648
INT_MAX = 2147483647
MISSING = object()


class Sym:
    __slots__ = ("name",)
    table: dict = {}

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return "Sym(%s)" % self.name


def sym(name: str) -> Sym:
    key = name.upper()
    s = Sym.table.get(key)
    if s is None:
        s = Sym(key)
        Sym.table[key] = s
    return s


T = sym("T")
NULL = Sym("")
QUOTE = sym("QUOTE")
LAMBDA = sym("LAMBDA")
SLASH = sym("/")
ERROR_SYM = sym("*ERROR*")
ERR_MARK = sym("%CATCH-ALL-APPLY-ERROR%")


class Cons:
    __slots__ = ("a", "d")

    def __init__(self, a, d=None):
        self.a = a
        self.d = d


class EName:
    __slots__ = ("handle",)

    def __init__(self, handle: int):
        self.handle = handle

    def __eq__(self, other):
        return type(other) is EName and other.handle == self.handle

    def __hash__(self):
        return hash(("en", self.handle))


_ids = itertools.count(0x1000)


class PickSet:
    __slots__ = ("handles", "ident")

    def __init__(self, handles=None):
        self.handles = list(handles or [])
        self.ident = next(_ids)


class FileObj:
    __slots__ = ("num", "path", "mode", "lines", "pos", "out", "closed", "size")

    def __init__(self, num: int, path: str, mode: str):
        self.num = num
        self.path = path
        self.mode = mode
        self.lines: list = []
        self.pos = 0
        self.out: list = []
        self.closed = False
        self.size = 0


class Subr:
    __slots__ = ("name", "fn", "lo", "hi")

    def __init__(self, name: str, fn, lo: int, hi):
        self.name = name
        self.fn = fn
        self.lo = lo
        self.hi = hi


class Usubr:
    __slots__ = ("name", "params", "locals", "body")

    def __init__(self, name, params, locals_, body):
        self.name = name
        self.params = params
        self.locals = locals_
        self.body = body


class AutoStub(Usubr):
    __slots__ = ("file", "cmd")

    def __init__(self, name, file, cmd):
        Usubr.__init__(self, name, [], [], None)
        self.file = file
        self.cmd = cmd


class LispError(Exception):
    def __init__(self, msg: str):
        Exception.__init__(self, msg)
        self.msg = msg


class LispAbort(Exception):
    def __init__(self, msg: str, kind: str = "quit"):
        Exception.__init__(self, msg)
        self.msg = msg
        self.kind = kind


def wrap32(n: int) -> int:
    return ((n + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def is_int(x) -> bool:
    return type(x) is int


def is_num(x) -> bool:
    t = type(x)
    return t is int or t is float


def from_list(items, tail=None):
    out = tail
    for v in reversed(items):
        out = Cons(v, out)
    return out


def to_list(x, what: str = "listp") -> list:
    out = []
    while type(x) is Cons:
        out.append(x.a)
        x = x.d
    if x is not None:
        from app.lisp.printer import prin1

        raise LispError("bad argument type: %s: %s" % (what, prin1(x)))
    return out


def is_list(x) -> bool:
    return x is None or type(x) is Cons


def point_of(x):
    if type(x) is not Cons:
        return None
    vals = []
    n = 0
    while type(x) is Cons:
        if not is_num(x.a):
            return None
        vals.append(float(x.a))
        x = x.d
        n += 1
        if n > 3:
            return None
    if x is not None or n < 2:
        return None
    return vals


def mkpoint(p) -> Cons:
    return from_list([float(v) for v in p])


def finite(x: float) -> bool:
    return math.isfinite(x)
