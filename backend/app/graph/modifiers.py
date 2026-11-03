import random

from app.calc import engine as cal
from app.graph import tree as T
from app.graph import values as gv

MOD_ORDER = (
    "expression", "null_to", "invert", "remove_null", "remove_empty", "flatten", "sort",
    "randomise", "reverse", "trim", "renumber", "graft", "simplify",
)
FLAG_KEYS = ("flatten", "graft", "simplify", "reverse", "invert", "principal", "remove_null", "remove_empty", "sort", "randomise", "renumber")
ALIASES = {"negate": "invert", "randomize": "randomise"}


class ModifierError(T.TreeError):
    pass


def normalise(mods) -> dict:
    out = {}
    for k, v in (mods or {}).items():
        out[ALIASES.get(k, k)] = v
    if out.get("null_to_true"):
        out["null_to"] = True
    if out.get("null_to_false"):
        out["null_to"] = False
    expr = out.get("expression")
    out["expression"] = expr.strip() if isinstance(expr, str) and expr.strip() else None
    tr = out.get("trim")
    out["trim"] = 1 if tr is True else (int(tr) if isinstance(tr, int) and not isinstance(tr, bool) and tr > 0 else 0)
    for k in FLAG_KEYS:
        out[k] = bool(out.get(k, False))
    if out.get("null_to") not in (True, False):
        out["null_to"] = None
    return out


def is_principal(mods) -> bool:
    return bool((mods or {}).get("principal"))


def active(mods) -> bool:
    m = normalise(mods)
    return bool(m["expression"] or m["null_to"] is not None or m["trim"] or any(m[k] for k in FLAG_KEYS if k != "principal"))


def _expr(tree: T.DataTree, expression: str) -> T.DataTree:
    out = T.DataTree()
    for p, b in tree.items():
        row = []
        for v in b:
            if v is None:
                row.append(None)
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ModifierError("EXPRESSION_TYPE", "an expression works on numbers, got %s" % gv.kind_of(v))
            try:
                r = cal.evaluate(expression, {"x": v})
            except cal.CalcError as err:
                raise ModifierError("EXPRESSION", str(err))
            if cal.is_vec(r):
                r = gv.Point3(r[0], r[1], 0.0)
            row.append(r)
        out.set_branch(p, row)
    return out


def _map_items(tree: T.DataTree, fn) -> T.DataTree:
    out = T.DataTree()
    for p, b in tree.items():
        out.set_branch(p, [fn(v) for v in b])
    return out


def _rank(v):
    if v is None:
        return (0, 0, "")
    if isinstance(v, bool):
        return (1, int(v), "")
    if isinstance(v, (int, float)):
        return (2, v, "")
    if isinstance(v, str):
        return (3, 0, str(v))
    return (4, 0, "%s%r" % (type(v).__name__, gv.flat_numbers(v)))


def _sort(tree: T.DataTree) -> T.DataTree:
    out = T.DataTree()
    for p, b in tree.items():
        out.set_branch(p, sorted(b, key=_rank))
    return out


def _randomise(tree: T.DataTree, seed: int) -> T.DataTree:
    out = T.DataTree()
    for p, b in tree.items():
        rows = list(b)
        random.Random("%s:%s" % (seed, p)).shuffle(rows)
        out.set_branch(p, rows)
    return out


def _reverse(tree: T.DataTree) -> T.DataTree:
    out = T.DataTree()
    for p, b in tree.items():
        out.set_branch(p, b[::-1])
    return out


def apply(tree: T.DataTree, mods, seed: int = 0) -> T.DataTree:
    if not active(mods):
        return tree
    m = normalise(mods)
    t = tree
    if m["expression"]:
        t = _expr(t, m["expression"])
    if m["null_to"] is not None:
        fill = m["null_to"]
        t = _map_items(t, lambda v: fill if v is None else v)
    if m["invert"]:
        t = _map_items(t, lambda v: (not v) if isinstance(v, bool) else v)
    if m["remove_null"]:
        t = T.clean(t, nulls=True, empties=False)
    if m["remove_empty"]:
        t = T.clean(t, nulls=False, empties=True)
    if m["flatten"]:
        t = T.flatten(t)
    if m["sort"]:
        t = _sort(t)
    elif m["randomise"]:
        t = _randomise(t, seed)
    if m["reverse"]:
        t = _reverse(t)
    if m["trim"] and not m["flatten"]:
        t = T.trim(t, m["trim"])
    if m["renumber"] and not m["flatten"]:
        t = T.renumber(t)
    if m["graft"]:
        t = T.graft(t)
    if m["simplify"] and not m["flatten"] and not m["renumber"]:
        t = T.simplify(t)
    return t
