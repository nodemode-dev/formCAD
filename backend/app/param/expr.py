import math
import re

from app.param import units as U

MAX_LEN = 1024
MAX_DEPTH = 64
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
FUNCTIONS = {
    "sqrt": (1, math.sqrt), "abs": (1, abs), "floor": (1, math.floor), "ceil": (1, math.ceil), "round": (1, lambda v: float(round(v))),
    "sin": (1, lambda v: math.sin(math.radians(v))), "cos": (1, lambda v: math.cos(math.radians(v))), "tan": (1, lambda v: math.tan(math.radians(v))),
    "asin": (1, lambda v: math.degrees(math.asin(v))), "acos": (1, lambda v: math.degrees(math.acos(v))), "atan": (1, lambda v: math.degrees(math.atan(v))),
    "atan2": (2, lambda a, b: math.degrees(math.atan2(a, b))), "min": (2, min), "max": (2, max), "pow": (2, math.pow), "hypot": (2, math.hypot),
    "ln": (1, math.log), "log": (1, math.log10), "exp": (1, math.exp), "sign": (1, lambda v: (v > 0) - (v < 0)),
}
RESERVED = set(CONSTANTS) | set(FUNCTIONS) | U.unit_names()
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOKEN_RE = re.compile(r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|'(?P<quoted>[^']+)'|(?P<op>[-+*/^(),@]))")


class ExprError(ValueError):
    pass


def valid_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        return "A name starts with a letter or underscore and then holds letters, digits or underscores."
    if name.lower() in RESERVED:
        return "'%s' is reserved." % name
    if len(name) > 64:
        return "A name holds at most 64 characters."
    return ""


def tokenize(src: str) -> list:
    if len(src) > MAX_LEN:
        raise ExprError("An expression holds at most %d characters." % MAX_LEN)
    out = []
    pos = 0
    n = len(src)
    while pos < n:
        if src[pos:].strip() == "":
            break
        m = TOKEN_RE.match(src, pos)
        if m is None:
            raise ExprError("Unexpected character '%s'." % src[pos:].lstrip()[:1])
        kind = m.lastgroup
        out.append((kind, m.group(kind), m.start(kind) if kind != "quoted" else m.start(kind) - 1, m.end(kind) if kind != "quoted" else m.end(kind) + 1))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def op(self, text):
        tok = self.peek()
        return tok is not None and tok[0] == "op" and tok[1] == text

    def parse(self):
        if not self.t:
            raise ExprError("The expression is empty.")
        node = self.sum()
        if self.peek() is not None:
            raise ExprError("Unexpected '%s'." % self.peek()[1])
        return node

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError("The expression is nested too deeply.")

    def sum(self):
        node = self.prod()
        while self.op("+") or self.op("-"):
            o = self.take()[1]
            node = ("bin", o, node, self.prod())
        return node

    def prod(self):
        node = self.unary()
        while self.op("*") or self.op("/"):
            o = self.take()[1]
            node = ("bin", o, node, self.unary())
        return node

    def unary(self):
        self.enter()
        try:
            if self.op("-"):
                self.take()
                return ("neg", self.unary())
            if self.op("+"):
                self.take()
                return self.unary()
            base = self.atom()
            if self.op("^"):
                self.take()
                return ("bin", "^", base, self.unary())
            return base
        finally:
            self.depth -= 1

    def atom(self):
        tok = self.take()
        if tok is None:
            raise ExprError("The expression ends too early.")
        kind, text = tok[0], tok[1]
        if kind == "num":
            unit = None
            nxt = self.peek()
            if nxt is not None and nxt[0] == "name" and U.is_unit(nxt[1]):
                after = self.t[self.i + 1] if self.i + 1 < len(self.t) else None
                if not (after is not None and after[0] == "op" and after[1] == "("):
                    unit = nxt[1].lower()
                    self.take()
            return ("num", float(text), unit)
        if kind == "op" and text == "(":
            self.enter()
            node = self.sum()
            self.depth -= 1
            if not self.op(")"):
                raise ExprError("A closing parenthesis is missing.")
            self.take()
            return node
        if kind == "quoted":
            name, _, sk = text.partition("@")
            return ("name", name.strip(), sk.strip() or None)
        if kind == "name":
            if self.op("("):
                if text.lower() not in FUNCTIONS:
                    raise ExprError("Unknown function '%s'." % text)
                self.take()
                args = []
                if not self.op(")"):
                    while True:
                        self.enter()
                        args.append(self.sum())
                        self.depth -= 1
                        if self.op(","):
                            self.take()
                            continue
                        break
                if not self.op(")"):
                    raise ExprError("A closing parenthesis is missing.")
                self.take()
                want = FUNCTIONS[text.lower()][0]
                if len(args) != want:
                    raise ExprError("%s takes %d argument%s." % (text, want, "" if want == 1 else "s"))
                return ("call", text.lower(), args)
            sk = None
            if self.op("@"):
                self.take()
                s = self.take()
                if s is None or s[0] != "name":
                    raise ExprError("A sketch name must follow '@'.")
                sk = s[1]
            if text.lower() in CONSTANTS and sk is None:
                return ("num", CONSTANTS[text.lower()], None)
            return ("name", text, sk)
        raise ExprError("Unexpected '%s'." % text)


