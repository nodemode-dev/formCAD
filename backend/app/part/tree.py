import copy

from app.param import sketch as K
from app.param import store as S
from app.param import units as U
from app.part import features_bodies, features_core, features_shapes, names, rebuild, registry, store
from app.part.registry import PartError
from app.sheetmetal import features as sheet_features
from app.solid import work

MAX_FEATURES = 5000
LABEL_MAX = 80


def d_of(doc):
    return doc.drawing


def children_map(d, t=None):
    t = t or store.tree(d)
    recs = store.records(d)
    out = {f: [] for f in t["order"]}
    for fid in t["order"]:
        rec = recs.get(fid)
        if rec is None:
            continue
        for p in rebuild.parents_of(rec, recs):
            out.setdefault(p, []).append(fid)
    return out


def descendants(d, fid, t=None):
    kids = children_map(d, t)
    seen, stack = [], list(kids.get(fid, []))
    while stack:
        f = stack.pop()
        if f not in seen:
            seen.append(f)
            stack.extend(kids.get(f, []))
    return seen


def describe(d, rec, t, kids=None, recs=None):
    recs = recs or store.records(d)
    kids = kids if kids is not None else children_map(d, t)
    ft = registry.TYPES.get(rec["type"])
    order = t["order"]
    return {
        "id": rec["id"], "type": rec["type"], "label": rec["label"], "group": ft.group if ft else "", "index": order.index(rec["id"]) if rec["id"] in order else -1,
        "suppressed": bool(rec.get("suppressed")), "params": rec.get("params") or {}, "refs": rec.get("refs") or {}, "state": rec.get("state") or store.blank_state(),
        "parents": rebuild.parents_of(rec, recs), "children": kids.get(rec["id"], []), "rolled": bool(t.get("rollback") and t["rollback"] in order and order.index(rec["id"]) > order.index(t["rollback"])),
    }


def listing(doc) -> dict:
    d = d_of(doc)
    t = store.tree(d)
    recs = store.records(d)
    kids = children_map(d, t)
    return {"workspace": t["workspace"], "rollback": t["rollback"], "auto": t["auto"], "body": t["body"], "built": t["built"], "features": [describe(d, recs[f], t, kids, recs) for f in t["order"] if f in recs], "rev": doc.rev}


def get_feature(doc, fid):
    d = d_of(doc)
    t = store.tree(d)
    rec = store.get(d, fid)
    if rec is None:
        raise PartError("There is no feature %s." % fid)
    return describe(d, rec, t)


def need(doc, fid):
    rec = store.get(doc.drawing, fid)
    if rec is None:
        raise PartError("There is no feature %s." % fid)
    return rec


def context_entry(doc, before_fid):
    d = d_of(doc)
    t = store.tree(d)
    rebuild.ensure_built(doc)
    cache = rebuild.cache_of(doc)
    order = t["order"]
    ids = order[: order.index(before_fid) + 1] if before_fid in order else list(order)
    for f in reversed(ids):
        e = cache.entries.get(f)
        if e is not None and not e.error:
            return f, e
    return None, None


def inverse_names(t):
    return {pid: key for key, pid in t["names"].items()}


def make_ref(doc, kind, raw, ctx_fid):
    d = d_of(doc)
    t = store.tree(d)
    if isinstance(raw, str):
        raw = {"id": raw} if kind in ("feature", "sketch") else {"key": raw}
    if not isinstance(raw, dict):
        raise PartError("A reference is an object.")
    if kind in ("feature", "sketch"):
        fid = raw.get("id") or raw.get("feature")
        if not fid or store.get(d, fid) is None:
            raise PartError("There is no feature %s." % fid)
        return {"kind": "feature", "id": fid}
    if kind == "plane":
        out = copy.deepcopy(raw)
        out["kind"] = "plane"
        return out
    if kind == "vertex":
        if raw.get("sig") and raw["sig"].get("p"):
            return {"kind": "vertex", "sig": raw["sig"], "ctx": ctx_fid}
        p = raw.get("p")
        if p is not None:
            s = U.mm_per_unit(d)
            return {"kind": "vertex", "sig": {"p": [float(v) * s for v in p]}, "ctx": ctx_fid}
        _f, entry = context_entry(doc, ctx_fid)
        if entry is None or raw.get("index") is None:
            raise PartError("Give a vertex position.")
        got = work.kcall("feat_signatures", {"id": entry.wid, "vertices": [int(raw["index"])]}, work.SHORT)["vertices"]
        return {"kind": "vertex", "sig": got[str(int(raw["index"]))], "ctx": ctx_fid}
    tag = "faces" if kind == "face" else "edges"
    if raw.get("key") and raw.get("sig") and raw.get("kind") == kind:
        out = copy.deepcopy(raw)
        out.setdefault("ctx", ctx_fid)
        return out
    key = raw.get("key")
    if not key and raw.get("pid") is not None:
        key = inverse_names(t).get(int(raw["pid"]))
        if not key:
            raise PartError("The persistent id %s is not known to this part." % raw["pid"])
    if not key and raw.get("feature") and raw.get("role"):
        key = "%s:%s" % (raw["feature"], raw["role"])
    fid, entry = context_entry(doc, ctx_fid)
    if entry is None or entry.wid is None:
        raise PartError("There is no body yet to pick %s from." % ("a face" if kind == "face" else "an edge"))
    keys = entry.faces if tag == "faces" else entry.edges
    if not key and raw.get("index") is not None:
        i = int(raw["index"])
        if not 0 <= i < len(keys):
            raise PartError("There is no %s %d." % (kind, i))
        key = keys[i]
    if not key:
        raise PartError("A %s reference needs pid, key, index or feature and role." % kind)
    if key not in keys:
        raise PartError("That %s does not exist at this point in the tree. Roll the bar back or pick it on the state before the new feature." % kind)
    idx = keys.index(key)
    sig = work.kcall("feat_signatures", {"id": entry.wid, tag: [idx]}, work.SHORT)[tag][str(idx)]
    pid = t["names"].get(key)
    return {"kind": kind, "key": key, "ctx": fid, "sig": sig, "pid": pid}


