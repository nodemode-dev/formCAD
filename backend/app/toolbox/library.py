import copy
import csv
import io
import json
import os
import re
import threading

from app.cmd import barred
from app.core import config
from app.toolbox import gens

SCHEMA = 1
MAX_FAMILIES = 200
MAX_ROWS = 5000
MAX_BYTES = 2 * 1024 * 1024
MAX_LIBRARY_BYTES = 16 * 1024 * 1024
MAX_PROBLEMS = 50
AGENT_ROWS = 500
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,39}$")
EXTS = (".csv", ".tsv", ".txt")
LOCK = threading.RLock()


class LibraryError(ValueError):
    pass


def file_path() -> str:
    return os.path.join(str(config.data_dir()), "toolbox", "library.json")


def blank() -> dict:
    return {"schema": SCHEMA, "families": {}}


def load() -> dict:
    path = file_path()
    if not os.path.isfile(path):
        return blank()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raise LibraryError("The user library file cannot be read.")
    if not isinstance(raw, dict) or not isinstance(raw.get("families"), dict):
        return blank()
    if int(raw.get("schema", 1)) > SCHEMA:
        raise LibraryError("The user library was written by a newer FormCAD.")
    return raw


def save(lib: dict) -> None:
    path = file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    text = json.dumps(lib, indent=1, sort_keys=True)
    if len(text) > MAX_LIBRARY_BYTES:
        raise LibraryError("The user library would be larger than %d MB; remove a family first." % (MAX_LIBRARY_BYTES // (1024 * 1024)))
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def view(lib: dict) -> dict:
    fams = []
    for f in lib["families"].values():
        fams.append({"id": f["id"], "label": f["label"], "kind": f["kind"], "source": f.get("source", ""), "unit": f.get("unit", "mm"), "rows": len(f["rows"])})
    return {"schema": SCHEMA, "families": fams, "limits": {"families": MAX_FAMILIES, "rows": MAX_ROWS}, "note": gens.NOTE}


def listing() -> dict:
    with LOCK:
        return view(load())


def family(fid: str) -> dict:
    with LOCK:
        lib = load()
    f = lib["families"].get(str(fid))
    if f is None:
        raise LibraryError("There is no library family %s." % fid)
    return copy.deepcopy(f)


def _fid(value, label="") -> str:
    fid = str(value or "").strip() or re.sub(r"[^A-Za-z0-9_\-]+", "_", str(label or "family")).strip("_")[:40]
    if not ID_RE.match(fid):
        raise LibraryError("A family id starts with a letter and holds letters, digits, underscores and hyphens (up to 40).")
    return fid


def _row(kind: str, name, params: dict, unit_scale: float, skip=()) -> dict:
    spec = {q["name"]: q for q in gens.KINDS[kind]["params"]}
    scaled = {}
    for k, v in params.items():
        if k not in spec:
            continue
        if v in (None, ""):
            continue
        try:
            x = float(str(v).replace(",", ".")) if isinstance(v, str) else float(v)
        except (TypeError, ValueError):
            raise LibraryError("%s is not a number: %s." % (spec[k]["label"], v))
        scaled[k] = x * unit_scale if k not in ("pitch", "race_ratio", "groove") else x
    p = gens.clean(kind, scaled)
    label = str(name or "").strip()[:80] or gens.designation(kind, p)
    return {"name": label, "params": {k: v for k, v in scaled.items()}}


def add_family(kind: str, label: str, fid: str = "", source: str = "", unit: str = "mm", caller: str = "") -> dict:
    if kind not in gens.KINDS:
        raise LibraryError("The kind is one of %s." % ", ".join(gens.KINDS))
    if unit not in ("mm", "inch"):
        raise LibraryError("The unit is mm or inch.")
    label = str(label or "").strip()[:80]
    if not label:
        raise LibraryError("A family needs a name.")
    with LOCK:
        lib = load()
        fid = _fid(fid, label)
        if fid in lib["families"]:
            raise LibraryError("There is already a family %s." % fid)
        if len(lib["families"]) >= MAX_FAMILIES:
            raise LibraryError("The user library holds at most %d families." % MAX_FAMILIES)
        lib["families"][fid] = {"id": fid, "label": label, "kind": kind, "source": str(source or "")[:300], "unit": unit, "rows": []}
        save(lib)
        return copy.deepcopy(lib["families"][fid])


def remove_family(fid: str) -> dict:
    with LOCK:
        lib = load()
        if str(fid) not in lib["families"]:
            raise LibraryError("There is no library family %s." % fid)
        gone = lib["families"].pop(str(fid))
        save(lib)
    return {"removed": gone["id"], "rows": len(gone["rows"])}


def add_row(fid: str, name: str, params: dict) -> dict:
    with LOCK:
        lib = load()
        f = lib["families"].get(str(fid))
        if f is None:
            raise LibraryError("There is no library family %s." % fid)
        if len(f["rows"]) >= MAX_ROWS:
            raise LibraryError("A family holds at most %d rows." % MAX_ROWS)
        scale = 25.4 if f.get("unit") == "inch" else 1.0
        row = _row(f["kind"], name, params or {}, scale)
        if any(r["name"] == row["name"] for r in f["rows"]):
            raise LibraryError("The family already has a row named %s." % row["name"])
        f["rows"].append(row)
        save(lib)
        return row


def remove_row(fid: str, name: str) -> dict:
    with LOCK:
        lib = load()
        f = lib["families"].get(str(fid))
        if f is None:
            raise LibraryError("There is no library family %s." % fid)
        keep = [r for r in f["rows"] if r["name"] != name]
        if len(keep) == len(f["rows"]):
            raise LibraryError("The family has no row %s." % name)
        f["rows"] = keep
        save(lib)
    return {"removed": name}


def resolve(fid: str, name: str) -> tuple:
    f = family(fid)
    for r in f["rows"]:
        if r["name"] == name:
            return f["kind"], dict(r["params"])
    raise LibraryError("The family %s has no row %s." % (fid, name))


def read_text(path: str, caller: str = "", runner=None) -> tuple:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw or "\x00" in raw:
        raise LibraryError("Give the size table file.")
    why = barred.path_refusal(raw, runner) if caller else ""
    if why:
        raise LibraryError(why)
    full = os.path.realpath(raw)
    if os.path.splitext(full)[1].lower() not in EXTS:
        raise LibraryError("A size table is a %s file." % ", ".join(EXTS))
    if not os.path.isfile(full):
        raise LibraryError("The file %s is not there." % os.path.basename(raw))
    if os.path.getsize(full) > MAX_BYTES:
        raise LibraryError("The size table is larger than %d MB." % (MAX_BYTES // (1024 * 1024)))
    with open(full, "rb") as fh:
        data = fh.read(MAX_BYTES + 1)
    if b"\x00" in data[:4096]:
        raise LibraryError("The file is not a text table.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return full, text


def parse_table(text: str) -> list:
    head = text[:2000]
    delim = max((",", ";", "\t"), key=lambda c: head.count(c))
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    except csv.Error as err:
        raise LibraryError("The table could not be read as text with a comma, semicolon or tab separator: %s." % err)
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise LibraryError("The table needs a header row and at least one size row.")
    return rows


def import_csv(*args, **kwargs) -> dict:
    with LOCK:
        before = set(load()["families"])
        try:
            return import_rows(*args, **kwargs)
        except LibraryError:
            lib = load()
            for fid in set(lib["families"]) - before:
                remove_family(fid)
            raise


def import_rows(path: str, fid: str, kind: str = "", label: str = "", mapping: dict | None = None, unit: str = "", source: str = "", replace: bool = False, caller: str = "", runner=None) -> dict:
    full, text = read_text(path, caller, runner)
    rows = parse_table(text)
    limit = AGENT_ROWS if caller else MAX_ROWS
    if len(rows) - 1 > limit:
        raise LibraryError("The table has more than %d rows." % limit)
    header = [h.strip() for h in rows[0]]
    keys = {re.sub(r"[^a-z0-9_]+", "_", h.lower()).strip("_"): i for i, h in enumerate(header)}
    with LOCK:
        lib = load()
        f = lib["families"].get(str(fid))
        created = f is None
        if f is None:
            if kind not in gens.KINDS:
                raise LibraryError("A new family needs kind, one of %s." % ", ".join(gens.KINDS))
            f = add_family(kind, label or fid, fid, source or os.path.basename(full), unit or "mm")
            lib = load()
            f = lib["families"][f["id"]]
        k = f["kind"]
        scale = 25.4 if (unit or f.get("unit")) == "inch" else 1.0
        spec = [q["name"] for q in gens.KINDS[k]["params"]]
        colmap = {}
        for name in spec:
            if name in keys:
                colmap[name] = keys[name]
        for col, param in (mapping or {}).items():
            c = re.sub(r"[^a-z0-9_]+", "_", str(col).lower()).strip("_")
            if c not in keys:
                raise LibraryError("The table has no column %s." % col)
            if param not in spec:
                raise LibraryError("%s has no parameter %s." % (gens.KINDS[k]["label"], param))
            colmap[param] = keys[c]
        name_col = keys.get("name", keys.get("designation", keys.get("size")))
        if not colmap:
            raise LibraryError("No column matches a parameter (%s); map the columns." % ", ".join(spec))
        if replace:
            f["rows"] = []
        have = {r["name"] for r in f["rows"]}
        added, problems, dup = 0, [], 0
        for n, r in enumerate(rows[1:], start=2):
            if len(f["rows"]) >= MAX_ROWS:
                problems.append("Row %d: the family is full (%d rows)." % (n, MAX_ROWS))
                break
            try:
                params = {p: r[i] for p, i in colmap.items() if i < len(r)}
                row = _row(k, r[name_col] if name_col is not None and name_col < len(r) else "", params, scale)
            except (LibraryError, gens.GenError) as err:
                if len(problems) < MAX_PROBLEMS:
                    problems.append("Row %d: %s" % (n, err))
                continue
            if row["name"] in have:
                dup += 1
                continue
            have.add(row["name"])
            f["rows"].append(row)
            added += 1
        if created and added == 0:
            remove_family(f["id"])
            raise LibraryError("No row of the table could be used, so no family was created. %s" % " ".join(problems[:3]))
        lib["families"][f["id"]] = f
        save(lib)
    return {"family": f["id"], "kind": k, "file": full, "added": added, "duplicates": dup, "skipped": len(rows) - 1 - added - dup, "problems": problems, "rows": len(f["rows"])}
