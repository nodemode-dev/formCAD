import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
ENGINE = BACKEND / "formcad_engine.py"

pytestmark = pytest.mark.live


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert port != 8290
    return port


def _env(data, port):
    env = dict(os.environ)
    env.pop("FORMCAD_LOCKED", None)
    env.pop("FORMCAD_TEST_DATA", None)
    env.update({"FORMCAD_DATA_DIR": str(data), "FORMCAD_PORT": str(port), "FORMCAD_DIST": str(data / "no-frontend"), "FORMCAD_LIBRARY_DIR": str(data / "Projects")})
    return env


class Live:
    def __init__(self, data: Path, port: int | None = None):
        self.data = data
        self.port = port or _free_port()
        self.out = open(data / "engine-output.txt", "ab")
        self.proc = subprocess.Popen([sys.executable, str(ENGINE)], cwd=str(BACKEND), env=_env(data, self.port), stdout=self.out, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (data / "engine.port").exists() and self.ask("GET", "/api/health", key=None)[0] == 200:
                break
            assert self.proc.poll() is None, (data / "engine-output.txt").read_text(errors="replace")
            time.sleep(0.2)
        else:
            self.stop()
            pytest.fail("the engine did not come up within 60 seconds")
        self.key = (data / "session.token").read_text(encoding="utf-8").strip()

    def ask(self, method, path, body=None, key="session", host=None):
        headers = {"content-type": "application/json"}
        if key == "session":
            key = self.key
        if key:
            headers["X-FormCAD-Token"] = key
        if host:
            headers["Host"] = host
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as reply:
                return reply.status, json.loads(reply.read() or b"null")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"null")
        except (urllib.error.URLError, ConnectionError):
            return 0, None

    def kill(self):
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait(timeout=30)
        self.out.close()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self.out.close()


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    engine = Live(tmp_path_factory.mktemp("live-data"))
    yield engine
    engine.stop()


def test_the_engine_writes_its_port_file_with_its_port_and_process_id(live):
    record = json.loads((live.data / "engine.port").read_text(encoding="utf-8"))
    assert record == {"pid": live.proc.pid, "port": live.port}


def test_the_session_key_file_opens_window_routes_and_requests_without_it_are_refused(live):
    assert live.ask("GET", "/api/health", key=None) == (200, {"ok": True, "version": live.ask("GET", "/api/health")[1]["version"]})
    status, body = live.ask("GET", "/api/docs")
    assert status == 200 and body["docs"] == []
    assert live.ask("GET", "/api/docs", key=None)[0] == 401
    assert live.ask("GET", "/api/docs", key="guessed")[0] == 401
    assert live.ask("GET", "/api/docs", host="evil.example:%d" % live.port)[0] == 403


def test_the_session_key_file_is_readable_by_its_owner_only(live):
    assert (live.data / "session.token").stat().st_mode & 0o077 == 0


def test_the_engine_uses_the_data_folder_it_is_given(live):
    status, caps = live.ask("GET", "/api/capabilities")
    assert status == 200
    assert Path(caps["dataDir"]).resolve() == live.data.resolve() and caps["dataDirSource"] == "override"
    assert (live.data / "Logs" / "formcad-engine.log").is_file()


def _outside_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            address = s.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def test_the_engine_listens_on_the_loopback_address_only(live):
    address = _outside_address()
    if address is None:
        pytest.skip("this machine has no address outside loopback to try")
    with socket.socket() as s:
        s.settimeout(3)
        assert s.connect_ex((address, live.port)) != 0


def test_a_second_engine_on_the_same_data_folder_refuses_to_start_and_the_first_keeps_answering(live):
    second = subprocess.run([sys.executable, str(ENGINE)], cwd=str(BACKEND), env=_env(live.data, _free_port()), capture_output=True, text=True, timeout=60)
    assert second.returncode == 2 and "already running" in second.stderr
    assert live.ask("GET", "/api/docs")[0] == 200
    assert json.loads((live.data / "engine.port").read_text(encoding="utf-8"))["pid"] == live.proc.pid


def test_selfcheck_exits_zero_and_reports_the_app_kernel_and_mesher_ready(tmp_path):
    done = subprocess.run([sys.executable, str(ENGINE), "--selfcheck"], cwd=str(BACKEND), env=_env(tmp_path, _free_port()), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["app"] == "ok" and report["kernel_record"] == "ok" and report["mesher_record"] == "ok"


def _content(engine, doc_id):
    _, snap = engine.ask("GET", "/api/docs/%s/snapshot" % doc_id)
    return sorted((e["kind"], tuple(e.get("start") or e.get("center"))) for e in snap["entities"])


def test_a_drawing_left_unsaved_by_a_crash_is_offered_back_after_a_restart_and_discard_removes_another(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    first = Live(data)
    try:
        _, kept = first.ask("POST", "/api/docs", {"name": "Crashed"})
        for line in ("LINE", "0,0", "30,40", "", "CIRCLE", "5,5", "2"):
            first.ask("POST", "/api/docs/%s/input" % kept["id"], {"text": line})
        _, unwanted = first.ask("POST", "/api/docs", {"name": "Unwanted"})
        first.ask("POST", "/api/docs/%s/input" % unwanted["id"], {"text": "CIRCLE"})
        first.ask("POST", "/api/docs/%s/input" % unwanted["id"], {"text": "0,0"})
        first.ask("POST", "/api/docs/%s/input" % unwanted["id"], {"text": "9"})
        lost = _content(first, kept["id"])
        assert lost == [("circle", (5.0, 5.0, 0.0)), ("line", (0.0, 0.0, 0.0))]
        assert first.ask("POST", "/api/docs/autosave/now")[1]["saved"] == 2
    finally:
        first.kill()
    stale = time.time() - 3600
    for lock in (data / "Autosave").glob("*.lock"):
        os.utime(lock, (stale, stale))
    second = Live(data)
    try:
        status, listed = second.ask("GET", "/api/docs/recovery")
        offered = {i["title"]: i["file"] for i in listed["items"]}
        assert status == 200 and sorted(offered) == ["Crashed", "Unwanted"]
        assert second.ask("POST", "/api/docs/recovery/discard", {"file": offered["Unwanted"]})[1] == {"discarded": True}
        assert not (data / "Autosave" / offered["Unwanted"]).exists()
        assert [i["title"] for i in second.ask("GET", "/api/docs/recovery")[1]["items"]] == ["Crashed"]
        status, back = second.ask("POST", "/api/docs/recovery/open", {"file": offered["Crashed"]})
        assert status == 200 and back["entities"] == 2 and back["dirty"] is True
        assert _content(second, back["id"]) == lost
    finally:
        second.stop()
