import copy
import fnmatch
import json
import os
import re
from datetime import datetime, timezone

from app.doc import rename as R
from app.doc.tables import LINEWEIGHTS, LW_DEFAULT, new_layer
from app.sysvars import registry as sv

PROPS = ("on", "frozen", "locked", "plot", "color", "linetype", "lineweight", "transparency", "description", "plot_style", "new_vp_freeze")
BOOLS = ("on", "frozen", "locked", "plot", "new_vp_freeze")
PROTECTED = ("0", "defpoints")
BUILTIN_FILTERS = ("All", "All Used Layers")
FILTER_KEYS = ("name", "on", "frozen", "locked", "plot", "new_vp_freeze", "color", "linetype", "lineweight", "transparency", "description", "plot_style", "used")
MAX_STATES = 5000
MAX_FILTERS = 2000
MAX_PREV = 30
STATE_FORMAT = "formcad-layer-states"

USAGE_HOOKS: list = []
RENAME_HOOKS: list = []
DELETE_HOOKS: list = []
MERGE_HOOKS: list = []
VIEWPORT_INFO: list = []
VIEWPORT_SET: list = []


class LayerError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_xref(name: str) -> bool:
    return "|" in str(name)


def is_protected(name: str) -> bool:
    return str(name).casefold() in PROTECTED


def natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(name).casefold())]


def lw_text(v) -> str:
    if v == LW_DEFAULT:
        return "Default"
    if v == -2:
        return "ByBlock"
    if v == -1:
        return "ByLayer"
    return "%.2f mm" % (v / 100.0)


def session(doc) -> dict:
    s = getattr(doc, "layer_session", None)
    if s is None:
        s = {"prev": [], "iso": []}
        doc.layer_session = s
    return s


def get(d, name):
    rec = d.layer(str(name).strip())
    if rec is None:
        raise LayerError('Cannot find layer "%s".' % str(name).strip())
    return rec


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "yes", "on", "1", "y"):
        return True
    if s in ("false", "no", "off", "0", "n"):
        return False
    raise LayerError("Expected true or false.")


def norm_lineweight(value) -> int:
    if isinstance(value, str):
        s = value.strip().lower()
        if s == "default":
            return LW_DEFAULT
        if s in ("bylayer", "byblock"):
            raise LayerError("A layer cannot use a ByLayer or ByBlock lineweight.")
        m = re.fullmatch(r"(\d*\.?\d+)\s*(mm)?", s)
        if not m:
            raise LayerError("Invalid lineweight.")
        value = float(m.group(1)) * 100.0 if m.group(2) else float(m.group(1))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LayerError("Invalid lineweight.")
    if value == LW_DEFAULT:
        return LW_DEFAULT
    if value < 0:
        raise LayerError("A layer cannot use a ByLayer or ByBlock lineweight.")
    if value > 211 + 50:
        raise LayerError("Lineweight is limited to 2.11 mm.")
    return min(LINEWEIGHTS, key=lambda x: abs(x - float(value)))


def norm_prop(d, prop: str, value):
    if prop in BOOLS:
        return as_bool(value)
    if prop == "color":
        try:
            c = sv.parse_color(value)
        except sv.SysvarError:
            raise LayerError("Invalid color.")
        if c in (0, 256):
            raise LayerError("A layer color cannot be ByLayer or ByBlock.")
        return c
    if prop == "linetype":
        lt = d.tables["linetypes"].get(str(value).strip())
        if lt is None or lt["name"].casefold() in ("bylayer", "byblock"):
            raise LayerError('Linetype "%s" is not loaded. Load it with the LINETYPE command.' % str(value).strip())
        return lt["name"]
    if prop == "lineweight":
        return norm_lineweight(value)
    if prop == "transparency":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise LayerError("Transparency must be a whole number from 0 to 90.")
        try:
            t = float(value)
        except ValueError:
            raise LayerError("Transparency must be a whole number from 0 to 90.")
        if t != int(t) or not 0 <= t <= 90:
            raise LayerError("Transparency must be a whole number from 0 to 90.")
        return int(t)
    if prop in ("description", "plot_style"):
        s = str(value)
        if len(s) > 1000:
            raise LayerError("The text is too long.")
        return s
    raise LayerError("Unknown layer property %s." % prop)


def clean_props(d, props: dict) -> dict:
    out = {}
    props = dict(props or {})
    if "lineweight_mm" in props:
        props["lineweight"] = norm_lineweight("%s mm" % props.pop("lineweight_mm"))
    if "newVpFreeze" in props:
        props["new_vp_freeze"] = props.pop("newVpFreeze")
    if "plotStyle" in props:
        props["plot_style"] = props.pop("plotStyle")
    for k, v in props.items():
        if k in ("name", "current", "make"):
            continue
        out[k] = norm_prop(d, k, v)
    return out


def snapshot(d, props=PROPS) -> list:
    out = []
    for rec in d.tables["layers"].values():
        row = {"name": rec["name"]}
        for p in props:
            if p in rec:
                row[p] = copy.deepcopy(rec[p])
        out.append(row)
    return out


