import copy
import re

from app.mates import store as S

KEY = "motion"
EASES = ("linear", "smooth", "hold")
CONTACT_MODES = ("stop", "report", "off")
DEFAULT_DYNAMICS = {"gravity": [0.0, 0.0, -9.81], "density": 1000.0, "servo_hz": 25.0, "damping_ratio": 1.0, "solref_loop": 0.005, "timestep": 0.002, "friction": 0.6, "contact_time": 0.006}
LIMITS = {
    "window": {"frames": 6000, "tracks": 64, "keys": 2000, "studies": 200, "contacts": 200, "pairs": 5000, "duration": 3600.0, "fps": 120, "checks": 800, "dyn_steps": 5000000, "dyn_duration": 600.0, "dyn_bodies": 300, "dyn_frames": 30000, "dyn_record_fps": 240},
    "restricted": {"frames": 1200, "tracks": 16, "keys": 200, "studies": 40, "contacts": 40, "pairs": 500, "duration": 300.0, "fps": 60, "checks": 150, "dyn_steps": 500000, "dyn_duration": 60.0, "dyn_bodies": 60, "dyn_frames": 3000, "dyn_record_fps": 60},
}


class MotionError(ValueError):
    pass


def limits(restricted: bool) -> dict:
    return LIMITS["restricted" if restricted else "window"]


def blank() -> dict:
    return {"studies": {}, "contacts": {}, "dynamics": copy.deepcopy(DEFAULT_DYNAMICS), "next_study": 1, "next_contact": 1}


def load(d) -> dict:
    out = blank()
    raw = S.header(d).get(KEY)
    if isinstance(raw, dict):
        for k, v in raw.items():
            out[k] = copy.deepcopy(v)
    dyn = copy.deepcopy(DEFAULT_DYNAMICS)
    dyn.update(out.get("dynamics") or {})
    out["dynamics"] = dyn
    return out


def save(d, data: dict) -> None:
    h = S.header(d)
    h[KEY] = copy.deepcopy(data)
    S.save_header(d, h)


def study(data: dict, sid) -> dict:
    key = str(sid)
    hit = data["studies"].get(key)
    if hit is None:
        for s in data["studies"].values():
            if s["name"].casefold() == key.casefold():
                return s
        raise MotionError("There is no motion study %s." % sid)
    return hit


def contact(data: dict, kid) -> dict:
    key = str(kid)
    hit = data["contacts"].get(key)
    if hit is None:
        for s in data["contacts"].values():
            if s["name"].casefold() == key.casefold():
                return s
        raise MotionError("There is no contact set %s." % kid)
    return hit


def number(v, name, lo=None, hi=None) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        raise MotionError("%s must be a number." % name)
    if out != out or out in (float("inf"), float("-inf")):
        raise MotionError("%s must be a finite number." % name)
    if lo is not None and out < lo:
        raise MotionError("%s must be at least %g." % (name, lo))
    if hi is not None and out > hi:
        raise MotionError("%s must be at most %g." % (name, hi))
    return out


RANGES = {"density": (1.0, 30000.0), "servo_hz": (0.5, 500.0), "damping_ratio": (0.0, 20.0), "solref_loop": (0.002, 1.0), "timestep": (1e-5, 0.05), "friction": (0.0, 5.0), "contact_time": (0.002, 1.0)}


def apply_settings(d, values: dict) -> dict:
    data = load(d)
    dyn = data["dynamics"]
    if values.get("gravity") is not None:
        g = values["gravity"]
        if not isinstance(g, (list, tuple)) or len(g) != 3:
            raise MotionError("Gravity is three numbers.")
        dyn["gravity"] = [number(v, "Gravity", -1000.0, 1000.0) for v in g]
    for k, (lo, hi) in RANGES.items():
        if values.get(k) is not None:
            dyn[k] = number(values[k], k, lo, hi)
    save(d, data)
    return dyn


NAME_RE = re.compile(r"^[^\x00-\x1f]{1,80}$")


def clean_name(v) -> str:
    s = str(v or "").strip()
    if not NAME_RE.match(s):
        raise MotionError("A name is 1 to 80 characters.")
    return s
