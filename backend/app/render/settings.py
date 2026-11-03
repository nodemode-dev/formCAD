import copy
import math

from app.core import guard
from app.render import environments

TABLE = "render"
NAME = "settings"
MAX_EDGE = 8192
MIN_EDGE = 16
MAX_PIXELS = 8192 * 4608
LOWER_EDGE = 3840
LOWER_SAMPLES = 512
MAX_SAMPLES = 4096
TONES = ("neutral", "aces", "agx", "linear")
GROUND = ("none", "floor")
RESOLUTIONS = environments.RESOLUTIONS
HEX_DIGITS = "0123456789abcdefABCDEF"


class SettingsError(ValueError):
    pass


def defaults() -> dict:
    return {
        "name": NAME,
        "environment": {"id": environments.default_id(), "resolution": "1k", "rotation": 0.0, "intensity": 1.0, "show_background": True, "background_color": "#ffffff", "blur": 0.0},
        "ground": {"mode": "none", "color": "#ffffff", "roughness": 0.6},
        "quality": {"samples": 256, "bounces": 6, "transmissive_bounces": 8, "filter_glossy": 0.5, "tiles": 4, "denoise": False, "exposure": 1.0, "tone_mapping": "neutral"},
        "output": {"width": 3840, "height": 2160, "transparent": False},
        "camera": {"fov": None, "aperture": 0.0, "focus_distance": None},
    }


def caller_is_limited() -> bool:
    return guard.CALLER.get() in ("macro", "agent")


def limits(limited=None) -> dict:
    low = caller_is_limited() if limited is None else limited
    return {"max_edge": LOWER_EDGE if low else MAX_EDGE, "min_edge": MIN_EDGE, "max_pixels": min(LOWER_EDGE * 2160, MAX_PIXELS) if low else MAX_PIXELS, "max_samples": LOWER_SAMPLES if low else MAX_SAMPLES, "max_tiles": 16, "limited_caller": low}


def _num(section: str, key: str, value, lo: float, hi: float, integer: bool = False):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SettingsError("%s %s needs a number." % (section, key))
    if not math.isfinite(v) or v < lo or v > hi:
        raise SettingsError("%s %s must be between %g and %g." % (section, key, lo, hi))
    return int(round(v)) if integer else v


def _hex(section: str, key: str, value) -> str:
    s = str(value)
    if len(s) != 7 or s[0] != "#" or any(c not in HEX_DIGITS for c in s[1:]):
        raise SettingsError("%s %s must be a colour like #rrggbb." % (section, key))
    return s.lower()


def _bool(section: str, key: str, value) -> bool:
    if not isinstance(value, bool):
        raise SettingsError("%s %s must be true or false." % (section, key))
    return value


def clean(rec: dict, limited=None) -> dict:
    out = defaults()
    lim = limits(limited)
    env = rec.get("environment") or {}
    o = out["environment"]
    if "id" in env:
        eid = str(env["id"])
        if environments.entry(eid) is None:
            raise SettingsError("There is no environment called %s." % eid)
        o["id"] = eid
    if "resolution" in env:
        if env["resolution"] not in RESOLUTIONS:
            raise SettingsError("Environment resolution must be one of %s." % ", ".join(RESOLUTIONS))
        o["resolution"] = env["resolution"]
    if "rotation" in env:
        o["rotation"] = _num("Environment", "rotation", env["rotation"], -360.0, 360.0)
    if "intensity" in env:
        o["intensity"] = _num("Environment", "intensity", env["intensity"], 0.0, 20.0)
    if "show_background" in env:
        o["show_background"] = _bool("Environment", "show_background", env["show_background"])
    if "background_color" in env:
        o["background_color"] = _hex("Environment", "background_color", env["background_color"])
    if "blur" in env:
        o["blur"] = _num("Environment", "blur", env["blur"], 0.0, 1.0)
    gr = rec.get("ground") or {}
    o = out["ground"]
    if "mode" in gr:
        if gr["mode"] not in GROUND:
            raise SettingsError("Ground mode must be none or floor.")
        o["mode"] = gr["mode"]
    if "color" in gr:
        o["color"] = _hex("Ground", "color", gr["color"])
    if "roughness" in gr:
        o["roughness"] = _num("Ground", "roughness", gr["roughness"], 0.0, 1.0)
    q = rec.get("quality") or {}
    o = out["quality"]
    if "samples" in q:
        o["samples"] = _num("Quality", "samples", q["samples"], 1, lim["max_samples"], True)
    if "bounces" in q:
        o["bounces"] = _num("Quality", "bounces", q["bounces"], 1, 32, True)
    if "transmissive_bounces" in q:
        o["transmissive_bounces"] = _num("Quality", "transmissive_bounces", q["transmissive_bounces"], 1, 32, True)
    if "filter_glossy" in q:
        o["filter_glossy"] = _num("Quality", "filter_glossy", q["filter_glossy"], 0.0, 1.0)
    if "tiles" in q:
        o["tiles"] = _num("Quality", "tiles", q["tiles"], 1, lim["max_tiles"], True)
    if "denoise" in q:
        o["denoise"] = _bool("Quality", "denoise", q["denoise"])
    if "exposure" in q:
        o["exposure"] = _num("Quality", "exposure", q["exposure"], 0.05, 20.0)
    if "tone_mapping" in q:
        if q["tone_mapping"] not in TONES:
            raise SettingsError("Tone mapping must be one of %s." % ", ".join(TONES))
        o["tone_mapping"] = q["tone_mapping"]
    op = rec.get("output") or {}
    o = out["output"]
    if "width" in op:
        o["width"] = _num("Output", "width", op["width"], MIN_EDGE, lim["max_edge"], True)
    if "height" in op:
        o["height"] = _num("Output", "height", op["height"], MIN_EDGE, lim["max_edge"], True)
    if "transparent" in op:
        o["transparent"] = _bool("Output", "transparent", op["transparent"])
    if o["width"] * o["height"] > lim["max_pixels"]:
        raise SettingsError("The image would have %d million pixels; the limit is %d million." % (o["width"] * o["height"] // 1000000, lim["max_pixels"] // 1000000))
    if out["quality"]["tiles"] < 2 and o["width"] * o["height"] > 2048 * 2048:
        out["quality"]["tiles"] = 2
    cam = rec.get("camera") or {}
    o = out["camera"]
    if cam.get("fov") is not None:
        o["fov"] = _num("Camera", "fov", cam["fov"], 5.0, 120.0)
    if "aperture" in cam:
        o["aperture"] = _num("Camera", "aperture", cam["aperture"], 0.0, 1000.0)
    if cam.get("focus_distance") is not None:
        o["focus_distance"] = _num("Camera", "focus_distance", cam["focus_distance"], 0.001, 1.0e9)
    return out


def merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for section, value in patch.items():
        if section == "name":
            continue
        if section not in out or not isinstance(value, dict):
            raise SettingsError("There is no settings section called %s." % section)
        out[section].update(value)
    return out


def read(d) -> dict:
    t = d.tables.get(TABLE)
    rec = t.get(NAME) if t is not None else None
    if rec is None:
        return defaults()
    try:
        return clean(rec, False)
    except SettingsError:
        return defaults()


def write(d, patch: dict) -> dict:
    merged = clean(merge(read(d), patch))
    d.table_set(TABLE, copy.deepcopy(merged))
    return merged
