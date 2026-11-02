from app.param import infer, ops
from app.param import store as S


def number(value, name, low, high, integer=False):
    try:
        v = int(value) if integer else float(value)
    except (TypeError, ValueError):
        raise S.ParamError("%s needs a number." % name)
    if not (low <= v <= high):
        raise S.ParamError("%s must be between %g and %g." % (name, low, high))
    return v


def update(d, changes: dict) -> dict:
    cfg = S.settings(d)
    for key, value in changes.items():
        if key == "infer":
            cfg["infer"] = number(value, "infer", 0, 1, True)
        elif key == "distance_tol":
            cfg[key] = number(value, "Distance tolerance", 1e-12, 1e6)
        elif key == "angle_tol":
            cfg[key] = number(value, "Angle tolerance", 1e-9, 45.0)
        elif key == "auto_types":
            types = [str(t).lower() for t in value]
            bad = [t for t in types if t not in infer.PRIORITY]
            if bad:
                raise S.ParamError("Auto-constrain cannot apply '%s'." % bad[0])
            cfg[key] = types
        elif key in ("bars", "dims"):
            if str(value).lower() not in ("all", "none"):
                raise S.ParamError("%s must be all or none." % key)
            cfg[key] = str(value).lower()
            cfg["bar_except" if key == "bars" else "dim_except"] = []
        elif key in ("bar_except", "dim_except"):
            cfg[key] = sorted({int(h) for h in value})
        elif key == "bar_transparency":
            cfg[key] = number(value, "Transparency", 0, 90, True)
        else:
            raise S.ParamError("Unknown setting '%s'." % key)
    S.save_settings(d, cfg)
    ops.mark(d)
    return cfg


def show_hide(d, which: str, handles, show: bool) -> dict:
    key, exc = ("bars", "bar_except") if which == "bars" else ("dims", "dim_except")
    cfg = S.settings(d)
    cur = set(cfg[exc])
    base_all = cfg[key] == "all"
    for h in handles:
        h = int(h)
        if show == base_all:
            cur.discard(h)
        else:
            cur.add(h)
    cfg[exc] = sorted(cur)
    S.save_settings(d, cfg)
    ops.touch(d, list(handles))
    ops.mark(d)
    return cfg


def show_all(d, which: str, show: bool) -> dict:
    cfg = S.settings(d)
    key, exc = ("bars", "bar_except") if which == "bars" else ("dims", "dim_except")
    touched = [int(h) for r in S.constraints(d) for h, _ in r["refs"]]
    cfg[key] = "all" if show else "none"
    cfg[exc] = []
    S.save_settings(d, cfg)
    ops.touch(d, touched)
    ops.mark(d)
    return cfg
