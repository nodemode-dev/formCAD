from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.param import infer, marks, ops, settings
from app.param import sketch as K
from app.param import store as S

router = APIRouter(tags=["constraints"])


class ConstraintBody(BaseModel):
    kind: str
    refs: list[Any]
    expr: Optional[str] = None
    value: Optional[float] = None
    driving: bool = True
    name: Optional[str] = None
    sketch: Optional[str] = None
    force: bool = False


class ParamBody(BaseModel):
    name: str
    expr: str = "0"
    unit: Optional[str] = None
    comment: Optional[str] = None


class ParamEdit(BaseModel):
    expr: Optional[str] = None
    unit: Optional[str] = None
    comment: Optional[str] = None
    new_name: Optional[str] = None
    driving: Optional[bool] = None


class BarBody(BaseModel):
    action: str = "data"
    which: str = "bars"
    handles: list[int] = []


class SettingsBody(BaseModel):
    values: dict[str, Any]


class AutoBody(BaseModel):
    handles: list[int]
    distance_tol: Optional[float] = None
    angle_tol: Optional[float] = None
    types: Optional[list[str]] = None


class SketchBody(BaseModel):
    action: str = "new"
    name: Optional[str] = None
    plane: Any = "XY"
    origin: Optional[list[float]] = None
    handles: list[int] = []
    flag: bool = True
    new: Optional[str] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc)
        except ops.Refused as err:
            raise HTTPException(409, {"message": err.message, "explanation": err.explanation})
        except S.ParamError as err:
            raise HTTPException(400, str(err))
        except CommandFailed as err:
            raise HTTPException(409, str(err))
        except ValueError as err:
            raise HTTPException(400, str(err))


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except S.ParamError as err:
            raise HTTPException(400, str(err))


@router.get("/{doc_id}/constraints")
def list_constraints(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"constraints": S.constraints(doc.drawing), "settings": S.settings(doc.drawing)})


@router.post("/{doc_id}/constraints")
def add_constraint(doc_id: str, body: ConstraintBody) -> dict:
    return _edit(doc_id, "CONSTRAINT", lambda doc: ops.add_constraint(doc.drawing, body.kind.lower(), body.refs, body.expr, body.value, body.driving, body.name, body.sketch, body.force))


@router.delete("/{doc_id}/constraints/{cid}")
def delete_constraint(doc_id: str, cid: int) -> dict:
    return _edit(doc_id, "DELCONSTRAINT", lambda doc: ops.remove_constraints(doc.drawing, [cid]))


@router.get("/{doc_id}/constraintstatus")
def constraint_status(doc_id: str, sketch: str = "") -> dict:
    return _read(doc_id, lambda doc: ops.status(doc.drawing, sketch or None))


@router.get("/{doc_id}/constraintbar")
def constraint_bar(doc_id: str) -> dict:
    def build(doc):
        data = marks.compute(doc)
        return {"glyphs": {str(h): v for h, v in data["glyphs"].items()}, "dims": {str(h): v for h, v in data["dims"].items()}, "status": {str(h): v for h, v in data["status"].items()}, "sketch": {str(h): v for h, v in data["sketch"].items()}, "settings": S.settings(doc.drawing)}

    return _read(doc_id, build)


@router.put("/{doc_id}/constraintbar")
def set_bar(doc_id: str, body: BarBody) -> dict:
    act = body.action.lower()
    which = "dims" if body.which.lower().startswith("dim") else "bars"

    def run(doc):
        if act in ("show", "hide"):
            return {"settings": settings.show_hide(doc.drawing, which, body.handles, act == "show")}
        if act in ("showall", "hideall"):
            return {"settings": settings.show_all(doc.drawing, which, act == "showall")}
        raise S.ParamError("Unknown option.")

    return _edit(doc_id, "CONSTRAINTBAR", run)


@router.get("/{doc_id}/constraintsettings")
def get_settings(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"settings": S.settings(doc.drawing)})


@router.put("/{doc_id}/constraintsettings")
def put_settings(doc_id: str, body: SettingsBody) -> dict:
    return _edit(doc_id, "CONSTRAINTSETTINGS", lambda doc: {"settings": settings.update(doc.drawing, body.values)})


@router.post("/{doc_id}/autoconstrain")
def auto(doc_id: str, body: AutoBody) -> dict:
    return _edit(doc_id, "AUTOCONSTRAIN", lambda doc: infer.autoconstrain(doc.drawing, body.handles, body.distance_tol, body.angle_tol, body.types))


@router.get("/{doc_id}/parameters")
def get_parameters(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: ops.listing(doc.drawing))


@router.post("/{doc_id}/parameters")
def new_parameter(doc_id: str, body: ParamBody) -> dict:
    return _edit(doc_id, "PARAMETERS", lambda doc: ops.set_parameter(doc.drawing, body.name, body.expr, body.unit, body.comment))


@router.put("/{doc_id}/parameters/{name}")
def edit_parameter(doc_id: str, name: str, body: ParamEdit) -> dict:
    def run(doc):
        d = doc.drawing
        out = {}
        cur = name
        if body.new_name and body.new_name != name:
            out = ops.rename_parameter(d, name, body.new_name)
            cur = body.new_name
        if body.driving is not None:
            out = ops.set_driving(d, cur, body.driving)
        if body.expr is not None or body.unit is not None or body.comment is not None:
            if body.expr is None:
                prm = next((p for p in S.user_params(d) if p["name"].casefold() == cur.casefold()), None)
                if prm is None:
                    raise S.ParamError("There is no parameter named %s." % cur)
                body.expr = prm["expr"]
            out = ops.set_parameter(d, cur, body.expr, body.unit, body.comment)
        return out

    return _edit(doc_id, "PARAMETERS", run)


@router.delete("/{doc_id}/parameters/{name}")
def remove_parameter(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "PARAMETERS", lambda doc: ops.delete_parameter(doc.drawing, name))


@router.get("/{doc_id}/sketches")
def list_sketches(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"sketches": K.listing(doc.drawing)})


@router.get("/{doc_id}/sketches/{name}")
def get_sketch(doc_id: str, name: str) -> dict:
    return _read(doc_id, lambda doc: K.info(doc.drawing, name))


@router.post("/{doc_id}/sketches")
def sketch_action(doc_id: str, body: SketchBody) -> dict:
    a = body.action.lower()

    def run(doc):
        d = doc.drawing
        if a == "new":
            return K.create(d, body.name or "", body.plane, body.handles, body.origin)
        if a == "add":
            return K.add_entities(d, body.name, body.handles)
        if a == "remove":
            return K.remove_entities(d, body.name, body.handles)
        if a == "construction":
            return K.set_construction(d, body.name, body.handles, body.flag)
        if a == "delete":
            return K.delete(d, body.name)
        if a == "rename":
            return K.rename(d, body.name, body.new or "")
        raise S.ParamError("Unknown sketch action.")

    return _edit(doc_id, "SKETCH", run)