def normalize_refs(doc, ft, refs, ctx_fid):
    out = {}
    for slot, raw in (refs or {}).items():
        spec = ft.slot(slot)
        if spec is None:
            raise PartError("%s has no reference slot %s." % (ft.label, slot))
        if raw is None:
            continue
        items = raw if isinstance(raw, list) else [raw]
        made = [make_ref(doc, spec.kind, it, ctx_fid) for it in items]
        if not spec.multi and len(made) > 1:
            raise PartError("%s takes one reference in %s." % (ft.label, slot))
        out[slot] = made if spec.multi else made[0]
    return out


def check_params(ft, params):
    allowed = {p.name for p in ft.params}
    bad = [k for k in (params or {}) if k not in allowed]
    if bad:
        raise PartError("%s has no parameter %s." % (ft.label, ", ".join(bad)))


def default_label(d, ft):
    n = 1
    have = {r["label"] for r in store.records(d).values()}
    while "%s%d" % (ft.label, n) in have:
        n += 1
    return "%s%d" % (ft.label, n)


def check_label(d, label, ignore=""):
    label = str(label or "").strip()
    if not label or len(label) > LABEL_MAX or any(c in label for c in "\n\r\t"):
        raise PartError("A feature name holds 1 to %d characters on one line." % LABEL_MAX)
    for r in store.records(d).values():
        if r["id"] != ignore and r["label"].casefold() == label.casefold():
            raise PartError("A feature named %s already exists." % label)
    return label


def mark_stale(doc):
    d = d_of(doc)
    for rec in list(store.records(d).values()):
        st = rec.get("state") or {}
        if st.get("status") not in ("stale", "suppressed"):
            q = copy.deepcopy(rec)
            q["state"] = {**store.blank_state(), **st, "status": "stale"}
            store.put(d, q)


def after_edit(doc, start=None):
    d = d_of(doc)
    t = store.tree(d)
    if t["auto"]:
        return rebuild.rebuild(doc, start=start)
    mark_stale(doc)
    return {"rebuilt": [], "reused": [], "errors": [], "ms": 0.0, "stale": True}


def add_feature(doc, type_name, params=None, refs=None, label=None, after=None, suppressed=False):
    d = d_of(doc)
    ft = registry.get(type_name)
    t = store.tree(d)
    if len(t["order"]) >= MAX_FEATURES:
        raise PartError("The part holds the most features it can.")
    check_params(ft, params)
    if after is None:
        after = t["rollback"] if t["rollback"] in t["order"] else (t["order"][-1] if t["order"] else "")
    if after and after not in t["order"]:
        raise PartError("There is no feature %s to insert after." % after)
    pos = t["order"].index(after) + 1 if after else 0
    made = normalize_refs(doc, ft, refs, after or None)
    t = store.tree(d)
    fid = store.new_id(t)
    values = {p.name: copy.deepcopy(p.default) for p in ft.params}
    values.update(copy.deepcopy(params or {}))
    name = check_label(d, label) if label else default_label(d, ft)
    rec = {"name": fid, "id": fid, "type": ft.type, "label": name, "params": values, "refs": made, "suppressed": bool(suppressed), "state": store.blank_state()}
    t["order"].insert(pos, fid)
    if t["rollback"] and after == t["rollback"]:
        t["rollback"] = fid
    if t["workspace"] != "part":
        t["workspace"] = "part"
    store.put(d, rec)
    store.save_tree(d, t)
    report = after_edit(doc, start=fid)
    out = get_feature(doc, fid)
    out["report"] = report
    return out


