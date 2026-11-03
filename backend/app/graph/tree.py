import json
import math
import re
from typing import Iterable, Optional

from app.graph import values as gv

TREE_FORMAT = "formcad.tree"
TREE_VERSION = 1
EMPTY_TEXT = "<empty>"
MAX_PATH_EXPR_DEPTH = 32


class TreeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Symbol(str):
    pass


class Path(tuple):
    def __new__(cls, parts=()):
        if isinstance(parts, int) and not isinstance(parts, bool):
            parts = (parts,)
        if isinstance(parts, str):
            return cls.parse(parts)
        vals = []
        for p in parts:
            if isinstance(p, bool) or not isinstance(p, int):
                if isinstance(p, float) and p.is_integer():
                    p = int(p)
                else:
                    raise TreeError("PATH_INVALID", "a path holds whole numbers, got %r" % (p,))
            if p < 0:
                raise TreeError("PATH_NEGATIVE", "a path cannot hold a negative number")
            vals.append(p)
        if not vals:
            raise TreeError("PATH_INVALID", "a path needs at least one number")
        return super().__new__(cls, vals)

    @classmethod
    def of(cls, *parts):
        return cls(parts)

    @classmethod
    def parse(cls, text: str):
        s = text.strip()
        if len(s) < 3 or s[0] != "{" or s[-1] != "}":
            raise TreeError("PATH_INVALID", "a path is written {0;1}, got %r" % text)
        parts = []
        for piece in s[1:-1].split(";"):
            piece = piece.strip()
            if not re.fullmatch(r"\d+", piece):
                raise TreeError("PATH_INVALID", "a path holds whole numbers, got %r" % text)
            parts.append(int(piece))
        return cls(parts)

    def child(self, index: int):
        return Path(tuple(self) + (index,))

    def extend(self, parts):
        return Path(tuple(self) + tuple(parts))

    @property
    def parent(self):
        return Path(self[:-1]) if len(self) > 1 else None

    @property
    def depth(self) -> int:
        return len(self)

    def is_ancestor(self, other) -> bool:
        return len(self) < len(other) and tuple(other[:len(self)]) == tuple(self)

    def __str__(self):
        return "{" + ";".join(str(p) for p in self) + "}"

    def __repr__(self):
        return "Path%s" % str(self)


def as_path(p) -> Path:
    return p if isinstance(p, Path) else Path(p)


def sort_paths(paths: Iterable) -> list:
    return sorted(as_path(p) for p in paths)


