import copy

from app.additive import placement
from app.additive import settings as cfg
from app.core import guard

SCHEMA = 1
HEADER = "ADDITIVE"
MAX_PROFILES = 64
MAX_PLATES = 32
MACRO_PLATES = 8
MAX_ITEMS = 64
MACRO_ITEMS = 16
MAX_NAME = 80


class AdditiveRecordError(ValueError):
    pass


def blank() -> dict:
    return {"schema": SCHEMA, "next": 1, "profiles": [], "plates": []}


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    for key in ("profiles", "plates"):
        if not isinstance(out.get(key), list):
            out[key] = []
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def mint(h: dict, prefix: str) -> str:
    n = int(h.get("next", 1))
    h["next"] = n + 1
    return "%s%d" % (prefix, n)


def name_of(value, fallback: str) -> str:
    text = str(value if value is not None else "").strip()[:MAX_NAME]
    return text or fallback


def find(h: dict, kind: str, rid: str):
    for rec in h[kind]:
        if rec.get("id") == str(rid or "").upper():
            return rec
    return None


def need(h: dict, kind: str, rid: str) -> dict:
    rec = find(h, kind, rid)
    if rec is None:
        raise AdditiveRecordError("There is no %s %s." % ("profile" if kind == "profiles" else "plate", rid))
    return rec


def add_profile(d, body: dict) -> dict:
    h = header(d)
    if len(h["profiles"]) >= MAX_PROFILES:
        raise AdditiveRecordError("A document holds at most %d printer profiles." % MAX_PROFILES)
    name = str(body.get("preset") or "standard")
    base = cfg.preset(name) if name in cfg.PRESETS else cfg.preset("standard")
    try:
        settings = cfg.clean(body.get("settings") or {}, base)
    except cfg.SettingError as err:
        raise AdditiveRecordError(str(err))
    rec = {"id": mint(h, "P"), "name": name_of(body.get("name"), "Profile"), "preset": name if name in cfg.PRESETS else "standard", "settings": settings}
    h["profiles"].append(rec)
    save(d, h)
    return rec


def edit_profile(d, pid: str, body: dict) -> dict:
    h = header(d)
    rec = need(h, "profiles", pid)
    if "name" in body:
        rec["name"] = name_of(body["name"], rec["name"])
    if "settings" in body:
        try:
            rec["settings"] = cfg.clean(body["settings"] or {}, rec["settings"])
        except cfg.SettingError as err:
            raise AdditiveRecordError(str(err))
    save(d, h)
    return rec


def remove_profile(d, pid: str) -> dict:
    h = header(d)
    rec = need(h, "profiles", pid)
    if any(p.get("profile") == rec["id"] for p in h["plates"]):
        raise AdditiveRecordError("A plate still uses that profile.")
    h["profiles"].remove(rec)
    save(d, h)
    return rec


def clean_items(items, limit: int) -> list:
    if not isinstance(items, list):
        raise AdditiveRecordError("Items is a list.")
    if len(items) > limit:
        raise AdditiveRecordError("A plate holds at most %d items here." % limit)
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise AdditiveRecordError("An item is an object.")
        try:
            body = int(it.get("body"))
            orient = it.get("orient")
            if orient is not None:
                placement.rotation_of(orient)
                orient = [float(x) for x in orient]
            row = {"body": body, "orient": orient, "rot_z": float(it.get("rot_z", 0.0) or 0.0), "x": float(it.get("x", 0.0) or 0.0), "y": float(it.get("y", 0.0) or 0.0), "lift": float(it.get("lift", 0.0) or 0.0)}
        except (TypeError, ValueError, placement.PlacementError) as err:
            raise AdditiveRecordError(str(err) if isinstance(err, placement.PlacementError) else "An item needs a body handle and numbers.")
        for k in ("rot_z", "x", "y", "lift"):
            if abs(row[k]) > 1e5 or row[k] != row[k]:
                raise AdditiveRecordError("An item value is out of range.")
        if row["lift"] < 0:
            raise AdditiveRecordError("The lift of an item is zero or more.")
        out.append(row)
    return out


def plate_limits():
    return (MACRO_PLATES, MACRO_ITEMS) if guard.CALLER.get() else (MAX_PLATES, MAX_ITEMS)


def vec2(value, default):
    if value is None:
        return list(default)
    try:
        a = [float(value[0]), float(value[1])]
    except (TypeError, ValueError, IndexError, KeyError):
        raise AdditiveRecordError("A bed size is two numbers.")
    if not all(20.0 <= x <= 2000.0 for x in a):
        raise AdditiveRecordError("A bed side is between 20 and 2000 mm.")
    return a


def add_plate(d, body: dict, items: list) -> dict:
    h = header(d)
    max_plates, max_items = plate_limits()
    if len(h["plates"]) >= max_plates:
        raise AdditiveRecordError("A document holds at most %d plates here." % max_plates)
    if not h["profiles"]:
        add_profile(d, {"name": "Standard", "preset": "standard"})
        h = header(d)
    pid = str(body.get("profile") or h["profiles"][0]["id"]).upper()
    prof = need(h, "profiles", pid)
    bed = vec2(body.get("bed"), prof["settings"]["bed"])
    spacing = float(body.get("spacing", 4.0))
    if not 0.0 <= spacing <= 100.0:
        raise AdditiveRecordError("Spacing is between 0 and 100 mm.")
    rec = {"id": mint(h, "T"), "name": name_of(body.get("name"), "Plate"), "profile": prof["id"], "bed": bed, "spacing": spacing, "metal": bool(body.get("metal", False)), "items": clean_items(items, max_items), "last": None}
    h["plates"].append(rec)
    save(d, h)
    return rec


def edit_plate(d, tid: str, body: dict) -> dict:
    h = header(d)
    rec = need(h, "plates", tid)
    if "name" in body:
        rec["name"] = name_of(body["name"], rec["name"])
    if "profile" in body:
        rec["profile"] = need(h, "profiles", body["profile"])["id"]
    if "bed" in body:
        rec["bed"] = vec2(body["bed"], rec["bed"])
    if "spacing" in body:
        sp = float(body["spacing"])
        if not 0.0 <= sp <= 100.0:
            raise AdditiveRecordError("Spacing is between 0 and 100 mm.")
        rec["spacing"] = sp
    if "metal" in body:
        rec["metal"] = bool(body["metal"])
    if "items" in body:
        rec["items"] = clean_items(body["items"], plate_limits()[1])
    save(d, h)
    return rec


def remove_plate(d, tid: str) -> dict:
    h = header(d)
    rec = need(h, "plates", tid)
    h["plates"].remove(rec)
    save(d, h)
    return rec


def set_last(d, tid: str, last) -> None:
    h = header(d)
    rec = need(h, "plates", tid)
    rec["last"] = last
    save(d, h)