def edit_feature(doc, fid, label=None, params=None, refs=None, suppressed=None):
    d = d_of(doc)
    rec = copy.deepcopy(need(doc, fid))
    ft = registry.get(rec["type"])
    t = store.tree(d)
    if label is not None:
        rec["label"] = check_label(d, label, fid)
    if params is not None:
        check_params(ft, params)
        rec["params"] = {**(rec.get("params") or {}), **copy.deepcopy(params)}
    if refs is not None:
        i = t["order"].index(fid)
        ctx = t["order"][i - 1] if i > 0 else None
        merged = dict(rec.get("refs") or {})
        fresh = normalize_refs(doc, ft, refs, ctx)
        for slot in refs:
            if refs[slot] is None:
                merged.pop(slot, None)
        merged.update(fresh)
        rec["refs"] = merged
    if suppressed is not None:
        rec["suppressed"] = bool(suppressed)
    store.put(d, rec)
    report = after_edit(doc, start=fid)
    out = get_feature(doc, fid)
    out["report"] = report
    return out


def delete_feature(doc, fid, cascade=False, with_sketch=False):
    d = d_of(doc)
    need(doc, fid)
    t = store.tree(d)
    kids = descendants(d, fid, t)
    if kids and not cascade:
        raise PartError("%s is used by %s; delete those too or edit them first." % (need(doc, fid)["label"], ", ".join(store.get(d, k)["label"] for k in kids)))
    gone = [fid] + kids
    if with_sketch:
        for g in list(gone):
            for ref in rebuild.flat_refs(need(doc, g)):
                if ref[1].get("kind") == "feature":
                    other = store.get(d, ref[1]["id"])
                    if other is not None and other["type"] == "sketch" and other["id"] not in gone:
                        users = [k for k in children_map(d, t).get(other["id"], []) if k not in gone]
                        if not users:
                            gone.append(other["id"])
    cache = rebuild.cache_of(doc)
    sketches = []
    for g in gone:
        rec = store.get(d, g)
        if rec["type"] == "sketch":
            sketches.append(rec["params"].get("sketch"))
        store.drop(d, g)
        rebuild.drop_entry(cache, g)
    t["order"] = [f for f in t["order"] if f not in gone]
    if t["rollback"] in gone:
        i = max([i for i, f in enumerate(t["order"])] or [-1])
        t["rollback"] = None
    t["names"] = {k: v for k, v in t["names"].items() if not set(rebuild.FEATURE_ID.findall(k)) & set(gone)}
    store.save_tree(d, t)
    for name in sketches:
        if name and S.get_sketch(d, name) is not None and not any(r["type"] == "sketch" and r["params"].get("sketch") == name for r in store.records(d).values()):
            try:
                K.delete(d, name)
            except S.ParamError:
                pass
    report = after_edit(doc, start=t["order"][0] if t["order"] else None)
    return {"deleted": gone, "report": report}


def set_suppressed(doc, fid, flag):
    return edit_feature(doc, fid, suppressed=bool(flag))


def set_rollback(doc, to):
    d = d_of(doc)
    t = store.tree(d)
    if to is not None and to not in t["order"]:
        raise PartError("There is no feature %s." % to)
    if to == (t["order"][-1] if t["order"] else None):
        to = None
    t["rollback"] = to
    store.save_tree(d, t)
    report = rebuild.rebuild(doc)
    return {"rollback": to, "report": report}


def can_move(d, fid, after, t=None):
    t = t or store.tree(d)
    order = [f for f in t["order"] if f != fid]
    pos = order.index(after) + 1 if after else 0
    recs = store.records(d)
    rec = recs[fid]
    for p in rebuild.parents_of(rec, recs):
        if p in order and order.index(p) >= pos:
            return "%s depends on %s, which would come after it." % (rec["label"], recs[p]["label"])
    for c in children_map(d, t).get(fid, []):
        if c in order and order.index(c) < pos:
            return "%s uses %s, so it must stay after it." % (recs[c]["label"], rec["label"])
    return ""


def reorder(doc, fid, after):
    d = d_of(doc)
    need(doc, fid)
    t = store.tree(d)
    if after is not None and after != "" and (after not in t["order"] or after == fid):
        raise PartError("There is no feature %s to move after." % after)
    why = can_move(d, fid, after or "", t)
    if why:
        raise PartError(why)
    order = [f for f in t["order"] if f != fid]
    pos = order.index(after) + 1 if after else 0
    order.insert(pos, fid)
    t["order"] = order
    store.save_tree(d, t)
    report = after_edit(doc, start=order[0])
    return {"order": order, "report": report}


