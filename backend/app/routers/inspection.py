from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cmd import barred
from app.routers.part import _doc, _edit, _read
from app.toolbox import inspection, mbd

router = APIRouter(tags=["inspection"])


def guarded(fn):
    def run(doc):
        try:
            return fn(doc)
        except inspection.ERRORS as err:
            raise ValueError(str(err))
        except mbd.ERRORS as err:
            raise ValueError(str(err))

    return run


class FileBody(BaseModel):
    file: str
    kind: str = ""


class OrderBody(BaseModel):
    order: Optional[list[str]] = None


class AssignBody(BaseModel):
    rule: str = "facing"


@router.get("/{doc_id}/inspection")
def listing(doc_id: str) -> dict:
    return _read(doc_id, guarded(lambda doc: inspection.listing(doc.drawing)))


@router.post("/{doc_id}/inspection/collect")
def collect(doc_id: str) -> dict:
    return _edit(doc_id, "INSPECTCOLLECT", guarded(lambda doc: inspection.collect(doc.drawing, barred.caller())))


@router.post("/{doc_id}/inspection")
def add(doc_id: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "INSPECTADD", guarded(lambda doc: inspection.add_manual(doc.drawing, body, barred.caller())))


@router.patch("/{doc_id}/inspection/{ident}")
def edit(doc_id: str, ident: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "INSPECTEDIT", guarded(lambda doc: inspection.edit(doc.drawing, ident, body)))


@router.delete("/{doc_id}/inspection/{ident}")
def delete(doc_id: str, ident: str) -> dict:
    return _edit(doc_id, "INSPECTDELETE", guarded(lambda doc: inspection.remove(doc.drawing, ident)))


@router.post("/{doc_id}/inspection/renumber")
def renumber(doc_id: str, body: OrderBody) -> dict:
    return _edit(doc_id, "INSPECTRENUMBER", guarded(lambda doc: inspection.renumber(doc.drawing, body.order)))


@router.post("/{doc_id}/inspection/balloons")
def balloons(doc_id: str) -> dict:
    return _edit(doc_id, "INSPECTBALLOONS", guarded(lambda doc: inspection.balloons(doc.drawing)))


@router.get("/{doc_id}/inspection/balloons")
def model_balloons(doc_id: str) -> dict:
    return _read(doc_id, guarded(lambda doc: {"balloons": inspection.model_balloons(doc.drawing)}))


@router.put("/{doc_id}/inspection/form")
def form(doc_id: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "INSPECTFORM", guarded(lambda doc: inspection.set_form(doc.drawing, body)))


@router.get("/{doc_id}/inspection/report")
def report(doc_id: str) -> dict:
    return _read(doc_id, guarded(inspection.build_report))


@router.post("/{doc_id}/inspection/export")
def export(doc_id: str, body: FileBody) -> dict:
    return _read(doc_id, guarded(lambda doc: inspection.export(doc, body.file, body.kind)))


@router.post("/{doc_id}/inspection/import")
def import_results(doc_id: str, body: FileBody) -> dict:
    return _edit(doc_id, "INSPECTRESULTS", guarded(lambda doc: inspection.import_results(doc.drawing, body.file, barred.caller())))


@router.get("/{doc_id}/mbd")
def mbd_listing(doc_id: str) -> dict:
    return _read(doc_id, guarded(lambda doc: {"views": mbd.header(doc.drawing)["views"], "cameras": sorted(mbd.CAMERAS)}))


@router.post("/{doc_id}/mbd/views")
def mbd_add(doc_id: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "MBDVIEW", guarded(lambda doc: mbd.add_view(doc.drawing, body)))


@router.patch("/{doc_id}/mbd/views/{view}")
def mbd_edit(doc_id: str, view: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "MBDVIEWEDIT", guarded(lambda doc: mbd.edit_view(doc.drawing, view, body)))


@router.delete("/{doc_id}/mbd/views/{view}")
def mbd_delete(doc_id: str, view: str) -> dict:
    return _edit(doc_id, "MBDVIEWDELETE", guarded(lambda doc: mbd.remove_view(doc.drawing, view)))


@router.post("/{doc_id}/mbd/views/{view}/assign")
def mbd_assign(doc_id: str, view: str, body: AssignBody) -> dict:
    return _edit(doc_id, "MBDASSIGN", guarded(lambda doc: mbd.assign(doc.drawing, view, body.rule)))


@router.get("/{doc_id}/mbd/views/{view}/display")
def mbd_display(doc_id: str, view: str) -> dict:
    return _read(doc_id, guarded(lambda doc: mbd.display(doc.drawing, view)))


@router.get("/{doc_id}/mbd/report")
def mbd_report(doc_id: str) -> dict:
    return _read(doc_id, guarded(lambda doc: mbd.report(doc.drawing)))
