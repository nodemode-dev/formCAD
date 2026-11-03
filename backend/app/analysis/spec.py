import math

from app.analysis import fields, ramps

MODES = ("zebra", "isophote", "curvature", "draft", "deviation", "wall")
LABELS = {"zebra": "Zebra stripes", "isophote": "Isophotes", "curvature": "Surface curvature", "draft": "Draft angle", "deviation": "Surface deviation", "wall": "Wall thickness"}


class SpecError(ValueError):
    pass


def number(raw, name, low=None, high=None, default=None):
    if raw is None:
        if default is None:
            raise SpecError("%s is needed." % name)
        return float(default)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise SpecError("%s must be a number." % name)
    if not math.isfinite(v):
        raise SpecError("%s must be finite." % name)
    if (low is not None and v < low) or (high is not None and v > high):
        raise SpecError("%s must be from %g to %g." % (name, low if low is not None else -math.inf, high if high is not None else math.inf))
    return v


def vector(raw, name, default):
    v = default if raw is None else raw
    try:
        fields.unit_vector(v, name)
    except fields.FieldError as err:
        raise SpecError(str(err))
    return [float(c) for c in v]


def handle_list(raw, name):
    if raw is None:
        return []
    if isinstance(raw, (int, str)):
        raw = [raw]
    try:
        return [int(h) for h in raw]
    except (TypeError, ValueError):
        raise SpecError("%s must be object handles." % name)


def normalise(d, spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("The analysis needs a mode and its settings.")
    mode = str(spec.get("mode", "")).lower()
    if mode not in MODES:
        raise SpecError("Choose an analysis: %s." % ", ".join(MODES))
    out = {"mode": mode, "targets": handle_list(spec.get("targets"), "targets")}
    if mode in ("zebra", "isophote"):
        out["view"] = vector(spec.get("view"), "view direction", [0.0, -1.0, 0.0])
        direction = str(spec.get("direction", "vertical")).lower()
        if direction not in ("vertical", "horizontal", "custom"):
            raise SpecError("Stripe direction is vertical, horizontal or custom.")
        out["direction"] = direction
        axis_default = [0.0, 0.0, 1.0] if direction != "horizontal" else [1.0, 0.0, 0.0]
        out["axis"] = vector(spec.get("axis"), "stripe axis", axis_default) if direction == "custom" else axis_default
        out["light"] = vector(spec.get("light"), "light direction", [0.0, -1.0, 1.0])
        out["band"] = number(spec.get("band"), "The stripe width", 0.05, 180.0, 6.0)
    elif mode == "curvature":
        measure = str(spec.get("measure", "gaussian")).lower()
        if measure not in fields.MEASURES:
            raise SpecError("Choose a curvature measure: %s." % ", ".join(fields.MEASURES))
        out["measure"] = measure
    elif mode == "draft":
        out["pull"] = vector(spec.get("pull"), "pull direction", [0.0, 0.0, 1.0])
        if spec.get("lower") is not None or spec.get("upper") is not None:
            lo = number(spec.get("lower"), "The lower limit", -90.0, 90.0, -3.0)
            hi = number(spec.get("upper"), "The upper limit", -90.0, 90.0, 3.0)
            if lo >= hi:
                raise SpecError("The lower draft limit must be below the upper limit.")
            out["limits"] = [lo, hi]
    elif mode == "wall":
        from app.plastic import wall as wall_mod

        method = str(spec.get("method", "ray")).lower()
        if method not in ("ray", "sphere"):
            raise SpecError("Choose the wall thickness method: ray or sphere.")
        out["method"] = method
        out["max_vertices"] = wall_mod.vertex_limit(method, None if spec.get("max_vertices") is None else number(spec.get("max_vertices"), "The vertex limit", 100, 500000))
        out["low"] = None if spec.get("low") is None else number(spec.get("low"), "The low limit", 0.0)
        out["high"] = None if spec.get("high") is None else number(spec.get("high"), "The high limit", 0.0)
        if out["low"] is not None and out["high"] is not None and out["low"] >= out["high"]:
            raise SpecError("The low wall limit must be below the high limit.")
    else:
        dev =spec.get("deviation") if isinstance(spec.get("deviation"), dict) else spec
        out["source"] = handle_list(dev.get("source"), "source")
        out["target"] = dev.get("target")
        if out["target"] is None:
            raise SpecError("Name the target surface to measure against.")
        out["target"] = int(out["target"])
        out["faces"] = [int(f) for f in dev.get("faces") or []]
        out["signed"] = bool(dev.get("signed", False))
        out["good"] = None if dev.get("good") is None else number(dev.get("good"), "The good distance", 0.0)
        out["bad"] = None if dev.get("bad") is None else number(dev.get("bad"), "The bad distance", 0.0)
        out["max_vertices"] = int(number(dev.get("max_vertices"), "The vertex limit", 100, 500000, 60000))
    if "ramp" in spec and spec["ramp"] is not None:
        r = spec["ramp"]
        try:
            ramps.resolve(d, mode, out.get("measure", ""), r)
        except (ramps.RampError, TypeError, ValueError) as err:
            raise SpecError(str(err))
        out["ramp"] = r if isinstance(r, dict) else str(r).lower()
    return out
