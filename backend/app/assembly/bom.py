import csv
import io
import os

from app.assembly import refs, store, walk
from app.assembly.store import AssemblyError

COLUMNS = {
    "find": "Find", "level": "Level", "name": "Name", "part_number": "Part number", "description": "Description", "material": "Material", "qty": "Qty", "ext_qty": "Total qty",
    "revision": "Revision", "file": "File", "status": "Status", "type": "Type",
}
DEFAULT_COLUMNS = ("find", "part_number", "description", "material", "qty")
MODES = ("top", "indented", "flat")
LEAD = ("=", "+", "-", "@", "\t", "\r")


def props_of(inst) -> dict:
    lp = inst.part
    merged = dict(lp.props) if lp is not None else {}
    if lp is None:
        merged = dict((inst.record.get("cache") or {}).get("props") or {})
    merged.update({k: v for k, v in (inst.record.get("props") or {}).items() if v != ""})
    if not merged.get("part_number") and merged.get("idno"):
        merged["part_number"] = merged["idno"]
    return merged


def identity(inst, props: dict) -> str:
    pn = (props.get("part_number") or "").strip()
    if pn:
        return "pn:" + pn.casefold()
    rec = inst.record
    if rec["type"] == "embedded":
        return "emb:" + rec["id"]
    ref = rec.get("ref") or {}
    path = (inst.status.get("resolved") or ref.get("abs") or ref.get("path") or "").casefold()
    return "file:%s#%s" % (path, (getattr(inst, "config", "") or "").casefold())


def describe(inst) -> dict:
    p = props_of(inst)
    lp = inst.part
    material = p.get("material") or (lp.material_of() if lp is not None else "") or ""
    return {
        "item": identity(inst, p), "name": inst.record["label"], "type": inst.record["type"], "part_number": p.get("part_number", ""), "description": p.get("description") or p.get("title") or "",
        "material": material, "revision": p.get("revision", ""), "file": (inst.record.get("ref") or {}).get("path", "") if inst.record["type"] != "embedded" else "(embedded)",
        "status": inst.status["status"] + (" (copy)" if inst.status["stale"] else ""), "cid": inst.cid, "config": getattr(inst, "config", ""),
    }


def _group(insts: list) -> list:
    groups: dict = {}
    for inst in insts:
        info = describe(inst)
        g = groups.setdefault(info["item"], {"info": info, "insts": []})
        g["insts"].append(inst)
    return list(groups.values())


def _children(all_insts: list, parent_key: str, depth: int) -> list:
    prefix = parent_key + "/"
    return [i for i in all_insts if i.depth == depth and i.key.startswith(prefix) and "/" not in i.key[len(prefix):]]


def _tree(all_insts: list, insts: list, depth: int, mult: int, out: list, finds: dict, warns: list) -> None:
    for g in _group(insts):
        info = g["info"]
        qty = len(g["insts"])
        if len({i.record["label"].casefold() for i in g["insts"]}) > 1:
            info = {**info, "name": refs.stem(info["file"]) if info["type"] != "embedded" else info["name"]}
        row = {**info, "level": depth, "qty": qty, "ext_qty": qty * mult, "keys": [i.key for i in g["insts"]], "stale": any(i.status["stale"] for i in g["insts"])}
        out.append(row)
        if info["type"] == "assembly":
            first = g["insts"][0]
            kids = _children(all_insts, first.key, depth + 1)
            _tree(all_insts, kids, depth + 1, mult * qty, out, finds, warns)


def _number(rows: list, finds: dict, nxt: int) -> tuple:
    stored = dict(finds)
    provisional = False
    for r in rows:
        n = stored.get(r["item"])
        if n is None:
            n = nxt
            nxt += 1
            stored[r["item"]] = n
            r["provisional"] = True
            provisional = True
        else:
            r["provisional"] = False
        r["find"] = n
    return stored, nxt, provisional


