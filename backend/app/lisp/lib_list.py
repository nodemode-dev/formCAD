from app.lisp.lib_num import _same_atom
from app.lisp.registry import bad_type, fn, integer, lst, string, truth
from app.lisp.types import AutoStub, Cons, EName, FileObj, PickSet, Subr, Sym, T, Usubr, from_list, is_num, sym, to_list

EQUAL_BUDGET = 1_000_000


@fn("atom", 1, 1)
def f_atom(L, a):
    return truth(type(a) is not Cons)


@fn("listp", 1, 1)
def f_listp(L, a):
    return truth(a is None or type(a) is Cons)


@fn("vl-consp", 1, 1)
def f_vl_consp(L, a):
    return truth(type(a) is Cons)


@fn("null", 1, 1)
def f_null(L, a):
    return truth(a is None)


@fn("not", 1, 1)
def f_not(L, a):
    return truth(a is None)


TYPES = {int: "INT", float: "REAL", str: "STR", Sym: "SYM", Cons: "LIST", EName: "ENAME", PickSet: "PICKSET", FileObj: "FILE", Subr: "SUBR", Usubr: "USUBR", AutoStub: "USUBR"}


@fn("type", 1, 1)
def f_type(L, a):
    if a is None:
        return None
    n = TYPES.get(type(a))
    return sym(n) if n else None


@fn("eq", 2, 2)
def f_eq(L, a, b):
    if a is b:
        return T
    if type(a) is int and type(b) is int:
        return truth(a == b)
    if type(a) is EName and type(b) is EName:
        return truth(a.handle == b.handle)
    return None


class _Budget:
    n = 0


def equal(a, b, fuzz=None) -> bool:
    work = [EQUAL_BUDGET]
    stack = [(a, b)]
    while stack:
        x, y = stack.pop()
        work[0] -= 1
        if work[0] < 0:
            return False
        if x is y:
            continue
        tx, ty = type(x), type(y)
        if tx is Cons:
            if ty is not Cons:
                return False
            stack.append((x.d, y.d))
            stack.append((x.a, y.a))
            continue
        if x is None or y is None:
            return False
        if is_num(x) and is_num(y):
            if fuzz is not None:
                if abs(x - y) > fuzz:
                    return False
            elif x != y:
                return False
            continue
        if not _same_atom(x, y):
            return False
    return True


@fn("equal", 2, 3)
def f_equal(L, a, b, fuzz=None):
    if fuzz is not None and not is_num(fuzz):
        raise bad_type("numberp", fuzz)
    return truth(equal(a, b, fuzz))


@fn("car", 1, 1)
def f_car(L, a):
    if a is None:
        return None
    if type(a) is not Cons:
        raise bad_type("listp", a)
    return a.a


@fn("cdr", 1, 1)
def f_cdr(L, a):
    if a is None:
        return None
    if type(a) is not Cons:
        raise bad_type("listp", a)
    return a.d


def _make_cxr(name: str):
    ops = name[1:-1]

    def f(L, a):
        x = a
        for op in reversed(ops):
            if x is None:
                return None
            if type(x) is not Cons:
                raise bad_type("listp", x)
            x = x.a if op == "a" else x.d
        return x

    return f


for _n in ("caar", "cadr", "cdar", "cddr", "caaar", "caadr", "cadar", "caddr", "cdaar", "cdadr", "cddar", "cdddr", "cadddr", "cddddr"):
    fn(_n, 1, 1)(_make_cxr(_n))


@fn("cons", 2, 2)
def f_cons(L, a, b):
    return Cons(a, b)


@fn("list", 0)
def f_list(L, *args):
    return from_list(args)


@fn("append", 0)
def f_append(L, *args):
    if not args:
        return None
    for a in args:
        lst(a)
    out = args[-1]
    for a in reversed(args[:-1]):
        out = from_list(to_list(a), out)
    return out


@fn("reverse", 1, 1)
def f_reverse(L, a):
    lst(a)
    out = None
    x = a
    while type(x) is Cons:
        out = Cons(x.a, out)
        x = x.d
    if x is not None:
        raise bad_type("listp", a)
    return out


@fn("length", 1, 1)
def f_length(L, a):
    lst(a)
    n = 0
    x = a
    while type(x) is Cons:
        n += 1
        x = x.d
    if x is not None:
        raise bad_type("listp", a)
    return n


@fn("nth", 2, 2)
def f_nth(L, n, a):
    integer(n)
    lst(a)
    if n < 0:
        return None
    x = a
    while n > 0 and type(x) is Cons:
        x = x.d
        n -= 1
    return x.a if type(x) is Cons else None


@fn("last", 1, 1)
def f_last(L, a):
    lst(a)
    if a is None:
        return None
    x = a
    while type(x.d) is Cons:
        x = x.d
    return x.a


@fn("member", 2, 2)
def f_member(L, item, a):
    lst(a)
    x = a
    while type(x) is Cons:
        if equal(item, x.a):
            return x
        x = x.d
    return None


@fn("assoc", 2, 2)
def f_assoc(L, key, a):
    lst(a)
    x = a
    while type(x) is Cons:
        e = x.a
        if type(e) is Cons and equal(key, e.a):
            return e
        x = x.d
    return None


@fn("subst", 3, 3)
def f_subst(L, new, old, a):
    lst(a)
    return from_list([new if equal(old, v) else v for v in to_list(a)])


@fn("vl-position", 2, 2)
def f_vl_position(L, item, a):
    lst(a)
    i = 0
    x = a
    while type(x) is Cons:
        if equal(item, x.a):
            return i
        i += 1
        x = x.d
    return None


@fn("vl-remove", 2, 2)
def f_vl_remove(L, item, a):
    lst(a)
    return from_list([v for v in to_list(a) if not equal(item, v)])


@fn("vl-list-length", 1, 1)
def f_vl_list_length(L, a):
    lst(a)
    n = 0
    x = a
    while type(x) is Cons:
        n += 1
        x = x.d
    return n if x is None else None


@fn("acad_strlsort", 1, 1)
def f_strlsort(L, a):
    lst(a)
    items = to_list(a)
    for s in items:
        string(s)
    return from_list(sorted(items, key=lambda s: s.lower()))


__all__ = ["equal"]
