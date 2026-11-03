import copy
import math
import re

from app.core import guard

SCHEMA = 1
HEADER = "PMI"
MAX_ITEMS = 5000
MACRO_ITEMS = 500
MAX_REFS = 16
MAX_TEXT = 200
TYPES = ("dimension", "tolerance", "datum")
DTYPES = ("distance", "diameter", "radius", "thickness", "angle")
TWO_FEATURE = ("distance", "angle")
CHARS = ("straightness", "flatness", "circularity", "cylindricity", "profile_line", "profile_surface", "parallelism", "perpendicularity", "angularity", "position", "concentricity", "symmetry", "runout", "total_runout")
NEEDS_DATUM = ("parallelism", "perpendicularity", "angularity", "concentricity", "symmetry", "runout", "total_runout")
ZONES = ("none", "diameter", "sphere")
MODIFIERS = ("", "M", "L")
ID_RE = re.compile(r"^M(\d+)$")
LETTER_RE = re.compile(r"^[A-Z]$")


class PmiError(ValueError):
    pass


def blank() -> dict:
    return {"schema": SCHEMA, "next": 1, "items": []}


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    if not isinstance(out.get("items"), list):
        out["items"] = []
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def items(d) -> list:
    return header(d)["items"]


def get(d, pmi_id: str):
    for it in items(d):
        if it.get("id") == pmi_id:
            return it
    return None


def need(d, pmi_id: str) -> dict:
    it = get(d, str(pmi_id or "").upper())
    if it is None:
        raise PmiError("There is no PMI item %s." % pmi_id)
    return it


def number(value, label, low=None, high=None, allow_none=False):
    if value is None and allow_none:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise PmiError("%s needs a number." % label)
    if not math.isfinite(v):
        raise PmiError("%s needs a finite number." % label)
    if low is not None and v < low:
        raise PmiError("%s must be at least %g." % (label, low))
    if high is not None and v > high:
        raise PmiError("%s must be at most %g." % (label, high))
    return v


def body_of(d, handle):
    try:
        ent = d.get(int(handle))
    except (TypeError, ValueError):
        ent = None
    if ent is None or ent.kind != "solidbody":
        raise PmiError("PMI attaches to a solid body; handle %s is not one." % handle)
    return ent


def clean_refs(body, raw, label):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_REFS:
        raise PmiError("%s is a list of at most %d features." % (label, MAX_REFS))
    out = []
    for r in raw:
        if not isinstance(r, dict):
            raise PmiError("Each feature is {kind, pid}.")
        kind = str(r.get("kind", "face")).lower()
        if kind not in ("face", "edge"):
            raise PmiError("A feature is a face or an edge.")
        try:
            pid = int(r.get("pid"))
        except (TypeError, ValueError):
            raise PmiError("A feature needs its persistent id (pid).")
        known = body.face_ids if kind == "face" else body.edge_ids
        if pid not in known:
            raise PmiError("The body has no %s with persistent id %d." % (kind, pid))
        out.append({"kind": kind, "pid": pid})
    return out


def clean_datums(raw):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 3:
        raise PmiError("A frame holds at most three datum letters.")
    out = []
    for x in raw:
        letter = str(x).strip().upper()
        if not LETTER_RE.match(letter):
            raise PmiError("A datum letter is one capital letter, A to Z.")
        if letter in out:
            raise PmiError("A datum letter appears once in a frame.")
        out.append(letter)
    return out


def normal_record(d, data: dict, base: dict | None = None) -> dict:
    rec = copy.deepcopy(base) if base else {}
    rec.update({k: v for k, v in data.items() if k not in ("id", "n")})
    typ = str(rec.get("type", "")).lower()
    if typ not in TYPES:
        raise PmiError("The type is dimension, tolerance or datum.")
    body = body_of(d, rec.get("body"))
    out = {"id": rec.get("id"), "n": rec.get("n"), "type": typ, "body": body.handle}
    out["refs"] = clean_refs(body, rec.get("refs"), "refs")
    out["refs2"] = clean_refs(body, rec.get("refs2"), "refs2")
    if not out["refs"]:
        raise PmiError("Pick at least one face or edge for the item.")
    text = str(rec.get("text") or "")
    if len(text) > MAX_TEXT or any(ord(c) < 32 for c in text):
        raise PmiError("The note is plain text of at most %d characters." % MAX_TEXT)
    off = rec.get("offset") or [0.0, 0.0, 0.0]
    if not isinstance(off, (list, tuple)) or len(off) != 3:
        raise PmiError("The offset is three numbers.")
    out["text"] = text
    out["offset"] = [number(v, "offset", -1e9, 1e9) for v in off]
    if typ == "dimension":
        dtype = str(rec.get("dtype", "distance")).lower()
        if dtype not in DTYPES:
            raise PmiError("A dimension is one of %s." % ", ".join(DTYPES))
        if dtype in TWO_FEATURE and not out["refs2"]:
            raise PmiError("A %s dimension needs two features: pick the second in refs2." % dtype)
        if dtype == "thickness" and not out["refs2"] and len(out["refs"]) < 2:
            raise PmiError("A thickness dimension needs two faces.")
        if dtype in ("diameter", "radius") and out["refs2"]:
            raise PmiError("A %s dimension takes one feature." % dtype)
        out["dtype"] = dtype
        out["value"] = number(rec.get("value"), "The value", 0.0, 1e9, True)
        if out["value"] is not None and out["value"] <= 0:
            raise PmiError("The value must be above zero; leave it empty to use the measured value.")
        out["plus"] = number(rec.get("plus", 0.0) or 0.0, "The plus tolerance", 0.0, 1e6)
        out["minus"] = number(rec.get("minus", 0.0) or 0.0, "The minus tolerance", 0.0, 1e6)
    elif typ == "tolerance":
        char = str(rec.get("char", "")).lower()
        if char not in CHARS:
            raise PmiError("A tolerance is one of %s." % ", ".join(CHARS))
        out["char"] = char
        out["tol"] = number(rec.get("tol"), "The tolerance zone width", 0.0, 1e6)
        if out["tol"] <= 0:
            raise PmiError("The tolerance zone width must be above zero.")
        zone = str(rec.get("zone", "none") or "none").lower()
        if zone not in ZONES:
            raise PmiError("The zone is none, diameter or sphere.")
        mod = str(rec.get("modifier", "") or "").upper()
        if mod not in MODIFIERS:
            raise PmiError("The modifier is empty, M or L.")
        out["zone"], out["modifier"] = zone, mod
        out["datums"] = clean_datums(rec.get("datums"))
        if char in NEEDS_DATUM and not out["datums"]:
            raise PmiError("%s needs at least one datum letter." % char.replace("_", " ").capitalize())
    else:
        letter = str(rec.get("letter", "")).strip().upper()
        if not LETTER_RE.match(letter):
            raise PmiError("A datum letter is one capital letter, A to Z.")
        out["letter"] = letter
        out["refs2"] = []
        if len(out["refs"]) != 1:
            out["refs"] = out["refs"][:1]
        for other in items(d):
            if other.get("type") == "datum" and other.get("body") == out["body"] and other.get("letter") == letter and other.get("id") != out["id"]:
                raise PmiError("Datum %s already exists on this body (%s)." % (letter, other["id"]))
    return out