def build(doc, mode: str = "indented", include_suppressed: bool = False, include_assemblies: bool = True) -> dict:
    mode = str(mode or "indented").lower()
    if mode not in MODES:
        raise AssemblyError("The BOM mode is top, indented or flat.")
    d = doc.drawing
    head = store.header(d)
    insts = walk.instances(doc, include_suppressed)
    if not include_suppressed:
        insts = [i for i in insts if not i.suppressed]
    tree: list = []
    warns: list = []
    _tree(insts, [i for i in insts if i.depth == 0], 0, 1, tree, head.get("finds") or {}, warns)
    if mode == "top":
        rows = [dict(r) for r in tree if r["level"] == 0]
        for r in rows:
            r["ext_qty"] = r["qty"]
    elif mode == "indented":
        rows = tree
    else:
        merged: dict = {}
        for i, r in enumerate(tree):
            has_kids = i + 1 < len(tree) and tree[i + 1]["level"] > r["level"]
            if r["type"] == "assembly" and (has_kids or not include_assemblies):
                continue
            m = merged.get(r["item"])
            if m is None:
                m = dict(r)
                m["qty"] = 0
                m["ext_qty"] = 0
                m["level"] = 0
                m["keys"] = []
                merged[r["item"]] = m
            m["ext_qty"] += r["ext_qty"]
            m["qty"] = m["ext_qty"]
            m["keys"] += r["keys"]
        rows = list(merged.values())
    all_items = []
    for r in tree:
        if r["item"] not in all_items:
            all_items.append(r["item"])
    stored, nxt, provisional = _number(rows, dict(head.get("finds") or {}), int(head.get("find_next", 1)))
    for r in rows:
        if not r["part_number"]:
            warns.append("%s has no part number." % r["name"])
    seen: dict = {}
    for r in tree:
        if r["part_number"]:
            prev = seen.setdefault(r["part_number"].casefold(), r["description"])
            if prev != r["description"]:
                warns.append("Part number %s is used with two descriptions." % r["part_number"])
    bad = sorted({r["name"] for r in tree if r["status"].startswith(("missing", "outofdate"))})
    if bad:
        warns.append("Not current: %s." % ", ".join(bad[:12]))
    return {"mode": mode, "rows": rows, "provisional": provisional, "warnings": list(dict.fromkeys(warns)), "total_parts": sum(r["ext_qty"] for r in rows) if mode == "flat" else sum(r["qty"] for r in tree if r["level"] == 0), "items": len(rows)}


def assign(doc) -> dict:
    d = doc.drawing
    head = store.ensure(d)
    info = build(doc, "indented", True)
    stored, nxt, _prov = _number([dict(r) for r in info["rows"]], dict(head.get("finds") or {}), int(head.get("find_next", 1)))
    head["finds"] = stored
    head["find_next"] = nxt
    store.save_header(d, head)
    return {"finds": stored, "next": nxt}


def renumber(doc) -> dict:
    d = doc.drawing
    head = store.ensure(d)
    info = build(doc, "indented", True)
    finds = {}
    n = 1
    for r in info["rows"]:
        if r["item"] not in finds:
            finds[r["item"]] = n
            n += 1
    head["finds"] = finds
    head["find_next"] = n
    store.save_header(d, head)
    return {"finds": finds, "next": n}


def cell(text) -> str:
    s = "" if text is None else str(text)
    return "'" + s if s.startswith(LEAD) else s


def columns_for(cols) -> list:
    out = []
    for c in cols or DEFAULT_COLUMNS:
        k = str(c).strip().lower()
        if k not in COLUMNS:
            raise AssemblyError("%s is not a BOM column; use %s." % (c, ", ".join(COLUMNS)))
        if k not in out:
            out.append(k)
    return out


def to_csv(info: dict, cols) -> str:
    cols = columns_for(cols)
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([COLUMNS[c] for c in cols])
    for r in info["rows"]:
        out = []
        for c in cols:
            v = r.get(c, "")
            if c == "name" and info["mode"] == "indented":
                v = ("  " * int(r["level"])) + str(v)
            out.append(cell(v))
        w.writerow(out)
    return buf.getvalue()


def export_csv(doc, path: str, mode: str = "indented", columns=None, include_suppressed: bool = False) -> dict:
    from app.core import outputs

    try:
        full = outputs.checked(path, (".csv",), ".csv")
    except outputs.OutputRefused as err:
        raise AssemblyError(str(err))
    assign(doc)
    info = build(doc, mode, include_suppressed)
    text = to_csv(info, columns)
    try:
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as err:
        raise AssemblyError("The file could not be written (%s)." % err.strerror)
    return {"path": full, "rows": len(info["rows"]), "mode": info["mode"], "warnings": info["warnings"]}
