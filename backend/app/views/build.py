import time

from app.doc import layouts
from app.solid import work
from app.views import model, sources
from app.views.model import ViewError

LONG = work.LONG


def layout_of(view) -> str:
    owner = str(view.owner or "")
    return owner[7:] if owner.startswith("layout:") else ""


def unit_mm_of(d, view) -> float:
    name = layout_of(view)
    rec = layouts.find(d, name) if name else None
    if rec is None:
        return 1.0
    return layouts.unit_mm(d, layouts.normalize(d, rec.get("page_setup")))


def worker_params(view, items: list, first: bool) -> dict:
    p = {
        "items": sources.worker_items(items), "normal": list(view.vnormal), "up": list(view.vup), "mode": view.mode,
        "cutover": model.DRAFT_CUTOVER_FACES, "attribute": view.mode != "draft",
    }
    if not first:
        p["origin"] = list(view.origin)
    elif view.origin and any(abs(v) > 0 for v in view.origin):
        p["origin"] = list(view.origin)
    sec = view.section
    if sec and sec.get("points"):
        p["section"] = {"kind": sec.get("kind", "full"), "points": sec["points"], "pnormal": sec["pnormal"], "keep": sec.get("keep")}
    if view.detail and view.detail.get("radius"):
        p["clip"] = {"circle": {"c": [0.0, 0.0], "r": float(view.detail["radius"])}}
    elif view.crop and view.crop.get("polygon"):
        p["clip"] = {"polygon": view.crop["polygon"]}
    if view.broken and view.broken.get("breaks"):
        p["breaks"] = view.broken["breaks"]
    return p


def add_ids(result: dict, items: list) -> None:
    for recs in result["classes"].values():
        for rec in recs:
            s = rec.get("s")
            if not s:
                continue
            i = s[0]
            if i < 0 or i >= len(items):
                continue
            body = items[i].body
            if body is None:
                continue
            ids = list(getattr(body, "edge_ids", []) or [])
            fids = list(getattr(body, "face_ids", []) or [])
            if s[1] and 0 < s[1] <= len(ids):
                rec["pid"] = ids[s[1] - 1]
            if s[2] and 0 < s[2] <= len(fids):
                rec["fpid"] = fids[s[2] - 1]


def compute(doc, view, first: bool = False) -> tuple:
    items = sources.resolve(doc, view.source)
    if len(items) > sources.MAX_ITEMS:
        raise ViewError("There are too many bodies for one view.")
    t0 = time.perf_counter()
    try:
        res = work.kcall("view_build", worker_params(view, items, first), LONG)
    except work.SolidError as err:
        raise ViewError(str(err))
    res["stats"]["round_trip_ms"] = (time.perf_counter() - t0) * 1000.0
    add_ids(res, items)
    return items, res


def store(d, handle: int, items: list, res: dict, rev: int, message: str = "") -> None:
    v = d.modify(handle)
    v.cache = {
        "classes": res["classes"], "faces": res["faces"], "extra": res["extra"], "bounds": res["bounds"], "frame": res["frame"],
        "origin": res["origin"], "model_bbox": res["model_bbox"], "counts": res["counts"], "items": [i.record() for i in items], "breaks": res.get("breaks", []),
    }
    v.origin = [float(c) for c in res["origin"]]
    v.unit_mm = unit_mm_of(d, v)
    v.state = {"status": "ok", "message": message, "sig": sources.signature(items), "ms": round(res["stats"]["round_trip_ms"], 1), "mode_used": res["stats"]["mode"], "built_rev": rev, "stats": res["stats"]}


def fail(d, handle: int, message: str, status: str = "error") -> None:
    v = d.modify(handle)
    st = dict(v.state or {})
    st.update(status=status, message=message)
    v.state = st


def rebuild(doc, handle: int, first: bool = False) -> dict:
    d = doc.drawing
    view = d.ents[handle]
    try:
        items, res = compute(doc, view, first)
    except (ViewError, sources.ViewError) as err:
        fail(d, handle, str(err))
        raise
    except Exception as err:
        fail(d, handle, str(err))
        raise ViewError(str(err))
    store(d, handle, items, res, doc.rev)
    return d.ents[handle].state
