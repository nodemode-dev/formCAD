import hashlib
import json
import threading
import time
from collections import OrderedDict

import numpy as np

from app.additive import arrange, bodies, checks, jobs, orient, pack, placement, plate3mf, slicer, store
from app.additive.jobs import AdditiveError
from app.core import outputs

RESULTS: OrderedDict = OrderedDict()
PREVIEWS: OrderedDict = OrderedDict()
_lock = threading.Lock()
KEEP = 6
KEEP_PREVIEWS = 8


def profile_of(h: dict, plate: dict) -> dict:
    return store.need(h, "profiles", plate["profile"])


def fingerprint(doc, plate: dict, prof: dict) -> str:
    d = doc.drawing
    sig = []
    for it in plate["items"]:
        e = d.get(int(it["body"]))
        sig.append(None if e is None else [e.handle, int(e.version), list(e.offset or [])])
    h = hashlib.sha1()
    h.update(json.dumps([prof["settings"], plate["items"], sig, plate["bed"]], sort_keys=True).encode())
    return h.hexdigest()[:16]


def describe_plate(doc, h: dict, plate: dict) -> dict:
    d = doc.drawing
    out = json.loads(json.dumps(plate))
    prof = store.find(h, "profiles", plate["profile"])
    last = plate.get("last")
    out["stale"] = bool(last) and (prof is None or last.get("hash") != fingerprint(doc, plate, prof))
    for it in out["items"]:
        e = d.get(int(it["body"]))
        it["state"] = "ok" if e is not None and e.kind in bodies.KINDS else "missing"
        it["name"] = e.name if e is not None and e.kind in bodies.KINDS else ""
    return out


def listing(doc) -> dict:
    h = store.header(doc.drawing)
    return {"profiles": h["profiles"], "plates": [describe_plate(doc, h, p) for p in h["plates"]], "limits": jobs.limits_view(), "bodies": bodies.listing(doc), "activity": jobs.running(doc.id)}


def plate_parts(doc, plate: dict, runner=None) -> tuple:
    d = doc.drawing
    items = [it for it in plate["items"] if d.get(int(it["body"])) is not None and d.get(int(it["body"])).kind in bodies.KINDS]
    if not items:
        raise AdditiveError("The plate holds no bodies that still exist.")
    if len(items) > jobs.cap("items", runner):
        raise AdditiveError("A plate holds at most %d items here." % jobs.cap("items", runner))
    handles = [it["body"] for it in items]
    parts = bodies.fetch(doc, handles, jobs.cap("triangles", runner))
    return parts, items


def default_items(doc, handles) -> list:
    rows = bodies.listing(doc)
    pick = [r for r in rows if handles is None or r["handle"] in [int(x) for x in handles]]
    if handles is not None:
        missing = [int(x) for x in handles if int(x) not in [r["handle"] for r in rows]]
        if missing:
            raise AdditiveError("There is no visible solid or mesh body with the handle %s." % missing[0])
    if not pick:
        raise AdditiveError("The document has no visible solid or mesh bodies to print.")
    return [{"body": r["handle"], "orient": None, "rot_z": 0.0, "x": 0.0, "y": 0.0, "lift": 0.0} for r in pick]


def arrange_items(doc, items: list, bed, spacing: float, rotations=None, act=jobs.QUIET, runner=None) -> tuple:
    if len(items) > jobs.cap("items", runner):
        raise AdditiveError("A plate holds at most %d items here." % jobs.cap("items", runner))
    if rotations is not None and len(rotations) > 24:
        raise AdditiveError("At most 24 rotations are tried.")
    parts = bodies.fetch(doc, [it["body"] for it in items], jobs.cap("triangles", runner))
    return arrange.arrange(parts, items, bed, spacing, rotations, act)


