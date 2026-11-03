import threading
import time
import uuid

from app.solid.work import SolidError

MAX_KEPT = 8
PROGRESS_GAP = 0.15
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


class JobError(ValueError):
    pass


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, doc_id: str, kind: str, study: str):
        self.id = uuid.uuid4().hex[:12]
        self.doc_id = doc_id
        self.kind = kind
        self.study = study
        self.state = "queued"
        self.message = ""
        self.progress = {"fraction": 0.0, "t": 0.0, "frames": 0, "elapsed": 0.0}
        self.result = None
        self.frames: list = []
        self.states: list = []
        self.created = time.time()
        self.finished = None
        self.stop = threading.Event()
        self.thread = None
        self.started = 0.0
        self.last_report = 0.0

    def view(self) -> dict:
        out = {"id": self.id, "doc": self.doc_id, "kind": self.kind, "study": self.study, "state": self.state, "message": self.message, "progress": dict(self.progress), "created": self.created, "finished": self.finished, "frames": len(self.frames)}
        if self.result is not None:
            out["result"] = self.result
        return out

    def check(self) -> None:
        if self.stop.is_set():
            raise Cancelled()

    def report(self, force=False, **fields) -> None:
        now = time.monotonic()
        self.progress.update(fields)
        self.progress["elapsed"] = round(now - self.started, 3) if self.started else 0.0
        self.progress["frames"] = len(self.frames)
        if force or now - self.last_report >= PROGRESS_GAP:
            self.last_report = now
            publish(self, "progress")


def publish(job: Job, phase: str) -> None:
    from app.doc import events

    events.publish({"type": "motion", "id": job.doc_id, "job": job.id, "kind": job.kind, "study": job.study, "state": job.state, "phase": phase, "progress": dict(job.progress)})


def evict() -> None:
    while len(ORDER) > MAX_KEPT:
        old = ORDER.pop(0)
        job = JOBS.get(old)
        if job is not None and job.state in ("running", "queued"):
            ORDER.append(old)
            break
        JOBS.pop(old, None)


def start(doc, kind: str, study: str, prepare, wait: bool = False) -> Job:
    with LOCK:
        for j in JOBS.values():
            if j.doc_id == doc.id and j.state in ("queued", "running"):
                raise JobError("A motion job is already running on this document. Stop it first.")
    with doc.lock:
        worker = prepare(doc)
    job = Job(doc.id, kind, study)
    with LOCK:
        JOBS[job.id] = job
        ORDER.append(job.id)
        evict()

    def body():
        job.state = "running"
        job.started = time.monotonic()
        publish(job, "start")
        try:
            job.result = worker(job)
            job.state = "cancelled" if job.result.get("cancelled") else "done"
            job.message = job.result.get("message", "")
        except Cancelled:
            job.state = "cancelled"
            job.message = "Stopped."
            job.result = job.result or {"frames": len(job.frames), "cancelled": True, "stopped": None, "plots": [], "contacts": []}
        except Exception as err:
            job.state = "failed"
            job.message = str(err) if isinstance(err, (ValueError, SolidError)) else "%s: %s" % (type(err).__name__, err)
        job.finished = time.time()
        job.progress["elapsed"] = round(time.monotonic() - job.started, 3)
        job.progress["fraction"] = 1.0 if job.state == "done" else job.progress.get("fraction", 0.0)
        publish(job, "end")

    job.thread = threading.Thread(target=body, name="motion-%s" % job.id, daemon=True)
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
