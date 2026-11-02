import math
import re

from app.calc import units

MAX_LENGTH = 4096
MAX_DEPTH = 64
OSNAP_FUNCS = {"end": "end", "mid": "mid", "cen": "cen", "int": "int", "ins": "ins", "nod": "nod", "qua": "qua", "nea": "nea", "per": "per", "tan": "tan", "app": "app", "cur": None}
UNIT_ARG_FUNCS = {"cvunit": (1, 2)}

TOKEN = re.compile(r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?P<id>[A-Za-z_][A-Za-z0-9_]*)|(?P<str>\"[^\"]*\"|'[^']*')|(?P<op>[-+*/^&()\[\],<]))")


class CalcError(Exception):
    pass


class NeedsPick(CalcError):
    def __init__(self, mode):
        super().__init__("a pick is needed for %s" % mode)
        self.mode = mode


class Vec(tuple):
    def __new__(cls, x, y):
        return super().__new__(cls, (float(x), float(y)))


def is_vec(v) -> bool:
    return isinstance(v, Vec)


def tokenize(text: str) -> list:
    if len(text) > MAX_LENGTH:
        raise CalcError("expression is too long")
    out = []
    pos = 0
    s = text
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = TOKEN.match(s, pos)
        if not m:
            bad = s[pos:].strip()[:1]
            raise CalcError("unexpected character %s" % bad)
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


def sig(v: float) -> float:
    return units.significant(v, 14)


