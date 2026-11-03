from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routers.part import _doc
from app.sim import study
from app.simnl import fatigue as ft
from app.simnl import laminate as lm

router = APIRouter(tags=["simnl"])

LIMITS = {"history": (200000, 20000), "blocks": (4096, 256), "plies": (256, 64)}


def cap(name: str) -> int:
    return LIMITS[name][1 if study.restricted() else 0]


class LaminateBody(BaseModel):
    ply: dict[str, Any]
    layup: list[Any]
    thickness: Optional[float] = None
    symmetric: bool = False
    loads: Optional[dict[str, Any]] = None


class LifeBody(BaseModel):
    sn: dict[str, Any]
    spectrum: list[dict[str, Any]]
    correction: str = "goodman"
    sigma_u: Optional[float] = None
    sigma_y: Optional[float] = None
    allowable: Optional[dict[str, Any]] = None


class RainflowBody(BaseModel):
    points: list[float]
    repeating: bool = False


def triple(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise lm.LaminateError("%s needs three numbers." % name)
    return [float(x) for x in v]


def guarded(fn):
    try:
        return fn()
    except (lm.LaminateError, ft.FatigueError) as err:
        raise HTTPException(400, str(err))
    except (TypeError, ValueError, KeyError) as err:
        raise HTTPException(400, "The request is not valid: %s." % (err.args[0] if err.args else err))


def mat_list(a):
    return [[float(x) for x in row] for row in a]


@router.post("/{doc_id}/sim/laminate")
def laminate(doc_id: str, body: LaminateBody) -> dict:
    _doc(doc_id)

    def run():
        if len(body.layup) > cap("plies"):
            raise lm.LaminateError("A laminate has at most %d plies for this caller." % cap("plies"))
        lam = lm.build(body.ply, body.layup, body.thickness, body.symmetric)
        out = {
            "thickness_m": lam["h"],
            "A": mat_list(lam["A"]),
            "B": mat_list(lam["B"]),
            "D": mat_list(lam["D"]),
            "constants": lm.engineering_constants(lam),
            "plies": [{"angle": p["angle"], "thickness": p["thickness"], "z0": p["z0"], "z1": p["z1"]} for p in lam["plies"]],
            "units": "SI: A in N/m, B in N, D in N m, stresses in Pa, lengths in m",
            "model": "classical laminate theory, Tsai-Wu with F12 = -0.5 sqrt(F11 F22)",
        }
        if body.loads:
            n = triple(body.loads.get("N", [0, 0, 0]), "N")
            m = triple(body.loads.get("M", [0, 0, 0]), "M")
            out["analysis"] = lm.analyse(lam, n, m)
        return out

    return guarded(run)


@router.post("/{doc_id}/sim/fatigue/life")
def fatigue_life(doc_id: str, body: LifeBody) -> dict:
    _doc(doc_id)

    def run():
        if len(body.spectrum) > cap("blocks"):
            raise ft.FatigueError("The spectrum has at most %d blocks for this caller." % cap("blocks"))
        sn = ft.SN(body.sn)
        out = ft.miner_life(sn, body.spectrum, body.sigma_u, body.sigma_y, body.correction)
        out["sn"] = {"C": sn.C, "b": sn.b, "endurance_limit": sn.limit}
        if body.allowable:
            n = float(body.allowable["cycles"])
            mean = float(body.allowable.get("mean", 0.0))
            amp = float(sn.amplitude_at(n))
            out["allowable_amplitude"] = {"cycles": n, "mean": mean, "reversed_amplitude": amp, "amplitude": float(ft.allowable_amplitude(amp, mean, body.correction, body.sigma_u, body.sigma_y))}
        return out

    return guarded(run)


@router.post("/{doc_id}/sim/fatigue/rainflow")
def fatigue_rainflow(doc_id: str, body: RainflowBody) -> dict:
    _doc(doc_id)

    def run():
        if len(body.points) > cap("history"):
            raise ft.FatigueError("The history has at most %d points for this caller." % cap("history"))
        cycles = ft.rainflow_repeating(body.points) if body.repeating else ft.rainflow(body.points)
        rows = ft.merge_cycles(cycles)
        return {"cycles": [{"range": r, "mean": m, "count": c} for r, m, c in rows], "total_cycles": float(sum(c for _, _, c in rows)), "method": "three-point rainflow after ASTM E1049-85, residue counted as half cycles"}

    return guarded(run)
