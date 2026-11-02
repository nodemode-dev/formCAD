import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "formcad-engine.log"
LOCK_NAME = "engine.lock"
LOG_BYTES = 1_048_576
LOG_KEEP = 3
STARTED = time.time()
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_LOGGERS = ("formcad", "uvicorn", "uvicorn.error", "uvicorn.access")


class AlreadyRunning(RuntimeError):
    pass


def apply_switches(argv: list[str]) -> list[str]:
    rest: list[str] = []
    items = list(argv)
    valued = {"--user-data-dir": "FORMCAD_DATA_DIR", "--port": "FORMCAD_PORT", "--log-level": "FORMCAD_LOG_LEVEL"}
    flags = {"--portable": ("FORMCAD_PORTABLE", "1")}
    i = 0
    while i < len(items):
        arg = items[i]
        name, eq, value = arg.partition("=")
        if name in valued:
            if not eq:
                i += 1
                value = items[i] if i < len(items) else ""
            if value:
                os.environ[valued[name]] = value
        elif arg in flags:
            os.environ[flags[arg][0]] = flags[arg][1]
        else:
            rest.append(arg)
        i += 1
    return rest


def switches() -> dict:
    return {
        "portable": os.environ.get("FORMCAD_PORTABLE") == "1",
        "logLevel": os.environ.get("FORMCAD_LOG_LEVEL", "INFO").upper(),
    }


def log_path(data: Path) -> Path:
    folder = data / "Logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / LOG_NAME


def start_logging(data: Path) -> Path:
    stop_logging()
    path = log_path(data)
    try:
        size = int(os.environ.get("FORMCAD_LOG_BYTES", "") or LOG_BYTES)
    except ValueError:
        size = LOG_BYTES
    level = getattr(logging, os.environ.get("FORMCAD_LOG_LEVEL", "INFO").upper(), logging.INFO)
    handler = RotatingFileHandler(path, maxBytes=max(size, 1024), backupCount=LOG_KEEP, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.set_name("formcad-file")
    for name in _LOGGERS:
        log = logging.getLogger(name)
        log.addHandler(handler)
        if name == "formcad" or log.level == logging.NOTSET or log.level > level:
            log.setLevel(level)
    logging.getLogger("formcad").info("engine started, pid %s, data folder %s", os.getpid(), data)
    return path


def stop_logging() -> None:
    for name in _LOGGERS:
        log = logging.getLogger(name)
        for handler in list(log.handlers):
            if handler.get_name() == "formcad-file":
                log.removeHandler(handler)
                handler.close()


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
        return bool(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as handle:
            return handle.read().rpartition(")")[2].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def claim(data: Path) -> Path:
    lock = data / LOCK_NAME
    try:
        held = int(json.loads(lock.read_text()).get("pid", 0))
    except (OSError, ValueError, AttributeError):
        held = 0
    if held and held != os.getpid() and _alive(held):
        raise AlreadyRunning(f"FormCAD is already running on {data} (engine process {held}).")
    lock.write_text(json.dumps({"pid": os.getpid(), "started": int(STARTED)}))
    return lock


def release(data: Path) -> None:
    lock = data / LOCK_NAME
    try:
        if int(json.loads(lock.read_text()).get("pid", 0)) == os.getpid():
            lock.unlink()
    except (OSError, ValueError, AttributeError):
        pass