def snap_layers(d) -> dict:
    return {"layers": snapshot(d), "current": d.current_layer()}


def push_prev(doc) -> None:
    ses = session(doc)
    snap = snap_layers(doc.drawing)
    if ses["prev"] and ses["prev"][-1] == snap:
        return
    ses["prev"].append(snap)
    del ses["prev"][:-MAX_PREV]


def _apply_snapshot(d, snap: dict, props=PROPS, create: bool = False) -> int:
    n = 0
    for row in snap["layers"]:
        rec = d.layer(row["name"])
        if rec is None:
            if not create:
                continue
            fresh = new_layer(row["name"])
            for p in props:
                if p in row:
                    fresh[p] = copy.deepcopy(row[p])
            d.table_set("layers", fresh)
            n += 1
            continue
        diff = {p: row[p] for p in props if p in row and rec.get(p) != row[p]}
        if diff:
            target = d.modify_record("layers", rec["name"])
            target.update(copy.deepcopy(diff))
            n += 1
    return n


def restore_prev(doc) -> int:
    d = doc.drawing
    ses = session(doc)
    cur = snap_layers(d)
    while ses["prev"]:
        snap = ses["prev"].pop()
        if snap == cur:
            continue
        n = _apply_snapshot(d, snap)
        want = snap["current"]
        if d.layer(want) is not None and d.current_layer().casefold() != want.casefold():
            d.set_header("CLAYER", d.layer(want)["name"])
        return n + 1
    raise LayerError("No previous layer state.")


def prune_noop(doc) -> None:
    tx = getattr(doc, "_tx", None)
    if tx is None:
        return
    d = doc.drawing
    for key in [k for k in tx.before if k[0] in ("t", "h")]:
        if d.read_key(key) == tx.before[key]:
            del tx.before[key]


def set_current(d, name: str) -> str:
    rec = get(d, name)
    if rec["frozen"]:
        raise LayerError('Layer "%s" is frozen and cannot be made current.' % rec["name"])
    if is_xref(rec["name"]):
        raise LayerError('Layer "%s" belongs to an external reference and cannot be made current.' % rec["name"])
    if d.current_layer().casefold() != rec["name"].casefold():
        d.set_header("CLAYER", rec["name"])
    return rec["name"]


def next_layer_name(d, base: str = "Layer") -> str:
    i = 1
    while d.layer("%s%d" % (base, i)) is not None:
        i += 1
    return "%s%d" % (base, i)


def create_layer(d, name: str = "", props: dict | None = None) -> dict:
    name = str(name or "").strip()
    if not name:
        name = next_layer_name(d)
    if not R.valid_name(name):
        raise LayerError('"%s" is not a valid layer name.' % name)
    if d.layer(name) is not None:
        raise LayerError('Layer "%s" already exists.' % name)
    clean = clean_props(d, props or {})
    rec = new_layer(name)
    rec.update(clean)
    d.table_set("layers", rec)
    return d.layer(name)


def set_props(d, names, props: dict) -> dict:
    clean = clean_props(d, props)
    cur = d.current_layer().casefold()
    recs = [get(d, n) for n in names]
    changed, skipped = [], []
    for rec in recs:
        c = dict(clean)
        if c.get("frozen") is True and rec["name"].casefold() == cur:
            skipped.append({"name": rec["name"], "prop": "frozen", "reason": 'Layer "%s" is the current layer and cannot be frozen.' % rec["name"]})
            c.pop("frozen")
        diff = {k: v for k, v in c.items() if rec.get(k) != v}
        if diff:
            d.modify_record("layers", rec["name"]).update(diff)
            changed.append(rec["name"])
    return {"changed": changed, "skipped": skipped}


def rename_layer(d, old: str, new: str) -> dict:
    rec = get(d, old)
    old = rec["name"]
    if is_protected(old):
        raise LayerError('Layer "%s" cannot be renamed.' % old)
    if is_xref(old):
        raise LayerError('Layer "%s" belongs to an external reference and cannot be renamed.' % old)
    try:
        info = R.rename(d, "layer", old, new)
    except R.RenameError as err:
        raise LayerError(str(err))
    return {"old": old, "new": info["new"], "updated": info["updated"]}


def after_rename(d, old: str, final: str) -> int:
    n = 0
    for f in list(d.tables["layerfilters"].values()):
        if f.get("kind") == "group" and any(m.casefold() == old.casefold() for m in f.get("layers", [])):
            r = d.modify_record("layerfilters", f["name"])
            r["layers"] = [final if m.casefold() == old.casefold() else m for m in r["layers"]]
            n += 1
    for st in list(d.tables["layerstates"].values()):
        if any(row["name"].casefold() == old.casefold() for row in st.get("layers", [])) or str(st.get("current", "")).casefold() == old.casefold():
            r = d.modify_record("layerstates", st["name"])
            for row in r["layers"]:
                if row["name"].casefold() == old.casefold():
                    row["name"] = final
            if str(r.get("current", "")).casefold() == old.casefold():
                r["current"] = final
            n += 1
    for fn in RENAME_HOOKS:
        n += int(fn(d, old, final) or 0)
    return n


