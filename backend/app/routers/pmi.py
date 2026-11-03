from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.pmi import geo, store
from app.routers.part import _edit, _read
from app.solid.work import SolidError

router = APIRouter(tags=["pmi"])


class MeasureBody(BaseModel):
    body: int
    dtype: str = "distance"
    refs: list[dict[str, Any]] = []
    refs2: list[dict[str, Any]] = []


def reports_of(doc) -> dict:
    mem = getattr(doc, "pmi_reports", {}) or {}
    notes = ((getattr(doc, "import_notes", {}) or {}).get("extra") or {}).get("pmi")
    return {"write": mem.get("write"), "read": mem.get("read") or notes}


def wrap(fn):
    try:
        return fn()
    except (store.PmiError, SolidError) as err:
        raise HTTPException(400, str(err))


@router.get("/{doc_id}/pmi")
def listing(doc_id: str) -> dict:
    def run(doc):
        d = doc.drawing
        recs = store.items(d)
        return {"items": [geo.describe(d, r) for r in recs[:geo.MAX_DRAWN]], "truncated": len(recs) > geo.MAX_DRAWN, "datums": store.datum_letters(d), "reports": reports_of(doc)}

    return _read(doc_id, lambda doc: wrap(lambda: run(doc)))


@router.post("/{doc_id}/pmi")
def add_item(doc_id: str, body: dict[str, Any]) -> dict:
    def run(doc):
        d = doc.drawing
        rec = store.add(d, body)
        if rec["type"] == "dimension":
            geo.kernel_measure(d, store.body_of(d, rec["body"]), rec["dtype"], rec["refs"], rec["refs2"])
        return geo.describe(d, rec)

    return _edit(doc_id, "PMIADD", lambda doc: wrap(lambda: run(doc)))


@router.patch("/{doc_id}/pmi/{pmi_id}")
def edit_item(doc_id: str, pmi_id: str, body: dict[str, Any]) -> dict:
    def run(doc):
        d = doc.drawing
        rec = store.edit(d, pmi_id, body)
        if rec["type"] == "dimension":
            geo.kernel_measure(d, store.body_of(d, rec["body"]), rec["dtype"], rec["refs"], rec["refs2"])
        return geo.describe(d, rec)

    return _edit(doc_id, "PMIEDIT", lambda doc: wrap(lambda: run(doc)))


@router.delete("/{doc_id}/pmi/{pmi_id}")
def delete_item(doc_id: str, pmi_id: str) -> dict:
    return _edit(doc_id, "PMIDELETE", lambda doc: wrap(lambda: {"removed": store.remove(doc.drawing, pmi_id)["id"]}))


@router.post("/{doc_id}/pmi/measure")
def measure(doc_id: str, body: MeasureBody) -> dict:
    def run(doc):
        m = geo.measure(doc.drawing, body.body, body.dtype, body.refs, body.refs2)
        return {"value": m["value"], "unit": "deg" if body.dtype == "angle" else "document", "from": m["from"], "to": m["to"]}

    return _read(doc_id, lambda doc: wrap(lambda: run(doc)))


@router.get("/{doc_id}/pmi/features/{handle}")
def features(doc_id: str, handle: int) -> dict:
    return _read(doc_id, lambda doc: wrap(lambda: geo.features(doc.drawing, handle)))


@router.get("/{doc_id}/pmi/display")
def display(doc_id: str) -> dict:
    def run(doc):
        drawn, cut = geo.display(doc.drawing)
        return {"items": drawn, "truncated": cut, "limit": geo.MAX_DRAWN}

    return _read(doc_id, lambda doc: wrap(lambda: run(doc)))


@router.get("/{doc_id}/pmi/report")
def report(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: reports_of(doc))
