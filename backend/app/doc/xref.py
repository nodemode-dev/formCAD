import copy
import dataclasses
import os
import re

from app.doc import blocktools as BT
from app.doc import container
from app.doc.blocktools import EditError
from app.doc.entities import entity_from_dict
from app.doc.model import SPACE_MODEL, block_space

READERS: dict = {}
MAX_FILES = 1000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_OBJECTS = 4_000_000
MAX_DEPTH = BT.MAX_NEST
SYMBOL_TABLES = ("layers", "linetypes", "textstyles", "dimstyles", "blocks")
SPECIAL_LT = ("bylayer", "byblock", "continuous")
STATUS_TEXT = {"loaded": "Loaded", "unloaded": "Unloaded", "notfound": "Not Found", "unresolved": "Unresolved", "notloaded": "Not loaded", "unreferenced": "Unreferenced"}


class XrefError(EditError):
    pass


def register_reader(ext: str, fn) -> None:
    READERS[ext.lower()] = fn


class Budget:
    def __init__(self):
        self.files = 0
        self.total = 0
        self.objects = 0


def new_info(path: str, overlay: bool = False, typed: bool = False) -> dict:
    return {"path": path, "overlay": bool(overlay), "status": "notloaded", "reason": "", "resolved": "", "objects": 0, "unloaded": False, "typed": bool(typed)}


def is_xref(rec) -> bool:
    return bool(rec and isinstance(rec.get("xref"), dict))


def tops(d) -> list:
    return [r for r in d.tables["blocks"].values() if is_xref(r) and "|" not in r["name"]]


def _unc_host(p: str) -> str:
    q = p.replace("\\", "/")
    if q.startswith("//"):
        return q[2:].split("/", 1)[0].casefold()
    return ""


def _foreign_abs(s: str) -> bool:
    if os.name == "nt":
        return s.startswith("/") and not s.startswith("//")
    return bool(re.match(r"^[A-Za-z]:[\\/]", s))


def resolve(stored: str, host_path: str, typed: bool = False):
    s = str(stored or "").strip()
    if not s:
        return None, "unresolved", "no path stored"
    if not typed:
        if "://" in s:
            return None, "unresolved", "path leads away from this computer"
        unc = _unc_host(s)
        if unc and unc != _unc_host(host_path or ""):
            return None, "unresolved", "path leads to another computer"
        if _foreign_abs(s):
            return None, "unresolved", "absolute path from another operating system"
    elif _foreign_abs(s) and os.name != "nt":
        return None, "unresolved", "absolute path from another operating system"
    s2 = os.path.expanduser(s) if typed else s
    if os.name != "nt":
        s2 = s2.replace("\\", "/")
    hostdir = os.path.dirname(os.path.realpath(host_path)) if host_path else ""
    cands = []
    if os.path.isabs(s2):
        cands.append(s2)
    elif hostdir:
        cands.append(os.path.join(hostdir, s2))
    elif typed:
        cands.append(os.path.abspath(s2))
    else:
        return None, "notfound", "the host drawing has no folder yet, so the relative path cannot be followed"
    if hostdir:
        cands.append(os.path.join(hostdir, os.path.basename(s2)))
    for c in cands:
        if os.path.isfile(c):
            return os.path.realpath(c), "", ""
    return None, "notfound", "file not found"


def stored_path(resolved: str, host_path: str) -> str:
    if host_path:
        hostdir = os.path.dirname(os.path.realpath(host_path))
        rp = os.path.realpath(resolved)
        try:
            inside = os.path.commonpath([hostdir, rp]) == hostdir
        except ValueError:
            inside = False
        if inside:
            return os.path.relpath(rp, hostdir).replace(os.sep, "/")
    return os.path.realpath(resolved)


