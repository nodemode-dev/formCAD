import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.additive import jobs, pack, service, store
from app.additive import settings as cfg
from app.additive.jobs import AdditiveError, Cancelled
from app.additive.placement import PlacementError
from app.core.outputs import OutputRefused
from app.routers.part import _doc, _edit, _read

router = APIRouter(tags=["additive"])
ERRORS = (AdditiveError, store.AdditiveRecordError, cfg.SettingError, PlacementError, OutputRefused)


class ProfileBody(BaseModel):
    name: Optional[str] = None
    preset: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class PlateBody(BaseModel):
    name: Optional[str] = None
    profile: Optional[str] = None
    bodies: Optional[list[int]] = None
    bed: Optional[list[float]] = None
    spacing: Optional[float] = None
    metal: Optional[bool] = None
    items: Optional[list[dict[str, Any]]] = None


class ArrangeBody(BaseModel):
    spacing: Optional[float] = None
    rotations: Optional[list[float]] = None


class OrientBody(BaseModel):
    bodies: list[int]
    preset: str = "balanced"
    angle: float = 45.0
    top: int = 5
    profile: Optional[str] = None


class ApplyBody(BaseModel):
    bodies: list[int]
    rotation: list[float]


class ExportBody(BaseModel):
    kind: str = "gcode"
    path: str


class PathBody(BaseModel):
    path: str


class ChecksBody(BaseModel):
    min_wall: Optional[float] = None


def wrap(fn):
    try:
        return fn()
    except Cancelled as err:
        raise HTTPException(409, str(err))
    except ERRORS as err:
        raise HTTPException(400, str(err))


def sets(body: PlateBody) -> dict:
    return {k: v for k, v in body.model_dump().items() if v is not None and k != "bodies"}


@router.get("/{doc_id}/additive")
def listing(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: wrap(lambda: service.listing(doc)))


@router.get("/{doc_id}/additive/defaults")
def defaults(doc_id: str) -> dict:
    _doc(doc_id)
    return {"settings": cfg.describe(), "presets": {k: cfg.preset(k) for k in cfg.PRESETS}}


@router.post("/{doc_id}/additive/profiles")
def add_profile(doc_id: str, body: ProfileBody) -> dict:
    return _edit(doc_id, "ADDPROFILE", lambda doc: wrap(lambda: store.add_profile(doc.drawing, body.model_dump())))


@router.patch("/{doc_id}/additive/profiles/{pid}")
def edit_profile(doc_id: str, pid: str, body: ProfileBody) -> dict:
    return _edit(doc_id, "EDITPROFILE", lambda doc: wrap(lambda: store.edit_profile(doc.drawing, pid, {k: v for k, v in body.model_dump().items() if v is not None})))


@router.delete("/{doc_id}/additive/profiles/{pid}")
def delete_profile(doc_id: str, pid: str) -> dict:
    return _edit(doc_id, "DELETEPROFILE", lambda doc: wrap(lambda: {"removed": store.remove_profile(doc.drawing, pid)["id"]}))


def arranged(doc, items, bed, spacing, rotations=None):
    return service.arrange_items(doc, items, bed, spacing, rotations)


@router.post("/{doc_id}/additive/plates")
def add_plate(doc_id: str, body: PlateBody) -> dict:
    def run(doc):
        items = body.items if body.items is not None else service.default_items(doc, body.bodies)
        data = sets(body)
        h = store.header(doc.drawing)
        prof = store.find(h, "profiles", data.get("profile") or (h["profiles"][0]["id"] if h["profiles"] else ""))
        bed = store.vec2(data.get("bed"), prof["settings"]["bed"] if prof else [220.0, 220.0])
        spacing = float(data.get("spacing", 4.0))
        if body.items is None:
            items, _report = arranged(doc, items, bed, spacing)
        rec = store.add_plate(doc.drawing, data, items)
        return service.describe_plate(doc, store.header(doc.drawing), rec)

    return _edit(doc_id, "ADDPLATE", lambda doc: wrap(lambda: run(doc)))


@router.patch("/{doc_id}/additive/plates/{tid}")
def edit_plate(doc_id: str, tid: str, body: PlateBody) -> dict:
    def run(doc):
        rec = store.edit_plate(doc.drawing, tid, sets(body))
        return service.describe_plate(doc, store.header(doc.drawing), rec)

    return _edit(doc_id, "EDITPLATE", lambda doc: wrap(lambda: run(doc)))


@router.delete("/{doc_id}/additive/plates/{tid}")
def delete_plate(doc_id: str, tid: str) -> dict:
    return _edit(doc_id, "DELETEPLATE", lambda doc: wrap(lambda: {"removed": store.remove_plate(doc.drawing, tid)["id"]}))


@router.post("/{doc_id}/additive/plates/{tid}/arrange")
def arrange_plate(doc_id: str, tid: str, body: ArrangeBody) -> dict:
    def run(doc):
        h = store.header(doc.drawing)
        plate = store.need(h, "plates", tid)
        spacing = plate["spacing"] if body.spacing is None else float(body.spacing)
        if not 0.0 <= spacing <= 100.0:
            raise AdditiveError("Spacing is between 0 and 100 mm.")
        items, report = service.arrange_items(doc, plate["items"], plate["bed"], spacing, body.rotations)
        rec = store.edit_plate(doc.drawing, tid, {"items": items, "spacing": spacing})
        return {"plate": service.describe_plate(doc, store.header(doc.drawing), rec), "report": report}

    return _edit(doc_id, "ARRANGEPLATE", lambda doc: wrap(lambda: run(doc)))


