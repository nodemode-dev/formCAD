import hashlib
import itertools
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from app.core import config
from app.routers.events import hub

WORKER = "formcad-kernel"
EXE = WORKER + (".exe" if sys.platform.startswith("win") else "")
RECORD = Path(__file__).resolve().parents[1] / "data" / "kernel-licence.json"
RETRY_AFTER = 30.0
HELLO_TIMEOUT = 60.0


class KernelError(RuntimeError):
    pass


def triple() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if arm else "x86_64-apple-darwin"
    if sys.platform.startswith("win"):
        return "x86_64-pc-windows-msvc"
    return "aarch64-unknown-linux-gnu" if arm else "x86_64-unknown-linux-gnu"


def record() -> dict:
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def kernel_root() -> Path:
    return config.data_dir() / "kernel"


def venv_python(folder: Path) -> Path | None:
    for rel in (("venv", "bin", "python"), ("venv", "Scripts", "python.exe")):
        candidate = folder.joinpath(*rel)
        if candidate.is_file():
            return candidate
    return None


def script_command(script: Path) -> list[str] | None:
    python = venv_python(script.parent)
    return [str(python), str(script)] if python else None


def resolve() -> tuple[list[str], str, str] | None:
    raw = os.environ.get("FORMCAD_KERNEL", "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.suffix == ".py" and path.is_file():
            command = script_command(path)
            if command:
                return command, str(path), "dev"
        elif path.is_file():
            return [str(path)], str(path), "env"
    root = kernel_root()
    release = os.environ.get("FORMCAD_KERNEL_RELEASE", "").strip()
    if not release and root.is_dir():
        found = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
        release = found[-1] if found else ""
    if release:
        installed = root / release / EXE
        if installed.is_file():
            return [str(installed)], str(installed), "installed"
    script = config.REPO_DIR / "kernel" / "formcad_kernel.py"
    if script.is_file():
        command = script_command(script)
        if command:
            return command, str(script), "dev"
    return None


class Worker:
    def __init__(self, command: list[str]) -> None:
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        self.lines: queue.Queue = queue.Queue()
        self.ids = itertools.count(1)
        threading.Thread(target=self.read, name="formcad-kernel-reader", daemon=True).start()

    def read(self) -> None:
        try:
            for line in self.process.stdout:
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def alive(self) -> bool:
        return self.process.poll() is None

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0):
        ident = next(self.ids)
        try:
            self.process.stdin.write(json.dumps({"id": ident, "method": method, "params": params or {}}) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as err:
            raise KernelError(f"The kernel worker is not answering ({err}).") from err
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty as err:
                self.process.kill()
                raise KernelError(f"The kernel worker did not answer {method} in time.") from err
            if line is None:
                raise KernelError("The kernel worker exited.")
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if reply.get("id") != ident:
                continue
            if "error" in reply:
                raise KernelError(str((reply["error"] or {}).get("message", "The kernel worker reported an error.")))
            return reply.get("result")

    def stop(self) -> None:
        if self.alive():
            try:
                self.call("shutdown", timeout=3.0)
            except KernelError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except (OSError, ValueError, AttributeError):
                pass


_lock = threading.RLock()
_worker: Worker | None = None
_info: dict | None = None
_found: tuple[list[str], str, str] | None = None
_message = "No kernel is installed."
_failed_at = 0.0
_install = {"installing": False, "progress": 0.0, "message": ""}
_serial = 0


def serial() -> int:
    with _lock:
        probe()
        return _serial if _worker is not None else 0


def _publish() -> None:
    hub.publish({"type": "kernel", **status()})


def _drop() -> None:
    global _worker, _info
    if _worker is not None:
        _worker.stop()
    _worker, _info = None, None


def probe(force: bool = False) -> dict | None:
    global _worker, _info, _found, _message, _failed_at, _serial
    with _lock:
        if _worker is not None and _info is not None and _worker.alive() and not force:
            return _info
        _drop()
        if not force and _failed_at and time.monotonic() - _failed_at < RETRY_AFTER:
            return None
        _found = resolve()
        if _found is None:
            _message = "No kernel is installed."
            _failed_at = time.monotonic()
            return None
        worker = None
        try:
            worker = Worker(_found[0])
            info = worker.call("hello", timeout=HELLO_TIMEOUT)
        except (OSError, KernelError) as err:
            if worker is not None:
                worker.stop()
            _message = str(err)
            _failed_at = time.monotonic()
            return None
        _worker, _info, _failed_at = worker, info, 0.0
        _serial += 1
        _message = f"Kernel ready, OpenCascade {info.get('occt', 'unknown')}."
        return _info


def call(method: str, params: dict | None = None, timeout: float = 30.0):
    with _lock:
        if probe() is None or _worker is None:
            raise KernelError(_message)
        return _worker.call(method, params, timeout)


def describe() -> dict:
    info = probe()
    with _lock:
        return {
            "available": info is not None,
            "version": str(info.get("occt")) if info else None,
            "path": _found[1] if (info and _found) else None,
            "source": _found[2] if (info and _found) else None,
        }


def status() -> dict:
    with _lock:
        ready = _info is not None and _worker is not None and _worker.alive()
        version = str(_info.get("occt")) if ready else None
        message = _install["message"] if _install["installing"] or _install["message"] else _message
        return {"available": ready, "version": version, "installing": _install["installing"], "progress": _install["progress"], "message": message}


def refresh() -> dict:
    probe(force=True)
    return status()


def stop() -> None:
    with _lock:
        _drop()


def expected_files(rec: dict, target: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in rec.get("files", []):
        if entry.get("triple") == target:
            out[str(entry["path"])] = str(entry["sha256"]).lower()
    return out


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_tree(root: Path, expected: dict[str, str]) -> str | None:
    present = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
    for rel, want in expected.items():
        if rel not in present:
            return f"{rel} is missing from the download."
        if sha256_of(present[rel]) != want:
            return f"{rel} does not match the recorded SHA-256."
    for rel in present:
        if rel not in expected:
            return f"{rel} is not in the shipped record."
    return None


def _set(message: str, progress: float | None = None, installing: bool | None = None) -> None:
    with _lock:
        _install["message"] = message
        if progress is not None:
            _install["progress"] = progress
        if installing is not None:
            _install["installing"] = installing
    _publish()


def download(url: str, target: Path) -> None:
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with target.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    _set("Downloading the kernel.", min(0.9, done / total * 0.9))


def run_install(rec: dict, release: str, target: str) -> None:
    try:
        root = kernel_root()
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".partial-", dir=root))
        try:
            archive = work / "kernel.tar.gz"
            download(str(rec["url"]).format(release=release, triple=target), archive)
            _set("Checking every file.", 0.92)
            unpacked = work / "unpacked"
            unpacked.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(unpacked, filter="data")
            folder = unpacked / str(rec["folder"]).format(release=release, triple=target)
            if not folder.is_dir():
                _set("The download does not hold the expected folder. Nothing was installed.", 0.0, False)
                return
            problem = verify_tree(folder, expected_files(rec, target))
            if problem:
                _set(f"{problem} Nothing was installed.", 0.0, False)
                return
            destination = root / release
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(folder, destination)
            worker = destination / EXE
            if worker.is_file() and not sys.platform.startswith("win"):
                worker.chmod(0o755)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        _set("Kernel installed.", 1.0, False)
        refresh()
        _publish()
    except Exception as err:
        _set(f"The kernel could not be installed ({err}). Nothing was installed.", 0.0, False)


def start_install() -> dict:
    with _lock:
        if _install["installing"]:
            return status()
        rec = record()
        release = os.environ.get("FORMCAD_KERNEL_RELEASE", "").strip() or rec.get("release")
        target = triple()
        if not release or not expected_files(rec, target):
            _install["message"] = "No kernel build is published yet. Downloads come from the formCAD-binaries releases and are checked against the shipped record before they are installed."
            return status()
        if release != rec.get("release"):
            _install["message"] = f"Release {release} is not the one this app ships a record for ({rec.get('release')}). Nothing was installed."
            return status()
        _install.update(installing=True, progress=0.0, message="Starting the download.")
    threading.Thread(target=run_install, args=(rec, str(release), target), name="formcad-kernel-install", daemon=True).start()
    return status()
