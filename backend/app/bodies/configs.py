import copy
import csv
import io
import json
import os
import re

from app.bodies import hooks, materials
from app.param import expr as X
from app.param import ops
from app.param import store as S

TABLE = "configs"
STATE = "@state"
DEFAULT = "Default"
NAME = re.compile(r"^[^\x00-\x1f@][^\x00-\x1f]{0,79}$")
MAX_CONFIGS = 500
MAX_KEYS = 500
MAX_FILE = 2 * 1024 * 1024
FORMAT = "formcad-design-table"
SUPPRESS_TRUE = {"s", "suppress", "suppressed", "1", "true", "yes", "y"}
SUPPRESS_FALSE = {"u", "unsuppress", "unsuppressed", "0", "false", "no", "n"}


class ConfigError(ValueError):
    pass


def configs(d) -> list:
    t = d.tables.get(TABLE)
    rows = [r for r in (t.values() if t is not None else []) if not str(r.get("name", "")).startswith("@")]
    return sorted(rows, key=lambda r: (not r.get("default", False), r.get("seq", 0)))


def get(d, name):
    t = d.tables.get(TABLE)
    rec = t.get(name) if t is not None else None
    return rec if rec is not None and not rec["name"].startswith("@") else None


def active_name(d) -> str:
    t = d.tables.get(TABLE)
    rec = t.get(STATE) if t is not None else None
    return rec["active"] if rec else DEFAULT


def new_record(name, seq, default=False, description="") -> dict:
    return {"name": name, "description": description, "values": {}, "suppress": {}, "materials": {}, "seq": seq, "default": default}


def ensure_default(d) -> dict:
    rec = get(d, DEFAULT)
    if rec is None:
        rec = new_record(DEFAULT, 0, True, "The values the model has before any configuration changes them.")
        d.table_set(TABLE, rec)
    return rec


def param_expr(d, name):
    for p in S.user_params(d):
        if p["name"].casefold() == name.casefold():
            return p["name"], str(p["expr"])
    for r in S.dim_records(d):
        if r["label"].casefold() == name.casefold():
            return r["label"], str(r.get("expr") or r.get("value") or "0")
    return None, None


def clean_expr(d, name, value):
    exact, current = param_expr(d, name)
    if exact is None:
        raise ConfigError("There is no parameter or dimension called %s." % name)
    text = str(value).strip()
    if not text:
        raise ConfigError("%s needs a value." % exact)
    bad = X.check(text)
    if bad:
        raise ConfigError("%s: %s" % (exact, bad))
    return exact, text


