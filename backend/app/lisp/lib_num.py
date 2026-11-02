import math

from app.lisp.registry import bad_type, bad_value, fn, integer, num, truth
from app.lisp.types import EName, INT_MAX, INT_MIN, LispError, T, is_num, wrap32

UNDEFINED = "function undefined for argument"


def _ints(args) -> bool:
    for a in args:
        if type(a) is not int:
            return False
    return True


def _tdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


@fn("+", 0)
def f_add(L, *args):
    for a in args:
        num(a)
    if _ints(args):
        r = 0
        for a in args:
            r = wrap32(r + a)
        return r
    return float(sum(args))


@fn("-", 0)
def f_sub(L, *args):
    if not args:
        return 0
    for a in args:
        num(a)
    if len(args) == 1:
        a = args[0]
        return wrap32(-a) if type(a) is int else -a
    if _ints(args):
        r = args[0]
        for a in args[1:]:
            r = wrap32(r - a)
        return r
    r = float(args[0])
    for a in args[1:]:
        r -= a
    return r


@fn("*", 0)
def f_mul(L, *args):
    for a in args:
        num(a)
    if _ints(args):
        r = 1
        for a in args:
            r = wrap32(r * a)
        return r
    r = 1.0
    for a in args:
        r *= a
    return r


@fn("/", 1)
def f_div(L, *args):
    for a in args:
        num(a)
    if len(args) == 1:
        return args[0]
    if _ints(args):
        r = args[0]
        for a in args[1:]:
            if a == 0:
                raise LispError("divide by zero")
            r = wrap32(_tdiv(r, a))
        return r
    r = float(args[0])
    for a in args[1:]:
        if a == 0:
            raise LispError("divide by zero")
        r /= a
    return r


@fn("rem", 1)
def f_rem(L, *args):
    for a in args:
        num(a)
    r = args[0]
    for b in args[1:]:
        if b == 0:
            raise LispError("divide by zero")
        if type(r) is int and type(b) is int:
            r = r - b * _tdiv(r, b)
        else:
            r = math.fmod(r, b)
    return r


@fn("1+", 1, 1)
def f_inc(L, a):
    num(a)
    return wrap32(a + 1) if type(a) is int else a + 1.0


@fn("1-", 1, 1)
def f_dec(L, a):
    num(a)
    return wrap32(a - 1) if type(a) is int else a - 1.0


@fn("abs", 1, 1)
def f_abs(L, a):
    num(a)
    return wrap32(abs(a)) if type(a) is int else abs(a)


def _extreme(args, pick):
    for a in args:
        num(a)
    r = args[0]
    for a in args[1:]:
        if pick(a, r):
            r = a
    if _ints(args):
        return r
    return float(r)


@fn("min", 1)
def f_min(L, *args):
    return _extreme(args, lambda a, b: a < b)


@fn("max", 1)
def f_max(L, *args):
    return _extreme(args, lambda a, b: a > b)


@fn("sqrt", 1, 1)
def f_sqrt(L, a):
    num(a)
    if a < 0:
        raise LispError(UNDEFINED)
    return math.sqrt(a)


@fn("exp", 1, 1)
def f_exp(L, a):
    num(a)
    try:
        return math.exp(a)
    except OverflowError:
        raise LispError(UNDEFINED)


@fn("log", 1, 1)
def f_log(L, a):
    num(a)
    if a <= 0:
        raise LispError(UNDEFINED)
    return math.log(a)


@fn("sin", 1, 1)
def f_sin(L, a):
    num(a)
    try:
        return math.sin(a)
    except ValueError:
        raise LispError(UNDEFINED)


@fn("cos", 1, 1)
def f_cos(L, a):
    num(a)
    try:
        return math.cos(a)
    except ValueError:
        raise LispError(UNDEFINED)


@fn("atan", 1, 2)
def f_atan(L, a, b=None):
    num(a)
    if b is None:
        return math.atan(a)
    num(b)
    if a == 0 and b == 0:
        return 0.0
    return math.atan2(a, b)


@fn("expt", 2, 2)
def f_expt(L, a, b):
    num(a)
    num(b)
    try:
        if type(a) is int and type(b) is int and b >= 0:
            if abs(a) > 1 and b > 64:
                return wrap32(pow(a, b, 1 << 32))
            return wrap32(a**b)
        r = float(a) ** float(b)
    except (OverflowError, ZeroDivisionError, ValueError):
        raise LispError(UNDEFINED)
    if type(r) is complex or not math.isfinite(r):
        raise LispError(UNDEFINED)
    return r


@fn("fix", 1, 1)
def f_fix(L, a):
    num(a)
    if type(a) is int:
        return a
    if not math.isfinite(a):
        raise LispError(UNDEFINED)
    t = math.trunc(a)
    if INT_MIN <= t <= INT_MAX:
        return t
    return float(t)


@fn("float", 1, 1)
def f_float(L, a):
    num(a)
    return float(a)


@fn("gcd", 2, 2)
def f_gcd(L, a, b):
    integer(a)
    integer(b)
    if a == 0 and b == 0:
        raise bad_value(0)
    return math.gcd(a, b)


@fn("logand", 0)
def f_logand(L, *args):
    r = -1
    for a in args:
        integer(a)
        r &= a
    return wrap32(r)


@fn("logior", 0)
def f_logior(L, *args):
    r = 0
    for a in args:
        integer(a)
        r |= a
    return wrap32(r)


@fn("lsh", 2, 2)
def f_lsh(L, a, n):
    integer(a)
    integer(n)
    if n >= 32 or n <= -32:
        return 0
    if n >= 0:
        return wrap32(a << n)
    return wrap32((a & 0xFFFFFFFF) >> (-n))


@fn("~", 1, 1)
def f_bnot(L, a):
    integer(a)
    return wrap32(~a)


def _same_atom(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if is_num(a) and is_num(b):
        return a == b
    ta, tb = type(a), type(b)
    if ta is not tb:
        return False
    if ta is str:
        return a == b
    if ta is EName:
        return a.handle == b.handle
    return a is b


def _cmp_ok(a):
    if not (is_num(a) or type(a) is str):
        raise bad_type("numberp", a)


def _chain(args, test):
    for a in args:
        _cmp_ok(a)
    for i in range(len(args) - 1):
        x, y = args[i], args[i + 1]
        if (type(x) is str) != (type(y) is str):
            raise bad_type("numberp", y if type(x) is str else x)
        if not test(x, y):
            return None
    return T


@fn("=", 1)
def f_eq_num(L, *args):
    for i in range(len(args) - 1):
        if not _same_atom(args[i], args[i + 1]):
            return None
    return T


@fn("/=", 1)
def f_ne(L, *args):
    for i in range(len(args) - 1):
        if _same_atom(args[i], args[i + 1]):
            return None
    return T


@fn("<", 1)
def f_lt(L, *args):
    return _chain(args, lambda x, y: x < y)


@fn(">", 1)
def f_gt(L, *args):
    return _chain(args, lambda x, y: x > y)


@fn("<=", 1)
def f_le(L, *args):
    return _chain(args, lambda x, y: x <= y)


@fn(">=", 1)
def f_ge(L, *args):
    return _chain(args, lambda x, y: x >= y)


@fn("zerop", 1, 1)
def f_zerop(L, a):
    num(a)
    return truth(a == 0)


@fn("minusp", 1, 1)
def f_minusp(L, a):
    num(a)
    return truth(a < 0)


@fn("numberp", 1, 1)
def f_numberp(L, a):
    return truth(is_num(a))