def read_drawing(path: str, budget: Budget):
    if budget.files >= MAX_FILES:
        raise XrefError("too many referenced files")
    try:
        size = os.path.getsize(path)
    except OSError as err:
        raise XrefError("cannot read: %s" % err)
    if size > MAX_FILE_BYTES:
        raise XrefError("file is larger than 512 MB")
    if budget.total + size > MAX_TOTAL_BYTES:
        raise XrefError("referenced files exceed 1 GB together")
    ext = os.path.splitext(path)[1].lower()
    try:
        from app.doc import blockio

        reader = READERS.get(ext) or blockio.READERS.get(ext)
        if reader is not None:
            src = reader(path)
        elif ext in (".fcad", ""):
            src, _man = container.load(path)
        else:
            raise XrefError("no reader for %s files is installed" % (ext or "this kind of"))
    except container.ContainerError as err:
        raise XrefError(err.message)
    budget.files += 1
    budget.total += size
    if budget.objects + len(src.ents) > MAX_OBJECTS:
        raise XrefError("more than 4 million objects")
    budget.objects += len(src.ents)
    return src


def _prefixed(prefix: str, name: str) -> str:
    return prefix + "|" + name


def _import(d, prefix, src, stack, src_path, depth, budget, notes):
    maps = {t: {} for t in SYMBOL_TABLES}
    for r in src.tables["layers"].values():
        nn = _prefixed(prefix, r["name"])
        maps["layers"][r["name"].casefold()] = nn
        if d.tables["layers"].get(nn) is None:
            nr = copy.deepcopy(r)
            nr["name"] = nn
            nr["xref"] = prefix
            d.table_set("layers", nr)
        else:
            d.modify_record("layers", nn)["xref"] = prefix
    for r in src.tables["linetypes"].values():
        if r["name"].casefold() in SPECIAL_LT:
            continue
        nn = _prefixed(prefix, r["name"])
        maps["linetypes"][r["name"].casefold()] = nn
        nr = copy.deepcopy(r)
        nr["name"] = nn
        nr["xref"] = prefix
        d.table_set("linetypes", nr)
    for t in ("textstyles", "dimstyles"):
        for r in src.tables[t].values():
            nn = _prefixed(prefix, r["name"])
            maps[t][r["name"].casefold()] = nn
            nr = copy.deepcopy(r)
            nr["name"] = nn
            nr["xref"] = prefix
            d.table_set(t, nr)
    nested, skipped, plain = [], set(), []
    for r in src.tables["blocks"].values():
        if isinstance(r.get("edit"), dict):
            continue
        nn = _prefixed(prefix, r["name"])
        maps["blocks"][r["name"].casefold()] = nn
        if is_xref(r):
            if r["xref"].get("overlay"):
                skipped.add(nn.casefold())
                continue
            nr = copy.deepcopy(r)
            nr["name"] = nn
            nr["xref"] = new_info(r["xref"].get("path", ""), False, r["xref"].get("typed", False))
            nr["anonymous"] = False
            d.table_set("blocks", nr)
            d.ensure_space(block_space(nn))
            nested.append(nn)
        else:
            nr = copy.deepcopy(r)
            nr["name"] = nn
            d.table_set("blocks", nr)
            d.ensure_space(block_space(nn))
            plain.append(r["name"])
    count = 0

    def move(e, space):
        nonlocal count
        if e.kind in ("insert", "dimension") and getattr(e, "block", "") and maps["blocks"].get(e.block.casefold(), "").casefold() in skipped:
            return
        dd = {f.name: getattr(e, f.name) for f in dataclasses.fields(e)}
        dd["handle"] = 0
        ne = type(e).from_dict(dd)
        BT.retarget(ne, maps)
        if budget.objects + count > MAX_OBJECTS:
            raise XrefError("more than 4 million objects")
        h = d.new_handle()
        ne.handle = h
        ne.owner = space
        d._rec_entity(h)
        d._rec_space(space)
        d.ensure_space(space)
        d.ents[h] = ne
        d.spaces[space].append(h)
        count += 1

    top_space = block_space(prefix)
    for e in src.entities(SPACE_MODEL):
        move(e, top_space)
    for bn in plain:
        for e in src.entities(block_space(bn)):
            move(e, block_space(_prefixed(prefix, bn)))
    top_count = len(d.spaces.get(top_space, []))
    for nn in nested:
        load_one(d, nn, src_path, stack, depth + 1, budget, notes, True)
    return top_count


