import copy

from app.cam import model
from app.cam.limits import CamError
from app.cutting import process as PR
from app.cutting.shapes import CutError

MAX_RECORDS = 200
MAX_STORED_POINTS = 400000


def _rows(d, kind):
    return model.rows(d, kind)


def processes(d) -> list:
    return _rows(d, "process")


def get_process(d, pid: str) -> dict:
    t = model.table(d)
    rec = t.get("process:%s" % pid) if t is not None else None
    if rec is None:
        raise CutError("There is no cutting process %s." % pid)
    return rec


def process_view(rec: dict) -> dict:
    out = {k: copy.deepcopy(v) for k, v in rec.items() if k in PR.BASE}
    out["kind"] = rec["kind_of"]
    out["name"] = rec.get("label") or str(rec.get("kind_of", "")).capitalize()
    return out


def add_process(d, raw: dict) -> dict:
    if len(processes(d)) >= MAX_RECORDS:
        raise CutError("A document holds at most %d cutting processes." % MAX_RECORDS)
    clean = PR.clean(raw)
    pid = model.next_id(d, "process", "P")
    rec = dict(clean)
    rec.update({"name": "process:%s" % pid, "label": clean["name"], "id": pid, "kind_of": clean["kind"], "kind": "process"})
    d.table_set(model.TABLE, rec)
    return rec


def update_process(d, pid: str, raw: dict) -> dict:
    cur = get_process(d, pid)
    base = process_view(cur)
    for k, v in (raw or {}).items():
        if k in ("id", "kind_of", "label") or (k == "kind" and v == "process"):
            continue
        base[k] = v
    clean = PR.clean(base)
    rec = dict(clean)
    rec.update({"name": cur["name"], "label": clean["name"], "id": pid, "kind_of": clean["kind"], "kind": "process"})
    d.table_set(model.TABLE, rec)
    bump_ops(d, process=pid)
    return rec


def delete_process(d, pid: str) -> None:
    get_process(d, pid)
    for op in model.ops(d):
        if op.get("type") == "cut_nest" and op["params"].get("process") == pid:
            raise CamError("Operation %s uses process %s." % (op["id"], pid))
    d.table_remove(model.TABLE, "process:%s" % pid)


def nests(d) -> list:
    return _rows(d, "nest")


def get_nest(d, nid: str) -> dict:
    t = model.table(d)
    rec = t.get("nest:%s" % nid) if t is not None else None
    if rec is None:
        raise CutError("There is no nest %s." % nid)
    return rec


def put_nest(d, nid, body: dict) -> dict:
    if nid is None:
        if len(nests(d)) >= MAX_RECORDS:
            raise CutError("A document holds at most %d nests." % MAX_RECORDS)
        nid = model.next_id(d, "nest", "N")
        stamp = 1
    else:
        stamp = int(get_nest(d, nid).get("stamp", 0)) + 1
    total = sum(len(l["pts"]) for p in body["parts"] for l in p["loops"])
    if total > MAX_STORED_POINTS:
        raise CutError("The nest holds %d profile points; at most %d are stored." % (total, MAX_STORED_POINTS))
    rec = {"name": "nest:%s" % nid, "id": nid, "kind": "nest", "stamp": stamp}
    rec.update(copy.deepcopy(body))
    d.table_set(model.TABLE, rec)
    bump_ops(d, nest=nid)
    return rec


def delete_nest(d, nid: str) -> None:
    get_nest(d, nid)
    for op in model.ops(d):
        if op.get("type") == "cut_nest" and op["params"].get("nest") == nid:
            raise CamError("Operation %s cuts nest %s." % (op["id"], nid))
    d.table_remove(model.TABLE, "nest:%s" % nid)


def bump_ops(d, nest=None, process=None) -> None:
    from app.cam import store

    for op in model.ops(d):
        if op.get("type") != "cut_nest":
            continue
        p = op["params"]
        if (nest is not None and p.get("nest") == nest) or (process is not None and p.get("process") == process):
            store.update_op(d, op["id"], {"params": {"stamp": int(p.get("stamp") or 0) + 1}})
