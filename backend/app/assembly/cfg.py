import copy

from app.assembly import store
from app.assembly.store import AssemblyError, CONFIGS, DEFAULT_CONFIG

KEYS = ("suppress", "visible", "component_config", "patterns")


def configs(d) -> list:
    return sorted(store.configs(d), key=lambda r: (not r.get("default"), r["name"].casefold()))


def active_name(d) -> str:
    return store.header(d).get("active_config") or DEFAULT_CONFIG


def get(d, name: str):
    return store.get_config(d, str(name or "").strip())


def need(d, name: str) -> dict:
    rec = get(d, name)
    if rec is None:
        raise AssemblyError("There is no configuration called %s." % name)
    return rec


def blank(name: str, default: bool = False, description: str = "") -> dict:
    return {"name": name, "description": description, "default": default, "suppress": {}, "visible": {}, "component_config": {}, "patterns": {}}


def base_value(d, kind: str, key: str):
    if kind == "patterns":
        p = store.get_pattern(d, key)
        return bool(p.get("suppressed")) if p else False
    rec = store.get(d, key)
    if rec is None:
        return None
    if kind == "suppress":
        return bool(rec.get("suppressed"))
    if kind == "visible":
        return bool(rec.get("visible", True))
    return str(rec.get("config") or "")


def ensure_default(d) -> dict:
    rec = get(d, DEFAULT_CONFIG)
    if rec is None or not rec.get("default"):
        rec = blank(DEFAULT_CONFIG, True, "The state the assembly had before any configuration was made.")
        d.table_set(CONFIGS, rec)
    return d.tables[CONFIGS].get(DEFAULT_CONFIG)


def check_name(d, name: str, ignore: str = "") -> str:
    n = str(name or "").strip()
    if not n or len(n) > 60 or any(c in n for c in "\x00\r\n"):
        raise AssemblyError("A configuration needs a name of up to 60 characters.")
    for r in store.configs(d):
        if r["name"].casefold() == n.casefold() and r["name"].casefold() != ignore.casefold():
            raise AssemblyError("There is already a configuration called %s." % r["name"])
    return n


def _clean(d, kind: str, values) -> dict:
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise AssemblyError("%s must map ids to values." % kind)
    out = {}
    for key, val in values.items():
        if kind == "patterns":
            if store.get_pattern(d, key) is None:
                raise AssemblyError("There is no pattern %s." % key)
            out[key] = bool(val)
            continue
        rec = store.find_component(d, key)
        if kind == "component_config":
            if rec["type"] == "embedded":
                raise AssemblyError("%s is an embedded part and has no configurations." % rec["label"])
            out[rec["id"]] = str(val or "")
        else:
            out[rec["id"]] = bool(val)
    return out


def merge(d, rec: dict, values: dict) -> None:
    base = ensure_default(d)
    base = copy.deepcopy(base)
    changed_base = False
    for kind in KEYS:
        for key, val in (values.get(kind) or {}).items():
            rec[kind][key] = val
            if key not in base[kind]:
                live = base_value(d, kind, key)
                if live is not None:
                    base[kind][key] = live
                    changed_base = True
    if changed_base:
        d.table_set(CONFIGS, base)


def create(d, name, description="", suppress=None, visible=None, component_config=None, patterns=None, copy_from=None) -> dict:
    n = check_name(d, name)
    rec = blank(n, False, str(description or ""))
    if copy_from:
        src = effective(d, copy_from)
        for kind in KEYS:
            rec[kind] = dict(src[kind])
    values = {"suppress": _clean(d, "suppress", suppress), "visible": _clean(d, "visible", visible), "component_config": _clean(d, "component_config", component_config), "patterns": _clean(d, "patterns", patterns)}
    ensure_default(d)
    merge(d, rec, values)
    d.table_set(CONFIGS, rec)
    return copy.deepcopy(rec)


