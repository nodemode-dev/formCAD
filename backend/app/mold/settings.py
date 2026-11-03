import copy
import math

HEADER = "MOLDSETTINGS"
RESULT = "MOLDRESULT"
CONVENTIONS = ("multiply", "divide")
MAX_SHRINK = 30.0


class MoldError(ValueError):
    pass


def defaults() -> dict:
    return {
        "body": None,
        "pull": [0.0, 0.0, 1.0],
        "min_draft": 1.0,
        "grid": 5,
        "height": None,
        "margin": None,
        "cavity_margin": None,
        "core_margin": None,
        "shrink": {"percent": [0.0, 0.0, 0.0], "convention": "multiply", "origin": None},
    }


def number(v, what, lo=None, hi=None, nullable=False):
    if v is None or v == "":
        if nullable:
            return None
        raise MoldError("Give a number for %s." % what)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise MoldError("%s must be a number." % what)
    if not math.isfinite(x):
        raise MoldError("%s must be finite." % what)
    if lo is not None and x < lo:
        raise MoldError("%s must be at least %g." % (what, lo))
    if hi is not None and x > hi:
        raise MoldError("%s must be at most %g." % (what, hi))
    return x


def vector(v, what, nonzero=False):
    try:
        out = [float(c) for c in v]
    except (TypeError, ValueError):
        raise MoldError("%s needs three numbers." % what)
    if len(out) == 2:
        out.append(0.0)
    if len(out) != 3 or not all(math.isfinite(c) for c in out):
        raise MoldError("%s needs three finite numbers." % what)
    if nonzero and math.sqrt(sum(c * c for c in out)) < 1e-9:
        raise MoldError("%s must not be the zero vector." % what)
    return out


def shrink_of(v) -> dict:
    rec = copy.deepcopy(defaults()["shrink"])
    if v is None:
        return rec
    if isinstance(v, (int, float)):
        v = {"percent": v}
    if not isinstance(v, dict):
        raise MoldError("Shrinkage is a percentage or a record with percent, convention and origin.")
    bad = [k for k in v if k not in rec]
    if bad:
        raise MoldError("%s is not a shrinkage value." % ", ".join(sorted(bad)))
    if "percent" in v:
        pc = v["percent"]
        if isinstance(pc, (int, float)):
            pc = [pc, pc, pc]
        if not isinstance(pc, (list, tuple)) or len(pc) != 3:
            raise MoldError("Shrinkage percent is one number or three numbers (x, y, z).")
        rec["percent"] = [number(c, "Shrinkage percent", 0.0, MAX_SHRINK) for c in pc]
    if "convention" in v:
        if v["convention"] not in CONVENTIONS:
            raise MoldError("Shrinkage convention is multiply (scale 1 + s) or divide (scale 1 / (1 - s)).")
        rec["convention"] = v["convention"]
    if "origin" in v:
        rec["origin"] = None if v["origin"] is None else vector(v["origin"], "The shrinkage origin")
    return rec


def merge(base: dict, values: dict) -> dict:
    rec = copy.deepcopy(base)
    bad = [k for k in values if k not in rec]
    if bad:
        raise MoldError("%s is not a mold setting." % ", ".join(sorted(bad)))
    for key, val in values.items():
        if key == "body":
            rec[key] = None if val in (None, "", 0) else int(val)
        elif key == "pull":
            rec[key] = vector(val, "The pull direction", True)
        elif key == "min_draft":
            rec[key] = number(val, "The minimum draft", 0.0, 45.0)
        elif key == "grid":
            rec[key] = int(number(val, "The sample grid", 2, 12))
        elif key in ("height", "margin", "cavity_margin", "core_margin"):
            rec[key] = number(val, key.replace("_", " "), 0.0 if key != "height" else None, None, True)
        elif key == "shrink":
            rec[key] = shrink_of(val)
    return rec


def current(d) -> dict:
    stored = d.header.get(HEADER)
    rec = defaults()
    if isinstance(stored, dict):
        rec = merge(rec, stored)
    rec["defined"] = isinstance(stored, dict)
    return rec


def put(d, values: dict) -> dict:
    if not isinstance(values, dict) or not values:
        raise MoldError("Give the mold settings to set.")
    base = current(d)
    base.pop("defined", None)
    rec = merge(base, values)
    d.set_header(HEADER, copy.deepcopy(rec))
    return current(d)


def reset(d) -> None:
    if HEADER in d.header:
        d.set_header(HEADER, None)


def factors(shrink: dict) -> list:
    out = []
    for s in shrink["percent"]:
        f = s / 100.0
        out.append(1.0 + f if shrink["convention"] == "multiply" else 1.0 / (1.0 - f))
    return out


def last_result(d) -> dict:
    v = d.header.get(RESULT)
    return copy.deepcopy(v) if isinstance(v, dict) else {}


def store_result(d, patch: dict) -> dict:
    rec = last_result(d)
    rec.update(patch)
    d.set_header(RESULT, copy.deepcopy(rec))
    return rec
