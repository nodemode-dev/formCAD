from typing import Any

from fastapi import APIRouter

from app.mold import service, settings
from app.routers.part import _doc, _edit, _fail, _read
from app.solid.work import SolidError

router = APIRouter(tags=["mold"])


def _free(doc_id: str, fn):
    doc = _doc(doc_id)
    try:
        return fn(doc)
    except (ValueError, KeyError, SolidError) as err:
        _fail(err)


@router.get("/{doc_id}/mold")
def show(doc_id: str) -> dict:
    return _read(doc_id, service.report)


@router.get("/{doc_id}/mold/settings")
def get_settings(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"settings": settings.current(doc.drawing)})


@router.put("/{doc_id}/mold/settings")
def put_settings(doc_id: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "MOLDSETTINGS", lambda doc: {"settings": settings.put(doc.drawing, body)})


@router.delete("/{doc_id}/mold/settings")
def delete_settings(doc_id: str) -> dict:
    def run(doc):
        settings.reset(doc.drawing)
        return {"settings": settings.current(doc.drawing)}

    return _edit(doc_id, "MOLDSETTINGS", run)


@router.post("/{doc_id}/mold/analyze")
def post_analyze(doc_id: str, body: dict[str, Any] | None = None) -> dict:
    return _free(doc_id, lambda doc: service.analyze(doc, body or {}))


@router.post("/{doc_id}/mold/parting")
def post_parting(doc_id: str, body: dict[str, Any] | None = None) -> dict:
    return _free(doc_id, lambda doc: service.parting(doc, body or {}))


@router.post("/{doc_id}/mold/block")
def post_block(doc_id: str, body: dict[str, Any] | None = None) -> dict:
    return _edit(doc_id, "MOLDBLOCK", lambda doc: service.block(doc, body or {}))


@router.post("/{doc_id}/mold/split")
def post_split(doc_id: str, body: dict[str, Any] | None = None) -> dict:
    return _edit(doc_id, "MOLDSPLIT", lambda doc: service.split(doc, body or {}))


@router.delete("/{doc_id}/mold/products")
def delete_products(doc_id: str) -> dict:
    return _edit(doc_id, "MOLDCLEAR", lambda doc: {"erased": service.clear(doc.drawing)})
