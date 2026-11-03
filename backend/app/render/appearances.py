import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path

from app.core import config

SHIPPED = Path(__file__).resolve().parents[1] / "data" / "render" / "appearances.json"
USER_NAME = "appearances-user.json"
MAX_ROWS = 1000
MAX_TEXT = 2000
DEFAULT_NAME = "Neutral grey"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CATEGORIES = ("metal", "plastic", "paint", "transparent", "emissive", "other")
UNIT_FIELDS = ("metallic", "roughness", "transmission", "clearcoat", "clearcoat_roughness", "sheen", "sheen_roughness", "opacity")
COLOR_FIELDS = ("base_color", "emissive", "sheen_color", "attenuation_color")
NUMBER_FIELDS = {"ior": (1.0, 2.5), "thickness": (0.0, 1000.0), "attenuation_distance": (0.0, 100000.0), "emissive_intensity": (0.0, 100.0)}
DEFAULTS = {"base_color": "#9a9ca0", "metallic": 0.0, "roughness": 0.5, "ior": 1.5, "transmission": 0.0, "thickness": 0.0, "clearcoat": 0.0, "clearcoat_roughness": 0.0, "sheen": 0.0, "sheen_roughness": 0.5, "sheen_color": "#000000", "emissive": "#000000", "emissive_intensity": 0.0, "opacity": 1.0, "attenuation_color": "#ffffff", "attenuation_distance": 0.0}
FIELDS = ("name", "category", "provenance", "sources") + tuple(DEFAULTS)
_lock = threading.Lock()


class AppearanceError(ValueError):
    pass


def user_path() -> Path:
    return config.data_dir() / USER_NAME


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def shipped_file() -> dict:
    return _read(SHIPPED)


def sources() -> dict:
    return dict(shipped_file().get("sources") or {})


def clean_row(row: dict) -> dict:
    name = str(row.get("name") or "").strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name) or name.startswith("@"):
        raise AppearanceError("An appearance needs a name of 1 to 80 characters.")
    cat = str(row.get("category") or "other")
    out = {"name": name, "category": cat if cat in CATEGORIES else "other"}
    for key in COLOR_FIELDS:
        v = row.get(key, DEFAULTS[key])
        if not isinstance(v, str) or not HEX.match(v):
            raise AppearanceError("%s must be a colour like #rrggbb." % key)
        out[key] = v.lower()
    for key in UNIT_FIELDS:
        out[key] = _num(row, key, 0.0, 1.0)
    for key, (lo, hi) in NUMBER_FIELDS.items():
        out[key] = _num(row, key, lo, hi)
    out["provenance"] = str(row.get("provenance") or "").strip()[:MAX_TEXT] or "Entered by the user; no external source recorded."
    src = row.get("sources") if isinstance(row.get("sources"), dict) else {}
    out["sources"] = {k: str(v)[:80] for k, v in src.items() if k in DEFAULTS and isinstance(v, str)}
    for key in DEFAULTS:
        out["sources"].setdefault(key, "authored" if key in row else "default")
    return out


def _num(row: dict, key: str, lo: float, hi: float) -> float:
    v = row.get(key, DEFAULTS[key])
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise AppearanceError("%s needs a number." % key)
    if not math.isfinite(v) or v < lo or v > hi:
        raise AppearanceError("%s must be between %g and %g." % (key, lo, hi))
    return v


def shipped_rows() -> list:
    out = []
    for r in shipped_file().get("appearances") or []:
        if isinstance(r, dict):
            out.append(dict(clean_row(r), origin="shipped"))
    return out


def user_rows() -> list:
    out = []
    rows = _read(user_path()).get("appearances")
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            try:
                out.append(dict(clean_row(r), origin="user"))
            except AppearanceError:
                continue
    return out[:MAX_ROWS]


def library() -> dict:
    rows = shipped_rows()
    taken = {r["name"].casefold() for r in rows}
    for r in user_rows():
        if r["name"].casefold() not in taken:
            rows.append(r)
            taken.add(r["name"].casefold())
    return {"sources": sources(), "material_map": dict(shipped_file().get("material_map") or {}), "default": DEFAULT_NAME, "appearances": rows}


def find(name: str):
    key = str(name or "").casefold()
    for r in library()["appearances"]:
        if r["name"].casefold() == key:
            return r
    return None


def default_row() -> dict:
    return find(DEFAULT_NAME) or dict(clean_row({"name": DEFAULT_NAME}), origin="shipped")


def for_material(material: str):
    entry = (shipped_file().get("material_map") or {}).get(material or "")
    if isinstance(entry, dict):
        return find(entry.get("appearance", ""))
    return None


def _write(rows: list) -> None:
    path = user_path()
    payload = {"format": "formcad-appearances", "version": 1, "appearances": [{k: r[k] for k in FIELDS if k in r} for r in rows]}
    fd, tmp = tempfile.mkstemp(prefix="appearances-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except OSError as err:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise AppearanceError("The appearances file could not be written (%s)." % err.strerror)


def add_user(row: dict) -> dict:
    clean = clean_row(row)
    with _lock:
        if find(clean["name"]) is not None:
            raise AppearanceError("An appearance called %s already exists." % clean["name"])
        rows = user_rows()
        if len(rows) >= MAX_ROWS:
            raise AppearanceError("The appearance library is full.")
        rows.append(clean)
        _write(rows)
    return dict(clean, origin="user")


def update_user(name: str, row: dict) -> dict:
    with _lock:
        rows = user_rows()
        at = next((i for i, r in enumerate(rows) if r["name"].casefold() == name.casefold()), None)
        if at is None:
            raise AppearanceError("Only appearances you added can be changed; %s is not one of them." % name)
        merged = dict(rows[at])
        merged.update({k: v for k, v in row.items() if k in FIELDS})
        clean = clean_row(merged)
        if clean["name"].casefold() != name.casefold() and find(clean["name"]) is not None:
            raise AppearanceError("An appearance called %s already exists." % clean["name"])
        rows[at] = clean
        _write(rows)
    return dict(clean, origin="user")


def delete_user(name: str) -> dict:
    with _lock:
        rows = user_rows()
        keep = [r for r in rows if r["name"].casefold() != name.casefold()]
        if len(keep) == len(rows):
            raise AppearanceError("Only appearances you added can be removed; %s is not one of them." % name)
        _write(keep)
    return {"removed": name}
