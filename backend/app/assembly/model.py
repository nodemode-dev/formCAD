import copy
import os
from datetime import datetime, timezone

import numpy as np

from app.assembly import cfg, parts, patterns, refs, store, walk, xform
from app.assembly import props as P
from app.assembly.store import AssemblyError
from app.doc.model import SPACE_MODEL
from app.param.units import mm_per_unit

REMOVE_HOOKS: list = []
MAX_NOTE = 2000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def host_real(doc) -> str:
    return os.path.realpath(doc.path) if getattr(doc, "path", "") else ""


def _guard(doc) -> dict:
    d = doc.drawing
    if getattr(doc, "kind", "assembly") not in ("assembly",):
        raise AssemblyError("This document is a %s; components are added to an assembly. Make a new assembly first." % doc.kind)
    return store.ensure(d)


def reaches(target: str, lp, seen=None, depth=0) -> bool:
    if depth > walk.MAX_DEPTH:
        return True
    seen = seen or set()
    if lp.path in seen:
        return False
    seen = seen | {lp.path}
    head = store.header(lp.drawing)
    for rec in store.components(lp.drawing):
        if rec["type"] != "assembly":
            continue
        real, _by, _log = refs.search(lp.path, rec.get("ref") or {}, head)
        if not real:
            continue
        if real == target:
            return True
        try:
            sub = parts.load(real)
        except parts.PartLoadError:
            continue
        if sub.is_assembly and reaches(target, sub, seen, depth + 1):
            return True
    return False


def check_cycle(doc, lp) -> None:
    me = host_real(doc)
    if not me:
        return
    if lp.path == me:
        raise AssemblyError("An assembly cannot contain itself.")
    if lp.is_assembly and reaches(me, lp):
        raise AssemblyError("%s already contains this assembly, so inserting it would make a loop." % os.path.basename(lp.path))


def _checked_file(path) -> str:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw:
        raise AssemblyError("Give the part or assembly file.")
    if "\x00" in raw:
        raise AssemblyError("That file name is not valid.")
    if os.path.splitext(raw)[1].lower() != refs.EXT:
        raise AssemblyError("Components come from %s files." % refs.EXT)
    real = os.path.realpath(raw)
    if not os.path.isfile(real):
        raise AssemblyError("The file %s is not there." % raw)
    return real


def _load(real: str):
    try:
        return parts.load(real)
    except parts.PartLoadError as err:
        raise AssemblyError("%s cannot be used: %s" % (os.path.basename(real), err))


def _check_config(lp, name: str) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    if lp.is_assembly:
        if cfg.get(lp.drawing, n) is None:
            raise AssemblyError("%s has no configuration called %s." % (os.path.basename(lp.path), n))
    elif n not in lp.configs:
        raise AssemblyError("%s has no configuration called %s." % (os.path.basename(lp.path), n))
    return n


def _fill_from(doc, rec: dict, lp, real: str, relative: bool) -> None:
    d = doc.drawing
    head = store.header(d)
    pin = (rec.get("ref") or {}).get("vault")
    rec["ref"] = {"path": refs.stored_path(real, doc.path, relative), "abs": real}
    if pin:
        rec["ref"]["vault"] = pin
    rec["sig"] = copy.deepcopy(lp.sig)
    if rec["type"] == "part":
        src = lp
        if rec.get("config") and rec["config"] in lp.configs and rec["config"] != lp.active_config:
            from app.assembly import variants

            try:
                src = variants.variant(lp, rec["config"])
            except variants.VariantError as err:
                raise AssemblyError("The configuration %s could not be built: %s" % (rec["config"], err))
        cache = parts.cache_record(d, src, bool(head.get("embed_cache", True)))
        cache["configs"] = list(lp.configs)
        cache["active_config"] = lp.active_config
        cache["taken"] = now()
        rec["cache"] = cache
    else:
        rec["cache"] = {"bodies": [], "props": copy.deepcopy(lp.props), "configs": [], "active_config": "", "mmu": lp.mm_per_unit, "taken": now()}
    rec["search"] = {"found_by": "", "resolved": real, "log": [], "order": refs.describe_order(head), "at": now()}