def clear(d, name, keep_layers=True):
    prefix = (name + "|").casefold()
    spaces = [block_space(name)] + [s for s in list(d.spaces) if s.casefold().startswith("block:" + prefix)]
    for sp in spaces:
        handles = list(d.spaces.get(sp, []))
        if not handles:
            continue
        d._rec_space(sp)
        for h in handles:
            d._rec_entity(h)
            d.ents.pop(h, None)
        d.spaces[sp] = []
    for t in ("linetypes", "textstyles", "dimstyles", "blocks") + (() if keep_layers else ("layers",)):
        for r in list(d.tables[t].values()):
            if r["name"].casefold().startswith(prefix):
                d.table_remove(t, r["name"])
    for sp in spaces[1:]:
        if sp in d.spaces:
            d._rec_space(sp)
            del d.spaces[sp]


def load_one(d, name, host_path, stack, depth, budget, notes, nested=False):
    rec = d.modify_record("blocks", name)
    x = rec["xref"]
    x.update({"status": "notloaded", "reason": "", "resolved": "", "objects": 0})
    label = 'nested xref "%s"' % name if nested else 'Xref "%s"' % name
    if x.get("unloaded"):
        x["status"] = "unloaded"
        return
    if depth > MAX_DEPTH:
        x.update(status="unresolved", reason="nesting is deeper than %d levels" % MAX_DEPTH)
        notes.append("%s not loaded: %s" % (label, x["reason"]))
        return
    path, st, why = resolve(x["path"], host_path, bool(x.get("typed")))
    if path is None:
        x.update(status=st, reason=why)
        notes.append("%s not loaded: %s" % (label, why))
        return
    x["resolved"] = path
    if path in stack:
        x.update(status="unresolved", reason="circular reference")
        notes.append("%s not loaded: circular reference" % label)
        return
    try:
        src = read_drawing(path, budget)
    except XrefError as err:
        x.update(status="unresolved", reason=err.args[0] if err.args else "unreadable")
        notes.append("%s not loaded: %s" % (label, x["reason"]))
        return
    try:
        n = _import(d, name, src, stack + [path], path, depth, budget, notes)
    except XrefError as err:
        clear(d, name)
        x.update(status="unresolved", reason=err.args[0] if err.args else "too large")
        notes.append("%s not loaded: %s" % (label, x["reason"]))
        return
    x.update(status="loaded", objects=n)
    notes.append('%s loaded from %s.' % (label, path))


def resolve_all(drawing, host_path: str) -> list:
    notes = []
    budget = Budget()
    stack = [os.path.realpath(host_path)] if host_path else []
    for rec in tops(drawing):
        try:
            load_one(drawing, rec["name"], host_path, stack, 0, budget, notes)
        except Exception as err:
            rec["xref"].update(status="unresolved", reason=str(err))
            notes.append('Xref "%s" not loaded: %s' % (rec["name"], err))
    return notes


def references(d, name) -> int:
    low = name.casefold()
    return sum(1 for e in d.ents.values() if e.kind == "insert" and e.block.casefold() == low and not e.owner.casefold().startswith("block:" + low + "|"))


def effective_status(d, rec) -> str:
    x = rec["xref"]
    if x["status"] == "loaded" and references(d, rec["name"]) == 0:
        return "unreferenced"
    return x["status"]


