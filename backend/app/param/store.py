import copy

from app.param import expr as X
from app.param import units as U

PARAMS = "parameters"
CONS = "constraints"
SKETCHES = "sketches"

DEFAULT_SETTINGS = {
    "infer": 0, "distance_tol": 1e-6, "angle_tol": 1e-4, "auto_types": ["coincident", "concentric", "tangent", "horizontal", "vertical", "collinear", "perpendicular", "parallel", "equal"],
    "bars": "all", "bar_except": [], "dims": "all", "dim_except": [], "bar_transparency": 0,
}
SETTINGS_KEY = "CONSTRAINTSETTINGS"
GEOMETRIC_WORDS = ("coincident", "collinear", "concentric", "fix", "parallel", "perpendicular", "horizontal", "vertical", "tangent", "smooth", "symmetric", "equal")
DIM_KINDS = ("distance", "hdistance", "vdistance", "angle", "radius", "diameter")
LABEL_PREFIX = {"distance": "d", "hdistance": "d", "vdistance": "d", "angle": "ang", "radius": "rad", "diameter": "dia"}
ANGLE_KINDS = ("angle",)
IMPLICIT_BASE = 1_000_000_000


class ParamError(ValueError):
    pass


def records(d, table: str) -> list:
    t = d.tables.get(table)
    return t.values() if t is not None else []


def constraints(d) -> list:
    return sorted(records(d, CONS), key=lambda r: r["id"])


def has_constraints(d) -> bool:
    t = d.tables.get(CONS)
    return t is not None and len(t) > 0


def user_params(d) -> list:
    return records(d, PARAMS)


def sketches(d) -> list:
    return records(d, SKETCHES)


def get_sketch(d, name: str):
    t = d.tables.get(SKETCHES)
    return t.get(name) if t is not None else None


def members(d, rec) -> list:
    have = list(rec["entities"])
    seen = set(have)
    for h in d.spaces.get("sketch:" + rec["name"], []):
        if h not in seen and h in d.ents and d.ents[h].kind not in ("dimension", "text", "mtext"):
            have.append(h)
            seen.add(h)
    return have


def con_key(cid: int) -> str:
    return "c%d" % cid


def get_con(d, cid: int):
    return d.tables[CONS].get(con_key(cid))


def next_id(d) -> int:
    ids = [r["id"] for r in records(d, CONS)]
    return (max(ids) + 1) if ids else 1


def put_con(d, rec: dict) -> None:
    rec = copy.deepcopy(rec)
    rec["name"] = con_key(rec["id"])
    d.table_set(CONS, rec)


def drop_con(d, cid: int) -> None:
    d.table_remove(CONS, con_key(cid))


def put_param(d, rec: dict) -> None:
    d.table_set(PARAMS, copy.deepcopy(rec))


def put_sketch(d, rec: dict) -> None:
    d.table_set(SKETCHES, copy.deepcopy(rec))


def settings(d) -> dict:
    out = copy.deepcopy(DEFAULT_SETTINGS)
    raw = d.header.get(SETTINGS_KEY)
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    return out


def save_settings(d, values: dict) -> None:
    d.set_header(SETTINGS_KEY, copy.deepcopy(values))


def dim_records(d) -> list:
    return [r for r in constraints(d) if r.get("label")]


def next_label(d, kind: str) -> str:
    pre = LABEL_PREFIX[kind]
    used = {r["label"].casefold() for r in dim_records(d)} | {p["name"].casefold() for p in user_params(d)}
    n = 1
    for r in dim_records(d):
        lab = r["label"]
        if lab.startswith(pre) and lab[len(pre):].isdigit():
            n = max(n, int(lab[len(pre):]) + 1)
    while ("%s%d" % (pre, n)).casefold() in used:
        n += 1
    return "%s%d" % (pre, n)


def name_taken(d, name: str, ignore: str = "") -> bool:
    low = name.casefold()
    if low == ignore.casefold():
        return False
    return any(r["label"].casefold() == low for r in dim_records(d)) or any(p["name"].casefold() == low for p in user_params(d))


class Scope:
    def __init__(self, d, params=None, dims=None):
        self.d = d
        self.params = {p["name"].casefold(): p for p in (params if params is not None else user_params(d))}
        self.dims = {r["label"].casefold(): r for r in (dims if dims is not None else dim_records(d))}
        self.memo = {}
        self.stack = []

    def lookup(self, name: str, sketch=None) -> float:
        key = name.casefold()
        if key in self.memo:
            return self.memo[key]
        if key in self.stack:
            ring = self.stack[self.stack.index(key):] + [key]
            raise X.ExprError("Circular reference: " + " -> ".join(ring))
        rec = self.dims.get(key)
        if rec is not None:
            if sketch and (rec.get("sketch") or "").casefold() != sketch.casefold():
                raise X.ExprError("%s is not in sketch %s." % (name, sketch))
            if not rec.get("driving", True):
                if self.stack and self.stack[-1] in self.dims and self.dims[self.stack[-1]].get("driving", True):
                    raise X.ExprError("%s is a reference dimension and cannot drive %s." % (name, self.stack[-1]))
                val = float(rec.get("value") or 0.0)
                self.memo[key] = val
                return val
            src = rec.get("expr") or ""
            if not src.strip():
                val = float(rec.get("value") or 0.0)
            else:
                self.stack.append(key)
                try:
                    val = X.evaluate(src, self.d, self.lookup)
                finally:
                    self.stack.pop()
            self.memo[key] = val
            return val
        prm = self.params.get(key)
        if prm is None:
            raise X.ExprError("Unknown name '%s'." % name)
        self.stack.append(key)
        try:
            val = self.user_value(prm)
        finally:
            self.stack.pop()
        self.memo[key] = val
        return val

    def user_value(self, prm) -> float:
        src = prm.get("expr") or "0"
        val = X.evaluate(src, self.d, self.lookup)
        unit = prm.get("unit") or ""
        if unit and X.pure_number(src):
            val = U.to_base(self.d, val, unit)
        return val

    def evaluate_text(self, src: str, unit: str = "") -> float:
        val = X.evaluate(src, self.d, self.lookup)
        if unit and X.pure_number(src):
            val = U.to_base(self.d, val, unit)
        return val


def dependents(d, label: str, params=None, dims=None) -> list:
    low = label.casefold()
    out = []
    for p in (params if params is not None else user_params(d)):
        if p["name"].casefold() != low and (low, None) in _refs_names(p.get("expr") or ""):
            out.append(p["name"])
    for r in (dims if dims is not None else dim_records(d)):
        if r["label"].casefold() != low and r.get("driving", True) and (low, None) in _refs_names(r.get("expr") or ""):
            out.append(r["label"])
    return out


def _refs_names(src: str) -> set:
    if not src.strip():
        return set()
    try:
        return {(n, None) for n, _s in X.references(src)}
    except X.ExprError:
        return set()