def insert(doc, path, label=None, transform=None, config="", relative=True, fixed=None, visible=True) -> dict:
    h = _guard(doc)
    d = doc.drawing
    if len(store.components(d)) >= store.MAX_COMPONENTS:
        raise AssemblyError("An assembly holds at most %d components." % store.MAX_COMPONENTS)
    real = _checked_file(path)
    lp = _load(real)
    check_cycle(doc, lp)
    m = xform.as_matrix(transform)
    cid, n = store.new_id(h)
    rec = {
        "name": cid, "id": cid, "n": n, "label": "", "type": "assembly" if lp.is_assembly else "part", "ref": {}, "embedded": None,
        "transform": xform.to_list(m), "visible": bool(visible), "suppressed": False, "fixed": bool(fixed) if fixed is not None else not store.components(d), "config": _check_config(lp, config), "props": {}, "sig": {}, "cache": {},
        "search": {}, "note": "",
    }
    _fill_from(doc, rec, lp, real, relative)
    rec["label"] = store.unique_label(d, store.clean_label(label, refs.stem(real)))
    store.save_header(d, h)
    store.put(d, rec)
    return copy.deepcopy(rec)


def remove(doc, cid: str) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    removed = {"component": rec["id"], "patterns": [], "bodies": 0}
    for fn in list(REMOVE_HOOKS):
        fn(doc, rec["id"])
    for p in store.patterns(d):
        if p["seed"] == rec["id"] or (p["kind"] == "feature" and p["params"].get("target") == rec["id"]):
            store.drop_pattern(d, p["id"])
            removed["patterns"].append(p["id"])
    for c in store.configs(d):
        cur = copy.deepcopy(c)
        dirty = False
        for kind in ("suppress", "visible", "component_config"):
            if rec["id"] in cur[kind]:
                cur[kind].pop(rec["id"])
                dirty = True
        for pid in removed["patterns"]:
            if pid in cur["patterns"]:
                cur["patterns"].pop(pid)
                dirty = True
        if dirty:
            d.table_set(store.CONFIGS, cur)
    if rec["type"] == "embedded":
        space = (rec.get("embedded") or {}).get("space")
        for hh in list(d.spaces.get(space, [])):
            d.erase_entity(hh)
            removed["bodies"] += 1
    store.drop(d, rec["id"])
    return removed


def set_transform(doc, cid: str, matrix, relative: bool = False, force: bool = False) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    if rec.get("fixed") and not force:
        raise AssemblyError("%s is fixed in place; unfix it first or move it with force." % rec["label"])
    m = xform.as_matrix(matrix)
    if relative:
        m = xform.check(m @ xform.as_matrix(rec["transform"]))
    d.modify_record(store.COMPONENTS, rec["id"])["transform"] = xform.to_list(m)
    return {"id": rec["id"], "transform": xform.to_list(m)}


def set_flags(doc, cid: str, visible=None, suppressed=None, fixed=None) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    live = d.modify_record(store.COMPONENTS, rec["id"])
    if visible is not None and bool(live.get("visible", True)) != bool(visible):
        old = bool(live.get("visible", True))
        live["visible"] = bool(visible)
        cfg.note_change(d, "visible", rec["id"], bool(visible), old)
    if suppressed is not None and bool(live.get("suppressed")) != bool(suppressed):
        old = bool(live.get("suppressed"))
        live["suppressed"] = bool(suppressed)
        cfg.note_change(d, "suppress", rec["id"], bool(suppressed), old)
    if fixed is not None:
        live["fixed"] = bool(fixed)
    return {"id": rec["id"], "visible": live.get("visible", True), "suppressed": live["suppressed"], "fixed": live["fixed"]}


def rename(doc, cid: str, label: str) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    n = store.clean_label(label, "")
    if not n:
        raise AssemblyError("A component needs a name.")
    if any(r["label"].casefold() == n.casefold() and r["id"] != rec["id"] for r in store.components(d)):
        raise AssemblyError("There is already a component called %s." % n)
    d.modify_record(store.COMPONENTS, rec["id"])["label"] = n
    return {"id": rec["id"], "label": n}


def set_note(doc, cid: str, text: str) -> None:
    d = doc.drawing
    rec = store.need(d, cid)
    d.modify_record(store.COMPONENTS, rec["id"])["note"] = str(text or "")[:MAX_NOTE]