def add(d, data: dict) -> dict:
    h = header(d)
    cap = MACRO_ITEMS if guard.CALLER.get() else MAX_ITEMS
    if len(h["items"]) >= cap:
        raise PmiError("The document holds the most PMI items this caller may add (%d)." % cap)
    rec = normal_record(d, data)
    n = int(h["next"])
    rec["n"], rec["id"] = n, "M%d" % n
    h["next"] = n + 1
    h["items"].append(rec)
    save(d, h)
    return rec


def edit(d, pmi_id: str, fields: dict) -> dict:
    h = header(d)
    cur = None
    for i, it in enumerate(h["items"]):
        if it.get("id") == str(pmi_id).upper():
            cur = i
            break
    if cur is None:
        raise PmiError("There is no PMI item %s." % pmi_id)
    base = h["items"][cur]
    fields = {k: v for k, v in fields.items() if k not in ("type", "body", "id", "n")}
    rec = normal_record(d, fields, base)
    rec["id"], rec["n"] = base["id"], base["n"]
    if base["type"] == "datum" and rec["letter"] != base["letter"]:
        for it in h["items"]:
            if it.get("type") == "tolerance" and it.get("body") == base["body"]:
                it["datums"] = [rec["letter"] if x == base["letter"] else x for x in it.get("datums", [])]
    h["items"][cur] = rec
    save(d, h)
    return rec


def remove(d, pmi_id: str) -> dict:
    h = header(d)
    keep, gone = [], None
    for it in h["items"]:
        if it.get("id") == str(pmi_id).upper():
            gone = it
        else:
            keep.append(it)
    if gone is None:
        raise PmiError("There is no PMI item %s." % pmi_id)
    if gone["type"] == "datum":
        still = any(i["type"] == "datum" and i["body"] == gone["body"] and i["letter"] == gone["letter"] for i in keep)
        if not still:
            for it in keep:
                if it["type"] == "tolerance" and it["body"] == gone["body"]:
                    it["datums"] = [x for x in it.get("datums", []) if x != gone["letter"]]
    h["items"] = keep
    save(d, h)
    return gone


def index_of(body, ref):
    known = body.face_ids if ref["kind"] == "face" else body.edge_ids
    try:
        return known.index(int(ref["pid"]))
    except ValueError:
        return None


def state_of(d, rec) -> str:
    try:
        body = body_of(d, rec.get("body"))
    except PmiError:
        return "lost"
    for r in list(rec.get("refs") or []) + list(rec.get("refs2") or []):
        if index_of(body, r) is None:
            return "lost"
    return "ok"


def datum_letters(d, handle=None) -> list:
    out = []
    for it in items(d):
        if it.get("type") == "datum" and (handle is None or it.get("body") == handle):
            out.append(it["letter"])
    return sorted(set(out))


def merge(d, src, handle_map: dict, pid_map: dict) -> int:
    raw = src.header.get(HEADER)
    if not isinstance(raw, dict):
        return 0
    h = header(d)
    added = 0
    for it in raw.get("items") or []:
        nh = handle_map.get(it.get("body"))
        if nh is None or len(h["items"]) >= MAX_ITEMS:
            continue
        rec = copy.deepcopy(it)
        rec["body"] = nh
        ok = True
        for key in ("refs", "refs2"):
            fixed = []
            for r in rec.get(key) or []:
                new = pid_map.get((it["body"], r["kind"], r["pid"]))
                if new is None:
                    ok = False
                    break
                fixed.append({"kind": r["kind"], "pid": new})
            rec[key] = fixed
        if not ok:
            continue
        n = int(h["next"])
        rec["n"], rec["id"] = n, "M%d" % n
        h["next"] = n + 1
        h["items"].append(rec)
        added += 1
    if added:
        save(d, h)
    return added
