import copy
import json
import math
import os
import threading
import uuid

from app.cam.limits import CamError
from app.cam import limits
from app.core import config

KINDS = ("flat", "ball", "bull", "drill", "chamfer", "tapered_ball", "engraver", "insert", "thread", "groove", "probe", "laser", "nozzle")
MILL_KINDS = ("flat", "ball", "bull", "drill", "chamfer", "tapered_ball", "engraver")
COOLANT = ("off", "flood", "mist")
_lock = threading.Lock()


def library_path() -> str:
    folder = config.data_dir() / "cam"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / "tools.json")


def _num(rec: dict, key: str, lo: float, hi: float, default: float, label: str) -> float:
    v = rec.get(key, default)
    if v is None:
        v = default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) < lo or float(v) > hi:
        raise CamError("%s must be a number between %g and %g." % (label, lo, hi))
    return float(v)


def clean_holder(h) -> dict:
    h = h or {}
    prof = []
    for pt in h.get("profile") or []:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in pt):
            raise CamError("A holder profile is a list of [radius, height] pairs.")
        if pt[0] < 0:
            raise CamError("A holder radius cannot be negative.")
        prof.append([float(pt[0]), float(pt[1])])
    if len(prof) > 200:
        raise CamError("A holder profile has at most 200 points.")
    return {"name": str(h.get("name") or "")[:80], "profile": prof, "collet_length": _num(h, "collet_length", 0, 1000, 0.0, "Collet length"), "gauge_length": _num(h, "gauge_length", 0, 1000, 0.0, "Gauge length")}


def clean_cutting(c) -> dict:
    out = {}
    for name, row in (c or {}).items():
        if not isinstance(row, dict):
            raise CamError("Cutting data for %s must be an object." % name)
        out[str(name)[:80]] = {"vc": _num(row, "vc", 0, 5000, 0.0, "Cutting speed"), "fz": _num(row, "fz", 0, 20, 0.0, "Feed per tooth"), "plunge_factor": _num(row, "plunge_factor", 0.01, 5, 0.5, "Plunge factor"), "ramp_factor": _num(row, "ramp_factor", 0.01, 5, 0.7, "Ramp factor")}
    return out


def clean(rec: dict, keep_id: bool = True) -> dict:
    if not isinstance(rec, dict):
        raise CamError("A tool is an object.")
    kind = rec.get("kind", "flat")
    if kind not in KINDS:
        raise CamError("Tool kind must be one of %s." % ", ".join(KINDS))
    d = _num(rec, "diameter", 0.01, 1000, 6.0, "Diameter")
    out = {
        "id": str(rec.get("id") or uuid.uuid4().hex[:12]) if keep_id else uuid.uuid4().hex[:12],
        "number": int(_num(rec, "number", 1, 999, 1, "Tool number")),
        "name": str(rec.get("name") or "%g mm %s" % (d, kind))[:120],
        "kind": kind,
        "diameter": d,
        "flutes": int(_num(rec, "flutes", 1, 64, 2, "Flutes")),
        "flute_length": _num(rec, "flute_length", 0.01, 1000, max(d * 2.0, 1.0), "Flute length"),
        "overall_length": _num(rec, "overall_length", 0.01, 2000, max(d * 8.0, 20.0), "Overall length"),
        "shank_diameter": _num(rec, "shank_diameter", 0.01, 1000, d, "Shank diameter"),
        "corner_radius": _num(rec, "corner_radius", 0, 500, d / 2.0 if kind == "ball" else 0.0, "Corner radius"),
        "tip_angle": _num(rec, "tip_angle", 1, 179, 118.0 if kind == "drill" else 90.0, "Tip angle"),
        "taper_angle": _num(rec, "taper_angle", 0, 89, 0.0, "Taper angle"),
        "tip_diameter": _num(rec, "tip_diameter", 0, 1000, 0.0, "Tip diameter"),
        "stickout": _num(rec, "stickout", 0, 2000, 0.0, "Stickout"),
        "length_offset": int(_num(rec, "length_offset", 0, 999, rec.get("number", 1) or 1, "Length offset number")),
        "diameter_offset": int(_num(rec, "diameter_offset", 0, 999, rec.get("number", 1) or 1, "Diameter offset number")),
        "rpm_max": _num(rec, "rpm_max", 0, 400000, 24000.0, "Maximum rpm"),
        "coolant": rec.get("coolant", "off"),
        "holder": clean_holder(rec.get("holder")),
        "insert": copy.deepcopy(rec.get("insert") or {}),
        "cutting": clean_cutting(rec.get("cutting")),
        "notes": str(rec.get("notes") or "")[:500],
    }
    if kind == "ball":
        out["corner_radius"] = d / 2.0
    if kind in ("flat", "drill", "chamfer", "engraver"):
        out["corner_radius"] = out["corner_radius"] if kind == "flat" else 0.0
    if out["corner_radius"] > d / 2.0 + 1e-9:
        raise CamError("Corner radius cannot exceed the tool radius.")
    if out["coolant"] not in COOLANT:
        raise CamError("Coolant must be one of %s." % ", ".join(COOLANT))
    if out["shank_diameter"] < 0.01:
        raise CamError("Shank diameter is too small.")
    return out


