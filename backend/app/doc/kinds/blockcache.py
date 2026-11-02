from app.doc import commit_hooks

PRIORITY = 95
EPS = 1e-9


def _same_box(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return len(a) == len(b) and all(abs(x - y) <= EPS for x, y in zip(a, b))


def _same_rows(a, b) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x["vis"] != y["vis"] or bool(x["lock_position"]) != bool(y["lock_position"]):
            return False
        if (x["at"] is None) != (y["at"] is None):
            return False
        if x["at"] is not None and not _same_box(x["at"], y["at"]):
            return False
    return True


def users_of(d) -> dict:
    from app.doc import blockdefs

    out = {}
    for rec in d.tables["blocks"].values():
        for used in blockdefs.uses(d, rec["name"]):
            out.setdefault(used, set()).add(rec["name"].casefold())
    return out


def closure(d, names: set) -> set:
    users = users_of(d)
    seen = set(names)
    stack = list(names)
    while stack:
        cur = stack.pop()
        for up in users.get(cur, ()):
            if up not in seen:
                seen.add(up)
                stack.append(up)
    return seen


def refresh_insert(d, handle: int) -> bool:
    from app.doc import attribs, blockdefs

    e = d.ents.get(handle)
    if e is None or e.kind != "insert":
        return False
    box = blockdefs.insert_bounds(d, e)
    box = [float(v) for v in box] if box is not None else None
    rows = attribs.cache_rows(d, e)
    if _same_box(e.extra.get("box"), box) and _same_rows(attribs.cache_current(e), rows):
        return False
    live = d.modify(handle)
    extra = dict(live.extra)
    if box is not None:
        extra["box"] = box
    else:
        extra.pop("box", None)
    live.extra = extra
    for att, row in zip(live.attributes or [], rows):
        att.update(row)
    return True


def refresh_all(d) -> int:
    from app.doc import blockdefs

    n = 0
    for e in list(blockdefs.all_inserts(d)):
        if refresh_insert(d, e.handle):
            n += 1
    return n


def follow(doc, tx) -> None:
    from app.doc import blockdefs

    d = doc.drawing
    todo = set()
    blocks = set()
    for k in tx.before:
        kind = k[0]
        if kind == "e":
            e = d.ents.get(k[1])
            if e is None:
                continue
            if e.kind == "insert":
                todo.add(e.handle)
            if e.owner.startswith("block:"):
                blocks.add(e.owner[6:].casefold())
        elif kind == "s" and k[1].startswith("block:"):
            blocks.add(k[1][6:].casefold())
        elif kind == "t" and k[1] == "blocks":
            blocks.add(k[2])
    if blocks:
        wide = closure(d, blocks)
        for e in blockdefs.all_inserts(d):
            if str(e.block).casefold() in wide:
                todo.add(e.handle)
    for h in todo:
        refresh_insert(d, h)


commit_hooks.register(PRIORITY, follow)