@router.post("/{doc_id}/additive/orient")
def orient_study(doc_id: str, body: OrientBody) -> dict:
    doc = _doc(doc_id)

    def run():
        if not body.bodies:
            raise AdditiveError("Give at least one body.")
        if not 10.0 <= body.angle <= 80.0:
            raise AdditiveError("The angle is between 10 and 80 degrees.")
        with doc.lock:
            h = store.header(doc.drawing)
            prof = store.find(h, "profiles", body.profile) if body.profile else (h["profiles"][0] if h["profiles"] else None)
            layer_h = prof["settings"]["layer_height"] if prof else 0.2
        return service.do_orient(doc, body.bodies, body.preset, body.angle, max(1, min(int(body.top), 20)), layer_h, None)

    return wrap(run)


@router.post("/{doc_id}/additive/plates/{tid}/orient")
def apply_orient(doc_id: str, tid: str, body: ApplyBody) -> dict:
    def run(doc):
        h = store.header(doc.drawing)
        plate = json.loads(json.dumps(store.need(h, "plates", tid)))
        service.orient_item(plate, body.bodies, body.rotation)
        items, _report = service.arrange_items(doc, plate["items"], plate["bed"], plate["spacing"])
        rec = store.edit_plate(doc.drawing, tid, {"items": items})
        return service.describe_plate(doc, store.header(doc.drawing), rec)

    return _edit(doc_id, "ORIENTPLATE", lambda doc: wrap(lambda: run(doc)))


@router.post("/{doc_id}/additive/plates/{tid}/slice")
def slice_plate(doc_id: str, tid: str) -> dict:
    doc = _doc(doc_id)

    def job():
        return service.do_slice(doc, tid, None)

    res, last = wrap(job)
    _edit(doc_id, "SLICE", lambda d: store.set_last(d.drawing, tid, last))
    return {"summary": res.summary, "warnings": res.warnings, "hash": res.hash}


@router.get("/{doc_id}/additive/plates/{tid}/layers")
def layers(doc_id: str, tid: str, header: int = 0):
    doc = _doc(doc_id)
    res = wrap(lambda: service.need_result(doc, tid))
    if header:
        return pack.header_of(res.pack)
    return Response(content=res.pack, media_type=pack.MEDIA_TYPE, headers={"Cache-Control": "no-store"})


@router.get("/{doc_id}/additive/plates/{tid}/gcode")
def gcode_text(doc_id: str, tid: str, start: int = 0, count: int = 200) -> dict:
    doc = _doc(doc_id)
    res = wrap(lambda: service.need_result(doc, tid))
    start = max(0, int(start))
    count = max(1, min(int(count), 2000))
    return {"lines": res.lines[start:start + count], "total": len(res.lines), "start": start}


@router.post("/{doc_id}/additive/plates/{tid}/export")
def export_plate(doc_id: str, tid: str, body: ExportBody) -> dict:
    doc = _doc(doc_id)

    def run():
        kind = body.kind.lower()
        if kind not in ("gcode", "3mf"):
            raise AdditiveError("Export kind is gcode or 3mf.")
        with doc.lock:
            h = store.header(doc.drawing)
            plate = json.loads(json.dumps(store.need(h, "plates", tid)))
        if kind == "3mf":
            return service.export_3mf(doc, plate, body.path)
        res = service.result_for(doc.id, plate["id"])
        if res is None or describe_stale(doc, tid):
            res, last = service.do_slice(doc, tid, None)
            _edit(doc_id, "SLICE", lambda d: store.set_last(d.drawing, tid, last))
        return service.export_gcode(res, body.path)

    return wrap(run)


def describe_stale(doc, tid: str) -> bool:
    with doc.lock:
        h = store.header(doc.drawing)
        plate = store.need(h, "plates", tid)
        last = plate.get("last")
        prof = store.find(h, "profiles", plate["profile"])
        return not last or prof is None or last.get("hash") != service.fingerprint(doc, plate, prof)


@router.post("/{doc_id}/additive/plates/{tid}/checks")
def checks_route(doc_id: str, tid: str, body: Optional[ChecksBody] = None) -> dict:
    doc = _doc(doc_id)

    def run():
        with doc.lock:
            h = store.header(doc.drawing)
            plate = json.loads(json.dumps(store.need(h, "plates", tid)))
            prof = json.loads(json.dumps(service.profile_of(h, plate)))
        return {"warnings": service.do_checks(doc, plate, prof, body.min_wall if body else None)}

    return wrap(run)


@router.post("/{doc_id}/additive/cancel")
def cancel(doc_id: str) -> dict:
    _doc(doc_id)
    return {"cancelled": jobs.cancel(doc_id)}


@router.get("/{doc_id}/additive/activity")
def activity(doc_id: str) -> dict:
    _doc(doc_id)
    return {"running": jobs.running(doc_id)}


@router.post("/{doc_id}/additive/import/gcode")
def import_gcode(doc_id: str, body: PathBody) -> dict:
    _doc(doc_id)
    return wrap(lambda: service.import_gcode(body.path))


@router.get("/{doc_id}/additive/previews/{key}/layers")
def preview_layers(doc_id: str, key: str):
    _doc(doc_id)
    data = service.preview(key)
    if data is None:
        raise HTTPException(404, "That preview is no longer held; import the G-code again.")
    return Response(content=data, media_type=pack.MEDIA_TYPE, headers={"Cache-Control": "no-store"})
