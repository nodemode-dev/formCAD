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
