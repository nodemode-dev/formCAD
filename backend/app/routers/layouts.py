from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.display import layout_view
from app.doc import layouts, papers, viewports
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["layouts"])


class ActionBody(BaseModel):
    action: str
    name: Optional[str] = None
    to: Optional[str] = None
    index: Optional[int] = None
    path: Optional[str] = None


class SpaceBody(BaseModel):
    tab: Optional[str] = None
    viewport: Optional[int] = None
    maximize: Optional[bool] = None


class ViewBody(BaseModel):
    center: list[float]
    height: float


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _run(doc, command: str, args: dict) -> dict:
    runner = doc.get_runner()
    if runner.run is not None:
        raise HTTPException(409, "A command is running; finish it first.")
    state = runner.run_command(command, args)
    if state.get("error"):
        raise HTTPException(400, state["error"])
    return state.get("result") or {}


def _summary(doc) -> dict:
    doc.current_space
    return {"tab": doc.tab, "current": layouts.tab_label(doc) if doc.tab != "model" else "Model", "viewport": doc.active_vp, "maximized": doc.vp_max, "layouts": layouts.listing(doc), "rev": doc.rev}


@router.get("/{doc_id}/layouts")
def list_layouts(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return _summary(doc)


@router.post("/{doc_id}/layouts")
def layout_action(doc_id: str, body: ActionBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        args = {k: v for k, v in body.model_dump().items() if v is not None}
        result = _run(doc, "layout", args)
        out = _summary(doc)
        out["result"] = result
        return out


@router.get("/{doc_id}/layouts/{name}")
def get_layout(doc_id: str, name: str, content: bool = True) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return layout_view.layout_dict(doc, name, content)
        except layouts.LayoutError as err:
            raise HTTPException(404, str(err))


@router.put("/{doc_id}/layouts/{name}/pagesetup")
def put_pagesetup(doc_id: str, name: str, body: dict[str, Any]) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        if layouts.find(doc.drawing, name) is None:
            raise HTTPException(404, 'Layout "%s" not found.' % name)
        _run(doc, "pagesetup", {**body, "layout": name})
        return layouts.page_setup(doc.drawing, name)


@router.get("/{doc_id}/layouts/{name}/pagesetup")
def get_pagesetup(doc_id: str, name: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            ps = layouts.page_setup(doc.drawing, name)
        except layouts.LayoutError as err:
            raise HTTPException(404, str(err))
        return {**ps, "sheet": list(layouts.sheet_size(ps)), "printable": layouts.printable(ps)}


@router.get("/{doc_id}/papers")
def get_papers(doc_id: str) -> dict:
    _doc(doc_id)
    return {"papers": papers.listing()}


@router.get("/{doc_id}/viewports")
def get_viewports(doc_id: str, layout: Optional[str] = None) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        d = doc.drawing
        rec = layouts.find(d, layout) if layout else (layouts.find(d, layouts.tab_label(doc)) if doc.tab != "model" else None)
        if rec is None:
            raise HTTPException(404, "No such layout.")
        return {"layout": rec["name"], "viewports": [viewports.info(d, v) for v in viewports.of_layout(d, rec["name"])]}


@router.put("/{doc_id}/viewports/{handle}")
def put_viewport(doc_id: str, handle: int, body: dict[str, Any]) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        vp = doc.drawing.get(handle)
        if vp is None or vp.kind != "viewport":
            raise HTTPException(404, "No such viewport.")
        res = _run(doc, "viewport.set", {**body, "handle": handle})
        return res["viewports"][0]


@router.post("/{doc_id}/viewports/{handle}/view")
def set_viewport_view(doc_id: str, handle: int, body: ViewBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        vp = doc.drawing.get(handle)
        if vp is None or vp.kind != "viewport":
            raise HTTPException(404, "No such viewport.")
        if len(body.center) != 2:
            raise HTTPException(400, "The centre is two numbers.")
        res = _run(doc, "viewport.set", {"handle": handle, "viewCenter": body.center, "viewHeight": body.height})
        return res["viewports"][0]


@router.post("/{doc_id}/space")
def set_space(doc_id: str, body: SpaceBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        runner = doc.get_runner()
        if runner.run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        if body.tab is not None:
            _run(doc, "layout", {"action": "set", "name": body.tab})
        if body.maximize is True:
            _run(doc, "vpmax", {"handle": body.viewport})
        elif body.maximize is False:
            _run(doc, "vpmin", {})
        elif body.viewport is not None:
            if body.viewport == 0:
                _run(doc, "pspace", {})
            else:
                _run(doc, "mspace", {"handle": body.viewport})
        return _summary(doc)
