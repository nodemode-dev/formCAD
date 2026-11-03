import copy
import math
import threading
import time
import uuid

import numpy as np

from app.cam import gen, limits, model, store
from app.cam import toolpath as T
from app.cam.limits import CamError, Cancelled
from app.cam3d import machines, simulate, simulate5

WINDOW = {"sim_cells": 4_000_000, "sim_moves": 2_000_000, "sim_voxels": 8_000_000, "sim_samples": 6_000_000, "sim_time_s": 600.0}
AGENT = {"sim_cells": 1_000_000, "sim_moves": 400_000, "sim_voxels": 2_000_000, "sim_samples": 1_000_000, "sim_time_s": 120.0}
MAX_KEPT = 6
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


def sim_limits() -> dict:
    return dict(AGENT if limits.limited() else WINDOW)


class SimJob:
    def __init__(self, doc_id):
        self.id = uuid.uuid4().hex[:12]
        self.doc_id = doc_id
        self.state = "queued"
        self.progress = 0.0
        self.phase = ""
        self.message = ""
        self.result = None
        self.state_data = None
        self.stop = threading.Event()
        self.started = 0.0
        self.last = 0.0
        self.limit_s = 600.0

    def check(self):
        if self.stop.is_set():
            raise Cancelled()
        if self.limit_s and time.monotonic() - self.started > self.limit_s:
            raise CamError("The simulation stopped after %d s (time limit). Use a larger cell." % int(self.limit_s))

    def report(self, f):
        self.progress = round(max(0.0, min(1.0, f)), 4)
        now = time.monotonic()
        if now - self.last > 0.2:
            self.last = now
            self.publish("progress")

    def set_phase(self, p):
        self.phase = p
        self.publish("progress")

    def publish(self, phase):
        from app.doc import events

        events.publish({"type": "cam", "reason": "simulate", "id": self.doc_id, "job": self.id, "state": self.state, "phase": phase, "progress": {"fraction": self.progress, "phase": self.phase}})

    def view(self, with_result=True):
        out = {"job": self.id, "doc": self.doc_id, "state": self.state, "progress": self.progress, "phase": self.phase, "message": self.message}
        if with_result and self.result is not None:
            out["result"] = self.result
        return out


def vertical(moves) -> bool:
    for m in moves:
        o = T.opts_of(m) if m and m[0] in ("rapid", "feed", "arc") else {}
        ax = o.get("ax")
        if ax and (abs(ax[0]) > 1e-9 or abs(ax[1]) > 1e-9 or ax[2] < 0):
            return False
    return True


def gather(doc, setup_id, op_ids, cell, tol, machine_id):
    d = doc.drawing
    lim = sim_limits()
    with doc.lock:
        if not setup_id:
            ss = model.setups(d)
            if not ss:
                raise CamError("There is no setup to simulate.")
            setup_id = ss[0]["id"]
        setup = copy.deepcopy(model.get_setup(d, setup_id))
        ids = [str(o) for o in op_ids] if op_ids else [o for o in setup["ops"] if model.get_op(d, o).get("enabled", True)]
        if not ids:
            raise CamError("There are no operations to simulate.")
        sb = model.stock_box(doc, setup)
        poly = model.stock_polygon(doc, setup)
        tris = model.setup_triangles(doc, setup)
        fix = model.fixture_triangles(doc, setup)
        rows = []
        for oid in ids:
            op = copy.deepcopy(model.get_op(d, oid))
            if op["setup"] != setup_id:
                raise CamError("Operation %s belongs to setup %s." % (oid, op["setup"]))
            rows.append((oid, op, store.tool_record(copy.deepcopy(model.get_tool(d, op["tool"])))))
    ops = []
    dmin = 1e9
    multi = False
    for oid, op, rec in rows:
        path = gen.toolpath_of(doc, oid, True)
        mv = [list(m) for m in path.moves]
        if not vertical(mv):
            multi = True
        dmin = min(dmin, float(rec.get("diameter") or 6.0))
        ops.append({"id": oid, "moves": mv, "tool": rec, "machine": setup.get("machine_profile") or {}})
    if not cell or cell <= 0:
        cell = max(tol, dmin / 12.0, 0.05)
    stock = {"min": sb["min"], "max": sb["max"], "polygon": poly, "kind": sb.get("kind")}
    if setup.get("stock", {}).get("kind") in ("cylinder", "tube"):
        stock["kind"] = setup["stock"]["kind"]
    inp = {"cell": cell, "stock": stock, "tris": tris, "fixtures": fix, "gouge_tol": tol, "ops": ops, "limits": lim}
    return inp, multi, setup_id


def start(doc, body: dict, wait=False) -> SimJob:
    with LOCK:
        for j in JOBS.values():
            if j.doc_id == doc.id and j.state in ("queued", "running"):
                raise CamError("A simulation is already running on this document.")
    tol = float(body.get("gouge_tolerance", 0.01))
    if not 0.0005 <= tol <= 5.0:
        raise CamError("The gouge tolerance is between 0.0005 and 5 mm.")
    cell = float(body.get("cell", 0.0) or 0.0)
    if cell and not 0.02 <= cell <= 50.0:
        raise CamError("The cell is between 0.02 and 50 mm.")
    inp, multi, sid = gather(doc, body.get("setup"), body.get("ops"), cell, float(body.get("tolerance", 0.01)) if False else tol, body.get("machine"))
    inp["snapshots"] = max(0, min(int(body.get("snapshots", 24)), 60))
    if multi:
        inp["machine"] = machines.get(body.get("machine") or "mill5_table_table")
        inp["snapshots"] = min(inp["snapshots"], 20)
    job = SimJob(doc.id)
    job.limit_s = inp["limits"]["sim_time_s"]
    with LOCK:
        JOBS[job.id] = job
        ORDER.append(job.id)
        while len(ORDER) > MAX_KEPT:
            old = ORDER.pop(0)
            j = JOBS.get(old)
            if j is not None and j.state in ("queued", "running"):
                ORDER.append(old)
                break
            JOBS.pop(old, None)

    def work():
        job.state = "running"
        job.started = time.monotonic()
        job.publish("start")
        try:
            fn = simulate5.run if multi else simulate.run
            out = fn(inp, job.check, job.report, job.set_phase)
            job.result = out["result"]
            job.result["setup"] = sid
            job.state_data = out["state"]
            job.state_data["tools"] = [o["tool"] for o in inp["ops"]]
            job.state = "done"
            job.progress = 1.0
        except Cancelled:
            job.state = "cancelled"
        except Exception as err:
            job.state = "failed"
            job.message = str(err) if isinstance(err, (CamError, ValueError)) else "%s: %s" % (type(err).__name__, err)
        job.publish("end")

    t = threading.Thread(target=work, name="sim-%s" % job.id, daemon=True)
    t.start()
    if wait:
        t.join()
    return job