def usage(d) -> dict:
    out = {}
    for e in d.ents.values():
        key = (e.layer or "0").casefold()
        row = out.get(key)
        if row is None:
            row = out[key] = {"objects": 0, "model": 0, "layouts": 0, "blocks": 0, "refs": 0}
        row["objects"] += 1
        owner = e.owner
        if owner == "model":
            row["model"] += 1
        elif owner.startswith("layout:"):
            row["layouts"] += 1
        else:
            row["blocks"] += 1
    for fn in USAGE_HOOKS:
        for key, n in (fn(d) or {}).items():
            k = str(key).casefold()
            row = out.get(k)
            if row is None:
                row = out[k] = {"objects": 0, "model": 0, "layouts": 0, "blocks": 0, "refs": 0}
            row["refs"] += int(n)
            row["objects"] += int(n)
    return out


def used_count(use: dict, name: str) -> int:
    row = use.get(str(name).casefold())
    return row["objects"] if row else 0


def name_matches(pattern: str, name: str, anywhere: bool = True) -> bool:
    pat = str(pattern)
    if not pat:
        return True
    if "*" in pat or "?" in pat:
        rx = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pat)
        return (re.search(rx, name, re.I) if anywhere else re.fullmatch(rx, name, re.I)) is not None
    return pat.casefold() in name.casefold() if anywhere else pat.casefold() == name.casefold()


def match_names(d, spec: str) -> list:
    out = []
    for raw in str(spec).split(","):
        nm = raw.strip()
        if not nm:
            continue
        if "*" in nm or "?" in nm:
            for rec in d.tables["layers"].values():
                if fnmatch.fnmatchcase(rec["name"].casefold(), nm.casefold()) and rec["name"] not in out:
                    out.append(rec["name"])
        else:
            rec = d.layer(nm)
            if rec is not None and rec["name"] not in out:
                out.append(rec["name"])
    return out


def delete_check(d, name: str, use: dict, with_objects: bool = False) -> str:
    rec = d.layer(name)
    if rec is None:
        return 'Cannot find layer "%s".' % name
    if is_protected(rec["name"]):
        return 'Layer "%s" cannot be deleted.' % rec["name"]
    if is_xref(rec["name"]):
        return 'Layer "%s" belongs to an external reference and cannot be deleted.' % rec["name"]
    if rec["name"].casefold() == d.current_layer().casefold():
        return 'Layer "%s" is the current layer and cannot be deleted.' % rec["name"]
    if not with_objects and used_count(use, rec["name"]):
        return 'Layer "%s" is in use (%d objects or references) and cannot be deleted.' % (rec["name"], used_count(use, rec["name"]))
    return ""


def _drop_layer_refs(d, name: str) -> None:
    for f in list(d.tables["layerfilters"].values()):
        if f.get("kind") == "group" and any(m.casefold() == name.casefold() for m in f.get("layers", [])):
            r = d.modify_record("layerfilters", f["name"])
            r["layers"] = [m for m in r["layers"] if m.casefold() != name.casefold()]
    for fn in DELETE_HOOKS:
        fn(d, name)


def delete_layers(d, names, with_objects: bool = False) -> dict:
    use = usage(d)
    deleted, refused, erased = [], [], 0
    for nm in names:
        why = delete_check(d, nm, use, with_objects)
        if why:
            refused.append({"name": str(nm), "reason": why})
    if refused and with_objects:
        raise LayerError(refused[0]["reason"])
    for nm in names:
        if any(r["name"] == str(nm) for r in refused):
            continue
        rec = d.layer(nm)
        key = rec["name"].casefold()
        if with_objects:
            for h in [h for h, e in d.ents.items() if (e.layer or "0").casefold() == key]:
                if d.erase_entity(h) is not None:
                    erased += 1
        _drop_layer_refs(d, rec["name"])
        d.table_remove("layers", rec["name"])
        deleted.append(rec["name"])
    return {"deleted": deleted, "refused": refused, "objects": erased}


def merge_layers(d, sources, target: str) -> dict:
    tgt = get(d, target)
    srcs = []
    for s in sources:
        rec = get(d, s)
        if rec["name"].casefold() == tgt["name"].casefold():
            raise LayerError("A layer cannot be merged into itself.")
        if is_protected(rec["name"]) or is_xref(rec["name"]):
            raise LayerError('Layer "%s" cannot be merged away.' % rec["name"])
        if rec["name"] not in srcs:
            srcs.append(rec["name"])
    if is_xref(tgt["name"]):
        raise LayerError('Layer "%s" belongs to an external reference and cannot be merged into.' % tgt["name"])
    if not srcs:
        raise LayerError("There is no layer to merge.")
    keys = {s.casefold() for s in srcs}
    moved = 0
    for h in [h for h, e in d.ents.items() if (e.layer or "0").casefold() in keys]:
        d.modify(h).layer = tgt["name"]
        moved += 1
    for s in srcs:
        for fn in MERGE_HOOKS:
            fn(d, s, tgt["name"])
        for f in list(d.tables["layerfilters"].values()):
            if f.get("kind") == "group" and any(m.casefold() == s.casefold() for m in f.get("layers", [])):
                r = d.modify_record("layerfilters", f["name"])
                members = [m for m in r["layers"] if m.casefold() != s.casefold()]
                if not any(m.casefold() == tgt["name"].casefold() for m in members):
                    members.append(tgt["name"])
                r["layers"] = members
        _drop_layer_refs(d, s)
        d.table_remove("layers", s)
    if d.current_layer().casefold() in keys or str(d.header.get("CLAYER", "0")).casefold() in keys:
        d.set_header("CLAYER", tgt["name"])
    return {"merged": srcs, "target": tgt["name"], "moved": moved}


