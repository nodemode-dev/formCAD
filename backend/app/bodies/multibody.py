import copy
import math

from app.bodies import refgeo
from app.doc.kinds.solidbody import SolidBody
from app.solid import ids, work
from app.solid.work import SolidError

OPS = {"add": "Add", "subtract": "Subtract", "common": "Common"}
MAX_COPIES = 500


class BodyError(ValueError):
    pass


def solid(d, handle):
    try:
        e = d.get(int(handle))
    except (TypeError, ValueError):
        e = None
    if e is None or e.kind != "solidbody":
        raise BodyError("There is no solid body with handle %s." % handle)
    return e


def unique_bodies(d, handles) -> list:
    out, seen = [], set()
    for h in handles or []:
        b = solid(d, h)
        if b.handle not in seen:
            seen.add(b.handle)
            out.append(b)
    return out


def guarded(fn, *args):
    try:
        return fn(*args)
    except SolidError as err:
        raise BodyError(str(err))


def part_owner(d, bodies):
    from app.doc.service import service
    from app.part import store

    if not store.has_part(d):
        return None, 0
    body = int(store.tree(d).get("body") or 0)
    if not body or body not in {b.handle for b in bodies}:
        return None, 0
    doc = next((x for x in list(service.docs.values()) if x.drawing is d), None)
    return doc, body


def add_part_feature(doc, type_name, params, label):
    from app.part import tree
    from app.part.registry import PartError

    try:
        return tree.add_feature(doc, type_name, params, {}, label)
    except PartError as err:
        raise BodyError(str(err))


def combine(d, op, handles, keep_tools=False, fuzzy=None, force=False, retry=True) -> dict:
    if op not in OPS:
        raise BodyError("Choose add, subtract or common.")
    bodies = unique_bodies(d, handles)
    if len(bodies) < 2:
        raise BodyError("Combine needs at least two different bodies.")
    doc, owned = part_owner(d, bodies)
    if owned:
        if doc is None or bodies[0].handle != owned:
            raise BodyError("The body of a part with a feature tree must be the first body in Combine, so the tree can record it.")
        out = add_part_feature(doc, "combine_body", {"op": op, "tools": [b.handle for b in bodies[1:]], "force": bool(force)}, None)
        st = out["state"]
        if st.get("status") == "error":
            raise BodyError(st.get("message") or "The combine failed.")
        return {"handle": bodies[0].handle, "name": bodies[0].name, "op": op, "erased": [], "feature": out["id"], "summary": d.get(bodies[0].handle).summary, "diagnostics": {}, "message": "Added %s to the feature tree; the tool bodies are kept so the tree can rebuild it." % out["label"]}
    wids = [guarded(work.worker_id, d, b) for b in bodies]
    s = work.mm(d)
    fuzz = float(fuzzy) if fuzzy is not None else float(d.tolerances["absolute"])
    if not math.isfinite(fuzz) or fuzz < 0:
        raise BodyError("The fuzzy value must be zero or more.")
    res = guarded(work.kcall, "combine", {"op": op, "bodies": wids, "fuzzy": fuzz * s, "force": bool(force), "retry": bool(retry)}, work.LONG)
    inputs = res.get("history", {}).get("inputs", [])
    parts = [(b.face_ids, b.edge_ids, h) for b, h in zip(bodies, inputs)]
    keep = {}
    for b in bodies:
        keep.update(b.lineage)
    target = d.modify(bodies[0].handle)
    names = [b.name for b in bodies]
    guarded(work.apply_result, d, target, res["id"], res["summary"], {"op": "combine", "mode": op, "from": names}, parts, keep)
    erased = []
    if not keep_tools:
        for t in bodies[1:]:
            d.erase_entity(t.handle)
            erased.append(t.handle)
    diag = res.get("diagnostics", {})
    return {"handle": target.handle, "name": target.name, "op": op, "erased": erased, "summary": target.summary, "diagnostics": diag, "message": "%s: %d faces, %d solid(s)%s." % (OPS[op], target.summary.get("faces", 0), target.summary.get("solids", 0), " (retried with fuzzy value %g mm)" % diag["fuzzy"] if diag.get("retried") else "")}


