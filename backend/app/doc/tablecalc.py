import math
import re

MAX_FORMULA = 1024
MAX_DEPTH = 32
MAX_RANGE = 100_000
MAX_FORMULAS = 20_000
MAX_ARGS = 256
MAX_VISITS = 4_000_000
FUNCTIONS = ("SUM", "AVERAGE", "COUNT", "MIN", "MAX", "ABS", "ROUND")
AGGREGATES = ("SUM", "AVERAGE", "COUNT", "MIN", "MAX")

_NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?([eE][+-]?\d+)?%?$")
_TOKEN = re.compile(r"\s*(?:(?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|(?P<ref>\$?[A-Za-z]{1,2}\$?\d+)|(?P<err>#REF)|(?P<name>[A-Za-z_][A-Za-z_0-9]*)|(?P<op>[-+*/^(),:]))")


class Err(str):
    pass


class CalcError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def col_name(c: int) -> str:
    c += 1
    out = ""
    while c > 0:
        c, rem = divmod(c - 1, 26)
        out = chr(65 + rem) + out
    return out


def col_index(letters: str) -> int:
    v = 0
    for ch in letters.upper():
        v = v * 26 + (ord(ch) - 64)
    return v - 1


def cell_name(r: int, c: int) -> str:
    return "%s%d" % (col_name(c), r + 1)


def parse_ref(text: str):
    m = re.fullmatch(r"\$?([A-Za-z]{1,2})\$?(\d+)", text)
    if not m:
        return None
    r = int(m.group(2)) - 1
    if r < 0:
        return None
    return r, col_index(m.group(1))


def parse_number(text):
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t or not _NUMBER.match(t) or not any(ch.isdigit() for ch in t):
        return None
    pct = t.endswith("%")
    t = t.rstrip("%").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return v / 100.0 if pct else v


def format_value(v, kind: str = "general", precision: int = 2) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    if kind == "decimal":
        s = "%.*f" % (max(0, min(8, int(precision))), v)
    elif kind == "percent":
        s = "%.*f%%" % (max(0, min(8, int(precision))), v * 100.0)
    else:
        s = "%.10g" % v
    if s in ("-0", "-0.0", "-0.00"):
        s = s[1:]
    return s


