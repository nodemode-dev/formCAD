from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.interchange import dwg, files, hooks
from app.interchange.errors import InterchangeError

hooks.install()

router = APIRouter(tags=["interchange"])


class OpenBody(BaseModel):
    path: str
    recover: bool = False


class SaveBody(BaseModel):
    path: str
    version: Optional[str] = ""
    binary: bool = False


class ImportBody(BaseModel):
    path: str
    recover: bool = False


class DwgBody(BaseModel):
    enabled: Optional[bool] = None
    converter: Optional[str] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _wrap(fn):
    try:
        return fn()
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    except InterchangeError as err:
        raise HTTPException(400, str(err))


@router.get("/interchange/formats")
def formats() -> dict:
    return files.formats()


@router.get("/interchange/dwg")
def dwg_status() -> dict:
    return dwg.status()


@router.put("/interchange/dwg")
def dwg_settings(body: DwgBody) -> dict:
    _wrap(lambda: dwg.save_settings(body.enabled, body.converter))
    return dwg.status()


@router.post("/interchange/open")
def open_file(body: OpenBody) -> dict:
    import os

    full = os.path.realpath(os.path.expanduser(body.path))
    if files.ext_of(full) in (".fcad",):
        return _wrap(lambda: service.open(full).summary())
    doc = _wrap(lambda: service.open_foreign(full, body.recover))
    out = doc.summary()
    out["notes"] = getattr(doc, "import_notes", {})
    return out


@router.post("/docs/{doc_id}/interchange/saveas")
def save_as(doc_id: str, body: SaveBody) -> dict:
    doc = _doc(doc_id)
    if files.ext_of(body.path) in (".dxf", ".dwg", ".dwt"):
        out = _wrap(lambda: service.save_foreign(doc, body.path, body.version or "", body.binary)).summary()
    else:
        out = _wrap(lambda: service.save(doc, body.path)).summary()
    out["notes"] = getattr(doc, "import_notes", {})
    return out


@router.post("/docs/{doc_id}/interchange/export")
def export_file(doc_id: str, body: SaveBody) -> dict:
    doc = _doc(doc_id)

    def run():
        report = files.write_any(doc.drawing, body.path, body.version or "", body.binary)
        return {"path": body.path, "notes": report.to_dict()}

    return _wrap(run)


@router.post("/docs/{doc_id}/interchange/import")
def import_file(doc_id: str, body: ImportBody) -> dict:
    doc = _doc(doc_id)
    return _wrap(lambda: files.merge_into(doc, body.path, "IMPORT", body.recover))
