import copy
import math
import re

HEADER = "ANALYSISRAMPS"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_STOPS = 32
KINDS = ("gradient", "bands", "zones")

DEFAULTS = {
    "diverging": {"kind": "gradient", "stops": [[0.0, "#2b6cb0"], [0.5, "#f2f2f2"], [1.0, "#c53030"]], "min": None, "max": None, "center": 0.0, "symmetric": True},
    "sequential": {"kind": "gradient", "stops": [[0.0, "#1a365d"], [0.35, "#2c7a7b"], [0.7, "#d69e2e"], [1.0, "#f7fafc"]], "min": None, "max": None, "center": None, "symmetric": False},
    "draft": {"kind": "zones", "stops": [[0.0, "#c53030"], [0.5, "#38a169"], [1.0, "#2b6cb0"]], "min": -90.0, "max": 90.0, "center": 0.0, "symmetric": False, "limits": [-3.0, 3.0]},
    "deviation": {"kind": "gradient", "stops": [[0.0, "#2f855a"], [0.5, "#d69e2e"], [1.0, "#c53030"]], "min": 0.0, "max": None, "center": None, "symmetric": False},
    "zebra": {"kind": "bands", "stops": [[0.0, "#141414"], [1.0, "#f4f4f4"]], "min": None, "max": None, "center": None, "symmetric": False},
    "wall": {"kind": "gradient", "stops": [[0.0, "#c53030"], [0.3, "#d69e2e"], [0.6, "#38a169"], [1.0, "#2b6cb0"]], "min": None, "max": None, "center": None, "symmetric": False},
}
MODE_RAMP = {"zebra": "zebra", "isophote": "zebra", "curvature": "diverging", "draft": "draft", "deviation": "deviation", "wall": "wall"}
CURVATURE_RAMP = {"gaussian": "diverging", "mean": "diverging", "max": "diverging", "min": "diverging", "absolute": "sequential", "rms": "sequential"}


class RampError(ValueError):
    pass


def clean(raw) -> dict:
    if not isinstance(raw, dict):
        raise RampError("A colour ramp is an object with stops.")
    kind = str(raw.get("kind", "gradient"))
    if kind not in KINDS:
        raise RampError("A colour ramp is a gradient or bands.")
    stops = raw.get("stops")
    if not isinstance(stops, list) or not 2 <= len(stops) <= MAX_STOPS:
        raise RampError("A colour ramp needs between 2 and %d stops." % MAX_STOPS)
    out = []
    last = -1.0
    for s in stops:
        if not isinstance(s, (list, tuple)) or len(s) != 2:
            raise RampError("A stop is a position from 0 to 1 and a colour such as #aabbcc.")
        t, c = float(s[0]), str(s[1])
        if not math.isfinite(t) or not 0.0 <= t <= 1.0 or t < last:
            raise RampError("Stop positions run from 0 to 1 in order.")
        if not HEX.match(c):
            raise RampError("Colours are written #rrggbb.")
        out.append([t, c.lower()])
        last = t
    rec = {"kind": kind, "stops": out}
    for key in ("min", "max", "center"):
        v = raw.get(key)
        if v is None:
            rec[key] = None
        else:
            v = float(v)
            if not math.isfinite(v):
                raise RampError("Limits must be finite numbers.")
            rec[key] = v
    if rec["min"] is not None and rec["max"] is not None and rec["min"] >= rec["max"]:
        raise RampError("The lower limit must be below the upper limit.")
    rec["symmetric"] = bool(raw.get("symmetric", False))
    limits = raw.get("limits")
    if limits is not None:
        if not isinstance(limits, (list, tuple)) or len(limits) != 2 or not all(math.isfinite(float(v)) for v in limits) or float(limits[0]) >= float(limits[1]):
            raise RampError("Limits are a lower and an upper number, the lower one smaller.")
        rec["limits"] = [float(limits[0]), float(limits[1])]
    return rec


def stored(d) -> dict:
    raw = d.header.get(HEADER)
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def all_ramps(d) -> dict:
    out = copy.deepcopy(DEFAULTS)
    for name, rec in stored(d).items():
        try:
            out[name] = clean(rec)
        except RampError:
            continue
    return out


def get(d, name: str) -> dict:
    ramps = all_ramps(d)
    if name not in ramps:
        raise RampError("There is no ramp named %s; choose %s." % (name, ", ".join(sorted(ramps))))
    return ramps[name]


def put(d, name: str, rec) -> dict:
    name = str(name).strip().lower()
    if not name or len(name) > 40 or not re.match(r"^[a-z0-9 _-]+$", name):
        raise RampError("A ramp name is up to 40 letters, digits, spaces, hyphens or underscores.")
    rec = clean(rec)
    held = stored(d)
    held[name] = rec
    d.set_header(HEADER, held)
    return rec


def reset(d, name: str) -> None:
    held = stored(d)
    if name in held:
        del held[name]
        d.set_header(HEADER, held)


def resolve(d, mode: str, measure: str, ramp) -> tuple:
    if isinstance(ramp, dict):
        base = MODE_RAMP.get(mode, "diverging") if mode != "curvature" else CURVATURE_RAMP.get(measure, "diverging")
        merged = {**get(d, base), **{k: v for k, v in ramp.items() if v is not None or k in ("min", "max", "center")}}
        return "custom", clean(merged)
    name = str(ramp).lower() if ramp else (CURVATURE_RAMP.get(measure, "diverging") if mode == "curvature" else MODE_RAMP.get(mode, "diverging"))
    return name, get(d, name)