def listing(d) -> list:
    out = []
    names = sorted(d.tables["blocks"].values(), key=lambda r: r["name"].casefold())
    for r in names:
        if not is_xref(r):
            continue
        x = r["xref"]
        st = effective_status(d, r)
        out.append({"name": r["name"], "path": x["path"], "found": x.get("resolved", ""), "type": "Overlay" if x.get("overlay") else "Attach", "status": STATUS_TEXT.get(st, st), "state": st, "references": references(d, r["name"]), "objects": x.get("objects", 0), "reason": x.get("reason", ""), "nested": "|" in r["name"], "parent": r["name"].rsplit("|", 1)[0] if "|" in r["name"] else ""})
    return out


def find(d, name):
    rec = d.table_get("blocks", name)
    if not is_xref(rec):
        raise XrefError('"%s" is not an external reference.' % name)
    return rec


def match(d, spec):
    names = [r["name"] for r in tops(d)]
    return BT.wildcard(spec or "*", names)


def attach(doc, path: str, name: str = "", overlay: bool = False) -> dict:
    d = doc.drawing
    resolved, st, why = resolve(path, doc.path, True)
    if resolved is None:
        raise XrefError('Cannot find file "%s".' % path if st == "notfound" else "%s: %s" % (path, why))
    for r in tops(d):
        if r["xref"].get("resolved") and os.path.realpath(r["xref"]["resolved"]) == resolved:
            return {"name": r["name"], "reused": True, "status": r["xref"]["status"], "notes": []}
        if r["xref"]["status"] != "loaded":
            p2, _s, _w = resolve(r["xref"]["path"], doc.path, bool(r["xref"].get("typed")))
            if p2 == resolved:
                return {"name": r["name"], "reused": True, "status": r["xref"]["status"], "notes": []}
    nm = (name or os.path.splitext(os.path.basename(resolved))[0]).strip()
    if not BT.valid_name(nm) or nm.startswith("*"):
        raise XrefError("Invalid xref name.")
    if d.tables["blocks"].has(nm):
        raise XrefError('The name "%s" is already used by another block or file.' % nm)
    from app.doc import blockedit

    blockedit.flag(doc)
    d.define_block(nm, [0.0, 0.0, 0.0], "", new_info(stored_path(resolved, doc.path), overlay, False))
    notes = []
    load_one(d, nm, doc.path, [os.path.realpath(doc.path)] if doc.path else [], 0, Budget(), notes)
    return {"name": nm, "reused": False, "status": d.table_get("blocks", nm)["xref"]["status"], "notes": notes}


def reload(doc, name: str) -> dict:
    d = doc.drawing
    rec = find(d, name)
    clear(d, rec["name"])
    rec = d.modify_record("blocks", rec["name"])
    rec["xref"]["unloaded"] = False
    notes = []
    load_one(d, rec["name"], doc.path, [os.path.realpath(doc.path)] if doc.path else [], 0, Budget(), notes)
    return {"name": rec["name"], "status": d.table_get("blocks", rec["name"])["xref"]["status"], "notes": notes}


def unload(doc, name: str) -> dict:
    d = doc.drawing
    rec = find(d, name)
    clear(d, rec["name"])
    rec = d.modify_record("blocks", rec["name"])
    rec["xref"].update(unloaded=True, status="unloaded", objects=0, reason="")
    return {"name": rec["name"], "status": "unloaded"}


def detach(doc, name: str) -> dict:
    d = doc.drawing
    rec = find(d, name)
    nm = rec["name"]
    gone = 0
    low = nm.casefold()
    for h in [e.handle for e in d.ents.values() if e.kind in ("insert", "dimension") and getattr(e, "block", "").casefold() == low]:
        if d.get(h) is not None and d.get(h).kind == "insert":
            d.erase_entity(h)
            gone += 1
    clear(d, nm, False)
    d._rec_space(block_space(nm))
    d.spaces.pop(block_space(nm), None)
    d.table_remove("blocks", nm)
    return {"name": nm, "references_removed": gone}


