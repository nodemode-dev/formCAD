import copy
import io
import json
import math
import os
import tempfile
import time

import numpy as np

from app.cmd import barred
from app.sim import fem, meshio, records, registry
from app.sim.fem import SimError
from app.sim.registry import Cancelled
from app.solid import blobs, work

LIMITS = {
    "dofs": (120000, 30000),
    "elements": (400000, 60000),
    "seconds": (900, 180),
}
SIM_PREFIX = "sim/"
DEFAULT_ELEMENT_BUDGET = 30000
TET_FACTOR = 0.1178


def restricted(runner=None) -> bool:
    return bool(barred.caller(runner))


def limits_for(restrict: bool) -> dict:
    return {k: (v[1] if restrict else v[0]) for k, v in LIMITS.items()}


def limits_view() -> dict:
    return {"interactive": {k: v[0] for k, v in LIMITS.items()}, "restricted": {k: v[1] for k, v in LIMITS.items()}}


def sim_path(blob: str) -> str:
    return "%s%s.npz" % (SIM_PREFIX, blob)


def put_blob(drawing, data: bytes) -> str:
    if len(data) > blobs.MAX_BLOB:
        raise SimError("The result is larger than the 256 MB limit.")
    key = blobs.digest(data)
    drawing.blobs.setdefault(sim_path(key), data)
    return key


def get_blob(drawing, key: str) -> bytes:
    data = drawing.blobs.get(sim_path(key))
    if data is None:
        raise SimError("The stored simulation data %s is missing from the file." % key)
    return data


def snapshot(doc, study_id: str) -> dict:
    d = doc.drawing
    study = records.need(d, study_id, "study")
    body = d.ents.get(study["geometry"]["body"])
    if body is None or body.kind != "solidbody":
        raise SimError("The solid body %s of study %s no longer exists." % (study["geometry"]["body"], study_id))
    snap = {
        "study": study,
        "loads": [records.need(d, i, "load") for i in study.get("loads") or []],
        "fixtures": [records.need(d, i, "fixture") for i in study.get("fixtures") or []],
        "contacts": [records.need(d, i, "contact") for i in study.get("contacts") or []],
        "controls": [records.need(d, i, "mesh_control") for i in (study["mesh"].get("controls") or [])],
        "material": records.get(d, study["material"], "material") if study.get("material") else None,
        "body": body,
        "mesh_blob": study.get("mesh_blob"),
    }
    return snap


def export_brep(doc, body, folder: str) -> str:
    wid = work.worker_id(doc.drawing, body)
    path = os.path.join(folder, "study.brep")
    work.kcall("shape_save", {"id": wid, "path": path}, work.LONG)
    return path


def material_si(row: dict | None, needs=()) -> dict:
    if row is None:
        raise SimError("Choose a material for the study.")
    out = {k: row.get(k) for k in records.MATERIAL_FIELDS}
    out["name"] = row.get("label") or row.get("id")
    return out


def default_maxh(faces: dict) -> tuple:
    rows = faces["faces"]
    lo = [min(r["bbox"][0][k] for r in rows) for k in range(3)]
    hi = [max(r["bbox"][1][k] for r in rows) for k in range(3)]
    dims = sorted(max(hi[k] - lo[k], 0.0) for k in range(3))
    diag = math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3)))
    h = min(diag / 20.0, max(dims[0], 1e-6) / 2.0)
    volume = max(faces["volume"], 1e-12)
    guess = volume / (TET_FACTOR * h ** 3)
    if guess > DEFAULT_ELEMENT_BUDGET:
        h = (volume / (TET_FACTOR * DEFAULT_ELEMENT_BUDGET)) ** (1.0 / 3.0)
    return h, diag


def groups_of(snap: dict) -> dict:
    out = {}
    for ld in snap["loads"]:
        if ld.get("select"):
            out["load:" + ld["id"]] = ld["select"]
    for fx in snap["fixtures"]:
        out["fix:" + fx["id"]] = fx["select"]
    for c in snap["contacts"]:
        out["contact:%s:a" % c["id"]] = c["a"]
        out["contact:%s:b" % c["id"]] = c["b"]
    return out


def mesh_step(doc, snap: dict, ctl, restrict: bool) -> dict:
    from app.services import mesher

    lim = limits_for(restrict)
    with tempfile.TemporaryDirectory(prefix="fcsim_") as tmp:
        ctl.step("Exporting the shape", 0.02)
        brep = export_brep(doc, snap["body"], tmp)
        ctl.step("Reading faces", 0.06)
        faces = mesher.call("faces", {"path": brep}, 60.0)
        if faces["solids"] != 1:
            raise SimError("A study needs one solid body; this shape holds %d solids." % faces["solids"])
        mesh_cfg = snap["study"]["mesh"]
        h = mesh_cfg.get("maxh_mm")
        defaulted = h is None
        if defaulted:
            h, _diag = default_maxh(faces)
        refine = [{"select": c["select"], "maxh": c["maxh_mm"]} for c in snap["controls"]]
        ctl.step("Meshing", 0.1)
        out = os.path.join(tmp, "mesh.npz")
        info = mesher.call("mesh", {"path": brep, "out": out, "maxh": h, "refine": refine, "groups": groups_of(snap), "max_elements": lim["elements"], "second_order": True}, 300.0)
        for name, ids in info["groups"].items():
            if not ids:
                raise SimError("The selection of %s matches no face of the part." % name.replace("load:", "load ").replace("fix:", "fixture "))
        with open(out, "rb") as fh:
            data = fh.read()
    ctl.step("Mesh ready", 0.25)
    return {"data": data, "info": info, "maxh_mm": h, "defaulted": defaulted}


