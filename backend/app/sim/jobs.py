import threading
import time
import uuid

from app.doc import events
from app.services import mesher
from app.services.mesher import MesherError
from app.sim import study
from app.sim.fem import SimError
from app.sim.registry import Cancelled
from app.sim.records import SimRecordError
from app.solid.work import SolidError

PROGRESS_GAP = 0.05
KEPT = 24
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


class Job:
    def __init__(self, doc, study_id: str, mode: str, restrict: bool):
        self.id = uuid.uuid4().hex[:12]
        self.doc = doc
        self.doc_id = getattr(doc, "id", "")
        self.study = study_id
        self.mode = mode
        self.restrict = restrict
        self.state = "queued"
        self.phase = ""
        self.progress = 0.0
        self.message = ""
        self.result = None
        self.started = time.time()
        self.finished = None
        self.stop = threading.Event()
        self.deadline = self.started + study.limits_for(restrict)["seconds"]
        self.thread = None
        self._last = -1.0

    def view(self) -> dict:
        return {"job": self.id, "id": self.doc_id, "study": self.study, "mode": self.mode, "state": self.state, "phase": self.phase, "progress": round(self.progress, 4), "message": self.message, "result": self.result, "started": self.started, "finished": self.finished}

    def publish(self) -> None:
        events.publish({"type": "simjob", **self.view()})

    def step(self, phase: str, fraction: float | None = None) -> None:
        if self.stop.is_set():
            raise Cancelled("The study was cancelled.")
        if time.time() > self.deadline:
            raise Cancelled("The study ran past its time budget and was stopped.")
        self.phase = phase
        if fraction is not None:
            self.progress = max(0.0, min(1.0, float(fraction)))
        if self.progress - self._last >= PROGRESS_GAP or self.progress >= 1.0:
            self._last = self.progress
            self.state = "running"
            self.publish()

    def run(self) -> None:
        self.state = "running"
        self.publish()
        try:
            self.result = study.execute(self.doc, self.study, self.mode, self, self.restrict)
            if self.stop.is_set():
                raise Cancelled("The study was cancelled.")
            self.state = "done"
            self.progress = 1.0
        except Cancelled as err:
            self.state = "cancelled"
            self.message = str(err)
        except (SimError, SimRecordError, MesherError, SolidError, KeyError, ValueError, MemoryError) as err:
            self.state = "cancelled" if self.stop.is_set() else "error"
            self.message = "The study was cancelled." if self.stop.is_set() else str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err)
        except Exception as err:
            self.state = "error"
            self.message = "The study failed (%s)." % err
        self.finished = time.time()
        self.publish()


def active(doc_id: str):
    with LOCK:
        for jid in ORDER:
            j = JOBS.get(jid)
            if j is not None and j.doc_id == doc_id and j.state in ("queued", "running"):
                return j
    return None


def start(doc, study_id: str, mode: str = "run", restrict: bool = False) -> dict:
    if mode not in ("run", "mesh"):
        raise SimError("A job mode is run or mesh.")
    with LOCK:
        busy = active(getattr(doc, "id", ""))
        if busy is not None:
            raise SimError("Another study (%s) is still running on this document." % busy.study)
        job = Job(doc, study_id, mode, restrict)
        JOBS[job.id] = job
        ORDER.append(job.id)
        while len(ORDER) > KEPT:
            old = ORDER.pop(0)
            if JOBS.get(old) is not None and JOBS[old].state in ("queued", "running"):
                ORDER.append(old)
                break
            JOBS.pop(old, None)
    job.thread = threading.Thread(target=job.run, name="formcad-sim-job", daemon=True)
    job.thread.start()
    return job.view()


def get(job_id: str) -> Job:
    with LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise SimError("There is no job %s." % job_id)
    return job


def view(job_id: str) -> dict:
    return get(job_id).view()


def cancel(job_id: str) -> dict:
    job = get(job_id)
    job.stop.set()
    mesher.abort(job)
    if job.state in ("queued", "running"):
        job.state = "cancelled"
        job.message = "The study was cancelled."
        job.finished = time.time()
        job.publish()
    return job.view()


def wait(job_id: str, timeout: float = 600.0) -> dict:
    job = get(job_id)
    if job.thread is not None:
        job.thread.join(timeout)
    return job.view()
