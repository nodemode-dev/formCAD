import contextvars
import threading
import time

from app.gen import run as gen_run
from app.sim import records
from app.sim import study as sim_study
from app.topo import jobs as tj
from app.topo.grid import Cancelled, TopoError

FIELDS = [{"name": "density", "unit": "", "location": "voxel", "components": 1}, {"name": "solid", "unit": "", "location": "voxel", "components": 1}, {"name": "vm", "unit": "MPa", "location": "voxel", "components": 1}]


class GenJob(tj.Job):
    def __init__(self, doc, study_id, restrict, overrides):
        super().__init__(doc, study_id, "generative", restrict, overrides)
        window = gen_run.cap(restrict, "seconds")
        self.deadline = min(self.started + float(overrides.get("seconds") or window), self.started + window)

    def run(self) -> None:
        self.state = "running"
        self.publish()
        try:
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
            self.message = "The generative study failed (%s)." % err
        self.finished = time.time()
        self.publish()


def start(doc, study_id: str, restrict: bool = False, overrides: dict = None) -> dict:
    with tj.LOCK:
        busy = tj.active(getattr(doc, "id", ""))
        if busy is not None:
            raise TopoError("Another study (%s) is still running on this document." % busy.study)
        job = GenJob(doc, study_id, restrict, dict(overrides or {}))
        tj.JOBS[job.id] = job
        tj.ORDER.append(job.id)
        while len(tj.ORDER) > tj.KEPT:
            old = tj.ORDER.pop(0)
            if tj.JOBS.get(old) is not None and tj.JOBS[old].state in ("queued", "running"):
                tj.ORDER.append(old)
                break
            tj.JOBS.pop(old, None)
    scope = contextvars.copy_context()
    job.thread = threading.Thread(target=lambda: scope.run(job.run), name="formcad-gen-job", daemon=True)
    job.thread.start()
    return job.view()


def execute(doc, study_id: str, overrides: dict, ctl, restrict: bool) -> dict:
    parts = gen_run.compute(doc, study_id, overrides, ctl, restrict)
    ctl.step("Storing the outcomes", 0.985)
    with doc.lock:
        with doc.transaction("GENRUN"):
            return store(doc.drawing, parts)


def store(d, parts: dict) -> dict:
    study_id = parts["study"]
    key = sim_study.put_blob(d, parts["data"])
    for old in records.of_kind(d, "result"):
        if old.get("study") == study_id:
            d.table_remove(records.TABLE, old["id"])
    res = records.put_result(d, {"study": study_id, "type": "generative", "blob": key, "summary": parts["summary"], "fields": FIELDS, "modes": [], "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())})
    row = records.get(d, study_id)
    row["result"] = res["id"]
    row["status"] = "solved"
    d.table_set(records.TABLE, row)
    return {"study": study_id, "result": res["id"], "summary": parts["summary"]}
