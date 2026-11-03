from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.pcb import drc, jobs, rules, service, store
from app.pcb import zones as Z
from app.pcb.jobs import Cancelled, PcbError
from app.routers.part import _doc, _edit, _read

router = APIRouter(tags=["pcb"])
ERRORS = (PcbError, store.PcbRecordError, rules.RuleError)


class Body(BaseModel):
    model_config = {"extra": "allow"}


class RulesBody(BaseModel):
    profile: Optional[str] = None
    overrides: Optional[dict[str, Any]] = None
    classes: Optional[dict[str, Any]] = None


class RouteBody(BaseModel):
    nets: Optional[list[str]] = None
    mode: str = "unrouted"
    pitch: Optional[float] = None
    width: Optional[float] = None
    via_dia: Optional[float] = None
    via_drill: Optional[float] = None
    via_cost: Optional[float] = None
    passes: Optional[int] = None
    max_rips: Optional[int] = None


class PlaceBody(BaseModel):
    margin: float = 1.0
    refdes: Optional[list[str]] = None


class NetlistBody(BaseModel):
    nets: list[dict[str, Any]]
    parts: list[dict[str, Any]] = []


class PartsBody(BaseModel):
    parts: list[dict[str, Any]]


def wrap(fn):
    try:
        return fn()
    except Cancelled as err:
        raise HTTPException(409, str(err))
    except ERRORS as err:
        raise HTTPException(400, str(err))


def locked() -> bool:
    return jobs.restricted()


def clean(body: BaseModel) -> dict:
    return {k: v for k, v in body.model_dump().items() if v is not None}


@router.get("/{doc_id}/pcb")
def board(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: service.describe(store.header(doc.drawing)))


@router.put("/{doc_id}/pcb/board")
def set_board(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "PCBBOARD", lambda doc: wrap(lambda: store.set_outline(doc.drawing, body.model_dump())))


@router.get("/{doc_id}/pcb/rules")
def rule_profiles(doc_id: str) -> dict:
    def run(doc):
        h = store.header(doc.drawing)
        return dict(rules.describe_profiles(), current=dict(h["rules"], values=rules.effective(h["rules"])))

    return _read(doc_id, run)


@router.put("/{doc_id}/pcb/rules")
def set_rules(doc_id: str, body: RulesBody) -> dict:
    return _edit(doc_id, "PCBRULES", lambda doc: wrap(lambda: store.set_rules(doc.drawing, clean(body))))


@router.post("/{doc_id}/pcb/netlist")
def set_netlist(doc_id: str, body: NetlistBody) -> dict:
    return _edit(doc_id, "PCBNETLIST", lambda doc: wrap(lambda: store.set_netlist(doc.drawing, body.model_dump())))


@router.post("/{doc_id}/pcb/sync")
def sync(doc_id: str, body: Optional[PlaceBody] = None) -> dict:
    margin = body.margin if body else 1.0
    return _edit(doc_id, "PCBSYNC", lambda doc: wrap(lambda: service.sync_ecad(doc.drawing, True, margin)))


@router.post("/{doc_id}/pcb/place")
def place(doc_id: str, body: Optional[PlaceBody] = None) -> dict:
    body = body or PlaceBody()
    only = set(body.refdes) if body.refdes else None
    return _edit(doc_id, "PCBPLACE", lambda doc: wrap(lambda: service.auto_place(doc.drawing, only, body.margin)))


@router.post("/{doc_id}/pcb/parts")
def add_part(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "PCBPART", lambda doc: wrap(lambda: store.place_part(doc.drawing, body.model_dump(), locked())))


@router.patch("/{doc_id}/pcb/parts/{refdes}")
def edit_part(doc_id: str, refdes: str, body: Body) -> dict:
    return _edit(doc_id, "PCBPART", lambda doc: wrap(lambda: store.edit_part(doc.drawing, refdes, body.model_dump())))


