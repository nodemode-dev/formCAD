from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.doc.service import DocumentFault, service
from app.gumball import frame as fr
from app.gumball import ops, state
from app.solid.work import SolidError

router = APIRouter(tags=["gumball"])


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (state.GumballError, ops.OpError, fr.FrameError) as err:
        raise HTTPException(400, str(err))
    except SolidError as err:
        raise HTTPException(503 if "kernel" in str(err).lower() else 400, str(err))


@router.get("/{doc_id}/gumball")
def gumball_state(doc_id: str, handles: str = "") -> dict:
    doc = _doc(doc_id)
    wanted = [int(h) for h in handles.split(",") if h.strip().isdigit()] if handles else None
    return _guard(state.describe, doc, wanted)


class OnIn(BaseModel):
    on: bool = True


@router.post("/{doc_id}/gumball/on")
def gumball_on(doc_id: str, body: OnIn) -> dict:
    return _guard(state.set_on, _doc(doc_id), body.on)


class AlignIn(BaseModel):
    mode: str
    plane: Optional[Any] = None
    object: Optional[int] = None
    face: Optional[int] = None


@router.post("/{doc_id}/gumball/align")
def gumball_align(doc_id: str, body: AlignIn) -> dict:
    return _guard(state.set_align, _doc(doc_id), body.mode, body.plane, body.object, body.face)


class RelocateIn(BaseModel):
    point: Optional[list] = None
    ray: Optional[Any] = None
    aperture: Optional[float] = None
    modes: Optional[list] = None
    base: Optional[list] = None
    plane: Optional[Any] = None
    handles: Optional[list] = None


@router.post("/{doc_id}/gumball/relocate")
def gumball_relocate(doc_id: str, body: RelocateIn) -> dict:
    return _guard(state.relocate, _doc(doc_id), body.point, body.ray, body.aperture, body.modes, body.base, body.plane, body.handles)


@router.post("/{doc_id}/gumball/reset")
def gumball_reset(doc_id: str) -> dict:
    return _guard(state.reset, _doc(doc_id))


class ApplyIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Any
    handles: Optional[list] = None
    copy_: bool = Field(False, alias="copy")
    preview: bool = False


@router.post("/{doc_id}/gumball/apply")
def gumball_apply(doc_id: str, body: ApplyIn) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rn = doc.get_runner()
        if rn.run is not None:
            raise HTTPException(409, "Finish or cancel the running command first.")
        if body.preview:
            import numpy as np

            def preview():
                picked = state.selection_handles(doc, body.handles)
                desc = state.describe(doc, picked)
                if desc["origin"] is None:
                    raise ops.OpError("The selection has no geometry to transform.")
                ops.check_op(body.op)
                aff = fr.build(body.op, desc["axes"], np.asarray(desc["origin"], dtype=np.float64))
                return {"matrix": aff.rows12(), "kind": aff.kind, "origin": desc["origin"], "count": len(picked)}

            return _guard(preview)
        label = "Gumball %s" % (body.op.get("type", "") if isinstance(body.op, dict) else "")
        try:
            with doc.transaction(label.strip()):
                out = ops.apply(doc, body.op, body.handles, bool(body.copy_))
        except (ops.OpError, state.GumballError, fr.FrameError) as err:
            raise HTTPException(400, str(err))
        except SolidError as err:
            raise HTTPException(503 if "kernel" in str(err).lower() else 400, str(err))
        out["rev"] = doc.rev
        out["gumball"] = state.describe(doc, body.handles)
        return out
