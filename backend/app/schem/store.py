import copy
import math
import re

from app.schem import symbols
from app.schem.errors import SchemError, need as room

TABLE = "schem"
SETTINGS_ID = "SETTINGS"
DEFAULT_SETTINGS = {"template": "{prefix}{sheet}-{seq:02}", "prefix": "W", "sheet_pitch": 500.0, "grid": 5.0}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,23}$")


def table(d):
    return d.tables.get(TABLE)


def rows(d, kind: str) -> list:
    tbl = table(d)
    out = [copy.deepcopy(r) for r in (tbl.values() if tbl is not None else []) if r.get("kind") == kind]
    return sorted(out, key=lambda r: (len(r["id"]), r["id"]))


def get(d, rid, kind=None):
    tbl = table(d)
    row = tbl.get(str(rid)) if tbl is not None else None
    if row is None or (kind and row.get("kind") != kind):
        return None
    return copy.deepcopy(row)


def need(d, rid, kind: str) -> dict:
    row = get(d, rid, kind)
    if row is None:
        raise SchemError("There is no %s %s." % (kind, rid))
    return row


def settings(d) -> dict:
    row = get(d, SETTINGS_ID, "setting")
    out = dict(DEFAULT_SETTINGS)
    if row:
        out.update({k: row[k] for k in DEFAULT_SETTINGS if k in row})
    return out


def save_settings(d, changes: dict) -> dict:
    cur = settings(d)
    for k, v in (changes or {}).items():
        if k not in DEFAULT_SETTINGS:
            continue
        if k in ("sheet_pitch", "grid"):
            cur[k] = num(v, k, 1.0, 1e5)
        else:
            cur[k] = str(v)[:60]
    check_template(cur["template"])
    d.table_set(TABLE, {"name": SETTINGS_ID, "id": SETTINGS_ID, "kind": "setting", **cur})
    return cur


TOKEN = re.compile(r"\{(prefix|sheet|seq|class|from|to|net)(?::(\d+))?\}")


def check_template(t: str) -> None:
    rest = TOKEN.sub("", t)
    if "{" in rest or "}" in rest:
        raise SchemError("The numbering template uses the tokens {prefix}, {sheet}, {seq}, {class}, {from}, {to} and {net}, each optionally with a width such as {seq:02}.")
    if not TOKEN.search(t):
        raise SchemError("The numbering template needs at least one token such as {seq}.")


def num(v, label, lo=None, hi=None):
    if isinstance(v, bool):
        raise SchemError("%s must be a number." % label)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SchemError("%s must be a number." % label)
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise SchemError("%s is out of range." % label)
    return x


def next_id(d, prefix: str) -> str:
    top = 0
    pat = re.compile(r"^%s(\d+)$" % prefix)
    tbl = table(d)
    for r in (tbl.values() if tbl is not None else []):
        m = pat.match(str(r.get("id", "")))
        if m:
            top = max(top, int(m.group(1)))
    return "%s%d" % (prefix, top + 1)


def clean_pins(raw) -> list:
    out = []
    seen = set()
    for p in raw or []:
        pid = str(p.get("id") if isinstance(p, dict) else "").strip()
        if not pid or len(pid) > 16 or pid in seen:
            raise SchemError("Pins need unique names of up to 16 characters.")
        seen.add(pid)
        out.append({"id": pid, "dx": num(p.get("dx"), "A pin x", -1e4, 1e4), "dy": num(p.get("dy"), "A pin y", -1e4, 1e4)})
    return out


def clean_device(d, raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in (raw or {}).items() if k not in ("id", "kind")})
    kind = str(row.get("type") or row.get("device") or "")
    if kind not in symbols.KINDS:
        raise SchemError("A device kind is one of %s." % ", ".join(symbols.KINDS))
    rot = int(num(row.get("rotation", 0), "The rotation", -360, 360)) % 360
    if rot not in (0, 90, 180, 270):
        raise SchemError("The rotation is 0, 90, 180 or 270 degrees.")
    pin_count = row.get("pin_count")
    if pin_count is not None and not 1 <= int(pin_count) <= 200:
        raise SchemError("A connector has 1 to 200 pins.")
    if isinstance(row.get("pins"), (list, tuple)):
        room(len(row["pins"]), "pins", "Pins on one device")
    if pin_count is not None:
        room(int(pin_count), "pins", "Pins on one device")
    default_pins, _draw = symbols.build(kind, pin_count)
    pins = clean_pins(row["pins"]) if row.get("pins") else default_pins
    if kind == "block" and not pins:
        raise SchemError("A block needs its pins: a list of {id, dx, dy}.")
    refdes = str(row.get("refdes") or "").strip()
    if refdes:
        if not ID_RE.match(refdes):
            raise SchemError("A reference designator starts with a letter and has letters, digits, dot, dash or underscore.")
        for other in rows(d, "device"):
            if other["refdes"].casefold() == refdes.casefold() and other["id"] != row.get("id"):
                raise SchemError("The reference %s is already used." % refdes)
    return {"type": kind, "refdes": refdes, "label": str(row.get("label") or "")[:60], "x": num(row.get("x", 0.0), "x", -1e6, 1e6), "y": num(row.get("y", 0.0), "y", -1e6, 1e6), "rotation": rot, "sheet": int(num(row.get("sheet", 1), "The sheet", 1, 200)), "pins": pins, "pin_count": int(pin_count) if pin_count is not None else None, "part": str(row.get("part") or "")[:80]}


