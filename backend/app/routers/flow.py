from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.flow import duct, fill, fin, limits, pack, stokes, su2
from app.flow.limits import FlowError

router = APIRouter(tags=["flow"])


class Su2Body(BaseModel):
    enabled: Optional[bool] = None
    path: Optional[str] = None
    mpi_path: Optional[str] = None
    ranks: Optional[int] = None


class Calc(BaseModel):
    spec: dict[str, Any]


def guarded(fn):
    try:
        return fn()
    except FlowError as err:
        raise HTTPException(400, str(err))


@router.get("/flow")
def overview() -> dict:
    return {
        "su2": su2.status(),
        "limits": limits.view(),
        "solvers": {"own": {"label": stokes.LABEL, "model": stokes.MODEL}, "su2": {"label": su2.LABEL}},
        "calculators": ["duct", "fin", "sink", "plate_fill", "pack", "warp"],
        "labels": {"duct": duct.LABEL, "fin": fin.LABEL, "fill": fill.LABEL, "pack": pack.LABEL},
    }


@router.get("/flow/su2")
def su2_status() -> dict:
    return su2.status()


@router.put("/flow/su2")
def su2_settings(body: Su2Body) -> dict:
    guarded(lambda: su2.save_settings(body.enabled, body.path, body.mpi_path, body.ranks))
    return su2.status()


@router.post("/flow/duct")
def duct_loss(body: Calc) -> dict:
    return guarded(lambda: duct.run(body.spec))


@router.post("/flow/fin")
def fin_calc(body: Calc) -> dict:
    return guarded(lambda: fin.fin(body.spec))


@router.post("/flow/sink")
def sink_calc(body: Calc) -> dict:
    return guarded(lambda: fin.sink(body.spec))


@router.post("/flow/plate-fill")
def plate_fill(body: Calc) -> dict:
    s = body.spec
    return guarded(lambda: fill.plate_formulas(s.get("length"), s.get("width"), s.get("gap"), s.get("flow"), s.get("eta"), s.get("k"), s.get("n")))


@router.post("/flow/pack")
def pack_calc(body: Calc) -> dict:
    return guarded(lambda: pack.pack(body.spec))


@router.post("/flow/warp")
def warp_calc(body: Calc) -> dict:
    return guarded(lambda: pack.warp(body.spec))
