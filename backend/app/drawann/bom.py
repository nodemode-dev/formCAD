import os

from app.drawann import settings

COLUMN_KEYS = settings.BOM_COLUMNS


class BomError(Exception):
    pass


def norm(raw: dict, n: int) -> dict:
    g = lambda *ks: next((str(raw[k]) for k in ks if raw.get(k) not in (None, "")), "")
    try:
        qty = int(float(raw.get("qty", raw.get("quantity", 1))))
    except (TypeError, ValueError):
        qty = 1
    return {"item": g("item", "number", "find") or str(n), "part_number": g("part_number", "pn"), "description": g("description", "label", "name"), "material": g("material"), "qty": qty, "key": g("key", "cid")}


def from_rows(rows) -> list:
    if not isinstance(rows, list) or not rows:
        raise BomError("Give at least one BOM row.")
    return [norm(r, i + 1) for i, r in enumerate(rows) if isinstance(r, dict)]


def leaf(inst) -> bool:
    lp = inst.part
    return lp is not None and not getattr(lp, "is_assembly", False)


def from_instances(instances) -> list:
    groups = {}
    order = []
    for inst in instances:
        if inst.suppressed or not leaf(inst):
            continue
        rec = inst.record
        ref = rec.get("ref") or {}
        ident = (ref.get("abs") or ref.get("path") or "embedded:" + str(rec.get("id")), rec.get("config", ""))
        if ident not in groups:
            lp = inst.part
            props = dict(getattr(lp, "props", {}) or {})
            stem = os.path.splitext(os.path.basename(ref.get("path") or ""))[0]
            groups[ident] = {"item": "", "part_number": props.get("part_number") or stem or str(rec.get("label", "")), "description": props.get("description") or str(rec.get("label", "")), "material": props.get("material") or lp.material_of(rec.get("config", "")), "qty": 0, "key": inst.key, "keys": []}
            order.append(ident)
        groups[ident]["qty"] += 1
        groups[ident]["keys"].append(inst.key)
    out = []
    for i, ident in enumerate(order):
        g = groups[ident]
        g["item"] = str(i + 1)
        out.append(g)
    return out


def collect(doc) -> list:
    from app.assembly import bom as asm_bom
    from app.assembly.store import AssemblyError

    try:
        info = asm_bom.build(doc, "flat")
    except AssemblyError as err:
        raise BomError(str(err))
    rows = []
    for r in info["rows"]:
        rows.append({"item": str(r.get("find", "")), "part_number": r.get("part_number", ""), "description": r.get("description") or r.get("name", ""), "material": r.get("material", ""), "qty": int(r.get("ext_qty", r.get("qty", 1))), "key": str((r.get("keys") or [r.get("cid", "")])[0]), "keys": [str(k) for k in (r.get("keys") or [])]})
    return rows


def cells(rows, columns) -> list:
    return [[str(r.get(c, "")) for c in columns] for r in rows]


def widths(rows, columns, th) -> list:
    out = []
    for i, c in enumerate(columns):
        longest = max([len(settings.COLUMN_TITLES[c])] + [len(str(r.get(c, ""))) for r in rows])
        out.append(max(8.0, 0.85 * th * longest + 3.0 * th * 0.6))
    return out
