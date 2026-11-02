import os
import sys
from pathlib import Path

from app import __version__

APP_NAME = "FormCAD"
VERSION = __version__
FRONTEND_PORT = 5290
BACKEND_PORT = 8290
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def _load_env_file() -> None:
    env_file = BACKEND_DIR / ".env"
    if not env_file.is_file():
        return
    for entry in env_file.read_text(encoding="utf-8").splitlines():
        entry = entry.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, _, value = entry.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            os.environ.setdefault(key, value)


_load_env_file()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def portable_dir() -> Path | None:
    frozen = getattr(sys, "frozen", False)
    beside = Path(sys.executable).resolve().parent if frozen else BACKEND_DIR
    marker = frozen and any((beside / name).is_file() for name in ("portable", "portable.txt"))
    if os.environ.get("FORMCAD_PORTABLE") == "1" or marker:
        return beside / "FormCADData"
    return None


def platform_data_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "FormCAD"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "FormCAD"
    base = Path(os.environ.get("XDG_DATA_HOME") or ".")
    return (base if base.is_absolute() else home / ".local" / "share") / "FormCAD"


def data_dir() -> Path:
    raw = os.environ.get("FORMCAD_DATA_DIR")
    if raw:
        return _ensure(Path(raw).expanduser())
    portable = portable_dir()
    if portable:
        return _ensure(portable)
    return _ensure(platform_data_dir())


def data_dir_source() -> str:
    if os.environ.get("FORMCAD_DATA_DIR"):
        return "override"
    return "portable" if portable_dir() else "default"


def projects_dir() -> Path:
    raw = os.environ.get("FORMCAD_LIBRARY_DIR", "").strip()
    if raw:
        try:
            return _ensure(Path(raw).expanduser())
        except OSError:
            pass
    return _ensure(data_dir() / "Projects")


def outputs_dir() -> Path:
    return _ensure(data_dir() / "Outputs")


def autosave_dir() -> Path:
    folder = data_dir() / "Autosave"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def dist_dir() -> Path | None:
    raw = os.environ.get("FORMCAD_DIST")
    folder = Path(raw).expanduser() if raw else REPO_DIR / "frontend" / "dist"
    return folder if (folder / "index.html").is_file() else None


def is_desktop() -> bool:
    return os.environ.get("FORMCAD_DESKTOP") == "1"


def cors_origins() -> list[str]:
    raw = os.environ.get("FORMCAD_CORS_ORIGINS")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [f"http://localhost:{FRONTEND_PORT}", f"http://127.0.0.1:{FRONTEND_PORT}"]


def allowed_origins() -> list[str]:
    preview = FRONTEND_PORT + 1
    return [
        *cors_origins(),
        f"http://localhost:{preview}",
        f"http://127.0.0.1:{preview}",
        f"http://127.0.0.1:{BACKEND_PORT}",
        "tauri://localhost",
        "http://tauri.localhost",
    ]