def isolate(doc, names) -> list:
    d = doc.drawing
    keep = []
    for n in names:
        rec = get(d, n)
        if rec["name"] not in keep:
            keep.append(rec["name"])
    if not keep:
        raise LayerError("There is no layer to isolate.")
    push_prev(doc)
    ses = session(doc)
    ses["iso"].append({"on": {r["name"]: r["on"] for r in d.tables["layers"].values()}, "current": d.current_layer()})
    del ses["iso"][:-MAX_PREV]
    ks = {k.casefold() for k in keep}
    for rec in d.tables["layers"].values():
        want = rec["name"].casefold() in ks
        if not want and rec["on"]:
            d.modify_record("layers", rec["name"])["on"] = False
    first = d.layer(keep[0])
    if first["on"] is False:
        d.modify_record("layers", first["name"])["on"] = True
    if not first["frozen"]:
        set_current(d, first["name"])
    return keep


def unisolate(doc) -> int:
    ses = session(doc)
    if not ses["iso"]:
        raise LayerError("No isolated layers.")
    d = doc.drawing
    push_prev(doc)
    snap = ses["iso"].pop()
    n = 0
    for name, on in snap["on"].items():
        rec = d.layer(name)
        if rec is not None and rec["on"] != on:
            d.modify_record("layers", rec["name"])["on"] = on
            n += 1
    cur = d.layer(snap["current"])
    if cur is not None and not cur["frozen"] and d.current_layer().casefold() != cur["name"].casefold():
        d.set_header("CLAYER", cur["name"])
    return n


def all_on(d) -> int:
    n = 0
    for rec in list(d.tables["layers"].values()):
        if not rec["on"]:
            d.modify_record("layers", rec["name"])["on"] = True
            n += 1
    return n


def thaw_all(d) -> int:
    n = 0
    for rec in list(d.tables["layers"].values()):
        if rec["frozen"]:
            d.modify_record("layers", rec["name"])["frozen"] = False
            n += 1
    return n


def layers_of(d, handles) -> list:
    out = []
    for h in handles:
        e = d.get(int(h))
        if e is not None:
            rec = d.layer(e.layer or "0")
            nm = rec["name"] if rec else (e.layer or "0")
            if nm not in out:
                out.append(nm)
    return out


def move_objects(d, handles, layer: str) -> dict:
    tgt = get(d, layer)
    moved, locked, same = 0, 0, 0
    for h in handles:
        e = d.get(int(h))
        if e is None:
            continue
        if d.layer_locked(e.layer):
            locked += 1
        elif (e.layer or "0").casefold() == tgt["name"].casefold():
            same += 1
        else:
            d.modify(int(h)).layer = tgt["name"]
            moved += 1
    return {"moved": moved, "locked": locked, "same": same, "layer": tgt["name"]}


def filter_match(d, f: dict, rec: dict, use: dict) -> bool:
    kind = f.get("kind")
    if kind == "group":
        return any(m.casefold() == rec["name"].casefold() for m in f.get("layers", []))
    ex = f.get("expr") or {}
    for k, want in ex.items():
        if want is None or want == "":
            continue
        if k == "name":
            if not name_matches(want, rec["name"], False):
                return False
        elif k in ("description", "plot_style", "linetype"):
            if not name_matches(want, str(rec.get(k, "")), False):
                return False
        elif k == "used":
            if (used_count(use, rec["name"]) > 0) != bool(want):
                return False
        elif k in BOOLS:
            if bool(rec.get(k)) != bool(want):
                return False
        elif k == "color":
            try:
                if rec["color"] != sv.parse_color(want):
                    return False
            except sv.SysvarError:
                return False
        elif k == "lineweight":
            try:
                if rec["lineweight"] != norm_lineweight(want):
                    return False
            except LayerError:
                return False
        elif k == "transparency":
            if int(rec.get("transparency", 0)) != int(want):
                return False
    return True


def filter_chain(d, name: str) -> list:
    chain, seen = [], set()
    cur = d.tables["layerfilters"].get(name)
    while cur is not None and cur["name"].casefold() not in seen:
        chain.append(cur)
        seen.add(cur["name"].casefold())
        cur = d.tables["layerfilters"].get(cur.get("parent", "")) if cur.get("parent") else None
    return chain


