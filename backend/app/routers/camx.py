import copy
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cam import export as cam_export
from app.cam import gen, model, post, store
from app.cam import hook as _hook  # noqa: F401
from app.cam.limits import CamError
from app.cam.ops import cut_ops, live_ops, probe_ops, turn_ops  # noqa: F401
from app.core import outputs
from app.cutting import jobs as njobs
from app.cutting import process as PR
from app.cutting import records, service
from app.cutting.shapes import CutError
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service as docs
from app.probing import cycles as PC
from app.probing import expr as PE
from app.probing import sim as PS
from app.turning import millturn
from app.turning import profile as PF
from app.turning.profile import TurnError

router = APIRouter(tags=["camx"])
GUARDED = (CamError, CutError, TurnError, PC.ProbeError, PE.ExprError, PS.SimError, CommandFailed, ValueError, KeyError)


class Body(BaseModel):
    model_config = {"extra": "allow"}


class NestIn(BaseModel):
    model_config = {"extra": "allow"}
    parts: Optional[list[dict[str, Any]]] = None
    from_flat: Optional[dict[str, Any]] = None
    from_outlines: Optional[dict[str, Any]] = None
    dxf: Optional[list[dict[str, Any]]] = None
    sheets: list[dict[str, Any]]
    clearance: float = 0.0
    kerf: float = 0.0
    margin: float = 5.0
    seconds: float = 20.0
    restarts: int = 8
    seed: int = 1
    rotations: Optional[list[float]] = None
    defects: Optional[list[list[list[float]]]] = None
    id: Optional[str] = None
    wait: bool = True


class PlanIn(BaseModel):
    process: Any
    sheet: Optional[int] = None
    order: str = "part"
    home_x: float = 0.0
    home_y: float = 0.0


class NestExportIn(BaseModel):
    process: Any
    post: str
    path: str
    sheet: Optional[int] = None
    order: str = "part"
    home_x: float = 0.0
    home_y: float = 0.0
    options: Optional[dict[str, Any]] = None


class MachineExportIn(BaseModel):
    path: str
    post: Optional[str] = None
    options: Optional[dict[str, Any]] = None


def _doc(doc_id: str):
    try:
        return docs.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    if isinstance(err, KeyError):
        raise HTTPException(404, str(err.args[0]) if err.args else "Not found.")
    raise HTTPException(400, str(err))


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc.drawing)
        except GUARDED as err:
            _fail(err)


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    try:
        with doc.lock:
            return fn(doc)
    except GUARDED as err:
        _fail(err)


def _view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in ("name",)}


@router.get("/cam/processes/blank")
def process_blank(kind: str = "laser") -> dict:
    try:
        return PR.blank(kind)
    except GUARDED as err:
        _fail(err)


@router.post("/cam/processes/kerf")
def process_kerf(body: Body) -> dict:
    b = body.model_dump()
    try:
        if b.get("kind") == "plasma":
            return {"kerf": PR.plasma_kerf(float(b["amps"])), "source": "Hypertherm hole quality page: about 2 mm at 100 A and 3 mm at 200 A, linear between and beyond"}
        if b.get("kind") == "waterjet":
            return {"kerf": PR.waterjet_kerf(float(b["tube"])), "source": "Flow International dictionary: about 10 percent above the mixing tube diameter"}
    except GUARDED as err:
        _fail(err)
    except (TypeError, KeyError):
        raise HTTPException(400, "Give kind plasma with amps, or waterjet with tube.")
    raise HTTPException(400, "Kerf formulas exist for plasma and waterjet; laser and router kerf is measured by the user.")


@router.get("/docs/{doc_id}/cam/processes")
def list_processes(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"processes": [_view(r) for r in records.processes(doc.drawing)]})


@router.post("/docs/{doc_id}/cam/processes")
def add_process(doc_id: str, body: Body) -> dict:
    return _view(_edit(doc_id, "Add cutting process", lambda d: records.add_process(d, body.model_dump())))


@router.put("/docs/{doc_id}/cam/processes/{pid}")
def put_process(doc_id: str, pid: str, body: Body) -> dict:
    return _view(_edit(doc_id, "Edit cutting process", lambda d: records.update_process(d, pid, body.model_dump())))


@router.delete("/docs/{doc_id}/cam/processes/{pid}")
def del_process(doc_id: str, pid: str) -> dict:
    _edit(doc_id, "Delete cutting process", lambda d: records.delete_process(d, pid))
    return {"deleted": pid}


@router.get("/docs/{doc_id}/cam/nest/sources")
def nest_sources(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: service.sources_view(doc.drawing))


@router.post("/docs/{doc_id}/cam/nest")
def run_nest(doc_id: str, body: NestIn) -> dict:
    doc = _doc(doc_id)
    req = body.model_dump()
    agent = service.limits_agent()
    try:
        with doc.lock:
            parts = service.build_parts(doc.drawing, req)
    except GUARDED as err:
        _fail(err)

    def work(job=None):
        res = service.run_nest(parts, req, agent, job.report if job else None, job.cancelled if job else None)
        with doc.lock:
            if doc.get_runner().run is not None:
                raise ValueError("A command is running; finish it first.")
            with doc.transaction("Nest parts"):
                rec = records.put_nest(doc.drawing, req.get("id"), service.nest_record(parts, req, res))
        return service.summary(rec)

    if not req.get("wait", True):
        try:
            job = njobs.start(doc_id, work)
        except ValueError as err:
            raise HTTPException(409, str(err))
        return {"job": job.id, "state": job.state}
    try:
        return work()
    except GUARDED as err:
        _fail(err)


