import asyncio
import os
import shutil
import threading
import uuid
from collections import deque

from app.core import config

try:
    if os.name == "nt":
        from winpty import PtyProcess
    else:
        from ptyprocess import PtyProcessUnicode as PtyProcess
except ImportError:
    PtyProcess = None

SCROLLBACK = 256 * 1024
MIN_COLS, MIN_ROWS = 10, 4
MAX_SESSIONS = 16
RESTARTABLE = ("shell", "claude", "codex", "cursor", "antigravity")
ENGINE_SECRETS = ("FORMCAD_TOKEN", "FORMCAD_GRANTS", "FORMCAD_MACRO_NAME")


class Session:
    def __init__(self, sid: str, title: str, cwd: str, proc, kind: str = "shell", argv: list[str] | None = None, env: dict | None = None) -> None:
        self.id = sid
        self.title = title
        self.cwd = cwd
        self.proc = proc
        self.chunks: deque[str] = deque()
        self.size = 0
        self.alive = proc is not None
        self.subscribers: set[asyncio.Queue] = set()
        self.lock = threading.Lock()
        self.gen = 0
        self.cols = 100
        self.rows = 30
        self.kind = kind
        self.argv = argv
        self.env = env
        self.on_close: list = []

    def describe(self) -> dict:
        return {"id": self.id, "title": self.title, "alive": self.alive, "kind": self.kind, "tip": self.cwd}

    def keep(self, text: str) -> None:
        with self.lock:
            self.chunks.append(text)
            self.size += len(text)
            while self.size > SCROLLBACK and len(self.chunks) > 1:
                self.size -= len(self.chunks.popleft())

    def scrollback(self) -> str:
        with self.lock:
            return "".join(self.chunks)


SESSIONS: dict[str, Session] = {}
_loop: asyncio.AbstractEventLoop | None = None
_port = {"value": config.BACKEND_PORT}


def available() -> bool:
    return PtyProcess is not None


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def note_port(port: int | None) -> int:
    if port:
        _port["value"] = int(port)
    return _port["value"]


def login_shell() -> list[str]:
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe")]
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    return [shell, "-l"]


def _env_file_keys() -> set[str]:
    path = config.BACKEND_DIR / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    except OSError:
        return set()
    return {line.partition("=")[0].strip() for line in lines if "=" in line and not line.strip().startswith("#")}


def base_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ENGINE_SECRETS}
    for key in _env_file_keys():
        env.pop(key, None)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["FORMCAD_TERMINAL"] = "1"
    env["FORMCAD_ENGINE_URL"] = f"http://127.0.0.1:{_port['value']}"
    return env


def workdir() -> str:
    return str(config.projects_dir())


def _deliver(session: Session, text: str | None) -> None:
    for q in list(session.subscribers):
        if q.qsize() < 4000:
            q.put_nowait(text)


def _send(session: Session, text: str | None) -> None:
    if _loop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_deliver, session, text)


def _pump(session: Session, proc, gen: int) -> None:
    while True:
        try:
            text = proc.read(65536)
        except (EOFError, OSError):
            break
        if not text:
            continue
        if session.gen != gen:
            return
        session.keep(text)
        _send(session, text)
    if session.gen != gen:
        return
    session.alive = False
    _send(session, None)


def _spawn(cwd: str, cols: int, rows: int, argv: list[str] | None = None, env: dict | None = None):
    if PtyProcess is None:
        raise OSError("the terminal needs ptyprocess (pywinpty on Windows); run ./formCAD install")
    return PtyProcess.spawn(argv or login_shell(), cwd=cwd, env=env or base_env(), dimensions=(max(MIN_ROWS, rows), max(MIN_COLS, cols)))


def open_session(cwd: str | None = None, cols: int = 100, rows: int = 30, title: str | None = None,
                 argv: list[str] | None = None, env: dict | None = None, kind: str = "shell") -> Session:
    if len(SESSIONS) >= MAX_SESSIONS:
        raise ValueError(f"FormCAD keeps at most {MAX_SESSIONS} terminal tabs. Close one first.")
    where = cwd or workdir()
    if not os.path.isdir(where):
        raise FileNotFoundError(f"There is no folder {where}.")
    proc = _spawn(where, cols, rows, argv, env)
    sid = uuid.uuid4().hex[:12]
    shells = sum(1 for s in SESSIONS.values() if s.kind == "shell")
    session = Session(sid, title or f"Terminal {shells + 1}", where, proc, kind, argv, env)
    session.cols, session.rows = max(MIN_COLS, cols), max(MIN_ROWS, rows)
    SESSIONS[sid] = session
    threading.Thread(target=_pump, args=(session, proc, 0), name=f"pty-{sid}", daemon=True).start()
    return session


def restart(sid: str) -> Session:
    session = get(sid)
    if session.kind not in RESTARTABLE:
        raise ValueError("This tab has no program to restart.")
    old = session.proc
    session.gen += 1
    gen = session.gen
    try:
        old.terminate(force=True)
    except Exception:
        pass
    where = session.cwd if os.path.isdir(session.cwd) else workdir()
    proc = _spawn(where, session.cols, session.rows, session.argv, session.env)
    with session.lock:
        session.chunks.clear()
        session.size = 0
    session.proc = proc
    session.alive = True
    _send(session, "\x1bc")
    threading.Thread(target=_pump, args=(session, proc, gen), name=f"pty-{sid}-{gen}", daemon=True).start()
    return session


def write(sid: str, data: str) -> None:
    session = get(sid)
    if session.proc is not None and session.alive:
        session.proc.write(data)


def resize(sid: str, cols: int, rows: int) -> None:
    session = get(sid)
    session.cols, session.rows = max(MIN_COLS, min(500, cols)), max(MIN_ROWS, min(200, rows))
    if session.alive and session.proc is not None:
        session.proc.setwinsize(session.rows, session.cols)


def close(sid: str) -> None:
    session = SESSIONS.pop(sid, None)
    if session is None:
        return
    session.gen += 1
    if session.proc is not None:
        try:
            session.proc.terminate(force=True)
        except Exception:
            pass
    for done in session.on_close:
        try:
            done()
        except Exception:
            pass
    _send(session, None)


def get(sid: str) -> Session:
    session = SESSIONS.get(sid)
    if session is None:
        raise KeyError(sid)
    return session


def live(kind: str) -> Session | None:
    return next((s for s in SESSIONS.values() if s.kind == kind and s.alive), None)


def listing() -> list[dict]:
    return [s.describe() for s in SESSIONS.values()]


def close_all() -> None:
    for sid in list(SESSIONS):
        close(sid)