def set_props(doc, cid: str, values: dict, remove=()) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    cur = dict(rec.get("props") or {})
    for k, v in (values or {}).items():
        cur[P.key_of(k)] = P.clean_value(v)
    for k in remove or ():
        cur.pop(P.key_of(k), None)
    if len(cur) > P.MAX_KEYS:
        raise AssemblyError("A component holds at most %d properties." % P.MAX_KEYS)
    d.modify_record(store.COMPONENTS, rec["id"])["props"] = cur
    return cur


def set_config(doc, cid: str, name: str) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    if rec["type"] == "embedded":
        raise AssemblyError("%s is an embedded part and has no configurations." % rec["label"])
    n = str(name or "").strip()
    if n:
        st, lp = walk.resolve(d, doc.path, rec)
        if lp is not None and getattr(lp, "source", "") == "file":
            _check_config(lp, n)
        elif rec["type"] == "part" and n not in (rec.get("cache") or {}).get("configs", []):
            raise AssemblyError("%s cannot be checked while its file is missing, and the copy kept here does not list the configuration %s." % (rec["label"], n))
    old = str(rec.get("config") or "")
    live = d.modify_record(store.COMPONENTS, rec["id"])
    live["config"] = n
    cfg.note_change(d, "component_config", rec["id"], n, old)
    if rec["type"] == "part" and lp_ok(d, doc, live):
        st, lp = walk.resolve(d, doc.path, live)
        if lp is not None and lp.source == "file" and st["status"] == "loaded":
            tmp = copy.deepcopy(live)
            _fill_from(doc, tmp, lp, st["resolved"], True)
            live["cache"] = tmp["cache"]
    return {"id": rec["id"], "config": n}


def lp_ok(d, doc, rec) -> bool:
    return bool(store.header(d).get("embed_cache", True))


def reload(doc, cid: str, folders=(), deep: bool = False, relative: bool = True) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    if rec["type"] == "embedded":
        raise AssemblyError("%s is stored in this file, so there is nothing to reload." % rec["label"])
    head = store.header(d)
    real, by, log = refs.search(doc.path, rec.get("ref") or {}, head, folders, deep)
    if not real:
        live = d.modify_record(store.COMPONENTS, rec["id"])
        live["search"] = {"found_by": "", "resolved": "", "log": log, "order": refs.describe_order(head), "at": now()}
        raise AssemblyError("The file for %s was not found (searched %d places). Use Find File, or Replace to choose another file." % (rec["label"], len(log)))
    parts.forget(real)
    lp = _load(real)
    check_cycle(doc, lp)
    if (rec["type"] == "assembly") != lp.is_assembly:
        raise AssemblyError("The file is %s, but this component is %s." % ("an assembly" if lp.is_assembly else "a part", "an assembly" if rec["type"] == "assembly" else "a part"))
    live = d.modify_record(store.COMPONENTS, rec["id"])
    before = dict(live.get("sig") or {})
    tmp = copy.deepcopy(live)
    _fill_from(doc, tmp, lp, real, relative)
    for k in ("ref", "sig", "cache"):
        live[k] = tmp[k]
    live["search"] = {"found_by": by, "resolved": real, "log": log, "order": refs.describe_order(head), "at": now()}
    warnings = []
    if live.get("config"):
        try:
            _check_config(lp, live["config"])
        except AssemblyError:
            warnings.append("The configuration %s no longer exists in the file; the component fell back to the default." % live["config"])
            live["config"] = ""
    for p in store.patterns(d):
        if p["kind"] == "feature" and p["params"].get("target") == rec["id"]:
            try:
                sites = patterns.feature_sites(lp, p["params"]["feature"])
                cur = copy.deepcopy(p)
                cur["params"]["sites"] = sites
                if cur["params"]["ref_site"] >= len(sites):
                    cur["params"]["ref_site"] = 0
                d.table_set(store.PATTERNS, cur)
            except Exception as err:
                warnings.append("Pattern %s kept its earlier sites: %s" % (p["id"], err))
    return {"id": rec["id"], "found_by": by, "resolved": real, "changed": not refs.same_sig(before, lp.sig), "warnings": warnings}


