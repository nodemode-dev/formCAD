from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.automation import ops

router = APIRouter(tags=["automation"])


class ValueBody(BaseModel):
    value: Any = None


class ExportBody(BaseModel):
    path: str
    version: Optional[str] = ""
    window: Optional[list[float]] = None
    layout: Optional[str] = "Model"
    dpi: Optional[float] = None
    paper: Optional[str] = ""


class RenderBody(BaseModel):
    window: Optional[list[float]] = None
    size: Optional[int] = 1600


def _run(fn):
    try:
        return fn()
    except ops.OpError as err:
        raise HTTPException(400, str(err))


@router.get("/{doc_id}/entities")
def entities(doc_id: str, kind: str = "", layer: str = "", selected: bool = False, window: str = "", crossing: bool = True, offset: int = 0, limit: int = ops.DEFAULT_PAGE, handle: Optional[int] = None, geometry: bool = True) -> dict:
    def go():
        box = [float(v) for v in window.split(",")] if window else None
        return ops.query_entities(ops.document(doc_id), kind, layer, selected, box, crossing, offset, limit, handle, geometry)

    return _run(go)


@router.get("/{doc_id}/variable/{name}")
def get_variable(doc_id: str, name: str) -> dict:
    return _run(lambda: {"name": name.upper(), "value": ops.variable(ops.document(doc_id), name)})


@router.post("/{doc_id}/variable/{name}")
def set_variable(doc_id: str, name: str, body: ValueBody) -> dict:
    return _run(lambda: {"name": name.upper(), "value": ops.set_variable(ops.document(doc_id), name, body.value)})


@router.get("/{doc_id}/automation/summary")
def summary(doc_id: str) -> dict:
    return _run(lambda: ops.summary(ops.document(doc_id)))


@router.post("/{doc_id}/automation/export")
def export(doc_id: str, body: ExportBody) -> dict:
    return _run(lambda: ops.export(ops.document(doc_id), body.path, body.version or "", body.window, "", body.layout or "Model", body.dpi, body.paper or ""))


@router.post("/{doc_id}/automation/render")
def render(doc_id: str, body: RenderBody) -> Response:
    data = _run(lambda: ops.render_png(ops.document(doc_id), body.window, body.size or 1600))
    return Response(content=data, media_type="image/png")
