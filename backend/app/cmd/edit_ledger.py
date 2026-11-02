from app.doc.entities import entity_from_dict


def new() -> dict:
    return {"mod": {}, "new": [], "gone": []}


def touch(ctx, led: dict, ent) -> None:
    if ent.handle not in led["mod"] and ent.handle not in led["new"]:
        led["mod"][ent.handle] = ent.to_dict()
    ctx.d.modify(ent.handle)


def made(led: dict, handle: int) -> int:
    led["new"].append(handle)
    return handle


def drop(ctx, led: dict, ent) -> None:
    if ent.handle in led["new"]:
        led["new"].remove(ent.handle)
    else:
        led["gone"].append(led["mod"].pop(ent.handle, None) or ent.to_dict())
    ctx.d.erase_entity(ent.handle)


def rollback(ctx, led: dict) -> None:
    d = ctx.d
    for h in led["new"]:
        d.erase_entity(h)
    for data in led["gone"]:
        ent = entity_from_dict(data)
        if ent.handle not in d.ents:
            d.restore_entity(ent)
    for h, data in led["mod"].items():
        if h in d.ents:
            d.modify(h)
            d.ents[h] = entity_from_dict(data)


def empty(led: dict) -> bool:
    return not (led["mod"] or led["new"] or led["gone"])
