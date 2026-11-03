from app.cmd import barred

LIMITS = {
    "unknowns": (90_000, 30_000),
    "nodes": (400_000, 100_000),
    "tets": (2_000_000, 400_000),
    "midplane_triangles": (200_000, 40_000),
    "fill_steps": (4000, 1000),
    "iterations": (3000, 600),
    "su2_seconds": (3600, 600),
    "su2_cells": (3_000_000, 500_000),
    "seconds": (900, 180),
    "bytes_per_unknown": (24_000, 24_000),
}


class FlowError(Exception):
    pass


class Cancelled(FlowError):
    pass


def restricted(runner=None) -> bool:
    if isinstance(runner, bool):
        return runner
    return bool(barred.caller(runner))


def cap(key: str, runner=None) -> int:
    window, locked = LIMITS[key]
    return locked if restricted(runner) else window


def view() -> dict:
    return {"interactive": {k: v[0] for k, v in LIMITS.items()}, "restricted": {k: v[1] for k, v in LIMITS.items()}}


def need(value, name: str, low=None, high=None, positive=False) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise FlowError("%s must be a number." % name)
    if x != x or x in (float("inf"), float("-inf")):
        raise FlowError("%s must be a finite number." % name)
    if positive and x <= 0:
        raise FlowError("%s must be greater than zero." % name)
    if low is not None and x < low:
        raise FlowError("%s must be at least %g." % (name, low))
    if high is not None and x > high:
        raise FlowError("%s must be at most %g." % (name, high))
    return x