_cache: dict = {}


def parse(src: str):
    node = _cache.get(src)
    if node is None:
        node = _Parser(tokenize(src)).parse()
        if len(_cache) > 4096:
            _cache.clear()
        _cache[src] = node
    return node


def check(src: str) -> str:
    try:
        parse(src)
    except ExprError as err:
        return str(err)
    return ""


def walk(node):
    yield node
    if node[0] == "neg":
        yield from walk(node[1])
    elif node[0] == "bin":
        yield from walk(node[2])
        yield from walk(node[3])
    elif node[0] == "call":
        for a in node[2]:
            yield from walk(a)


def references(src: str) -> list:
    out = []
    for n in walk(parse(src)):
        if n[0] == "name":
            key = (n[1].casefold(), n[2].casefold() if n[2] else None)
            if key not in out:
                out.append(key)
    return out


def has_units(src: str) -> bool:
    return any(n[0] == "num" and n[2] for n in walk(parse(src)))


def pure_number(src: str) -> bool:
    return not references(src) and not has_units(src)


def evaluate(src: str, d, lookup):
    def ev(n):
        k = n[0]
        if k == "num":
            return n[1] * U.factor(d, n[2]) if n[2] else n[1]
        if k == "name":
            return lookup(n[1], n[2])
        if k == "neg":
            return -ev(n[1])
        if k == "bin":
            a, b = ev(n[2]), ev(n[3])
            o = n[1]
            if o == "+":
                return a + b
            if o == "-":
                return a - b
            if o == "*":
                return a * b
            if o == "/":
                if b == 0:
                    raise ExprError("Division by zero.")
                return a / b
            try:
                r = math.pow(a, b)
            except (ValueError, OverflowError):
                raise ExprError("The power is not defined.")
            return r
        fn = FUNCTIONS[n[1]][1]
        try:
            return float(fn(*[ev(a) for a in n[2]]))
        except (ValueError, OverflowError, ZeroDivisionError):
            raise ExprError("%s is not defined for that value." % n[1])

    v = float(ev(parse(src)))
    if not math.isfinite(v):
        raise ExprError("The result is not a finite number.")
    return v


def rename(src: str, old: str, new: str) -> str:
    low = old.casefold()
    toks = tokenize(src)
    out = []
    last = 0
    for kind, text, a, b in toks:
        if kind == "name" and text.casefold() == low:
            out.append(src[last:a])
            out.append(new)
            last = b
        elif kind == "quoted":
            name, sep, sk = text.partition("@")
            if name.strip().casefold() == low:
                out.append(src[last:a])
                out.append("'" + new + sep + sk + "'")
                last = b
    out.append(src[last:])
    return "".join(out)
