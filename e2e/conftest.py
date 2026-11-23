import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
BACKEND = REPO / "backend"
FIXTURES = REPO / "fixtures"
URL = os.environ.get("FORMCAD_E2E_URL", "http://127.0.0.1:5290/")
API = os.environ.get("FORMCAD_E2E_API", "http://127.0.0.1:8290")
GIVEN_DATA = os.environ.get("FORMCAD_E2E_DATA")
DATA = Path(GIVEN_DATA or tempfile.mkdtemp(prefix="formcad-e2e-"))
READY = ".cv-app"


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _wait(url: str, seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _answers(url):
            return
        time.sleep(0.4)
    pytest.exit("%s did not start at %s." % (what, url), returncode=1)


def _engine_python() -> str:
    for rel in (("venv", "bin", "python"), ("venv", "Scripts", "python.exe")):
        found = BACKEND.joinpath(*rel)
        if found.is_file():
            return str(found)
    return sys.executable


def pytest_collection_modifyitems(config, items):
    shard = os.environ.get("FORMCAD_E2E_SHARD")
    if not shard:
        return
    index, total = (int(x) for x in shard.split("/"))
    files: dict = {}
    for item in items:
        files.setdefault(item.nodeid.split("::")[0], []).append(item)
    keep, drop = [], []
    for n, name in enumerate(sorted(files)):
        (keep if n % total == index - 1 else drop).extend(files[name])
    order = {id(i): n for n, i in enumerate(items)}
    keep.sort(key=lambda i: order[id(i)])
    config.hook.pytest_deselected(items=drop)
    items[:] = keep


def _start(command: list, cwd: Path, env: dict):
    if os.name == "nt":
        return subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _stop(proc) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.kill()


@pytest.fixture(scope="session", autouse=True)
def servers():
    started = []
    env = {**os.environ, "FORMCAD_DATA_DIR": str(DATA), "FORMCAD_LIBRARY_DIR": str(DATA / "Projects")}
    env.pop("FORMCAD_LOCKED", None)
    try:
        if not _answers(API + "/api/health"):
            port = API.rsplit(":", 1)[1]
            started.append(_start([_engine_python(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port], BACKEND, env))
            _wait(API + "/api/health", 90, "The engine")
        elif not GIVEN_DATA:
            pytest.exit("An engine is already running at %s. Stop it, or set FORMCAD_E2E_DATA to its data folder." % API, returncode=1)
        if _answers(URL) and not GIVEN_DATA:
            pytest.exit("A dev build is already running at %s with another engine's key. Stop it, or set FORMCAD_E2E_DATA to its data folder." % URL, returncode=1)
        if not _answers(URL):
            vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
            node = shutil.which("node") or "node"
            started.append(_start([node, str(vite), "--host", "127.0.0.1", "--port", "5290", "--strictPort"], FRONTEND, env))
            _wait(URL, 90, "The dev build")
        yield
    finally:
        for proc in reversed(started):
            _stop(proc)


class Api:
    def __init__(self) -> None:
        self.token = (DATA / "session.token").read_text(encoding="utf-8").strip()

    def call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(API + path, data=data, method=method, headers={"X-FormCAD-Token": self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if r.headers.get("content-type", "").startswith("application/json") else raw

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, body=None):
        return self.call("POST", path, body if body is not None else {})

    def docs(self) -> list:
        return self.get("/api/docs")["docs"]

    def active(self) -> str | None:
        return self.get("/api/docs")["active"]

    def snapshot(self, doc_id: str | None = None) -> dict:
        return self.get("/api/docs/%s/snapshot" % (doc_id or self.active()))

    def entities(self, kind: str | None = None, doc_id: str | None = None) -> list:
        found = self.snapshot(doc_id)["entities"]
        return [e for e in found if kind is None or e.get("kind") == kind]

    def state(self, doc_id: str | None = None) -> dict:
        return self.get("/api/docs/%s/state" % (doc_id or self.active()))

    def close_all(self) -> None:
        for d in self.docs():
            self.post("/api/docs/%s/close" % d["id"], {"force": True})


@pytest.fixture(scope="session")
def api(servers) -> Api:
    return Api()


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="module")
def browser(servers):
    with sync_playwright() as p:
        exe = os.environ.get("FORMCAD_E2E_CHROME") or None
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        yield b
        b.close()


@pytest.fixture()
def context(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    yield ctx
    ctx.close()


def open_app(page) -> list:
    errors: list = []
    page.failed = []
    page.warnings = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: page.warnings.append("%s: %s" % (m.type, m.text[:300])) if m.type in ("warning", "error") else None)
    page.on("response", lambda r: page.failed.append("%d %s" % (r.status, r.url)) if r.status >= 500 else None)
    page.goto(URL)
    page.wait_for_selector(READY, timeout=60000)
    return errors


@pytest.fixture()
def page(context, api):
    api.close_all()
    pg = context.new_page()
    pg.errors = open_app(pg)
    yield pg
    assert not pg.errors, pg.errors
    assert not pg.failed, pg.failed
    api.close_all()


def throttle(page, rate: float = 4.0):
    session = page.context.new_cdp_session(page)
    session.send("Emulation.setCPUThrottlingRate", {"rate": rate})
    return session


WATCH = """
(selector) => {
  const root = document.querySelector(selector);
  const log = { removed: 0, added: 0, rootReplaced: false };
  const seen = new MutationObserver((records) => {
    for (const r of records) {
      log.added += r.addedNodes.length;
      log.removed += r.removedNodes.length;
      for (const n of r.removedNodes) if (n === root) log.rootReplaced = true;
    }
  });
  seen.observe(document.body, { childList: true, subtree: true });
  window.__formcadWatch = { log, root, selector, seen };
}
"""

REPORT = """
() => {
  const w = window.__formcadWatch;
  w.seen.disconnect();
  return { ...w.log, sameRoot: document.querySelector(w.selector) === w.root };
}
"""


def watch_dom(page, selector: str = READY) -> None:
    page.evaluate(WATCH, selector)


def dom_report(page) -> dict:
    return page.evaluate(REPORT)