@router.get("/docs/{doc_id}/cam/nest/jobs/{jid}")
def nest_job(doc_id: str, jid: str) -> dict:
    job = njobs.get(jid)
    if job is None or job.doc_id != doc_id:
        raise HTTPException(404, "There is no such nesting job.")
    return job.view()


@router.post("/docs/{doc_id}/cam/nest/jobs/{jid}/cancel")
def nest_cancel(doc_id: str, jid: str) -> dict:
    job = njobs.get(jid)
    if job is None or job.doc_id != doc_id:
        raise HTTPException(404, "There is no such nesting job.")
    job.stop.set()
    return {"job": jid, "state": job.state}


@router.get("/docs/{doc_id}/cam/nests")
def list_nests(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"nests": [service.summary(r) for r in records.nests(doc.drawing)]})


@router.get("/docs/{doc_id}/cam/nests/{nid}")
def get_nest(doc_id: str, nid: str) -> dict:
    def fn(doc):
        rec = records.get_nest(doc.drawing, nid)
        out = service.summary(rec)
        out["request"] = rec["request"]
        out["sheets_detail"] = rec["result"]["sheets"]
        out["parts"] = [{"name": p["name"], "qty": p["qty"], "area": p["area"], "rotations": p["rotations"]} for p in rec["parts"]]
        return out

    return _read(doc_id, fn)


@router.get("/docs/{doc_id}/cam/nests/{nid}/shapes")
def nest_shapes(doc_id: str, nid: str, sheet: int = 1) -> dict:
    from app.cutting import layout

    def fn(doc):
        rec = records.get_nest(doc.drawing, nid)
        sheets = rec["result"]["sheets"]
        if not 1 <= sheet <= len(sheets):
            raise CutError("The nest has %d sheets." % len(sheets))
        sh = sheets[sheet - 1]
        parts = layout.world_parts(rec["parts"], sh)
        return {"sheet": sheet, "width": sh["width"], "height": sh["height"], "parts": [{"name": p["name"], "loops": [{"pts": [[round(x, 3), round(y, 3)] for x, y in l["pts"]], "outer": l["outer"]} for l in p["loops"]]} for p in parts]}

    return _read(doc_id, fn)


@router.delete("/docs/{doc_id}/cam/nests/{nid}")
def del_nest(doc_id: str, nid: str) -> dict:
    _edit(doc_id, "Delete nest", lambda d: records.delete_nest(d, nid))
    return {"deleted": nid}


@router.post("/docs/{doc_id}/cam/nests/{nid}/plan")
def plan_nest(doc_id: str, nid: str, body: PlanIn) -> dict:
    def fn(doc):
        res = service.plan(doc.drawing, nid, body.process, body.sheet, body.order, (body.home_x, body.home_y))
        proc = service.process_for(doc.drawing, body.process)
        return {"sheets": [{"sheet": r["sheet"], "parts": r["parts"], "moves": len(r["moves"]), "stats": r["stats"], "warnings": r["warnings"], "order": [list(o) for o in r["order"]], "time": service.estimate(r, proc), "toolpath": r["moves"]} for r in res]}

    return _read(doc_id, fn)


@router.post("/docs/{doc_id}/cam/nests/{nid}/export")
def export_nest(doc_id: str, nid: str, body: NestExportIn) -> dict:
    def fn(doc):
        return service.export(doc.drawing, getattr(doc, "name", "FORMCAD"), nid, body.process, body.post, body.path, body.sheet, body.order, (body.home_x, body.home_y), body.options)

    try:
        return _read(doc_id, fn)
    except outputs.OutputRefused as err:
        raise HTTPException(400, str(err))


@router.post("/cam/turning/profile")
def turning_profile(body: Body) -> dict:
    spec = body.model_dump()
    try:
        prof = PF.build(spec.get("profile") or spec)
    except (GUARDED + (TypeError,)) as err:
        _fail(err)
    pts = prof["pts"]
    return {"pts": [[round(z, 4), round(r, 4)] for z, r in pts], "monotonic": PF.check_direction(prof), "max_diameter": 2 * max(r for _, r in pts), "length": pts[0][0] - pts[-1][0]}


@router.post("/cam/turning/thread")
def turning_thread(body: Body) -> dict:
    b = body.model_dump()
    try:
        pitch = float(b["pitch"])
        n = int(b.get("passes", 6))
        if pitch <= 0 or not 1 <= n <= 40:
            raise ValueError("Pitch above zero and 1 to 40 passes.")
    except (KeyError, TypeError, ValueError) as err:
        raise HTTPException(400, str(err))
    depth = float(b.get("depth") or 0.6134 * pitch)
    return {"depth": depth, "pass_depths": [round(depth * (k / n) ** 0.5, 4) for k in range(1, n + 1)], "formula": "0.6134 times the pitch (17/24 of the thread triangle height), depth of pass k = depth times the square root of k over n"}


