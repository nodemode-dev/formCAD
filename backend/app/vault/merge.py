import copy
import json

from app.vault.base import MAX_CONFLICTS, VaultError, digest
from app.vault.entities import EMap, core, derived_entity, display, kind_of, scan_strings

MISSING = object()
CHOICES = ("ours", "theirs", "base", "value", "accept", "restore", "keep_both")
SHOW_LIMIT = 4000


def show(v):
    if v is MISSING:
        return {"$absent": True}
    try:
        text = json.dumps(v, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return {"$unprintable": True}
    if len(text) > SHOW_LIMIT:
        return {"$truncated": True, "size": len(text), "digest": digest(text.encode())[:6].hex()}
    return v


class Ctx:
    def __init__(self, choices: dict):
        self.choices = choices or {}
        self.conflicts: list = []
        self.rebuild = False
        self.stats = {"ours_only": 0, "theirs_only": 0, "both_same": 0, "fields_merged": 0, "added": 0, "removed": 0}

    def conflict(self, kind: str, entity: str, name: str, path: str, base, ours, theirs):
        if len(self.conflicts) >= MAX_CONFLICTS:
            raise VaultError("The merge has more than %d conflicts; merge in smaller steps." % MAX_CONFLICTS)
        cid = "c" + digest(("%s\0%s\0%s" % (kind, entity, path)).encode("utf-8"))[:5].hex()
        choice = self.choices.get(cid)
        rec = {"id": cid, "kind": kind, "entity": entity, "name": name, "path": path, "base": show(base), "ours": show(ours), "theirs": show(theirs), "suggested": "ours", "choice": None, "value": None}
        if isinstance(choice, dict) and "value" in choice:
            rec["choice"] = "value"
            rec["value"] = choice["value"]
        elif isinstance(choice, str):
            rec["choice"] = choice
        self.conflicts.append(rec)
        return rec

    def pick(self, rec, base, ours, theirs):
        c = rec["choice"]
        if c == "theirs":
            return theirs
        if c == "base":
            return base
        if c == "value":
            return rec["value"]
        return ours


def three(b, o, t, ctx: Ctx, entity: str, name: str, path: str = "", depth: int = 0):
    if o == t:
        return o
    if o == b:
        return t
    if t == b:
        return o
    if isinstance(o, dict) and isinstance(t, dict) and isinstance(b, dict) and depth < 6:
        out = {}
        for k in list(dict.fromkeys(list(o) + [x for x in t if x not in o] + [x for x in b if x not in o and x not in t])):
            r = three(b.get(k, MISSING), o.get(k, MISSING), t.get(k, MISSING), ctx, entity, name, (path + "." if path else "") + str(k), depth + 1)
            if r is not MISSING:
                out[k] = r
        if out != o and out != t:
            ctx.stats["fields_merged"] += 1
        return out
    rec = ctx.conflict("field", entity, name, path, b, o, t)
    return ctx.pick(rec, b, o, t)


def merge_order(b: list, o: list, t: list, keep: set, ctx: Ctx, entity: str, name: str) -> list:
    common = set(b) & set(o) & set(t) & keep
    sb = [x for x in b if x in common]
    so = [x for x in o if x in common]
    st = [x for x in t if x in common]
    if so == st:
        skel = so
    elif so == sb:
        skel = st
    elif st == sb:
        skel = so
    else:
        rec = ctx.conflict("order", entity, name, "", sb[:60], so[:60], st[:60])
        skel = ctx.pick(rec, sb, so, st)
    placed = set(skel)
    kids: dict = {}
    for lst in (o, t):
        prev = None
        for x in lst:
            if x not in keep:
                continue
            if x in placed:
                prev = x
                continue
            placed.add(x)
            kids.setdefault(prev, []).append(x)
            prev = x
    out: list = []

    def emit(parent):
        stack = [iter(kids.get(parent, []))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                stack.pop()
                continue
            out.append(nxt)
            stack.append(iter(kids.get(nxt, [])))

    emit(None)
    for x in skel:
        out.append(x)
        emit(x)
    seen = set(out)
    for x in keep:
        if x not in seen:
            out.append(x)
    return out


def merge_maps(base: EMap, ours: EMap, theirs: EMap, ctx: Ctx) -> dict:
    items: dict = {}
    ids = list(dict.fromkeys(list(ours.items) + [e for e in theirs.items if e not in ours.items] + [e for e in base.items if e not in ours.items and e not in theirs.items]))
    kept_both: list = []
    full: dict = {}
    for eid in ids:
        bf = base.items.get(eid, MISSING)
        of = ours.items.get(eid, MISSING)
        tf = theirs.items.get(eid, MISSING)
        if derived_entity(of) or derived_entity(tf) or derived_entity(bf):
            if of is MISSING and tf == bf or tf is MISSING and of == bf:
                continue
            if of == bf and tf is not MISSING:
                items[eid] = tf
            elif of is not MISSING:
                items[eid] = of
                if tf != bf and tf != of:
                    ctx.rebuild = True
            else:
                items[eid] = tf
            full[eid] = True
            continue
        b = core(eid, bf) if bf is not MISSING else MISSING
        o = core(eid, of) if of is not MISSING else MISSING
        t = core(eid, tf) if tf is not MISSING else MISSING
        name = display(ours, eid) if o is not MISSING else display(theirs, eid) if t is not MISSING else display(base, eid)
        if o == t:
            if o is not MISSING:
                items[eid] = o
                if b is MISSING:
                    ctx.stats["both_same"] += 1
            continue
        if o == b:
            ctx.stats["theirs_only"] += 1
            if t is not MISSING:
                items[eid] = t
            continue
        if t == b:
            ctx.stats["ours_only"] += 1
            if o is not MISSING:
                items[eid] = o
            continue
        if b is MISSING:
            rec = ctx.conflict("both_added", eid, name, "", MISSING, o, t)
            if rec["choice"] == "keep_both" and kind_of(eid) == "entity":
                items[eid] = o
                kept_both.append((eid, t))
            else:
                items[eid] = ctx.pick(rec, MISSING, o, t)
            continue
        if t is MISSING:
            rec = ctx.conflict("edit_delete", eid, name, "", b, o, t)
            v = ctx.pick(rec, b, o, t)
            if v is not MISSING:
                items[eid] = v
            continue
        if o is MISSING:
            rec = ctx.conflict("delete_edit", eid, name, "", b, o, t)
            v = ctx.pick(rec, b, o, t)
            if v is not MISSING:
                items[eid] = v
            continue
        items[eid] = three(b, o, t, ctx, eid, name)
    for eid in list(items):
        if full.get(eid):
            continue
        res = items[eid]
        of = ours.items.get(eid, MISSING)
        tf = theirs.items.get(eid, MISSING)
        if of is not MISSING and res == core(eid, of):
            items[eid] = of
        elif tf is not MISSING and res == core(eid, tf):
            items[eid] = tf
        elif eid.startswith("table:features:") and isinstance(res, dict):
            res = dict(res)
            keep = of if isinstance(of, dict) and "state" in of else tf
            if isinstance(keep, dict) and "state" in keep:
                res["state"] = keep["state"]
            items[eid] = res
            ctx.rebuild = True
        elif eid == "header:PARTTREE" and isinstance(res, dict):
            res = dict(res)
            base_of = of if isinstance(of, dict) else {}
            if "built" in base_of:
                res["built"] = base_of["built"]
            items[eid] = res
            ctx.rebuild = True
    nxt = max(int(ours.meta.get("next_handle") or 0), int(theirs.meta.get("next_handle") or 0), int(base.meta.get("next_handle") or 0))
    new_orders: dict = {}
    for eid, rec in kept_both:
        h = nxt
        nxt += 1
        copy_rec = copy.deepcopy(rec)
        copy_rec["handle"] = h
        new_id = "entity:%d" % h
        items[new_id] = copy_rec
        new_orders.setdefault("order:entities", []).append(new_id)
        ours.names[new_id] = display(theirs, eid) + " (theirs)"
    return {"items": items, "next_handle": nxt, "extra_order": new_orders}


def reference_checks(base: EMap, ours: EMap, theirs: EMap, items: dict, ctx: Ctx) -> list:
    broken = []
    sides = ((ours, theirs, "ours"), (theirs, ours, "theirs"))
    for deleter, other, label in sides:
        gone = {e for e in base.items if e not in deleter.items and e not in items and kind_of(e) == "table"}
        if not gone:
            continue
        by_name: dict = {}
        for e in gone:
            by_name.setdefault(e.split(":", 2)[2], []).append(e)
        for eid, rec in other.items.items():
            if eid not in items or eid in gone or core(eid, base.items.get(eid)) == core(eid, rec):
                continue
            found: set = set()
            scan_strings(rec, found)
            for n in found & set(by_name):
                for d in by_name[n]:
                    if (d, eid) not in [(x[0], x[1]) for x in broken]:
                        broken.append((d, eid, label))
    for d, eid, label in broken:
        rec = ctx.conflict("reference_broken", d, display(base, d), eid, base.items.get(d), None, None)
        rec["ours"] = {"deleted_by": label, "still_used_by": eid, "used_by_name": display(ours, eid) or display(theirs, eid)}
        rec["theirs"] = None
        rec["suggested"] = "accept"
        if rec["choice"] == "restore":
            items[d] = base.items[d]
    return broken


def finish_orders(base: EMap, ours: EMap, theirs: EMap, items: dict, extra: dict, ctx: Ctx) -> dict:
    orders = {}
    keys = list(dict.fromkeys(list(ours.orders) + [k for k in theirs.orders if k not in ours.orders] + [k for k in base.orders if k not in ours.orders and k not in theirs.orders]))
    for k in keys:
        union = set(ours.orders.get(k, ())) | set(theirs.orders.get(k, ())) | set(base.orders.get(k, ()))
        if k == "order:tables":
            keep = set(ours.orders.get(k, ())) | set(theirs.orders.get(k, ()))
        else:
            keep = {e for e in union if e in items}
        orders[k] =merge_order(base.orders.get(k, []), ours.orders.get(k, []), theirs.orders.get(k, []), keep, ctx, k, "order of " + k.split(":", 1)[1])
    for k, extra_ids in extra.items():
        orders.setdefault(k, []).extend(x for x in extra_ids if x not in orders[k])
    return orders


def merge_members(base: dict, ours: dict, theirs: dict, ctx: Ctx) -> dict:
    out = {}
    for name in dict.fromkeys(list(ours) + [n for n in theirs if n not in ours] + [n for n in base if n not in ours and n not in theirs]):
        b, o, t = base.get(name), ours.get(name), theirs.get(name)
        if o == t:
            if o is not None:
                out[name] = o
            continue
        if o == b:
            if t is not None:
                out[name] = t
            continue
        if t == b:
            if o is not None:
                out[name] = o
            continue
        if name.startswith("cache/"):
            if o is not None:
                out[name] = o
            elif t is not None:
                out[name] = t
            continue
        rec = ctx.conflict("blob", "blob:" + name, name, "", {"mode": b[0], "child": b[1].hex()} if b else MISSING, {"mode": o[0], "child": o[1].hex()} if o else MISSING, {"mode": t[0], "child": t[1].hex()} if t else MISSING)
        pick = rec["choice"]
        v = t if pick == "theirs" else b if pick == "base" else o
        if v is not None:
            out[name] = v
    return out
