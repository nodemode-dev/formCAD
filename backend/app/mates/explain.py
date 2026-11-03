import math

from app.mates import eqs


def value_text(rec: dict) -> str:
    v = rec.get("value")
    kind = rec["kind"]
    if v is None:
        if kind.startswith("limit"):
            o = rec.get("opt") or {}
            return " %g to %g" % (o.get("min", 0), o.get("max", 0))
        return ""
    if kind in ("angle",):
        return " %g deg" % v
    return " %g" % v


def text_of(rec: dict) -> str:
    comps = []
    for r in rec.get("refs") or []:
        c = r.get("comp") or "world"
        if c not in comps:
            comps.append(c)
    label = rec.get("label") or rec["name"]
    return "%s (%s%s between %s)" % (label, rec["kind"], value_text(rec), " and ".join(comps))


def item(rec: dict, new_id=None) -> dict:
    return {"id": rec["id"], "name": rec["name"], "kind": rec["kind"], "label": rec.get("label", ""), "text": text_of(rec), "new": rec["id"] == new_id, "components": [r.get("comp") for r in rec.get("refs") or []]}


def conflict(recs_by_id: dict, mates: list, exact: bool, fixes: list, new_id=None) -> dict:
    ordered = sorted(mates, key=lambda m: (m.id == new_id, m.id))
    items = [item(recs_by_id[m.id], new_id) for m in ordered]
    names = ", ".join(i["text"] for i in items)
    out = {"kind": "conflict", "mates": items, "new": new_id, "minimal": exact, "fixes": [item(recs_by_id[m.id], new_id) for m in fixes]}
    out["message"] = "These mates cannot all hold at once: %s." % names
    if fixes:
        out["message"] += " Removing any one of %s lets the rest solve." % ", ".join(i["name"] for i in out["fixes"])
    return out


def redundant(recs_by_id: dict, ids: list, new_id=None) -> dict:
    items = [item(recs_by_id[i], new_id) for i in ids]
    return {"kind": "redundant", "mates": items, "new": new_id, "minimal": True, "fixes": [], "message": "This mate repeats what the others already fix: %s." % ", ".join(i["text"] for i in items)}


def unsupported(message: str) -> dict:
    return {"kind": "invalid", "mates": [], "message": message}


def deg(rad: float) -> float:
    return math.degrees(rad)
