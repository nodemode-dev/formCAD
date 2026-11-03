from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.mates import explode, interf, motion, ops, timing
from app.mates import store as S
from app.solid.work import SolidError

router = APIRouter(tags=["mates"])


class MateBody(BaseModel):
    kind: str
    refs: list[Any]
    value: Optional[float] = None
    opt: dict[str, Any] = {}
    label: str = ""
    force: bool = False


class MateEdit(BaseModel):
    value: Optional[float] = None
    opt: Optional[dict[str, Any]] = None
    label: Optional[str] = None
    suppressed: Optional[bool] = None


class DragBody(BaseModel):
    component: str
    point: list[float]
    target: list[float]
    commit: bool = False


class DriveBody(BaseModel):
    value: Optional[float] = None
    values: Optional[list[float]] = None
    start: Optional[float] = None
    end: Optional[float] = None
    count: Optional[int] = None
    max_step: Optional[float] = None
    commit: bool = True
    report: bool = False
    components: Optional[list[str]] = None


class SweepBody(BaseModel):
    mate: str
    start: float = 0.0
    end: float = 350.0
    count: int = 36
    clearance: Optional[float] = None
    fuzzy: Optional[float] = None
    max_step: Optional[float] = None
    ignore: Optional[list[list[str]]] = None


class InterfereBody(BaseModel):
    clearance: Optional[float] = None
    fuzzy: Optional[float] = None
    min_volume: Optional[float] = None
    ignore: Optional[list[list[str]]] = None


class ViewBody(BaseModel):
    name: str


class StepBody(BaseModel):
    name: Optional[str] = None
    comps: Optional[list[str]] = None
    dir: Optional[Any] = None
    dist: Optional[float] = None
    index: Optional[int] = None


class MoveBody(BaseModel):
    index: int


class AutoBody(BaseModel):
    save_as: Optional[str] = None


class SettingsBody(BaseModel):
    fuzzy: Optional[float] = None
    clearance: Optional[float] = None
    min_volume: Optional[float] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, S.MateRefused):
        raise HTTPException(409, {"message": err.message, "explanation": err.explanation})
    raise HTTPException(400, str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc)
        except (S.MateRefused, SolidError, ValueError, KeyError) as err:
            _fail(err)
        except CommandFailed as err:
            raise HTTPException(409, str(err))


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except (S.MateRefused, SolidError, ValueError, KeyError) as err:
            _fail(err)


def _mate_key(mid: str):
    return int(mid) if str(mid).isdigit() else mid


@router.get("/{doc_id}/mates")
def list_mates(doc_id: str) -> dict:
    return _read(doc_id, ops.list_mates)


@router.get("/{doc_id}/mates/status")
def mate_status(doc_id: str) -> dict:
    return _read(doc_id, ops.status)


@router.post("/{doc_id}/mates")
def add_mate(doc_id: str, body: MateBody) -> dict:
    return _edit(doc_id, "MATE", lambda doc: ops.add_mate(doc, body.kind, body.refs, body.value, body.opt, body.label, body.force))


@router.patch("/{doc_id}/mates/{mid}")
def edit_mate(doc_id: str, mid: str, body: MateEdit) -> dict:
    return _edit(doc_id, "MATEEDIT", lambda doc: ops.set_mate(doc, _mate_key(mid), body.value, body.opt, body.label, body.suppressed))


@router.delete("/{doc_id}/mates/{mid}")
def delete_mate(doc_id: str, mid: str) -> dict:
    return _edit(doc_id, "MATEDELETE", lambda doc: ops.remove_mates(doc, [_mate_key(mid)]))


@router.post("/{doc_id}/mates/solve")
def solve(doc_id: str) -> dict:
    return _edit(doc_id, "MATESOLVE", ops.resolve_all)


@router.post("/{doc_id}/mates/drag")
def drag(doc_id: str, body: DragBody) -> dict:
    if body.commit:
        return _edit(doc_id, "MATEDRAG", lambda doc: ops.drag(doc, body.component, body.point, body.target, True))
    return _read(doc_id, lambda doc: ops.drag(doc, body.component, body.point, body.target, False))


@router.post("/{doc_id}/mates/{mid}/drive")
def drive(doc_id: str, mid: str, body: DriveBody) -> dict:
    def run(doc):
        return ops.drive(doc, _mate_key(mid), body.value, body.values, body.start, body.end, body.count, body.max_step, body.commit, body.report, body.components)

    return _edit(doc_id, "MATEDRIVE", run) if body.commit else _read(doc_id, run)


