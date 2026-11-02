from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc import layerops as LO
from app.doc import viewops as VO
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["layers"])


class OpsBody(BaseModel):
    ops: list[dict[str, Any]]
    label: Optional[str] = None


class ActionBody(BaseModel):
    action: str = "list"
    name: Optional[str] = None
    names: Optional[list[str]] = None
    to: Optional[str] = None
    description: Optional[str] = None
    overwrite: Optional[bool] = None
    props: Optional[list[str]] = None
    offMissing: Optional[bool] = None
    createMissing: Optional[bool] = None
    restoreCurrent: Optional[bool] = None
    layers: Optional[list[dict[str, Any]]] = None
    add: Optional[list[str]] = None
    remove: Optional[list[str]] = None
    update: Optional[bool] = None
    current: Optional[str] = None
    rename: Optional[str] = None
    path: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    kind: Optional[str] = None
    expr: Optional[dict[str, Any]] = None
    parent: Optional[str] = None
    snapshot: Optional[bool] = None
    camera3d: Optional[dict[str, Any]] = None
    p1: Optional[list[float]] = None
    p2: Optional[list[float]] = None


class VportBody(BaseModel):
    option: str = "list"
    orient: Optional[str] = None
    name: Optional[str] = None
    names: Optional[list[str]] = None
    dominant: Optional[int] = None
    other: Optional[int] = None
    tile: Optional[int] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _idle(doc) -> None:
    if doc.get_runner().run is not None:
        raise HTTPException(409, "A command is running; finish it first.")


def _run(doc, label: str, fn):
    _idle(doc)
    try:
        with doc.transaction(label):
            out = fn()
            LO.prune_noop(doc)
        return out
    except (LO.LayerError, VO.ViewError) as err:
        raise HTTPException(400, str(err))
    except (KeyError, TypeError, ValueError) as err:
        raise HTTPException(400, "Invalid request: %s" % err)


@router.get("/{doc_id}/layers")
def get_layers(doc_id: str, filter: str = "", search: str = "", sort: str = "name", desc: bool = False, viewport: Optional[int] = None) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return LO.describe(doc, filter, search, sort, desc, viewport)
        except LO.LayerError as err:
            raise HTTPException(404, str(err))


