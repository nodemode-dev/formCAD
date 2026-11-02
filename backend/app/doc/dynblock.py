import copy
import json
import math
import re

from app.doc import blocktools as BT
from app.doc.blocktools import EditError
from app.doc.blockxf import clone_through, insert_matrices
from app.doc.model import block_space
from app.text.model import affine

PARAM_TYPES = ("linear", "rotation", "flip", "visibility", "point", "lookup", "base")
ACTION_TYPES = ("stretch", "move", "scale", "rotate", "flip", "array")


def definition(rec):
    dyn = rec.get("dynamic") if rec else None
    return dyn if isinstance(dyn, dict) and dyn.get("parameters") else None


def _num(v, what):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise EditError("%s must be a number." % what)
    if not math.isfinite(f):
        raise EditError("%s must be a finite number." % what)
    return f


def validate(data) -> dict:
    if not isinstance(data, dict):
        raise EditError("Dynamic data must be an object.")
    params = data.get("parameters", [])
    actions = data.get("actions", [])
    if not isinstance(params, list) or not isinstance(actions, list):
        raise EditError("Parameters and actions must be lists.")
    names = []
    for p in params:
        if not isinstance(p, dict) or p.get("type") not in PARAM_TYPES or not str(p.get("name", "")).strip():
            raise EditError("Every parameter needs a name and one of: %s." % ", ".join(PARAM_TYPES))
        if p["name"].casefold() in names:
            raise EditError('Parameter "%s" is defined twice.' % p["name"])
        names.append(p["name"].casefold())
        t = p["type"]
        if t == "linear":
            for k in ("base", "end"):
                if not (isinstance(p.get(k), list) and len(p[k]) >= 2):
                    raise EditError('Linear parameter "%s" needs base and end points.' % p["name"])
        if t == "visibility" and not (isinstance(p.get("states"), list) and p["states"]):
            raise EditError('Visibility parameter "%s" needs states.' % p["name"])
        if t == "lookup" and not (isinstance(p.get("rows"), list) and p["rows"]):
            raise EditError('Lookup parameter "%s" needs rows.' % p["name"])
    for a in actions:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            raise EditError("Every action needs one of: %s." % ", ".join(ACTION_TYPES))
        if str(a.get("param", "")).casefold() not in names:
            raise EditError("Action %s names a parameter that does not exist." % a["type"])
    return data


def define(doc, name, data) -> dict:
    d = doc.drawing
    rec = d.table_get("blocks", name)
    if rec is None or rec["name"].startswith("*"):
        raise EditError('Block "%s" not found.' % name)
    if data in (None, {}):
        rec = d.modify_record("blocks", rec["name"])
        rec["dynamic"] = None
        refresh_references(d, rec["name"])
        return {"name": rec["name"], "parameters": 0, "actions": 0}
    validate(data)
    rec = d.modify_record("blocks", rec["name"])
    rec["dynamic"] = copy.deepcopy(data)
    refresh_references(d, rec["name"])
    return {"name": rec["name"], "parameters": len(data.get("parameters", [])), "actions": len(data.get("actions", []))}


def read_definition(d, name) -> dict:
    rec = d.table_get("blocks", name)
    if rec is None:
        raise EditError('Block "%s" not found.' % name)
    src = rec.get("dyn_of") or rec["name"]
    rec = d.table_get("blocks", src)
    dyn = definition(rec)
    if dyn is None:
        return {"block": rec["name"], "dynamic": False, "parameters": [], "actions": [], "note": "This block has no dynamic data."}
    return {"block": rec["name"], "dynamic": True, "parameters": copy.deepcopy(dyn["parameters"]), "actions": copy.deepcopy(dyn.get("actions", [])), "note": "This is a dynamic block: its parameters and actions are kept but can't be edited yet."}


def _p(dyn, name):
    for p in dyn["parameters"]:
        if p["name"].casefold() == str(name).casefold():
            return p
    return None


