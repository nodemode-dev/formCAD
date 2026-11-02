import math
import os
import tempfile
import threading
from collections import OrderedDict

from app.doc.kinds.solidbody import SolidBody
from app.param.units import mm_per_unit
from app.services import kernel
from app.solid import blobs, ids

LOADED_LIMIT = 96
SHORT = 60.0
LONG = 300.0
_lock = threading.RLock()
_loaded: OrderedDict = OrderedDict()
_seen = [0]


class SolidError(Exception):
    pass


def kcall(method: str, params: dict | None = None, timeout: float = SHORT):
    try:
        return kernel.call(method, params, timeout)
    except kernel.KernelError as err:
        raise SolidError(str(err))


def mm(d) -> float:
    return mm_per_unit(d)


def reset_if_restarted() -> int:
    serial = kernel.serial()
    if serial == 0:
        raise SolidError(kernel.status().get("message") or "No kernel is installed.")
    if serial != _seen[0]:
        _loaded.clear()
        _seen[0] = serial
    return serial


def remember(key, wid) -> None:
    _loaded[key] = wid
    _loaded.move_to_end(key)
    while len(_loaded) > LOADED_LIMIT:
        _old, old_wid = _loaded.popitem(last=False)
        try:
            kernel.call("shape_free", {"ids": [old_wid]}, 10.0)
        except kernel.KernelError:
            pass


def load_blob(d, blob: str) -> str:
    data = blobs.get_part(d, blob)
    with tempfile.TemporaryDirectory(prefix="fcshape_") as tmp:
        path = os.path.join(tmp, "in.brep")
        with open(path, "wb") as fh:
            fh.write(data)
        res = kcall("shape_load", {"path": path}, LONG)
    return res["id"]


def worker_id(d, body) -> str:
    with _lock:
        reset_if_restarted()
        scale = mm(d)
        off = tuple(round(v * scale, 9) for v in body.offset)
        key = (body.blob, off)
        got = _loaded.get(key)
        if got:
            _loaded.move_to_end(key)
            return got
        base_key = (body.blob, (0.0, 0.0, 0.0))
        base = _loaded.get(base_key)
        if base is None:
            base = load_blob(d, body.blob)
            remember(base_key, base)
        if off == (0.0, 0.0, 0.0):
            return base
        moved = kcall("transform", {"id": base, "translate": list(off)}, LONG)["id"]
        remember(key, moved)
        return moved


def save_shape(d, wid: str) -> str:
    with tempfile.TemporaryDirectory(prefix="fcshape_") as tmp:
        path = os.path.join(tmp, "out.brep")
        kcall("shape_save", {"id": wid, "path": path}, LONG)
        with open(path, "rb") as fh:
            data = fh.read(blobs.MAX_BLOB + 1)
    try:
        return blobs.put_part(d, data)
    except ValueError as err:
        raise SolidError(str(err))


def extent_of(d, bbox) -> list:
    if not bbox:
        return []
    s = mm(d)
    return [bbox[0] / s, bbox[1] / s, bbox[3] / s, bbox[4] / s]


def trim_summary(summary: dict) -> dict:
    return {k: summary.get(k) for k in ("solids", "shells", "faces", "edges", "vertices", "valid", "closed", "bbox")}


def apply_result(d, body, wid, summary, source, history_parts=None, keep_lineage=None) -> None:
    blob = save_shape(d, wid)
    nf, ne = int(summary["faces"]), int(summary["edges"])
    if history_parts:
        faces, edges, lineage = ids.inherit(d, nf, ne, history_parts, keep_lineage)
    else:
        faces, edges = ids.fresh(d, nf, ne)
        lineage = {}
    body.blob = blob
    body.version = int(body.version) + 1
    body.face_ids = faces
    body.edge_ids = edges
    body.lineage = lineage
    body.summary = trim_summary(summary)
    body.source = source
    body.offset = [0.0, 0.0, 0.0]
    body.extent = extent_of(d, summary.get("bbox"))
    with _lock:
        remember((blob, (0.0, 0.0, 0.0)), wid)