def filtered(d, name: str, use: dict | None = None) -> list:
    if not name or name.casefold() == "all":
        return [r["name"] for r in d.tables["layers"].values()]
    use = use if use is not None else usage(d)
    if name.casefold() == "all used layers":
        return [r["name"] for r in d.tables["layers"].values() if used_count(use, r["name"]) > 0]
    if d.tables["layerfilters"].get(name) is None:
        raise LayerError('Cannot find layer filter "%s".' % name)
    chain = filter_chain(d, name)
    return [r["name"] for r in d.tables["layers"].values() if all(filter_match(d, f, r, use) for f in chain)]


def filter_list(d, use: dict | None = None) -> list:
    use = use if use is not None else usage(d)
    out = [{"name": "All", "kind": "builtin", "parent": "", "count": len(d.tables["layers"])}, {"name": "All Used Layers", "kind": "builtin", "parent": "", "count": sum(1 for r in d.tables["layers"].values() if used_count(use, r["name"]) > 0)}]
    for f in d.tables["layerfilters"].values():
        chain = filter_chain(d, f["name"])
        n = sum(1 for r in d.tables["layers"].values() if all(filter_match(d, c, r, use) for c in chain))
        out.append({"name": f["name"], "kind": f["kind"], "parent": f.get("parent", ""), "expr": copy.deepcopy(f.get("expr") or {}), "layers": list(f.get("layers", [])), "count": n})
    return out


def set_filter(d, name: str, kind: str | None = None, expr: dict | None = None, layers=None, parent: str | None = None, add=None, remove=None) -> dict:
    name = str(name or "").strip()
    if not R.valid_name(name):
        raise LayerError('"%s" is not a valid filter name.' % name)
    if name.casefold() in (b.casefold() for b in BUILTIN_FILTERS):
        raise LayerError('"%s" is a built-in filter.' % name)
    old = d.tables["layerfilters"].get(name)
    if old is None and len(d.tables["layerfilters"]) >= MAX_FILTERS:
        raise LayerError("Too many layer filters.")
    kind = kind or (old["kind"] if old else "property")
    if kind not in ("property", "group"):
        raise LayerError("A filter is a property filter or a group filter.")
    par = str(parent).strip() if parent is not None else (old.get("parent", "") if old else "")
    if par:
        pf = d.tables["layerfilters"].get(par)
        if pf is None:
            raise LayerError('Cannot find layer filter "%s".' % par)
        if pf["name"].casefold() == name.casefold() or any(c["name"].casefold() == name.casefold() for c in filter_chain(d, pf["name"])):
            raise LayerError("A filter cannot be nested inside itself.")
        par = pf["name"]
    rec = copy.deepcopy(old) if old else {"name": name, "kind": kind, "parent": "", "expr": {}, "layers": []}
    rec["name"] = old["name"] if old else name
    rec["kind"] = kind
    rec["parent"] = par
    if expr is not None:
        clean = {}
        for k, v in dict(expr).items():
            if k not in FILTER_KEYS:
                raise LayerError("Unknown filter property %s." % k)
            if v is None or v == "":
                continue
            if k in BOOLS or k == "used":
                v = as_bool(v)
            elif k == "color":
                try:
                    v = sv.parse_color(v)
                except sv.SysvarError:
                    raise LayerError("Invalid color.")
            elif k == "lineweight":
                v = norm_lineweight(v)
            elif k == "transparency":
                v = norm_prop(d, "transparency", v)
            else:
                v = str(v)
            clean[k] = v
        rec["expr"] = clean
    members = list(rec.get("layers", []))
    if layers is not None:
        members = []
        for n in layers:
            members.append(get(d, n)["name"])
    for n in add or []:
        nm = get(d, n)["name"]
        if not any(m.casefold() == nm.casefold() for m in members):
            members.append(nm)
    for n in remove or []:
        members = [m for m in members if m.casefold() != str(n).casefold()]
    rec["layers"] = members if kind == "group" else []
    if kind == "group":
        rec["expr"] = {}
    d.table_set("layerfilters", rec)
    return rec


def delete_filter(d, name: str) -> list:
    f = d.tables["layerfilters"].get(name)
    if f is None:
        raise LayerError('Cannot find layer filter "%s".' % name)
    gone = [f["name"]]
    changed = True
    while changed:
        changed = False
        for g in d.tables["layerfilters"].values():
            if g["name"] not in gone and g.get("parent") and any(g["parent"].casefold() == x.casefold() for x in gone):
                gone.append(g["name"])
                changed = True
    for n in gone:
        d.table_remove("layerfilters", n)
    return gone


