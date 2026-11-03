import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.interchange import threedm
from app.interchange.errors import InterchangeError
from app.meshes import core, store
from app.meshes.core import MeshError

router = APIRouter(tags=["meshes"])


class InfoBody(BaseModel):
    path: str


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _mesh(doc, handle: int):
    ent = doc.drawing.get(int(handle))
    if ent is None or ent.kind != "meshbody":
        raise HTTPException(404, "There is no mesh object with that handle.")
    return ent


@router.get("/{doc_id}/meshes")
def mesh_list(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rows = []
        for e in doc.drawing.entities("model"):
            if e.kind == "meshbody":
                rows.append({"handle": e.handle, "name": e.name, "points_only": bool(e.points_only), "summary": e.summary, "source": e.source, "version": e.version})
        return {"meshes": rows, "rev": doc.rev}


@router.get("/{doc_id}/meshes/{handle}/report")
def mesh_report(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _mesh(doc, handle)
        if ent.points_only:
            return {"handle": ent.handle, "report": ent.summary}
        try:
            return {"handle": ent.handle, "report": core.report(store.load(doc.drawing, ent))}
        except MeshError as err:
            raise HTTPException(409, str(err))


@router.get("/{doc_id}/meshes/{handle}/naked")
def mesh_naked(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _mesh(doc, handle)
        if ent.points_only:
            return {"handle": ent.handle, "polylines": [], "unit_mm": 1.0}
        try:
            lines = store.naked_polylines(store.load(doc.drawing, ent))
        except MeshError as err:
            raise HTTPException(409, str(err))
        from app.param.units import mm_per_unit

        s = mm_per_unit(doc.drawing)
        return {"handle": ent.handle, "polylines": [[[c / s for c in p] for p in line] for line in lines], "unit_mm": s}


@router.post("/3dm/info")
def info_3dm(body: InfoBody) -> dict:
    full = os.path.realpath(os.path.expanduser(body.path))
    if not os.path.isfile(full) or os.path.splitext(full)[1].lower() != ".3dm":
        raise HTTPException(400, "Give the path of an existing .3dm file.")
    try:
        return threedm.info(full)
    except InterchangeError as err:
        raise HTTPException(400, str(err))
