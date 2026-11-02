from fastapi import APIRouter, HTTPException

from app.doc.service import DocumentFault, service
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


def _mm(d) -> float:
    from app.solid import surfwork as sw

    return float(sw.scale(d.drawing))
