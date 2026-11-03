import contextvars
import json
import threading
import time
import uuid

import numpy as np

from app.cmd import barred
from app.doc import events
from app.sim import records
from app.sim import study as sim_study
from app.topo import outcome, outer, study as topo_study
from app.topo.grid import Cancelled, TopoError

PROGRESS_GAP = 0.2
KEPT = 24
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


class Job:
    def __init__(self, doc, study_id: str, kind: str, restrict: bool, overrides: dict):
        self.id = uuid.uuid4().hex[:12]
        self.doc = doc
        self.doc_id = getattr(doc, "id", "")
        self.study = study_id
        self.kind = kind
        self.restrict = restrict
        self.overrides = overrides or {}
        self.state = "queued"
        self.phase = ""
        self.progress = 0.0
        self.message = ""
        self.result = None
        self.live = {}
        self.started = time.time()
        self.finished = None
        self.stop = threading.Event()
        self.deadline = self.started + float(self.overrides.get("seconds") or topo_study.cap(restrict, "seconds"))
        self.deadline = min(self.deadline, self.started + topo_study.cap(restrict, "seconds"))
        self.thread = None
        self._last = 0.0

    def view(self) -> dict:
        return {"job": self.id, "id": self.doc_id, "study": self.study, "kind": self.kind, "state": self.state, "phase": self.phase, "progress": round(self.progress, 4), "message": self.message, "live": dict(self.live), "result": self.result, "started": self.started, "finished": self.finished}

    def publish(self) -> None:
        events.publish({"type": "topojob", **self.view()})

    def cancelled(self) -> bool:
        if self.stop.is_set():
            return True
        if time.time() > self.deadline:
            self.message = "The study ran past its time budget and was stopped."
            self.stop.set()
            return True
        return False

    def step(self, phase: str, fraction: float, info: dict = None) -> None:
        self.phase = phase
        self.progress = max(0.0, min(1.0, float(fraction)))
        if info:
            self.live = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in info.items()}
        now = time.monotonic()
        if now - self._last >= PROGRESS_GAP:
            self._last = now
            self.state = "running"
            self.publish()

    def run(self) -> None:
        self.state = "running"
        self.publish()
        try:
            if self.kind == "shape":
                from app.topo import shape

                self.result = shape.execute(self.doc, self.study, self.overrides, self, self.restrict)
            else:
                self.result = execute(self.doc, self.study, self.overrides, self, self.restrict)
            self.state = "done"
            self.progress = 1.0
        except Cancelled as err:
            self.state = "cancelled"
            self.message = self.message or str(err)
        except (TopoError, records.SimRecordError, KeyError, ValueError, MemoryError) as err:
            self.state = "error"
            self.message = str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err)
        except Exception as err:
            self.state = "error"
            self.message = "The optimisation failed (%s)." % err
        self.finished = time.time()
        self.publish()


def active(doc_id: str):
    with LOCK:
        for jid in ORDER:
            j = JOBS.get(jid)
            if j is not None and j.doc_id == doc_id and j.state in ("queued", "running"):
                return j
    return None


def start(doc, study_id: str, kind: str = "topology", restrict: bool = False, overrides: dict = None) -> dict:
    with LOCK:
        busy = active(getattr(doc, "id", ""))
        if busy is not None:
            raise TopoError("Another optimisation (%s) is still running on this document." % busy.study)
        job = Job(doc, study_id, kind, restrict, overrides)
        JOBS[job.id] = job
        ORDER.append(job.id)
        while len(ORDER) > KEPT:
            old = ORDER.pop(0)
            if JOBS.get(old) is not None and JOBS[old].state in ("queued", "running"):
                ORDER.append(old)
                break
            JOBS.pop(old, None)
    scope = contextvars.copy_context()
    job.thread = threading.Thread(target=lambda: scope.run(job.run), name="formcad-topo-job", daemon=True)
    job.thread.start()
    return job.view()


def get(job_id: str) -> Job:
    with LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise TopoError("There is no job %s." % job_id)
    return job


def view(job_id: str) -> dict:
    return get(job_id).view()


def cancel(job_id: str) -> dict:
    job = get(job_id)
    job.stop.set()
    return job.view()


def wait(job_id: str, timeout: float = 3600.0) -> dict:
    job = get(job_id)
    if job.thread is not None:
        job.thread.join(timeout)
    return job.view()


def restricted(runner=None) -> bool:
    return bool(barred.caller(runner))


class Inline:
    def __init__(self, restrict: bool, overrides: dict = None):
        self.stop = threading.Event()
        self.deadline = time.time() + topo_study.cap(restrict, "seconds")
        self.message = ""

    def step(self, phase: str, fraction: float, info: dict = None) -> None:
        return None

    def cancelled(self) -> bool:
        if time.time() > self.deadline:
            self.message = "The study ran past its time budget and was stopped."
            return True
        return False


def execute(doc, study_id: str, overrides: dict, ctl: Job, restrict: bool) -> dict:
    parts = compute(doc, study_id, overrides, ctl, restrict)
    ctl.step("Storing the result", 0.98)
    with doc.lock:
        with doc.transaction("TOPORUN"):
            return store(doc.drawing, parts)


def compute(doc, study_id: str, overrides: dict, ctl, restrict: bool) -> dict:
    ctl.step("Reading the study", 0.0)
    with doc.lock:
        snap = topo_study.snapshot(doc, study_id)
    ctl.step("Building the design grid", 0.01)
    setup = topo_study.resolve(snap, restrict, overrides)
    ctl.step("Optimising", 0.02, {"unknowns": setup.grid.ndof, "cells": setup.grid.ne})
    try:
        out = outer.run(setup.problem, setup.spec, setup.bounds, ctl.step, ctl.cancelled)
    except Cancelled as err:
        raise Cancelled(ctl.message or str(err))
    summary = out.summary()
    summary["grid"] = setup.grid.dims()
    summary["cells_design"] = setup.info["cells_design"]
    summary["cells_preserved"] = setup.info["cells_preserved"]
    summary["notes"] = list(summary["notes"]) + list(setup.info["notes"])
    summary["material"] = setup.info["material"]
    summary["initial_mass_cad_kg"] = setup.info["body_volume_mm3"] * setup.info["material"]["rho_kg_mm3"]
    meta = {"summary": summary, "options": setup.spec, "study": study_id}
    data = outcome.pack(setup.grid, out.xphys, out.solid, out.final.vm if out.final.vm is not None else np.zeros(setup.grid.ne), setup.problem.cls, out.history, meta)
    clean = json.loads(json.dumps(summary, default=float))
    return {"study": study_id, "data": data, "summary": clean}


FIELDS = [{"name": "density", "unit": "", "location": "voxel", "components": 1}, {"name": "solid", "unit": "", "location": "voxel", "components": 1}, {"name": "vm", "unit": "MPa", "location": "voxel", "components": 1}]


def store(d, parts: dict) -> dict:
    study_id = parts["study"]
    key = sim_study.put_blob(d, parts["data"])
    for old in records.of_kind(d, "result"):
        if old.get("study") == study_id:
            d.table_remove(records.TABLE, old["id"])
    res = records.put_result(d, {"study": study_id, "type": "topology", "blob": key, "summary": parts["summary"], "fields": FIELDS, "modes": [], "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())})
    row = records.get(d, study_id)
    row["result"] = res["id"]
    row["status"] = "solved"
    d.table_set(records.TABLE, row)
    return {"study": study_id, "result": res["id"], "summary": parts["summary"]}