def do_slice(doc, tid: str, runner=None):
    with doc.lock:
        h = store.header(doc.drawing)
        plate = store.need(h, "plates", tid)
        prof = profile_of(h, plate)
        plate = json.loads(json.dumps(plate))
        prof = json.loads(json.dumps(prof))
        key = fingerprint(doc, plate, prof)
    settings = dict(prof["settings"])
    settings["bed"] = plate["bed"]
    with jobs.activity(doc.id, "slice", runner) as act:
        parts, items = plate_parts(doc, plate, runner)
        res = slicer.slice_job(parts, items, settings, act, plate["id"], prof["id"], runner, key)
    with _lock:
        RESULTS[(doc.id, plate["id"])] = res
        RESULTS.move_to_end((doc.id, plate["id"]))
        while len(RESULTS) > KEEP:
            RESULTS.popitem(last=False)
    last = {"hash": key, "layers": res.summary["layers"], "filament_mm": res.summary["filament_mm"], "time_s": res.summary["time_s"], "support_volume_mm3": res.summary["support_volume_mm3"], "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}
    return res, last


def result_for(doc_id: str, tid: str):
    with _lock:
        return RESULTS.get((doc_id, str(tid).upper()))


def need_result(doc, tid: str):
    res = result_for(doc.id, tid)
    if res is None:
        raise AdditiveError("This plate has not been sliced in this session; slice it first.")
    return res


def export_gcode(res, path: str) -> dict:
    full = outputs.checked(path, (".gcode", ".gco"), ".gcode")
    text = "\n".join(res.lines) + "\n"
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return {"path": full, "bytes": len(text.encode("utf-8")), "summary": res.summary}


def export_3mf(doc, plate: dict, path: str) -> dict:
    full = outputs.checked(path, (".3mf",), ".3mf")
    parts, items = plate_parts(doc, plate)
    data = plate3mf.write_plate(parts, items, plate["bed"], plate["name"], plate["id"])
    with open(full, "wb") as fh:
        fh.write(data)
    return {"path": full, "bytes": len(data), "items": len(items)}


def do_orient(doc, handles, preset: str, angle: float, top: int, layer_h: float, runner=None) -> dict:
    if len(handles) > jobs.cap("items", runner):
        raise AdditiveError("At most %d bodies are scored together here." % jobs.cap("items", runner))
    parts = bodies.fetch(doc, handles, jobs.cap("orient_triangles", runner))
    v = np.vstack([p.v for p in parts])
    off, ts = 0, []
    for p in parts:
        ts.append(p.t + off)
        off += len(p.v)
    t = np.vstack(ts)
    with jobs.activity(doc.id, "orient", runner) as act:
        return orient.study(v, t, preset, angle, top, layer_h, act)


def orient_item(plate: dict, handles, rotation) -> dict:
    placement.rotation_of(rotation)
    want = {int(x) for x in handles}
    hit = False
    for it in plate["items"]:
        if int(it["body"]) in want:
            it["orient"] = [float(x) for x in rotation]
            it["rot_z"] = 0.0
            hit = True
    if not hit:
        raise AdditiveError("The plate holds none of those bodies.")
    return plate


def do_checks(doc, plate: dict, prof: dict, min_wall=None) -> list:
    parts, items = plate_parts(doc, plate)
    s = dict(prof["settings"])
    return checks.run(parts, items, s, plate["bed"], bool(plate.get("metal")), min_wall)


def import_gcode(path: str, runner=None) -> dict:
    import os

    real = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    ext = os.path.splitext(real)[1].lower()
    if ext not in (".gcode", ".gco", ".g", ".txt", ".nc") or not os.path.isfile(real):
        raise AdditiveError("Give the path of an existing .gcode file.")
    limit = jobs.cap("gcode_bytes", runner)
    if os.path.getsize(real) > limit:
        raise AdditiveError("The G-code file is larger than %d MB." % (limit >> 20))
    with open(real, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    try:
        data = pack.parse_gcode(text)
    except pack.PackError as err:
        raise AdditiveError(str(err))
    key = hashlib.sha1(data).hexdigest()[:16]
    with _lock:
        PREVIEWS[key] = data
        PREVIEWS.move_to_end(key)
        while len(PREVIEWS) > KEEP_PREVIEWS:
            PREVIEWS.popitem(last=False)
    return {"key": key, "header": pack.header_of(data)}


def preview(key: str):
    with _lock:
        return PREVIEWS.get(key)
