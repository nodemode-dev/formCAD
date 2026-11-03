import json
import urllib.parse

from app.part import rebuild, registry, store, tree
from app.part.registry import PartError
from app.services import kernel
from app.solid import scene as scene_mod


class Discard(list):
    def append(self, item):
        return None


def isolated_cache(doc):
    real = rebuild.sync_cache(doc)
    shadow = rebuild.Cache()
    shadow.entries = dict(real.entries)
    shadow.serial = real.serial
    shadow.applied = getattr(real, "applied", None)
    shadow.sides = dict(real.sides)
    shadow.trash = Discard()
    return real, shadow


def free_new(real, shadow):
    ids = []
    for fid, e in shadow.entries.items():
        if real.entries.get(fid) is e:
            continue
        if e.owns and e.wid:
            ids.append(e.wid)
        if e.tool:
            ids.append(e.tool)
        ids.extend(x["wid"] for x in e.extras)
    if ids:
        try:
            kernel.call("shape_free", {"ids": ids}, 10.0)
        except Exception:
            pass


def info_of(doc, fid):
    rec = store.get(doc.drawing, fid)
    st = (rec or {}).get("state") or {}
    return {"id": fid, "status": st.get("status", "stale"), "message": st.get("message", ""), "warnings": st.get("warnings", []), "failed": st.get("failed", {})}


def at(doc, fid, detail=1.0):
    tree.need(doc, fid)
    with doc.transaction("REBUILD"):
        rebuild.ensure_built(doc)
    real, shadow = isolated_cache(doc)
    doc.part_cache = shadow
    doc.begin("SCENEAT")
    try:
        tree.set_rollback(doc, fid)
        payload = scene_mod.build(doc, 0, detail)
    finally:
        doc.rollback()
        doc.part_cache = real
        free_new(real, shadow)
    return payload


def run(doc, type_name, fid, params, refs, after, detail=1.0, hold=None):
    if fid is None and not type_name:
        raise PartError("A preview needs a feature type or a feature id.")
    if fid is not None:
        tree.need(doc, fid)
    with doc.transaction("REBUILD"):
        rebuild.ensure_built(doc)
    real, shadow = isolated_cache(doc)
    doc.part_cache = shadow
    doc.begin("PREVIEW")
    try:
        if fid is not None:
            tree.edit_feature(doc, fid, None, params or None, refs or None, None)
            target = fid
        else:
            registry.get(type_name)
            made = tree.add_feature(doc, type_name, params or {}, refs or {}, None, after, False)
            target = made["id"]
        info = info_of(doc, target)
        if hold:
            tree.need(doc, hold)
            tree.set_rollback(doc, hold)
        payload = scene_mod.build(doc, 0, detail)
    finally:
        doc.rollback()
        doc.part_cache = real
        free_new(real, shadow)
    return payload, info


def header(info) -> str:
    return urllib.parse.quote(json.dumps(info, separators=(",", ":")))
