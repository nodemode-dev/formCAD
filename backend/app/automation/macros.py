import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.core import config, guard
from app.doc import container

SETTINGS = "automation.json"
MAX_SOURCE = 1_000_000
MAX_OUTPUT = 262_144
DEFAULT_LIMITS = {"timeoutSeconds": 120, "cpuSeconds": 110, "memoryBytes": 1 << 30, "fileBytes": 16 << 20, "openFiles": 256, "processes": 1}
SCOPE = ("/api/docs", "/api/commands")
_lock = threading.RLock()


class MacroError(Exception):
    pass


def settings_path() -> Path:
    return config.data_dir() / SETTINGS


def load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    container.atomic_write(str(settings_path()), json.dumps(data, indent=2, sort_keys=True).encode("utf-8"), 0o600)


def macro_folder() -> Path:
    folder = config.data_dir() / "macros"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def sdk_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "app", "data", "sdk")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sdk")


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read(MAX_SOURCE + 1))
    return h.hexdigest()


def check_file(path: str) -> str:
    full = os.path.realpath(os.path.expanduser(str(path or "")))
    if os.path.splitext(full)[1].lower() != ".py":
        raise MacroError("Python macros are .py files.")
    if not os.path.isfile(full):
        raise MacroError('Cannot find the macro "%s".' % path)
    if os.path.getsize(full) > MAX_SOURCE:
        raise MacroError("The macro file is larger than 1 MB.")
    return full


def record(full: str) -> dict:
    data = load_settings().get("macros", {}).get(full)
    return data if isinstance(data, dict) else {}


def status(path: str) -> dict:
    full = check_file(path)
    rec = record(full)
    digest = file_hash(full)
    trusted = bool(rec.get("trusted")) and rec.get("sha256") == digest
    return {"path": full, "name": os.path.basename(full), "sha256": digest, "trusted": trusted, "changedSinceTrust": bool(rec.get("trusted")) and not trusted, "grants": rec.get("grants", {}) if trusted else {}}


def source(path: str) -> str:
    full = check_file(path)
    with open(full, "rb") as fh:
        return fh.read(MAX_SOURCE).decode("utf-8", "replace")


def set_trust(path: str, trusted: bool, grants: dict | None = None, sha256: str = "") -> dict:
    full = check_file(path)
    digest = file_hash(full)
    if trusted and not sha256:
        raise MacroError("Trusting a macro needs the hash that was shown with its source.")
    if trusted and sha256 != digest:
        raise MacroError("The macro changed after it was shown. Review it again.")
    clean = {"network": False, "subprocess": False, "native": False, "files": []}
    for key, value in (grants or {}).items():
        if key == "files":
            clean["files"] = [os.path.realpath(os.path.expanduser(str(p))) for p in (value or []) if str(p).strip()]
        elif key in ("network", "subprocess", "native"):
            clean[key] = bool(value)
    with _lock:
        data = load_settings()
        macros = data.setdefault("macros", {})
        if trusted:
            macros[full] = {"trusted": True, "sha256": digest, "grants": clean, "at": int(time.time())}
        else:
            macros.pop(full, None)
        save_settings(data)
    return status(full)


def listing() -> list:
    out = []
    folders = [macro_folder()]
    extra = load_settings().get("macroFolders", [])
    folders += [Path(p) for p in extra if isinstance(p, str)]
    seen = set()
    for folder in folders:
        try:
            names = sorted(folder.glob("*.py"))
        except OSError:
            continue
        for item in names:
            full = os.path.realpath(str(item))
            if full in seen:
                continue
            seen.add(full)
            try:
                out.append(status(full))
            except (MacroError, OSError):
                continue
    return out


def detect_python() -> list:
    found = []
    wanted = load_settings().get("python", "")
    seen = set()
    candidates = [wanted] if wanted else []
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    for name in ("python3", "python"):
        candidates.append(shutil.which(name) or "")
    if os.name == "nt":
        candidates.append(shutil.which("py") or "")
    for cand in candidates:
        if not cand or cand in seen or not os.path.isfile(cand):
            continue
        seen.add(cand)
        try:
            res = subprocess.run([cand, "-I", "-c", "import sys;print(sys.version.split()[0])"], capture_output=True, text=True, timeout=10, env=clean_env({}), stdin=subprocess.DEVNULL)
            if res.returncode == 0:
                found.append({"path": cand, "version": res.stdout.strip(), "chosen": cand == wanted})
        except (OSError, subprocess.SubprocessError):
            continue
    return found


def interpreter() -> list:
    wanted = load_settings().get("python", "")
    if wanted:
        if not os.path.isfile(wanted):
            raise MacroError("The Python interpreter set in the preferences does not exist: %s" % wanted)
        return [wanted, "-I", os.path.join(sdk_dir(), "_host.py")]
    if getattr(sys, "frozen", False):
        return [sys.executable, "macro", "--host"]
    return [sys.executable, "-I", os.path.join(sdk_dir(), "_host.py")]