def plane_spec(d, spec, s):
    if isinstance(spec, dict) and "ref" in spec:
        try:
            fr = refgeo.cs_frame(d, spec["ref"])
        except refgeo.RefError as err:
            raise BodyError(str(err))
        return {"origin": [c * s for c in fr["origin"]], "normal": list(fr["z"])}
    if not isinstance(spec, dict) or spec.get("origin") is None or spec.get("normal") is None:
        raise BodyError("A cutting plane needs an origin and a normal, or the name of a plane.")
    try:
        o = [float(v) * s for v in spec["origin"]]
        n = [float(v) for v in spec["normal"]]
    except (TypeError, ValueError):
        raise BodyError("A cutting plane needs numbers.")
    if len(o) != 3 or len(n) != 3 or not all(math.isfinite(v) for v in o + n) or math.sqrt(sum(v * v for v in n)) < 1e-12:
        raise BodyError("A cutting plane needs a three-number origin and a non-zero normal.")
    return {"origin": o, "normal": n}


def claim(piece_ids, taken, d, lineage):
    out = []
    for pid in piece_ids:
        if pid in taken:
            fresh = ids.next_pid(d)
            lineage[str(fresh)] = pid
            out.append(fresh)
        else:
            taken.add(pid)
            out.append(pid)
    return out


def split(d, handle, planes=None, tools=None, keep_tools=True, fuzzy=None, force=False) -> dict:
    body = solid(d, handle)
    s = work.mm(d)
    specs = [plane_spec(d, p, s) for p in (planes or [])]
    tool_bodies = unique_bodies(d, tools)
    if body.handle in {t.handle for t in tool_bodies}:
        raise BodyError("A body cannot split itself.")
    if not specs and not tool_bodies:
        raise BodyError("Give a cutting plane or a surface body to split with.")
    doc, owned = part_owner(d, [body] + tool_bodies)
    if owned:
        if body.handle != owned:
            raise BodyError("The body of a part with a feature tree can be split, but it cannot be a cutting body.")
        out = add_part_feature(doc, "split_body", {"planes": [dict(p) if isinstance(p, dict) else p for p in planes or []], "tools": [t.handle for t in tool_bodies], "keep": 1, "force": bool(force)}, None)
        if out["state"].get("status") == "error":
            raise BodyError(out["state"].get("message") or "The split failed.")
        from app.part import store

        sides = store.tree(d).get("sides") or {}
        mine = [h for k, h in sorted(sides.items(), key=lambda kv: int(kv[0].rsplit(":", 1)[1])) if k.startswith(out["id"] + ":")]
        return {"handles": [owned] + mine, "erased": [], "feature": out["id"], "message": "Added %s to the feature tree: %d pieces; piece 1 stays the part and the others are separate bodies that follow every rebuild." % (out["label"], 1 + len(mine)), "diagnostics": {}}
    wid = guarded(work.worker_id, d, body)
    tool_wids = [guarded(work.worker_id, d, t) for t in tool_bodies]
    fuzz = float(fuzzy) if fuzzy is not None else float(d.tolerances["absolute"])
    res = guarded(work.kcall, "split", {"body": wid, "planes": specs, "tools": tool_wids, "fuzzy": fuzz * s, "force": bool(force)}, work.LONG)
    pieces = res["pieces"]
    old_faces, old_edges, old_lineage = list(body.face_ids), list(body.edge_ids), dict(body.lineage)
    taken_f, taken_e = set(), set()
    source = {"op": "split", "from": body.name}
    made = []
    for i, piece in enumerate(pieces):
        hist = {"faces": piece["faces"], "edges": piece["edges"]}
        lineage = dict(old_lineage)
        faces, edges, lineage = ids.inherit(d, int(piece["summary"]["faces"]), int(piece["summary"]["edges"]), [(old_faces, old_edges, hist)], lineage)
        faces = claim(faces, taken_f, d, lineage)
        edges = claim(edges, taken_e, d, lineage)
        if i == 0:
            target = d.modify(body.handle)
        else:
            target = SolidBody(name="%s (%d)" % (body.name or "Body", i + 1), version=0, rgb=list(body.rgb), layer=body.layer, material=body.material)
        blob = guarded(work.save_shape, d, piece["id"])
        target.blob = blob
        target.version = int(target.version) + 1
        target.face_ids, target.edge_ids, target.lineage = faces, edges, lineage
        target.summary = work.trim_summary(piece["summary"])
        target.source = dict(source, piece=i + 1)
        target.offset = [0.0, 0.0, 0.0]
        target.extent = work.extent_of(d, piece["summary"].get("bbox"))
        work.remember((blob, (0.0, 0.0, 0.0)), piece["id"])
        if i > 0:
            try:
                d.add_entity(target, body.owner)
            except ValueError as err:
                raise BodyError(str(err))
        made.append(target.handle)
    erased = []
    if not keep_tools:
        for t in tool_bodies:
            d.erase_entity(t.handle)
            erased.append(t.handle)
    return {"handles": made, "erased": erased, "message": "Split into %d bodies." % len(made), "diagnostics": res.get("diagnostics", {})}