def _dir(p):
    dx, dy = p["end"][0] - p["base"][0], p["end"][1] - p["base"][1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else (1.0, 0.0)


def default_value(p):
    t = p["type"]
    if t == "linear":
        return float(p["value"]) if "value" in p else math.hypot(p["end"][0] - p["base"][0], p["end"][1] - p["base"][1])
    if t == "rotation":
        return float(p.get("value", 0.0))
    if t == "flip":
        return int(p.get("value", 0))
    if t == "visibility":
        return str(p.get("value") or p["states"][0]["name"])
    if t == "point":
        v = p.get("value") or p.get("base") or [0.0, 0.0]
        return [float(v[0]), float(v[1])]
    if t == "lookup":
        return str(p.get("value") or p["rows"][0]["label"])
    return 0.0


def defaults(dyn) -> dict:
    return {p["name"]: default_value(p) for p in dyn["parameters"] if p["type"] != "base"}


def values_of(d, ins, dyn) -> dict:
    out = defaults(dyn)
    cur = (ins.extra or {}).get("dyn", {}).get("values", {}) if isinstance(ins.extra, dict) else {}
    for k, v in cur.items():
        p = _p(dyn, k)
        if p is not None:
            out[p["name"]] = v
    return out


def _stretch(ent, frame, vec):
    x0, y0, x1, y1 = frame

    def inside(p):
        return x0 - 1e-9 <= p[0] <= x1 + 1e-9 and y0 - 1e-9 <= p[1] <= y1 + 1e-9

    def sh(p):
        q = list(p)
        q[0] += vec[0]
        q[1] += vec[1]
        return q

    moved = False
    for name in ent.POINTS:
        v = getattr(ent, name)
        if v is not None and inside(v):
            setattr(ent, name, sh(v))
            moved = True
    for name in ent.POINT_LISTS:
        setattr(ent, name, [sh(p) if inside(p) else p for p in getattr(ent, name)])
    for name in ent.VERTEX_LISTS:
        for v in getattr(ent, name):
            if inside(v["p"]):
                v["p"] = sh(v["p"])
    if ent.kind == "hatch":
        for loop in ent.loops:
            for v in loop.get("vertices", []):
                if inside(v["p"]):
                    v["p"] = sh(v["p"])
    return moved


def _mat_rotate(a, b0):
    c, s = math.cos(a), math.sin(a)
    return affine(c, s, -s, c, b0[0] - (c * b0[0] - s * b0[1]), b0[1] - (s * b0[0] + c * b0[1]))


def _mat_scale(k, b0):
    return affine(k, 0.0, 0.0, k, b0[0] - k * b0[0], b0[1] - k * b0[1])


def _mat_flip(axis, b0):
    n = math.hypot(axis[0], axis[1]) or 1.0
    ux, uy = axis[0] / n, axis[1] / n
    a, b, c, dd = 2 * ux * ux - 1, 2 * ux * uy, 2 * ux * uy, 2 * uy * uy - 1
    return affine(a, b, c, dd, b0[0] - (a * b0[0] + c * b0[1]), b0[1] - (b * b0[0] + dd * b0[1]))


def evaluate(d, source, values) -> list:
    rec = d.table_get("blocks", source)
    dyn = definition(rec)
    base_ents = list(d.entities(block_space(rec["name"])))
    clones = {}
    order = []
    for e in base_ents:
        c = e.copy_as_new()
        clones[e.handle] = c
        order.append(e.handle)
    if dyn is None:
        return [clones[h] for h in order]
    dfl = defaults(dyn)
    hidden = set()
    for p in dyn["parameters"]:
        if p["type"] == "visibility":
            want = str(values.get(p["name"], dfl[p["name"]])).casefold()
            union = set()
            keep = set()
            for st in p["states"]:
                mem = {int(h) for h in st.get("members", [])}
                union |= mem
                if st["name"].casefold() == want:
                    keep = mem
            hidden |= union - keep
    for h in hidden:
        clones.pop(h, None)
        if h in order:
            order.remove(h)
    extra_copies = []
    for a in dyn.get("actions", []):
        p = _p(dyn, a["param"])
        val = values.get(p["name"], dfl[p["name"]])
        dv = dfl[p["name"]]
        members = [int(h) for h in a.get("members", [])] or list(order)
        members = [h for h in members if h in clones]
        t = a["type"]
        factor = float(a.get("factor", 1.0))
        if p["type"] == "linear":
            delta = (float(val) - float(dv)) * factor
            ux, uy = _dir(p)
            vec = [ux * delta, uy * delta, 0.0]
        elif p["type"] == "point":
            vec = [(float(val[0]) - float(dv[0])) * factor, (float(val[1]) - float(dv[1])) * factor, 0.0]
        else:
            vec = [0.0, 0.0, 0.0]
        b0 = a.get("base") or p.get("base") or [0.0, 0.0]
        if t == "stretch":
            frame = a.get("frame") or [0, 0, 0, 0]
            for h in members:
                _stretch(clones[h], frame, vec)
        elif t == "move":
            for h in members:
                clones[h].move_by(vec)
        elif t == "scale":
            k = (float(val) / float(dv)) if p["type"] == "linear" and abs(float(dv)) > 1e-12 else 1.0
            for h in members:
                out = clone_through(clones[h], _mat_scale(k, b0))
                if out is not None:
                    out.handle = 0
                    clones[h] = out
        elif t == "rotate":
            ang = math.radians(float(val) - float(dv)) if p["type"] == "rotation" else 0.0
            for h in members:
                out = clone_through(clones[h], _mat_rotate(ang, b0))
                if out is not None:
                    clones[h] = out
        elif t == "flip":
            if int(val) != int(dv):
                m = _mat_flip(p.get("axis") or [0.0, 1.0], b0)
                for h in members:
                    out = clone_through(clones[h], m)
                    if out is not None:
                        clones[h] = out
        elif t == "array":
            cols = max(1, int(a.get("columns", 1)))
            rows = max(1, int(a.get("rows", 1)))
            cd = float(a.get("column_distance", 0.0))
            rd = float(a.get("row_distance", 0.0))
            if p["type"] == "linear":
                cd += (float(val) - float(dv)) * factor
            for r in range(rows):
                for c in range(cols):
                    if r == 0 and c == 0:
                        continue
                    for h in members:
                        cp = clones[h].copy_as_new()
                        cp.move_by([c * cd, r * rd, 0.0])
                        extra_copies.append(cp)
    return [clones[h] for h in order if h in clones] + extra_copies


def _derived_number(d):
    n = 0
    for r in d.tables["blocks"].values():
        m = re.fullmatch(r"\*U(\d+)", r["name"])
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


def _is_default(dyn, values) -> bool:
    dfl = defaults(dyn)
    for k, v in values.items():
        p = _p(dyn, k)
        if p is None:
            continue
        if json.dumps(v) != json.dumps(dfl[p["name"]]) and not (isinstance(v, (int, float)) and isinstance(dfl[p["name"]], (int, float)) and abs(v - dfl[p["name"]]) < 1e-12):
            return False
    return True


def _fill(d, name, source, values):
    sp = block_space(name)
    for h in list(d.spaces.get(sp, [])):
        d.erase_entity(h)
    for c in evaluate(d, source, values):
        c.handle = 0
        d.add_entity(c, sp)


def derived_block(d, source, values) -> str:
    key = source.casefold() + "|" + json.dumps(values, sort_keys=True)
    for r in d.tables["blocks"].values():
        if r.get("dyn_key") == key:
            return r["name"]
    src = d.table_get("blocks", source)
    name = "*U%d" % _derived_number(d)
    d.define_block(name, list(src["base"]), "")
    rec = d.modify_record("blocks", name)
    rec["dyn_of"] = src["name"]
    rec["dyn_key"] = key
    rec["dyn_values"] = copy.deepcopy(values)
    _fill(d, name, src["name"], values)
    return name


def refresh_references(d, source) -> int:
    low = source.casefold()
    n = 0
    for r in list(d.tables["blocks"].values()):
        if str(r.get("dyn_of", "")).casefold() == low:
            rec = d.modify_record("blocks", r["name"])
            src = d.table_get("blocks", source)
            rec["base"] = list(src["base"])
            _fill(d, r["name"], source, rec["dyn_values"])
            n += 1
    return n


def _source(d, ins):
    dyn_info = (ins.extra or {}).get("dyn") if isinstance(ins.extra, dict) else None
    if isinstance(dyn_info, dict) and dyn_info.get("base"):
        return dyn_info["base"]
    return ins.block


def reference_properties(d, handle) -> dict:
    ins = d.get(int(handle))
    if ins is None or ins.kind != "insert":
        raise EditError("Select a block reference.")
    src = _source(d, ins)
    rec = d.table_get("blocks", src)
    dyn = definition(rec)
    if dyn is None:
        return {"block": ins.block, "dynamic": False, "properties": []}
    vals = values_of(d, ins, dyn)
    props = []
    for p in dyn["parameters"]:
        if p["type"] == "base":
            continue
        item = {"name": p["name"], "type": p["type"], "value": vals[p["name"]]}
        if p["type"] in ("linear", "rotation"):
            item.update({"min": p.get("min"), "max": p.get("max"), "increment": p.get("increment", 0), "list": list(p.get("list", []))})
        if p["type"] == "visibility":
            item["states"] = [s["name"] for s in p["states"]]
        if p["type"] == "lookup":
            item["rows"] = [r["label"] for r in p["rows"]]
        props.append(item)
    return {"block": src, "dynamic": True, "properties": props}


def snap_value(p, v):
    lst = [float(x) for x in p.get("list", [])]
    if lst:
        return min(lst, key=lambda x: abs(x - v))
    inc = float(p.get("increment", 0) or 0)
    lo = p.get("min")
    if inc > 0:
        origin = float(lo) if lo is not None else 0.0
        v = origin + round((v - origin) / inc) * inc
    if lo is not None and v < float(lo):
        v = float(lo)
    if p.get("max") is not None and v > float(p["max"]):
        v = float(p["max"])
    return v


def check_value(p, v):
    t = p["type"]
    if t in ("linear", "rotation"):
        f = _num(v, p["name"])
        lst = [float(x) for x in p.get("list", [])]
        if lst and not any(abs(f - x) < 1e-9 for x in lst):
            raise EditError("%s must be one of: %s." % (p["name"], ", ".join("%g" % x for x in lst)))
        if p.get("min") is not None and f < float(p["min"]) - 1e-9 or p.get("max") is not None and f > float(p["max"]) + 1e-9:
            raise EditError("%s is outside its allowed range." % p["name"])
        inc = float(p.get("increment", 0) or 0)
        if inc > 0 and not lst:
            origin = float(p["min"]) if p.get("min") is not None else 0.0
            k = (f - origin) / inc
            if abs(k - round(k)) > 1e-6:
                raise EditError("%s must be a multiple of %g." % (p["name"], inc))
        return f
    if t == "flip":
        if str(v).lower() in ("1", "true", "flipped"):
            return 1
        if str(v).lower() in ("0", "false", "not flipped"):
            return 0
        raise EditError("%s is 0 or 1." % p["name"])
    if t == "visibility":
        for s in p["states"]:
            if s["name"].casefold() == str(v).casefold():
                return s["name"]
        raise EditError('Visibility state "%s" does not exist.' % v)
    if t == "point":
        if not (isinstance(v, (list, tuple)) and len(v) >= 2):
            raise EditError("%s needs a point." % p["name"])
        return [_num(v[0], p["name"]), _num(v[1], p["name"])]
    if t == "lookup":
        for r in p["rows"]:
            if r["label"].casefold() == str(v).casefold():
                return r["label"]
        raise EditError('Lookup entry "%s" does not exist.' % v)
    raise EditError("%s cannot be set." % p["name"])


def set_property(doc, handle, name, value) -> dict:
    d = doc.drawing
    ins = d.get(int(handle))
    if ins is None or ins.kind != "insert":
        raise EditError("Select a block reference.")
    if d.layer_locked(ins.layer):
        raise EditError("The object is on a locked layer.")
    src = _source(d, ins)
    rec = d.table_get("blocks", src)
    dyn = definition(rec)
    if dyn is None:
        raise EditError("This block reference has no dynamic properties.")
    p = _p(dyn, name)
    if p is None or p["type"] == "base":
        raise EditError('The property "%s" does not exist.' % name)
    vals = values_of(d, ins, dyn)
    vals[p["name"]] = check_value(p, value)
    if p["type"] == "lookup":
        row = next(r for r in p["rows"] if r["label"] == vals[p["name"]])
        for k, v in (row.get("values") or {}).items():
            q = _p(dyn, k)
            if q is not None:
                vals[q["name"]] = check_value(q, v)
    return _apply(doc, ins, src, dyn, vals)


def _apply(doc, ins, src, dyn, vals) -> dict:
    d = doc.drawing
    ent = d.modify(ins.handle)
    if _is_default(dyn, vals):
        ent.block = d.table_get("blocks", src)["name"]
        ent.extra = {k: v for k, v in ent.extra.items() if k != "dyn"}
    else:
        name = derived_block(d, src, vals)
        ent.block = name
        ent.extra = {**ent.extra, "dyn": {"base": d.table_get("blocks", src)["name"], "values": copy.deepcopy(vals)}}
    return {"handle": ins.handle, "block": ent.block, "values": vals}


def custom_grips(d, handle) -> list:
    ins = d.get(int(handle))
    if ins is None or ins.kind != "insert":
        raise EditError("Select a block reference.")
    src = _source(d, ins)
    rec = d.table_get("blocks", src)
    dyn = definition(rec)
    if dyn is None:
        return []
    vals = values_of(d, ins, dyn)
    m = insert_matrices(ins, d.table_get("blocks", ins.block) or rec)[0]
    out = []

    def world(p):
        return [m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5]]

    for p in dyn["parameters"]:
        t = p["type"]
        if t == "linear":
            ux, uy = _dir(p)
            v = float(vals[p["name"]])
            pt = [p["base"][0] + ux * v, p["base"][1] + uy * v]
            out.append({"id": p["name"], "kind": "distance", "param": p["name"], "p": world(pt), "value": v})
        elif t == "point":
            v = vals[p["name"]]
            out.append({"id": p["name"], "kind": "position", "param": p["name"], "p": world(v), "value": list(v)})
        elif t == "rotation":
            b = p.get("base") or [0.0, 0.0]
            r = float(p.get("radius", 10.0))
            a = math.radians(float(vals[p["name"]]))
            out.append({"id": p["name"], "kind": "rotation", "param": p["name"], "p": world([b[0] + r * math.cos(a), b[1] + r * math.sin(a)]), "value": vals[p["name"]]})
        elif t in ("flip", "visibility", "lookup"):
            b = p.get("base") or p.get("point") or [0.0, 0.0]
            out.append({"id": p["name"], "kind": "flip" if t == "flip" else "state", "param": p["name"], "p": world(b), "value": vals[p["name"]]})
    return out


