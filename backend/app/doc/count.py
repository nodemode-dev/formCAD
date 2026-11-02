from app.doc.model import SPACE_MODEL, block_space, layout_space

MAX_DEPTH = 16
MAX_STEPS = 5_000_000
MAX_HIGHLIGHT = 100_000
PROPS = ("handle", "owner", "layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "thickness", "normal", "plot_style", "annotation_scales", "xdata", "reactors", "extra")


class CountResult:
    def __init__(self):
        self.direct: dict = {}
        self.nested: dict = {}
        self.capped = False
        self.deep = False

    def names(self) -> list:
        return sorted(set(self.direct) | set(self.nested), key=str.casefold)

    def total(self) -> int:
        return sum(self.direct.values()) + sum(self.nested.values())

    def rows(self) -> list:
        return [{"name": n, "count": self.direct.get(n, 0), "nested": self.nested.get(n, 0)} for n in self.names()]


def multiplicity(ent) -> int:
    arr = ent.array or {}
    rows = max(1, min(int(arr.get("rows", 1) or 1), 100))
    cols = max(1, min(int(arr.get("cols", arr.get("columns", 1)) or 1), 100))
    return rows * cols


def report_name(d, name: str) -> str:
    rec = d.tables["blocks"].get(name)
    if rec is None:
        return name
    base = rec.get("dyn_of")
    return str(base) if base else name


def shown(d, name: str) -> bool:
    rec = d.tables["blocks"].get(name)
    return not name.startswith("*") and not (rec and rec.get("anonymous") and not rec.get("dyn_of"))


def space_names(d, scope: str, current: str) -> list:
    low = scope.strip().lower()
    if low in ("", "current"):
        return [current]
    if low == "model":
        return [SPACE_MODEL]
    if low == "all":
        return [SPACE_MODEL] + [layout_space(r["name"]) for r in sorted(d.tables["layouts"].values(), key=lambda r: r.get("order", 0))]
    for rec in d.tables["layouts"].values():
        if rec["name"].casefold() == scope.strip().casefold():
            return [layout_space(rec["name"])]
    return []


def scope_label(d, scope: str, current: str) -> str:
    low = scope.strip().lower()
    if low == "selection":
        return "the selection"
    if low == "all":
        return "all spaces"
    sp = space_names(d, scope, current)
    if not sp:
        return scope
    s = sp[0]
    return "model space" if s == SPACE_MODEL else "layout " + s.split(":", 1)[1] if s.startswith("layout:") else s


def count_blocks(d, spaces: list, handles=None) -> CountResult:
    res = CountResult()
    inserts = []
    if handles is not None:
        for h in handles:
            e = d.get(h)
            if e is not None and e.kind == "insert":
                inserts.append(e)
    else:
        for sp in spaces:
            inserts.extend(e for e in d.entities(sp) if e.kind == "insert")
    top: dict = {}
    for e in inserts:
        top[e.block] = top.get(e.block, 0) + multiplicity(e)
    for name, n in top.items():
        if shown(d, name):
            key = report_name(d, name)
            res.direct[key] = res.direct.get(key, 0) + n
    steps = [0]

    def walk(name: str, mult: int, depth: int) -> None:
        if depth >= MAX_DEPTH:
            res.deep = True
            return
        rec = d.tables["blocks"].get(name)
        if rec is None or rec.get("xref"):
            return
        for e in d.entities(block_space(name)):
            if e.kind != "insert":
                continue
            steps[0] += 1
            if steps[0] > MAX_STEPS:
                res.capped = True
                return
            m = mult * multiplicity(e)
            if shown(d, e.block):
                key = report_name(d, e.block)
                res.nested[key] = res.nested.get(key, 0) + m
            walk(e.block, m, depth + 1)
            if res.capped:
                return

    for name, n in top.items():
        walk(name, n, 0)
        if res.capped:
            break
    return res


def _round(v):
    if isinstance(v, float):
        return round(v, 6) + 0.0
    if isinstance(v, (list, tuple)):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in sorted(v.items())}
    return v


def _shift(v, dx, dy):
    if isinstance(v, (list, tuple)):
        if len(v) in (2, 3) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            return [v[0] - dx, v[1] - dy] + list(v[2:])
        return [_shift(x, dx, dy) for x in v]
    if isinstance(v, dict):
        return {k: (_shift(x, dx, dy) if k in ("p", "start", "end", "center", "position", "base", "points", "vertices", "corners", "control_points", "fit_points", "loops") else x) for k, x in v.items()}
    return v


def shape_key(ent) -> str:
    b = ent.bounds()
    dx, dy = (b[0], b[1]) if b else (0.0, 0.0)
    data = ent.to_dict()
    for p in PROPS:
        data.pop(p, None)
    return repr(_round(_shift(data, dx, dy)))


def count_like(d, spaces: list, sample, handles=None) -> list:
    key = shape_key(sample)
    out = []
    pool = []
    if handles is not None:
        pool = [d.get(h) for h in handles]
    else:
        for sp in spaces:
            pool.extend(d.entities(sp))
    for e in pool:
        if e is None or e.kind != sample.kind:
            continue
        if sample.kind == "insert":
            if e.block == sample.block:
                out.append(e.handle)
        elif shape_key(e) == key:
            out.append(e.handle)
    return out
