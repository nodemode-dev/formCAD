import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from app.core import config, guard, outputs
from app.render import settings as rs

MAX_JOBS = 50
MAX_ACTIVE = 2
MAX_RESULT = 268435456
MAX_SPEC_BYTES = 65536
MAX_TIMEOUT = 3600
DEFAULT_TIMEOUT = 900
BACKENDS = ("page", "window", "headless")
BROWSER_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "msedge", "microsoft-edge")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
_lock = threading.Lock()
JOBS: dict = {}


class JobError(ValueError):
    pass


class Job:
    def __init__(self, doc_id: str, backend: str, spec: dict, out: str, timeout: int):
        self.id = uuid.uuid4().hex[:16]
        self.doc_id = doc_id
        self.backend = backend
        self.spec = spec
        self.out = out
        self.timeout = timeout
        self.state = "queued"
        self.message = ""
        self.done = 0
        self.total = 0
        self.phase = ""
        self.created = time.time()
        self.started = 0.0
        self.finished = 0.0
        self.stats: dict = {}
        self.result_path = ""
        self.cancel = False
        self.proc = None
        self.token = ""
        self.profile = ""

    def brief(self) -> dict:
        return {"id": self.id, "document": self.doc_id, "backend": self.backend, "state": self.state, "message": self.message, "done": self.done, "total": self.total, "phase": self.phase, "out": self.result_path or self.out, "stats": self.stats, "elapsed": round((self.finished or time.time()) - self.started, 3) if self.started else 0.0, "width": self.spec["output"]["width"], "height": self.spec["output"]["height"], "samples": self.spec["quality"]["samples"]}


def get(job_id: str) -> Job:
    j = JOBS.get(job_id)
    if j is None:
        raise JobError("There is no render job %s." % job_id)
    return j


def _trim() -> None:
    old = sorted((j for j in JOBS.values() if j.state in ("done", "failed", "cancelled")), key=lambda j: j.created)
    while len(JOBS) > MAX_JOBS and old:
        JOBS.pop(old.pop(0).id, None)


def create(doc, backend: str, body: dict, base_url: str) -> Job:
    if backend not in BACKENDS:
        raise JobError("Backend must be one of %s." % ", ".join(BACKENDS))
    stored = rs.read(doc.drawing)
    patch = {}
    for section in ("output", "quality", "environment", "ground", "camera"):
        if isinstance(body.get(section), dict):
            patch[section] = body[section]
    spec = rs.clean(rs.merge(stored, patch))
    cam = body.get("view")
    if cam is not None:
        if not isinstance(cam, dict) or len(json.dumps(cam)) > MAX_SPEC_BYTES:
            raise JobError("The view is not a camera record.")
    spec["view"] = cam
    spec["engine"] = "raster" if body.get("engine") == "raster" else "path"
    spec["document"] = doc.id
    out = ""
    if body.get("out"):
        try:
            out = outputs.checked(str(body["out"]), (".png",), ".png")
        except outputs.OutputRefused as err:
            raise JobError(str(err))
    timeout = int(body.get("timeout") or DEFAULT_TIMEOUT)
    timeout = max(10, min(MAX_TIMEOUT, timeout))
    with _lock:
        if sum(1 for j in JOBS.values() if j.state in ("queued", "running")) >= MAX_ACTIVE:
            raise JobError("Two render jobs are already running; wait for one to finish or cancel it.")
        job = Job(doc.id, backend, spec, out, timeout)
        JOBS[job.id] = job
        _trim()
    if backend == "headless":
        try:
            _launch(job, base_url, str(body.get("origin") or ""))
        except JobError as err:
            _finish(job, "failed", str(err))
            raise
    return job


def find_browser() -> str:
    cands = [os.environ.get("FORMCAD_CHROMIUM", "")]
    try:
        cands.append(str(json.loads((config.data_dir() / "render.json").read_text(encoding="utf-8")).get("browser", "")))
    except (OSError, ValueError, AttributeError):
        pass
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    for n in BROWSER_NAMES:
        p = shutil.which(n)
        if p:
            return p
    raise JobError("No Chromium-based browser was found for the headless path. Install one, or set its path in render.json in the data folder as {\"browser\": \"...\"}, or set FORMCAD_CHROMIUM.")


