from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.harness import service
from app.routers.part import _doc

router = APIRouter(tags=["harness"])


class ActionBody(BaseModel):
    action: str
    args: Optional[dict[str, Any]] = None


class ExportBody(BaseModel):
    kind: str = "wirelist"
    file: str
    sep: str = ","


def _run(doc, command: str, args: dict) -> dict:
    runner = doc.get_runner()
    if runner.run is not None:
        raise HTTPException(409, "A command is running; finish it first.")
    state = runner.run_command(command, args)
    if state.get("error"):
        raise HTTPException(400, state["error"])
    return state.get("result") or {}


def _read(doc_id, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except service.ERRORS as err:
            raise HTTPException(400, str(err))


@router.get("/{doc_id}/harness")
def listing(doc_id: str) -> dict:
    return _read(doc_id, service.listing)


@router.get("/{doc_id}/harness/report")
def report(doc_id: str) -> dict:
    return _read(doc_id, service.report)


@router.post("/{doc_id}/harness")
def act(doc_id: str, body: ActionBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return _run(doc, "harness", {**(body.args or {}), "action": body.action})


@router.post("/{doc_id}/harness/export")
def export(doc_id: str, body: ExportBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return _run(doc, "harnessexport", body.model_dump())
