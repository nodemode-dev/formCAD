from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.analysis import combs, ramps, service as an, snaps, spec as spec_mod
from app.doc.service import DocumentFault, service
from app.solid.work import SolidError

router = APIRouter(tags=["analysis"])


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _mem(doc) -> dict:
    return doc.get_runner().memory


@router.get("/{doc_id}/analysis")
def analysis_state(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        mem = _mem(doc)
        return {
            "seq": int(mem.get("analysis_seq", 0)), "spec": mem.get("analysis3d"), "combs": mem.get("combs3d"), "modes": list(spec_mod.MODES),
            "ramps": ramps.all_ramps(doc.drawing), "rev": doc.rev,
        }


def _values(doc, spec, detail: float) -> Response:
    try:
        payload = an.compute(doc, spec, detail)
    except spec_mod.SpecError as err:
        raise HTTPException(400, str(err))
    except SolidError as err:
        raise HTTPException(503, str(err))
    return Response(content=payload, media_type=an.MEDIA_TYPE, headers={"Cache-Control": "no-store", "X-FormCAD-Rev": str(doc.rev)})


@router.get("/{doc_id}/analysis/values")
def analysis_values(doc_id: str, detail: float = 1.0) -> Response:
    doc = _doc(doc_id)
    with doc.lock:
        spec = _mem(doc).get("analysis3d")
    if not spec:
        raise HTTPException(404, "No surface analysis is switched on.")
    return _values(doc, spec, detail)


class ComputeIn(BaseModel):
    spec: Any
    detail: float = 1.0


@router.post("/{doc_id}/analysis/compute")
def analysis_compute(doc_id: str, body: ComputeIn) -> Response:
    return _values(_doc(doc_id), body.spec, body.detail)


@router.get("/{doc_id}/analysis/ramps")
def analysis_ramps(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"ramps": ramps.all_ramps(doc.drawing)}


class CombIn(BaseModel):
    handles: Optional[list] = None
    edges: Optional[list] = None
    per_span: int = 12
    scale: float = 1.0


def _combs(doc, handles, edges, per_span, scale) -> dict:
    try:
        with doc.lock:
            return combs.compute(doc.drawing, handles or [], edges or [], max(8, min(int(per_span), 64)), float(scale))
    except SolidError as err:
        raise HTTPException(503 if "kernel" in str(err).lower() else 400, str(err))


@router.get("/{doc_id}/analysis/combs")
def comb_state(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        held = _mem(doc).get("combs3d")
    if not held:
        raise HTTPException(404, "No curvature comb is switched on.")
    return _combs(doc, held.get("handles"), held.get("edges"), held.get("per_span", 12), held.get("scale", 1.0))


@router.post("/{doc_id}/analysis/combs")
def comb_compute(doc_id: str, body: CombIn) -> dict:
    return _combs(_doc(doc_id), body.handles, body.edges, body.per_span, body.scale)


class PointsIn(BaseModel):
    points: list
    target: int
    faces: Optional[list] = None
    signed: bool = False
    good: Optional[float] = None
    bad: Optional[float] = None


@router.post("/{doc_id}/analysis/points")
def point_deviation(doc_id: str, body: PointsIn) -> dict:
    doc = _doc(doc_id)
    try:
        return an.point_deviation(doc, body.points, body.target, body.faces, body.signed, body.good, body.bad)
    except spec_mod.SpecError as err:
        raise HTTPException(400, str(err))
    except SolidError as err:
        raise HTTPException(503, str(err))


class SnapIn(BaseModel):
    ray: Any
    aperture: float = 1.0
    modes: Optional[list] = None
    base: Optional[list] = None
    plane: Optional[Any] = None
    handles: Optional[list] = None
    limit: int = 60


@router.post("/{doc_id}/snap3d")
def snap3d(doc_id: str, body: SnapIn) -> dict:
    doc = _doc(doc_id)
    try:
        return snaps.query(doc, body.ray, body.aperture, body.modes, body.base, body.plane, body.handles, body.limit)
    except SolidError as err:
        raise HTTPException(503 if "kernel" in str(err).lower() else 400, str(err))
