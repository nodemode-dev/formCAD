from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.param import store as S
from app.part import preview
from app.part.registry import PartError
from app.solid import scene as scene_mod
from app.solid.work import SolidError

router = APIRouter(tags=["part"])


class PreviewBody(BaseModel):
    type: Optional[str] = None
    id: Optional[str] = None
    params: dict[str, Any] = {}
    refs: dict[str, Any] = {}
    after: Optional[str] = None
    detail: float = 1.0
    hold: Optional[str] = None


@router.get("/{doc_id}/part/scene-at")
def part_scene_at(doc_id: str, to: str, detail: float = 1.0) -> Response:
    try:
        doc = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            payload = preview.at(doc, to, detail)
        except SolidError as err:
            raise HTTPException(503, str(err))
        except (PartError, S.ParamError, ValueError, KeyError, CommandFailed) as err:
            raise HTTPException(400, str(err))
    return Response(content=payload, media_type=scene_mod.MEDIA_TYPE, headers={"Cache-Control": "no-store"})


@router.post("/{doc_id}/part/preview")
def part_preview(doc_id: str, body: PreviewBody) -> Response:
    try:
        doc = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            payload, info = preview.run(doc, body.type, body.id, body.params, body.refs, body.after, body.detail, body.hold)
        except SolidError as err:
            raise HTTPException(503, str(err))
        except (PartError, S.ParamError, ValueError, KeyError, CommandFailed) as err:
            raise HTTPException(400, str(err))
    return Response(content=payload, media_type=scene_mod.MEDIA_TYPE, headers={"Cache-Control": "no-store", "X-FormCAD-Preview": preview.header(info)})
