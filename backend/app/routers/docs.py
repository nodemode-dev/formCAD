from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["docs"])


class NewBody(BaseModel):
    name: Optional[str] = None
    template: Optional[str] = None


class PathBody(BaseModel):
    path: Optional[str] = None


class CloseBody(BaseModel):
    force: Optional[bool] = False


class StepsBody(BaseModel):
    steps: Optional[int] = 1


class TextBody(BaseModel):
    text: Optional[str] = None
    point: Optional[list[float]] = None
    snap: Optional[dict[str, Any]] = None
    pick: Optional[dict[str, Any]] = None
    selection: Optional[dict[str, Any]] = None


class CommandBody(BaseModel):
    command: str
    args: Optional[dict[str, Any]] = None


class FileBody(BaseModel):
    file: str


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _wrap(fn):
    try:
        return fn()
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    except CommandFailed as err:
        raise HTTPException(409, str(err))


@router.get("")
def list_docs() -> dict:
    return {"docs": service.summaries(), "active": service.active_id}


@router.post("")
def new_doc(body: Optional[NewBody] = None) -> dict:
    body = body or NewBody()
    return _wrap(lambda: service.new(body.name or "", body.template or "").summary())


@router.post("/open")
def open_doc(body: PathBody) -> dict:
    return _wrap(lambda: service.open(body.path or "").summary())


@router.get("/recovery")
def recovery_list() -> dict:
    return {"items": service.recovery_list()}


@router.post("/recovery/open")
def recovery_open(body: FileBody) -> dict:
    return _wrap(lambda: service.recovery_open(body.file).summary())


@router.post("/recovery/discard")
def recovery_discard(body: FileBody) -> dict:
    return {"discarded": service.recovery_discard(body.file)}


@router.post("/autosave/now")
def autosave_now() -> dict:
    return {"saved": service.saver.save_now()}


@router.get("/{doc_id}")
def get_doc(doc_id: str) -> dict:
    return _doc(doc_id).summary()


@router.post("/{doc_id}/save")
def save_doc(doc_id: str, body: Optional[PathBody] = None) -> dict:
    doc = _doc(doc_id)
    return _wrap(lambda: service.save(doc, (body.path if body else "") or "").summary())


@router.post("/{doc_id}/close")
def close_doc(doc_id: str, body: Optional[CloseBody] = None) -> dict:
    doc = _doc(doc_id)
    closed = service.close(doc, bool(body.force) if body else False)
    return {"closed": closed, "dirty": doc.dirty and not closed}


def _history(doc, fn, steps: int) -> dict:
    with doc.lock:
        rn = doc.get_runner()
        if rn.run is not None and fn == "undo" and rn.inline_undo():
            return {"rev": doc.rev, "label": "Undo", "labels": ["Undo"], "inline": True, "state": rn.state()}
        rn.begin_call()
        if rn.run is not None:
            rn.cancel_run()
        try:
            labels = doc.do_undo(steps) if fn == "undo" else doc.do_redo(steps)
        except CommandFailed as err:
            raise HTTPException(409, str(err))
        if not labels:
            rn.log("Nothing to undo." if fn == "undo" else "Nothing to redo.")
        else:
            for label in labels:
                rn.log(label)
        return {"rev": doc.rev, "label": labels[-1] if labels else "", "labels": labels, "state": rn.state()}


@router.post("/{doc_id}/undo")
def undo(doc_id: str, body: Optional[StepsBody] = None) -> dict:
    return _history(_doc(doc_id), "undo", max(1, (body.steps if body and body.steps else 1)))


@router.post("/{doc_id}/redo")
def redo(doc_id: str, body: Optional[StepsBody] = None) -> dict:
    return _history(_doc(doc_id), "redo", max(1, (body.steps if body and body.steps else 1)))


@router.get("/{doc_id}/snapshot")
def snapshot(doc_id: str, since: int = 0) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return doc.snapshot(since)


@router.get("/{doc_id}/state")
def state(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rn = doc.get_runner()
        rn.begin_call()
        return rn.state()


@router.post("/{doc_id}/input")
def send_input(doc_id: str, body: TextBody) -> dict:
    runner = _doc(doc_id).get_runner()
    if body.point is not None:
        return runner.submit_point(body.point, body.snap)
    if body.pick is not None:
        return runner.submit_pick(body.pick)
    if body.selection is not None:
        return runner.submit_selection(body.selection)
    return runner.submit(body.text or "")


@router.post("/{doc_id}/command")
def run_command(doc_id: str, body: CommandBody) -> dict:
    return _doc(doc_id).get_runner().run_command(body.command, body.args)


@router.post("/{doc_id}/cancel")
def cancel(doc_id: str) -> dict:
    return _doc(doc_id).get_runner().cancel()