def rename_filter(d, old: str, new: str) -> dict:
    f = d.tables["layerfilters"].get(old)
    if f is None:
        raise LayerError('Cannot find layer filter "%s".' % old)
    new = str(new).strip()
    if not R.valid_name(new) or new.casefold() in (b.casefold() for b in BUILTIN_FILTERS):
        raise LayerError('"%s" is not a valid filter name.' % new)
    if d.tables["layerfilters"].get(new) is not None and new.casefold() != f["name"].casefold():
        raise LayerError('A layer filter named "%s" already exists.' % new)
    fresh = copy.deepcopy(f)
    oldname = f["name"]
    fresh["name"] = new
    d.table_remove("layerfilters", oldname)
    d.table_set("layerfilters", fresh)
    for g in list(d.tables["layerfilters"].values()):
        if g.get("parent", "").casefold() == oldname.casefold():
            d.modify_record("layerfilters", g["name"])["parent"] = new
    return fresh


def state_valid_name(name: str) -> bool:
    return R.valid_name(name) and not name.startswith("*")


def state_get(d, name: str) -> dict:
    st = d.tables["layerstates"].get(str(name).strip())
    if st is None:
        raise LayerError('Cannot find layer state "%s".' % str(name).strip())
    return st


def state_list(d) -> list:
    out = []
    for st in d.tables["layerstates"].values():
        if st["name"].startswith("*"):
            continue
        out.append({"name": st["name"], "description": st.get("description", ""), "layers": len(st.get("layers", [])), "current": st.get("current", ""), "created": st.get("created", "")})
    return sorted(out, key=lambda r: natural_key(r["name"]))


def save_state(d, name: str, description: str = "", overwrite: bool = False, internal: bool = False) -> dict:
    name = str(name or "").strip()
    if not internal and not state_valid_name(name):
        raise LayerError('"%s" is not a valid layer state name.' % name)
    old = d.tables["layerstates"].get(name)
    if old is not None and not overwrite:
        raise LayerError('Layer state "%s" already exists.' % old["name"])
    if old is None and len(d.tables["layerstates"]) >= MAX_STATES:
        raise LayerError("Too many layer states.")
    rec = {"name": old["name"] if old else name, "description": str(description or ""), "current": d.current_layer(), "created": old.get("created", now_iso()) if old else now_iso(), "layers": snapshot(d)}
    d.table_set("layerstates", rec)
    return rec


def restore_state(d, name: str, props=None, off_missing: bool = False, create_missing: bool = True, restore_current: bool = True) -> dict:
    st = state_get(d, name)
    use = [p for p in (props or PROPS)]
    for p in use:
        if p not in PROPS:
            raise LayerError("Unknown layer property %s." % p)
    notes, created, changed = [], [], 0
    names = set()
    for row in st["layers"]:
        names.add(row["name"].casefold())
        rec = d.layer(row["name"])
        want = {p: row[p] for p in use if p in row}
        if "linetype" in want and d.tables["linetypes"].get(want["linetype"]) is None:
            notes.append('Linetype "%s" of layer "%s" is not loaded; the layer keeps its linetype.' % (want["linetype"], row["name"]))
            want.pop("linetype")
        if rec is None:
            if not create_missing:
                continue
            fresh = new_layer(row["name"])
            fresh.update(copy.deepcopy(want))
            d.table_set("layers", fresh)
            created.append(row["name"])
            continue
        diff = {k: v for k, v in want.items() if rec.get(k) != v}
        if diff:
            d.modify_record("layers", rec["name"]).update(copy.deepcopy(diff))
            changed += 1
    if off_missing:
        for rec in list(d.tables["layers"].values()):
            if rec["name"].casefold() not in names and rec["on"] and rec["name"].casefold() != str(st.get("current", "")).casefold():
                d.modify_record("layers", rec["name"])["on"] = False
                changed += 1
    cur = d.layer(st.get("current", "")) if restore_current and st.get("current") else None
    if cur is not None and not cur["frozen"] and d.current_layer().casefold() != cur["name"].casefold():
        d.set_header("CLAYER", cur["name"])
    return {"name": st["name"], "changed": changed, "created": created, "notes": notes}


def edit_state(d, name: str, description=None, layers=None, add=None, remove=None, update=False, current=None, rename=None) -> dict:
    st = copy.deepcopy(state_get(d, name))
    oldname = st["name"]
    if description is not None:
        st["description"] = str(description)
    rows = {r["name"].casefold(): r for r in st["layers"]}
    if update:
        fresh = snapshot(d)
        st["layers"] = fresh
        st["current"] = d.current_layer()
        rows = {r["name"].casefold(): r for r in st["layers"]}
    for n in add or []:
        rec = get(d, n)
        if rec["name"].casefold() not in rows:
            row = snapshot_one(rec)
            st["layers"].append(row)
            rows[rec["name"].casefold()] = row
    for n in remove or []:
        key = str(n).casefold()
        if key not in rows:
            raise LayerError('Layer "%s" is not in the layer state.' % n)
        st["layers"] = [r for r in st["layers"] if r["name"].casefold() != key]
        rows.pop(key)
    for item in layers or []:
        nm = str(item.get("name", "")).strip()
        row = rows.get(nm.casefold())
        if row is None:
            raise LayerError('Layer "%s" is not in the layer state.' % nm)
        clean = clean_props(d, {k: v for k, v in item.items() if k != "name"})
        row.update(clean)
    if current is not None:
        if rows.get(str(current).casefold()) is None:
            raise LayerError('Layer "%s" is not in the layer state.' % current)
        st["current"] = rows[str(current).casefold()]["name"]
    if rename is not None and str(rename).strip().casefold() != oldname.casefold():
        new = str(rename).strip()
        if not state_valid_name(new):
            raise LayerError('"%s" is not a valid layer state name.' % new)
        if d.tables["layerstates"].get(new) is not None:
            raise LayerError('Layer state "%s" already exists.' % new)
        d.table_remove("layerstates", oldname)
        st["name"] = new
    d.table_set("layerstates", st)
    return st


