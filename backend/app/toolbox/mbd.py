import copy
import math
import re

from app.pmi import geo, store as pmi_store
from app.solid.work import SolidError
from app.toolbox import inspection

SCHEMA = 1
HEADER = "MBD"
MAX_VIEWS = 100
MAX_NAME = 60
ID_RE = re.compile(r"^V(\d+)$")
TYPES = ("dimension", "tolerance", "datum")
CAMERAS = {
    "front": ([0.0, -1.0, 0.0], [0.0, 0.0, 1.0]), "back": ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]),
    "top": ([0.0, 0.0, 1.0], [0.0, 1.0, 0.0]), "bottom": ([0.0, 0.0, -1.0], [0.0, -1.0, 0.0]),
    "left": ([-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]), "right": ([1.0, 0.0, 0.0], [0.0, 0.0, 1.0]),
    "iso": ([1.0, -1.0, 1.0], [0.0, 0.0, 1.0]),
}


class MbdError(ValueError):
    pass


def blank() -> dict:
    return {"schema": SCHEMA, "next": 1, "views": []}


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    if not isinstance(out.get("views"), list):
        out["views"] = []
    if int(out.get("schema", 1)) > SCHEMA:
        raise MbdError("The MBD views were written by a newer FormCAD.")
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def unit(v, what):
    try:
        a = [float(x) for x in v]
    except (TypeError, ValueError):
        raise MbdError("%s is three numbers." % what)
    n = math.sqrt(sum(x * x for x in a)) if len(a) == 3 else 0.0
    if len(a) != 3 or not math.isfinite(n) or n < 1e-9:
        raise MbdError("%s is three numbers that are not all zero." % what)
    return [x / n for x in a]


def camera_of(args: dict) -> dict:
    cam = args.get("camera")
    if isinstance(cam, str):
        if cam.lower() not in CAMERAS:
            raise MbdError("The camera is one of %s or a {dir, up} object." % ", ".join(CAMERAS))
        v, u = CAMERAS[cam.lower()]
        return {"name": cam.lower(), "dir": unit(v, "dir"), "up": unit(u, "up")}
    if isinstance(cam, dict):
        v, u = unit(cam.get("dir"), "The view direction"), unit(cam.get("up") or [0, 0, 1], "The up direction")
        if abs(sum(a * b for a, b in zip(v, u))) > 0.999:
            raise MbdError("The up direction is along the view direction.")
        out = {"name": str(cam.get("name") or "custom")[:30], "dir": v, "up": u}
        if cam.get("target") is not None:
            out["target"] = [float(x) for x in cam["target"][:3]]
        if cam.get("zoom") is not None:
            out["zoom"] = float(cam["zoom"])
        return out
    return {"name": "iso", "dir": unit(CAMERAS["iso"][0], "dir"), "up": unit(CAMERAS["iso"][1], "up")}


def new_name(h: dict, raw, mine=None) -> str:
    n = str(raw or "").strip()
    if not n or len(n) > MAX_NAME:
        raise MbdError("A view name holds 1 to %d characters." % MAX_NAME)
    for v in h["views"]:
        if v["name"].casefold() == n.casefold() and v["id"] != mine:
            raise MbdError("There is already a view called %s." % n)
    return n


def clean_items(d, raw):
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > 5000:
        raise MbdError("items is a list of PMI ids, or null for all.")
    known = {i["id"] for i in pmi_store.items(d)}
    ids = [str(x).upper() for x in raw]
    bad = [i for i in ids if i not in known]
    if bad:
        raise MbdError("There is no PMI item %s." % bad[0])
    return list(dict.fromkeys(ids))


def clean_types(raw):
    if raw is None:
        return list(TYPES)
    t = [str(x).lower() for x in raw] if isinstance(raw, list) else []
    if not t or any(x not in TYPES for x in t):
        raise MbdError("types lists %s." % ", ".join(TYPES))
    return t


def add_view(d, args: dict) -> dict:
    h = header(d)
    if len(h["views"]) >= MAX_VIEWS:
        raise MbdError("At most %d views." % MAX_VIEWS)
    n = h["next"]
    h["next"] = n + 1
    view = {"id": "V%d" % n, "name": new_name(h, args.get("name") or "View %d" % n), "camera": camera_of(args), "items": clean_items(d, args.get("items")), "types": clean_types(args.get("types")), "balloons": bool(args.get("balloons", False)), "note": str(args.get("note") or "")[:200]}
    h["views"].append(view)
    save(d, h)
    return copy.deepcopy(view)