def set_path(doc, name: str, path: str) -> dict:
    d = doc.drawing
    rec = find(d, name)
    if "|" in rec["name"]:
        raise XrefError("The path of a nested reference belongs to the file that holds it.")
    new = str(path or "").strip()
    if not new:
        raise XrefError("A path is required.")
    resolved, _st, _why = resolve(new, doc.path, True)
    rec = d.modify_record("blocks", rec["name"])
    rec["xref"]["path"] = stored_path(resolved, doc.path) if resolved else new
    rec["xref"]["typed"] = False if resolved else True
    if rec["xref"].get("unloaded"):
        return {"name": rec["name"], "status": "unloaded", "notes": []}
    return reload(doc, rec["name"])


def set_type(doc, name: str, overlay: bool) -> dict:
    d = doc.drawing
    rec = find(d, name)
    if "|" in rec["name"]:
        raise XrefError("The type of a nested reference belongs to the file that holds it.")
    rec = d.modify_record("blocks", rec["name"])
    rec["xref"]["overlay"] = bool(overlay)
    return {"name": rec["name"], "type": "Overlay" if overlay else "Attach"}


def dependents(d, name):
    prefix = (name + "|").casefold()
    return {t: [r["name"] for r in d.tables[t].values() if r["name"].casefold().startswith(prefix)] for t in SYMBOL_TABLES}


def _bound_name(old, n):
    return old.replace("|", "$%d$" % n)


def bind(doc, name: str, insert_mode: bool = False) -> dict:
    d = doc.drawing
    rec = find(d, name)
    nm = rec["name"]
    if "|" in nm:
        raise XrefError("Bind the outer reference; nested references are bound with it.")
    if rec["xref"]["status"] != "loaded":
        raise XrefError('Xref "%s" is not loaded, so it cannot be bound.' % nm)
    names = dependents(d, nm)
    maps = {t: {} for t in SYMBOL_TABLES}
    create = {t: [] for t in SYMBOL_TABLES}
    if insert_mode:
        seen = {t: set() for t in SYMBOL_TABLES}
        for t in SYMBOL_TABLES:
            for old in names[t]:
                new = old.rsplit("|", 1)[1]
                maps[t][old.casefold()] = new
                if not d.tables[t].has(new) and new.casefold() not in seen[t]:
                    seen[t].add(new.casefold())
                    create[t].append(old)
    else:
        n = 0
        while True:
            clash = False
            for t in SYMBOL_TABLES:
                for old in names[t]:
                    if d.tables[t].has(_bound_name(old, n)):
                        clash = True
            if not clash:
                break
            n += 1
        for t in SYMBOL_TABLES:
            for old in names[t]:
                maps[t][old.casefold()] = _bound_name(old, n)
                create[t].append(old)
    from app.doc import blockedit

    blockedit.flag(doc)
    owned = [block_space(nm)] + [block_space(o) for o in names["blocks"]]
    for sp in owned:
        for h in list(d.spaces.get(sp, [])):
            BT.retarget(d.modify(h), maps)
    for t in SYMBOL_TABLES:
        for old in names[t]:
            new = maps[t][old.casefold()]
            if old in create[t]:
                nr = copy.deepcopy(d.table_get(t, old))
                nr["name"] = new
                nr.pop("xref", None)
                if t == "blocks":
                    nr["xref"] = None
                d.table_set(t, nr)
                if t == "blocks":
                    osp, nsp = block_space(old), block_space(new)
                    d._rec_space(osp)
                    d._rec_space(nsp)
                    handles = list(d.spaces.pop(osp, []))
                    d.spaces[nsp] = handles
                    for h in handles:
                        d.modify(h).owner = nsp
            elif t == "blocks":
                for h in list(d.spaces.get(block_space(old), [])):
                    d.erase_entity(h)
                d._rec_space(block_space(old))
                d.spaces.pop(block_space(old), None)
            d.table_remove(t, old)
    rec = d.modify_record("blocks", nm)
    rec["xref"] = None
    count = sum(len(v) for v in create.values())
    return {"name": nm, "mode": "insert" if insert_mode else "bind", "symbols": count}


