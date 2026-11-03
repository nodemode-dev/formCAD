import copy

from app.render import appearances
from app.solid import scene as base

TABLE = "render"
ASSIGN = "assign"
MAX_ASSIGNMENTS = 20000


class TargetError(ValueError):
    pass


def assignments(d) -> dict:
    t = d.tables.get(TABLE)
    rec = t.get(ASSIGN) if t is not None else None
    m = rec.get("map") if isinstance(rec, dict) else None
    return dict(m) if isinstance(m, dict) else {}


def _rgb_hex(rgb) -> str:
    try:
        r, g, b = (max(0, min(255, int(round(float(c) * 255)))) for c in list(rgb)[:3])
    except (TypeError, ValueError):
        return ""
    return "#%02x%02x%02x" % (r, g, b)


def _effective(amap: dict, keys: list, material: str, own_rgb) -> tuple:
    for k in keys:
        name = amap.get(k)
        if name:
            row = appearances.find(name)
            if row is not None:
                return row, "assigned"
    row = appearances.for_material(material)
    if row is not None:
        return row, "material"
    row = dict(appearances.default_row())
    tint = _rgb_hex(own_rgb) if own_rgb else ""
    if tint:
        row = dict(row, base_color=tint, name=row["name"] + " (body colour)")
        return row, "body colour"
    return row, "default"


def rows(doc) -> list:
    d = doc.drawing
    amap = assignments(d)
    out = []
    if doc.kind == "assembly":
        from app.assembly import walk

        handle = 0
        for inst in walk.instances(doc):
            if inst.record["type"] == "assembly" or inst.part is None:
                continue
            lp = inst.part
            for b in lp.bodies:
                handle += 1
                keys = ["i:%s/%s" % (inst.key, b.name), "i:%s" % inst.key]
                row, how = _effective(amap, keys, b.material or "", b.rgb)
                out.append({"id": handle, "key": keys[0], "instance_key": keys[1], "name": inst.record["label"] + ("" if len(lp.bodies) == 1 else " / " + b.name), "material": b.material or "", "appearance": row, "from": how, "assigned": next((amap[k] for k in keys if amap.get(k)), "")})
        for e in d.ordered_entities():
            if e.kind != "solidbody" or e.owner != "model":
                continue
            handle += 1
            row, how = _effective(amap, ["h:%d" % e.handle], getattr(e, "material", "") or "", e.rgb)
            out.append({"id": handle, "key": "h:%d" % e.handle, "instance_key": "", "name": e.name or "Body", "material": getattr(e, "material", "") or "", "appearance": row, "from": how, "assigned": amap.get("h:%d" % e.handle, "")})
    else:
        for e in d.ordered_entities():
            if e.kind not in base.BODY_KINDS:
                continue
            row, how = _effective(amap, ["h:%d" % e.handle], getattr(e, "material", "") or "", e.rgb)
            out.append({"id": e.handle, "key": "h:%d" % e.handle, "instance_key": "", "name": e.name or "Body", "material": getattr(e, "material", "") or "", "appearance": row, "from": how, "assigned": amap.get("h:%d" % e.handle, "")})
    return out


def assign(d, keys: list, name) -> dict:
    if not isinstance(keys, list) or not keys:
        raise TargetError("Choose at least one body.")
    if len(keys) > MAX_ASSIGNMENTS:
        raise TargetError("Too many bodies in one request.")
    for k in keys:
        if not isinstance(k, str) or not (k.startswith("i:") or k.startswith("h:")) or len(k) > 400:
            raise TargetError("A body key looks like i:<instance>, i:<instance>/<body> or h:<handle>.")
    if name:
        if appearances.find(str(name)) is None:
            raise TargetError("There is no appearance called %s." % name)
        name = appearances.find(str(name))["name"]
    amap = assignments(d)
    for k in keys:
        if name:
            amap[k] = name
        else:
            amap.pop(k, None)
    if len(amap) > MAX_ASSIGNMENTS:
        raise TargetError("Too many assignments.")
    d.table_set(TABLE, {"name": ASSIGN, "map": copy.deepcopy(amap)})
    return {"assigned": len(keys), "appearance": name or ""}
