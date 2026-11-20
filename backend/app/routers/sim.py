import os
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cmd import barred
from app.core.outputs import OutputRefused
from app.routers.part import _doc, _edit, _fail, _read
from app.services import mesher
from app.sim import display, jobs, materials, records, registry, report, study
from app.sim.fem import SimError
from app.sim.records import SimRecordError

router = APIRouter(tags=["sim"])


def guarded(fn):
    try:
        return fn()
    except mesher.MesherError as err:
        raise HTTPException(503, str(err))
    except OutputRefused as err:
        raise HTTPException(400, str(err))
    except (SimError, SimRecordError) as err:
        raise HTTPException(400, str(err))
    except KeyError as err:
        raise HTTPException(400, str(err.args[0]) if err.args else "Not found.")


class RecordBody(BaseModel):
    kind: str
    fields: Optional[dict[str, Any]] = None
    model_config = {"extra": "allow"}


class PointsBody(BaseModel):
    points: list[list[float]]
    mode: int = 0


class ReportBody(BaseModel):
    path: str
    format: str = "html"
    title: Optional[str] = None


def overview(doc) -> dict:
    d = doc.drawing
    grouped = {k: records.of_kind(d, k) for k in records.KINDS}
    for row in grouped["study"]:
        info = row.get("mesh_info") or {}
        body = d.ents.get((row.get("geometry") or {}).get("body"))
        moved = body is not None and info.get("body_blob") and (info["body_blob"] != body.blob or [float(v) for v in body.offset] != info.get("body_offset"))
        if moved and row.get("status") in ("solved", "meshed"):
            row["status"] = "stale"
    return {
        "records": grouped,
        "solvers": registry.listing(),
        "mesher": mesher.status(),
        "limits": study.limits_view(),
        "job": None,
    }


@router.get("/{doc_id}/sim")
def show(doc_id: str) -> dict:
    mesher.probe()
    out = _read(doc_id, overview)
    active = jobs.active(doc_id)
    out["job"] = active.view() if active else None
    return out


@router.get("/{doc_id}/sim/status")
def mesher_status(doc_id: str) -> dict:
    _doc(doc_id)
    mesher.probe()
    return mesher.status()


@router.post("/{doc_id}/sim/mesher/install")
def mesher_install(doc_id: str) -> dict:
    _doc(doc_id)
    return mesher.start_install()


@router.get("/{doc_id}/sim/materials/library")
def library(doc_id: str) -> dict:
    _doc(doc_id)
    return materials.library()


@router.post("/{doc_id}/sim/records")
def create_record(doc_id: str, body: RecordBody) -> dict:
    raw = dict(body.model_extra or {})
    raw.update(body.fields or {})
    return guarded(lambda: _edit(doc_id, "SIMRECORD", lambda doc: {"record": records.create(doc.drawing, body.kind, raw)}))


@router.put("/{doc_id}/sim/records/{rid}")
def update_record(doc_id: str, rid: str, body: dict[str, Any]) -> dict:
    return guarded(lambda: _edit(doc_id, "SIMRECORD", lambda doc: {"record": records.update(doc.drawing, rid, body)}))


@router.delete("/{doc_id}/sim/records/{rid}")
def delete_record(doc_id: str, rid: str) -> dict:
    return guarded(lambda: _edit(doc_id, "SIMRECORD", lambda doc: {"removed": records.remove(doc.drawing, rid)["id"]}))


@router.get("/{doc_id}/sim/studies/{sid}/faces")
def study_faces(doc_id: str, sid: str) -> dict:
    doc = _doc(doc_id)

    def run():
        with doc.lock:
            snap = study.snapshot(doc, sid)
        with tempfile.TemporaryDirectory(prefix="fcsim_") as tmp:
            brep = study.export_brep(doc, snap["body"], tmp)
            return mesher.call("faces", {"path": brep}, 60.0)

    return guarded(lambda: _guard_work(run))


def _guard_work(fn):
    from app.solid.work import SolidError

    try:
        return fn()
    except SolidError as err:
        raise HTTPException(503, str(err))


def _start(doc_id: str, sid: str, mode: str) -> dict:
    doc = _doc(doc_id)
    restrict = study.restricted()
    with doc.lock:
        records.need(doc.drawing, sid, "study")
    return guarded(lambda: {"job": jobs.start(doc, sid, mode, restrict)})


@router.post("/{doc_id}/sim/studies/{sid}/mesh")
def mesh_study(doc_id: str, sid: str) -> dict:
    return _start(doc_id, sid, "mesh")


@router.post("/{doc_id}/sim/studies/{sid}/run")
def run_study(doc_id: str, sid: str) -> dict:
    return _start(doc_id, sid, "run")


def _job(doc_id: str, job_id: str):
    _doc(doc_id)
    job = guarded(lambda: jobs.get(job_id))
    if job.doc_id != doc_id:
        raise HTTPException(404, "There is no job %s on this document." % job_id)
    return job


@router.get("/{doc_id}/sim/jobs/{job_id}")
def job_view(doc_id: str, job_id: str) -> dict:
    return {"job": _job(doc_id, job_id).view()}


@router.post("/{doc_id}/sim/jobs/{job_id}/cancel")
def job_cancel(doc_id: str, job_id: str) -> dict:
    _job(doc_id, job_id)
    return {"job": guarded(lambda: jobs.cancel(job_id))}


@router.get("/{doc_id}/sim/studies/{sid}/mesh/display")
def mesh_display(doc_id: str, sid: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: report.mesh_display(doc, sid)))


@router.get("/{doc_id}/sim/studies/{sid}/result")
def result_view(doc_id: str, sid: str) -> dict:
    def run(doc):
        row = records.need(doc.drawing, sid, "study")
        res = records.get(doc.drawing, row.get("result"), "result") if row.get("result") else None
        return {"study": row, "result": res}

    return guarded(lambda: _read(doc_id, run))


@router.get("/{doc_id}/sim/studies/{sid}/result/display")
def result_display(doc_id: str, sid: str, field: str = "", mode: int = 0, scale: str = "auto", ramp: str = "") -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: display.show(doc, sid, field, mode, scale, ramp)))


@router.post("/{doc_id}/sim/studies/{sid}/result/probe")
def result_probe(doc_id: str, sid: str, body: PointsBody) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: display.probe(doc, sid, body.points, body.mode)))


@router.post("/{doc_id}/sim/studies/{sid}/report")
def make_report(doc_id: str, sid: str, body: ReportBody) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: report.write(doc, sid, body.path, body.format, body.title)))