def xbind(doc, kind: str, spec: str) -> dict:
    d = doc.drawing
    table = {"block": "blocks", "dimstyle": "dimstyles", "layer": "layers", "ltype": "linetypes", "linetype": "linetypes", "style": "textstyles", "textstyle": "textstyles"}.get(kind.lower())
    if table is None:
        raise XrefError("Only blocks, dimension styles, layers, linetypes and text styles can be bound.")
    cands = [r["name"] for r in d.tables[table].values() if "|" in r["name"]]
    picked = BT.wildcard(spec, cands)
    if not picked:
        raise XrefError('No dependent %s matches "%s".' % (kind, spec))
    from app.doc import blockedit

    blockedit.flag(doc)
    done = {}
    maps = {t: {} for t in SYMBOL_TABLES}

    def bound(t, old):
        key = old.casefold()
        if key in maps[t]:
            return maps[t][key]
        n = 0
        while d.tables[t].has(_bound_name(old, n)):
            n += 1
        new = _bound_name(old, n)
        maps[t][key] = new
        rec = d.table_get(t, old)
        if rec is None:
            return old
        nr = copy.deepcopy(rec)
        nr["name"] = new
        nr.pop("xref", None)
        done[(t, old)] = new
        if t == "layers":
            lt = nr.get("linetype", "")
            if "|" in lt:
                nr["linetype"] = bound("linetypes", lt)
        if t == "dimstyles":
            tx = nr.get("vars", {}).get("DIMTXSTY", "")
            if "|" in str(tx):
                nr["vars"]["DIMTXSTY"] = bound("textstyles", tx)
        if t == "blocks":
            nr["xref"] = None
            d.table_set(t, nr)
            sp = block_space(new)
            d.ensure_space(sp)
            for e in list(d.entities(block_space(old))):
                dd = e.to_dict()
                dd["handle"] = 0
                ne = entity_from_dict(dd)
                for fld, tb in (("layer", "layers"), ("linetype", "linetypes"), ("block", "blocks")):
                    v = getattr(ne, fld, None)
                    if isinstance(v, str) and "|" in v and d.tables[tb].has(v):
                        setattr(ne, fld, bound(tb, v))
                if ne.kind in ("text", "mtext", "attdef") and "|" in str(ne.style) and d.tables["textstyles"].has(ne.style):
                    ne.style = bound("textstyles", ne.style)
                d.add_entity(ne, sp)
            return new
        d.table_set(t, nr)
        return new

    for old in picked:
        bound(table, old)
    return {"bound": len(done), "names": sorted(done.values())}


def clip_spaces(data: dict, names: set) -> None:
    spaces = {block_space(n) for n in names}
    data["spaces"] = [s for s in data.get("spaces", []) if s not in spaces]
    data["entities"] = [e for e in data.get("entities", []) if e.get("owner") not in spaces]


def strip_for_save(data: dict) -> None:
    blocks = data.get("tables", {}).get("blocks", [])
    topn = {r["name"].casefold() for r in blocks if isinstance(r.get("xref"), dict) and "|" not in r["name"]}
    if not topn:
        return
    prefixes = tuple(n + "|" for n in topn)

    def dependent(name):
        return name.casefold().startswith(prefixes)

    gone = {r["name"] for r in blocks if dependent(r["name"]) or r["name"].casefold() in topn}
    clip_spaces(data, gone)
    for t in ("linetypes", "textstyles", "dimstyles", "blocks"):
        data["tables"][t] = [r for r in data["tables"].get(t, []) if not dependent(r["name"])]
    for r in data["tables"]["blocks"]:
        if isinstance(r.get("xref"), dict):
            r["xref"] = {**r["xref"], "status": "unloaded" if r["xref"].get("unloaded") else "notloaded", "reason": "", "resolved": "", "objects": 0}
