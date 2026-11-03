import copy
import math

from app.cutting.shapes import CutError

KINDS = ("laser", "plasma", "waterjet", "router")

BASE = {
    "name": "",
    "kind": "laser",
    "kerf": 0.2,
    "feed": 1000.0,
    "pierce_feed": 300.0,
    "power": 1000.0,
    "pierce_delay": 0.0,
    "z_control": False,
    "z_clearance": 10.0,
    "pierce_height": 3.8,
    "cut_height": 1.5,
    "rapid": 10000.0,
    "good_side": "right",
    "lead_in": {"type": "arc", "length": 2.0, "angle": 45.0},
    "lead_out": {"type": "overcut", "length": 1.0},
    "small_hole_ratio": 1.0,
    "small_hole_factor": 1.0,
    "thickness": 3.0,
    "material": "",
    "notes": "",
}

KIND_DEFAULTS = {
    "laser": {"kerf": 0.2, "feed": 1500.0, "pierce_delay": 0.0, "z_control": False, "power": 1000.0},
    "plasma": {"kerf": 2.0, "feed": 2000.0, "pierce_delay": 0.5, "z_control": True, "power": 1.0, "lead_in": {"type": "arc", "length": 4.0, "angle": 45.0}, "lead_out": {"type": "overcut", "length": 2.5}},
    "waterjet": {"kerf": 1.0, "feed": 300.0, "pierce_delay": 1.0, "z_control": False, "power": 1.0, "lead_in": {"type": "arc", "length": 3.0, "angle": 45.0}, "lead_out": {"type": "line", "length": 3.0, "angle": 45.0}},
    "router": {"kerf": 6.0, "feed": 1500.0, "pierce_delay": 0.0, "z_control": True, "power": 18000.0, "lead_in": {"type": "arc", "length": 3.0, "angle": 45.0}, "lead_out": {"type": "arc", "length": 3.0, "angle": 45.0}},
}

PLASMA_KERF_POINTS = ((100.0, 2.0), (200.0, 3.0))
WATERJET_KERF_RATIO = 1.1


def plasma_kerf(amps: float) -> float:
    (a0, k0), (a1, k1) = PLASMA_KERF_POINTS
    amps = float(amps)
    if amps <= 0:
        raise CutError("Plasma current must be above zero.")
    return k0 + (k1 - k0) * (amps - a0) / (a1 - a0)


def waterjet_kerf(tube_diameter: float) -> float:
    d = float(tube_diameter)
    if d <= 0:
        raise CutError("The mixing tube diameter must be above zero.")
    return WATERJET_KERF_RATIO * d


def blank(kind: str) -> dict:
    if kind not in KINDS:
        raise CutError("A cutting process is one of %s." % ", ".join(KINDS))
    rec = copy.deepcopy(BASE)
    rec.update(copy.deepcopy(KIND_DEFAULTS[kind]))
    rec["kind"] = kind
    rec["name"] = kind.capitalize()
    return rec


def _num(rec, key, lo, hi, what):
    v = rec[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise CutError("%s needs a number." % what)
    if not lo <= float(v) <= hi:
        raise CutError("%s must be between %g and %g." % (what, lo, hi))
    rec[key] = float(v)


def clean(raw: dict) -> dict:
    raw = raw or {}
    kind = raw.get("kind", "laser")
    rec = blank(kind)
    for k, v in raw.items():
        if k not in BASE:
            raise CutError("A cutting process has no field called %s." % k)
        if isinstance(rec.get(k), dict) and isinstance(v, dict):
            merged = dict(rec[k])
            merged.update(v)
            rec[k] = merged
        else:
            rec[k] = v
    for k, lo, hi, what in (("kerf", 0.0, 100.0, "Kerf"), ("feed", 1.0, 100000.0, "Cut feed"), ("pierce_feed", 1.0, 100000.0, "Pierce feed"), ("power", 0.0, 1000000.0, "Power"), ("pierce_delay", 0.0, 60.0, "Pierce delay"), ("z_clearance", 0.0, 500.0, "Travel height"), ("pierce_height", 0.0, 500.0, "Pierce height"), ("cut_height", 0.0, 500.0, "Cut height"), ("rapid", 1.0, 1000000.0, "Rapid rate"), ("small_hole_ratio", 0.0, 100.0, "Small hole ratio"), ("small_hole_factor", 0.05, 1.0, "Small hole factor"), ("thickness", 0.0, 1000.0, "Thickness")):
        _num(rec, k, lo, hi, what)
    if rec["good_side"] not in ("right", "left", "none"):
        raise CutError("The good side is right, left or none.")
    for lead, kinds in (("lead_in", ("arc", "line", "none")), ("lead_out", ("overcut", "arc", "line", "none"))):
        d = rec[lead]
        if d.get("type") not in kinds:
            raise CutError("%s is one of %s." % (lead.replace("_", " ").capitalize(), ", ".join(kinds)))
        for key in ("length", "angle"):
            if key in d:
                if not isinstance(d[key], (int, float)) or isinstance(d[key], bool) or not 0 <= float(d[key]) <= 1000:
                    raise CutError("%s %s must be between 0 and 1000." % (lead, key))
                d[key] = float(d[key])
        d.setdefault("length", 0.0)
        d.setdefault("angle", 45.0)
        if d["angle"] <= 0 or d["angle"] > 90:
            if d["type"] == "line":
                raise CutError("A straight lead angle is above 0 and at most 90 degrees.")
    if rec["pierce_height"] < rec["cut_height"] and rec["z_control"]:
        raise CutError("The pierce height is below the cut height; the torch pierces higher than it cuts.")
    rec["z_control"] = bool(rec["z_control"])
    rec["name"] = str(rec["name"] or kind.capitalize())
    return rec