def clean_flag(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in SUPPRESS_TRUE:
        return True
    if text in SUPPRESS_FALSE:
        return False
    raise ConfigError("Suppression is S (suppressed) or U (unsuppressed), not %r." % value)


def body_key(d, raw) -> str:
    text = str(raw).strip()
    if text.startswith("#"):
        text = text[1:]
    if text.isdigit():
        e = d.get(int(text))
        if e is not None and e.kind == "solidbody":
            return str(e.handle)
    found = [e for e in d.ents.values() if e.kind == "solidbody" and e.name and e.name.casefold() == text.casefold()]
    if len(found) == 1:
        return str(found[0].handle)
    if len(found) > 1:
        raise ConfigError("Several bodies are called %s; use #handle." % raw)
    raise ConfigError("There is no body %s." % raw)


def clean_material(name) -> str:
    text = str(name).strip()
    if not text:
        return ""
    if materials.find(text) is None:
        raise ConfigError("There is no material called %s in the library." % text)
    return materials.find(text)["name"]


def check_name(d, name, ignore=""):
    if not isinstance(name, str) or not NAME.match(name.strip()):
        raise ConfigError("A configuration name has 1 to 80 characters and does not start with @.")
    other = get(d, name.strip())
    if other is not None and other["name"].casefold() != ignore.casefold():
        raise ConfigError("There is already a configuration called %s." % name.strip())


def capture_base(d, kind, key):
    base = ensure_default(d)
    store = {"param": "values", "suppress": "suppress", "material": "materials"}[kind]
    if key in base[store]:
        return
    rec = copy.deepcopy(base)
    if kind == "param":
        _n, cur = param_expr(d, key)
        rec["values"][key] = cur
    elif kind == "suppress":
        rec["suppress"][key] = bool(hooks.state(d).get(key, False))
    else:
        e = d.get(int(key))
        rec["materials"][key] = (e.material if e is not None else "") or ""
    d.table_set(TABLE, rec)


def merge(d, rec, values=None, suppress=None, mats=None):
    values = values or {}
    suppress = suppress or {}
    mats = mats or {}
    if len(rec["values"]) + len(values) > MAX_KEYS:
        raise ConfigError("Too many columns.")
    known = hooks.known_features(d)
    for k, v in values.items():
        if v is None or v == "":
            rec["values"].pop(param_expr(d, k)[0] or k, None)
            continue
        name, text = clean_expr(d, k, v)
        capture_base(d, "param", name)
        rec["values"][name] = text
    for k, v in suppress.items():
        name = str(k).strip()
        if not name or len(name) > 80:
            raise ConfigError("A feature name has 1 to 80 characters.")
        if known is not None and name not in known:
            raise ConfigError("There is no feature called %s." % name)
        if v is None or v == "":
            rec["suppress"].pop(name, None)
            continue
        capture_base(d, "suppress", name)
        rec["suppress"][name] = clean_flag(v)
    for k, v in mats.items():
        key = body_key(d, k)
        if v is None or v == "":
            rec["materials"].pop(key, None)
            continue
        capture_base(d, "material", key)
        rec["materials"][key] = clean_material(v)
    return rec


def create(d, name, description="", values=None, suppress=None, mats=None, copy_from=None) -> dict:
    name = str(name).strip()
    check_name(d, name)
    ensure_default(d)
    if len(configs(d)) >= MAX_CONFIGS:
        raise ConfigError("The document holds too many configurations.")
    seq = max([r.get("seq", 0) for r in configs(d)] + [0]) + 1
    rec = new_record(name, seq, False, str(description or "")[:500])
    if copy_from:
        src = get(d, copy_from)
        if src is None:
            raise ConfigError("There is no configuration called %s." % copy_from)
        for key in ("values", "suppress", "materials"):
            rec[key] = copy.deepcopy(src[key])
    merge(d, rec, values, suppress, mats)
    ensure_default(d)
    d.table_set(TABLE, rec)
    return rec


def update(d, name, description=None, values=None, suppress=None, mats=None, new_name=None) -> dict:
    old = get(d, name)
    if old is None:
        raise ConfigError("There is no configuration called %s." % name)
    rec = copy.deepcopy(old)
    if old.get("default") and new_name and new_name != old["name"]:
        raise ConfigError("The Default configuration cannot be renamed.")
    if description is not None:
        rec["description"] = str(description)[:500]
    if old.get("default"):
        for k, v in (values or {}).items():
            if v in (None, ""):
                raise ConfigError("The Default configuration must keep a value for %s." % k)
    merge(d, rec, values, suppress, mats)
    if new_name and new_name.strip() != old["name"]:
        new_name = new_name.strip()
        check_name(d, new_name, old["name"])
        d.table_remove(TABLE, old["name"])
        rec["name"] = new_name
        if active_name(d).casefold() == old["name"].casefold():
            d.table_set(TABLE, {"name": STATE, "active": new_name})
    d.table_set(TABLE, rec)
    return rec


def effective(d, name) -> dict:
    rec = get(d, name)
    if rec is None:
        raise ConfigError("There is no configuration called %s." % name)
    base = ensure_default(d)
    out = {"values": dict(base["values"]), "suppress": dict(base["suppress"]), "materials": dict(base["materials"])}
    if not rec.get("default"):
        for key in out:
            out[key].update(rec[key])
    return out


def delete(d, name) -> dict:
    rec = get(d, name)
    if rec is None:
        raise ConfigError("There is no configuration called %s." % name)
    if rec.get("default"):
        raise ConfigError("The Default configuration cannot be deleted.")
    warnings = []
    if active_name(d).casefold() == rec["name"].casefold():
        warnings = activate(d, DEFAULT)["warnings"]
    d.table_remove(TABLE, rec["name"])
    return {"removed": rec["name"], "warnings": warnings}


def activate(d, name) -> dict:
    rec = get(d, name)
    if rec is None:
        raise ConfigError("There is no configuration called %s." % name)
    eff = effective(d, rec["name"])
    warnings, applied = [], {"values": [], "suppress": [], "materials": []}
    for pname, text in eff["values"].items():
        exact, cur = param_expr(d, pname)
        if exact is None:
            warnings.append("%s is no longer a parameter; skipped." % pname)
            continue
        if cur.strip() != text.strip():
            try:
                ops.set_parameter(d, exact, text)
            except (S.ParamError, X.ExprError) as err:
                raise ConfigError("%s cannot take the value %s: %s" % (exact, text, getattr(err, "message", str(err))))
            applied["values"].append(exact)
    changed = {k: v for k, v in eff["suppress"].items() if bool(hooks.state(d).get(k, False)) != bool(v)}
    if changed:
        applied["suppress"] = hooks.set_suppressed(d, changed)
    for key, mat in eff["materials"].items():
        e = d.get(int(key)) if key.isdigit() else None
        if e is None or e.kind != "solidbody":
            warnings.append("Body %s is gone; its material was skipped." % key)
            continue
        if (e.material or "") != mat:
            materials.assign(d, e, mat)
            applied["materials"].append(e.handle)
    hooks.rebuild(d)
    d.table_set(TABLE, {"name": STATE, "active": rec["name"]})
    return {"active": rec["name"], "applied": applied, "warnings": warnings}


def listing(d) -> dict:
    return {"active": active_name(d), "configs": [copy.deepcopy(r) for r in configs(d)], "suppression": hooks.state(d), "materials_in_use": sorted(m["name"] for m in materials.doc_rows(d))}


def grid(d) -> dict:
    rows = configs(d)
    cols = []

    def add(kind, key):
        cid = "%s:%s" % (kind, key)
        if cid not in [c["id"] for c in cols]:
            cols.append({"id": cid, "kind": kind, "key": key})

    for r in rows:
        for k in r["values"]:
            add("param", k)
    for r in rows:
        for k in r["suppress"]:
            add("suppress", k)
    for r in rows:
        for k in r["materials"]:
            add("material", k)
    for c in cols:
        if c["kind"] == "material":
            e = d.get(int(c["key"]))
            clash = sum(1 for o in d.ents.values() if o.kind == "solidbody" and o.name and e is not None and o.name.casefold() == e.name.casefold())
            c["label"] = e.name if (e is not None and e.name and clash == 1) else "#" + c["key"]
        else:
            c["label"] = c["key"]
    out = []
    for r in rows:
        cells = {}
        for c in cols:
            store = {"param": r["values"], "suppress": r["suppress"], "material": r["materials"]}[c["kind"]]
            if c["key"] in store:
                v = store[c["key"]]
                cells[c["id"]] = ("S" if v else "U") if c["kind"] == "suppress" else v
        out.append({"name": r["name"], "description": r["description"], "cells": cells})
    return {"active": active_name(d), "columns": cols, "rows": out}


def split_id(cid: str):
    kind, _s, key = str(cid).partition(":")
    if kind not in ("param", "suppress", "material") or not key:
        raise ConfigError("A column is param:NAME, suppress:FEATURE or material:BODY, not %r." % cid)
    return kind, key


def apply_grid(d, data) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ConfigError("The table needs a list of rows.")
    rows = data["rows"]
    if len(rows) > MAX_CONFIGS + 1:
        raise ConfigError("The table has too many rows.")
    names = []
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigError("Each row is an object with a name and cells.")
        nm = str(row.get("name") or "").strip()
        if not nm:
            raise ConfigError("A row has no configuration name.")
        if nm.casefold() in [n.casefold() for n in names]:
            raise ConfigError("The configuration %s appears twice." % nm)
        names.append(nm)
    previous = {r["name"].casefold(): r for r in configs(d)}
    for r in configs(d):
        if not r.get("default"):
            d.table_remove(TABLE, r["name"])
    base = ensure_default(d)
    seq = 0
    kept = []
    for row in rows:
        nm = str(row["name"]).strip()
        cells = row.get("cells") or {}
        if not isinstance(cells, dict):
            raise ConfigError("The cells of %s must be an object." % nm)
        values, sup, mats = {}, {}, {}
        for cid, v in cells.items():
            kind, key = split_id(cid)
            (values if kind == "param" else sup if kind == "suppress" else mats)[key] = v
        if nm.casefold() == DEFAULT.casefold():
            rec = copy.deepcopy(get(d, DEFAULT))
            rec["description"] = str(row.get("description", rec["description"]))[:500]
            for k, v in values.items():
                if v not in (None, ""):
                    exact, text = clean_expr(d, k, v)
                    rec["values"][exact] = text
            for k, v in sup.items():
                if v not in (None, ""):
                    rec["suppress"][str(k)] = clean_flag(v)
            for k, v in mats.items():
                if v not in (None, ""):
                    rec["materials"][body_key(d, k)] = clean_material(v)
            d.table_set(TABLE, rec)
            continue
        seq += 1
        check_name(d, nm)
        rec = new_record(nm, seq, False, str(row.get("description") or "")[:500])
        merge(d, rec, values, sup, mats)
        d.table_set(TABLE, rec)
        kept.append(nm)
    keep_active = active_name(d) if active_name(d).casefold() in [n.casefold() for n in kept] else DEFAULT
    shown = activate(d, keep_active)
    return {"configs": kept, "replaced": len(previous) - (1 if DEFAULT.casefold() in previous else 0), "active": shown["active"], "warnings": shown["warnings"]}


def cell_text(value: str) -> str:
    text = str(value)
    if text[:1] in ("=", "+", "@") or (text[:1] == "-" and len(text) > 1 and not (text[1].isdigit() or text[1] in ".(")):
        return " " + text
    return text


def to_csv(d) -> str:
    g = grid(d)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    head = ["Configuration", "Description"]
    for c in g["columns"]:
        head.append(c["label"] if c["kind"] == "param" else "%s:%s" % (c["kind"], c["label"]))
    w.writerow(head)
    for row in g["rows"]:
        w.writerow([cell_text(row["name"]), cell_text(row["description"])] + [cell_text(row["cells"].get(c["id"], "")) for c in g["columns"]])
    return out.getvalue()


def parse_header(d, head):
    if len(head) < 1 or head[0].strip().lower() not in ("configuration", "name", "config"):
        raise ConfigError("The first column must be named Configuration.")
    cols = []
    for i, raw in enumerate(head):
        text = raw.strip()
        if i == 0:
            continue
        if text.lower() == "description":
            cols.append(("description", None))
            continue
        low = text.lower()
        if low.startswith("suppress:"):
            cols.append(("suppress", text[9:].strip()))
        elif low.startswith("material:"):
            cols.append(("material", text[9:].strip()))
        elif low.startswith("param:"):
            cols.append(("param", text[6:].strip()))
        elif text:
            cols.append(("param", text))
        else:
            raise ConfigError("Column %d has no name." % (i + 1))
    if len(cols) > MAX_KEYS:
        raise ConfigError("The table has too many columns.")
    return cols


def from_csv(d, text) -> dict:
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 1:
        raise ConfigError("The file is empty.")
    if len(rows) > MAX_CONFIGS + 2:
        raise ConfigError("The file has too many rows.")
    cols = parse_header(d, rows[0])
    data_rows = []
    for line in rows[1:]:
        if len(line) > len(cols) + 1:
            raise ConfigError("The row %s has more cells than columns." % (line[0] if line else "?"))
        line = list(line) + [""] * (len(cols) + 1 - len(line))
        row = {"name": line[0].strip(), "cells": {}}
        for (kind, key), cell in zip(cols, line[1:]):
            cell = cell.strip()
            if kind == "description":
                row["description"] = cell
            elif cell:
                row["cells"]["%s:%s" % (kind, key)] = cell
        data_rows.append(row)
    return apply_grid(d, {"rows": data_rows})


def read_text(path: str, suffixes) -> str:
    full = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if os.path.splitext(full)[1].lower() not in suffixes:
        raise ConfigError("That file type is not read here. Use one of: %s." % ", ".join(suffixes))
    if not os.path.isfile(full):
        raise ConfigError("The file does not exist.")
    if os.path.getsize(full) > MAX_FILE:
        raise ConfigError("The file is larger than 2 MB.")
    try:
        with open(full, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        raise ConfigError("The file could not be read as UTF-8 text.")


def export_file(d, path: str) -> dict:
    from app.core import outputs

    try:
        full = outputs.checked(path, (".csv", ".fcdt"), ".csv")
    except outputs.OutputRefused as err:
        raise ConfigError(str(err))
    if full.lower().endswith(".fcdt"):
        text = json.dumps({"format": FORMAT, "version": 1, **grid(d)}, indent=2)
    else:
        text = to_csv(d)
    try:
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as err:
        raise ConfigError("The file could not be written (%s)." % err.strerror)
    return {"path": full, "rows": len(grid(d)["rows"])}


def import_file(d, path: str) -> dict:
    text = read_text(path, (".csv", ".fcdt"))
    if str(path).lower().endswith(".fcdt"):
        try:
            data = json.loads(text)
        except ValueError:
            raise ConfigError("The file is not valid JSON.")
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise ConfigError("That is not a FormCAD design table.")
        return apply_grid(d, data)
    return from_csv(d, text)
