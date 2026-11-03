import base64
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.gen import jobs as gen_jobs, run as gen_run
from app.routers.part import _doc, _read
from app.routers.topo import guarded
from app.sim import records
from app.sim import study as sim_study
from app.topo import jobs as tj, outcome as topo_outcome, study as topo_study
from app.topo.grid import TopoError

router = APIRouter(tags=["generative"])


class RunBody(BaseModel):
    options: Optional[dict[str, Any]] = None
    model_config = {"extra": "allow"}


def _job(doc_id: str, job_id: str):
    _doc(doc_id)
    job = guarded(lambda: tj.get(job_id))
    if job.doc_id != doc_id:
        raise HTTPException(404, "There is no job %s on this document." % job_id)
    return job


def _result(doc, sid: str):
    d = doc.drawing
    row = records.need(d, sid, "study")
    if row.get("type") != "generative":
        raise HTTPException(400, "Study %s is not a generative study." % sid)
    rid = row.get("result")
    if not rid:
        raise HTTPException(404, "Study %s has no outcomes yet." % sid)
    return row, records.need(d, rid, "result")


def _outcome(res: dict, oid: str) -> dict:
    for o in res["summary"].get("outcomes", []):
        if o["id"] == oid:
            return o
    raise HTTPException(404, "There is no outcome %s." % oid)


def limits_view() -> dict:
    return {"interactive": {k: v[0] for k, v in gen_run.CAPS.items()}, "restricted": {k: v[1] for k, v in gen_run.CAPS.items()}, "defaults": gen_run.DEFAULTS, "methods": [{"method": m, "label": gen_run.rules.LABELS[m]} for m in gen_run.rules.METHODS], "objectives": list(gen_run.OBJECTIVES)}


@router.get("/{doc_id}/gen/limits")
def limits(doc_id: str) -> dict:
    _doc(doc_id)
    return limits_view()


@router.get("/{doc_id}/gen/studies/{sid}/preview")
def preview(doc_id: str, sid: str) -> dict:
    doc = _doc(doc_id)

    def run():
        restrict = tj.restricted()
        with doc.lock:
            snap = gen_run.snapshot(doc, sid)
        opts = gen_run.options_of(snap["study"])
        topo_snap = dict(snap, study=dict(snap["study"], options={k: v for k, v in (snap["study"].get("options") or {}).items() if k != "generative"}))
        setup = topo_study.resolve(topo_snap, restrict)
        runs = len(opts["methods"]) * (len(opts["volume_fractions"]) if opts["objective"] == "min_compliance" else 1)
        return {"study": sid, "info": setup.info, "options": opts, "runs": runs, "limits": limits_view()}

    return guarded(run)


@router.post("/{doc_id}/gen/studies/{sid}/run")
def run_study(doc_id: str, sid: str, body: RunBody = RunBody()) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        row = records.need(doc.drawing, sid, "study")
    if row.get("type") != "generative":
        raise HTTPException(400, "Study %s is a %s study; this route runs a generative study." % (sid, row.get("type")))
    over = dict(body.options or {})
    over.update({k: v for k, v in (body.model_extra or {}).items()})
    return guarded(lambda: {"job": gen_jobs.start(doc, sid, tj.restricted(), over)})


@router.get("/{doc_id}/gen/jobs/{job_id}")
def job_view(doc_id: str, job_id: str) -> dict:
    return {"job": _job(doc_id, job_id).view()}


@router.post("/{doc_id}/gen/jobs/{job_id}/cancel")
def job_cancel(doc_id: str, job_id: str) -> dict:
    _job(doc_id, job_id)
    return {"job": tj.cancel(job_id)}


@router.get("/{doc_id}/gen/studies/{sid}/outcomes")
def outcomes(doc_id: str, sid: str, thumbnails: bool = True) -> dict:
    def run(doc):
        row, res = _result(doc, sid)
        s = res["summary"]
        items = []
        for o in s.get("outcomes", []):
            item = {k: v for k, v in o.items() if k not in ("passes",)}
            if not thumbnails:
                item.pop("thumbnail_png_base64", None)
            items.append(item)
        return {"study": sid, "result": res["id"], "objective": s["objective"], "required_safety_factor": s["required_safety_factor"], "stress_limit_mpa": s["stress_limit_mpa"], "baseline": s["baseline"], "grid": s["grid"], "material": s["material"], "outcomes": items, "notes": s.get("notes", []), "seconds": s.get("seconds"), "safety_factor_basis": s.get("safety_factor_basis")}

    return guarded(lambda: _read(doc_id, run))


@router.get("/{doc_id}/gen/studies/{sid}/outcomes/{oid}")
def outcome_view(doc_id: str, sid: str, oid: str) -> dict:
    def run(doc):
        _row, res = _result(doc, sid)
        return {"study": sid, "outcome": _outcome(res, oid)}

    return guarded(lambda: _read(doc_id, run))


@router.get("/{doc_id}/gen/studies/{sid}/outcomes/{oid}/voxels")
def outcome_voxels(doc_id: str, sid: str, oid: str) -> dict:
    def run(doc):
        _row, res = _result(doc, sid)
        _outcome(res, oid)
        grid, arrays, _meta = gen_run.unpack(sim_study.get_blob(doc.drawing, res["blob"]))
        dens = np.clip(np.round(arrays[oid + "_density"] * 255.0), 0, 255).astype(np.uint8)
        return {"grid": grid.dims(), "order": "x fastest, then y, then z", "density_u8": base64.b64encode(dens.tobytes()).decode("ascii"), "solid_u8": base64.b64encode(arrays[oid + "_solid"].astype(np.uint8).tobytes()).decode("ascii"), "class_u8": base64.b64encode(arrays["cls"].astype(np.uint8).tobytes()).decode("ascii"), "classes": {"0": "design", "1": "preserved", "2": "empty"}}

    return guarded(lambda: _read(doc_id, run))


@router.get("/{doc_id}/gen/studies/{sid}/outcomes/{oid}/display")
def outcome_display(doc_id: str, sid: str, oid: str, smooth: int = 8, sigma: float = 0.6, max_triangles: int = 60000) -> dict:
    def run(doc):
        _row, res = _result(doc, sid)
        o = _outcome(res, oid)
        grid, arrays, _meta = gen_run.unpack(sim_study.get_blob(doc.drawing, res["blob"]))
        sub = {"solid": arrays[oid + "_solid"], "vm": arrays[oid + "_vm"]}
        v, t, _lv = topo_outcome.extract(grid, sub, max(0, min(int(smooth), 100)), max(0.0, min(float(sigma), 2.0)))
        v, t = topo_outcome.decimate(v, t, max(100, min(int(max_triangles), 200000)))
        vals = topo_outcome.vertex_stress(grid, sub, v)
        return {"study": sid, "outcome": oid, "unit": "MPa", "label": "von Mises", "positions": np.round(v, 5).ravel().tolist(), "indices": t.astype(int).ravel().tolist(), "values": np.round(vals, 4).tolist(), "min": float(vals.min()), "max": float(vals.max()), "triangles": int(len(t)), "limit": res["summary"].get("stress_limit_mpa"), "summary": {k: o[k] for k in ("method", "label", "mass_kg", "safety_factor", "peak_stress_mpa", "manufacturable")}}

    return guarded(lambda: _read(doc_id, run))
