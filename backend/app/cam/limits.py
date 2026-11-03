from app.core import guard


class CamError(ValueError):
    pass


class Cancelled(Exception):
    pass


WINDOW = {"setups": 50, "ops": 500, "region_vertices": 200000, "moves": 2000000, "triangles": 2000000, "passes": 100000, "holes": 20000, "seconds": 120.0, "export_lines": 5000000, "grid_cells": 6000000, "tools": 500}
AGENT = {"setups": 10, "ops": 100, "region_vertices": 50000, "moves": 400000, "triangles": 400000, "passes": 20000, "holes": 5000, "seconds": 40.0, "export_lines": 1000000, "grid_cells": 1500000, "tools": 100}


def limited() -> bool:
    return guard.CALLER.get() in ("macro", "agent")


def get(low=None) -> dict:
    use_low = limited() if low is None else low
    out = dict(AGENT if use_low else WINDOW)
    out["limited_caller"] = use_low
    return out


def need(count, key: str, what: str, low=None) -> None:
    cap = get(low)[key]
    if count > cap:
        raise CamError("%s: %d is more than the limit of %d." % (what, count, cap))
