import json
import os

MAX_READ = 64 * 1024 * 1024
MAX_WRITE = 64 * 1024 * 1024
FILE = "lisp-settings.json"


def _data():
    from app.core import config

    return config.data_dir()


def default_folder() -> str:
    return str(_data() / "support")


def _load() -> dict:
    try:
        with open(os.path.join(str(_data()), FILE), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def folders() -> list:
    raw = _load().get("support")
    out = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip() and "\x00" not in item:
                p = os.path.abspath(os.path.expanduser(item.strip()))
                if not protected(p):
                    out.append(p)
    return out or [default_folder()]


def protected(path: str) -> str:
    data = os.path.realpath(str(_data()))
    real = os.path.realpath(path)
    if real == data or data.startswith(real.rstrip(os.sep) + os.sep):
        return "the FormCAD data folder or a folder that holds it"
    for name in ("plugins", "macros"):
        keep = os.path.join(data, name)
        if real == keep or real.startswith(keep + os.sep) or keep.startswith(real.rstrip(os.sep) + os.sep):
            return "the %s folder" % name
    return ""


def set_folders(items) -> list:
    clean = []
    for item in items or []:
        if isinstance(item, str) and item.strip() and "\x00" not in item:
            p = os.path.abspath(os.path.expanduser(item.strip()))
            why = protected(p)
            if why:
                raise ValueError("A support folder cannot be %s: %s" % (why, p))
            if p not in clean:
                clean.append(p)
    data = _load()
    data["support"] = clean
    path = os.path.join(str(_data()), FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)
    return folders()


def memory_mb() -> int:
    raw = _load().get("memory_mb")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw == raw:
        return int(min(max(raw, 16), 4096))
    return 128


def primary() -> str:
    return folders()[0]


def _inside(real: str, folder: str) -> bool:
    try:
        base = os.path.realpath(folder)
        return os.path.commonpath([real, base]) == base
    except ValueError:
        return False


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def resolve_read(path: str):
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    p = _norm(path)
    dirs = folders()
    if os.path.isabs(p):
        real = os.path.realpath(p)
        if any(_inside(real, d) for d in dirs) and os.path.isfile(real):
            return real
        return None
    for d in dirs:
        real = os.path.realpath(os.path.join(d, p))
        if _inside(real, d) and os.path.isfile(real):
            return real
    return None


def resolve_write(path: str):
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    p = _norm(path)
    dirs = folders()
    if os.path.isabs(p):
        cands = [(None, p)]
    else:
        cands = [(d, os.path.join(d, p)) for d in dirs[:1]]
    for d, full in cands:
        if d is not None:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                continue
        parent = os.path.realpath(os.path.dirname(full))
        name = os.path.basename(full)
        if not name or name in (".", ".."):
            continue
        real = os.path.join(parent, name)
        if os.path.islink(real):
            real = os.path.realpath(real)
        if not os.path.isdir(parent):
            continue
        if any(_inside(parent, x) for x in dirs) and (d is None or _inside(parent, d)) and any(_inside(os.path.realpath(real), x) for x in dirs):
            return real
    return None


def read_text(real: str):
    try:
        if os.path.getsize(real) > MAX_READ:
            return None
        with open(real, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