@router.put("/{doc_id}/layers")
def put_layers(doc_id: str, body: OpsBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        out = _run(doc, (body.label or "LAYER").upper()[:60], lambda: LO.apply_ops(doc, body.ops))
        res = LO.describe(doc)
        res.update(out)
        return res


@router.get("/{doc_id}/layers/filters")
def get_filters(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"filters": LO.filter_list(doc.drawing)}


@router.put("/{doc_id}/layers/filters")
def put_filters(doc_id: str, body: OpsBody) -> dict:
    doc = _doc(doc_id)

    def run():
        d = doc.drawing
        out = []
        for op in body.ops:
            kind = str(op.get("op", "set")).lower()
            if kind == "set":
                out.append(LO.set_filter(d, op.get("name", ""), op.get("kind"), op.get("expr"), op.get("layers"), op.get("parent"), op.get("add"), op.get("remove"))["name"])
            elif kind == "delete":
                out.extend(LO.delete_filter(d, op.get("name", "")))
            elif kind == "rename":
                out.append(LO.rename_filter(d, op.get("name", ""), op.get("to", ""))["name"])
            else:
                raise LO.LayerError("Unknown filter operation %s." % kind)
        return out

    with doc.lock:
        touched = _run(doc, "LAYER FILTER", run)
        return {"touched": touched, "filters": LO.filter_list(doc.drawing)}


@router.get("/{doc_id}/layers/states")
def get_states(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"states": LO.state_list(doc.drawing)}


@router.post("/{doc_id}/layers/states")
def post_states(doc_id: str, body: ActionBody) -> dict:
    doc = _doc(doc_id)
    action = body.action.lower()

    def run():
        d = doc.drawing
        name = body.name or ""
        if action == "list":
            return {}
        if action == "save":
            LO.push_prev(doc)
            rec = LO.save_state(d, name, body.description or "", bool(body.overwrite))
            return {"state": rec["name"]}
        if action == "restore":
            LO.push_prev(doc)
            return LO.restore_state(d, name, body.props, bool(body.offMissing), True if body.createMissing is None else body.createMissing, True if body.restoreCurrent is None else body.restoreCurrent)
        if action == "edit":
            st = LO.edit_state(d, name, body.description, body.layers, body.add, body.remove, bool(body.update), body.current, body.rename)
            return {"state": st["name"]}
        if action == "rename":
            return {"state": LO.edit_state(d, name, rename=body.to or "")["name"]}
        if action == "delete":
            return {"deleted": LO.delete_states(d, body.names or name)}
        if action == "export":
            return LO.export_states(d, body.names or ([name] if name else None), body.path or "")
        if action == "import":
            return LO.import_states(d, body.data, body.path or "", body.names, bool(body.overwrite))
        raise LO.LayerError("Unknown layer state action %s." % action)

    with doc.lock:
        out = _run(doc, "LAYER STATE", run)
        out["states"] = LO.state_list(doc.drawing)
        return out


@router.get("/{doc_id}/views")
def get_views(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"views": VO.list_views(doc.drawing), "snapshot": VO.view_session(doc)["snapshot"], "view": dict(doc.view), "space": doc.current_space}


@router.post("/{doc_id}/views")
def post_views(doc_id: str, body: ActionBody) -> dict:
    doc = _doc(doc_id)
    action = body.action.lower()

    def run():
        d = doc.drawing
        name = body.name or ""
        if action == "list":
            return {}
        if action == "save":
            rec, replaced = VO.save_view(doc, name, None, body.snapshot, body.camera3d)
            return {"view": rec["name"], "replaced": replaced}
        if action == "window":
            if not body.p1 or not body.p2:
                raise VO.ViewError("Give two corners (p1, p2).")
            rec, replaced = VO.save_view(doc, name, (body.p1, body.p2), body.snapshot)
            return {"view": rec["name"], "replaced": replaced}
        if action == "restore":
            return VO.restore_view(doc, name)
        if action == "delete":
            return {"deleted": VO.delete_views(d, body.names or name)}
        if action == "settings":
            if body.snapshot is not None:
                VO.view_session(doc)["snapshot"] = bool(body.snapshot)
            return {}
        raise VO.ViewError("Unknown view action %s." % action)

    with doc.lock:
        out = _run(doc, "VIEW", run)
        out["views"] = VO.list_views(doc.drawing)
        return out


@router.get("/{doc_id}/vports")
def get_vports(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return VO.describe_tiles(doc)
        except VO.ViewError as err:
            raise HTTPException(404, str(err))


@router.post("/{doc_id}/vports")
def post_vports(doc_id: str, body: VportBody) -> dict:
    doc = _doc(doc_id)
    opt = body.option.lower()

    def run():
        d = doc.drawing
        if opt in ("list", "?"):
            return VO.describe_tiles(doc)
        if opt in ("1", "single"):
            return VO.single(doc)
        if opt in ("2", "3", "4"):
            return VO.arrange(doc, int(opt), body.orient or "")
        if opt == "join":
            return VO.join(doc, int(body.dominant or VO.current_index(doc) + 1), int(body.other or 0))
        if opt == "save":
            rec, replaced = VO.save_config(doc, body.name or "")
            return {"name": rec["name"], "replaced": replaced}
        if opt == "restore":
            return VO.restore_config(doc, body.name or "")
        if opt == "delete":
            return {"deleted": VO.delete_configs(d, body.names or body.name or "")}
        if opt == "current":
            return VO.set_current_tile(doc, int(body.tile or 0))
        raise VO.ViewError("Unknown viewport option %s." % opt)

    with doc.lock:
        if opt == "current":
            try:
                out = dict(VO.set_current_tile(doc, int(body.tile or 0)))
            except VO.ViewError as err:
                raise HTTPException(400, str(err))
            return out
        out = _run(doc, "VPORTS", run)
        out.update(VO.describe_tiles(doc))
        return out
