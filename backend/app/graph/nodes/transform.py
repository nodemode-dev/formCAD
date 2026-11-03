import math

from app.graph import shapes
from app.graph.docvalues import Attributed
from app.graph.geo import Skip, call, guid, make_shape, run_batched, shape_spec, stale_exit
from app.graph.sdk import NodeType, Port, register
from app.graph.values import PlaneF, Shape, Transform, ValueError3, Vector3

CAT = "Transform"
XY = PlaneF()


def apply_many(ctx, pairs: list) -> list:
    wrappers = [v if isinstance(v, Attributed) else None for v, _x in pairs]
    inner = [(v.geometry if isinstance(v, Attributed) else v, x) for v, x in pairs]
    out = apply_plain(ctx, inner)
    return [w.with_(geometry=o) if (w is not None and not isinstance(o, Exception)) else o for w, o in zip(wrappers, out)]


def apply_plain(ctx, pairs: list) -> list:
    out = [None] * len(pairs)
    ops, at = [], []
    for i, (value, xf) in enumerate(pairs):
        if isinstance(value, Shape):
            try:
                ops.append({"op": "xf", "shape": shape_spec(value), "matrix": list(xf.m)})
            except shapes.Stale:
                stale_exit(ctx)
            at.append(i)
            continue
        try:
            out[i] = xf.apply(value)
        except ValueError3 as err:
            out[i] = Skip(str(err))
    if ops:
        for i, r in zip(at, call(ctx, ops)):
            out[i] = Skip(r["error"]) if "error" in r else make_shape(r)
    return out


def define(type_id, name, nick, inputs, outputs, expand, description, multi=False):
    def handler(ctx, rows):
        pairs, owners = [], []
        results = [None] * len(rows)
        for i, args in enumerate(rows):
            try:
                made = expand(*args)
            except (Skip, ValueError3, ValueError) as err:
                results[i] = Skip(str(err))
                continue
            owners.append((i, len(made)))
            pairs.extend(made)
        done = apply_many(ctx, [(v, x) for v, x in pairs]) if pairs else []
        k = 0
        for i, n in owners:
            chunk = done[k:k + n]
            k += n
            bad = next((c for c in chunk if isinstance(c, Exception)), None)
            if bad is not None:
                results[i] = bad
                continue
            if multi:
                results[i] = ([c for c in chunk], [x for _v, x in pairs[k - n:k]])
            else:
                results[i] = (chunk[0], pairs[k - n][1])
        return results

    def run(ctx, trees):
        return run_batched(ctx, trees, nt, lambda rows: handler(ctx, rows), multi=multi)

    nt = NodeType(id=type_id, guid=guid(type_id), name=name, nick=nick, category=CAT, group="Apply", inputs=inputs, outputs=outputs, run=run, description=description, multi=multi)
    register(nt)
    return nt


define(
    "transform.apply_to", "Apply Transform", "Xf",
    [Port("geometry", "geometry"), Port("transform", "transform")],
    [Port("geometry", "geometry"), Port("transform", "transform")],
    lambda geometry, transform: [(geometry, transform)],
    "Move, turn, scale or mirror any geometry by a transform value.",
)


def linear(geometry, direction, count):
    n = int(count)
    if n < 1 or n > 10000:
        raise Skip("The count must be from 1 to 10000.")
    return [(geometry, Transform.translation(direction * float(i))) for i in range(n)]


define(
    "transform.array_linear", "Linear Array", "ArrL",
    [Port("geometry", "geometry"), Port("direction", "vector", default=Vector3(1.0, 0.0, 0.0), description="Step between copies"), Port("count", "integer", default=3, min=1)],
    [Port("geometry", "geometry"), Port("transforms", "transform")],
    linear,
    "Copies of geometry at equal steps along a vector; the first copy stays in place.",
    multi=True,
)


def polar(geometry, plane, count, angle):
    n = int(count)
    if n < 1 or n > 10000:
        raise Skip("The count must be from 1 to 10000.")
    total = float(angle)
    step = total / n if abs(abs(total) - 2 * math.pi) < 1e-9 or n == 1 else total / (n - 1)
    return [(geometry, Transform.rotation(step * i, plane.z, plane.origin)) for i in range(n)]


define(
    "transform.array_polar", "Polar Array", "ArrP",
    [Port("geometry", "geometry"), Port("plane", "plane", default=XY, description="Axis is the plane normal through its origin"), Port("count", "integer", default=6, min=1), Port("angle", "number", default=2 * math.pi, description="Total sweep in radians")],
    [Port("geometry", "geometry"), Port("transforms", "transform")],
    polar,
    "Copies of geometry turned about an axis; a full turn spreads them evenly without repeating the first.",
    multi=True,
)


def orient(geometry, source, target):
    return [(geometry, Transform.plane_to_plane(source, target))]


define(
    "transform.orient_plane", "Orient Plane To Plane", "Ori",
    [Port("geometry", "geometry"), Port("source", "plane", default=XY), Port("target", "plane", default=XY)],
    [Port("geometry", "geometry"), Port("transform", "transform")],
    orient,
    "Carry geometry from one plane to another.",
)