@router.delete("/{doc_id}/pcb/parts/{refdes}")
def delete_part(doc_id: str, refdes: str) -> dict:
    return _edit(doc_id, "PCBPART", lambda doc: wrap(lambda: {"removed": store.remove_part(doc.drawing, refdes)["refdes"]}))


@router.post("/{doc_id}/pcb/tracks")
def add_track(doc_id: str, body: Body) -> dict:
    data = body.model_dump()

    def run(doc):
        if "points" in data:
            return {"tracks": store.add_polyline(doc.drawing, data, locked())}
        return store.add_track(doc.drawing, data, locked())

    return _edit(doc_id, "PCBTRACK", lambda doc: wrap(lambda: run(doc)))


@router.patch("/{doc_id}/pcb/tracks/{tid}")
def edit_track(doc_id: str, tid: str, body: Body) -> dict:
    return _edit(doc_id, "PCBTRACK", lambda doc: wrap(lambda: store.edit_track(doc.drawing, tid, body.model_dump())))


@router.delete("/{doc_id}/pcb/tracks/{tid}")
def delete_track(doc_id: str, tid: str) -> dict:
    return _edit(doc_id, "PCBTRACK", lambda doc: wrap(lambda: {"removed": store.remove_record(doc.drawing, "tracks", tid)["id"]}))


@router.post("/{doc_id}/pcb/vias")
def add_via(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "PCBVIA", lambda doc: wrap(lambda: store.add_via(doc.drawing, body.model_dump(), locked())))


@router.patch("/{doc_id}/pcb/vias/{vid}")
def edit_via(doc_id: str, vid: str, body: Body) -> dict:
    return _edit(doc_id, "PCBVIA", lambda doc: wrap(lambda: store.edit_via(doc.drawing, vid, body.model_dump())))


@router.delete("/{doc_id}/pcb/vias/{vid}")
def delete_via(doc_id: str, vid: str) -> dict:
    return _edit(doc_id, "PCBVIA", lambda doc: wrap(lambda: {"removed": store.remove_record(doc.drawing, "vias", vid)["id"]}))


@router.post("/{doc_id}/pcb/zones")
def add_zone(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "PCBZONE", lambda doc: wrap(lambda: store.add_zone(doc.drawing, body.model_dump(), locked())))


@router.patch("/{doc_id}/pcb/zones/{zid}")
def edit_zone(doc_id: str, zid: str, body: Body) -> dict:
    return _edit(doc_id, "PCBZONE", lambda doc: wrap(lambda: store.edit_zone(doc.drawing, zid, body.model_dump())))


@router.delete("/{doc_id}/pcb/zones/{zid}")
def delete_zone(doc_id: str, zid: str) -> dict:
    return _edit(doc_id, "PCBZONE", lambda doc: wrap(lambda: {"removed": store.remove_record(doc.drawing, "zones", zid)["id"]}))


@router.post("/{doc_id}/pcb/keepouts")
def add_keepout(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "PCBKEEPOUT", lambda doc: wrap(lambda: store.add_keepout(doc.drawing, body.model_dump(), locked())))


@router.patch("/{doc_id}/pcb/keepouts/{kid}")
def edit_keepout(doc_id: str, kid: str, body: Body) -> dict:
    return _edit(doc_id, "PCBKEEPOUT", lambda doc: wrap(lambda: store.edit_keepout(doc.drawing, kid, body.model_dump())))


@router.delete("/{doc_id}/pcb/keepouts/{kid}")
def delete_keepout(doc_id: str, kid: str) -> dict:
    return _edit(doc_id, "PCBKEEPOUT", lambda doc: wrap(lambda: {"removed": store.remove_record(doc.drawing, "keepouts", kid)["id"]}))


@router.post("/{doc_id}/pcb/holes")
def add_hole(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "PCBHOLE", lambda doc: wrap(lambda: store.add_hole(doc.drawing, body.model_dump(), locked())))


@router.delete("/{doc_id}/pcb/holes/{hid}")
def delete_hole(doc_id: str, hid: str) -> dict:
    return _edit(doc_id, "PCBHOLE", lambda doc: wrap(lambda: {"removed": store.remove_record(doc.drawing, "holes", hid)["id"]}))