def tokenize(text: str):
    pos = 0
    out = []
    n = len(text)
    while pos < n:
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m:
            raise CalcError("#SYNTAX")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect_op(self, op):
        k, v = self.take()
        if k != "op" or v != op:
            raise CalcError("#SYNTAX")

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalcError("#LIMIT")

    def leave(self):
        self.depth -= 1

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise CalcError("#SYNTAX")
        return node

    def expr(self):
        self.enter()
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        self.leave()
        return node

    def term(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        k, v = self.peek()
        if k == "op" and v in "+-":
            self.take()
            self.enter()
            inner = self.unary()
            self.leave()
            return ("neg", inner) if v == "-" else ("pos", inner)
        return self.power()

    def power(self):
        base = self.primary()
        if self.peek() == ("op", "^"):
            self.take()
            self.enter()
            exp = self.unary()
            self.leave()
            return ("bin", "^", base, exp)
        return base

    def primary(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v))
        if k == "err":
            return ("err", "#REF")
        if k == "ref":
            a = parse_ref(v)
            if a is None:
                raise CalcError("#SYNTAX")
            if self.peek() == ("op", ":"):
                self.take()
                k2, v2 = self.take()
                b = parse_ref(v2) if k2 == "ref" else None
                if b is None:
                    raise CalcError("#SYNTAX")
                return ("range", min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            return ("ref", a[0], a[1])
        if k == "name":
            name = v.upper()
            if name not in FUNCTIONS or self.peek() != ("op", "("):
                raise CalcError("#SYNTAX")
            self.take()
            self.enter()
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    args.append(self.expr())
                    if len(args) > MAX_ARGS:
                        raise CalcError("#LIMIT")
                    if self.peek() == ("op", ","):
                        self.take()
                        continue
                    break
            self.expect_op(")")
            self.leave()
            return ("call", name, args)
        if k == "op" and v == "(":
            inner = self.expr()
            self.expect_op(")")
            return inner
        raise CalcError("#SYNTAX")


def parse_formula(text: str):
    body = text.strip()
    if body.startswith("="):
        body = body[1:]
    if len(text) > MAX_FORMULA:
        raise CalcError("#LIMIT")
    if not body.strip():
        raise CalcError("#SYNTAX")
    return Parser(tokenize(body)).parse()


def refs_of(node, out):
    k = node[0]
    if k in ("ref", "range"):
        out.append(node)
    elif k in ("neg", "pos"):
        refs_of(node[1], out)
    elif k == "bin":
        refs_of(node[2], out)
        refs_of(node[3], out)
    elif k == "call":
        for a in node[2]:
            refs_of(a, out)


class Sheet:
    def __init__(self, table, fmt_of):
        self.table = table
        self.rows = table.rows()
        self.cols = table.cols()
        self.fmt_of = fmt_of
        self.cover = table.cover()
        self.results = {}
        self.visits = 0

    def raw(self, r, c):
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            raise CalcError("#REF")
        if (r, c) in self.cover:
            return None
        cell = self.table.cells[r][c]
        if cell.get("formula"):
            res = self.results.get((r, c))
            return res
        text = cell.get("text", "")
        if text.strip() == "":
            return None
        n = parse_number(text)
        return n if n is not None else str(text)

    def num(self, v):
        if isinstance(v, Err):
            raise CalcError(str(v))
        if v is None:
            return 0.0
        if isinstance(v, str):
            raise CalcError("#VALUE")
        return float(v)

    def range_values(self, r0, c0, r1, c1):
        if r1 >= self.rows or c1 >= self.cols:
            raise CalcError("#REF")
        if (r1 - r0 + 1) * (c1 - c0 + 1) > MAX_RANGE:
            raise CalcError("#LIMIT")
        out = []
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                self.visits += 1
                v = self.raw(r, c)
                if isinstance(v, Err):
                    raise CalcError(str(v))
                out.append(v)
        if self.visits > MAX_VISITS:
            raise CalcError("#LIMIT")
        return out

    def scalar(self, node):
        if node[0] == "range":
            return sum(float(v) for v in self.range_values(*node[1:]) if isinstance(v, float))
        return self.eval(node)

    def collect(self, node):
        if node[0] == "range":
            return [v for v in self.range_values(*node[1:]) if isinstance(v, float)]
        if node[0] == "ref":
            v = self.raw(node[1], node[2])
            if isinstance(v, Err):
                raise CalcError(str(v))
            return [v] if isinstance(v, float) else []
        v = self.eval(node)
        return [v] if isinstance(v, float) else []

    def eval(self, node):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "err":
            raise CalcError(node[1])
        if k == "ref":
            v = self.raw(node[1], node[2])
            if isinstance(v, Err):
                raise CalcError(str(v))
            return v
        if k == "range":
            return self.scalar(node)
        if k == "neg":
            return -self.num(self.eval(node[1]))
        if k == "pos":
            return self.num(self.eval(node[1]))
        if k == "bin":
            a, b = self.num(self.eval(node[2])), self.num(self.eval(node[3]))
            op = node[1]
            try:
                if op == "+":
                    v = a + b
                elif op == "-":
                    v = a - b
                elif op == "*":
                    v = a * b
                elif op == "/":
                    if b == 0:
                        raise CalcError("#DIV/0")
                    v = a / b
                else:
                    if a == 0 and b < 0:
                        raise CalcError("#DIV/0")
                    v = a**b
                    if isinstance(v, complex):
                        raise CalcError("#VALUE")
            except OverflowError:
                raise CalcError("#LIMIT")
            if not math.isfinite(v):
                raise CalcError("#VALUE")
            return v
        name, args = node[1], node[2]
        if name in AGGREGATES:
            vals = []
            for a in args:
                vals.extend(self.collect(a))
            if name == "COUNT":
                return float(len(vals))
            if name == "SUM":
                return math.fsum(vals)
            if name == "AVERAGE":
                if not vals:
                    raise CalcError("#DIV/0")
                return math.fsum(vals) / len(vals)
            if not vals:
                return 0.0
            return min(vals) if name == "MIN" else max(vals)
        if name == "ABS":
            if len(args) != 1:
                raise CalcError("#SYNTAX")
            return abs(self.num(self.scalar(args[0])))
        if len(args) not in (1, 2):
            raise CalcError("#SYNTAX")
        x = self.num(self.scalar(args[0]))
        n = int(self.num(self.scalar(args[1]))) if len(args) == 2 else 0
        n = max(-15, min(15, n))
        f = 10.0**n
        return math.copysign(math.floor(abs(x) * f + 0.5) / f, x)


def recalc(table, fmt_of) -> dict:
    sheet = Sheet(table, fmt_of)
    formulas = {}
    for r, row in enumerate(table.cells):
        for c, cell in enumerate(row):
            if cell.get("formula"):
                formulas[(r, c)] = cell
    if len(formulas) > MAX_FORMULAS:
        for (r, c), cell in formulas.items():
            sheet.results[(r, c)] = Err("#LIMIT")
        return _write(table, sheet, formulas, fmt_of)
    asts = {}
    deps = {}
    for key, cell in formulas.items():
        try:
            ast = parse_formula(cell["formula"])
        except CalcError as err:
            sheet.results[key] = Err(err.code)
            continue
        asts[key] = ast
        refs = []
        refs_of(ast, refs)
        need = set()
        for ref in refs:
            if ref[0] == "ref":
                if (ref[1], ref[2]) in formulas:
                    need.add((ref[1], ref[2]))
                sheet.visits += 1
            else:
                _r0, _c0, _r1, _c1 = ref[1:]
                area = (_r1 - _r0 + 1) * (_c1 - _c0 + 1)
                sheet.visits += min(area, len(formulas))
                if area <= len(formulas):
                    for r in range(_r0, _r1 + 1):
                        for c in range(_c0, _c1 + 1):
                            if (r, c) in formulas:
                                need.add((r, c))
                else:
                    for fr, fc in formulas:
                        if _r0 <= fr <= _r1 and _c0 <= fc <= _c1:
                            need.add((fr, fc))
        deps[key] = need
    if sheet.visits > MAX_VISITS:
        for key in formulas:
            sheet.results[key] = Err("#LIMIT")
        return _write(table, sheet, formulas, fmt_of)
    order = []
    remaining = {k: {d for d in v if d in asts or d in sheet.results} for k, v in deps.items()}
    users = {}
    for k, v in remaining.items():
        for d in v:
            users.setdefault(d, set()).add(k)
    ready = [k for k, v in remaining.items() if not v]
    ready.extend(k for k in sheet.results if k not in remaining and k in users)
    seen = set(ready)
    while ready:
        k = ready.pop()
        order.append(k)
        for u in users.get(k, ()):
            remaining[u].discard(k)
            if not remaining[u] and u not in seen:
                seen.add(u)
                ready.append(u)
    for key in formulas:
        if key in sheet.results:
            continue
        if key not in seen:
            sheet.results[key] = Err("#CYCLE")
    for key in order:
        if key in sheet.results:
            continue
        try:
            v = sheet.eval(asts[key])
            if isinstance(v, float) and not math.isfinite(v):
                raise CalcError("#VALUE")
            sheet.results[key] = v
        except CalcError as err:
            sheet.results[key] = Err(err.code)
        except RecursionError:
            sheet.results[key] = Err("#LIMIT")
    return _write(table, sheet, formulas, fmt_of)


def _write(table, sheet, formulas, fmt_of) -> dict:
    errors = {}
    for key, cell in formulas.items():
        v = sheet.results.get(key, Err("#SYNTAX"))
        if isinstance(v, Err):
            cell["text"] = str(v)
            cell["value"] = None
            errors[cell_name(*key)] = str(v)
        elif v is None:
            cell["text"] = ""
            cell["value"] = None
        elif isinstance(v, str):
            cell["text"] = v
            cell["value"] = None
        else:
            kind, prec = fmt_of(*key)
            cell["text"] = format_value(v, kind, prec)
            cell["value"] = v
    return errors


def shift_formula(text: str, fn_cell, fn_range) -> str:
    try:
        toks = tokenize(text.lstrip()[1:] if text.lstrip().startswith("=") else text)
    except CalcError:
        return text
    out = []
    i = 0
    while i < len(toks):
        k, v = toks[i]
        if k == "ref" and i + 2 < len(toks) + 0 and toks[i + 1] == ("op", ":") and toks[i + 2][0] == "ref":
            a, b = parse_ref(v), parse_ref(toks[i + 2][1])
            mark_a = _marks(v)
            mark_b = _marks(toks[i + 2][1])
            if a is None or b is None:
                out.append(v)
                i += 1
                continue
            r0, c0, r1, c1 = min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
            res = fn_range(r0, c0, r1, c1)
            if res is None:
                out.append("#REF")
            else:
                out.append(_ref_text(res[0], res[1], mark_a) + ":" + _ref_text(res[2], res[3], mark_b))
            i += 3
            continue
        if k == "ref":
            a = parse_ref(v)
            res = fn_cell(*a) if a else None
            out.append("#REF" if res is None else _ref_text(res[0], res[1], _marks(v)))
            i += 1
            continue
        out.append(v)
        i += 1
    return "=" + "".join(out)


def _marks(token: str):
    m = re.fullmatch(r"(\$?)[A-Za-z]{1,2}(\$?)\d+", token)
    return (m.group(1), m.group(2))


def _ref_text(r: int, c: int, marks) -> str:
    return "%s%s%s%d" % (marks[0], col_name(c), marks[1], r + 1)
