from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.doc.service import DocumentFault, service
from app.solid import scene as scene_mod
from app.solid import work
from app.solid.work import SolidError

router = APIRouter(tags=["scene"])


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


@router.get("/{doc_id}/scene")
def get_scene(doc_id: str, since: int = 0, detail: float = 1.0) -> Response:
    doc = _doc(doc_id)
    try:
        if doc.kind == "assembly":
            from app.assembly import scene as assembly_scene

            payload = assembly_scene.build(doc, since, detail)
        else:
            payload = scene_mod.build(doc, since, detail)
    except SolidError as err:
        raise HTTPException(503, str(err))
    except ValueError as err:
        raise HTTPException(400, str(err))
    return Response(content=payload, media_type=scene_mod.MEDIA_TYPE, headers={"Cache-Control": "no-store", "X-FormCAD-Rev": str(doc.rev)})


@router.get("/{doc_id}/solids")
def list_solids(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        d = doc.drawing
        out = []
        for e in d.ordered_entities():
            if e.kind != "solidbody":
                continue
            out.append({"handle": e.handle, "name": e.name, "layer": e.layer, "version": e.version, "source": e.source, "rgb": e.rgb, "summary": e.summary, "visible": bool(d.visible(e)), "offset": e.offset})
        return {"rev": doc.rev, "mm_per_unit": work.mm(d), "bodies": out}


@router.get("/{doc_id}/solids/{handle}/massprops")
def solid_massprops(doc_id: str, handle: int, density: float = 1.0) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        body = doc.drawing.get(handle)
        if body is None or body.kind != "solidbody":
            raise HTTPException(404, "No such solid body.")
        try:
            return work.mass_properties(doc.drawing, body, density)
        except SolidError as err:
            raise HTTPException(503, str(err))


@router.get("/{doc_id}/solids/{handle}/face/{pid}")
def solid_face(doc_id: str, handle: int, pid: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        body = doc.drawing.get(handle)
        if body is None or body.kind != "solidbody":
            raise HTTPException(404, "No such solid body.")
        if pid in body.face_ids:
            return {"kind": "face", "pid": pid, "index": body.face_ids.index(pid), "version": body.version, "parent": body.lineage.get(str(pid))}
        if pid in body.edge_ids:
            return {"kind": "edge", "pid": pid, "index": body.edge_ids.index(pid), "version": body.version, "parent": body.lineage.get(str(pid))}
        raise HTTPException(404, "No such face or edge in this body.")