def new_body(d, wid, summary, name, source, rgb=None, history_parts=None) -> SolidBody:
    body = SolidBody(name=name, source=source, version=0, rgb=list(rgb or []))
    apply_result(d, body, wid, summary, source, history_parts)
    return body


def unit_params(d, params: dict) -> dict:
    s = mm(d)
    out = dict(params)
    for key in ("dx", "dy", "dz", "radius", "radius1", "radius2", "height", "major", "minor"):
        if key in out and out[key] is not None:
            out[key] = float(out[key]) * s
    if out.get("origin") is not None:
        o = out["origin"]
        out["origin"] = [float(o[0]) * s, float(o[1]) * s, (float(o[2]) if len(o) > 2 else 0.0) * s]
    return out


def create_primitive(ctx, params: dict, name: str):
    d = ctx.d
    res = kcall("primitive", unit_params(d, params), SHORT)
    body = new_body(d, res["id"], res["summary"], name, {"op": params.get("kind", "primitive")})
    ctx.add(body)
    return body


def boolean(ctx, op: str, base, tools: list):
    d = ctx.d
    base_wid = worker_id(d, base)
    tool_wids = [worker_id(d, t) for t in tools]
    res = kcall("boolean", {"op": op, "base": base_wid, "tools": tool_wids}, LONG)
    inputs = res.get("history", {}).get("inputs", [])
    sources = [base] + list(tools)
    parts = []
    for body, hist in zip(sources, inputs):
        parts.append((body.face_ids, body.edge_ids, hist))
    keep = dict(base.lineage)
    for t in tools:
        keep.update(t.lineage)
    target = d.modify(base.handle)
    apply_result(d, target, res["id"], res["summary"], {"op": op, "from": [base.name] + [t.name for t in tools]}, parts, keep)
    for t in tools:
        d.erase_entity(t.handle)
    return target


def profile_loops(d, ent) -> tuple:
    s = mm(d)
    if ent.kind == "circle":
        return [{"circle": {"c": [ent.center[0] * s, ent.center[1] * s], "r": ent.radius * s}, "outer": True}], 0.0
    if ent.kind == "lwpolyline":
        if not ent.closed:
            raise SolidError("The polyline is open; close it first.")
        verts = [[v["p"][0] * s, v["p"][1] * s, float(v.get("bulge", 0.0) or 0.0)] for v in ent.vertices]
        return [{"vertices": verts, "outer": True}], float(ent.elevation) * s
    if ent.kind == "region":
        loops = []
        for lp in ent.loops:
            loops.append({"vertices": [[v["p"][0] * s, v["p"][1] * s, float(v.get("bulge", 0.0) or 0.0)] for v in lp["vertices"]], "outer": bool(lp.get("outer", True))})
        return loops, 0.0
    raise SolidError("Only closed polylines, circles and regions can be extruded.")


def extrude(ctx, ent, height: float, name: str = "Extrusion", rgb=None):
    d = ctx.d
    loops, z = profile_loops(d, ent)
    params = {"kind": "extrude", "loops": loops, "height": height * mm(d), "plane": {"origin": [0.0, 0.0, z], "normal": [0, 0, 1], "xdir": [1, 0, 0]}}
    res = kcall("primitive", params, SHORT)
    body = new_body(d, res["id"], res["summary"], name, {"op": "extrude", "profile": ent.kind, "height": height}, rgb)
    ctx.add(body)
    return body


