from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cmd import barred
from app.doc.service import DocumentFault, service
from app.routers.part import _doc
from app.solid.work import SolidError
from app.toolbox import gens, insert, library, partfile

router = APIRouter(tags=["toolbox"])
ERRORS = insert.ERRORS + (SolidError, DocumentFault, library.LibraryError, gens.GenError)


def wrap(fn):
    try:
        return fn()
    except SolidError as err:
        raise HTTPException(503, str(err))
    except ERRORS as err:
        raise HTTPException(400, str(err))


class PartBody(BaseModel):
    source: dict[str, Any]
    folder: str
    stem: Optional[str] = None
    extra: Optional[dict[str, str]] = None


class FamilyBody(BaseModel):
    kind: str
    label: str
    id: str = ""
    source: str = ""
    unit: str = "mm"


class RowBody(BaseModel):
    name: str = ""
    params: dict[str, Any] = {}


class ImportBody(BaseModel):
    file: str
    family: str
    kind: str = ""
    label: str = ""
    mapping: Optional[dict[str, str]] = None
    unit: str = ""
    source: str = ""
    replace: bool = False


class InsertBody(BaseModel):
    source: Optional[dict[str, Any]] = None
    items: Optional[list[dict[str, Any]]] = None
    hole: Optional[dict[str, Any]] = None
    seat: Optional[dict[str, Any]] = None
    at: Optional[dict[str, Any]] = None
    folder: Optional[str] = None
    label: Optional[str] = None
    offset: float = 0.0
    flip: bool = False
    mates: bool = True
    extra: Optional[dict[str, str]] = None


@router.get("/toolbox/kinds")
def kinds() -> dict:
    return {"kinds": gens.kinds(), "note": gens.NOTE}


@router.post("/toolbox/check")
def check(body: dict[str, Any]) -> dict:
    def run():
        kind, params = insert.source_of(body.get("source") or body)
        p = gens.clean(kind, params)
        profile = None
        if gens.KINDS[kind]["group"] == "shape":
            profile = gens.profile(kind, p)
        return {"kind": kind, "params": p, "designation": gens.designation(kind, p), "volume": gens.expected_volume(kind, p), "profile": profile}

    return wrap(run)


@router.post("/toolbox/part")
def make_part(body: PartBody) -> dict:
    def run():
        kind, params = insert.source_of(body.source)
        return partfile.make(kind, params, body.folder, body.extra, body.stem or "")

    return wrap(run)


@router.get("/toolbox/library")
def library_list() -> dict:
    return wrap(library.listing)


@router.get("/toolbox/library/{fid}")
def library_family(fid: str) -> dict:
    return wrap(lambda: library.family(fid))


@router.post("/toolbox/library")
def library_add(body: FamilyBody) -> dict:
    return wrap(lambda: library.add_family(body.kind, body.label, body.id, body.source, body.unit, barred.caller()))


@router.delete("/toolbox/library/{fid}")
def library_remove(fid: str) -> dict:
    return wrap(lambda: library.remove_family(fid))


@router.post("/toolbox/library/{fid}/rows")
def library_row(fid: str, body: RowBody) -> dict:
    return wrap(lambda: library.add_row(fid, body.name, body.params))


@router.delete("/toolbox/library/{fid}/rows/{name}")
def library_row_remove(fid: str, name: str) -> dict:
    return wrap(lambda: library.remove_row(fid, name))


@router.post("/toolbox/library/import")
def library_import(body: ImportBody) -> dict:
    return wrap(lambda: library.import_csv(body.file, body.family, body.kind, body.label, body.mapping, body.unit, body.source, body.replace, barred.caller()))


@router.post("/docs/{doc_id}/toolbox/insert")
def insert_part(doc_id: str, body: InsertBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction("TOOLBOXINSERT"):
                if body.items is not None:
                    return insert.many(doc, body.items, hole=body.hole, seat=body.seat, folder=body.folder, flip=body.flip, mates=body.mates, offset=body.offset)
                return insert.one(doc, body.source or {}, body.hole, body.seat, body.at, body.folder, body.label, body.offset, body.flip, body.mates, body.extra)
        except SolidError as err:
            raise HTTPException(503, str(err))
        except ERRORS as err:
            raise HTTPException(400, str(err))
