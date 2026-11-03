import contextvars
import threading
import time
import uuid

from app.cam import gen, model
from app.cam.limits import CamError, Cancelled

MAX_KEPT = 12
PROGRESS_GAP = 0.15
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


class Job:
    def __init__(self, doc_id: str, ops: list):
        self.id = uuid.uuid4().hex[:12]
        self.doc_id = doc_id
        self.ops = ops
        self.state = "queued"
        self.message = ""
        self.progress = {"fraction": 0.0, "op": "", "done": 0, "total": len(ops), "elapsed": 0.0}
        self.results: dict = {}
        self.created = time.time()
        self.finished = None
        self.stop = threading.Event()
        self.thread = None
        self.started = 0.0
        self.last_report = 0.0

    def view(self) -> dict:
        return {"id": self.id, "doc": self.doc_id, "state": self.state, "message": self.message, "progress": dict(self.progress), "results": self.results, "ops": list(self.ops), "created": self.created, "finished": self.finished}

    def check(self) -> None:
        if self.stop.is_set():
            raise Cancelled()

    def report(self, force=False, op_fraction=None, **fields) -> None:
        now = time.monotonic()
        if op_fraction is not None:
            total = max(self.progress["total"], 1)
            self.progress["fraction"] = round((self.progress["done"] + max(0.0, min(1.0, op_fraction))) / total, 4)
        self.progress.update(fields)
        self.progress["elapsed"] = round(now - self.started, 3) if self.started else 0.0
        if force or now - self.last_report >= PROGRESS_GAP:
            self.last_report = now
            publish(self, "progress")


def publish(job: Job, phase: str) -> None:
    from app.doc import events

    events.publish({"type": "cam", "id": job.doc_id, "job": job.id, "state": job.state, "phase": phase, "progress": dict(job.progress)})


def evict() -> None:
    while len(ORDER) > MAX_KEPT:
        old = ORDER.pop(0)
        job = JOBS.get(old)
        if job is not None and job.state in ("running", "queued"):
            ORDER.append(old)
            break
        JOBS.pop(old, None)


def start(doc, ops: list, wait: bool = False) -> Job:
    with LOCK:
        for j in JOBS.values():
            if j.doc_id == doc.id and j.state in ("queued", "running"):
                raise CamError("A toolpath job is already running on this document. Stop it first.")
    job = Job(doc.id, ops)
    with LOCK:
        JOBS[job.id] = job
        ORDER.append(job.id)
        evict()

    def body():
        job.state = "running"
        job.started = time.monotonic()
        publish(job, "start")
        failed = 0
        try:
            for i, oid in enumerate(ops):
                job.check()
                job.progress.update({"op": oid, "done": i})
                job.report(True, 0.0)
                try:
                    st = gen.generate_one(doc, oid, job)
                    job.results[oid] = {"status": st["status"], "message": st["message"], "summary": st["summary"], "warnings": st["warnings"]}
                except Cancelled:
                    raise
                except CamError as err:
                    failed += 1
                    job.results[oid] = {"status": "failed", "message": str(err)}
                job.progress["done"] = i + 1
            job.state = "done"
            job.message = "%d of %d operations generated." % (len(ops) - failed, len(ops))
            job.progress["fraction"] = 1.0
        except Cancelled:
            job.state = "cancelled"
            job.message = "Stopped."
        except Exception as err:
            job.state = "failed"
            job.message = "%s: %s" % (type(err).__name__, err)
        job.finished = time.time()
        job.progress["elapsed"] = round(time.monotonic() - job.started, 3)
        publish(job, "end")

    scope = contextvars.copy_context()
    job.thread = threading.Thread(target=lambda: scope.run(body), name="cam-%s" % job.id, daemon=True)
    job.thread.start()
    if wait:
        job.thread.join()
    return job


def get(job_id: str):
    return JOBS.get(job_id)


def cancel(job_id: str) -> bool:
    job = JOBS.get(job_id)
    if job is None:
        return False
    job.stop.set()
    return True


def listing(doc_id=None) -> list:
    return [j.view() for j in JOBS.values() if doc_id is None or j.doc_id == doc_id]


def ops_for(doc, setup=None, ops=None) -> list:
    d = doc.drawing
    if ops:
        out = []
        for oid in ops:
            op = model.get_op(d, str(oid))
            out.append(op["id"])
        return out
    out = []
    for s in model.setups(d):
        if setup and s["id"] != setup:
            continue
        for oid in s["ops"]:
            if model.get_op(d, oid).get("enabled", True):
                out.append(oid)
    if not out:
        raise CamError("There are no operations to generate.")
    return out