@router.get("/cam/probing/cycles")
def probing_cycles() -> dict:
    return {"cycles": [{"kind": k, "defaults": PC.defaults(k), "limits": {n: list(v) for n, v in PC.LIMITS.items()}} for k in PC.KINDS], "parameters": "G38 contact in #5061 to #5063; work offset blocks #5221 + 20 per slot (X Y Z), rotation 9 above"}


@router.post("/cam/probing/build")
def probing_build(body: Body) -> dict:
    b = body.model_dump()
    try:
        return PC.build(str(b.get("kind")), b.get("params") or {})
    except GUARDED as err:
        _fail(err)


@router.post("/cam/probing/simulate")
def probing_simulate(body: Body) -> dict:
    b = body.model_dump()
    try:
        built = PC.build(str(b.get("kind")), b.get("params") or {})
        w = b.get("world") or {}
        solids_in = w.get("solids") or []
        if not 1 <= len(solids_in) <= 50:
            raise ValueError("The virtual part has 1 to 50 solids.")
        if sum(len(s.get("pts") or []) for s in solids_in) > 2000:
            raise ValueError("The virtual part has more than 2000 points.")
        solids = []
        for s in solids_in:
            z0, z1 = float(s["z0"]), float(s["z1"])
            if s.get("kind") == "circle":
                solids.append(PS.Solid("circle", z0, z1, c=tuple(s["c"]), r=float(s["r"])))
            else:
                solids.append(PS.Solid("poly", z0, z1, pts=[tuple(p) for p in s["pts"]], holes=[{"c": tuple(h["c"]), "r": float(h["r"])} for h in s.get("holes", [])]))
        radius = built["params"]["radius"]
        world = PS.World(solids, [float(v) for v in w.get("origin", [0, 0, 0])], radius)
        start = [float(v) for v in w.get("start", [0, 0, built["params"]["clearance"]])]
        res = PS.run(built["moves"], world, start)
    except GUARDED as err:
        _fail(err)
    outs = {k: res["env"].get(k) for k in built["outputs"]}
    return {"outputs": outs, "origin": res["origin"], "rotation": res["rot"], "crashes": len(res["crashes"]), "probes": res["probes"]}


@router.get("/docs/{doc_id}/cam/machines")
def list_machines(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"machines": [_view(r) for r in millturn.machines(doc.drawing)]})


@router.put("/docs/{doc_id}/cam/machines/{mid}")
def put_machine(doc_id: str, mid: str, body: Body) -> dict:
    def fn(d):
        return _view(millturn.put_machine(d, None if mid == "new" else mid, body.model_dump()))

    return _edit(doc_id, "Edit machine", fn)


@router.post("/docs/{doc_id}/cam/machines/{mid}/check")
def check_machine(doc_id: str, mid: str) -> dict:
    return _read(doc_id, lambda doc: millturn.check(doc.drawing, mid))


@router.post("/docs/{doc_id}/cam/machines/{mid}/export")
def export_machine(doc_id: str, mid: str, body: MachineExportIn) -> dict:
    def fn(doc):
        d = doc.drawing
        chk = millturn.check(d, mid)
        if not chk["ok"]:
            raise CamError("The machine check found errors: %s" % "; ".join(i["text"] for i in chk["issues"] if i["level"] == "error")[:400])
        mach = millturn.get_machine(d, mid)
        post_id = body.post or mach["post"]
        items = []
        prev = None
        for row in chk["setups"]:
            setup_rec = copy.deepcopy(model.get_setup(d, row["setup"]))
            if prev is None or millturn.assignment(prev)["mode"] != row["mode"]:
                from app.cam import toolpath as T

                items.append({"setup": setup_rec, "op": {"id": "MODE", "label": "Mode change"}, "toolpath": T.Toolpath(millturn.mode_item(prev, setup_rec, mach), {}), "tool": {}})
            prev = setup_rec
            enabled = [o for o in setup_rec["ops"] if model.get_op(d, o).get("enabled", True)]
            if enabled:
                items.extend(cam_export.items_for(doc, setup_rec["id"], enabled))
        opt = dict(body.options or {})
        opt.setdefault("program", getattr(doc, "name", "FORMCAD"))
        opt.setdefault("date", "")
        res = post.generate(items, post_id, opt)
        spec = post.load(post_id)
        path = outputs.checked(body.path, cam_export.ALLOWED, spec["extension"])
        with open(path, "w", encoding="ascii", errors="replace", newline="\n") as fh:
            fh.write(res["text"])
        return {"path": path, "lines": res["lines"], "warnings": res["warnings"], "post": post_id, "setups": [r["setup"] for r in chk["setups"]]}

    doc = _doc(doc_id)
    try:
        return fn(doc)
    except GUARDED as err:
        _fail(err)
    except outputs.OutputRefused as err:
        raise HTTPException(400, str(err))