@router.get("/{doc_id}/mates/timing")
def solve_timing(doc_id: str, kind: str = "") -> dict:
    doc = _doc(doc_id)
    return timing.read(id(doc.drawing), kind)


@router.post("/{doc_id}/mates/interference")
def interference(doc_id: str, body: InterfereBody) -> dict:
    return _read(doc_id, lambda doc: interf.check(doc, body.clearance, body.fuzzy, body.min_volume, None, body.ignore))


@router.post("/{doc_id}/mates/interference/sweep")
def interference_sweep(doc_id: str, body: SweepBody) -> dict:
    def run(doc):
        rec = S.get(doc.drawing, _mate_key(body.mate))
        if rec is None:
            raise S.MateRefused("There is no mate %s." % body.mate)
        return motion.interference_sweep(doc, rec["id"], body.start, body.end, body.count, body.clearance, body.fuzzy, body.max_step, body.ignore)

    return _read(doc_id, run)


@router.put("/{doc_id}/matesettings")
def mate_settings(doc_id: str, body: SettingsBody) -> dict:
    def run(doc):
        h = S.header(doc.drawing)
        for key in ("fuzzy", "clearance", "min_volume"):
            v = getattr(body, key)
            if v is not None:
                if v < 0:
                    raise S.MateRefused("%s cannot be negative." % key)
                h["settings"][key] = float(v)
        S.save_header(doc.drawing, h)
        return h["settings"]

    return _edit(doc_id, "MATESETTINGS", run)


@router.get("/{doc_id}/mates/explode")
def explode_list(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: explode.listing(doc.drawing))


@router.post("/{doc_id}/mates/explode")
def explode_new(doc_id: str, body: ViewBody) -> dict:
    return _edit(doc_id, "EXPLODE", lambda doc: explode.new_view(doc.drawing, body.name))


@router.post("/{doc_id}/mates/explode/auto")
def explode_auto(doc_id: str, body: AutoBody) -> dict:
    run = lambda doc: explode.suggest(doc, body.save_as)
    return _edit(doc_id, "EXPLODE", run) if body.save_as else _read(doc_id, run)


@router.delete("/{doc_id}/mates/explode/{view}")
def explode_delete(doc_id: str, view: str) -> dict:
    def run(doc):
        explode.delete_view(doc.drawing, view)
        return {"deleted": view}

    return _edit(doc_id, "EXPLODE", run)


@router.put("/{doc_id}/mates/explode/{view}/active")
def explode_active(doc_id: str, view: str) -> dict:
    def run(doc):
        explode.set_active(doc.drawing, view)
        return {"active": view}

    return _edit(doc_id, "EXPLODE", run)


@router.get("/{doc_id}/mates/explode/{view}/pose")
def explode_pose(doc_id: str, view: str, t: Optional[float] = None) -> dict:
    return _read(doc_id, lambda doc: explode.pose(doc.drawing, view, t))


@router.post("/{doc_id}/mates/explode/{view}/steps")
def explode_add_step(doc_id: str, view: str, body: StepBody) -> dict:
    spec = body.model_dump(exclude_none=True)
    index = spec.pop("index", None)
    return _edit(doc_id, "EXPLODE", lambda doc: explode.add_step(doc.drawing, view, spec, index))


@router.patch("/{doc_id}/mates/explode/{view}/steps/{sid}")
def explode_edit_step(doc_id: str, view: str, sid: int, body: StepBody) -> dict:
    spec = body.model_dump(exclude_none=True)
    spec.pop("index", None)
    return _edit(doc_id, "EXPLODE", lambda doc: explode.edit_step(doc.drawing, view, sid, spec))


@router.delete("/{doc_id}/mates/explode/{view}/steps/{sid}")
def explode_remove_step(doc_id: str, view: str, sid: int) -> dict:
    def run(doc):
        explode.remove_step(doc.drawing, view, sid)
        return {"removed": sid}

    return _edit(doc_id, "EXPLODE", run)


@router.post("/{doc_id}/mates/explode/{view}/steps/{sid}/move")
def explode_move_step(doc_id: str, view: str, sid: int, body: MoveBody) -> dict:
    return _edit(doc_id, "EXPLODE", lambda doc: {"steps": explode.move_step(doc.drawing, view, sid, body.index)})
