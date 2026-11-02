from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc import blockedit, dynblock, editstate, refedit, xref
from app.doc.blocktools import EditError
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["xrefs"])


class XrefBody(BaseModel):
    action: str
    name: Optional[str] = None
    path: Optional[str] = None
    mode: Optional[str] = None
    type: Optional[str] = None
    overlay: Optional[bool] = None
    point: Optional[list[float]] = None
    scale: Optional[Any] = None
    rotation: Optional[float] = None
    place: Optional[bool] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


@router.get("/{doc_id}/xrefs")
def list_xrefs(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rows = xref.listing(doc.drawing)
        return {"xrefs": rows, "total": len([r for r in rows if not r["nested"]]), "notes": list(getattr(doc, "xref_notes", []))}


@router.post("/{doc_id}/xrefs")
def run_xref(doc_id: str, body: XrefBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rn = doc.get_runner()
        if rn.run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        args = {k: v for k, v in body.model_dump().items() if v is not None}
        state = rn.run_command("-xref", args)
        if rn.error:
            raise HTTPException(400, rn.error)
        rows = xref.listing(doc.drawing)
        return {"result": rn.result, "output": state.get("output", []), "xrefs": rows, "rev": doc.rev}


@router.get("/{doc_id}/blockedit")
def block_editor(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"editor": blockedit.status(doc.drawing), "reference": refedit.status(doc.drawing), "blocks": blockedit.listing(doc.drawing)}


@router.get("/{doc_id}/dynblock/{handle}")
def dynamic_block(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            props = dynblock.reference_properties(doc.drawing, handle)
            props["grips"] = dynblock.custom_grips(doc.drawing, handle) if props["dynamic"] else []
        except EditError as err:
            raise HTTPException(400, str(err))
        return props


@router.get("/{doc_id}/blockedit/guard")
def guard_state(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"space": doc.current_space, "refused": editstate.command_refusal(doc, "layout")}
