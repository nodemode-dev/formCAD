from typing import Any

from fastapi import APIRouter, HTTPException

from app.doc.service import DocumentFault, service
from app.drawann import build, glyphs, settings, titleblock

router = APIRouter(tags=["drawann"])


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


@router.get("/{doc_id}/drawann/glyphs")
def get_glyphs(doc_id: str) -> dict:
    _doc(doc_id)
    return {"characteristics": glyphs.listing(), "categories": list(glyphs.CATEGORIES), "modifiers": ["", "M", "L"], "zones": list(glyphs.ZONES), "order": list(settings.ORDER_NAMES)}


@router.get("/{doc_id}/drawann/settings")
def get_settings(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"settings": settings.get(doc.drawing), "defaults": settings.DEFAULTS}


@router.put("/{doc_id}/drawann/settings")
def put_settings(doc_id: str, body: dict[str, Any]) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        runner = doc.get_runner()
        if runner.run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction("GDTSTYLE"):
                cur = settings.put(doc.drawing, body)
        except settings.SettingsError as err:
            raise HTTPException(400, str(err))
        return {"settings": cur}


@router.get("/{doc_id}/drawann/properties")
def get_props(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"properties": titleblock.props(doc.drawing), "statusTerms": list(titleblock.STATUS_TERMS), "fields": [{"tag": t, "property": k, "label": p} for t, k, p in titleblock.FIELDS]}


@router.put("/{doc_id}/drawann/properties")
def put_props(doc_id: str, body: dict[str, Any]) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        runner = doc.get_runner()
        if runner.run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction("DOCPROPS"):
                cur = titleblock.put_props(doc.drawing, body)
        except titleblock.TitleError as err:
            raise HTTPException(400, str(err))
        return {"properties": cur}


@router.get("/{doc_id}/drawann/frame/{handle}")
def get_frame(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        e = doc.drawing.get(handle)
        if e is None or e.kind != "gdtframe":
            raise HTTPException(404, "No such geometric tolerance frame.")
        st = settings.get(doc.drawing)
        _prims, W, H, th = build.frame_layout(e, st)
        info = glyphs.CHARACTERISTICS[glyphs.key_of(e.char)]
        return {"handle": handle, "char": e.char, "name": info["name"], "category": info["category"], "tolerance": e.tolerance, "zone": e.zone, "modifier": e.modifier, "projected": e.projected, "datums": e.datums, "order": e.order or st["gdt_order"], "width": W, "height": H, "textHeight": th}
