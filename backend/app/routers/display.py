from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app import display
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["display"])


@router.get("/{doc_id}/display")
def get_display(doc_id: str, since: Optional[int] = None, space: str = "model") -> Response:
    try:
        doc = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with doc.lock:
        try:
            payload = display.build(doc, since, space)
        except display.NoSuchSpace:
            raise HTTPException(404, "No such space.")
    return Response(content=payload, media_type="application/json")


@router.get("/{doc_id}/underlays/{handle}")
def get_underlay(doc_id: str, handle: int) -> Response:
    from app.doc import underlays as U

    try:
        doc = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with doc.lock:
        e = doc.drawing.get(handle)
        if e is None or e.kind != "underlay":
            raise HTTPException(404, "No such underlay.")
        full = U.resolve(e.path, U.folder_of(doc))
        page = int(e.page)
        want = ("pdf",) if e.source == "pdf" else ("png", "jpeg")
    if not full or U.kind_of(full) not in want:
        raise HTTPException(404, "The underlay file was not found.")
    try:
        data, media = U.screen_bytes(full, page)
    except (U.UnderlayError, OSError) as err:
        raise HTTPException(422, str(err))
    return Response(content=data, media_type=media, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
