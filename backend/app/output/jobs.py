import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.output import plot
from app.output import request as R

MAX_KEPT = 24
MAX_BYTES = 256 * 1024 * 1024
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="plot")
_lock = threading.Lock()
JOBS = {}
ORDER = []


class Job:
    def __init__(self, doc_id, kind, raw):
        self.id = uuid.uuid4().hex[:12]
        self.doc_id = doc_id
        self.kind = kind
        self.raw = raw
        self.state = "queued"
        self.message = ""
        self.created = time.time()
        self.finished = None
        self.result = None
        self.future = None

    def view(self):
        out = {"id": self.id, "doc": self.doc_id, "kind": self.kind, "state": self.state, "message": self.message, "created": self.created, "finished": self.finished}
        if self.result is not None:
            r = self.result
            out.update({"output": r["output"], "mime": r["mime"], "size": r["size"], "pages": r["pages"], "path": r.get("path", "")})
        return out


def _evict():
    total = sum(len(j.result["data"]) for j in JOBS.values() if j.result is not None)
    while ORDER and (len(ORDER) > MAX_KEPT or total > MAX_BYTES):
        old = JOBS.pop(ORDER.pop(0), None)
        if old is not None and old.result is not None:
            total -= len(old.result["data"])


def _run(job, doc):
    job.state = "running"
    try:
        if job.kind == "svg":
            res = plot.export_svg(doc, job.raw)
        else:
            res = plot.run(doc, job.raw, job.kind if job.kind in ("pdf", "png") else None)
        job.result = res
        job.state = "done"
        where = res.get("path")
        job.message = "Plotted %s%s." % (", ".join(p["name"] for p in res["pages"]), " to " + where if where else "")
    except R.PlotError as err:
        job.state = "failed"
        job.message = str(err)
    except Exception as err:
        job.state = "failed"
        job.message = "The plot failed: %s" % err
    job.finished = time.time()


def submit(doc, doc_id, kind, raw, wait=True, timeout=600.0):
    job = Job(doc_id, kind, raw)
    with _lock:
        JOBS[job.id] = job
        ORDER.append(job.id)
        _evict()
    job.future = _pool.submit(_run, job, doc)
    if wait:
        job.future.result(timeout=timeout)
    return job


def get(job_id):
    return JOBS.get(job_id)


def listing(doc_id=None):
    return [j.view() for j in JOBS.values() if doc_id is None or j.doc_id == doc_id]
