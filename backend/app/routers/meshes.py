import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.interchange import threedm
from app.interchange.errors import InterchangeError
from app.meshes import core, jobs, repair, store
from app.meshes.core import MeshError

router = APIRouter(tags=["meshes"])


class InfoBody(BaseModel):
    path: str


class SelfBody(BaseModel):
    max_pairs: int = 1000


class Window:
    runner = None

    def __init__(self, doc):
        self.doc = doc


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
                rows.append({"handle": e.handle, "name": e.name, "points_only": bool(e.points_only), "summary": e.summary, "source": e.source, "version": e.version, "rgb": list(e.rgb or [])})
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


@router.get("/{doc_id}/meshes/limits")
def mesh_limits(doc_id: str) -> dict:
    _doc(doc_id)
    return jobs.limits_view()


@router.get("/{doc_id}/meshes/activity")
def mesh_activity(doc_id: str) -> dict:
    _doc(doc_id)
    return {"running": jobs.running(doc_id)}


@router.post("/{doc_id}/meshes/cancel")
def mesh_cancel(doc_id: str) -> dict:
    _doc(doc_id)
    return {"cancelled": jobs.cancel(doc_id)}


@router.post("/{doc_id}/meshes/{handle}/selfintersections")
def mesh_selfx(doc_id: str, handle: int, body: SelfBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _mesh(doc, handle)
        if ent.points_only:
            raise HTTPException(409, "A point cloud has no triangles to check.")
        n = int(ent.summary.get("triangles", 0))
        if n > jobs.cap(None, "selfx"):
            raise HTTPException(413, "The self-intersection check is limited to %d triangles; this mesh has %d. Reduce it first." % (jobs.cap(None, "selfx"), n))
        try:
            m = store.load(doc.drawing, ent)
        except MeshError as err:
            raise HTTPException(409, str(err))
    try:
        with jobs.activity(Window(doc), "meshselfx") as act:
            res = repair.self_intersections(m, max(1, min(int(body.max_pairs), jobs.SELFX_MAX_PAIRS)), act)
    except jobs.Cancelled as err:
        raise HTTPException(409, str(err))
    except Exception as err:
        raise HTTPException(409, str(err))
    from app.param.units import mm_per_unit

    s = mm_per_unit(doc.drawing)
    off = [c for c in ent.offset]
    pts = [[(p[0]) / s + off[0], p[1] / s + off[1], p[2] / s + off[2]] for p in res["points"]]
    return {"handle": ent.handle, "pairs": res["pairs"], "triangles_involved": res["triangles_involved"], "sample": res["sample"], "capped": res["capped"], "points": pts}


@router.post("/3dm/info")
def info_3dm(body: InfoBody) -> dict:
    full = os.path.realpath(os.path.expanduser(body.path))
    if not os.path.isfile(full) or os.path.splitext(full)[1].lower() != ".3dm":
        raise HTTPException(400, "Give the path of an existing .3dm file.")
    try:
        return threedm.info(full)
    except InterchangeError as err:
        raise HTTPException(400, str(err))