def scaled(d, params, k):
    s = work.mm(d)
    out = {}
    if params.get("translate") is not None:
        t = params["translate"]
        if not isinstance(t, (list, tuple)) or len(t) != 3:
            raise BodyError("Translate needs three numbers.")
        out["translate"] = [float(v) * s * k for v in t]
    if params.get("rotate") is not None:
        r = params["rotate"]
        if not isinstance(r, dict) or r.get("axis") is None:
            raise BodyError("Rotate needs an axis and degrees.")
        out["rotate"] = {"origin": [float(v) * s for v in (r.get("origin") or [0, 0, 0])], "axis": [float(v) for v in r["axis"]], "degrees": float(r.get("degrees", 0.0)) * k}
    if not out:
        raise BodyError("Give translate, rotate or both.")
    return out


def move(d, handles, params) -> dict:
    bodies = unique_bodies(d, handles)
    if not bodies:
        raise BodyError("Give the bodies to move.")
    scaled(d, params, 1)
    moved = []
    doc, owned = part_owner(d, bodies)
    if owned:
        raw = {k: params.get(k) for k in ("translate", "rotate") if params.get(k) is not None}
        out = add_part_feature(doc, "move_body", raw, None)
        if out["state"].get("status") == "error":
            raise BodyError(out["state"].get("message") or "The move failed.")
        moved.append(owned)
        bodies = [b for b in bodies if b.handle != owned]
    for b in bodies:
        wid = guarded(work.worker_id, d, b)
        res = guarded(work.kcall, "transform", {**scaled(d, params, 1), "id": wid}, work.LONG)
        inputs = res.get("history", {}).get("inputs", [])
        target = d.modify(b.handle)
        guarded(work.apply_result, d, target, res["id"], res["summary"], dict(b.source, moved=True), [(b.face_ids, b.edge_ids, inputs[0] if inputs else {})], b.lineage)
        moved.append(target.handle)
    return {"handles": moved, "message": "Moved %d bodies." % len(moved)}


def copy_bodies(d, handles, params, count=1) -> dict:
    bodies = unique_bodies(d, handles)
    if not bodies:
        raise BodyError("Give the bodies to copy.")
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise BodyError("The number of copies must be a whole number.")
    if not 1 <= count <= MAX_COPIES:
        raise BodyError("Make between 1 and %d copies." % MAX_COPIES)
    made = []
    doc, owned = part_owner(d, bodies)
    if owned:
        scaled(d, params, 1)
        raw = {k: params.get(k) for k in ("translate", "rotate") if params.get(k) is not None}
        out = add_part_feature(doc, "copy_body", dict(raw, count=count), None)
        if out["state"].get("status") == "error":
            raise BodyError(out["state"].get("message") or "The copy failed.")
        from app.part import store

        sides = store.tree(d).get("sides") or {}
        made.extend(h for k, h in sorted(sides.items(), key=lambda kv: int(kv[0].rsplit(":", 1)[1])) if k.startswith(out["id"] + ":"))
        bodies = [b for b in bodies if b.handle != owned]
    for b in bodies:
        wid = guarded(work.worker_id, d, b)
        for k in range(1, count + 1):
            res = guarded(work.kcall, "transform", {**scaled(d, params, k), "id": wid}, work.LONG)
            name = "%s copy" % (b.name or "Body") if count == 1 else "%s copy %d" % (b.name or "Body", k)
            nb = guarded(work.new_body, d, res["id"], res["summary"], name, {"op": "copy", "from": b.name}, b.rgb)
            nb.layer = b.layer
            nb.material = b.material
            try:
                d.add_entity(nb, b.owner)
            except ValueError as err:
                raise BodyError(str(err))
            made.append(nb.handle)
    return {"handles": made, "message": "Copied to %d new bodies." % len(made)}


def describe(d) -> list:
    out = []
    for e in d.ordered_entities():
        if e.kind != "solidbody":
            continue
        out.append({"handle": e.handle, "name": e.name, "material": e.material or None, "summary": copy.deepcopy(e.summary), "visible": bool(d.visible(e)), "source": e.source})
    return out
