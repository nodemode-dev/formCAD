import base64
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routers.part import _doc, _read
from app.sim import records
from app.sim import study as sim_study
from app.sim.fem import SimError
from app.sim.records import SimRecordError
from app.topo import jobs, outcome, study as topo_study
from app.topo.grid import TopoError

router = APIRouter(tags=["topo"])


class RunBody(BaseModel):
    options: Optional[dict[str, Any]] = None
    model_config = {"extra": "allow"}


def guarded(fn):
    try:
        return fn()
    except (TopoError, SimError, SimRecordError) as err:
        raise HTTPException(400, str(err))
    except KeyError as err:
        raise HTTPException(400, str(err.args[0]) if err.args else "Not found.")


def limits_view() -> dict:
    return {"interactive": {k: v[0] for k, v in topo_study.CAPS.items()}, "restricted": {k: v[1] for k, v in topo_study.CAPS.items()}, "defaults": {"cells": topo_study.DEFAULT_CELLS}}


def _job(doc_id: str, job_id: str):
    _doc(doc_id)
    job = guarded(lambda: jobs.get(job_id))
    if job.doc_id != doc_id:
        raise HTTPException(404, "There is no job %s on this document." % job_id)
    return job


def _start(doc_id: str, sid: str, kind: str, body: RunBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        row = records.need(doc.drawing, sid, "study")
    want = "topology" if kind == "topology" else "shape"
    if row.get("type") != want:
        raise HTTPException(400, "Study %s is a %s study; this route runs a %s study." % (sid, row.get("type"), want))
    over = dict(body.options or {})
    over.update({k: v for k, v in (body.model_extra or {}).items()})
    return guarded(lambda: {"job": jobs.start(doc, sid, kind, jobs.restricted(), over)})


def _result(doc, sid: str):
    d = doc.drawing
    row = records.need(d, sid, "study")
    if row.get("type") not in ("topology", "shape"):
        raise HTTPException(400, "Study %s is not an optimisation study." % sid)
    rid = row.get("result")
    if not rid:
        raise HTTPException(404, "Study %s has no result yet." % sid)
    res = records.need(d, rid, "result")
    return row, res


@router.get("/{doc_id}/topo/limits")
def limits(doc_id: str) -> dict:
    _doc(doc_id)
    return limits_view()


@router.get("/{doc_id}/topo/studies/{sid}/preview")
def preview(doc_id: str, sid: str) -> dict:
    doc = _doc(doc_id)

    def run():
        with doc.lock:
            snap = topo_study.snapshot(doc, sid)
        setup = topo_study.resolve(snap, jobs.restricted())
        return {"study": sid, "info": setup.info, "options": setup.spec}

    return guarded(run)


@router.post("/{doc_id}/topo/studies/{sid}/run")
def run_topology(doc_id: str, sid: str, body: RunBody = RunBody()) -> dict:
    return _start(doc_id, sid, "topology", body)


@router.post("/{doc_id}/topo/studies/{sid}/shape")
def run_shape(doc_id: str, sid: str, body: RunBody = RunBody()) -> dict:
    return _start(doc_id, sid, "shape", body)


@router.get("/{doc_id}/topo/jobs/{job_id}")
def job_view(doc_id: str, job_id: str) -> dict:
    return {"job": _job(doc_id, job_id).view()}


@router.post("/{doc_id}/topo/jobs/{job_id}/cancel")
def job_cancel(doc_id: str, job_id: str) -> dict:
    _job(doc_id, job_id)
    return {"job": jobs.cancel(job_id)}


@router.get("/{doc_id}/topo/studies/{sid}/result")
def result(doc_id: str, sid: str) -> dict:
    doc = _doc(doc_id)

    def run(doc):
        row, res = _result(doc, sid)
        out = {"study": sid, "result": res["id"], "type": res.get("type"), "summary": res["summary"], "created": res.get("created"), "status": row.get("status")}
        if res.get("type") == "topology":
            grid, arrays, meta = outcome.unpack(sim_study.get_blob(doc.drawing, res["blob"]))
            out["history"] = {"columns": ["iteration", "compliance", "volume", "change", "beta"], "rows": np.round(arrays["history"], 6).tolist()}
            out["grid"] = grid.dims()
        return out

    return guarded(lambda: _read(doc_id, run))


@router.get("/{doc_id}/topo/studies/{sid}/result/display")
def display(doc_id: str, sid: str, field: str = "stress", smooth: int = 8, sigma: float = 0.6, max_triangles: int = 60000) -> dict:
    if field not in ("stress", "solid"):
        raise HTTPException(400, "The field is stress or solid.")

    def run(doc):
        row, res = _result(doc, sid)
        if res.get("type") != "topology":
            raise HTTPException(400, "Only a topology result has a surface.")
        grid, arrays, meta = outcome.unpack(sim_study.get_blob(doc.drawing, res["blob"]))
        v, t, _level = outcome.extract(grid, arrays, max(0, min(int(smooth), 100)), max(0.0, min(float(sigma), 2.0)))
        v, t = outcome.decimate(v, t, max(100, min(int(max_triangles), 200000)))
        vals = outcome.vertex_stress(grid, arrays, v)
        return {"study": sid, "field": field, "unit": "MPa", "label": "von Mises", "positions": np.round(v, 5).ravel().tolist(), "indices": t.astype(int).ravel().tolist(), "values": np.round(vals, 4).tolist(), "min": float(vals.min()), "max": float(vals.max()), "triangles": int(len(t)), "limit": res["summary"].get("stress_limit_mpa"), "summary": res["summary"]}

    return guarded(lambda: _read(doc_id, run))


@router.get("/{doc_id}/topo/studies/{sid}/result/voxels")
def voxels(doc_id: str, sid: str) -> dict:
    def run(doc):
        row, res = _result(doc, sid)
        if res.get("type") != "topology":
            raise HTTPException(400, "Only a topology result has voxels.")
        grid, arrays, meta = outcome.unpack(sim_study.get_blob(doc.drawing, res["blob"]))
        dens = np.clip(np.round(arrays["density"] * 255.0), 0, 255).astype(np.uint8)
        return {"grid": grid.dims(), "order": "x fastest, then y, then z", "density_u8": base64.b64encode(dens.tobytes()).decode("ascii"), "solid_u8": base64.b64encode(arrays["solid"].astype(np.uint8).tobytes()).decode("ascii"), "class_u8": base64.b64encode(arrays["cls"].astype(np.uint8).tobytes()).decode("ascii"), "classes": {"0": "design", "1": "preserved", "2": "empty"}}

    return guarded(lambda: _read(doc_id, run))
