from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.param import store as S
from app.part import features_core, hook, names, rebuild, registry, store, tree
from app.part.registry import PartError, RefLost
from app.solid.work import SolidError

router = APIRouter(tags=["part"])
LOADED = (features_core, hook, names)


class AddBody(BaseModel):
    type: str
    label: Optional[str] = None
    params: dict[str, Any] = {}
    refs: dict[str, Any] = {}
    after: Optional[str] = None
    suppressed: bool = False


class EditBody(BaseModel):
    label: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    refs: Optional[dict[str, Any]] = None
    suppressed: Optional[bool] = None


class SuppressBody(BaseModel):
    suppressed: bool = True


class RollbackBody(BaseModel):
    to: Optional[str] = None


class ReorderBody(BaseModel):
    id: str
    after: Optional[str] = None


class RebuildBody(BaseModel):
    start: Optional[str] = None
    force: bool = False


class RefBody(BaseModel):
    kind: str = "face"
    pid: Optional[int] = None
    index: Optional[int] = None
    key: Optional[str] = None
    feature: Optional[str] = None
    role: Optional[str] = None
    p: Optional[list[float]] = None
    id: Optional[str] = None
    ctx: Optional[str] = None


class WorkspaceBody(BaseModel):
    workspace: str


class AutoBody(BaseModel):
    auto: bool


class SketchBody(BaseModel):
    name: Optional[str] = None
    plane: str = "XY"
    offset: float = 0.0
    face: Optional[dict[str, Any]] = None
    origin: Optional[list[float]] = None
    xdir: Optional[list[float]] = None
    after: Optional[str] = None
    entities: list[int] = []
    source: Optional[dict[str, Any]] = None


class EntitiesBody(BaseModel):
    handles: list[int]


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, SolidError):
        raise HTTPException(503, str(err))
    if isinstance(err, (PartError, S.ParamError, ValueError, KeyError)):
        raise HTTPException(400, str(err))
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    raise err


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc)
        except (PartError, S.ParamError, SolidError, ValueError, KeyError, CommandFailed) as err:
            _fail(err)


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except (PartError, S.ParamError, SolidError, ValueError, KeyError) as err:
            _fail(err)


@router.get("/{doc_id}/part")
def part_tree(doc_id: str) -> dict:
    return _read(doc_id, tree.listing)


@router.get("/{doc_id}/part/types")
def part_types(doc_id: str) -> dict:
    _doc(doc_id)
    return {"types": registry.listing()}


@router.post("/{doc_id}/part/features")
def add_feature(doc_id: str, body: AddBody) -> dict:
    return _edit(doc_id, "FEATURE", lambda doc: tree.add_feature(doc, body.type, body.params, body.refs, body.label, body.after, body.suppressed))


@router.get("/{doc_id}/part/features/{fid}")
def get_feature(doc_id: str, fid: str) -> dict:
    return _read(doc_id, lambda doc: tree.get_feature(doc, fid))


@router.patch("/{doc_id}/part/features/{fid}")
def edit_feature(doc_id: str, fid: str, body: EditBody) -> dict:
    return _edit(doc_id, "FEATUREEDIT", lambda doc: tree.edit_feature(doc, fid, body.label, body.params, body.refs, body.suppressed))


@router.delete("/{doc_id}/part/features/{fid}")
def delete_feature(doc_id: str, fid: str, cascade: int = 0, sketch: int = 0) -> dict:
    return _edit(doc_id, "FEATUREDELETE", lambda doc: tree.delete_feature(doc, fid, bool(cascade), bool(sketch)))


@router.post("/{doc_id}/part/features/{fid}/suppress")
def suppress_feature(doc_id: str, fid: str, body: SuppressBody) -> dict:
    return _edit(doc_id, "SUPPRESS" if body.suppressed else "UNSUPPRESS", lambda doc: tree.set_suppressed(doc, fid, body.suppressed))


@router.post("/{doc_id}/part/rollback")
def rollback(doc_id: str, body: RollbackBody) -> dict:
    return _edit(doc_id, "ROLLBACK", lambda doc: tree.set_rollback(doc, body.to))


@router.post("/{doc_id}/part/reorder")
def reorder(doc_id: str, body: ReorderBody) -> dict:
    return _edit(doc_id, "FEATUREMOVE", lambda doc: tree.reorder(doc, body.id, body.after))


@router.get("/{doc_id}/part/features/{fid}/canmove")
def can_move(doc_id: str, fid: str, after: str = "") -> dict:
    def run(doc):
        tree.need(doc, fid)
        why = tree.can_move(doc.drawing, fid, after)
        return {"ok": not why, "message": why}

    return _read(doc_id, run)


@router.post("/{doc_id}/part/rebuild")
def rebuild_route(doc_id: str, body: RebuildBody) -> dict:
    return _edit(doc_id, "REBUILD", lambda doc: {"report": rebuild.rebuild(doc, body.force, body.start), "tree": tree.listing(doc)})


@router.post("/{doc_id}/part/refs")
def make_ref(doc_id: str, body: RefBody) -> dict:
    def run(doc):
        raw = {k: v for k, v in body.model_dump().items() if v is not None and k not in ("kind", "ctx")}
        return tree.make_ref(doc, body.kind, raw, body.ctx)

    return _read(doc_id, run)


@router.put("/{doc_id}/part/workspace")
def workspace(doc_id: str, body: WorkspaceBody) -> dict:
    return _edit(doc_id, "WORKSPACE", lambda doc: tree.set_workspace(doc, body.workspace))


@router.put("/{doc_id}/part/auto")
def auto(doc_id: str, body: AutoBody) -> dict:
    return _edit(doc_id, "AUTOREBUILD", lambda doc: tree.set_auto(doc, body.auto))


@router.post("/{doc_id}/part/sketch")
def create_sketch(doc_id: str, body: SketchBody) -> dict:
    return _edit(doc_id, "PARTSKETCH", lambda doc: tree.create_sketch(doc, body.name, body.plane, body.offset, body.face, body.origin, body.xdir, body.after, body.entities, body.source))


@router.post("/{doc_id}/part/sketch/{fid}/enter")
def sketch_enter(doc_id: str, fid: str) -> dict:
    return _edit(doc_id, "SKETCHENTER", lambda doc: tree.sketch_enter(doc, fid))


@router.post("/{doc_id}/part/sketch/exit")
def sketch_exit(doc_id: str) -> dict:
    return _edit(doc_id, "SKETCHEXIT", tree.sketch_exit)


@router.post("/{doc_id}/part/sketch/{fid}/entities")
def sketch_entities(doc_id: str, fid: str, body: EntitiesBody) -> dict:
    return _edit(doc_id, "SKETCHADD", lambda doc: tree.add_sketch_entities(doc, fid, body.handles))
