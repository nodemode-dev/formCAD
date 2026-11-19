import json
import os
import shutil
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from app.core import config
from app.routers.events import hub
from app.services import kernel

WORKER = "formcad-mesher"
EXE = WORKER + (".exe" if os.name == "nt" else "")
RECORD = Path(__file__).resolve().parents[1] / "data" / "mesher-licence.json"
RETRY_AFTER = 30.0
HELLO_TIMEOUT = 60.0
MAX_DOWNLOAD = 600 << 20


class MesherError(RuntimeError):
    pass


def record() -> dict:
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def root() -> Path:
    return config.data_dir() / "mesher"


def resolve() -> tuple[list[str], str, str] | None:
    raw = os.environ.get("FORMCAD_MESHER", "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.suffix == ".py" and path.is_file():
            command = kernel.script_command(path)
            if command:
                return command, str(path), "dev"
        elif path.is_file():
            return [str(path)], str(path), "env"
    folder = root()
    release = os.environ.get("FORMCAD_MESHER_RELEASE", "").strip()
    if not release and folder.is_dir():
        found = sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))
        release = found[-1] if found else ""
    if release:
        installed = folder / release / EXE
        if installed.is_file():
            return [str(installed)], str(installed), "installed"
    script = config.REPO_DIR / "mesher" / "formcad_mesher.py"
    if script.is_file():
        command = kernel.script_command(script)
        if command:
            return command, str(script), "dev"
    return None


_lock = threading.RLock()
_call_lock = threading.Lock()
_owner = None
_worker = None
_info: dict | None = None
_found = None
_message = "No mesher is installed."
_failed_at = 0.0
_install = {"installing": False, "progress": 0.0, "message": ""}


def _drop() -> None:
    global _worker, _info
    if _worker is not None:
        _worker.stop()
    _worker, _info = None, None


def probe(force: bool = False):
    global _worker, _info, _found, _message, _failed_at
    with _lock:
        if _worker is not None and _info is not None and _worker.alive() and not force:
            return _info
        _drop()
        if not force and _failed_at and time.monotonic() - _failed_at < RETRY_AFTER:
            return None
        _found = resolve()
        if _found is None:
            _message = "No mesher is installed."
            _failed_at = time.monotonic()
            return None
        worker = None
        try:
            worker = kernel.Worker(_found[0])
            info = worker.call("hello", timeout=HELLO_TIMEOUT)
        except (OSError, kernel.KernelError) as err:
            if worker is not None:
                worker.stop()
            _message = str(err)
            _failed_at = time.monotonic()
            return None
        _worker, _info, _failed_at = worker, info, 0.0
        _message = "Mesher ready, Netgen %s." % info.get("netgen-mesher", "unknown")
        return _info


def call(method: str, params: dict | None = None, timeout: float = 120.0, owner=None):
    global _owner
    if not _call_lock.acquire(timeout=timeout):
        raise MesherError("The mesher is busy with another study.")
    try:
        with _lock:
            if probe() is None or _worker is None:
                raise MesherError(_message)
            worker = _worker
            _owner = owner
        try:
            return worker.call(method, params, timeout)
        except kernel.KernelError as err:
            raise MesherError(str(err))
    finally:
        _owner = None
        _call_lock.release()


def abort(owner) -> bool:
    with _lock:
        if owner is not None and _owner is owner and _worker is not None and _worker.alive():
            _worker.process.kill()
            return True
    return False


def status() -> dict:
    with _lock:
        ready = _info is not None and _worker is not None and _worker.alive()
        found = _found if ready else None
        message = _install["message"] if _install["installing"] or _install["message"] else _message
        return {
            "available": ready,
            "version": str(_info.get("netgen-mesher")) if ready else None,
            "path": found[1] if found else None,
            "source": found[2] if found else None,
            "installing": _install["installing"],
            "progress": _install["progress"],
            "message": message,
        }


def refresh() -> dict:
    probe(force=True)
    return status()


def stop() -> None:
    with _lock:
        _drop()


def _set(message: str, progress: float | None = None, installing: bool | None = None) -> None:
    with _lock:
        _install["message"] = message
        if progress is not None:
            _install["progress"] = progress
        if installing is not None:
            _install["installing"] = installing
    hub.publish({"type": "mesher", **status()})


def run_install(rec: dict, release: str, target: str) -> None:
    try:
        base = root()
        base.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".partial-", dir=base))
        try:
            archive = work / "mesher.tar.gz"
            import httpx

            with httpx.stream("GET", str(rec["url"]).format(release=release, triple=target), follow_redirects=True, timeout=60.0) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with archive.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
                        done += len(chunk)
                        if done > MAX_DOWNLOAD:
                            raise OSError("the download is larger than the %d MB a mesher build can be" % (MAX_DOWNLOAD >> 20))
                        if total:
                            _set("Downloading the mesher.", min(0.9, done / total * 0.9))
            _set("Checking every file.", 0.92)
            unpacked = work / "unpacked"
            unpacked.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(unpacked, filter="data")
            folder = unpacked / str(rec["folder"]).format(release=release, triple=target)
            if not folder.is_dir():
                _set("The download does not hold the expected folder. Nothing was installed.", 0.0, False)
                return
            problem = kernel.verify_tree(folder, kernel.expected_files(rec, target))
            if problem:
                _set("%s Nothing was installed." % problem, 0.0, False)
                return
            destination = base / release
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(folder, destination)
            worker = destination / EXE
            if worker.is_file() and os.name != "nt":
                worker.chmod(0o755)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        _set("Mesher installed.", 1.0, False)
        refresh()
    except Exception as err:
        _set("The mesher could not be installed (%s). Nothing was installed." % err, 0.0, False)


def start_install() -> dict:
    with _lock:
        if _install["installing"]:
            return status()
        rec = record()
        release = os.environ.get("FORMCAD_MESHER_RELEASE", "").strip() or rec.get("release")
        target = kernel.triple()
        if not release or not kernel.expected_files(rec, target):
            _install["message"] = "No mesher build is published yet. Downloads come from the formai-binaries releases and are checked against the shipped record before they are installed."
            return status()
        _install.update(installing=True, progress=0.0, message="Starting the download.")
    threading.Thread(target=run_install, args=(rec, str(release), target), name="formcad-mesher-install", daemon=True).start()
    return status()