def build_model(data: bytes):
    return meshio.build(io.BytesIO(data))


def result_bytes(model, outcome, extra: dict) -> bytes:
    buf = io.BytesIO()
    arrays = {"nodes": model.nodes_mm, "tris": model.tris, "tri_face": model.tri_face}
    for k, v in outcome.fields.items():
        arrays["f_" + k] = np.asarray(v)
    meta = {"fields": outcome.meta.get("fields", []), "modes": outcome.meta.get("modes", []), "basis": outcome.meta.get("basis"), "summary": outcome.summary, "extra": extra}
    arrays["meta"] = np.array(json.dumps(meta, default=float))
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def solve_step(snap: dict, mesh_data: bytes, ctl, restrict: bool):
    registry.load()
    solver = registry.get(snap["study"]["type"])
    lim = limits_for(restrict)
    if "material" in solver.needs:
        mat = material_si(snap["material"])
    else:
        mat = material_si(snap["material"]) if snap["material"] else {}
    if "loads" in solver.needs and not snap["loads"]:
        raise SimError("The %s study needs at least one load." % solver.label.lower())
    if "fixtures" in solver.needs and not snap["fixtures"]:
        raise SimError("The %s study needs at least one fixture." % solver.label.lower())
    model = build_model(mesh_data)
    ctl.step("Solving", 0.3)
    ctx = registry.Context(snap["study"], mat, snap["loads"], snap["fixtures"], snap["contacts"], model, lim, progress=lambda f, p: ctl.step(p or "Solving", 0.3 + 0.65 * f), stop=ctl.stop, deadline=ctl.deadline)
    started = time.time()
    outcome = solver.run(ctx)
    outcome.summary.setdefault("seconds", round(time.time() - started, 3))
    return model, outcome


class Inline:
    def __init__(self, restrict: bool = False):
        import threading

        self.stop = threading.Event()
        self.deadline = time.time() + limits_for(restrict)["seconds"]

    def step(self, phase: str, fraction=None) -> None:
        if time.time() > self.deadline:
            raise Cancelled("The study ran past its time budget and was stopped.")


def compute(doc, study_id: str, mode: str, ctl, restrict: bool) -> dict:
    with doc.lock:
        snap = snapshot(doc, study_id)
    ms = mesh_step(doc, snap, ctl, restrict)
    info = ms["info"]
    mesh = {"nodes": info["nodes"], "tets": info["tets"], "curved": info["curved"], "maxh_mm": ms["maxh_mm"], "defaulted_size": ms["defaulted"], "volume_mm3": info["volume"], "body_blob": snap["body"].blob, "body_offset": [float(v) for v in snap["body"].offset]}
    parts = {"study": study_id, "mode": mode, "mesh": mesh, "mesh_data": ms["data"], "type": snap["study"]["type"]}
    if mode == "mesh":
        return parts
    model, outcome = solve_step(snap, ms["data"], ctl, restrict)
    ctl.step("Storing the result", 0.97)
    parts["payload"] = result_bytes(model, outcome, {"mesh": mesh})
    parts["summary"] = json.loads(json.dumps(outcome.summary, default=float))
    parts["fields"] = outcome.meta.get("fields", [])
    parts["modes"] = outcome.meta.get("modes", [])
    return parts


def store(d, parts: dict) -> dict:
    study_id = parts["study"]
    mkey = put_blob(d, parts["mesh_data"])
    row = records.get(d, study_id)
    if row is None:
        raise SimError("Study %s was removed while it ran." % study_id)
    row["mesh_blob"] = mkey
    row["mesh_info"] = parts["mesh"]
    if parts["mode"] == "mesh":
        if row.get("status") in ("new", None):
            row["status"] = "meshed"
        d.table_set(records.TABLE, row)
        return {"study": study_id, "mesh_blob": mkey, "summary": {"mesh": parts["mesh"]}}
    rkey = put_blob(d, parts["payload"])
    for old in records.of_kind(d, "result"):
        if old.get("study") == study_id:
            d.table_remove(records.TABLE, old["id"])
    res = records.put_result(d, {"study": study_id, "type": parts["type"], "blob": rkey, "mesh_blob": mkey, "summary": parts["summary"], "fields": parts["fields"], "modes": parts["modes"], "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())})
    row["result"] = res["id"]
    row["status"] = "solved"
    d.table_set(records.TABLE, row)
    return {"study": study_id, "result": res["id"], "summary": res["summary"]}


def execute(doc, study_id: str, mode: str, ctl, restrict: bool) -> dict:
    parts = compute(doc, study_id, mode, ctl, restrict)
    with doc.lock:
        with doc.transaction("SIMRUN" if mode == "run" else "SIMMESH"):
            return store(doc.drawing, parts)


def load_result(drawing, result_id: str) -> tuple:
    row = records.get(drawing, result_id, "result")
    if row is None:
        raise SimError("There is no result %s." % result_id)
    with np.load(io.BytesIO(get_blob(drawing, row["blob"])), allow_pickle=False) as z:
        data = {k: z[k] for k in z.files}
    meta = json.loads(str(data.pop("meta")))
    return row, data, meta
