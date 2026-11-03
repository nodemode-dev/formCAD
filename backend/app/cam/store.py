import copy
import hashlib
import json
import math

from app.cam import limits, model, registry, tools
from app.cam.limits import CamError

MACHINES = ("mill3", "mill5", "lathe", "laser", "printer")
STOCK_KINDS = ("from_model", "box", "cylinder", "tube")
FEED_KEYS = ("rpm", "vc", "fz", "vf_cut", "vf_plunge", "vf_ramp", "material")
HEIGHT_KEYS = ("clearance", "retract", "feed", "top", "bottom")
GEOMETRY_KINDS = ("polygons", "rect", "entities", "stock", "section", "removal", "points", "model_holes", "ruled")
MAX_JSON = 200000


def _num(v, label, lo=-1e6, hi=1e6, none_ok=False):
    if v is None and none_ok:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) < lo or float(v) > hi:
        raise CamError("%s must be a number between %g and %g." % (label, lo, hi))
    return float(v)


def _vec(v, label, n=3):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise CamError("%s needs %d numbers." % (label, n))
    return [_num(x, label) for x in v]


def clean_wcs(w, old=None) -> dict:
    base = copy.deepcopy(old) if old else {"slot": 1, "origin_on": "stock_top_min", "origin": [0.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0], "x": [1.0, 0.0, 0.0], "rotary": {"a": 0.0, "b": 0.0, "c": 0.0}}
    w = w or {}
    base.update({k: v for k, v in w.items() if k in ("slot", "origin_on", "origin", "z", "x", "rotary")})
    slot = base["slot"]
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 9:
        raise CamError("The work coordinate slot is a whole number from 1 to 9.")
    if base["origin_on"] not in model.ORIGINS:
        raise CamError("Origin must be one of %s." % ", ".join(model.ORIGINS))
    base["origin"] = _vec(base["origin"], "WCS origin")
    base["z"] = _vec(base["z"], "WCS z axis")
    base["x"] = _vec(base["x"], "WCS x axis")
    if math.sqrt(sum(c * c for c in base["z"])) < 1e-9 or math.sqrt(sum(c * c for c in base["x"])) < 1e-9:
        raise CamError("WCS axes cannot be zero vectors.")
    rot = base.get("rotary") or {}
    base["rotary"] = {k: _num(rot.get(k, 0.0), "Rotary %s" % k, -3600, 3600) for k in ("a", "b", "c")}
    return base