def find(h: dict, ident) -> dict:
    s = str(ident or "").strip()
    for v in h["views"]:
        if v["id"] == s.upper() or v["name"].casefold() == s.casefold():
            return v
    raise MbdError("There is no MBD view %s." % ident)


def edit_view(d, ident, args: dict) -> dict:
    h = header(d)
    v = find(h, ident)
    if "name" in args:
        v["name"] = new_name(h, args["name"], v["id"])
    if "camera" in args:
        v["camera"] = camera_of(args)
    if "items" in args:
        v["items"] = clean_items(d, args["items"])
    if "types" in args:
        v["types"] = clean_types(args["types"])
    if "balloons" in args:
        v["balloons"] = bool(args["balloons"])
    if "note" in args:
        v["note"] = str(args["note"] or "")[:200]
    save(d, h)
    return copy.deepcopy(v)


def remove_view(d, ident) -> dict:
    h = header(d)
    v = find(h, ident)
    h["views"].remove(v)
    save(d, h)
    return {"removed": v["id"]}


def facing(d, view: dict) -> list:
    cam = view["camera"]["dir"]
    keep = []
    cache = {}
    for rec in pmi_store.items(d):
        if pmi_store.state_of(d, rec) != "ok":
            continue
        bid = rec["body"]
        if bid not in cache:
            try:
                cache[bid] = {f["pid"]: f for f in geo.features(d, bid)["faces"]}
            except SolidError:
                cache[bid] = {}
        ok = not rec.get("refs")
        for r in (rec.get("refs") or []) + (rec.get("refs2") or []):
            f = cache[bid].get(r["pid"]) if r["kind"] == "face" else None
            if f is None or f.get("kind") != "plane" or not f.get("direction"):
                ok = True
                break
            if sum(a * b for a, b in zip(f["direction"], cam)) > 0.2:
                ok = True
                break
        if ok:
            keep.append(rec["id"])
    return keep


def assign(d, ident, rule: str = "facing") -> dict:
    h = header(d)
    v = find(h, ident)
    if rule == "all":
        v["items"] = None
    elif rule == "facing":
        v["items"] = facing(d, v)
    else:
        raise MbdError("The rule is facing or all.")
    save(d, h)
    return {"view": v["id"], "items": v["items"], "count": None if v["items"] is None else len(v["items"])}


def display(d, ident) -> dict:
    h = header(d)
    v = find(h, ident)
    drawn, cut = geo.display(d)
    keep = set(v["items"]) if v["items"] is not None else None
    items = [i for i in drawn if (keep is None or i["id"] in keep) and i["type"] in v["types"]]
    out = {"view": copy.deepcopy(v), "items": items, "truncated": cut}
    if v["balloons"]:
        wanted = {i["id"] for i in items}
        out["balloons"] = [b for b in inspection.model_balloons(d) if b["pmi"] in wanted]
    return out


def report(d) -> dict:
    h = header(d)
    recs = pmi_store.items(d)
    letters = set(pmi_store.datum_letters(d))
    shown = {}
    for v in h["views"]:
        ids = {r["id"] for r in recs} if v["items"] is None else set(v["items"])
        for r in recs:
            if r["id"] in ids and r["type"] in v["types"]:
                shown.setdefault(r["id"], []).append(v["id"])
    problems = []
    for r in recs:
        st = pmi_store.state_of(d, r)
        if st != "ok":
            problems.append({"id": r["id"], "code": "state_" + st, "message": "PMI item %s is %s." % (r["id"], st)})
        if r["type"] == "tolerance":
            for ltr in r.get("datums") or []:
                if ltr not in letters:
                    problems.append({"id": r["id"], "code": "datum_missing", "message": "Frame %s refers to datum %s, which is not defined." % (r["id"], ltr)})
        if r["type"] == "dimension" and not (r.get("plus") or r.get("minus")):
            problems.append({"id": r["id"], "code": "no_tolerance", "message": "Dimension %s has no tolerance band." % r["id"]})
        if r["id"] not in shown:
            problems.append({"id": r["id"], "code": "not_in_view", "message": "PMI item %s appears in no saved view." % r["id"]})
    used = {ltr for r in recs if r["type"] == "tolerance" for ltr in (r.get("datums") or [])}
    for ltr in sorted(letters - used):
        problems.append({"id": ltr, "code": "datum_unused", "message": "Datum %s is defined but no frame refers to it." % ltr})
    return {"views": [{"id": v["id"], "name": v["name"], "items": len(recs) if v["items"] is None else len(v["items"]), "camera": v["camera"]["name"]} for v in h["views"]], "pmi_items": len(recs), "shown": len(shown), "problems": problems, "complete": not problems and bool(recs)}


ERRORS = (MbdError, pmi_store.PmiError, SolidError)