def snapshot_one(rec: dict) -> dict:
    row = {"name": rec["name"]}
    for p in PROPS:
        if p in rec:
            row[p] = copy.deepcopy(rec[p])
    return row


def delete_states(d, spec) -> list:
    pats = [s.strip() for s in (spec if isinstance(spec, (list, tuple)) else str(spec).split(",")) if str(s).strip()]
    gone = []
    for st in list(d.tables["layerstates"].values()):
        if st["name"].startswith("*"):
            continue
        if any(name_matches(p, st["name"], False) for p in pats):
            gone.append(st["name"])
    if not gone:
        raise LayerError("No matching layer states found.")
    for n in gone:
        d.table_remove("layerstates", n)
    return gone


def export_states(d, names=None, path: str = "") -> dict:
    sel = []
    for st in d.tables["layerstates"].values():
        if st["name"].startswith("*"):
            continue
        if names and not any(str(n).casefold() == st["name"].casefold() for n in names):
            continue
        sel.append(copy.deepcopy(st))
    if names:
        for n in names:
            if not any(s["name"].casefold() == str(n).casefold() for s in sel):
                raise LayerError('Cannot find layer state "%s".' % n)
    if not sel:
        raise LayerError("There are no layer states to export.")
    data = {"format": STATE_FORMAT, "version": 1, "states": sel}
    if path:
        from app.doc import container

        from app.core import outputs

        try:
            target = outputs.checked(str(path), (".fcls",), ".fcls")
        except outputs.OutputRefused as err:
            raise LayerError(str(err))
        try:
            container.atomic_write(target, json.dumps(data, indent=1).encode("utf-8"))
        except OSError as err:
            raise LayerError("Cannot write the file: %s" % err)
        return {"path": target, "count": len(sel), "data": None}
    return {"path": "", "count": len(sel), "data": data}


