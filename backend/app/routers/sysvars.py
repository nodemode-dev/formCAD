from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import sysvars
from app.doc.service import DocError, service

router = APIRouter(tags=["sysvars"])


class SetBody(BaseModel):
    doc: Optional[str] = None
    value: Any = None


def _doc(doc_id: Optional[str]):
    if doc_id:
        try:
            return service.get(doc_id)
        except DocError as err:
            raise HTTPException(err.status, err.message)
    return service.active()


@router.get("")
def list_vars(doc: Optional[str] = None) -> dict:
    d = _doc(doc)
    if d is None:
        return {"vars": sysvars.listing(None)}
    with d.lock:
        return {"vars": sysvars.listing(d)}


@router.get("/{name}")
def get_var(name: str, doc: Optional[str] = None) -> dict:
    d = _doc(doc)
    try:
        return {"name": name.upper(), "value": sysvars.get_var(d, name)}
    except sysvars.SysvarError as err:
        raise HTTPException(400, str(err))


@router.put("/{name}")
def put_var(name: str, body: SetBody) -> dict:
    d = _doc(body.doc)
    try:
        if d is not None:
            with d.lock:
                value = sysvars.set_var(d, name, body.value)
        else:
            value = sysvars.set_var(None, name, body.value)
    except sysvars.SysvarError as err:
        raise HTTPException(400, str(err))
    return {"name": name.upper(), "value": value}