def find(doc, cid: str, folders=(), deep: bool = False, relink: bool = True, relative: bool = True) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    if rec["type"] == "embedded":
        raise AssemblyError("%s is stored in this file." % rec["label"])
    head = store.header(d)
    real, by, log = refs.search(doc.path, rec.get("ref") or {}, head, folders, deep)
    live = d.modify_record(store.COMPONENTS, rec["id"])
    live["search"] = {"found_by": by, "resolved": real, "log": log, "order": refs.describe_order(head) + (["deep"] if deep and "deep" not in refs.describe_order(head) else []), "at": now()}
    if real and relink:
        pin = (live.get("ref") or {}).get("vault")
        live["ref"] = {"path": refs.stored_path(real, doc.path, relative), "abs": real}
        if pin:
            live["ref"]["vault"] = pin
    return {"id": rec["id"], "found": bool(real), "resolved": real, "found_by": by, "order": live["search"]["order"], "log": log}


def replace(doc, cid: str, path, relative: bool = True) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.need(d, cid)
    if rec["type"] == "embedded":
        raise AssemblyError("An embedded part has no file to replace.")
    real = _checked_file(path)
    lp = _load(real)
    check_cycle(doc, lp)
    if (rec["type"] == "assembly") != lp.is_assembly:
        raise AssemblyError("Replace a part with a part and an assembly with an assembly.")
    live = d.modify_record(store.COMPONENTS, rec["id"])
    tmp = copy.deepcopy(live)
    _fill_from(doc, tmp, lp, real, relative)
    tmp["ref"].pop("vault", None)
    for k in ("ref", "sig", "cache", "search"):
        live[k] = tmp[k]
    warnings = []
    if live.get("config"):
        try:
            _check_config(lp, live["config"])
        except AssemblyError:
            warnings.append("The new file has no configuration %s; the component uses its default." % live["config"])
            live["config"] = ""
    return {"id": rec["id"], "resolved": real, "warnings": warnings}


def embed(doc, handles, label=None, fixed=None) -> dict:
    h = _guard(doc)
    d = doc.drawing
    hs = []
    for v in handles or []:
        try:
            hh = int(v)
        except (TypeError, ValueError):
            raise AssemblyError("Handles are whole numbers.")
        e = d.ents.get(hh)
        if e is None or e.kind != "solidbody" or e.owner != SPACE_MODEL:
            raise AssemblyError("Handle %s is not a solid body in the model." % v)
        hs.append(hh)
    if not hs:
        raise AssemblyError("Select at least one solid body.")
    cid, n = store.new_id(h)
    space = "part:%s" % cid
    d.ensure_space(space)
    first = d.ents[hs[0]]
    for hh in hs:
        ent = d.erase_entity(hh)
        ent.owner = space
        d.restore_entity(ent)
    rec = {
        "name": cid, "id": cid, "n": n, "label": store.unique_label(d, store.clean_label(label, first.name or "Part")), "type": "embedded", "ref": {}, "embedded": {"space": space},
        "transform": xform.to_list(xform.identity()), "visible": True, "suppressed": False, "fixed": bool(fixed) if fixed is not None else not store.components(d), "config": "", "props": {}, "sig": {}, "cache": {}, "search": {}, "note": "",
    }
    store.save_header(d, h)
    store.put(d, rec)
    return copy.deepcopy(rec)


def settings(doc, search_folders=None, search_order=None, embed_cache=None) -> dict:
    h = _guard(doc)
    if search_folders is not None:
        out = []
        for f in search_folders if isinstance(search_folders, (list, tuple)) else [search_folders]:
            s = os.path.expanduser(str(f).strip())
            if not s or "\x00" in s:
                continue
            if s not in out:
                out.append(s)
        if len(out) > 32:
            raise AssemblyError("At most 32 search folders.")
        h["search_folders"] = out
    if search_order is not None:
        h["search_order"] = refs.clean_order(search_order)
    if embed_cache is not None:
        h["embed_cache"] = bool(embed_cache)
    store.save_header(doc.drawing, h)
    return {"search_folders": h["search_folders"], "search_order": h["search_order"], "embed_cache": h["embed_cache"]}