def clean_stock(s, old=None) -> dict:
    base = copy.deepcopy(old) if old else {"kind": "from_model", "offsets": {}, "dims": [0, 0, 0], "material": ""}
    s = s or {}
    base.update({k: v for k, v in s.items() if k in ("kind", "offsets", "dims", "diameter", "inner", "length", "axis", "material", "position")})
    if base["kind"] not in STOCK_KINDS:
        raise CamError("Stock kind must be one of %s." % ", ".join(STOCK_KINDS))
    off = base.get("offsets") or {}
    base["offsets"] = {k: _num(off.get(k, 0.0), "Stock offset %s" % k, -1e4, 1e4) for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")}
    if base["kind"] == "box":
        base["dims"] = _vec(base.get("dims") or [0, 0, 0], "Stock size")
        if min(base["dims"]) <= 0:
            raise CamError("A box stock needs a size.")
    if base["kind"] in ("cylinder", "tube"):
        base["diameter"] = _num(base.get("diameter"), "Stock diameter", 0.01, 1e5)
        base["length"] = _num(base.get("length"), "Stock length", 0.01, 1e5)
        if base["kind"] == "tube":
            base["inner"] = _num(base.get("inner"), "Stock inner diameter", 0.0, 1e5)
            if base["inner"] >= base["diameter"]:
                raise CamError("The inner diameter must be smaller than the outer.")
    if base.get("position") is not None:
        base["position"] = _vec(base["position"], "Stock position")
    base["material"] = str(base.get("material") or "")[:80]
    return base


def clean_safe(s, old=None) -> dict:
    base = dict(old) if old else {"clearance": 20.0, "retract": 5.0, "feed": 2.0}
    base.update(s or {})
    out = {k: _num(base.get(k), "Safe height %s" % k, 0.0, 1e4) for k in ("clearance", "retract", "feed")}
    if not out["clearance"] >= out["retract"] >= out["feed"]:
        raise CamError("Clearance must be at least retract, which must be at least feed.")
    return out


def clean_handles(v, label):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 2000:
        raise CamError("%s is a list of body handles." % label)
    return [str(x) for x in v]


def add_setup(d, body: dict) -> dict:
    limits.need(len(model.setups(d)) + 1, "setups", "Setups")
    sid = model.next_id(d, "setup", "S")
    rec = {"name": "setup:%s" % sid, "id": sid, "kind": "setup", "label": str(body.get("label") or "Setup %s" % sid)[:80], "machine": body.get("machine", "mill3"), "wcs": clean_wcs(body.get("wcs")), "stock": clean_stock(body.get("stock")), "bodies": clean_handles(body.get("bodies"), "Bodies"), "fixtures": clean_handles(body.get("fixtures"), "Fixtures"), "ops": [], "safe": clean_safe(body.get("safe")), "machine_profile": copy.deepcopy(body.get("machine_profile") or {})}
    if rec["machine"] not in MACHINES:
        raise CamError("Machine must be one of %s." % ", ".join(MACHINES))
    d.table_set(model.TABLE, rec)
    return rec


def update_setup(d, sid: str, body: dict) -> dict:
    cur = model.get_setup(d, sid)
    rec = copy.deepcopy(cur)
    if "label" in body:
        rec["label"] = str(body["label"])[:80]
    if "machine" in body:
        if body["machine"] not in MACHINES:
            raise CamError("Machine must be one of %s." % ", ".join(MACHINES))
        rec["machine"] = body["machine"]
    if "wcs" in body:
        rec["wcs"] = clean_wcs(body["wcs"], cur["wcs"])
    if "stock" in body:
        rec["stock"] = clean_stock(body["stock"], cur["stock"])
    if "bodies" in body:
        rec["bodies"] = clean_handles(body["bodies"], "Bodies")
    if "fixtures" in body:
        rec["fixtures"] = clean_handles(body["fixtures"], "Fixtures")
    if "safe" in body:
        rec["safe"] = clean_safe(body["safe"], cur["safe"])
    if "machine_profile" in body:
        rec["machine_profile"] = copy.deepcopy(body["machine_profile"] or {})
    d.table_set(model.TABLE, rec)
    mark_setup_ops(d, sid)
    return rec


def delete_setup(d, sid: str) -> list:
    cur = model.get_setup(d, sid)
    gone = []
    for oid in cur["ops"]:
        d.table_remove(model.TABLE, "op:%s" % oid)
        gone.append(oid)
    d.table_remove(model.TABLE, cur["name"])
    return gone


def import_tool(d, source: dict) -> dict:
    if source.get("library_id"):
        rec = tools.find(str(source["library_id"]))
    else:
        rec = tools.clean(source.get("tool") or {}, keep_id=False)
    if source.get("number") is not None:
        rec = dict(rec)
        rec["number"] = int(source["number"])
        rec = tools.clean(rec)
    row = _tool_row(rec)
    d.table_set(model.TABLE, row)
    mark_all_ops(d)
    return row


def _tool_row(rec: dict) -> dict:
    row = copy.deepcopy(rec)
    row["library_id"] = row.pop("id", "")
    row["tool_kind"] = row.pop("kind")
    row["name_label"] = row.pop("name")
    row["name"] = "tool:T%d" % rec["number"]
    row["id"] = "T%d" % rec["number"]
    row["kind"] = "tool"
    return row


def tool_record(row: dict) -> dict:
    rec = copy.deepcopy(row)
    rec["kind"] = rec.pop("tool_kind")
    rec["name"] = rec.pop("name_label")
    rec["id"] = rec.pop("library_id", "")
    return rec


def delete_tool(d, number) -> None:
    n = int(number)
    for op in model.ops(d):
        if op.get("tool") == n:
            raise CamError("Operation %s uses tool T%d." % (op["id"], n))
    model.get_tool(d, n)
    d.table_remove(model.TABLE, "tool:T%d" % n)


def clean_feeds(v) -> dict:
    v = v or {}
    out = {}
    for k in v:
        if k not in FEED_KEYS:
            raise CamError("Feeds has no field %s." % k)
    for k in FEED_KEYS:
        if k == "material":
            out[k] = str(v.get(k) or "")[:80]
        else:
            out[k] = _num(v.get(k), "Feed %s" % k, 0.0, 1e6, True)
    return out


def clean_heights(v) -> dict:
    v = v or {}
    for k in v:
        if k not in HEIGHT_KEYS:
            raise CamError("Heights has no field %s." % k)
    return {k: _num(v.get(k), "Height %s" % k, -1e5, 1e5, True) for k in HEIGHT_KEYS}


def clean_geometry(v) -> dict:
    if not v:
        return {}
    if not isinstance(v, dict) or v.get("kind") not in GEOMETRY_KINDS:
        raise CamError("Geometry kind must be one of %s." % ", ".join(GEOMETRY_KINDS))
    if len(json.dumps(v)) > MAX_JSON * (5 if not limits.limited() else 1):
        raise CamError("The geometry is too large.")
    return copy.deepcopy(v)


def new_state(status="never", message="") -> dict:
    return {"status": status, "sig": "", "message": message, "warnings": [], "summary": {}}


def add_op(d, body: dict) -> dict:
    limits.need(len(model.ops(d)) + 1, "ops", "Operations")
    typ = registry.get(str(body.get("type") or ""))
    setup = model.get_setup(d, str(body.get("setup") or ""))
    tool_no = body.get("tool")
    if tool_no is None:
        raise CamError("Give a tool number.")
    tool_row = model.get_tool(d, tool_no)
    if typ.tool_kinds and tool_row["tool_kind"] not in typ.tool_kinds:
        raise CamError("%s needs one of these tools: %s." % (typ.label, ", ".join(typ.tool_kinds)))
    oid = model.next_id(d, "op", "O")
    rec = {"name": "op:%s" % oid, "id": oid, "kind": "op", "type": typ.kind, "label": str(body.get("label") or "%s %s" % (typ.label, oid))[:80], "setup": setup["id"], "tool": int(tool_no), "enabled": bool(body.get("enabled", True)), "geometry": clean_geometry(body.get("geometry")), "params": typ.clean(body.get("params")), "feeds": clean_feeds(body.get("feeds")), "heights": clean_heights(body.get("heights")), "state": new_state()}
    d.table_set(model.TABLE, rec)
    s = copy.deepcopy(setup)
    s["ops"] = list(s["ops"]) + [oid]
    d.table_set(model.TABLE, s)
    return rec


def update_op(d, oid: str, body: dict) -> dict:
    cur = model.get_op(d, oid)
    rec = copy.deepcopy(cur)
    typ = registry.get(rec["type"])
    if "label" in body:
        rec["label"] = str(body["label"])[:80]
    if "enabled" in body:
        rec["enabled"] = bool(body["enabled"])
    if "tool" in body:
        row = model.get_tool(d, body["tool"])
        if typ.tool_kinds and row["tool_kind"] not in typ.tool_kinds:
            raise CamError("%s needs one of these tools: %s." % (typ.label, ", ".join(typ.tool_kinds)))
        rec["tool"] = int(body["tool"])
    if "geometry" in body:
        rec["geometry"] = clean_geometry(body["geometry"])
    if "params" in body:
        merged = dict(rec["params"])
        merged.update(body["params"] or {})
        rec["params"] = typ.clean(merged)
    if "feeds" in body:
        merged = dict(rec["feeds"])
        merged.update(body["feeds"] or {})
        rec["feeds"] = clean_feeds(merged)
    if "heights" in body:
        merged = dict(rec["heights"])
        merged.update(body["heights"] or {})
        rec["heights"] = clean_heights(merged)
    changed = any(k in body for k in ("tool", "geometry", "params", "feeds", "heights"))
    if changed:
        st = dict(rec["state"])
        if st["status"] in ("ok", "empty", "failed"):
            st["status"] = "stale"
        rec["state"] = st
    d.table_set(model.TABLE, rec)
    return rec


def delete_op(d, oid: str) -> None:
    cur = model.get_op(d, oid)
    s = copy.deepcopy(model.get_setup(d, cur["setup"]))
    s["ops"] = [x for x in s["ops"] if x != oid]
    d.table_set(model.TABLE, s)
    d.table_remove(model.TABLE, cur["name"])


def move_op(d, oid: str, index: int) -> dict:
    cur = model.get_op(d, oid)
    s = copy.deepcopy(model.get_setup(d, cur["setup"]))
    order = [x for x in s["ops"] if x != oid]
    index = max(0, min(int(index), len(order)))
    order.insert(index, oid)
    s["ops"] = order
    d.table_set(model.TABLE, s)
    return s


def mark_setup_ops(d, sid: str) -> None:
    for op in model.ops(d):
        if op["setup"] == sid:
            _stale(d, op)


def mark_all_ops(d) -> None:
    for op in model.ops(d):
        _stale(d, op)


def _stale(d, op):
    st = op.get("state") or {}
    if st.get("status") in ("ok", "empty", "failed"):
        rec = copy.deepcopy(op)
        rec["state"]["status"] = "stale"
        d.table_set(model.TABLE, rec)


def signature_of(doc, setup: dict, op: dict, tool_row: dict) -> str:
    h = hashlib.sha256()
    s = {k: v for k, v in setup.items() if k not in ("ops", "label")}
    o = {k: v for k, v in op.items() if k not in ("state", "label", "enabled")}
    h.update(json.dumps([model.source_signature(doc), s, o, tool_row], sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:20]


def view(doc) -> dict:
    d = doc.drawing
    return {"setups": model.setups(d), "ops": model.ops(d), "tools": model.tool_rows(d), "limits": limits.get()}
