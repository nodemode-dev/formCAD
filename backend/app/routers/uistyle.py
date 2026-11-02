import json
import math
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dim import regen
from app.dim import vars as DV
from app.doc import hatchfill, patterns
from app.doc.entities import Dimension
from app.doc.service import DocumentFault, service
from app.display.state import make_entry

router = APIRouter(tags=["ui-styles"])

SWATCH_SIDE = 1.0
SWATCH_LIMIT = 480
KINDS = ("linear", "radius", "diameter", "angular")


class DimPreviewBody(BaseModel):
    vars: Optional[dict[str, Any]] = None
    style: Optional[str] = None
    kind: str = "linear"


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _swatch(name: str, fams: list) -> list:
    ring = [[0.0, 0.0], [SWATCH_SIDE, 0.0], [SWATCH_SIDE, SWATCH_SIDE], [0.0, SWATCH_SIDE]]
    segs, _dense = hatchfill.pattern_segments([np.asarray(ring)], fams, 1.0, 0.0, (0.0, 0.0), 1.0, 20000, 2000)
    rows = np.round(np.asarray(segs, dtype=float), 4).tolist()
    if len(rows) > SWATCH_LIMIT:
        step = len(rows) / float(SWATCH_LIMIT)
        rows = [rows[int(i * step)] for i in range(SWATCH_LIMIT)]
    return rows


@router.get("/ui/patterns")
def pattern_swatches() -> dict:
    info = patterns.listing()
    out = []
    for name in list(info["standard"]) + list(info["user"]):
        if patterns.is_solid(name):
            out.append({"name": name, "description": info["descriptions"].get(name, ""), "user": False, "solid": True, "segs": []})
            continue
        _n, fams = patterns.lookup(name)
        out.append({
            "name": name,
            "description": info["descriptions"].get(name, ""),
            "user": name in info["user"],
            "solid": False,
            "segs": _swatch(name, fams or []),
        })
    return {"patterns": out, "side": SWATCH_SIDE}


@router.get("/docs/{doc_id}/ui/hatch/{handle}")
def hatch_fields(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = doc.drawing.get(handle)
        if ent is None or ent.kind != "hatch":
            raise HTTPException(404, "No such hatch.")
        grad = ent.gradient
        return {
            "handle": ent.handle,
            "pattern": ent.pattern,
            "solid": bool(ent.solid),
            "scale": float(ent.pattern_scale),
            "angle": math.degrees(float(ent.pattern_angle)),
            "associative": bool(ent.associative),
            "island": int(ent.style or 0),
            "origin": [float(ent.origin[0]), float(ent.origin[1])],
            "originMode": str(ent.origin_mode),
            "gap": float(ent.gap or 0.0),
            "gradient": grad if isinstance(grad, dict) else None,
            "loops": [{"outer": bool(lp.get("outer", True))} for lp in ent.loops],
        }


def _sample(doc, kind: str, V: dict, rec: str):
    ref = 2.5 if doc.drawing.metric else 0.18
    span = ref * 16.0
    off = ref * 6.0
    e = Dimension(dim_type="linear", style=rec)
    e.layer = "0"
    e.color = 256
    e.overrides = dict(V)
    if kind == "radius" or kind == "diameter":
        r = span * 0.5
        c = [0.0, 0.0, 0.0]
        ang = math.radians(35.0)
        p = [r * math.cos(ang), r * math.sin(ang), 0.0]
        if kind == "diameter":
            far = [-p[0], -p[1], 0.0]
            e.dim_type = "diameter"
            e.def_point = far
            e.p15 = p
            e.text_point = [p[0] + ref * 4.0, p[1] + ref * 4.0, 0.0]
        else:
            e.dim_type = "radius"
            e.def_point = c
            e.p15 = p
            e.text_point = [p[0] + ref * 4.0, p[1] + ref * 4.0, 0.0]
        e.text_moved = True
        return e
    if kind == "angular":
        e.dim_type = "angular"
        e.p13 = [0.0, 0.0, 0.0]
        e.p14 = [span, 0.0, 0.0]
        e.p15 = [0.0, 0.0, 0.0]
        e.p16 = [span * 0.7, span * 0.7, 0.0]
        e.def_point = [span * 0.55, span * 0.3, 0.0]
        return e
    e.p13 = [0.0, 0.0, 0.0]
    e.p14 = [span, 0.0, 0.0]
    e.def_point = [span, off, 0.0]
    e.rotation = 0.0
    return e


@router.post("/docs/{doc_id}/ui/dimstyle-preview")
def dimension_preview(doc_id: str, body: DimPreviewBody) -> dict:
    doc = _doc(doc_id)
    if body.kind not in KINDS:
        raise HTTPException(400, "Kind must be linear, radius, diameter or angular.")
    with doc.lock:
        V = {}
        for k, v in (body.vars or {}).items():
            key = DV.clean_name(k)
            if not DV.known(key):
                continue
            try:
                V[key] = DV.coerce(key, v)
            except (ValueError, TypeError):
                raise HTTPException(400, "Bad value for %s." % key)
        name = body.style or str(doc.drawing.header.get("DIMSTYLE", "Standard"))
        e = _sample(doc, body.kind, V, name)
        try:
            rctx = regen.make_context(doc)
            regen.refresh(doc, e, rctx)
            entry = make_entry(e, rctx, 0, 0)
        except Exception as err:
            raise HTTPException(400, "The sample could not be built: %s" % err)
        if entry is None:
            return {"items": [], "bounds": None}
        item = json.loads(entry.js)
        item["h"] = None
        item["grips"] = []
        return {"items": [item], "bounds": item.get("bounds")}
