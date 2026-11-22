from app.lisp.printer import prin1
from app.lisp.types import Cons, LispError, Subr, Sym, is_num, sym

BUILTIN: dict = {}
SPECIAL: dict = {}
CONSTANTS: dict = {}


def fn(name: str, lo: int = 0, hi=None):
    def wrap(f):
        BUILTIN[sym(name)] = Subr(name.upper(), f, lo, hi)
        return f

    return wrap


def special(name: str):
    def wrap(f):
        SPECIAL[sym(name)] = f
        return f

    return wrap


def bad_type(pred: str, val) -> LispError:
    return LispError("bad argument type: %s: %s" % (pred, prin1(val)))


def bad_value(val) -> LispError:
    return LispError("bad argument value: %s" % prin1(val))


def num(x, pred: str = "numberp"):
    if not is_num(x):
        raise bad_type(pred, x)
    return x


def integer(x, pred: str = "fixnump") -> int:
    if type(x) is not int:
        raise bad_type(pred, x)
    return x


def string(x) -> str:
    if type(x) is not str:
        raise bad_type("stringp", x)
    return x


def symbol(x) -> Sym:
    if type(x) is not Sym:
        raise bad_type("symbolp", x)
    return x


def lst(x):
    if x is not None and type(x) is not Cons:
        raise bad_type("listp", x)
    return x


def truth(b):
    from app.lisp.types import T

    return T if b else None