def fmt_number(v: float) -> str:
    if not math.isfinite(v):
        raise CalcError("the result is not finite")
    s = ("%.10f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def format_value(v) -> str:
    if is_vec(v):
        return "%s,%s" % (fmt_number(v[0]), fmt_number(v[1]))
    return fmt_number(v)


def to_value(raw):
    if isinstance(raw, bool):
        raise CalcError("variables must be numbers or points")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip()
        try:
            return float(s)
        except ValueError:
            parts = [p for p in re.split(r"\s*,\s*", s) if p != ""]
            if len(parts) in (2, 3):
                try:
                    return Vec(float(parts[0]), float(parts[1]))
                except ValueError:
                    pass
        raise CalcError("bad variable value %s" % raw)
    if isinstance(raw, (list, tuple)) and len(raw) in (2, 3):
        return Vec(float(raw[0]), float(raw[1]))
    raise CalcError("variables must be numbers or points")


def num(v, what="value"):
    if is_vec(v):
        raise CalcError("%s must be a number, not a point" % what)
    return v


def vec(v, what="value"):
    if not is_vec(v):
        raise CalcError("%s must be a point or vector" % what)
    return v


def _angle360(dx, dy) -> float:
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _check(x):
    if not math.isfinite(x):
        raise CalcError("the result is not finite")
    return x


def f_sin(a):
    return math.sin(math.radians(num(a)))


def f_cos(a):
    return math.cos(math.radians(num(a)))


def f_tan(a):
    x = num(a) % 180.0
    if abs(x - 90.0) < 1e-12:
        raise CalcError("tangent is undefined")
    return math.tan(math.radians(num(a)))


def f_asin(a):
    x = num(a)
    if not -1.0 <= x <= 1.0:
        raise CalcError("asin needs a value from -1 to 1")
    return math.degrees(math.asin(x))


def f_acos(a):
    x = num(a)
    if not -1.0 <= x <= 1.0:
        raise CalcError("acos needs a value from -1 to 1")
    return math.degrees(math.acos(x))


def f_atan(a):
    return math.degrees(math.atan(num(a)))


def f_sqrt(a):
    x = num(a)
    if x < 0:
        raise CalcError("square root of a negative number")
    return math.sqrt(x)


def f_sqr(a):
    return _check(num(a) ** 2)


def f_ln(a):
    x = num(a)
    if x <= 0:
        raise CalcError("logarithm of a non-positive number")
    return math.log(x)


def f_log(a):
    x = num(a)
    if x <= 0:
        raise CalcError("logarithm of a non-positive number")
    return math.log10(x)


def f_exp(a):
    try:
        return math.exp(num(a))
    except OverflowError:
        raise CalcError("the result is too large")


def f_exp10(a):
    try:
        return 10.0 ** num(a)
    except OverflowError:
        raise CalcError("the result is too large")


def f_round(a):
    x = num(a)
    return float(math.floor(abs(x) + 0.5)) * (1.0 if x >= 0 else -1.0)


def f_trunc(a):
    return float(math.trunc(num(a)))


def f_r2d(a):
    return math.degrees(num(a))


def f_d2r(a):
    return math.radians(num(a))


def f_pow(a, b):
    return pow_op(num(a), num(b))


def f_min(*a):
    return min(num(x) for x in a)


def f_max(*a):
    return max(num(x) for x in a)


def f_abs(a):
    return math.hypot(a[0], a[1]) if is_vec(a) else abs(a)


def f_dist(a, b):
    p, q = vec(a, "first point"), vec(b, "second point")
    return math.hypot(q[0] - p[0], q[1] - p[1])


def f_ang(*a):
    if len(a) == 1:
        v = vec(a[0])
        return _angle360(v[0], v[1])
    if len(a) == 2:
        p, q = vec(a[0]), vec(a[1])
        return _angle360(q[0] - p[0], q[1] - p[1])
    if len(a) == 3:
        o, p, q = vec(a[0]), vec(a[1]), vec(a[2])
        v1 = (p[0] - o[0], p[1] - o[1])
        v2 = (q[0] - o[0], q[1] - o[1])
        n = math.hypot(*v1) * math.hypot(*v2)
        if n == 0:
            raise CalcError("angle between zero length vectors")
        c = (v1[0] * v2[0] + v1[1] * v2[1]) / n
        return math.degrees(math.acos(max(-1.0, min(1.0, c))))
    raise CalcError("ang takes one, two or three arguments")


def f_vec(a, b):
    p, q = vec(a), vec(b)
    return Vec(q[0] - p[0], q[1] - p[1])


def f_vec1(*a):
    if len(a) == 1:
        v = vec(a[0])
    elif len(a) == 2:
        v = f_vec(a[0], a[1])
    else:
        raise CalcError("vec1 takes one or two arguments")
    n = math.hypot(v[0], v[1])
    if n == 0:
        raise CalcError("zero length vector")
    return Vec(v[0] / n, v[1] / n)


def f_ill(a, b, c, d):
    p1, p2, p3, p4 = vec(a), vec(b), vec(c), vec(d)
    r = (p2[0] - p1[0], p2[1] - p1[1])
    s = (p4[0] - p3[0], p4[1] - p3[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-14 * max(1.0, math.hypot(*r) * math.hypot(*s)):
        raise CalcError("the lines are parallel")
    t = ((p3[0] - p1[0]) * s[1] - (p3[1] - p1[1]) * s[0]) / den
    return Vec(p1[0] + t * r[0], p1[1] + t * r[1])


def f_plt(a, b, t):
    p, q, k = vec(a), vec(b), num(t)
    return Vec(p[0] + k * (q[0] - p[0]), p[1] + k * (q[1] - p[1]))


def f_pld(a, b, d):
    p, q, k = vec(a), vec(b), num(d)
    n = math.hypot(q[0] - p[0], q[1] - p[1])
    if n == 0:
        raise CalcError("the two points coincide")
    return Vec(p[0] + k * (q[0] - p[0]) / n, p[1] + k * (q[1] - p[1]) / n)


def f_rot(p, o, a):
    pt, org, ang = vec(p), vec(o), math.radians(num(a))
    dx, dy = pt[0] - org[0], pt[1] - org[1]
    c, s = math.cos(ang), math.sin(ang)
    return Vec(org[0] + dx * c - dy * s, org[1] + dx * s + dy * c)


FUNCS = {
    "sin": (f_sin, 1, 1), "cos": (f_cos, 1, 1), "tan": (f_tan, 1, 1), "asin": (f_asin, 1, 1), "acos": (f_acos, 1, 1), "atan": (f_atan, 1, 1),
    "sqrt": (f_sqrt, 1, 1), "sqr": (f_sqr, 1, 1), "ln": (f_ln, 1, 1), "log": (f_log, 1, 1), "exp": (f_exp, 1, 1), "exp10": (f_exp10, 1, 1),
    "round": (f_round, 1, 1), "trunc": (f_trunc, 1, 1), "r2d": (f_r2d, 1, 1), "d2r": (f_d2r, 1, 1), "pow": (f_pow, 2, 2), "min": (f_min, 2, 64), "max": (f_max, 2, 64),
    "abs": (f_abs, 1, 1), "dist": (f_dist, 2, 2), "ang": (f_ang, 1, 3), "vec": (f_vec, 2, 2), "vec1": (f_vec1, 1, 2), "ill": (f_ill, 4, 4), "plt": (f_plt, 3, 3), "pld": (f_pld, 3, 3), "rot": (f_rot, 3, 3),
}


def pow_op(a, b):
    try:
        r = a**b
    except ZeroDivisionError:
        raise CalcError("division by zero")
    except OverflowError:
        raise CalcError("the result is too large")
    if isinstance(r, complex):
        raise CalcError("the result is not a real number")
    return _check(float(r))


def add(a, b, sign):
    if is_vec(a) and is_vec(b):
        return Vec(a[0] + sign * b[0], a[1] + sign * b[1])
    if not is_vec(a) and not is_vec(b):
        return _check(a + sign * b)
    raise CalcError("cannot add a number and a point")


def mul(a, b):
    if is_vec(a) and is_vec(b):
        return a[0] * b[0] + a[1] * b[1]
    if is_vec(a):
        return Vec(a[0] * b, a[1] * b)
    if is_vec(b):
        return Vec(a * b[0], a * b[1])
    return _check(a * b)


def div(a, b):
    if is_vec(b):
        raise CalcError("cannot divide by a point")
    if b == 0:
        raise CalcError("division by zero")
    if is_vec(a):
        return Vec(a[0] / b, a[1] / b)
    return _check(a / b)


def cross(a, b):
    p, q = vec(a), vec(b)
    return p[0] * q[1] - p[1] * q[0]


class Parser:
    def __init__(self, tokens, variables, picker):
        self.t = tokens
        self.i = 0
        self.vars = variables
        self.picker = picker
        self.depth = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, op):
        k, v = self.take()
        if k != "op" or v != op:
            raise CalcError("expected %s" % op)

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalcError("expression is nested too deeply")

    def leave(self):
        self.depth -= 1

    def parse(self):
        if not self.t:
            raise CalcError("empty expression")
        v = self.expr()
        if self.i < len(self.t):
            raise CalcError("unexpected %s" % self.t[self.i][1])
        return v

    def expr(self):
        v = self.term()
        while True:
            k, op = self.peek()
            if k == "op" and op in "+-":
                self.take()
                v = add(v, self.term(), 1 if op == "+" else -1)
            else:
                return v

    def term(self):
        v = self.unary()
        while True:
            k, op = self.peek()
            if k == "op" and op in "*/&":
                self.take()
                r = self.unary()
                v = mul(v, r) if op == "*" else div(v, r) if op == "/" else cross(v, r)
            else:
                return v

    def raised(self):
        v = self.primary()
        k, op = self.peek()
        if k == "op" and op == "^":
            self.take()
            self.enter()
            r = self.unary()
            self.leave()
            return pow_op(num(v, "base"), num(r, "exponent"))
        return v

    def unary(self):
        k, op = self.peek()
        if k == "op" and op in "+-":
            self.take()
            self.enter()
            v = self.unary()
            self.leave()
            if op == "-":
                return Vec(-v[0], -v[1]) if is_vec(v) else -v
            return v
        return self.raised()

    def primary(self):
        k, v = self.take()
        if k == "num":
            return float(v)
        if k == "op" and v == "(":
            self.enter()
            r = self.expr()
            self.expect(")")
            self.leave()
            return r
        if k == "op" and v == "[":
            self.enter()
            r = self.point()
            self.leave()
            return r
        if k == "id":
            return self.name(v)
        if k is None:
            raise CalcError("the expression ended too soon")
        raise CalcError("unexpected %s" % v)

    def point(self):
        first = self.expr()
        k, op = self.peek()
        if k == "op" and op == "<":
            self.take()
            ang = self.expr()
            self.expect("]")
            d, a = num(first, "distance"), math.radians(num(ang, "angle"))
            return Vec(d * math.cos(a), d * math.sin(a))
        self.expect(",")
        second = self.expr()
        k, op = self.peek()
        if k == "op" and op == ",":
            self.take()
            num(self.expr(), "z")
        self.expect("]")
        return Vec(num(first, "x"), num(second, "y"))

    def name(self, ident):
        low = ident.lower()
        k, op = self.peek()
        if k == "op" and op == "(":
            if low in UNIT_ARG_FUNCS:
                return self.unit_call()
            empty = self.i + 1 < len(self.t) and self.t[self.i + 1] == ("op", ")")
            if low in OSNAP_FUNCS and (empty or low not in FUNCS):
                self.take()
                self.expect(")")
                return self.pick(low)
            if low not in FUNCS:
                raise CalcError("unknown function %s" % ident)
            fn, lo, hi = FUNCS[low]
            self.take()
            self.enter()
            args = []
            k2, v2 = self.peek()
            if not (k2 == "op" and v2 == ")"):
                args.append(self.expr())
                while True:
                    k2, v2 = self.peek()
                    if k2 == "op" and v2 == ",":
                        self.take()
                        args.append(self.expr())
                    else:
                        break
            self.expect(")")
            self.leave()
            if not lo <= len(args) <= hi:
                raise CalcError("%s takes %s argument%s" % (low, lo if lo == hi else "%d to %d" % (lo, hi), "" if lo == 1 and hi == 1 else "s"))
            return fn(*args)
        if low in OSNAP_FUNCS:
            return self.pick(low)
        if low in self.vars:
            return self.vars[low]
        if low == "pi":
            return math.pi
        if low == "e":
            return math.e
        raise CalcError("unknown name %s" % ident)

    def pick(self, mode):
        if self.picker is None:
            raise NeedsPick(mode)
        p = self.picker(OSNAP_FUNCS[mode])
        if p is None:
            raise NeedsPick(mode)
        return Vec(p[0], p[1])

    def unit_call(self):
        self.take()
        self.enter()
        value = self.expr()
        names = []
        while True:
            k, v = self.peek()
            if k == "op" and v == ",":
                self.take()
                k, v = self.take()
                if k == "str":
                    names.append(v[1:-1])
                elif k == "id":
                    names.append(v)
                elif k == "num":
                    j, w = self.peek()
                    if j == "id":
                        self.take()
                        names.append(v + w)
                    else:
                        names.append(v)
                else:
                    raise CalcError("a unit name is expected")
            else:
                break
        self.expect(")")
        self.leave()
        if len(names) != 2:
            raise CalcError("cvunit takes a value, a unit to convert from and a unit to convert to")
        try:
            return units.convert(num(value), names[0], names[1])
        except units.UnitError as err:
            raise CalcError(str(err))


def prepare_vars(variables) -> dict:
    out = {}
    for k, v in (variables or {}).items():
        out[str(k).lower()] = to_value(v)
    return out


def evaluate(expression: str, variables=None, picker=None):
    p = Parser(tokenize(str(expression)), prepare_vars(variables), picker)
    v = p.parse()
    if is_vec(v):
        return Vec(sig(v[0]), sig(v[1]))
    return sig(_check(v))


def run(expression: str, variables=None, picker=None) -> dict:
    v = evaluate(expression, variables, picker)
    if is_vec(v):
        return {"kind": "point", "value": [v[0], v[1]], "text": format_value(v)}
    return {"kind": "number", "value": v, "text": format_value(v)}


def pick_helper(mode: str, points) -> dict:
    mode = str(mode).lower()
    pts = [to_value(p) for p in points]
    need = {"point": 1, "distance": 2, "angle": 2, "intersection": 4}
    if mode not in need:
        raise CalcError("pick mode must be point, distance, angle or intersection")
    if len(pts) < need[mode]:
        raise CalcError("%s needs %d points" % (mode, need[mode]))
    if any(not is_vec(p) for p in pts):
        raise CalcError("picks must be points")
    if mode == "point":
        v = pts[0]
    elif mode == "distance":
        v = f_dist(pts[0], pts[1])
    elif mode == "angle":
        v = f_ang(pts[0], pts[1])
    else:
        v = f_ill(*pts[:4])
    if is_vec(v):
        v = Vec(sig(v[0]), sig(v[1]))
        return {"kind": "point", "value": [v[0], v[1]], "text": format_value(v)}
    v = sig(v)
    return {"kind": "number", "value": v, "text": format_value(v)}