def values_equal(a, b, tol: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        return a == b or abs(a - b) <= tol
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and str(a) == str(b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(values_equal(p, q, tol) for p, q in zip(a, b))
    return gv.close(a, b, tol)


class DataTree:
    def __init__(self, branches=None):
        self._d = {}
        self._order = None
        if branches is None:
            return
        pairs = branches.items() if hasattr(branches, "items") else branches
        for path, items in pairs:
            self.set_branch(path, items)

    @staticmethod
    def from_items(items: Iterable, path=Path((0,))):
        t = DataTree()
        t.set_branch(path, list(items))
        return t

    @staticmethod
    def from_item(item, path=Path((0,))):
        return DataTree.from_items([item], path)

    @staticmethod
    def coerce(value):
        if isinstance(value, DataTree):
            return value
        if isinstance(value, (list, tuple)):
            return DataTree.from_items(value)
        if value is None:
            return DataTree.from_items([None])
        return DataTree.from_item(value)

    def set_branch(self, path, items) -> None:
        p = as_path(path)
        if p not in self._d:
            self._order = None
        self._d[p] = list(items)

    def add(self, path, item) -> None:
        p = as_path(path)
        if p not in self._d:
            self._order = None
            self._d[p] = []
        self._d[p].append(item)

    def extend(self, path, items) -> None:
        p = as_path(path)
        if p not in self._d:
            self._order = None
            self._d[p] = []
        self._d[p].extend(items)

    def remove_branch(self, path) -> None:
        if self._d.pop(as_path(path), None) is not None:
            self._order = None

    def branch(self, path) -> list:
        return self._d[as_path(path)]

    def get(self, path, default=None):
        return self._d.get(as_path(path), default)

    @property
    def paths(self) -> list:
        if self._order is None:
            self._order = sorted(self._d)
        return list(self._order)

    def items(self) -> list:
        if self._order is None:
            self._order = sorted(self._d)
        return [(p, self._d[p]) for p in self._order]

    def flat_items(self) -> list:
        out = []
        for _, b in self.items():
            out.extend(b)
        return out

    @property
    def count(self) -> int:
        return len(self._d)

    @property
    def item_count(self) -> int:
        return sum(len(b) for b in self._d.values())

    @property
    def is_empty(self) -> bool:
        return not self._d

    @property
    def min_depth(self) -> int:
        return min((len(p) for p in self._d), default=0)

    @property
    def max_depth(self) -> int:
        return max((len(p) for p in self._d), default=0)

    def copy(self):
        t = DataTree()
        for p, b in self._d.items():
            t._d[p] = list(b)
        return t

    def __len__(self):
        return len(self._d)

    def __iter__(self):
        return iter(self.paths)

    def __contains__(self, path):
        try:
            return as_path(path) in self._d
        except TreeError:
            return False

    def equals(self, other, tol: float = 1e-9) -> bool:
        if not isinstance(other, DataTree) or self.paths != other.paths:
            return False
        for p in self._d:
            a, b = self._d[p], other._d[p]
            if len(a) != len(b) or not all(values_equal(x, y, tol) for x, y in zip(a, b)):
                return False
        return True

    def __eq__(self, other):
        return self.equals(other, 0.0)

    __hash__ = None

    def __str__(self):
        return format(self)

    def __repr__(self):
        return "DataTree(%s)" % format(self)


_NUM = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
_INT = re.compile(r"[+-]?\d+\Z")
_SYMBOL = re.compile(r"[A-Za-z_~][^\s,\[\]{}\"'():]*\Z")
_ESC = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "t": "\t", "r": "\r", "/": "/"}


def _perr(text: str, pos: int, what: str):
    raise TreeError("PARSE", "%s at position %d of %r" % (what, pos, text[:80]))


def _read_quoted(text: str, i: int):
    q = text[i]
    j = i + 1
    out = []
    while j < len(text):
        c = text[j]
        if c == "\\":
            if j + 1 >= len(text):
                _perr(text, j, "unfinished escape")
            e = text[j + 1]
            if e == "u":
                hx = text[j + 2:j + 6]
                if not re.fullmatch(r"[0-9a-fA-F]{4}", hx):
                    _perr(text, j, "bad \\u escape")
                out.append(chr(int(hx, 16)))
                j += 6
                continue
            if e not in _ESC:
                _perr(text, j, "unknown escape")
            out.append(_ESC[e])
            j += 2
            continue
        if c == q:
            return "".join(out), j + 1
        out.append(c)
        j += 1
    _perr(text, i, "unterminated text")


def _item_from_token(tok: str, text: str, pos: int):
    if tok == "true":
        return True
    if tok == "false":
        return False
    if tok == "null":
        return None
    if _INT.match(tok):
        return int(tok)
    if _NUM.match(tok):
        return float(tok)
    if _SYMBOL.match(tok):
        return Symbol(tok)
    _perr(text, pos, "bad value %r" % tok)


def parse(text: str) -> DataTree:
    s = text
    n = len(s)
    tree = DataTree()
    i = 0

    def ws(k):
        while k < n and s[k].isspace():
            k += 1
        return k

    i = ws(0)
    if i >= n or s[i:].strip() == EMPTY_TEXT:
        return tree
    while i < n:
        if s[i] != "{":
            _perr(s, i, "expected {")
        j = s.find("}", i)
        if j < 0:
            _perr(s, i, "unterminated path")
        path = Path.parse(s[i:j + 1])
        if path in tree:
            raise TreeError("PATH_DUPLICATE", "the path %s is written twice" % path)
        i = ws(j + 1)
        if i >= n or s[i] != ":":
            _perr(s, i, "expected :")
        i = ws(i + 1)
        if i >= n or s[i] != "[":
            _perr(s, i, "expected [")
        i = ws(i + 1)
        items = []
        if i < n and s[i] == "]":
            i += 1
        else:
            while True:
                i = ws(i)
                if i >= n:
                    _perr(s, i, "unterminated branch")
                if s[i] in "\"'":
                    val, i = _read_quoted(s, i)
                else:
                    k = i
                    while k < n and s[k] not in ",]" and not s[k].isspace():
                        k += 1
                    tok = s[i:k]
                    if tok == "":
                        _perr(s, i, "expected a value")
                    val = _item_from_token(tok, s, i)
                    i = k
                items.append(val)
                i = ws(i)
                if i >= n:
                    _perr(s, i, "unterminated branch")
                if s[i] == ",":
                    i += 1
                    continue
                if s[i] == "]":
                    i += 1
                    break
                _perr(s, i, "expected , or ]")
        tree.set_branch(path, items)
        i = ws(i)
    return tree


def format_item(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return json.dumps(str(v))
        return repr(v)
    if isinstance(v, Symbol):
        if _SYMBOL.match(v) and v not in ("true", "false", "null"):
            return str(v)
        return json.dumps(str(v), ensure_ascii=False)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    flat = gv.flat_numbers(v)
    if flat is not None:
        return json.dumps("%s(%s)" % (type(v).__name__, ",".join(repr(c) for c in flat)))
    return json.dumps("<%s>" % type(v).__name__)


def format(tree: DataTree) -> str:
    if tree.count == 0:
        return EMPTY_TEXT
    return " ".join("%s:[%s]" % (p, ",".join(format_item(v) for v in b)) for p, b in tree.items())


def _enc(v):
    return gv.encode(v)


def to_json(tree: DataTree) -> dict:
    return {
        "format": TREE_FORMAT,
        "version": TREE_VERSION,
        "branches": [{"path": list(p), "items": [_enc(v) for v in b]} for p, b in tree.items()],
    }


def from_json(obj) -> DataTree:
    if isinstance(obj, str):
        obj = json.loads(obj)
    if not isinstance(obj, dict) or obj.get("format") != TREE_FORMAT:
        raise TreeError("JSON_FORMAT", "not a %s document" % TREE_FORMAT)
    if int(obj.get("version", 0)) > TREE_VERSION:
        raise TreeError("JSON_VERSION", "a newer tree version %s is not readable" % obj.get("version"))
    t = DataTree()
    for br in obj.get("branches", []):
        p = Path(br["path"])
        if p in t:
            raise TreeError("PATH_DUPLICATE", "the path %s is stored twice" % p)
        t.set_branch(p, [gv.decode(v) for v in br.get("items", [])])
    return t


def to_map(tree: DataTree, kind: Optional[str] = None) -> dict:
    if kind is None:
        return {str(p): [_enc(v) for v in b] for p, b in tree.items()}
    return {str(p): [gv.to_wire(v, kind) for v in b] for p, b in tree.items()}


def from_map(obj: dict, kind: Optional[str] = None) -> DataTree:
    if not isinstance(obj, dict):
        raise TreeError("JSON_FORMAT", "a stored tree is an object keyed by path text")
    t = DataTree()
    for key, items in obj.items():
        p = Path.parse(key)
        if p in t:
            raise TreeError("PATH_DUPLICATE", "the path %s is stored twice" % p)
        if not isinstance(items, list):
            raise TreeError("JSON_FORMAT", "branch %s must be an array" % key)
        t.set_branch(p, [gv.decode(v) if kind is None else gv.from_wire(v, kind) for v in items])
    return t


def graft(tree: DataTree) -> DataTree:
    out = DataTree()
    for p, b in tree.items():
        for i, v in enumerate(b):
            out.set_branch(p.child(i), [v])
    return out


def flatten(tree: DataTree, path=None) -> DataTree:
    out = DataTree()
    if tree.count == 0:
        return out
    out.set_branch(Path((0,)) if path is None else as_path(path), tree.flat_items())
    return out


def simplify(tree: DataTree) -> DataTree:
    if tree.count == 0:
        return DataTree()
    paths = tree.paths
    first = paths[0]
    cap = min(len(p) for p in paths) - 1
    k = 0
    while k < cap and all(p[k] == first[k] for p in paths):
        k += 1
    out = DataTree()
    for p, b in tree.items():
        out.set_branch(Path(p[k:]), b)
    return out


def flip(tree: DataTree) -> DataTree:
    out = DataTree()
    if tree.count == 0:
        return out
    depths = {len(p) for p in tree.paths}
    if len(depths) > 1:
        raise TreeError("FLIP_VARIABLE_DEPTH", "flip needs every branch path to have the same depth")
    branches = [b for _, b in tree.items()]
    m = max(len(b) for b in branches)
    for j in range(m):
        out.set_branch(Path((j,)), [b[j] if j < len(b) else None for b in branches])
    return out


def flip_tree(tree: DataTree, position: int = 0) -> DataTree:
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise TreeError("FLIP_POSITION", "the position is a whole number from 0")
    out = DataTree()
    for p, b in tree.items():
        if position >= len(p):
            raise TreeError("FLIP_POSITION", "branch %s has no integer at position %d" % (p, position))
        for j, v in enumerate(b):
            q = list(p)
            q[position] = j
            out.add(Path(q), v)
    return out


def trim(tree: DataTree, depth: int = 1) -> DataTree:
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise TreeError("TRIM_DEPTH", "the trim depth is a whole number from 0")
    out = DataTree()
    for p, b in tree.items():
        keep = max(1, len(p) - depth)
        out.extend(Path(p[:keep]), b)
    return out


def shift_paths(tree: DataTree, offset: int, position="last") -> DataTree:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TreeError("SHIFT_OFFSET", "the offset is a whole number")
    out = DataTree()
    for p, b in tree.items():
        if position == "last":
            idx = len(p) - 1
        elif position == "first":
            idx = 0
        elif isinstance(position, int) and not isinstance(position, bool):
            idx = position if position >= 0 else len(p) + position
            if idx < 0 or idx >= len(p):
                out.extend(p, b)
                continue
        else:
            raise TreeError("SHIFT_POSITION", "the position is first, last or a whole number")
        q = list(p)
        q[idx] += offset
        if q[idx] < 0:
            raise TreeError("PATH_NEGATIVE", "shifting %s by %d makes a negative path number" % (p, offset))
        out.extend(Path(q), b)
    return out


def renumber(tree: DataTree, start: int = 0) -> DataTree:
    out = DataTree()
    for k, (_, b) in enumerate(tree.items()):
        out.set_branch(Path((start + k,)), b)
    return out


def clean(tree: DataTree, nulls: bool = True, empties: bool = True) -> DataTree:
    out = DataTree()
    for p, b in tree.items():
        items = [v for v in b if v is not None] if nulls else list(b)
        if empties and not items:
            continue
        out.set_branch(p, items)
    return out


PATH_MAP_PRESETS = {
    "flatten": "{A}(i) -> {0}(*)",
    "graft": "{A}(i) -> {A;i}(0)",
    "renumber": "{A}(i) -> {path_index}(i)",
    "reverse": "{A}(i) -> {path_count-1-path_index}(i)",
}
PATH_CONSTANTS = ("item_count", "path_count", "path_index")
_TOK = re.compile(r"\s*(?:(?P<int>\d+)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>->|[-+*/%();(){}]))")


def _tokens(text: str) -> list:
    out = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOK.match(text, pos)
        if not m:
            raise TreeError("PM_SYNTAX", "unexpected character %r in the mapping" % text[pos:].strip()[:1])
        pos = m.end()
        out.append((m.lastgroup, m.group(m.lastgroup)))
    return out


class _Expr:
    def __init__(self, toks, names):
        self.t = toks
        self.i = 0
        self.names = names

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self, depth=0):
        if depth > MAX_PATH_EXPR_DEPTH:
            raise TreeError("PM_SYNTAX", "the expression nests too deeply")
        left = self.term(depth)
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            left = (op, left, self.term(depth))
        return left

    def term(self, depth):
        left = self.unary(depth)
        while self.peek()[1] in ("*", "/", "%"):
            op = self.take()[1]
            left = (op, left, self.unary(depth))
        return left

    def unary(self, depth):
        if self.peek()[1] == "-":
            self.take()
            return ("neg", self.unary(depth), None)
        return self.atom(depth)

    def atom(self, depth):
        kind, val = self.take()
        if kind == "int":
            return ("num", int(val), None)
        if kind == "name":
            if val not in self.names and val not in PATH_CONSTANTS:
                raise TreeError("PM_NAME", "the name %s is not bound by the source pattern" % val)
            return ("var", val, None)
        if val == "(":
            e = self.parse(depth + 1)
            if self.take()[1] != ")":
                raise TreeError("PM_SYNTAX", "a bracket is not closed")
            return e
        raise TreeError("PM_SYNTAX", "an expression was expected")


def _eval(node, env):
    op, a, b = node
    if op == "num":
        return a
    if op == "var":
        return env[a]
    if op == "neg":
        return -_eval(a, env)
    x, y = _eval(a, env), _eval(b, env)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:
        raise TreeError("PM_DIVZERO", "the mapping divides by zero")
    return x // y if op == "/" else x % y


class PathMapping:
    def __init__(self, text: str):
        self.text = text
        toks = _tokens(text)
        kinds = [v for _, v in toks]
        if "->" not in kinds:
            raise TreeError("PM_SYNTAX", "a mapping is written source -> target")
        k = kinds.index("->")
        self.source, self.index_name = self._source(toks[:k])
        self.names = {n for n in self.source if isinstance(n, str)} | {self.index_name}
        self.target, self.key = self._target(toks[k + 1:])

    def _source(self, toks):
        vals = [v for _, v in toks]
        if len(vals) < 6 or vals[0] != "{" or "}" not in vals:
            raise TreeError("PM_SYNTAX", "the source is written {A;B}(i)")
        close = vals.index("}")
        inner = toks[1:close]
        rest = vals[close + 1:]
        if len(rest) != 3 or rest[0] != "(" or rest[2] != ")" or toks[close + 2][0] != "name":
            raise TreeError("PM_SYNTAX", "the source ends with (name) for the item index")
        index = rest[1]
        parts = []
        expect_val = True
        for kind, val in inner:
            if val == ";":
                if expect_val:
                    raise TreeError("PM_SYNTAX", "an empty slot in the source path")
                expect_val = True
                continue
            if not expect_val:
                raise TreeError("PM_SYNTAX", "slots in the source path are separated by ;")
            if kind == "int":
                parts.append(int(val))
            elif kind == "name":
                if val in PATH_CONSTANTS:
                    raise TreeError("PM_NAME", "%s is a constant and cannot be bound" % val)
                parts.append("_" if val == "_" else val)
            else:
                raise TreeError("PM_SYNTAX", "a source slot is a name, a whole number or _")
            expect_val = False
        if expect_val or not parts:
            raise TreeError("PM_SYNTAX", "the source path ends with a slot")
        named = [p for p in parts if isinstance(p, str) and p != "_"]
        if len(set(named + [index])) != len(named) + 1:
            raise TreeError("PM_NAME", "a name is bound twice in the source pattern")
        return parts, index

    def _target(self, toks):
        vals = [v for _, v in toks]
        if not vals or vals[0] != "{" or "}" not in vals:
            raise TreeError("PM_SYNTAX", "the target is written {A;i}(key)")
        close = len(vals) - 1 - vals[::-1].index("}")
        inner, rest = toks[1:close], toks[close + 1:]
        if len(rest) < 3 or rest[0][1] != "(" or rest[-1][1] != ")":
            raise TreeError("PM_SYNTAX", "the target ends with (key) or (*)")
        slots, cur, level = [], [], 0
        for tok in inner:
            if tok[1] == "(":
                level += 1
            elif tok[1] == ")":
                level -= 1
            if tok[1] == ";" and level == 0:
                slots.append(cur)
                cur = []
            else:
                cur.append(tok)
        slots.append(cur)
        exprs = []
        for sl in slots:
            if not sl:
                raise TreeError("PM_SYNTAX", "an empty slot in the target path")
            e = _Expr(sl, self.names)
            exprs.append(e.parse())
            if e.i != len(sl):
                raise TreeError("PM_SYNTAX", "extra text in a target slot")
        body = rest[1:-1]
        if len(body) == 1 and body[0][1] == "*":
            key = None
        else:
            e = _Expr(body, self.names)
            key = e.parse()
            if e.i != len(body):
                raise TreeError("PM_SYNTAX", "extra text in the key")
        return exprs, key

    def apply(self, tree: DataTree, warnings: Optional[list] = None) -> DataTree:
        paths = tree.paths
        path_count = len(paths)
        landing = {}
        seq = 0
        dropped = 0
        for pi, p in enumerate(paths):
            if len(p) != len(self.source):
                dropped += 1
                continue
            env = {}
            ok = True
            for slot, val in zip(self.source, p):
                if isinstance(slot, int):
                    if slot != val:
                        ok = False
                        break
                elif slot != "_":
                    env[slot] = val
            if not ok:
                dropped += 1
                continue
            branch = tree.branch(p)
            env["item_count"] = len(branch)
            env["path_count"] = path_count
            env["path_index"] = pi
            for idx, v in enumerate(branch):
                env[self.index_name] = idx
                tp = [_eval(e, env) for e in self.target]
                if any(c < 0 for c in tp):
                    raise TreeError("PATH_NEGATIVE", "the mapping makes the negative path %s" % (tp,))
                key = seq if self.key is None else _eval(self.key, env)
                landing.setdefault(Path(tp), []).append((key, seq, v))
                seq += 1
        if dropped and warnings is not None:
            warnings.append(("PATH_PATTERN_MISMATCH", "%d branch(es) did not match the source pattern" % dropped))
        out = DataTree()
        for tp, rows in landing.items():
            rows.sort(key=lambda r: (r[0], r[1]))
            out.set_branch(tp, [r[2] for r in rows])
        return out


def path_map(tree: DataTree, mapping, warnings: Optional[list] = None) -> DataTree:
    if isinstance(mapping, str) and mapping in PATH_MAP_PRESETS:
        mapping = PATH_MAP_PRESETS[mapping]
    if isinstance(mapping, str):
        mapping = PathMapping(mapping)
    return mapping.apply(tree, warnings)