def update(d, name, description=None, suppress=None, visible=None, component_config=None, patterns=None, new_name=None) -> dict:
    cur = copy.deepcopy(need(d, name))
    if new_name and new_name != cur["name"]:
        if cur.get("default"):
            raise AssemblyError("The Default configuration cannot be renamed.")
        n = check_name(d, new_name, cur["name"])
        d.table_remove(CONFIGS, cur["name"])
        cur["name"] = n
        if active_name(d).casefold() == str(name).casefold():
            h = store.header(d)
            h["active_config"] = n
            store.save_header(d, h)
    if description is not None:
        cur["description"] = str(description)
    values = {"suppress": _clean(d, "suppress", suppress), "visible": _clean(d, "visible", visible), "component_config": _clean(d, "component_config", component_config), "patterns": _clean(d, "patterns", patterns)}
    merge(d, cur, values)
    d.table_set(CONFIGS, cur)
    return copy.deepcopy(cur)


def effective(d, name: str) -> dict:
    rec = need(d, name)
    base = ensure_default(d) if get(d, DEFAULT_CONFIG) is None else get(d, DEFAULT_CONFIG)
    out = {k: dict(base[k]) for k in KEYS}
    if not rec.get("default"):
        for k in KEYS:
            out[k].update(rec[k])
    return out


def overlay(d, name: str) -> dict | None:
    if not name or get(d, name) is None:
        return None
    return effective(d, name)


def delete(d, name: str) -> dict:
    rec = need(d, name)
    if rec.get("default"):
        raise AssemblyError("The Default configuration cannot be deleted.")
    warnings = []
    if active_name(d).casefold() == rec["name"].casefold():
        warnings = activate(d, DEFAULT_CONFIG)["warnings"]
    d.table_remove(CONFIGS, rec["name"])
    return {"removed": rec["name"], "warnings": warnings}


def activate(d, name: str) -> dict:
    rec = need(d, name)
    eff = effective(d, rec["name"])
    warnings, applied = [], {"suppress": [], "visible": [], "component_config": [], "patterns": []}
    for cid, val in eff["suppress"].items():
        comp = store.get(d, cid)
        if comp is None:
            warnings.append("Component %s is gone; skipped." % cid)
        elif bool(comp.get("suppressed")) != bool(val):
            d.modify_record(store.COMPONENTS, cid)["suppressed"] = bool(val)
            applied["suppress"].append(cid)
    for cid, val in eff["visible"].items():
        comp = store.get(d, cid)
        if comp is None:
            warnings.append("Component %s is gone; skipped." % cid)
        elif bool(comp.get("visible", True)) != bool(val):
            d.modify_record(store.COMPONENTS, cid)["visible"] = bool(val)
            applied["visible"].append(cid)
    for cid, val in eff["component_config"].items():
        comp = store.get(d, cid)
        if comp is None:
            warnings.append("Component %s is gone; skipped." % cid)
        elif str(comp.get("config") or "") != str(val):
            d.modify_record(store.COMPONENTS, cid)["config"] = str(val)
            applied["component_config"].append(cid)
    for pid, val in eff["patterns"].items():
        pat = store.get_pattern(d, pid)
        if pat is None:
            warnings.append("Pattern %s is gone; skipped." % pid)
        elif bool(pat.get("suppressed")) != bool(val):
            d.modify_record(store.PATTERNS, pid)["suppressed"] = bool(val)
            applied["patterns"].append(pid)
    h = store.header(d)
    h["active_config"] = rec["name"]
    store.save_header(d, h)
    return {"active": rec["name"], "applied": applied, "warnings": warnings}


def note_change(d, kind: str, key: str, value, old=None) -> None:
    if not len(d.tables[CONFIGS]):
        return
    name = active_name(d)
    rec = get(d, name)
    if rec is None:
        return
    base = get(d, DEFAULT_CONFIG)
    if base is not None and key not in base[kind] and old is not None and not rec.get("default"):
        nb = copy.deepcopy(base)
        nb[kind][key] = old
        d.table_set(CONFIGS, nb)
    cur = copy.deepcopy(rec)
    cur[kind][key] = value
    d.table_set(CONFIGS, cur)


def listing(d) -> dict:
    return {"active": active_name(d), "configs": [copy.deepcopy(r) for r in configs(d)]}
