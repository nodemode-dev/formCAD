import math
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.nurbs3d import grips
from app.nurbs3d.form import FormError, NurbsForm

router = APIRouter(tags=["curves"])


def describe(e, per_span: int) -> dict:
    form = NurbsForm.from_entity(e)
    lo, hi = form.domain()
    return {
        "handle": e.handle,
        "name": getattr(e, "name", ""),
        "degree": e.degree,
        "periodic": bool(e.periodic),
        "domain": [lo, hi],
        "poles": [list(p) for p in e.poles],
        "weights": list(e.weights),
        "knots": list(e.knots),
        "mults": list(e.mults),
        "samples": form.sample(per_span),
        "edit_points": form.edit_points(),
        "audit": getattr(e, "audit", {}),
    }


@router.get("/{doc_id}/curves")
def curves(doc_id: str, per_span: int = 24) -> dict:
    try:
        d = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    per_span = max(2, min(int(per_span), 256))
    out = []
    for e in d.drawing.entities():
        if e.kind != "nurbscurve":
            continue
        try:
            out.append(describe(e, per_span))
        except FormError as err:
            out.append({"handle": e.handle, "error": str(err)})
    return {"curves": out}


class PreviewIn(BaseModel):
    grip: str
    to: list[float]
    per_span: int = 16


@router.post("/{doc_id}/curves/{handle}/preview")
def curve_preview(doc_id: str, handle: int, body: PreviewIn) -> dict:
    try:
        d = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    if len(body.to) < 2 or not all(math.isfinite(v) for v in body.to[:2]):
        raise HTTPException(400, "Give the new position as two finite numbers.")
    with d.lock:
        e = d.drawing.get(handle)
        if e is None or e.kind != "nurbscurve":
            raise HTTPException(404, "No such curve.")
        try:
            held = SimpleNamespace(degree=e.degree, poles=[list(p) for p in e.poles], weights=list(e.weights), knots=list(e.knots), mults=list(e.mults), periodic=bool(e.periodic))
            grips.stretch(held, body.grip, body.to[:2])
            form = NurbsForm.from_entity(held)
            return {"handle": handle, "poles": [list(p) for p in held.poles], "samples": form.sample(max(2, min(int(body.per_span), 64)))}
        except (FormError, ValueError, IndexError) as err:
            raise HTTPException(400, str(err))


@router.get("/{doc_id}/surface-last")
def surface_last(doc_id: str) -> dict:
    try:
        d = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with d.lock:
        mem = d.get_runner().memory
        return {"seq": int(mem.get("surface_seq", 0)), "report": mem.get("surface_report"), "naked": mem.get("surface_naked"), "mm_per_unit": _mm(d)}


@router.get("/{doc_id}/model-tolerance")
def model_tolerance(doc_id: str) -> dict:
    from app.solid import surfwork as sw

    try:
        d = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with d.lock:
        t = sw.model_tolerance(d.drawing)
        return {"absolute_mm": t["tol"], "absolute_units": t["tol_units"], "angular": t["angtol"], "absolute_source": t["absolute_source"], "angular_source": t["angular_source"], "mm_per_unit": _mm(d)}


@router.get("/{doc_id}/surfaces/{handle}/net")
def surface_net(doc_id: str, handle: int) -> dict:
    from app.cmd.commands.surfpoints import net_of
    from app.solid.work import SolidError

    try:
        d = service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    with d.lock:
        e = d.drawing.get(handle)
        if e is None or e.kind != "solidbody":
            raise HTTPException(404, "No such surface.")
        try:
            net = net_of(d.drawing, e)
        except SolidError as err:
            raise HTTPException(409, str(err))
        return {"handle": handle, "name": e.name, "version": int(e.version), "blob": e.blob, **net}


def _mm(d) -> float:
    from app.solid import surfwork as sw

    return float(sw.scale(d.drawing))
