import math

from app.graph import docvalues, shapes
from app.graph.geo import call, guid, make_shape, plist
from app.graph.sdk import NodeError, NodeType, NodeWarning, Port, register
from app.graph.values import Arc3, Circle3, Colour, Line3, PlaneF, Point3, Polyline3, Vector3

CAT = "Document"
SUPPORTED = ("point", "line", "circle", "arc", "lwpolyline", "polyline3d", "nurbscurve", "solidbody")

docvalues.install()


def drawing_of(ctx):
    d = ctx.doc
    if d is None:
        raise NodeError("This node reads the open document, and no document is open in this run.", "NO_DOCUMENT")
    return d


def mm_of(d) -> float:
    from app.param.units import mm_per_unit

    return mm_per_unit(d)


def colour_of(ent, d):
    from app.display import palette

    layer = d.layer(ent.layer)
    rgb, _adaptive = palette.resolve(ent.color, layer["color"] if layer else 7, None)
    return Colour(rgb[0], rgb[1], rgb[2])


def normal_plane(origin: Point3, normal) -> PlaneF:
    n = Vector3(float(normal[0]), float(normal[1]), float(normal[2]))
    if n.length < 1e-12:
        n = Vector3(0.0, 0.0, 1.0)
    return PlaneF.from_origin_normal(origin, n, Vector3(1.0, 0.0, 0.0))


def body_shape(ctx, d, ent):
    from app.solid import work

    try:
        wid = work.worker_id(d, ent)
    except Exception as err:
        raise NodeError(str(err) or "The body could not be loaded into the kernel.", "KERNEL")
    res = call(ctx, [{"op": "copy", "shape": {"sid": wid}}])[0]
    if "error" in res:
        raise NodeError(res["error"], "KERNEL")
    kind = "brep" if ent.summary.get("solids") else "surface"
    return make_shape(res, kind)


def nurbs_shape(ctx, d, ent, s):
    rec = ent.record()
    rec["poles"] = [[c * s for c in q] for q in rec["poles"]]
    res = call(ctx, [{"op": "wire", "curve": {"t": "nurbs", "curve": rec}}])[0]
    if "error" in res:
        raise NodeError(res["error"], "KERNEL")
    return make_shape(res, "curve")


def entity_value(ctx, d, ent):
    s = mm_of(d)
    k = ent.kind
    if k == "point":
        return Point3(ent.position[0] * s, ent.position[1] * s, ent.position[2] * s)
    if k == "line":
        return Line3(Point3(*[c * s for c in ent.start]), Point3(*[c * s for c in ent.end]))
    if k == "circle":
        return Circle3(normal_plane(Point3(*[c * s for c in ent.center]), ent.normal), ent.radius * s)
    if k == "arc":
        plane = normal_plane(Point3(*[c * s for c in ent.center]), ent.normal)
        a0, a1 = ent.start_angle, ent.end_angle
        while a1 <= a0:
            a1 += 2 * math.pi
        return Arc3(plane, ent.radius * s, a0, a1)
    if k == "lwpolyline":
        z = float(ent.elevation) * s
        if any(abs(float(v.get("bulge", 0.0) or 0.0)) > 1e-12 for v in ent.vertices):
            ctx.warn("A polyline with arc segments was read as straight chords.", "BULGE_FLATTENED")
        pts = tuple(Point3(v["p"][0] * s, v["p"][1] * s, z) for v in ent.vertices)
        return Polyline3(pts, bool(ent.closed))
    if k == "polyline3d":
        return Polyline3(tuple(Point3(*[c * s for c in q]) for q in ent.points), bool(ent.closed))
    if k == "nurbscurve":
        return nurbs_shape(ctx, d, ent, s)
    if k == "solidbody":
        return body_shape(ctx, d, ent)
    raise NodeWarning("The object %s of kind %s cannot be read into a graph." % (ent.handle, k), "UNSUPPORTED")


def describe_ent(d, ent) -> tuple:
    return ent.handle, ent.name if getattr(ent, "name", "") else "", ent.layer, ent.kind


def kinds_of(group: str):
    if group in ("", "any"):
        return SUPPORTED
    return tuple(k for k in docvalues.KIND_GROUPS.get(group, ()) if k in SUPPORTED)


def pick(d, layer, group, name, ids):
    kinds = kinds_of(group)
    out = []
    pattern = (name or "*").lower()
    import fnmatch

    pool = [d.ents[h] for h in ids if h in d.ents] if ids else list(d.ordered_entities())
    for ent in pool:
        if ent.kind not in kinds:
            continue
        if not docvalues.layer_match(layer, ent.layer):
            continue
        nm = getattr(ent, "name", "") or ""
        if pattern not in ("*", "") and not fnmatch.fnmatchcase(nm.lower(), pattern):
            continue
        out.append(ent)
    return out


def objects(ctx, layer, group, name, ids):
    d = drawing_of(ctx)
    ids = [int(i) for i in ids if i is not None]
    docvalues.watch(ctx.graph, ctx.node.id, docvalues.Sub(d, ids, layer if not ids else None, kinds_of(group) if not ids else None))
    found = pick(d, layer, group, name, ids)
    geo, handles, names, layers, kinds = [], [], [], [], []
    for ent in found:
        try:
            geo.append(entity_value(ctx, d, ent))
        except NodeWarning as w:
            ctx.warn(w.message, w.code)
            continue
        handles.append(int(ent.handle))
        names.append(getattr(ent, "name", "") or "")
        layers.append(ent.layer)
        kinds.append(ent.kind)
    return geo, handles, names, layers, kinds


register(NodeType(
    id="doc.objects", guid=guid("doc.objects"), name="Document Objects", nick="Obj", category=CAT, group="Reference",
    inputs=[
        Port("layer", "text", default="*", description="Layer name; a trailing * also takes the layers below it"),
        Port("kind", "text", default="any", choices=("any", "body", "curve", "point")),
        Port("name", "text", default="*", description="Name pattern for bodies and named objects"),
        Port("ids", "integer", access="list", optional=True, description="Pick these handles instead of searching"),
    ],
    outputs=[Port("geometry", "geometry"), Port("id", "integer"), Port("name", "text"), Port("layer", "text"), Port("kind", "text")],
    solve=lambda ctx, layer, kind, name, ids: objects(ctx, layer, kind, name, ids),
    multi=True, volatile=True,
    description="Bodies, curves and points of the open document by layer, kind or handle. The node recomputes when the objects it reads change.",
))


def by_id(ctx, handle):
    d = drawing_of(ctx)
    h = int(handle)
    docvalues.watch(ctx.graph, ctx.node.id, docvalues.Sub(d, [h]))
    ent = d.ents.get(h)
    if ent is None:
        raise NodeWarning("There is no object with handle %d in the document." % h, "NO_OBJECT")
    value = entity_value(ctx, d, ent)
    return value, getattr(ent, "name", "") or "", ent.layer, ent.kind


register(NodeType(
    id="doc.object_by_id", guid=guid("doc.object_by_id"), name="Document Object By Handle", nick="ObjId", category=CAT, group="Reference",
    inputs=[Port("id", "integer")],
    outputs=[Port("geometry", "geometry"), Port("name", "text"), Port("layer", "text"), Port("kind", "text")],
    solve=lambda ctx, handle: by_id(ctx, handle),
    volatile=True,
    description="One body, curve or point of the open document by its handle. The node recomputes when that object changes.",
))
