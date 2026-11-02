import base64
import copy
import math
import os
import tempfile

from app.doc import container, geom
from app.doc.model import SPACE_MODEL, block_space

MAX_OBJECTS = 200_000
MAX_LISTED = 1000
MAX_GRID = 8
MAX_DEPTH = 16
SKIP = ("handle", "owner", "reactors", "extra", "xdata")
DIM_SKIP = ("block", "measurement", "text_moved")
GREEN = 3
RED = 1
GRAY = 8


class CompareError(Exception):
    pass


def _round(v):
    if isinstance(v, float):
        return round(v, 6) + 0.0
    if isinstance(v, (list, tuple)):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in sorted(v.items())}
    return v


def block_sig(d, name, depth=0, memo=None):
    memo = memo if memo is not None else {}
    low = name.casefold()
    if low in memo:
        return memo[low]
    if depth >= MAX_DEPTH or not d.tables["blocks"].has(name):
        return ""
    memo[low] = "~"
    parts = sorted(full_sig(d, e, depth + 1, memo) for e in d.entities(block_space(name)))
    memo[low] = "|".join(parts)
    return memo[low]


def geometry_data(e) -> dict:
    data = e.to_dict()
    for k in SKIP:
        data.pop(k, None)
    return data


def full_sig(d, e, depth=0, memo=None) -> str:
    data = geometry_data(e)
    if e.kind == "dimension":
        for k in DIM_SKIP:
            data.pop(k, None)
    if e.kind == "insert":
        name = data.pop("block", "")
        data["block_content"] = block_sig(d, name, depth, memo)
        if not name.startswith("*"):
            data["block_name"] = name
    return repr(_round(data))


def load_other(spec: str, data: str = "", name: str = ""):
    if data:
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:
            raise CompareError("The inline drawing data is not valid base64.")
        suffix = os.path.splitext(name or "x.fcad")[1] or ".fcad"
        with tempfile.TemporaryDirectory(prefix="fccmp_") as tmp:
            path = os.path.join(tmp, "inline" + suffix)
            with open(path, "wb") as fh:
                fh.write(raw)
            return read_file(path), name or "inline"
    return read_file(spec), os.path.basename(spec)


def read_file(path: str):
    full = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(full):
        raise CompareError('Cannot find the drawing "%s".' % path)
    ext = os.path.splitext(full)[1].lower()
    try:
        if ext == ".fcad":
            return container.load(full)[0]
        from app.interchange import files

        return files.read_any(full)[0]
    except container.ContainerError as err:
        raise CompareError(err.message)
    except Exception as err:
        raise CompareError(getattr(err, "message", None) or str(err))


def find_open(service, spec: str, current):
    s = str(spec or "").strip()
    if not s:
        return None
    low = s.casefold()
    docs = list(service.docs.values())
    if s.isdigit() and 1 <= int(s) <= len(docs):
        return docs[int(s) - 1]
    for d in docs:
        if d.id == s or d.name.casefold() == low or (d.path and os.path.realpath(d.path) == os.path.realpath(os.path.expanduser(s))):
            return d
    return None


def pool(d, space):
    ents = list(d.entities(space)) if space in d.spaces else []
    if len(ents) > MAX_OBJECTS:
        return ents[:MAX_OBJECTS], len(ents) - MAX_OBJECTS
    return ents, 0


def diff(d1, d2, space: str) -> dict:
    a, cut_a = pool(d1, space)
    b, cut_b = pool(d2, space)
    sig_a = {e.handle: full_sig(d1, e) for e in a}
    sig_b = {e.handle: full_sig(d2, e) for e in b}
    buckets = {}
    for h, s in sig_b.items():
        buckets.setdefault(s, []).append(h)
    both = []
    left_a = []
    taken = set()
    for e in a:
        s = sig_a[e.handle]
        if e.handle in buckets.get(s, ()) and e.handle not in taken:
            taken.add(e.handle)
            both.append((e.handle, e.handle))
        else:
            left_a.append(e)
    rest_a = []
    for e in left_a:
        s = sig_a[e.handle]
        cand = next((h for h in buckets.get(s, ()) if h not in taken), None)
        if cand is not None:
            taken.add(cand)
            both.append((e.handle, cand))
        else:
            rest_a.append(e)
    rest_b = {e.handle: e for e in b if e.handle not in taken}
    changed = []
    only_a = []
    for e in rest_a:
        o = rest_b.get(e.handle)
        if o is not None and o.kind == e.kind:
            changed.append((e.handle, o.handle))
            del rest_b[e.handle]
        else:
            only_a.append(e.handle)
    return {"same": both, "changed": changed, "only_this": only_a, "only_other": list(rest_b), "cut": cut_a + cut_b}


def bounds_of(d, h):
    e = d.ents.get(h)
    return e.bounds() if e is not None else None