def clean_env(extra: dict) -> dict:
    env = {}
    if os.name == "nt":
        for key in ("SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    else:
        env["PATH"] = "/usr/bin:/bin"
        env["LANG"] = os.environ.get("LANG", "C.UTF-8")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _job_object(proc, limits: dict) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", Counters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = Extended()
        info.Basic.LimitFlags = 0x2000 | 0x100 | 0x4
        if limits.get("processes") is not None:
            info.Basic.LimitFlags |= 0x8
            info.Basic.ActiveProcessLimit = 1
        info.Basic.PerJobUserTimeLimit = int(limits["cpuSeconds"]) * 10_000_000
        info.ProcessMemoryLimit = int(limits["memoryBytes"])
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return False
        handle = int(proc._handle)
        if not k32.AssignProcessToJobObject(job, handle):
            return False
        proc._formcad_job = job
        return True
    except Exception:
        return False


def _kill(proc) -> None:
    try:
        if os.name == "posix":
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def _tail(path: str) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            data = fh.read(MAX_OUTPUT)
        text = data.decode("utf-8", "replace")
        return text + ("\n[output cut at %d bytes of %d]" % (MAX_OUTPUT, size) if size > MAX_OUTPUT else "")
    except OSError:
        return ""


def snapshot(path: str) -> tuple:
    full = check_file(path)
    with open(full, "rb") as fh:
        data = fh.read(MAX_SOURCE + 1)
    if len(data) > MAX_SOURCE:
        raise MacroError("The macro file is larger than 1 MB.")
    return full, data, hashlib.sha256(data).hexdigest()


def run(path: str, base_url: str, doc_id: str = "", timeout: float | None = None, args: list | None = None, consent: dict | None = None) -> dict:
    full, data, digest = snapshot(path)
    rec = record(full)
    trusted = bool(rec.get("trusted")) and rec.get("sha256") == digest
    info = {"path": full, "name": os.path.basename(full), "sha256": digest, "trusted": trusted, "changedSinceTrust": bool(rec.get("trusted")) and not trusted, "grants": rec.get("grants", {}) if trusted else {}}
    if consent is not None:
        info["trusted"] = True
        info["grants"] = consent
    if not info["trusted"]:
        raise MacroError("This macro is not trusted yet. Review its source and trust it first." if not info["changedSinceTrust"] else "This macro changed since you trusted it. Review it and trust it again.")
    limits = dict(DEFAULT_LIMITS)
    limits.update({k: v for k, v in load_settings().get("macroLimits", {}).items() if k in limits and isinstance(v, (int, float))})
    wait = float(timeout or limits["timeoutSeconds"])
    wait = max(1.0, min(wait, 3600.0))
    limits["cpuSeconds"] = int(min(limits["cpuSeconds"], wait + 5))
    if info["grants"].get("subprocess"):
        limits["processes"] = None
    port = int(base_url.rsplit(":", 1)[1].split("/")[0])
    token = guard.issue_run_token(SCOPE, info["grants"].get("files", []))
    work = tempfile.mkdtemp(prefix="formcad-macro-")
    out_path, err_path = os.path.join(work, ".stdout"), os.path.join(work, ".stderr")
    copy_path = os.path.join(work, "macro.py")
    with open(copy_path, "wb") as fh:
        fh.write(data)
    env = clean_env({"FORMCAD_MACRO_NAME": info["path"], "FORMCAD_MACRO_SHA256": digest, "FORMCAD_URL": base_url, "FORMCAD_TOKEN": token, "FORMCAD_DOC": doc_id, "FORMCAD_PORT": port, "FORMCAD_LIMITS": json.dumps(limits), "FORMCAD_GRANTS": json.dumps(info["grants"]), "FORMCAD_CALL_TIMEOUT": min(wait, 120)})
    cmd = interpreter() + [copy_path] + [str(a) for a in (args or [])]
    flags = {}
    if os.name == "nt":
        flags["creationflags"] = 0x00000200 | 0x08000000
    else:
        flags["start_new_session"] = True
    started = time.monotonic()
    timed_out = False
    job = False
    try:
        with open(out_path, "wb") as so, open(err_path, "wb") as se:
            proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=so, stderr=se, close_fds=True, shell=False, **flags)
            job = _job_object(proc, limits)
            try:
                code = proc.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill(proc)
                code = proc.wait(timeout=10)
            if not timed_out:
                _kill(proc)
        return {"ok": code == 0 and not timed_out, "exit": code, "timedOut": timed_out, "seconds": round(time.monotonic() - started, 3), "stdout": _tail(out_path), "stderr": _tail(err_path), "limits": {**limits, "jobObject": job, "rlimits": os.name == "posix"}, "macro": info["path"], "sha256": info["sha256"]}
    finally:
        guard.revoke_run_token(token)
        shutil.rmtree(work, ignore_errors=True)
