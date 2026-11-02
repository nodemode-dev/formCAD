from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.cmd import grips
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["canvas"])


class PreviewBody(BaseModel):
    point: list[float]
    snap: Optional[dict[str, Any]] = None


class SelectionBody(BaseModel):
    handles: list[int] = []
    mode: Optional[str] = "set"


class GripBody(BaseModel):
    handle: int
    grip: Any
    mode: str = "stretch"
    to: list[float]
    base: Optional[list[float]] = None
    copy_: Optional[bool] = Field(False, alias="copy")
    preview: Optional[bool] = False
    ref: Optional[float] = None
    option: Optional[str] = None
    value: Optional[float] = None
    more: Optional[list[list[float]]] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _point(value: Optional[list[float]], label: str) -> Optional[list[float]]:
    if value is None:
        return None
    if len(value) not in (2, 3):
        raise HTTPException(400, "%s must be [x, y]." % label)
    return value


@router.post("/{doc_id}/preview")
def preview(doc_id: str, body: PreviewBody) -> dict:
    doc = _doc(doc_id)
    _point(body.point, "point")
    return doc.get_runner().preview(body.point)


@router.get("/{doc_id}/selection")
def get_selection(doc_id: str) -> dict:
    from app.sysvars import registry as sv

    doc = _doc(doc_id)
    handles = doc.get_runner().current_selection()
    return {"handles": handles, "pickfirst": bool(sv.get_var(doc, "PICKFIRST")), "rev": doc.rev}


@router.put("/{doc_id}/selection")
def put_selection(doc_id: str, body: SelectionBody) -> dict:
    from app.sysvars import registry as sv

    doc = _doc(doc_id)
    mode = body.mode or "set"
    if mode not in ("set", "add", "remove"):
        raise HTTPException(400, "mode must be set, add or remove.")
    handles = doc.get_runner().set_selection(body.handles, mode)
    return {"handles": handles, "pickfirst": bool(sv.get_var(doc, "PICKFIRST")), "rev": doc.rev}


@router.get("/{doc_id}/grips")
def get_grips(doc_id: str, handles: str = "") -> dict:
    doc = _doc(doc_id)
    try:
        wanted = [int(h) for h in handles.split(",") if h.strip()]
    except ValueError:
        raise HTTPException(400, "handles must be a comma list of integers.")
    with doc.lock:
        if not wanted:
            wanted = doc.get_runner().current_selection()
        return {"sets": grips.grip_sets(doc, wanted)}


@router.post("/{doc_id}/grip")
def grip_edit(doc_id: str, body: GripBody) -> dict:
    doc = _doc(doc_id)
    _point(body.to, "to")
    _point(body.base, "base")
    try:
        return grips.run(doc, body.handle, body.grip, body.mode, body.to, body.base, bool(body.copy_),bool(body.preview), body.ref, body.option, body.value, body.more)
    except grips.GripError as err:
        raise HTTPException(400, str(err))
    except CommandFailed as err:
        raise HTTPException(409, str(err))
