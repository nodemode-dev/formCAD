from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.calc import service as calc_service
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["calc"])


class CalcBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    expression: Optional[str] = None
    variables: Optional[dict[str, Any]] = None
    picks: Optional[list[Any]] = None
    convert: Optional[dict[str, Any]] = None
    units: Optional[Any] = None
    pick: Optional[dict[str, Any]] = None
    doc_id: Optional[str] = Field(None, alias="docId")


@router.post("/calc")
def calc(body: CalcBody) -> dict:
    doc = None
    if body.doc_id:
        try:
            doc = service.get(body.doc_id)
        except DocumentFault as err:
            raise HTTPException(err.status, err.message)
    payload = body.model_dump(exclude_none=True)
    payload.pop("doc_id", None)
    if doc is None:
        return calc_service.handle(payload)
    with doc.lock:
        return calc_service.handle(payload, doc)
