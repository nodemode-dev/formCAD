import copy

from app.cam import model
from app.cam.limits import CamError

MODES = ("turn", "mill")
TURN_OPS = ("turn_face", "turn_rough", "turn_finish", "turn_groove", "turn_thread", "turn_partoff")
LIVE_OPS = ("live_drill_axial", "live_drill_radial")
TURN_TOOLS = ("insert", "groove", "thread")
MAX_MODE_LINES = 20

BLANK = {"name": "Mill-turn", "kind_of": "mill_turn", "c_axis": True, "live_tools": True, "y_axis": False, "mode_lines": {"turn": [], "mill": []}, "post": "millturn_linuxcnc"}


def machines(d) -> list:
    return model.rows(d, "machine")


def get_machine(d, mid: str) -> dict:
    t = model.table(d)
    rec = t.get("machine:%s" % mid) if t is not None else None
    if rec is None:
        raise CamError("There is no machine %s." % mid)
    return rec


def clean(raw: dict, old=None) -> dict:
    base = copy.deepcopy(BLANK)
    if old:
        base.update({k: copy.deepcopy(v) for k, v in old.items() if k in BLANK})
        base["name"] = old.get("label") or base["name"]
    for k, v in (raw or {}).items():
        if k not in BLANK:
            raise CamError("A machine has no field called %s." % k)
        base[k] = v
    base["name"] = str(base["name"] or "Mill-turn")[:80]
    for k in ("c_axis", "live_tools", "y_axis"):
        base[k] = bool(base[k])
    ml = base["mode_lines"]
    if not isinstance(ml, dict):
        raise CamError("Mode lines are an object with turn and mill lists.")
    out = {}
    for mode in MODES:
        lines = ml.get(mode) or []
        if not isinstance(lines, list) or len(lines) > MAX_MODE_LINES:
            raise CamError("Mode lines for %s are a list of at most %d lines." % (mode, MAX_MODE_LINES))
        for line in lines:
            if not isinstance(line, str) or len(line) > 120 or "\n" in line or "\r" in line:
                raise CamError("A mode line is a short single line of text.")
        out[mode] = list(lines)
    base["mode_lines"] = out
    base["post"] = str(base.get("post") or "millturn_linuxcnc")[:40]
    base["kind_of"] = "mill_turn"
    return base


def put_machine(d, mid, raw: dict) -> dict:
    if mid is None:
        mid = model.next_id(d, "machine", "M")
        old = None
    else:
        old = get_machine(d, mid)
    rec = clean(raw, old)
    row = dict(rec)
    row.update({"name": "machine:%s" % mid, "id": mid, "kind": "machine", "label": rec["name"]})
    d.table_set(model.TABLE, row)
    return row


def assignment(setup) -> dict:
    mp = setup.get("machine_profile") or {}
    return {"machine": mp.get("machine"), "mode": mp.get("mode")}


def check(d, mid: str) -> dict:
    mach = get_machine(d, mid)
    issues = []
    rows = []
    for s in model.setups(d):
        a = assignment(s)
        if a["machine"] != mid:
            continue
        mode = a["mode"]
        if mode not in MODES:
            issues.append({"setup": s["id"], "level": "error", "text": "Setup %s has no mode; set machine_profile mode to turn or mill." % s["id"]})
            continue
        if s["machine"] not in ("lathe", "mill3"):
            issues.append({"setup": s["id"], "level": "error", "text": "Setup %s is a %s setup; a mill-turn machine runs lathe or 3-axis setups." % (s["id"], s["machine"])})
        rows.append({"setup": s["id"], "mode": mode, "ops": list(s["ops"])})
        for oid in s["ops"]:
            op = model.get_op(d, oid)
            tool = model.get_tool(d, op["tool"])
            kind = op["type"]
            if kind in TURN_OPS and mode != "turn":
                issues.append({"setup": s["id"], "op": oid, "level": "error", "text": "%s is a turning operation in a milling mode setup." % oid})
            if kind in TURN_OPS and tool["tool_kind"] not in TURN_TOOLS:
                issues.append({"setup": s["id"], "op": oid, "level": "error", "text": "%s needs an insert, groove or thread tool." % oid})
            if kind in LIVE_OPS:
                if mode != "mill":
                    issues.append({"setup": s["id"], "op": oid, "level": "error", "text": "%s is a live tool operation in a turning mode setup." % oid})
                if not mach["live_tools"]:
                    issues.append({"setup": s["id"], "op": oid, "level": "error", "text": "The machine has no live tools."})
                if not mach["c_axis"]:
                    issues.append({"setup": s["id"], "op": oid, "level": "error", "text": "The machine has no C axis to index the part."})
                if tool["tool_kind"] != "drill":
                    issues.append({"setup": s["id"], "op": oid, "level": "error", "text": "%s needs a drill." % oid})
            elif kind not in TURN_OPS and not kind.startswith("probe_") and mode == "mill" and not mach["y_axis"]:
                issues.append({"setup": s["id"], "op": oid, "level": "warning", "text": "%s is a milling operation; without a Y axis this machine only supports live drilling." % oid})
    if not rows:
        issues.append({"level": "error", "text": "No setup is assigned to machine %s." % mid})
    return {"machine": mid, "issues": issues, "setups": rows, "ok": not any(i["level"] == "error" for i in issues)}


def mode_item(setup_prev, setup_next, mach):
    mode = assignment(setup_next)["mode"]
    lines = mach["mode_lines"].get(mode) or []
    moves = [["comment", "Mode change to %s" % ("turning" if mode == "turn" else "milling")], ["stop", "optional"]]
    moves.extend(["raw", ln] for ln in lines)
    return moves