def set_workspace(doc, ws):
    d = d_of(doc)
    if ws not in ("part", "drafting"):
        raise PartError("The workspace is part or drafting.")
    t = store.tree(d)
    t["workspace"] = ws
    store.save_tree(d, t)
    if ws == "drafting":
        doc.current_space = "model"
    return {"workspace": ws}


def set_auto(doc, flag):
    d = d_of(doc)
    t = store.tree(d)
    t["auto"] = bool(flag)
    store.save_tree(d, t)
    return {"auto": bool(flag)}


def move_to_space(d, handles, space):
    d.ensure_space(space)
    for h in handles:
        ent = d.modify(int(h))
        old = ent.owner
        if old == space:
            continue
        d._rec_space(old)
        d._rec_space(space)
        if int(h) in d.spaces.get(old, []):
            d.spaces[old].remove(int(h))
        d.spaces[space].append(int(h))
        ent.owner = space


def sketch_space(name):
    return "sketch:" + name


def create_sketch(doc, name=None, plane="XY", offset=0.0, face=None, origin=None, xdir=None, after=None, entities=(), source=None):
    d = d_of(doc)
    if not name:
        n = 1
        while S.get_sketch(d, "Sketch%d" % n) is not None:
            n += 1
        name = "Sketch%d" % n
    params = {"sketch": name, "plane": plane, "offset": offset}
    refs = {}
    plane_rec = plane
    if face is not None:
        params["plane"] = "face"
        t = store.tree(d)
        ctx = after if after is not None else (t["rollback"] or (t["order"][-1] if t["order"] else None))
        refs["face"] = face
        ref = make_ref(doc, "face", face, ctx)
        sg = ref["sig"]
        if sg.get("k") != features_core.PLANE_KIND:
            raise PartError("A sketch can only be placed on a flat face.")
        s = U.mm_per_unit(d)
        n = sg["n"]
        c = [v / s for v in features_core.project([0.0, 0.0, 0.0], sg["c"], n)]
        if origin is None:
            origin = c
        if xdir is None:
            x = features_core.planes.on_face(sg["c"], n)["x"]
            xdir = list(x)
        params["origin"] = [float(v) for v in origin]
        params["xdir"] = [float(v) for v in xdir]
        plane_rec = {"name": "Face", "origin": [float(v) for v in origin], "x": [float(v) for v in xdir], "normal": [float(v) for v in n]}
        refs["face"] = ref
    elif source is not None:
        params["plane"] = "source"
        refs["plane"] = source
        plane_rec = {"name": "Reference", "origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]}
    elif plane not in K.PLANES:
        raise PartError("The plane is XY, XZ or YZ, or give a face.")
    space = sketch_space(name)
    K.create(d, name, plane_rec, ())
    rec = copy.deepcopy(S.get_sketch(d, name))
    rec["space"] = space
    S.put_sketch(d, rec)
    d.ensure_space(space)
    if entities:
        move_to_space(d, entities, space)
        K.add_entities(d, name, entities)
    return add_feature(doc, "sketch", params, refs, name, after)


def sketch_enter(doc, fid):
    d = d_of(doc)
    rec = need(doc, fid)
    if rec["type"] != "sketch":
        raise PartError("%s is not a sketch feature." % rec["label"])
    name = rec["params"].get("sketch")
    sk = S.get_sketch(d, name)
    if sk is None:
        raise PartError("The sketch %s is missing." % name)
    space = sk.get("space") or sketch_space(name)
    d.ensure_space(space)
    doc.current_space = space
    return {"sketch": name, "space": space, "feature": fid}


def sketch_exit(doc):
    d = d_of(doc)
    space = doc.current_space
    attached = []
    if isinstance(space, str) and space.startswith("sketch:"):
        name = space[len("sketch:"):]
        sk = S.get_sketch(d, name)
        if sk is not None:
            have = set(sk["entities"])
            attached = [h for h in d.spaces.get(space, []) if h not in have and h in d.ents]
            if attached:
                K.add_entities(d, name, attached)
    doc.current_space = "model"
    return {"space": "model", "attached": attached}


def add_sketch_entities(doc, fid, handles):
    d = d_of(doc)
    rec = need(doc, fid)
    name = rec["params"].get("sketch")
    sk = S.get_sketch(d, name)
    if sk is None:
        raise PartError("The sketch %s is missing." % name)
    move_to_space(d, handles, sk.get("space") or sketch_space(name))
    K.add_entities(d, name, handles)
    return after_edit(doc, start=fid)
