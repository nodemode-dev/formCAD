import importlib

from app.doc import layerops


class _Lazy:
    def __getattr__(self, name):
        return getattr(importlib.import_module("app.doc.viewports"), name)


VP = _Lazy()


def _all(d) -> list:
    return [e for e in d.ents.values() if e.kind == "viewport"]


def _usage(d) -> dict:
    out = {}
    for vp in _all(d):
        for n in vp.frozen:
            key = str(n).casefold()
            out[key] = out.get(key, 0) + 1
        for key in vp.overrides:
            out[key] = out.get(key, 0) + 1
    return out


def _info(d, handle: int) -> dict:
    vp = d.get(handle)
    if vp is None or vp.kind != "viewport":
        return {}
    out = {}
    for rec in d.tables["layers"].values():
        name = rec["name"]
        ov = VP.override_of(vp, name)
        row = {"vp_freeze": VP.is_frozen(vp, name)}
        for key in VP.OVERRIDE_KEYS:
            row["vp_" + key] = ov.get(key)
        out[name.casefold()] = row
    return out


def _set(d, handle: int, layer: str, props: dict) -> None:
    vp = d.get(handle)
    if vp is None or vp.kind != "viewport":
        raise layerops.LayerError("No such viewport.")
    vp = d.modify(handle)
    for key, value in props.items():
        if key == "freeze":
            if value:
                VP.freeze(vp, layer)
            else:
                VP.thaw(vp, layer)
        elif key == "vp_freeze":
            _set(d, handle, layer, {"freeze": value})
        elif key == "clear":
            VP.clear_overrides(vp, layer)
        else:
            name = key[3:] if key.startswith("vp_") else key
            if name not in VP.OVERRIDE_KEYS:
                raise layerops.LayerError("Unknown viewport property %s." % key)
            VP.set_override(vp, layer, name, value)


def _rename(d, old: str, new: str) -> int:
    n = 0
    okey = old.casefold()
    for vp in _all(d):
        touched = False
        if any(str(x).casefold() == okey for x in vp.frozen):
            ent = d.modify(vp.handle)
            ent.frozen = [new if str(x).casefold() == okey else x for x in ent.frozen]
            touched = True
        if okey in vp.overrides:
            ent = d.modify(vp.handle)
            cur = dict(ent.overrides)
            rec = dict(cur.pop(okey))
            rec["name"] = new
            cur[new.casefold()] = rec
            ent.overrides = cur
            touched = True
        n += 1 if touched else 0
    return n


def _delete(d, name: str) -> None:
    key = name.casefold()
    for vp in _all(d):
        if any(str(x).casefold() == key for x in vp.frozen) or key in vp.overrides:
            ent = d.modify(vp.handle)
            ent.frozen = [x for x in ent.frozen if str(x).casefold() != key]
            cur = dict(ent.overrides)
            cur.pop(key, None)
            ent.overrides = cur


def _merge(d, source: str, target: str) -> None:
    skey, tkey = source.casefold(), target.casefold()
    for vp in _all(d):
        frozen = any(str(x).casefold() == skey for x in vp.frozen)
        if not frozen and skey not in vp.overrides:
            continue
        ent = d.modify(vp.handle)
        if frozen and not VP.is_frozen(ent, target):
            VP.freeze(ent, target)
        cur = dict(ent.overrides)
        rec = cur.get(skey)
        if rec is not None and tkey not in cur:
            moved = dict(rec)
            moved["name"] = target
            cur[tkey] = moved
        ent.overrides = cur


layerops.USAGE_HOOKS.append(_usage)
layerops.VIEWPORT_INFO.append(_info)
layerops.VIEWPORT_SET.append(_set)
layerops.RENAME_HOOKS.append(_rename)
layerops.DELETE_HOOKS.append(_delete)
layerops.MERGE_HOOKS.append(_merge)
