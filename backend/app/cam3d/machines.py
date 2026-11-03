import json
import os
import re

from app.cam.limits import CamError
from app.cam3d import kinematics
from app.core import config

SHIPPED = {kinematics.DEFAULT["id"]: kinematics.DEFAULT}
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def folder() -> str:
    d = config.data_dir() / "cam" / "machines"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def clean(rec: dict) -> dict:
    if not isinstance(rec, dict):
        raise CamError("A machine model is an object.")
    out = json.loads(json.dumps(kinematics.DEFAULT))
    for key in ("id", "name", "kind", "version"):
        if key in rec:
            out[key] = rec[key]
    if out["kind"] != "table_table":
        raise CamError("Only the table-table machine kind is available.")
    if not ID.match(str(out["id"])):
        raise CamError("The machine id uses lower case letters, digits, dash and underscore, up to 48 characters.")

    def num(v, lo, hi, what):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= float(v) <= hi:
            raise CamError("%s must be a number between %g and %g." % (what, lo, hi))
        return float(v)

    for ax in ("a", "c"):
        r = rec.get(ax) or {}
        lo = num(r.get("min", out[ax]["min"]), -1e6, 1e6, "%s minimum" % ax.upper())
        hi = num(r.get("max", out[ax]["max"]), -1e6, 1e6, "%s maximum" % ax.upper())
        if hi <= lo:
            raise CamError("%s maximum must be above its minimum." % ax.upper())
        out[ax] = {"min": lo, "max": hi}
    piv = rec.get("pivot", out["pivot"])
    if not isinstance(piv, list) or len(piv) != 3:
        raise CamError("The pivot is three numbers.")
    out["pivot"] = [num(v, -1e5, 1e5, "Pivot") for v in piv]
    off = rec.get("offset") or {}
    out["offset"] = {"dy": num(off.get("dy", 0.0), -1e4, 1e4, "Offset dy"), "dz": num(off.get("dz", 0.0), -1e4, 1e4, "Offset dz")}
    tr = rec.get("travel") or {}
    out["travel"] = {}
    for ax in ("x", "y", "z"):
        r = tr.get(ax, kinematics.DEFAULT["travel"][ax])
        if not isinstance(r, list) or len(r) != 2:
            raise CamError("Travel %s is two numbers." % ax)
        lo, hi = num(r[0], -1e5, 1e5, "Travel"), num(r[1], -1e5, 1e5, "Travel")
        if hi <= lo:
            raise CamError("Travel %s maximum must be above its minimum." % ax)
        out["travel"][ax] = [lo, hi]
    tb = rec.get("table") or {}
    out["table"] = {"radius": num(tb.get("radius", 150.0), 1.0, 1e4, "Table radius"), "thickness": num(tb.get("thickness", 40.0), 0.0, 1e4, "Table thickness")}
    hd = rec.get("head") or {}
    out["head"] = {"radius": num(hd.get("radius", 60.0), 1.0, 1e4, "Head radius"), "length": num(hd.get("length", 120.0), 1.0, 1e4, "Head length")}
    for key, lo, hi in (("rapid", 1.0, 1e6), ("accel", 1.0, 1e6), ("tool_change_s", 0.0, 600.0), ("rotary_feed_max", 1.0, 1e6)):
        out[key] = num(rec.get(key, out[key]), lo, hi, key)
    out["name"] = str(out["name"])[:80]
    return out


def user_path(mid: str) -> str:
    return os.path.join(folder(), mid + ".json")


def listing() -> list:
    rows = [{"id": k, "name": v["name"], "kind": v["kind"], "shipped": True} for k, v in SHIPPED.items()]
    for name in sorted(os.listdir(folder())):
        if not name.endswith(".json"):
            continue
        mid = name[:-5]
        if mid in SHIPPED:
            continue
        try:
            rec = get(mid)
        except CamError:
            continue
        rows.append({"id": mid, "name": rec["name"], "kind": rec["kind"], "shipped": False})
    return rows


def get(mid: str) -> dict:
    if mid in SHIPPED:
        return json.loads(json.dumps(SHIPPED[mid]))
    if not ID.match(str(mid)):
        raise KeyError("There is no machine model %s." % mid)
    path = user_path(mid)
    if not os.path.isfile(path):
        raise KeyError("There is no machine model %s." % mid)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        raise CamError("The machine model %s cannot be read." % mid)
    rec["id"] = mid
    return clean(rec)


def save(mid: str, rec: dict) -> dict:
    if mid in SHIPPED:
        raise CamError("The shipped machine %s cannot be changed; save a copy under another id." % mid)
    rec = dict(rec)
    rec["id"] = mid
    out = clean(rec)
    path = user_path(mid)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    os.replace(tmp, path)
    return out


def remove(mid: str) -> None:
    if mid in SHIPPED:
        raise CamError("The shipped machine %s cannot be deleted." % mid)
    if not ID.match(str(mid)) or not os.path.isfile(user_path(mid)):
        raise KeyError("There is no machine model %s." % mid)
    os.remove(user_path(mid))
