import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, NamedTuple, Optional

from app.graph import modifiers
from app.graph import tree as T

ACCESS = ("item", "list", "tree")
MODES = ("longest", "shortest", "cross")
CROSS_SCOPES = ("items",)
PRINCIPAL_RULES = ("extreme", "first")
DEFAULT_SETTINGS = {"cross_scope": "items", "principal_rule": "extreme"}
ROOT = T.Path((0,))


class Message(NamedTuple):
    level: str
    code: str
    text: str
    port: Optional[str] = None


class Call(NamedTuple):
    path: T.Path
    args: Optional[tuple]
    index: Optional[int]


class Result(NamedTuple):
    path: T.Path
    index: Optional[int]
    value: Any


class RunResult(NamedTuple):
    trees: list
    messages: list
    calls: int


class MatchCancelled(Exception):
    pass


EMPTY = object()
NULLED = object()


@dataclass
class MatchInput:
    name: str
    tree: Any
    access: str = "item"
    optional: bool = False
    default: Any = None
    mods: dict = field(default_factory=dict)


def settings_for(settings: Optional[dict]) -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(settings or {})
    if s["cross_scope"] not in CROSS_SCOPES:
        raise ValueError("cross_scope %r is not implemented, only %s" % (s["cross_scope"], ", ".join(CROSS_SCOPES)))
    if s["principal_rule"] not in PRINCIPAL_RULES:
        raise ValueError("principal_rule must be one of %s" % ", ".join(PRINCIPAL_RULES))
    return s


def _prepare(inp: MatchInput, seed: int):
    if inp.access not in ACCESS:
        raise ValueError("access must be one of %s" % ", ".join(ACCESS))
    tree = T.DataTree.coerce(inp.tree)
    tree = modifiers.apply(tree, inp.mods, seed)
    if tree.count == 0 and inp.optional:
        tree = T.DataTree.from_item(inp.default)
    return tree


def iterate(inputs: list, mode: str = "longest", settings: Optional[dict] = None, messages: Optional[list] = None, seed: int = 0) -> Iterator[Call]:
    if mode not in MODES:
        raise ValueError("mode must be one of %s" % ", ".join(MODES))
    st = settings_for(settings)
    msgs = messages if messages is not None else []
    trees = [_prepare(i, seed) for i in inputs]
    for inp, tr in zip(inputs, trees):
        if tr.count == 0 and not inp.optional:
            msgs.append(Message("warning", "NO_DATA", "input %s has no data" % inp.name, inp.name))
            return
    free = [k for k, i in enumerate(inputs) if i.access in ("item", "list")]
    if not free:
        yield Call(ROOT, tuple(trees), None)
        return
    branches = {k: trees[k].items() for k in free}
    counts = {k: len(branches[k]) for k in free}
    shortest = mode == "shortest"
    n_pairs = min(counts.values()) if shortest else max(counts.values())
    principal = next((k for k in free if modifiers.is_principal(inputs[k].mods)), None)
    if principal is None:
        if st["principal_rule"] == "first":
            principal = free[0]
        else:
            want = min(counts.values()) if shortest else max(counts.values())
            principal = next(k for k in free if counts[k] == want)
    item_ids = [k for k in free if inputs[k].access == "item"]
    for pair in range(n_pairs):
        paired = {k: branches[k][min(pair, counts[k] - 1)] for k in free}
        path = paired[principal][0]
        rows = {k: paired[k][1] for k in free}
        if not item_ids:
            yield Call(path, _args(inputs, trees, rows, {}), None)
            continue
        if any(len(rows[k]) == 0 for k in item_ids):
            yield Call(path, None, 0)
            continue
        lens = [len(rows[k]) for k in item_ids]
        if mode == "cross":
            combos = itertools.product(*[range(n) for n in lens])
        elif shortest:
            combos = (tuple([j] * len(item_ids)) for j in range(min(lens)))
        else:
            combos = (tuple(min(j, n - 1) for n in lens) for j in range(max(lens)))
        for j, combo in enumerate(combos):
            picks = {k: rows[k][c] for k, c in zip(item_ids, combo)}
            yield Call(path, _args(inputs, trees, rows, picks), j)


def _args(inputs, trees, rows, picks) -> tuple:
    out = []
    for k, inp in enumerate(inputs):
        if inp.access == "tree":
            out.append(trees[k])
        elif inp.access == "list":
            out.append(list(rows[k]))
        else:
            v = picks[k]
            out.append(inp.default if (v is None and inp.optional) else v)
    return tuple(out)


def collect(results: Iterable, n_outputs: int = 1, multi=False) -> list:
    flags = _multi_flags(multi, n_outputs)
    outs = [T.DataTree() for _ in range(n_outputs)]
    for path, index, value in results:
        if value is EMPTY:
            for o in range(n_outputs):
                at = path.child(0) if flags[o] and index is not None else path
                if at not in outs[o]:
                    outs[o].set_branch(at, [])
            continue
        if value is NULLED:
            vals = [None] * n_outputs
            nulled = True
        else:
            nulled = False
            vals = [value] if n_outputs == 1 else list(value)
            if len(vals) != n_outputs:
                raise ValueError("a call returned %d values for %d outputs" % (len(vals), n_outputs))
        for o in range(n_outputs):
            v = vals[o]
            if flags[o]:
                at = path.child(index) if index is not None else path
                if nulled:
                    outs[o].extend(at, [None])
                else:
                    if v is None:
                        v = []
                    if not isinstance(v, (list, tuple, T.DataTree)):
                        raise ValueError("output %d is a multi output and must return a list" % o)
                    outs[o].extend(at, v.flat_items() if isinstance(v, T.DataTree) else v)
            else:
                outs[o].add(path, v)
    return outs


def _multi_flags(multi, n: int) -> list:
    if isinstance(multi, (list, tuple)):
        if len(multi) != n:
            raise ValueError("multi needs one flag per output")
        return [bool(m) for m in multi]
    return [bool(multi)] * n


def run(inputs: list, fn: Callable, n_outputs: int = 1, mode: str = "longest", settings: Optional[dict] = None, multi=False, out_mods: Optional[list] = None, seed: int = 0, cancelled: Optional[Callable] = None) -> RunResult:
    msgs = []
    results = []
    calls = 0
    item_ids = [k for k, i in enumerate(inputs) if i.access == "item" and not i.optional]
    nulls = 0
    for call in iterate(inputs, mode, settings, msgs, seed):
        if cancelled is not None and cancelled():
            raise MatchCancelled()
        if call.args is None:
            results.append(Result(call.path, call.index, EMPTY))
            continue
        if call.index is not None and any(call.args[k] is None for k in item_ids):
            nulls += 1
            results.append(Result(call.path, call.index, NULLED))
            continue
        calls += 1
        results.append(Result(call.path, call.index, fn(*call.args)))
    if nulls:
        for _ in range(nulls):
            msgs.append(Message("warning", "NULL_INPUT", "a call was skipped because an input item was null", None))
    trees = collect(results, n_outputs, multi)
    if out_mods:
        trees = [modifiers.apply(t, m, seed) if m else t for t, m in zip(trees, out_mods)]
    return RunResult(trees, msgs, calls)
