from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.plastic import check, data, records, rule
from app.routers.part import _edit, _read

router = APIRouter(tags=["plastic"])


class CheckBody(BaseModel):
    pull: Optional[list[float]] = None
    samples: Optional[int] = None
    method: Optional[str] = None


def overview(doc) -> dict:
    d = doc.drawing
    return {"rule": rule.current(d), "features": records.features(d)}


@router.get("/{doc_id}/plastic")
def show(doc_id: str) -> dict:
    return _read(doc_id, overview)


@router.get("/{doc_id}/plastic/rule")
def get_rule(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"rule": rule.current(doc.drawing)})


@router.put("/{doc_id}/plastic/rule")
def put_rule(doc_id: str, body: dict[str, Any]) -> dict:
    def run(doc):
        out = rule.put(doc.drawing, body)
        rule.refresh(doc)
        return {"rule": out}

    return _edit(doc_id, "PLASTICRULE", run)


@router.delete("/{doc_id}/plastic/rule")
def delete_rule(doc_id: str) -> dict:
    def run(doc):
        rule.reset(doc.drawing)
        rule.refresh(doc)
        return {"rule": rule.current(doc.drawing)}

    return _edit(doc_id, "PLASTICRULE", run)


@router.get("/{doc_id}/plastic/data")
def get_data(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: data.listing())


@router.get("/{doc_id}/plastic/features")
def get_features(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"features": records.features(doc.drawing)})


@router.post("/{doc_id}/plastic/checks")
def post_checks(doc_id: str, body: CheckBody) -> dict:
    return _read(doc_id, lambda doc: check.run(doc, body.model_dump()))


@router.get("/{doc_id}/plastic/wall")
def get_wall(doc_id: str, method: str = "sphere", samples: Optional[int] = None) -> dict:
    return _read(doc_id, lambda doc: {"wall": check.run(doc, {"method": method, "samples": samples})["wall"]})


@router.post("/{doc_id}/plastic/wall")
def post_wall(doc_id: str, body: CheckBody) -> dict:
    return _read(doc_id, lambda doc: {"wall": check.run(doc, body.model_dump())["wall"]})