def rebase(doc, relative: bool = True) -> dict:
    _guard(doc)
    d = doc.drawing
    head = store.header(d)
    changed, missing = [], []
    for rec in store.components(d):
        if rec["type"] == "embedded":
            continue
        real, _by, _log = refs.search(doc.path, rec.get("ref") or {}, head)
        if not real:
            missing.append(rec["id"])
            continue
        new = refs.stored_path(real, doc.path, relative)
        if new != (rec.get("ref") or {}).get("path") or real != (rec.get("ref") or {}).get("abs"):
            fresh = {"path": new, "abs": real}
            if (rec.get("ref") or {}).get("vault"):
                fresh["vault"] = rec["ref"]["vault"]
            d.modify_record(store.COMPONENTS, rec["id"])["ref"] = fresh
            changed.append(rec["id"])
    return {"changed": changed, "missing": missing}


def next_pattern_label(d, kind):
    return "%s pattern %d" % (kind.capitalize(), len(store.patterns(d)) + 1)


def add_pattern(doc, kind: str, seed: str, params: dict, label: str = "") -> dict:
    h = _guard(doc)
    d = doc.drawing
    kind = str(kind or "").lower()
    if kind not in patterns.KINDS:
        raise AssemblyError("A pattern is linear, circular or feature.")
    srec = store.find_component(d, seed)
    params = dict(params or {})
    if kind == "feature":
        target = store.find_component(d, params.get("target"))
        if target["type"] != "part":
            raise AssemblyError("A feature pattern follows a feature of a part component.")
        if target["id"] == srec["id"]:
            raise AssemblyError("The seed cannot be the part that drives the pattern.")
        st, lp = walk.resolve(d, doc.path, target)
        if lp is None or lp.source != "file":
            raise AssemblyError("The part %s is not available, so its feature cannot be read." % target["label"])
        sites = patterns.feature_sites(lp, params.get("feature"))
        params["target"] = target["id"]
        params["sites"] = sites
        mmu = mm_per_unit(d)
        tm = xform.as_matrix(target["transform"])
        sm = xform.as_matrix(srec["transform"])
        if "ref_site" not in params or params["ref_site"] is None:
            world = [tm[:3, :3] @ (np.asarray(s["c"]) / mmu) + tm[:3, 3] for s in sites]
            params["ref_site"] = int(np.argmin([np.linalg.norm(w - sm[:3, 3]) for w in world])) if world else 0
        if len(sites) < 2:
            raise AssemblyError("The feature has only %d site; a pattern needs at least two." % len(sites))
        fid = params.get("feature")
        params["feature"] = fid
    clean = patterns.clean_params(kind, params)
    pid = store.new_pattern_id(h)
    rec = patterns.new_record(pid, kind, srec["id"], clean, store.clean_label(label, next_pattern_label(d, kind)))
    store.save_header(d, h)
    store.put_pattern(d, rec)
    return copy.deepcopy(rec)


def edit_pattern(doc, pid: str, params=None, label=None, skip=None, suppressed=None) -> dict:
    _guard(doc)
    d = doc.drawing
    rec = store.get_pattern(d, pid)
    if rec is None:
        raise AssemblyError("There is no pattern %s." % pid)
    cur = copy.deepcopy(rec)
    if params:
        merged = dict(cur["params"])
        merged.update({k: v for k, v in params.items()})
        cur["params"] = patterns.clean_params(cur["kind"], merged)
    if label is not None:
        cur["label"] = store.clean_label(label, cur["label"])
    if skip is not None:
        cur["skip"] = sorted({int(i) for i in skip if int(i) > 0})
    if suppressed is not None and bool(cur.get("suppressed")) != bool(suppressed):
        cfg.note_change(d, "patterns", pid, bool(suppressed), bool(cur.get("suppressed")))
        cur["suppressed"] = bool(suppressed)
    d.table_set(store.PATTERNS, cur)
    return copy.deepcopy(cur)


def delete_pattern(doc, pid: str) -> dict:
    _guard(doc)
    d = doc.drawing
    if store.get_pattern(d, pid) is None:
        raise AssemblyError("There is no pattern %s." % pid)
    store.drop_pattern(d, pid)
    for c in store.configs(d):
        if pid in c["patterns"]:
            cur = copy.deepcopy(c)
            cur["patterns"].pop(pid)
            d.table_set(store.CONFIGS, cur)
    return {"removed": pid}
