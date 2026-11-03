from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.outputs import OutputRefused
from app.pipe import fittings, limits, service, store
from app.pipe.limits import PipeError
from app.routers.part import _edit, _read
from app.solid import work as solidwork

router = APIRouter(tags=["pipes"])


class Free(BaseModel):
    model_config = {"extra": "allow"}


class FittingBody(BaseModel):
    type: str
    params: Optional[dict[str, Any]] = None
    run: Optional[str] = None
    vertex: Optional[int] = None
    name: Optional[str] = None


class ExportBody(BaseModel):
    path: str
    kind: str = "cutlist"
    run: Optional[str] = None


def guarded(fn):
    try:
        return fn()
    except (PipeError, OutputRefused) as err:
        raise HTTPException(400, str(err))


def overview(doc) -> dict:
    d = doc.drawing
    return {"specs": store.rows(d, "spec"), "runs": store.rows(d, "run"), "examples": store.EXAMPLES, "fitting_types": list(fittings.TYPES), "fitting_defaults": fittings.DEFAULTS, "limits": limits.get(), "labels": {"specs": store.LABEL, "fittings": fittings.LABEL}}


@router.get("/{doc_id}/pipes")
def show(doc_id: str) -> dict:
    return guarded(lambda: _read(doc_id, overview))


@router.post("/{doc_id}/pipes/specs")
def add_spec(doc_id: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "PIPESPEC", lambda doc: store.add(doc.drawing, "spec", "S", store.clean_spec(body.model_dump()))))


@router.put("/{doc_id}/pipes/specs/{sid}")
def edit_spec(doc_id: str, sid: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "PIPESPEC", lambda doc: store.put(doc.drawing, sid, "spec", store.clean_spec(body.model_dump(), store.need(doc.drawing, sid, "spec")))))


@router.delete("/{doc_id}/pipes/specs/{sid}")
def drop_spec(doc_id: str, sid: str) -> dict:
    def work(doc):
        d = doc.drawing
        if any(r.get("spec") == sid for r in store.rows(d, "run")):
            raise PipeError("Runs still use that spec.")
        store.drop(d, sid, "spec")
        return {"deleted": sid}

    return guarded(lambda: _edit(doc_id, "PIPESPEC", work))


def check_spec(d, run):
    if run.get("spec"):
        store.need(d, run["spec"], "spec")


@router.post("/{doc_id}/pipes/runs")
def add_run(doc_id: str, body: Free) -> dict:
    def work(doc):
        run = store.clean_run(body.model_dump())
        check_spec(doc.drawing, run)
        return store.add(doc.drawing, "run", "R", run)

    return guarded(lambda: _edit(doc_id, "PIPERUN", work))


@router.get("/{doc_id}/pipes/runs/{rid}")
def get_run(doc_id: str, rid: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: store.need(doc.drawing, rid, "run")))


@router.put("/{doc_id}/pipes/runs/{rid}")
def edit_run(doc_id: str, rid: str, body: Free) -> dict:
    def work(doc):
        d = doc.drawing
        run = store.clean_run(body.model_dump(), store.need(d, rid, "run"))
        check_spec(d, run)
        return store.put(d, rid, "run", run)

    return guarded(lambda: _edit(doc_id, "PIPERUN", work))


@router.delete("/{doc_id}/pipes/runs/{rid}")
def drop_run(doc_id: str, rid: str) -> dict:
    def work(doc):
        store.drop(doc.drawing, rid, "run")
        return {"deleted": rid}

    return guarded(lambda: _edit(doc_id, "PIPERUN", work))


@router.get("/{doc_id}/pipes/runs/{rid}/solve")
def solve_run(doc_id: str, rid: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: service.view(service.solve(doc.drawing, store.need(doc.drawing, rid, "run")), solidwork.mm(doc.drawing))))


@router.get("/{doc_id}/pipes/runs/{rid}/bender")
def bender(doc_id: str, rid: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: service.bender_table(doc.drawing, store.need(doc.drawing, rid, "run"))))


@router.get("/{doc_id}/pipes/cutlist")
def cutlist(doc_id: str, run: Optional[str] = None) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: {"rows": service.cutlist(doc.drawing, run), "fittings": service.fitting_bom(doc.drawing)}))


@router.post("/{doc_id}/pipes/fittings")
def make_fitting(doc_id: str, body: FittingBody) -> dict:
    def work(doc):
        d = doc.drawing
        place = None
        params = dict(body.params or {})
        if body.run:
            run = store.need(d, body.run, "run")
            res = service.solve(d, run)
            wanted = [f for f in res["fittings"] if f["kind"] == body.type and (body.vertex is None or f.get("vertex") == body.vertex)]
            if not wanted:
                raise PipeError("The run has no %s there." % body.type)
            place = service.place_of(res, wanted[0])
            params.setdefault("od", res["od"])
            params.setdefault("wall", res["wall"])
            if body.type == "elbow":
                params.setdefault("clr", wanted[0]["radius"])
        handle, p, summary = fittings.make(d, body.type, params, body.name or body.type.capitalize(), place)
        return {"handle": handle, "params": p, "summary": summary}

    return guarded(lambda: _edit(doc_id, "PIPEFITTING", work))


@router.post("/{doc_id}/pipes/runs/{rid}/bodies")
def run_bodies(doc_id: str, rid: str) -> dict:
    def work(doc):
        d = doc.drawing
        run = store.need(d, rid, "run")
        out = service.generate_bodies(d, run)
        store.put(d, rid, "run", {"bodies": out["bodies"]})
        return out

    return guarded(lambda: _edit(doc_id, "PIPEBODIES", work))


@router.post("/{doc_id}/pipes/export")
def export(doc_id: str, body: ExportBody) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: service.export(doc.drawing, body.path, body.kind, body.run)))
