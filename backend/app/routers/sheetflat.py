from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.sheetmetal import bend, flat, flatdxf
from app.solid.work import SolidError

router = APIRouter(tags=["sheetflat"])

GUARDED = (flat.FlatError, flatdxf.FlatDxfError, bend.BendError, SolidError, ValueError, KeyError)


class FlatIn(BaseModel):
    on: Optional[bool] = None
    flip: Optional[bool] = None
    fixed_face: Optional[int] = None
    clear_fixed: bool = False
    align: Optional[str] = None
    rule: Optional[dict[str, Any]] = None


class FlatExportIn(BaseModel):
    path: str
    profile: str = "bending"
    version: str = "R2018"
    notes: bool = False
    handle: Optional[int] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, SolidError):
        raise HTTPException(503, str(err))
    raise HTTPException(400, str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


@router.get("/{doc_id}/sheetmetal/flat")
def get_flat(doc_id: str, data: bool = True, handle: Optional[int] = None):
    doc = _doc(doc_id)
    with doc.lock:
        d = doc.drawing
        st = flat.state(d)
        out = {"state": st}
        if data and st["on"]:
            try:
                out["flat"] = flat.compute(d, handle)
            except GUARDED as err:
                _fail(err)
        return out


@router.put("/{doc_id}/sheetmetal/flat")
def put_flat(doc_id: str, body: FlatIn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction("Flat pattern"):
                d = doc.drawing
                changes = {k: v for k, v in (("on", body.on), ("flip", body.flip), ("align", body.align), ("rule", body.rule)) if v is not None}
                if body.fixed_face is not None:
                    changes["fixed_face"] = body.fixed_face
                if body.clear_fixed:
                    changes["fixed_face"] = None
                st = flat.set_state(d, **changes)
                out = {"state": st}
                if st["on"]:
                    out["flat"] = flat.compute(d)
                return out
        except GUARDED as err:
            _fail(err)


@router.get("/{doc_id}/sheetmetal/flat/props")
def get_props(doc_id: str, handle: Optional[int] = None):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return flat.cutlist(flat.compute(doc.drawing, handle))
        except GUARDED as err:
            _fail(err)


@router.post("/{doc_id}/sheetmetal/flat/export")
def export_flat(doc_id: str, body: FlatExportIn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return flatdxf.export(flat.compute(doc.drawing, body.handle), body.path, body.profile, body.version, body.notes)
        except GUARDED as err:
            _fail(err)
