import os
import re
from pathlib import Path

from app.core import config

SERVICE = "FormCAD"


def _store():
    try:
        import keyring
        from keyring.backends import fail, null

        kr = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(kr, (fail.Keyring, null.Keyring)) or getattr(kr, "priority", 1) <= 0:
        return None
    return kr


def _file(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    folder = config.data_dir() / "secrets"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    return folder / safe


def _file_read(name: str) -> str | None:
    try:
        return _file(name).read_text(encoding="utf-8") or None
    except OSError:
        return None


def _file_write(name: str, value: str) -> None:
    fd = os.open(_file(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)


def _file_clear(name: str) -> None:
    try:
        _file(name).unlink()
    except OSError:
        pass


def where() -> dict:
    kr = _store()
    return {"store": "system" if kr else "file", "backend": type(kr).__name__ if kr else "file readable only by you"}


def get(name: str) -> str | None:
    kr = _store()
    if not kr:
        return _file_read(name)
    try:
        value = kr.get_password(SERVICE, name)
    except Exception:
        value = None
    if value:
        return value
    legacy = _file_read(name)
    if legacy:
        try:
            kr.set_password(SERVICE, name, legacy)
            if kr.get_password(SERVICE, name) == legacy:
                _file_clear(name)
        except Exception:
            pass
    return legacy


def put(name: str, value: str) -> str:
    kr = _store()
    if kr:
        try:
            kr.set_password(SERVICE, name, value)
            if kr.get_password(SERVICE, name) == value:
                _file_clear(name)
                return "system"
        except Exception:
            pass
    _file_write(name, value)
    return "file"


def delete(name: str) -> None:
    kr = _store()
    if kr:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    _file_clear(name)