def load_all() -> list:
    path = library_path()
    with _lock:
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            raise CamError("The tool library file cannot be read.")
    rows = data.get("tools") if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        try:
            out.append(clean(r))
        except CamError:
            continue
    return out


def save_all(rows: list) -> None:
    path = library_path()
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "tools": rows}, fh, indent=1)
        os.replace(tmp, path)


def add(rec: dict) -> dict:
    rows = load_all()
    limits.need(len(rows) + 1, "tools", "Tool library")
    if "number" not in rec or rec["number"] is None:
        rec = dict(rec)
        rec["number"] = max([r["number"] for r in rows] + [0]) + 1
    row = clean(rec, keep_id=False)
    rows.append(row)
    save_all(rows)
    return row


def update(tool_id: str, patch: dict) -> dict:
    rows = load_all()
    for i, r in enumerate(rows):
        if r["id"] == tool_id:
            merged = dict(r)
            merged.update(patch)
            merged["id"] = tool_id
            rows[i] = clean(merged)
            save_all(rows)
            return rows[i]
    raise CamError("There is no library tool %s." % tool_id)


def remove(tool_id: str) -> None:
    rows = load_all()
    keep = [r for r in rows if r["id"] != tool_id]
    if len(keep) == len(rows):
        raise CamError("There is no library tool %s." % tool_id)
    save_all(keep)


def find(tool_id: str) -> dict:
    for r in load_all():
        if r["id"] == tool_id:
            return r
    raise CamError("There is no library tool %s." % tool_id)


class Tool:
    def __init__(self, rec: dict):
        self.rec = rec
        self.kind = rec["kind"]
        self.number = rec["number"]
        self.name = rec["name"]
        self.diameter = rec["diameter"]
        self.radius = rec["diameter"] / 2.0
        self.corner_radius = rec["corner_radius"]
        self.flutes = rec["flutes"]
        self.flute_length = rec["flute_length"]
        self.tip_angle = rec["tip_angle"]
        self.taper_angle = rec["taper_angle"]
        self.overall_length = rec["overall_length"]
        self.length_offset = rec["length_offset"]
        self.diameter_offset = rec["diameter_offset"]
        self.rpm_max = rec["rpm_max"]
        self.cutting = rec["cutting"]
        self.coolant = rec["coolant"]

    def tip_length(self) -> float:
        if self.kind != "drill":
            return 0.0
        return self.radius / math.tan(math.radians(self.tip_angle / 2.0))

    def profile(self, steps: int = 12) -> list:
        r = self.radius
        out = []
        if self.kind == "drill":
            out.append((0.0, 0.0))
            out.append((r, self.tip_length()))
            out.append((r, self.flute_length))
        elif self.kind in ("chamfer", "engraver"):
            tip_r = max(self.rec["tip_diameter"] / 2.0, 0.0)
            h = (r - tip_r) / math.tan(math.radians(self.tip_angle / 2.0))
            out.extend([(0.0, 0.0), (tip_r, 0.0), (r, h), (r, max(self.flute_length, h))])
        elif self.kind in ("ball", "bull", "flat", "tapered_ball"):
            cr = min(self.corner_radius, r)
            if cr > 1e-9:
                out.append((0.0, 0.0))
                for k in range(steps + 1):
                    a = math.pi / 2.0 * k / steps
                    out.append((r - cr + cr * math.sin(a), cr - cr * math.cos(a)))
            else:
                out.extend([(0.0, 0.0), (r, 0.0)])
            out.append((r, max(self.flute_length, cr)))
        else:
            out.extend([(0.0, 0.0), (r, 0.0), (r, self.flute_length)])
        return out

    def effective_diameter(self, ap: float) -> float:
        d = self.diameter
        if self.kind == "ball":
            if ap >= self.radius:
                return d
            return 2.0 * math.sqrt(max(ap * (d - ap), 0.0))
        if self.kind == "bull":
            cr = self.corner_radius
            if ap >= cr:
                return d
            return (d - 2.0 * cr) + 2.0 * math.sqrt(max(ap * (2.0 * cr - ap), 0.0))
        return d