def add_device(d, raw: dict) -> dict:
    room(len(rows(d, "device")) + 1, "devices", "Devices")
    f = clean_device(d, raw)
    rid = next_id(d, "D")
    if not f["refdes"]:
        f["refdes"] = auto_refdes(d, f["type"])
    row = {"name": rid, "id": rid, "kind": "device", **f}
    d.table_set(TABLE, row)
    return copy.deepcopy(row)


def auto_refdes(d, kind: str) -> str:
    pre = symbols.PREFIX[kind]
    used = {r["refdes"].casefold() for r in rows(d, "device")}
    i = 1
    while "%s%d" % (pre, i) in used or ("%s%d" % (pre, i)).casefold() in used:
        i += 1
    return "%s%d" % (pre, i)


def edit_device(d, rid: str, raw: dict) -> dict:
    cur = need(d, rid, "device")
    f = clean_device(d, {**cur, **(raw or {}), "id": rid}, cur)
    removed = {p["id"] for p in cur["pins"]} - {p["id"] for p in f["pins"]}
    for w in rows(d, "wire"):
        for end in ("from", "to"):
            if w[end]["device"] == rid and w[end]["pin"] in removed:
                raise SchemError("Wire %s still uses pin %s." % (w["id"], w[end]["pin"]))
    row = d.modify_record(TABLE, rid)
    row.update(f)
    return copy.deepcopy(row)


def drop_device(d, rid: str) -> None:
    need(d, rid, "device")
    for w in rows(d, "wire"):
        if w["from"]["device"] == rid or w["to"]["device"] == rid:
            raise SchemError("Wire %s is connected to this device; delete the wire first." % w["id"])
    d.table_remove(TABLE, rid)


def endpoint(d, spec, what: str) -> dict:
    if not isinstance(spec, dict):
        raise SchemError("%s is {device, pin}." % what)
    key = str(spec.get("device") or "")
    dev = get(d, key, "device")
    if dev is None:
        dev = next((r for r in rows(d, "device") if r["refdes"].casefold() == key.casefold()), None)
    if dev is None:
        raise SchemError("%s names a device that does not exist." % what)
    pin = str(spec.get("pin") or "")
    if pin not in {p["id"] for p in dev["pins"]}:
        raise SchemError("%s has no pin %s." % (dev["refdes"], pin or "(none given)"))
    return {"device": dev["id"], "pin": pin}


def clean_wire(d, raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in (raw or {}).items() if k not in ("id", "kind")})
    a = endpoint(d, row.get("from"), "from")
    b = endpoint(d, row.get("to"), "to")
    if a == b:
        raise SchemError("A wire joins two different pins.")
    name = str(row.get("wire") or "").strip()
    if name and not ID_RE.match(name):
        raise SchemError("A wire name starts with a letter and has letters, digits, dot, dash or underscore.")
    via = []
    for p in row.get("via") or []:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise SchemError("A waypoint is [x, y].")
        via.append([num(p[0], "A waypoint", -1e6, 1e6), num(p[1], "A waypoint", -1e6, 1e6)])
    return {"from": a, "to": b, "wire": name, "name_auto": bool(row.get("name_auto")), "gauge": str(row.get("gauge") or "")[:16], "colour": str(row.get("colour", row.get("color")) or "")[:24], "signal_class": str(row.get("signal_class") or "")[:24], "net": str(row.get("net") or "")[:40], "sheet": int(num(row.get("sheet", 1), "The sheet", 1, 200)), "via": via, "number": str(row.get("number") or "")[:40], "manual": bool(row.get("manual")), "length": None if row.get("length") in (None, "") else num(row.get("length"), "The length", 0.0, 1e7)}


def incoming(raw: dict) -> dict:
    out = {k: v for k, v in (raw or {}).items() if k != "name"}
    if "name" in (raw or {}):
        out["wire"] = raw["name"]
    return out


def public(row: dict) -> dict:
    out = copy.deepcopy(row)
    if out.get("kind") == "wire":
        out["name"] = out.get("wire", "")
    return out


def add_wire(d, raw: dict) -> dict:
    room(len(rows(d, "wire")) + 1, "wires", "Wires")
    f = clean_wire(d, incoming(raw))
    if f["wire"]:
        unique_name(d, f["wire"], None)
    rid = next_id(d, "WR")
    f["name_auto"] = not f["wire"]
    row = {"name": rid, "id": rid, "kind": "wire", **f}
    d.table_set(TABLE, row)
    return public(row)


def unique_name(d, name: str, own) -> None:
    for w in rows(d, "wire"):
        if w["wire"].casefold() == name.casefold() and w["id"] != own:
            raise SchemError("The wire name %s is already used." % name)


def edit_wire(d, rid: str, raw: dict) -> dict:
    cur = need(d, rid, "wire")
    given = incoming(raw)
    f = clean_wire(d, {**cur, **given}, cur)
    if "wire" in given:
        f["name_auto"] = not f["wire"]
    else:
        f["name_auto"] = cur.get("name_auto", False)
    if f["wire"]:
        unique_name(d, f["wire"], rid)
    if "number" in given and "manual" not in given:
        f["manual"] = bool(f["number"])
    row = d.modify_record(TABLE, rid)
    row.update(f)
    return public(row)


def drop_wire(d, rid: str) -> None:
    need(d, rid, "wire")
    d.table_remove(TABLE, rid)