def drag_grip(doc, handle, grip_id, point) -> dict:
    d = doc.drawing
    ins = d.get(int(handle))
    grips = custom_grips(d, handle)
    g = next((x for x in grips if x["id"].casefold() == str(grip_id).casefold()), None)
    if g is None:
        raise EditError('The dynamic grip "%s" does not exist.' % grip_id)
    src = _source(d, ins)
    dyn = definition(d.table_get("blocks", src))
    p = _p(dyn, g["param"])
    rec = d.table_get("blocks", ins.block)
    inv = BT.inverse(insert_matrices(ins, rec)[0])
    bx = inv[0] * point[0] + inv[2] * point[1] + inv[4]
    by = inv[1] * point[0] + inv[3] * point[1] + inv[5]
    if g["kind"] == "distance":
        ux, uy = _dir(p)
        v = (bx - p["base"][0]) * ux + (by - p["base"][1]) * uy
        v = snap_value(p, v)
        return set_property(doc, handle, p["name"], v)
    if g["kind"] == "position":
        return set_property(doc, handle, p["name"], [bx, by])
    if g["kind"] == "rotation":
        b = p.get("base") or [0.0, 0.0]
        v = math.degrees(math.atan2(by - b[1], bx - b[0])) % 360.0
        return set_property(doc, handle, p["name"], snap_value(p, v))
    vals = values_of(d, ins, dyn)
    if p["type"] == "flip":
        return set_property(doc, handle, p["name"], 0 if int(vals[p["name"]]) else 1)
    names = [s["name"] for s in p["states"]] if p["type"] == "visibility" else [r["label"] for r in p["rows"]]
    cur = [n.casefold() for n in names].index(str(vals[p["name"]]).casefold())
    return set_property(doc, handle, p["name"], names[(cur + 1) % len(names)])
