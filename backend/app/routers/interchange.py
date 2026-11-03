import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import outputs
from app.doc.service import DocumentFault, service
from app.interchange import dwg, fileunits, files, hooks
from app.interchange.errors import InterchangeError

hooks.install()

router = APIRouter(tags=["interchange"])


class OpenBody(BaseModel):
    path: str
    recover: bool = False
    unit: Optional[str] = ""
    options: dict[str, Any] = {}


class SaveBody(BaseModel):
    path: str
    version: Optional[str] = ""
    binary: bool = False
    options: dict[str, Any] = {}


class ImportBody(BaseModel):
    path: str
    recover: bool = False
    unit: Optional[str] = ""
    options: dict[str, Any] = {}


class InspectBody(BaseModel):
    path: str
    document: Optional[str] = None


class DwgBody(BaseModel):
    enabled: Optional[bool] = None
    converter: Optional[str] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def remember(doc, key: str, value) -> None:
    if value is None:
        return
    if not hasattr(doc, "pmi_reports"):
        doc.pmi_reports = {}
    doc.pmi_reports[key] = value


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


@router.post("/interchange/inspect")
def inspect_file(body: InspectBody) -> dict:
    target = _doc(body.document).drawing if body.document else None
    out = _wrap(lambda: fileunits.inspect_file(body.path, target))
    if out["ext"] in (".stl", ".obj", ".ply"):
        out["suggestion"] = _wrap(lambda: mesh_hint(out["path"], out["ext"], target))
    return out


def mesh_hint(path: str, ext: str, target):
    import numpy as np

    from app.meshes import exchange, formats, ply
    from app.meshes.core import MeshError

    if os.path.getsize(path) > 64 * 1024 * 1024:
        return {}
    data = exchange.read_file_bytes(path)
    try:
        if ext == ".stl":
            m, _ = formats.read_stl(data)
        elif ext == ".obj":
            m, _ = formats.read_obj(data)
        else:
            m, info = ply.read_ply(data)
    except MeshError as err:
        raise InterchangeError(str(err), "badmesh")
    diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0)))
    from app.interchange.fileunits import document_unit

    key, mm = document_unit(target) if target is not None else ("mm", 1.0)
    hint = exchange.suggest_unit(diag, mm) if not (0.1 <= diag * mm <= 10000.0) else ""
    return {"diagonal_raw": diag, "diagonal_mm_in_document_unit": diag * mm, "suggested_unit": hint}


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
    doc = _wrap(lambda: service.open_foreign(full, body.recover, body.unit or "", body.options))
    out = doc.summary()
    out["notes"] = getattr(doc, "import_notes", {})
    return out


@router.post("/docs/{doc_id}/interchange/saveas")
def save_as(doc_id: str, body: SaveBody) -> dict:
    doc = _doc(doc_id)
    if files.ext_of(body.path) in files.THREEDM_EXT + files.MESH_EXT:
        try:
            target = outputs.checked(body.path, files.THREEDM_EXT + files.MESH_EXT)
        except outputs.OutputRefused as err:
            raise HTTPException(400, str(err))
        report = _wrap(lambda: files.write_any(doc.drawing, target, body.version or "", body.binary, 16, body.options, doc))
        out = doc.summary()
        out["notes"] = report.to_dict()
        return out
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
        target = body.path
        if files.ext_of(target) in files.MODEL_EXT + files.NEW_MESH_EXT:
            try:
                target = outputs.checked(body.path, files.MODEL_EXT + files.NEW_MESH_EXT)
            except outputs.OutputRefused as err:
                raise InterchangeError(str(err), "refused")
        report = files.write_any(doc.drawing, target, body.version or "", body.binary, 16, body.options, doc)
        remember(doc, "write", report.extra.get("pmi"))
        return {"path": target, "notes": report.to_dict()}

    return _wrap(run)


@router.post("/docs/{doc_id}/interchange/import")
def import_file(doc_id: str, body: ImportBody) -> dict:
    doc = _doc(doc_id)
    out = _wrap(lambda: files.merge_into(doc, body.path, "IMPORT", body.recover, body.unit or "", body.options))
    remember(doc, "read", ((out.get("report") or {}).get("extra") or {}).get("pmi"))
    return out
