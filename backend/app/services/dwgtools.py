import json
import os
import shutil
import tarfile
import tempfile
import threading
from pathlib import Path

from app.core import config
from app.routers.events import hub
from app.services import kernel

TOOLS = ("dwg2dxf", "dxf2dwg")
EXT = ".exe" if os.name == "nt" else ""
SHIPPED = Path(__file__).resolve().parents[1] / "data" / "dwg-licence.json"
MAX_DOWNLOAD = 200 << 20

_lock = threading.RLock()
_install = {"installing": False, "progress": 0.0, "message": ""}


def record() -> dict:
    path = Path(os.environ.get("FORMCAD_DWG_RECORD", "").strip() or SHIPPED)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def root() -> Path:
    return config.data_dir() / "dwg"


def published() -> bool:
    rec = record()
    return bool(rec.get("release")) and bool(kernel.expected_files(rec, kernel.triple()))


def installed() -> dict | None:
    folder = root()
    if not folder.is_dir():
        return None
    for release in sorted((p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")), reverse=True):
        read, write = (folder / release / (t + EXT) for t in TOOLS)
        if read.is_file() and write.is_file():
            return {"release": release, "read": str(read), "write": str(write)}
    return None


def status() -> dict:
    with _lock:
        have = installed()
        rec = record()
        return {
            "published": published(),
            "installed": have is not None,
            "release": have["release"] if have else rec.get("release"),
            "licence": rec.get("licence", ""),
            "writeVersions": list(rec.get("write_versions") or ["R2000"]),
            "installing": _install["installing"],
            "progress": _install["progress"],
            "message": _install["message"],
        }


def _set(message: str, progress: float | None = None, installing: bool | None = None) -> None:
    with _lock:
        _install["message"] = message
        if progress is not None:
            _install["progress"] = progress
        if installing is not None:
            _install["installing"] = installing
    hub.publish({"type": "dwgtools", **status()})


def run_install(rec: dict, release: str, target: str) -> None:
    try:
        base = root()
        base.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".partial-", dir=base))
        try:
            archive = work / "dwg.tar.gz"
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
                            raise OSError("the download is larger than the %d MB the DWG tools can be" % (MAX_DOWNLOAD >> 20))
                        if total:
                            _set("Downloading the DWG tools.", min(0.9, done / total * 0.9))
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
            if os.name != "nt":
                for tool in TOOLS:
                    (destination / tool).chmod(0o755)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        _set("DWG tools installed.", 1.0, False)
    except Exception as err:
        _set("The DWG tools could not be installed (%s). Nothing was installed." % err, 0.0, False)


def start_install() -> dict:
    with _lock:
        if _install["installing"]:
            return status()
        rec = record()
        release = str(rec.get("release") or "")
        target = kernel.triple()
        if not release or not kernel.expected_files(rec, target):
            return status()
        _install.update(installing=True, progress=0.0, message="Starting the download.")
    threading.Thread(target=run_install, args=(rec, release, target), name="formcad-dwg-install", daemon=True).start()
    return status()


def remove() -> dict:
    with _lock:
        if _install["installing"]:
            return status()
        folder = root()
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        _install.update(progress=0.0, message="DWG tools removed.")
    return status()
