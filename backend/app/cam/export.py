import copy
import datetime

from app.cam import gen, model, post, store, toolpath as T
from app.cam.limits import CamError
from app.core import outputs

ALLOWED = (".nc", ".ngc", ".gcode", ".tap", ".txt", ".cnc", ".gc")


def items_for(doc, setup=None, ops=None) -> list:
    d = doc.drawing
    ids = []
    if ops:
        ids = [str(o) for o in ops]
    else:
        for s in model.setups(d):
            if setup and s["id"] != setup:
                continue
            ids.extend(o for o in s["ops"] if model.get_op(d, o).get("enabled", True))
    if not ids:
        raise CamError("There are no operations to post.")
    out = []
    for oid in ids:
        try:
            path = gen.toolpath_of(doc, oid, True)
        except CamError as err:
            raise CamError("%s: %s" % (oid, err))
        with doc.lock:
            op = copy.deepcopy(model.get_op(d, oid))
            setup_rec = copy.deepcopy(model.get_setup(d, op["setup"]))
            tool_row = copy.deepcopy(model.get_tool(d, op["tool"]))
        out.append({"setup": setup_rec, "op": op, "toolpath": path, "tool": store.tool_record(tool_row)})
    return out


def post_text(doc, post_id: str, setup=None, ops=None, options=None) -> dict:
    items = items_for(doc, setup, ops)
    opt = dict(options or {})
    opt.setdefault("program", doc.name if hasattr(doc, "name") else "FORMCAD")
    if opt.get("date") is True:
        opt["date"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elif opt.get("date") in (False, None):
        opt["date"] = ""
    res = post.generate(items, post_id, opt)
    res["ops"] = [i["op"]["id"] for i in items]
    return res


def write_file(doc, out: str, post_id: str, setup=None, ops=None, options=None) -> dict:
    res = post_text(doc, post_id, setup, ops, options)
    try:
        path = outputs.checked(out, ALLOWED, res["extension"])
    except outputs.OutputRefused as err:
        raise CamError(str(err))
    with open(path, "w", encoding="ascii", errors="replace", newline="\n") as fh:
        fh.write(res["text"])
    res["path"] = path
    res.pop("text")
    return res


def time_report(doc, setup=None, ops=None) -> dict:
    d = doc.drawing
    rows = []
    total = {"simple_s": 0.0, "trapezoid_s": 0.0, "cut_length": 0.0, "rapid_length": 0.0}
    ids = [str(o) for o in ops] if ops else []
    if not ids:
        for s in model.setups(d):
            if setup and s["id"] != setup:
                continue
            ids.extend(o for o in s["ops"] if model.get_op(d, o).get("enabled", True))
    for oid in ids:
        try:
            path = gen.toolpath_of(doc, oid, True)
        except CamError as err:
            rows.append({"op": oid, "label": "", "error": str(err)})
            continue
        with doc.lock:
            op = model.get_op(d, oid)
            machine = (model.get_setup(d, op["setup"]).get("machine_profile") or {})
        ct = T.cycle_time(path.moves, machine)
        ln = path.lengths()
        rows.append({"op": oid, "label": op["label"], "simple_s": round(ct["simple_s"], 2), "trapezoid_s": round(ct["trapezoid_s"], 2), "cut_length": round(ln["cut"], 2), "rapid_length": round(ln["rapid"], 2)})
        total["simple_s"] += ct["simple_s"]
        total["trapezoid_s"] += ct["trapezoid_s"]
        total["cut_length"] += ln["cut"]
        total["rapid_length"] += ln["rapid"]
    return {"ops": rows, "total": {k: round(v, 2) for k, v in total.items()}}
