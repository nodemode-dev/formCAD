import base64
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cam import limits
from app.cam.limits import CamError
from app.cam3d import kinematics, machines, simjob
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["cam3d"])
GUARDED = (CamError, ValueError, KeyError)


class Body(BaseModel):
    model_config = {"extra": "allow"}


class SimIn(BaseModel):
    setup: Optional[str] = None
    ops: Optional[list[str]] = None
    cell: float = 0.0
    tolerance: float = 0.01
    gouge_tolerance: float = 0.01
    machine: Optional[str] = None
    snapshots: int = 24
    wait: bool = False


def fail(err):
    if isinstance(err, KeyError):
        raise HTTPException(404, str(err.args[0]) if err.args else "Not found.")
    raise HTTPException(400, str(err))


def doc_of(doc_id):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def machine_of(mid):
    try:
        return kinematics.TableTable(machines.get(mid))
    except GUARDED as err:
        fail(err)


@router.get("/cam/machines")
def list_machines() -> dict:
    return {"machines": machines.listing()}


@router.get("/cam/machines/{mid}")
def get_machine(mid: str) -> dict:
    try:
        return machines.get(mid)
    except GUARDED as err:
        fail(err)


@router.put("/cam/machines/{mid}")
def put_machine(mid: str, body: Body) -> dict:
    try:
        return machines.save(mid, body.model_dump())
    except GUARDED as err:
        fail(err)


@router.delete("/cam/machines/{mid}")
def delete_machine(mid: str) -> dict:
    try:
        machines.remove(mid)
    except GUARDED as err:
        fail(err)
    return {"ok": True}


@router.post("/cam/machines/{mid}/solve")
def solve(mid: str, body: Body) -> dict:
    m = machine_of(mid)
    data = body.model_dump()
    pts = data.get("points") or []
    if not isinstance(pts, list) or len(pts) > 20000:
        raise HTTPException(400, "Give up to 20000 points.")
    prev = data.get("previous") or {"a": 0.0, "c": 0.0}
    out = []
    try:
        for pt in pts:
            p, k = pt["p"], pt["k"]
            try:
                s = m.solve(p, k, prev)
                s["ok"] = not m.in_travel((s["x"], s["y"], s["z"]))
                s["reason"] = "" if s["ok"] else "outside the linear travel"
                prev = {"a": s["a"], "c": s["c"]}
                s["branch"] = "a>=0" if s["a"] >= 0 else "a<0"
            except kinematics.Reach as err:
                s = {"ok": False, "reason": str(err)}
            out.append(s)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Each point needs p and k, three numbers each.")
    return {"solutions": out}


@router.post("/cam/machines/{mid}/forward")
def forward(mid: str, body: Body) -> dict:
    m = machine_of(mid)
    out = []
    try:
        for j in (body.model_dump().get("joints") or [])[:20000]:
            p, k = m.forward(j["x"], j["y"], j["z"], j["a"], j["c"])
            out.append({"tip": p.tolist(), "axis": k.tolist()})
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Each joint set needs x, y, z, a and c.")
    return {"poses": out}


@router.get("/cam/machines/{mid}/pose")
def pose(mid: str, a: float = 0.0, c: float = 0.0, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> dict:
    m = machine_of(mid)
    from app.cam3d.kinematics import rx, rz
    import math

    ra = rx(math.radians(a))
    rc = rz(math.radians(c))
    return {"table_origin": (m.origin - m.arm + ra @ m.arm).tolist(), "table_rotation": (ra @ rc).tolist(), "a_axis_origin": (m.origin - m.arm).tolist(), "tool_tip": [x, y, z], "table": m.rec["table"], "head": m.rec["head"], "travel": m.rec["travel"]}


@router.get("/cam/sim-limits")
def sim_limits() -> dict:
    return simjob.sim_limits()


@router.post("/docs/{doc_id}/cam/simulate")
def simulate_start(doc_id: str, body: SimIn) -> dict:
    doc = doc_of(doc_id)
    try:
        job = simjob.start(doc, body.model_dump(), body.wait)
    except GUARDED as err:
        fail(err)
    return job.view()


def job_of(doc_id, jid):
    j = simjob.JOBS.get(jid)
    if j is None or j.doc_id != doc_id:
        raise HTTPException(404, "There is no simulation %s." % jid)
    return j


@router.get("/docs/{doc_id}/cam/simulate/{jid}")
def simulate_get(doc_id: str, jid: str) -> dict:
    return job_of(doc_id, jid).view()


@router.post("/docs/{doc_id}/cam/simulate/{jid}/cancel")
def simulate_cancel(doc_id: str, jid: str) -> dict:
    job_of(doc_id, jid).stop.set()
    return {"ok": True}


@router.get("/docs/{doc_id}/cam/simulate/{jid}/snapshot/{n}")
def snapshot(doc_id: str, jid: str, n: int) -> dict:
    j = job_of(doc_id, jid)
    st = j.state_data
    if st is None:
        raise HTTPException(409, "The simulation has not finished.")
    if not 0 <= n < len(st["snaps"]):
        raise HTTPException(404, "There is no snapshot %d." % n)
    s = st["snaps"][n]
    if j.result["mode"] == "voxel":
        return {"mode": "voxel", "count": int(len(s)), "points": base64.b64encode(np.ascontiguousarray(s, dtype="<f4").tobytes()).decode()}
    top, bot, gouge = s
    g = st["grid"]
    c = g["cell"] * st["sub"]
    enc = lambda a, t: base64.b64encode(np.ascontiguousarray(a, dtype=t).tobytes()).decode()
    return {"mode": "dexel", "nx": int(top.shape[0]), "ny": int(top.shape[1]), "cell": c, "origin": g["origin"], "layout": "x-major", "top": enc(top, "<f4"), "bottom": enc(bot, "<f4"), "gouge": enc(gouge, "u1")}


@router.get("/docs/{doc_id}/cam/simulate/{jid}/tool/{n}")
def tool_pose(doc_id: str, jid: str, n: int) -> dict:
    j = job_of(doc_id, jid)
    st = j.state_data
    if st is None or not 0 <= n < len(st["poses"]):
        raise HTTPException(404, "There is no pose %d." % n)
    p = st["poses"][n]
    if p is None:
        return {"tip": None}
    if isinstance(p, dict):
        return {"tip": p["tip"], "axis": p["axis"], "op": p["op"]}
    return {"tip": p[0], "axis": [0, 0, 1], "op": p[1], "move": p[2]}
