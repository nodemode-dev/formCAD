import copy
import re

from app.doc import layouts
from app.doc.entities import entity_from_dict
from app.doc.model import block_space, layout_space

STYLE_TABLES = ("layers", "linetypes", "textstyles", "dimstyles", "mleaderstyles", "tablestyles", "mlinestyles", "plotstyles")
MAX_LAYOUTS = 64


def pick(src, wanted) -> list:
    recs = layouts.records(src)
    w = str(wanted or "").strip()
    if w in ("", "*"):
        return recs[:MAX_LAYOUTS]
    rec = layouts.find(src, w)
    if rec is None:
        raise layouts.LayoutError('The template has no layout named "%s".' % w)
    return [rec]


def free_name(d, name: str) -> str:
    if not layouts.check_name(d, name):
        return name
    base = re.sub(r"\s*\(\d+\)$", "", name.strip())[:240]
    i = 2
    while layouts.check_name(d, "%s (%d)" % (base, i)):
        i += 1
    return "%s (%d)" % (base, i)


def needed_blocks(src, ents) -> list:
    seen = []
    stack = [getattr(e, "block", "") for e in ents]
    while stack:
        nm = stack.pop()
        if not nm or nm.casefold() in (s.casefold() for s in seen):
            continue
        rec = src.tables["blocks"].get(nm)
        if rec is None or rec.get("xref"):
            continue
        seen.append(rec["name"])
        stack.extend(getattr(e, "block", "") for e in src.entities(block_space(rec["name"])))
    return seen


def copy_blocks(d, src, names) -> dict:
    remap = {}
    fresh = []
    taken = set()
    for nm in names:
        if not d.tables["blocks"].has(nm):
            remap[nm.casefold()] = nm
            fresh.append(nm)
        elif nm.startswith("*"):
            n = 1
            while d.tables["blocks"].has("*U%d" % n) or n in taken:
                n += 1
            taken.add(n)
            remap[nm.casefold()] = "*U%d" % n
            fresh.append(nm)
    for nm in fresh:
        target = remap[nm.casefold()]
        rec = src.tables["blocks"].get(nm)
        nr = d.define_block(target, rec.get("base"), rec.get("description", ""))
        nr["explodable"] = bool(rec.get("explodable", True))
        nr["annotative"] = bool(rec.get("annotative", False))
        d.table_set("blocks", nr)
    for nm in fresh:
        target = remap[nm.casefold()]
        for e in src.entities(block_space(nm)):
            c = entity_from_dict(e.to_dict())
            c.handle = 0
            c.reactors = []
            if getattr(c, "block", None) and c.block.casefold() in remap:
                c.block = remap[c.block.casefold()]
            d.add_entity(c, block_space(target))
    return remap


def import_layouts(d, src, wanted=None) -> dict:
    chosen = pick(src, wanted)
    if not chosen:
        raise layouts.LayoutError("The template has no layouts.")
    for t in STYLE_TABLES:
        if t not in src.tables or t not in d.tables:
            continue
        for rec in src.tables[t].values():
            if not d.tables[t].has(rec["name"]):
                d.table_set(t, copy.deepcopy(rec))
    made = []
    notes = []
    objects = 0
    for rec in chosen:
        ents = list(src.entities(layout_space(rec["name"])))
        remap = copy_blocks(d, src, needed_blocks(src, ents))
        name = free_name(d, rec["name"])
        ps = layouts.normalize(d, rec.get("page_setup"))
        if ps.get("style_table") and not d.tables["plotstyles"].has(ps["style_table"]):
            ps["style_table"] = ""
        fresh = copy.deepcopy(rec)
        fresh.update({"name": name, "tab_order": len(d.tables["layouts"]) + 1, "page_setup": ps, "view": None})
        probe = layouts.unit_mm(src, layouts.normalize(src, rec.get("page_setup")))
        if probe != layouts.unit_mm(d, ps):
            notes.append('Layout "%s": the template sheet units differ from this drawing; paper space objects were not scaled.' % name)
        d.table_set("layouts", fresh)
        space = layout_space(name)
        d.ensure_space(space)
        for e in ents:
            c = entity_from_dict(e.to_dict())
            c.handle = 0
            c.reactors = []
            if getattr(c, "block", None) and c.block.casefold() in remap:
                c.block = remap[c.block.casefold()]
            if c.kind == "viewport":
                c.clip_source = 0
            if c.kind == "dimension":
                c.associativity = {}
            d.add_entity(c, space)
            objects += 1
        made.append(name)
    layouts.renumber(d)
    return {"layouts": made, "objects": objects, "notes": notes}
