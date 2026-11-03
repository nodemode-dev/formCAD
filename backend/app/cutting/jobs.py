import threading
import time
import uuid

from app.cutting.nest import Cancelled

MAX_KEPT = 12
GAP = 0.2
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


class Job:
    def __init__(self, doc_id):
        self.id = uuid.uuid4().hex[:12]
        self.doc_id = doc_id
        self.state = "queued"
        self.message = ""
        self.progress = {"fraction": 0.0, "message": ""}
        self.result = None
        self.stop = threading.Event()
        self.created = time.time()
        self.finished = None
        self.last = 0.0

    def view(self):
        return {"id": self.id, "doc": self.doc_id, "state": self.state, "message": self.message, "progress": dict(self.progress), "result": self.result, "created": self.created, "finished": self.finished}

    def cancelled(self):
        return self.stop.is_set()

    def report(self, fraction, message=""):
        self.progress = {"fraction": round(fraction, 4), "message": message}
        now = time.monotonic()
        if now - self.last >= GAP:
            self.last = now
            publish(self, "progress")


def publish(job, phase):
    from app.doc import events

    events.publish({"type": "cam", "id": job.doc_id, "job": job.id, "kind": "nest", "state": job.state, "phase": phase, "progress": dict(job.progress)})


def start(doc_id, fn):
    with LOCK:
        for j in JOBS.values():
            if j.doc_id == doc_id and j.state in ("queued", "running"):
                raise ValueError("A nesting job is already running on this document. Stop it first.")
        job = Job(doc_id)
        JOBS[job.id] = job
        ORDER.append(job.id)
        while len(ORDER) > MAX_KEPT:
            old = ORDER.pop(0)
            JOBS.pop(old, None)

    def body():
        job.state = "running"
        publish(job, "start")
        try:
            job.result = fn(job)
            job.state = "done"
        except Cancelled:
            job.state = "cancelled"
            job.message = "Stopped."
        except Exception as err:
            job.state = "failed"
            job.message = str(err)
        job.finished = time.time()
        publish(job, "end")

    threading.Thread(target=body, daemon=True).start()
    return job


def get(jid):
    with LOCK:
        return JOBS.get(jid)