def transform(ctx, body, params: dict):
    d = ctx.d
    wid = worker_id(d, body)
    p = dict(params)
    s = mm(d)
    if p.get("translate"):
        p["translate"] = [float(v) * s for v in p["translate"]]
    if p.get("rotate") and p["rotate"].get("origin"):
        p["rotate"] = {**p["rotate"], "origin": [float(v) * s for v in p["rotate"]["origin"]]}
    if p.get("scale_origin"):
        p["scale_origin"] = [float(v) * s for v in p["scale_origin"]]
    res = kcall("transform", {**p, "id": wid}, LONG)
    inputs = res.get("history", {}).get("inputs", [])
    parts = [(body.face_ids, body.edge_ids, inputs[0] if inputs else {})]
    target = d.modify(body.handle)
    apply_result(d, target, res["id"], res["summary"], {**body.source, "moved": True}, parts, body.lineage)
    return target


def mass_properties(d, body, density: float = 1.0) -> dict:
    wid = worker_id(d, body)
    raw = kcall("mass_properties", {"id": wid, "density": density}, SHORT)
    s = mm(d)
    out = dict(raw)
    out["unit_mm"] = s
    for key, power in (("area", 2), ("volume", 3)):
        if raw.get(key) is not None:
            out[key] = raw[key] / s**power
    if raw.get("centroid"):
        out["centroid"] = [c / s for c in raw["centroid"]]
    if raw.get("mass") is not None:
        out["mass"] = out["volume"] * density
    if raw.get("inertia"):
        out["inertia"] = [[v / s**5 for v in row] for row in raw["inertia"]]
        out["principal"] = [v / s**5 for v in raw["principal"]]
    return out


def bounds_units(d, body) -> list | None:
    wid = worker_id(d, body)
    raw = kcall("bounds", {"id": wid}, SHORT)
    s = mm(d)
    return [v / s for v in raw["min"]] + [v / s for v in raw["max"]]


def detail_params(summary: dict, detail: float) -> tuple:
    box = summary.get("bbox") or [0, 0, 0, 1, 1, 1]
    diag = math.dist(box[:3], box[3:])
    return max(diag * 0.0008 * detail, 1e-3), 0.3 if detail >= 1.0 else 0.5 if detail < 0.5 else 0.4


def detail_tag(detail: float) -> str:
    return "d%g" % detail


def mesh_for(d, body, detail: float) -> bytes:
    tag = detail_tag(detail)
    path = blobs.cache_path(body.blob, tag)
    cached = d.blobs.get(path)
    if cached is not None:
        return cached
    linear, angular = detail_params(body.summary, detail)
    with _lock:
        reset_if_restarted()
        base_key = (body.blob, (0.0, 0.0, 0.0))
        wid = _loaded.get(base_key)
        if wid is None:
            wid = load_blob(d, body.blob)
            remember(base_key, wid)
    with tempfile.TemporaryDirectory(prefix="fcmesh_") as tmp:
        out = os.path.join(tmp, "body.mesh")
        kcall("tessellate", {"id": wid, "linear": linear, "angular": angular, "path": out}, LONG)
        size = os.path.getsize(out)
        if size > blobs.MAX_BLOB:
            raise SolidError("The mesh is larger than the 256 MB limit; raise the tolerance.")
        with open(out, "rb") as fh:
            data = fh.read()
    d.blobs[path] = data
    return data


def export_step(d, path: str, bodies_list: list, schema: str = "ap214") -> dict:
    items = []
    for b in bodies_list:
        items.append({"id": worker_id(d, b), "name": b.name, "rgb": [c for c in b.rgb] if len(b.rgb) == 3 else None})
    return kcall("save_step", {"path": path, "bodies": items, "schema": schema}, LONG)


def read_model(path: str, ext: str) -> list:
    method = "open_iges" if ext in (".iges", ".igs") else "open_step"
    res = kcall(method, {"path": path}, LONG)
    return res["bodies"]


def add_model_bodies(d, items: list, stem: str, layer: str = "0") -> int:
    count = 0
    for i, item in enumerate(items):
        name = item.get("name") or "%s %d" % (stem, i + 1)
        body = new_body(d, item["id"], item["summary"], name, {"op": "import", "file": stem})
        body.rgb = list(item.get("rgb") or [])
        body.layer = layer
        d.add_entity(body, "model")
        count += 1
    return count