@router.delete("/{doc_id}/pcb/nets/{net}/copper")
def unroute(doc_id: str, net: str) -> dict:
    return _edit(doc_id, "PCBUNROUTE", lambda doc: wrap(lambda: store.remove_net_copper(doc.drawing, net)))


@router.get("/{doc_id}/pcb/zones/fill")
def zone_fill(doc_id: str) -> dict:
    def run(doc):
        h = store.header(doc.drawing)
        fills = Z.fill_all(h)
        return {"fills": fills, "areas": {f["id"]: round(Z.fill_area(f), 3) for f in fills}}

    return _read(doc_id, lambda doc: wrap(lambda: run(doc)))


@router.get("/{doc_id}/pcb/ratsnest")
def ratsnest(doc_id: str) -> dict:
    def run(doc):
        h = store.header(doc.drawing)
        fills = Z.fill_all(h) if h["zones"] else []
        return {"ratsnest": drc.ratsnest(h, fills)}

    return _read(doc_id, lambda doc: wrap(lambda: run(doc)))


def drc_run(doc_id: str, save: bool) -> dict:
    doc = _doc(doc_id)

    def run():
        with doc.lock:
            h = store.header(doc.drawing)
        with jobs.activity(doc_id, "drc") as act:
            return drc.run(h, act)

    res = wrap(run)
    if save:
        summary = {"errors": res["errors"], "warnings": res["warnings"], "passed": res["passed"], "counts": res["counts"], "profile": res["profile"]}
        _edit(doc_id, "PCBDRC", lambda d: store.set_last(d.drawing, "drc", summary))
    return res


@router.get("/{doc_id}/pcb/drc")
def drc_get(doc_id: str) -> dict:
    return drc_run(doc_id, False)


@router.post("/{doc_id}/pcb/drc")
def drc_post(doc_id: str) -> dict:
    return drc_run(doc_id, True)


@router.post("/{doc_id}/pcb/route")
def autoroute(doc_id: str, body: Optional[RouteBody] = None) -> dict:
    body = body or RouteBody()
    doc = _doc(doc_id)
    opts = clean(body)
    if body.mode not in ("unrouted", "all"):
        raise HTTPException(400, "Mode is unrouted or all.")

    def run():
        with doc.lock:
            h = store.header(doc.drawing)
            before = service.snapshot_key(h)
        replace = None
        if body.mode == "all":
            replace = set(body.nets) if body.nets else {t["net"] for t in h["tracks"]} | {v["net"] for v in h["vias"]}
            h["tracks"] = [t for t in h["tracks"] if t["net"] not in replace]
            h["vias"] = [v for v in h["vias"] if v["net"] not in replace]
        with jobs.activity(doc_id, "route") as act:
            res = service.route.autoroute(h, act, opts)
        return res, before, replace

    res, before, replace = wrap(run)

    def commit(d):
        if service.snapshot_key(store.header(d.drawing)) != before:
            raise PcbError("The board changed while routing; route again.")
        added = service.commit_routes(d.drawing, res, replace, locked())
        summary = {"nets_total": res["nets_total"], "nets_routed": res["nets_routed"], "failed": res["failed"], "rips": res["rips"], "seconds": res["seconds"], "pitch": res["pitch"], "tracks": added["tracks"], "vias": added["vias"]}
        store.set_last(d.drawing, "route", summary)
        return summary

    summary = _edit(doc_id, "PCBROUTE", lambda d: wrap(lambda: commit(d)))
    return summary


@router.post("/{doc_id}/pcb/cancel")
def cancel(doc_id: str) -> dict:
    _doc(doc_id)
    return {"cancelled": jobs.cancel(doc_id)}


@router.get("/{doc_id}/pcb/activity")
def activity(doc_id: str) -> dict:
    _doc(doc_id)
    return {"running": jobs.running(doc_id), "limits": jobs.limits_view()}
