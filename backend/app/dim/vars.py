import math

from app.doc.tables import DIM_DEFAULTS

NAMES = tuple(DIM_DEFAULTS.keys())
ANGLE_NAMES = ("DIMJOGANG",)


def style_record(drawing, name):
    rec = drawing.table_get("dimstyles", name) if name else None
    if rec is None:
        rec = drawing.table_get("dimstyles", "Standard")
    return rec


def resolve(drawing, style_name, overrides=None) -> dict:
    out = dict(DIM_DEFAULTS)
    rec = style_record(drawing, style_name)
    if rec is not None:
        out.update(rec.get("vars", {}))
    if overrides:
        for k, v in overrides.items():
            if k in DIM_DEFAULTS:
                out[k] = v
    return out


def of(drawing, dim) -> dict:
    return resolve(drawing, dim.style, dim.overrides)


def scale_of(drawing, v) -> float:
    s = float(v.get("DIMSCALE", 1.0) or 0.0)
    if s > 0:
        return s
    name = drawing.header.get("CANNOSCALE", "1:1")
    f = drawing.scale_value(name)
    return f if f > 0 else 1.0


def clean_name(name: str) -> str:
    return str(name or "").strip().upper()


def known(name: str) -> bool:
    return clean_name(name) in DIM_DEFAULTS


def coerce(name: str, raw):
    key = clean_name(name)
    if key not in DIM_DEFAULTS:
        raise KeyError(name)
    cur = DIM_DEFAULTS[key]
    if isinstance(cur, str):
        return str(raw)
    if isinstance(cur, float):
        val = float(raw)
        if not math.isfinite(val):
            raise ValueError("Requires a finite number.")
        return val
    if isinstance(raw, str):
        txt = raw.strip()
        try:
            val = int(txt)
        except ValueError:
            val = float(txt)
            if val != int(val):
                raise ValueError("Requires an integer.")
            val = int(val)
        return val
    return int(raw)


def format_value(val) -> str:
    if isinstance(val, float):
        s = ("%.6f" % val).rstrip("0").rstrip(".")
        return "0" if s in ("", "-0") else s
    return str(val)


def validate(doc, name, raw):
    from app.sysvars import registry as sv

    sv._ensure_loaded()
    key = clean_name(name)
    vd = sv.BY_NAME.get(key)
    if vd is None or key not in DIM_DEFAULTS:
        raise KeyError(name)
    try:
        v = sv._coerce(vd, raw)
        v = sv._check(vd, v, doc)
    except sv.SysvarError as err:
        raise ValueError(str(err))
    cur = DIM_DEFAULTS[key]
    if isinstance(cur, float):
        v = float(v)
    return v