def areas(d1, d2, result) -> list:
    boxes = []
    for h in result["only_this"]:
        boxes.append(bounds_of(d1, h))
    for h in result["only_other"]:
        boxes.append(bounds_of(d2, h))
    for h1, h2 in result["changed"]:
        boxes.append(geom.union_bounds(bounds_of(d1, h1), bounds_of(d2, h2)))
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return []
    ext = None
    for b in boxes:
        ext = geom.union_bounds(ext, b)
    n = max(1, min(MAX_GRID, int(math.ceil(math.sqrt(len(boxes))))))
    w = max(ext[2] - ext[0], 1e-12) / n
    h = max(ext[3] - ext[1], 1e-12) / n
    cells = {}
    for b in boxes:
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0
        col = min(n - 1, int((cx - ext[0]) / w))
        row = min(n - 1, int((ext[3] - cy) / h))
        cell = cells.setdefault((row, col), {"box": None, "count": 0})
        cell["box"] = geom.union_bounds(cell["box"], b)
        cell["count"] += 1
    return [{"box": list(c["box"]), "count": c["count"]} for _k, c in sorted(cells.items())]


def compare(doc, other_drawing, other_name: str, other_path: str = "") -> dict:
    space = doc.current_space
    res = diff(doc.drawing, other_drawing, space)
    out = {
        "other": other_name,
        "other_path": other_path,
        "space": space,
        "only_this": res["only_this"][:MAX_LISTED],
        "only_other": res["only_other"][:MAX_LISTED],
        "changed": [{"this": a, "other": b} for a, b in res["changed"][:MAX_LISTED]],
        "counts": {"same": len(res["same"]), "only_this": len(res["only_this"]), "only_other": len(res["only_other"]), "changed": len(res["changed"])},
        "left_out": res["cut"],
        "areas": areas(doc.drawing, other_drawing, res),
        "index": -1,
        "_drawing": other_drawing,
        "_same": res["same"],
    }
    out["listed_all"] = all(len(res[k]) <= MAX_LISTED for k in ("only_this", "only_other", "changed"))
    return out


def public(state) -> dict:
    if state is None:
        return {"active": False}
    out = {k: v for k, v in state.items() if not k.startswith("_")}
    d2 = state["_drawing"]
    out["active"] = True
    out["overlay"] = {"current": list(state["only_this"]), "other": [d2.ents[h].to_dict() for h in state["only_other"] if h in d2.ents], "changed_other": [d2.ents[c["other"]].to_dict() for c in state["changed"] if c["other"] in d2.ents], "changed_current": [c["this"] for c in state["changed"]]}
    return out


def recolour_entity(e, colour):
    c = copy.deepcopy(e)
    c.color = colour
    c.handle = 0
    c.reactors = []
    c.extra = {k: v for k, v in c.extra.items() if k != "box"} if c.extra else {}
    return c


def export(doc, state, service, other_d):
    d1 = doc.drawing
    space = state["space"]
    title = "compare_%s vs %s.dwg" % (doc.name, state["other"])
    new = service.new(title)
    nd = new.drawing
    with new.transaction("COMPAREEXPORT"):
        for kind in ("layers", "linetypes", "textstyles", "dimstyles", "mleaderstyles", "tablestyles", "mlinestyles", "scales"):
            for rec in d1.tables[kind].values():
                if not nd.tables[kind].has(rec["name"]):
                    nd.table_set(kind, copy.deepcopy(rec))
            for rec in other_d.tables[kind].values():
                if not nd.tables[kind].has(rec["name"]):
                    nd.table_set(kind, copy.deepcopy(rec))
        memo = {}

        def block_copy(src_d, name, colour, depth=0):
            key = (id(src_d), name.casefold(), colour)
            if key in memo:
                return memo[key]
            new_name = "%s$%s" % (name.lstrip("*") or "B", {GREEN: "CUR", RED: "OTH", GRAY: "SAME"}[colour])
            if not src_d.tables["blocks"].has(name) or depth >= MAX_DEPTH:
                return name
            memo[key] = new_name
            if not nd.tables["blocks"].has(new_name):
                rec = src_d.tables["blocks"].get(name)
                nd.define_block(new_name, rec.get("base"), rec.get("description", ""))
                for child in src_d.entities(block_space(name)):
                    c = recolour_entity(child, colour)
                    if c.kind == "insert":
                        c.block = block_copy(src_d, c.block, colour, depth + 1)
                    nd.add_entity(c, block_space(new_name))
            return new_name

        def put(src_d, e, colour):
            c = recolour_entity(e, colour)
            if c.kind == "insert":
                c.block = block_copy(src_d, c.block, colour)
            if c.kind == "dimension":
                c.associativity = {}
            return nd.add_entity(c, SPACE_MODEL)

        groups = {"COMPARE_COMPARED": [], "COMPARE_CURRENT": []}
        for h in state["only_other"]:
            if h in other_d.ents:
                groups["COMPARE_COMPARED"].append(put(other_d, other_d.ents[h], RED))
        for c in state["changed"]:
            if c["other"] in other_d.ents:
                groups["COMPARE_COMPARED"].append(put(other_d, other_d.ents[c["other"]], RED))
        for h in state["only_this"]:
            if h in d1.ents:
                groups["COMPARE_CURRENT"].append(put(d1, d1.ents[h], GREEN))
        for c in state["changed"]:
            if c["this"] in d1.ents:
                groups["COMPARE_CURRENT"].append(put(d1, d1.ents[c["this"]], GREEN))
        for a, _b in state["_same"]:
            if a in d1.ents:
                put(d1, d1.ents[a], GRAY)
        from app.doc import groups as G

        for name, members in groups.items():
            if members:
                G.create(nd, members, name)
    return new