def _read_states(data=None, path: str = "") -> list:
    if data is None:
        target = os.path.expanduser(str(path))
        if not os.path.isfile(target):
            raise LayerError("Cannot find the file.")
        if target.lower().endswith(".fcad"):
            from app.doc import container

            try:
                drawing, _ = container.load(target)
            except container.ContainerError as err:
                raise LayerError(err.message)
            return [copy.deepcopy(s) for s in drawing.tables["layerstates"].values()]
        try:
            with open(target, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            raise LayerError("The file is not a layer state file.")
    if not isinstance(data, dict) or data.get("format") != STATE_FORMAT or not isinstance(data.get("states"), list):
        raise LayerError("The file is not a layer state file.")
    return data["states"]


def import_states(d, data=None, path: str = "", names=None, overwrite: bool = False) -> dict:
    states = _read_states(data, path)
    added, skipped = [], []
    for raw in states:
        if not isinstance(raw, dict) or not isinstance(raw.get("layers"), list) or not state_valid_name(str(raw.get("name", ""))):
            continue
        if names and not any(str(n).casefold() == raw["name"].casefold() for n in names):
            continue
        if raw["name"].startswith("*"):
            continue
        rows = []
        for r in raw["layers"]:
            if isinstance(r, dict) and R.valid_name(str(r.get("name", ""))):
                row = {"name": str(r["name"])}
                for p in PROPS:
                    if p in r:
                        try:
                            row[p] = norm_prop_loose(p, r[p])
                        except LayerError:
                            pass
                rows.append(row)
        old = d.tables["layerstates"].get(raw["name"])
        if old is not None and not overwrite:
            skipped.append(raw["name"])
            continue
        rec = {"name": old["name"] if old else raw["name"], "description": str(raw.get("description", "")), "current": str(raw.get("current", "")), "created": now_iso(), "layers": rows}
        d.table_set("layerstates", rec)
        added.append(rec["name"])
    if names:
        for n in names:
            if not any(a.casefold() == str(n).casefold() for a in added + skipped):
                raise LayerError('Cannot find layer state "%s" in the file.' % n)
    if not added and not skipped:
        raise LayerError("There are no layer states to import.")
    return {"imported": added, "skipped": skipped}


def norm_prop_loose(prop: str, value):
    if prop in BOOLS:
        return as_bool(value)
    if prop == "color":
        c = sv.parse_color(value)
        if c in (0, 256):
            raise LayerError("Invalid color.")
        return c
    if prop == "lineweight":
        return norm_lineweight(value)
    if prop == "transparency":
        return max(0, min(90, int(value)))
    if prop == "linetype":
        return str(value)
    return str(value)


def describe(doc, filter: str = "", search: str = "", sort: str = "name", desc: bool = False, viewport=None) -> dict:
    d = doc.drawing
    use = usage(d)
    cur = d.current_layer()
    names = filtered(d, filter or "All", use)
    allowed = {n.casefold() for n in names}
    info = {}
    if viewport not in (None, "", 0):
        for fn in VIEWPORT_INFO:
            for key, extra in (fn(d, int(viewport)) or {}).items():
                info.setdefault(str(key).casefold(), {}).update(extra)
    rows = []
    for rec in d.tables["layers"].values():
        if rec["name"].casefold() not in allowed:
            continue
        if search and not name_matches(search, rec["name"], True):
            continue
        u = use.get(rec["name"].casefold()) or {"objects": 0, "model": 0, "layouts": 0, "blocks": 0, "refs": 0}
        row = {k: copy.deepcopy(rec[k]) for k in ("name", *PROPS) if k in rec}
        row.update({"current": rec["name"].casefold() == cur.casefold(), "objects": u["objects"], "model": u["model"], "layouts": u["layouts"], "blocks": u["blocks"], "refs": u["refs"], "used": u["objects"] > 0, "xref": is_xref(rec["name"]), "protected": is_protected(rec["name"]), "colorText": sv.color_text(rec["color"]), "lineweightText": lw_text(rec["lineweight"])})
        row.update(info.get(rec["name"].casefold(), {}))
        rows.append(row)
    keys = {"name": lambda r: natural_key(r["name"]), "objects": lambda r: (r["objects"], natural_key(r["name"])), "color": lambda r: (str(r["color"]), natural_key(r["name"])), "linetype": lambda r: (r["linetype"].casefold(), natural_key(r["name"])), "lineweight": lambda r: (r["lineweight"], natural_key(r["name"])), "transparency": lambda r: (r["transparency"], natural_key(r["name"])), "description": lambda r: (r["description"].casefold(), natural_key(r["name"]))}
    rows.sort(key=keys.get(sort, keys["name"]), reverse=bool(desc))
    return {"layers": rows, "total": len(d.tables["layers"]), "shown": len(rows), "current": cur, "filter": filter or "All", "filters": filter_list(d, use), "states": state_list(d), "viewport": viewport or None}


def apply_ops(doc, ops: list) -> dict:
    d = doc.drawing
    results, skipped = [], []
    push_prev(doc)
    for op in ops:
        kind = str(op.get("op", "")).lower()
        if kind == "new":
            rec = create_layer(d, op.get("name", ""), op.get("props"))
            if op.get("current"):
                set_current(d, rec["name"])
            results.append({"op": kind, "name": rec["name"]})
        elif kind == "set":
            names = op.get("names") or ([op["name"]] if op.get("name") else [])
            if not names:
                raise LayerError("Name the layers to change.")
            props = dict(op.get("props") or {})
            vp = op.get("viewport")
            vprops = op.get("vp") or props.pop("vp", None)
            if vp and vprops:
                if not VIEWPORT_SET:
                    raise LayerError("Viewport layer overrides are not available.")
                for n in names:
                    rec = get(d, n)
                    for fn in VIEWPORT_SET:
                        fn(d, int(vp), rec["name"], dict(vprops))
            r = set_props(d, names, props) if props else {"changed": [], "skipped": []}
            skipped.extend(r["skipped"])
            results.append({"op": kind, "changed": r["changed"]})
        elif kind == "rename":
            r = rename_layer(d, op.get("name", ""), op.get("to", ""))
            results.append({"op": kind, **r})
        elif kind == "delete":
            names = op.get("names") or ([op["name"]] if op.get("name") else [])
            r = delete_layers(d, [get(d, n)["name"] for n in names], bool(op.get("objects")))
            for x in r["refused"]:
                skipped.append({"name": x["name"], "prop": "delete", "reason": x["reason"]})
            results.append({"op": kind, "deleted": r["deleted"], "objects": r["objects"]})
        elif kind == "current":
            results.append({"op": kind, "name": set_current(d, op.get("name", ""))})
        elif kind == "merge":
            r = merge_layers(d, op.get("names") or [], op.get("target", ""))
            results.append({"op": kind, **r})
        elif kind == "isolate":
            results.append({"op": kind, "kept": isolate(doc, op.get("names") or [])})
        elif kind == "unisolate":
            results.append({"op": kind, "changed": unisolate(doc)})
        elif kind == "allon":
            results.append({"op": kind, "changed": all_on(d)})
        elif kind == "thawall":
            results.append({"op": kind, "changed": thaw_all(d)})
        elif kind == "previous":
            results.append({"op": kind, "changed": restore_prev(doc)})
        else:
            raise LayerError("Unknown layer operation %s." % (kind or "(none)"))
    prune_noop(doc)
    return {"results": results, "skipped": skipped}