def extra_args() -> list:
    raw = os.environ.get("FORMCAD_CHROMIUM_ARGS", "")
    out = [a for a in raw.split() if a.startswith("--")][:16]
    if out:
        return out
    try:
        listed = json.loads((config.data_dir() / "render.json").read_text(encoding="utf-8")).get("args", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [a for a in listed if isinstance(a, str) and a.startswith("--") and len(a) < 200][:16] if isinstance(listed, list) else []


def _origin(base_url: str, origin: str) -> str:
    use = origin or base_url
    parts = urlsplit(use)
    if parts.scheme not in ("http", "https") or (parts.hostname or "") not in guard.LOOPBACK:
        raise JobError("The render page must be served from this computer.")
    return "%s://%s" % (parts.scheme, parts.netloc)


def _launch(job: Job, base_url: str, origin: str) -> None:
    exe = find_browser()
    root = _origin(base_url, origin)
    job.token = guard.issue_run_token(("/api/docs/%s" % job.doc_id, "/api/render"))
    job.profile = tempfile.mkdtemp(prefix="formcad-render-")
    w = job.spec["output"]["width"]
    h = job.spec["output"]["height"]
    args = [exe, "--headless=new", "--user-data-dir=" + job.profile, "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl", "--window-size=%d,%d" % (min(w, 1280), min(h, 720)), "--disable-dev-shm-usage"]
    args.extend(extra_args())
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")
    args.append("%s/render.html?job=%s#rt=%s" % (root, job.id, job.token))
    try:
        job.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as err:
        raise JobError("The browser could not be started (%s)." % err.strerror)
    job.state = "running"
    job.started = time.time()
    threading.Thread(target=_watch, args=(job,), daemon=True).start()


def _watch(job: Job) -> None:
    deadline = time.time() + job.timeout
    while job.state in ("queued", "running"):
        if job.cancel:
            _finish(job, "cancelled", "Cancelled.")
            break
        if job.proc is not None and job.proc.poll() is not None and job.state == "running":
            time.sleep(0.5)
            if job.state == "running":
                _finish(job, "failed", "The browser stopped before the image was sent (exit code %s)." % job.proc.returncode)
            break
        if time.time() > deadline:
            _finish(job, "failed", "The render did not finish within %d seconds." % job.timeout)
            break
        time.sleep(0.25)
    _reap(job)


def _reap(job: Job) -> None:
    p = job.proc
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    if job.token:
        guard.revoke_run_token(job.token)
    if job.profile:
        shutil.rmtree(job.profile, ignore_errors=True)
        job.profile = ""


def _finish(job: Job, state: str, message: str = "") -> None:
    if job.state in ("done", "failed", "cancelled"):
        return
    job.state = state
    job.message = message
    job.finished = time.time()


def start_page(job: Job) -> None:
    if job.state == "queued":
        job.state = "running"
        job.started = time.time()


def progress(job: Job, body: dict) -> None:
    if job.state not in ("queued", "running"):
        return
    start_page(job)
    try:
        job.done = max(0, int(body.get("done", job.done)))
        job.total = max(0, int(body.get("total", job.total)))
    except (TypeError, ValueError):
        pass
    job.phase = str(body.get("phase", job.phase))[:80]
    if body.get("state") == "failed":
        _finish(job, "failed", str(body.get("message") or "The render page reported a failure.")[:500])
        if job.backend != "headless":
            return


def png_size(data: bytes) -> tuple:
    if len(data) < 33 or data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        raise JobError("That is not a PNG image.")
    return struct.unpack(">II", data[16:24])


def store_result(job: Job, data: bytes, stats: dict) -> str:
    if job.state in ("failed", "cancelled", "done"):
        raise JobError("This render job is %s." % job.state)
    if len(data) > MAX_RESULT:
        raise JobError("The image is larger than the %d MB limit." % (MAX_RESULT // 1048576))
    w, h = png_size(data)
    want = (job.spec["output"]["width"], job.spec["output"]["height"])
    if (w, h) != want:
        raise JobError("The image is %d by %d; the job asked for %d by %d." % (w, h, want[0], want[1]))
    target = job.out
    if not target:
        folder = config.data_dir() / "renders"
        folder.mkdir(parents=True, exist_ok=True)
        target = str(folder / ("render-%s.png" % job.id))
    fd, tmp = tempfile.mkstemp(prefix="render-", suffix=".tmp", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    except OSError as err:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise JobError("The image could not be written (%s)." % err.strerror)
    job.result_path = target
    job.stats = {k: stats[k] for k in ("samples", "ms", "tiles", "renderer", "engine", "bytes") if k in stats}
    job.stats["bytes"] = len(data)
    job.stats["wall"] = round(time.time() - (job.started or job.created), 3)
    _finish(job, "done", "")
    return target


def cancel(job: Job) -> None:
    job.cancel = True
    if job.backend != "headless":
        _finish(job, "cancelled", "Cancelled.")


def spec_for_page(job: Job) -> dict:
    return {"id": job.id, "document": job.doc_id, "backend": job.backend, "settings": {k: job.spec[k] for k in ("environment", "ground", "quality", "output", "camera")}, "view": job.spec.get("view"), "engine": job.spec.get("engine", "path"), "state": job.state}
