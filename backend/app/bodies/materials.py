import copy
import json
import math
import os
import tempfile
import threading
from pathlib import Path

from app.core import config

TABLE = "materials"
SHIPPED = Path(__file__).resolve().parents[1] / "data" / "materials.json"
USER_NAME = "materials-user.json"
MAX_ROWS = 2000
MAX_TEXT = 2000
UNITS = {"density": "kg/m3", "youngs_modulus": "GPa", "poissons_ratio": "1"}
FIELDS = ("name", "grade", "density", "youngs_modulus", "poissons_ratio", "provenance", "single_source_fields", "single_source")
_lock = threading.Lock()


class MaterialError(ValueError):
    pass


def user_path() -> Path:
    return config.data_dir() / USER_NAME


def read_rows(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("materials") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)][:MAX_ROWS] if isinstance(rows, list) else []


def number(row: dict, key: str, low: float, high: float, label: str, inclusive_low: bool = False) -> float:
    try:
        v = float(row.get(key))
    except (TypeError, ValueError):
        raise MaterialError("%s needs a number." % label)
    if not math.isfinite(v) or v > high or v < low or (v == low and not inclusive_low):
        raise MaterialError("%s must be between %g and %g." % (label, low, high))
    return v


def clean_row(row: dict) -> dict:
    name = str(row.get("name") or "").strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name) or name.startswith("@"):
        raise MaterialError("A material needs a name of 1 to 80 characters.")
    out = {
        "name": name,
        "grade": str(row.get("grade") or "")[:120],
        "density": number(row, "density", 0.0, 30000.0, "Density (kg/m3)"),
        "youngs_modulus": number(row, "youngs_modulus", 0.0, 2000.0, "Young's modulus (GPa)"),
        "poissons_ratio": number(row, "poissons_ratio", -1.0, 0.5, "Poisson's ratio"),
        "provenance": str(row.get("provenance") or "").strip()[:MAX_TEXT] or "Entered by the user; no external source recorded.",
        "single_source_fields": [f for f in (row.get("single_source_fields") or []) if f in ("density", "youngs_modulus", "poissons_ratio")],
        "single_source": bool(row.get("single_source", False)),
    }
    return out


def shipped_rows() -> list:
    return [dict(clean_row(r), origin="shipped") for r in read_rows(SHIPPED)]


def user_rows() -> list:
    out = []
    for r in read_rows(user_path()):
        try:
            out.append(dict(clean_row(r), origin="user"))
        except MaterialError:
            continue
    return out


def library() -> dict:
    rows = shipped_rows()
    taken = {r["name"].casefold() for r in rows}
    for r in user_rows():
        if r["name"].casefold() not in taken:
            rows.append(r)
            taken.add(r["name"].casefold())
    return {"units": dict(UNITS), "materials": rows}


def find(name: str):
    for r in library()["materials"]:
        if r["name"].casefold() == str(name).casefold():
            return r
    return None


def write_user(rows: list) -> None:
    path = user_path()
    payload = {"format": "formcad-materials", "version": 1, "units": dict(UNITS), "materials": [{k: r[k] for k in FIELDS if k in r} for r in rows]}
    fd, tmp = tempfile.mkstemp(prefix="materials-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except OSError as err:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise MaterialError("The materials file could not be written (%s)." % err.strerror)


def add_user(row: dict) -> dict:
    clean = clean_row(row)
    with _lock:
        if find(clean["name"]) is not None:
            raise MaterialError("A material called %s already exists." % clean["name"])
        rows = [dict(r) for r in user_rows()]
        if len(rows) >= MAX_ROWS:
            raise MaterialError("The materials library is full.")
        rows.append(clean)
        write_user(rows)
    return dict(clean, origin="user")


def update_user(name: str, row: dict) -> dict:
    with _lock:
        rows = [dict(r) for r in user_rows()]
        at = next((i for i, r in enumerate(rows) if r["name"].casefold() == name.casefold()), None)
        if at is None:
            raise MaterialError("Only materials you added can be changed; %s is not one of them." % name)
        merged = dict(rows[at])
        merged.update({k: v for k, v in row.items() if k in FIELDS})
        clean = clean_row(merged)
        if clean["name"].casefold() != name.casefold() and find(clean["name"]) is not None:
            raise MaterialError("A material called %s already exists." % clean["name"])
        rows[at] = clean
        write_user(rows)
    return dict(clean, origin="user")


def delete_user(name: str) -> dict:
    with _lock:
        rows = [dict(r) for r in user_rows()]
        keep = [r for r in rows if r["name"].casefold() != name.casefold()]
        if len(keep) == len(rows):
            raise MaterialError("Only materials you added can be removed; %s is not one of them." % name)
        write_user(keep)
    return {"removed": name}


def doc_rows(d) -> list:
    t = d.tables.get(TABLE)
    return t.values() if t is not None else []


def doc_row(d, name: str):
    t = d.tables.get(TABLE)
    return t.get(name) if (t is not None and name) else None


def bring_in(d, name: str, refresh: bool = False) -> dict:
    have = doc_row(d, name)
    if have is not None and not refresh:
        return have
    src = find(name)
    if src is None:
        if have is not None:
            return have
        raise MaterialError("There is no material called %s in the library." % name)
    rec = {k: copy.deepcopy(src[k]) for k in FIELDS if k in src}
    d.table_set(TABLE, rec)
    return rec


def assign(d, body, name: str, refresh: bool = False) -> dict:
    if not name:
        target = d.modify(body.handle)
        target.material = ""
        return {"handle": body.handle, "material": ""}
    rec = bring_in(d, name, refresh)
    target = d.modify(body.handle)
    target.material = rec["name"]
    return {"handle": body.handle, "material": rec["name"], "density": rec["density"]}


def density_of(d, body):
    rec = doc_row(d, getattr(body, "material", ""))
    return float(rec["density"]) if rec is not None else None
