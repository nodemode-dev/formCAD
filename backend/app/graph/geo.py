import math
import uuid

from app.graph import match, modifiers, shapes
from app.graph import tree as T
from app.graph.sdk import Aborted, NodeError, NodeType, Port, register
from app.graph.values import Arc3, Circle3, Line3, PlaneF, Point3, Polyline3, Shape, Transform, Vector3
from app.services import kernel

NAMESPACE = uuid.UUID("5f0b8c2e-6a1d-4c37-9b52-3d1e7a9c4f10")
BATCH_LIMIT = 4000
BASE_TIMEOUT = 40.0
PER_OP = 0.03


class Skip(Exception):
    pass


def guid(type_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, type_id))


def plist(p) -> list:
    return [p.x, p.y, p.z]


def pt(v) -> Point3:
    return Point3(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def vec(v) -> Vector3:
    return Vector3(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)


def plane_spec(p: PlaneF) -> dict:
    return {"o": plist(p.origin), "n": plist(p.z), "x": plist(p.x)}


def curve_spec(v) -> dict:
    if isinstance(v, Line3):
        return {"t": "line", "a": plist(v.a), "b": plist(v.b)}
    if isinstance(v, Polyline3):
        return {"t": "poly", "pts": [plist(p) for p in v.points], "closed": bool(v.closed)}
    if isinstance(v, Circle3):
        return {"t": "circle", "c": plist(v.plane.origin), "n": plist(v.plane.z), "x": plist(v.plane.x), "r": v.radius}
    if isinstance(v, Arc3):
        if abs(v.sweep) >= 2 * math.pi - 1e-9:
            raise Skip("The arc sweeps a full turn; use a circle.")
        return {"t": "arc", "a": plist(v.point_at(0.0)), "m": plist(v.point_at(0.5)), "b": plist(v.point_at(1.0))}
    if isinstance(v, Shape):
        return {"sid": shapes.checked(v.sid)}
    raise Skip("A curve was expected.")


def shape_spec(v) -> dict:
    if isinstance(v, Shape):
        return {"sid": shapes.checked(v.sid)}
    raise Skip("A kernel shape was expected.")


def curve_or_shape(v) -> dict:
    return curve_spec(v)


def make_shape(desc: dict, kind: str = "") -> Shape:
    bbox = desc.get("bbox")
    return Shape(kind or desc.get("kind", "geometry"), shapes.wrap(desc["sid"]), tuple(bbox) if bbox else None)


def shapes_of(res: dict, key: str = "shapes") -> list:
    return [make_shape(d) for d in res.get(key) or []]


def collect_ids(obj, out: list) -> None:
    if isinstance(obj, dict):
        sid = obj.get("sid")
        if isinstance(sid, str):
            out.append(shapes.wrap(sid))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                collect_ids(v, out)


def call(ctx, ops: list, free=None) -> list:
    if not ops:
        return []
    out = []
    for start in range(0, len(ops), BATCH_LIMIT):
        chunk = ops[start:start + BATCH_LIMIT]
        params = {"ops": chunk}
        timeout = BASE_TIMEOUT + PER_OP * len(chunk)
        try:
            if hasattr(ctx, "kernel"):
                res = ctx.kernel("graph_batch", params, timeout)
            else:
                res = kernel.call("graph_batch", params, timeout)
        except NodeError:
            raise
        except Exception as err:
            raise NodeError(str(err) or "The kernel did not answer.", "KERNEL")
        got = res.get("results") or []
        ids = []
        collect_ids(got, ids)
        shapes.track(ids)
        out.extend(got)
    return out


def unwrap_result(res: dict) -> dict:
    if "error" in res:
        raise Skip(res["error"])
    return res


def tol_of(ctx) -> float:
    return max(float(getattr(ctx, "tol", 0.001) or 0.001) * 0.001, 1e-7)


def match_inputs(ctx, trees: dict, ports: list) -> list:
    node = ctx.node
    out = []
    for p in ports:
        ps = node.port(p.name, "in") if node is not None else None
        mods = {"principal": True} if (ps is not None and ps.mods.get("principal")) else {}
        out.append(match.MatchInput(p.name, trees.get(p.name, T.DataTree()), p.access, p.is_optional, p.default, mods))
    return out


def run_batched(ctx, trees: dict, nt: NodeType, handler, multi=False, rows=()) -> dict:
    node = ctx.node
    inputs = match_inputs(ctx, trees, nt.inputs)
    msgs = []
    mode = getattr(node, "matching", "longest") or "longest"
    calls = list(match.iterate(inputs, mode, None, msgs, getattr(ctx, "seed", 0)))
    item_ids = [k for k, i in enumerate(inputs) if i.access == "item" and not i.optional]
    run_at, run_args = [], []
    results = [None] * len(calls)
    nulls = 0
    for i, c in enumerate(calls):
        if c.args is None:
            results[i] = match.Result(c.path, c.index, match.EMPTY)
        elif c.index is not None and any(c.args[k] is None for k in item_ids):
            nulls += 1
            results[i] = match.Result(c.path, c.index, match.NULLED)
        else:
            run_at.append(i)
            run_args.append(c.args)
    done = handler(run_args) if run_args else []
    failures = []
    for i, r in zip(run_at, done):
        c = calls[i]
        if isinstance(r, Exception):
            failures.append(str(r))
            results[i] = match.Result(c.path, c.index, match.NULLED)
        else:
            results[i] = match.Result(c.path, c.index, r)
    n_out = len(nt.outputs)
    row_ports = set(rows)
    flags = [bool(multi) or (o.name in row_ports) for o in nt.outputs]
    outs = collect_rows(results, nt, flags, row_ports)
    for m in msgs:
        ctx.warn(m.text, m.code, m.port or "")
    if nulls:
        ctx.warn("%d calls were skipped because an input item was null." % nulls, "NULL_INPUT")
    if failures:
        first = failures[0]
        ctx.warn("%d of %d items failed: %s" % (len(failures), len(done), first), "ITEM_FAILED")
    return {o.name: tree for o, tree in zip(nt.outputs, outs)}


def collect_rows(results: list, nt: NodeType, flags: list, row_ports: set) -> list:
    n_out = len(nt.outputs)
    normal = [r for r in results]
    outs = match.collect(_plain(normal, nt, row_ports), n_out, flags)
    for r in normal:
        if r.value is match.EMPTY or r.value is match.NULLED:
            continue
        vals = [r.value] if n_out == 1 else list(r.value)
        for o, port in enumerate(nt.outputs):
            if port.name not in row_ports:
                continue
            at = r.path.child(r.index) if r.index is not None else r.path
            for k, row in enumerate(vals[o] or []):
                outs[o].set_branch(at.child(k), list(row))
            if at in outs[o] and not outs[o].branch(at):
                outs[o].remove_branch(at)
    return outs


def _plain(results: list, nt: NodeType, row_ports: set):
    for r in results:
        if r.value is match.EMPTY or r.value is match.NULLED or not row_ports:
            yield r
            continue
        vals = [r.value] if len(nt.outputs) == 1 else list(r.value)
        patched = [([] if port.name in row_ports else vals[o]) for o, port in enumerate(nt.outputs)]
        yield match.Result(r.path, r.index, patched[0] if len(patched) == 1 else tuple(patched))


def stale_exit(ctx):
    if shapes.recover(getattr(ctx, "graph", None)):
        raise Aborted()
    raise NodeError("A kernel shape is from before the kernel restarted; solve the graph again.", "STALE_SHAPE")


def simple_node(type_id, name, nick, group, inputs, outputs, build, finish, category="Geometry", description="", multi=False, rows=(), icon=""):
    def handler(ctx, arg_rows):
        built, pos = [], []
        out = [None] * len(arg_rows)
        for i, args in enumerate(arg_rows):
            try:
                op = build(*args)
            except shapes.Stale:
                stale_exit(ctx)
            except Skip as err:
                out[i] = Skip(str(err))
                continue
            except (ValueError, TypeError) as err:
                out[i] = Skip(str(err))
                continue
            built.append(op)
            pos.append(i)
        if built:
            if isinstance(built[0], dict):
                res = call(ctx, built)
            else:
                res = built
            for i, r in zip(pos, res):
                if isinstance(r, dict) and "error" in r:
                    out[i] = Skip(r["error"])
                    continue
                try:
                    out[i] = finish(arg_rows[i], r)
                except Skip as err:
                    out[i] = Skip(str(err))
        return out

    def run(ctx, trees):
        return run_batched(ctx, trees, nt, lambda arg_rows: handler(ctx, arg_rows), multi=multi, rows=rows)

    nt = NodeType(id=type_id, guid=guid(type_id), name=name, nick=nick, category=category, group=group, inputs=inputs, outputs=outputs, run=run, description=description, multi=multi, icon=icon)
    register(nt)
    return nt


def broadcast(*lists) -> list:
    if not lists or any(len(x) == 0 for x in lists):
        return []
    n = max(len(x) for x in lists)
    return [tuple(x[min(i, len(x) - 1)] for x in lists) for i in range(n)]


def apply_transform(value, xf: Transform):
    return xf.apply(value)


def transform_shapes(ctx, pairs: list) -> list:
    ops = []
    for v, xf in pairs:
        ops.append({"op": "xf", "shape": shape_spec(v), "matrix": list(xf.m)})
    res = call(ctx, ops)
    out = []
    for r in res:
        if "error" in r:
            out.append(Skip(r["error"]))
        else:
            out.append(make_shape(r))
    return out
