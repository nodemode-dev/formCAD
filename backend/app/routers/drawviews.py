from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cmd import barred
from app.doc import layouts
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.solid.work import SolidError
from app.views import hook, model, ops
from app.views.model import ViewError

router = APIRouter(tags=["views"])
LOADED = (hook,)
FAILURES = (ViewError, layouts.LayoutError, SolidError, ValueError, KeyError, TypeError, CommandFailed)


class CreateBody(BaseModel):
    type: str = "base"
    layout: Optional[str] = None
    parent: Optional[Any] = None
    source: Optional[dict[str, Any]] = None
    component: Optional[str] = None
    direction: Optional[str] = None
    vnormal: Optional[list[float]] = None
    vup: Optional[list[float]] = None
    rel: Optional[str] = None
    scale: Optional[Any] = None
    position: Optional[list[float]] = None
    label: Optional[str] = None
    letter: Optional[str] = None
    kind: Optional[str] = None
    line: Optional[list[list[float]]] = None
    flip: bool = False
    edge: Optional[dict[str, Any]] = None
    center: Optional[list[float]] = None
    radius: Optional[float] = None
    gap: Optional[float] = None
    mode: Optional[str] = None
    show: Optional[dict[str, Any]] = None
    style: Optional[dict[str, Any]] = None
    auto: bool = True
    flat: bool = False
    breaks: Optional[list[dict[str, Any]]] = None
    polygon: Optional[list[list[float]]] = None


class PatchBody(BaseModel):
    changes: dict[str, Any] = {}
    breaks: Optional[list[dict[str, Any]]] = None
    polygon: Optional[list[list[float]]] = None
    clear_breaks: bool = False
    clear_crop: bool = False


class ProjectionBody(BaseModel):
    layout: str
    system: str


class UpdateBody(BaseModel):
    all: bool = False


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, SolidError):
        raise HTTPException(503, str(err))
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    raise HTTPException(400, str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc)
        except FAILURES as err:
            _fail(err)


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except FAILURES as err:
            _fail(err)


def _no_file_source(src):
    if isinstance(src, dict) and src.get("doc") and barred.caller(None):
        raise HTTPException(403, "A macro or outside agent cannot point a view at another file.")


@router.get("/{doc_id}/drawviews")
def list_views(doc_id: str, layout: str = "") -> dict:
    def go(doc):
        d = doc.drawing
        rows = [ops.info(d, v) for v in sorted(ops.views_of(d, layout), key=lambda e: e.handle)]
        return {"views": rows, "projection": {n: model.projection_of(d, n) for n in layouts.names(d)}}

    return _read(doc_id, go)


@router.get("/{doc_id}/drawviews/{handle}")
def get_view(doc_id: str, handle: int, cache: bool = False) -> dict:
    return _read(doc_id, lambda doc: ops.info(doc.drawing, ops.get(doc.drawing, handle), cache))


@router.post("/{doc_id}/drawviews")
def create_view(doc_id: str, body: CreateBody) -> dict:
    args = body.model_dump(exclude_none=True)
    _no_file_source(args.get("source"))
    kind = args.pop("type", "base")

    def go(doc):
        d = doc.drawing
        if kind == "base":
            h = ops.create_base(doc, args)
        elif kind == "projected":
            h = ops.create_projected(doc, args)
        elif kind in ("auxiliary", "aux"):
            h = ops.create_aux(doc, args)
        elif kind == "section":
            h = ops.create_section(doc, args)
        elif kind == "detail":
            h = ops.create_detail(doc, args)
        else:
            raise ViewError("Create a broken or cropped view by editing a view.")
        return ops.info(d, ops.get(d, h))

    return _edit(doc_id, "VIEW", go)


@router.patch("/{doc_id}/drawviews/{handle}")
def patch_view(doc_id: str, handle: int, body: PatchBody) -> dict:
    _no_file_source(body.changes.get("source"))

    def go(doc):
        d = doc.drawing
        if body.breaks is not None or body.clear_breaks:
            ops.set_breaks(doc, handle, body.breaks or [], body.clear_breaks)
        if body.polygon is not None or body.clear_crop:
            ops.set_crop(doc, handle, body.polygon, body.clear_crop)
        if body.changes:
            ops.edit(doc, handle, body.changes)
        return ops.info(d, ops.get(d, handle))

    return _edit(doc_id, "VIEWEDIT", go)


@router.delete("/{doc_id}/drawviews/{handle}")
def delete_view(doc_id: str, handle: int, cascade: bool = False) -> dict:
    return _edit(doc_id, "VIEWDELETE", lambda doc: {"deleted": ops.delete(doc, handle, cascade)})


@router.post("/{doc_id}/drawviews/{handle}/update")
def update_view(doc_id: str, handle: int) -> dict:
    def go(doc):
        ops.update(doc, handle)
        return ops.info(doc.drawing, ops.get(doc.drawing, handle))

    return _edit(doc_id, "VIEWUPDATE", go)


@router.post("/{doc_id}/drawviews/update")
def update_views(doc_id: str, body: UpdateBody) -> dict:
    return _edit(doc_id, "VIEWUPDATE", lambda doc: {"updated": ops.update_all(doc, not body.all)})


@router.put("/{doc_id}/drawviews/projection")
def put_projection(doc_id: str, body: ProjectionBody) -> dict:
    return _edit(doc_id, "VIEWPROJECTION", lambda doc: {"layout": body.layout, "projection": model.set_projection(doc.drawing, body.layout, body.system)})
