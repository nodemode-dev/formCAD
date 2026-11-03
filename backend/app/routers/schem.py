from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.outputs import OutputRefused
from app.routers.part import _doc, _edit, _read
from app.schem import numbering, service, store
from app.schem.errors import SchemError

router = APIRouter(tags=["schem"])


class Free(BaseModel):
    model_config = {"extra": "allow"}


class NumberBody(BaseModel):
    template: Optional[str] = None
    prefix: Optional[str] = None
    keep_manual: bool = True


class ExportBody(BaseModel):
    path: str


class CompareBody(BaseModel):
    harness: Optional[list[dict[str, Any]]] = None
    sheets: Optional[list[int]] = None
    harness_doc: Optional[str] = None


def guarded(fn):
    try:
        return fn()
    except (SchemError, OutputRefused) as err:
        raise HTTPException(400, str(err))


@router.get("/{doc_id}/schem")
def show(doc_id: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: service.overview(doc.drawing)))


@router.post("/{doc_id}/schem/devices")
def add_device(doc_id: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMDEVICE", lambda doc: store.add_device(doc.drawing, body.model_dump())))


@router.put("/{doc_id}/schem/devices/{rid}")
def edit_device(doc_id: str, rid: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMDEVICE", lambda doc: store.edit_device(doc.drawing, rid, body.model_dump())))


@router.delete("/{doc_id}/schem/devices/{rid}")
def drop_device(doc_id: str, rid: str) -> dict:
    def work(doc):
        store.drop_device(doc.drawing, rid)
        return {"deleted": rid}

    return guarded(lambda: _edit(doc_id, "SCHEMDEVICE", work))


@router.post("/{doc_id}/schem/wires")
def add_wire(doc_id: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMWIRE", lambda doc: store.add_wire(doc.drawing, body.model_dump())))


@router.put("/{doc_id}/schem/wires/{rid}")
def edit_wire(doc_id: str, rid: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMWIRE", lambda doc: store.edit_wire(doc.drawing, rid, body.model_dump())))


@router.delete("/{doc_id}/schem/wires/{rid}")
def drop_wire(doc_id: str, rid: str) -> dict:
    def work(doc):
        store.drop_wire(doc.drawing, rid)
        return {"deleted": rid}

    return guarded(lambda: _edit(doc_id, "SCHEMWIRE", work))


@router.put("/{doc_id}/schem/settings")
def settings(doc_id: str, body: Free) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMSETTINGS", lambda doc: store.save_settings(doc.drawing, body.model_dump())))


@router.post("/{doc_id}/schem/number")
def number(doc_id: str, body: NumberBody) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMNUMBER", lambda doc: numbering.renumber(doc.drawing, body.template, body.prefix, body.keep_manual)))


@router.get("/{doc_id}/schem/check")
def check(doc_id: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: service.check(doc.drawing)))


@router.get("/{doc_id}/schem/nodes")
def nodes(doc_id: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: {"nodes": [{k: v for k, v in n.items() if k != "_w"} for n in numbering.nodes(doc.drawing)]}))


@router.post("/{doc_id}/schem/draw")
def draw(doc_id: str) -> dict:
    return guarded(lambda: _edit(doc_id, "SCHEMDRAW", lambda doc: service.draw(doc.drawing)))


@router.get("/{doc_id}/schem/wirelist")
def wirelist(doc_id: str) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: {"rows": service.wirelist(doc.drawing)}))


@router.post("/{doc_id}/schem/export")
def export(doc_id: str, body: ExportBody) -> dict:
    return guarded(lambda: _read(doc_id, lambda doc: service.write_csv(body.path, service.wirelist(doc.drawing))))


@router.post("/{doc_id}/schem/compare")
def compare(doc_id: str, body: CompareBody) -> dict:
    def work(doc):
        rows = body.harness
        if body.harness_doc:
            other = _doc(body.harness_doc)
            with other.lock:
                rows = service.harness_rows(other.drawing)
        return service.compare(doc.drawing, rows, body.sheets)

    return guarded(lambda: _read(doc_id, work))
