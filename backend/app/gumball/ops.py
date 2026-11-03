import math

import numpy as np

from app.bodies import multibody
from app.cmd import grips
from app.cmd.commands.modify_transform import rotate_fn, scale_fn
from app.doc import editstate
from app.doc.entities import Line, Point, Polyline3d, Spline
from app.doc.kinds.nurbscurve import NurbsCurve
from app.gumball import frame as fr
from app.gumball import state
from app.solid import work
from app.solid.work import SolidError

TWO_D = ("circle", "arc", "ellipse", "lwpolyline")
MIN_FACTOR = 1e-6
MAX_FACTOR = 1e6


class OpError(Exception):
    pass


def locked(doc, e) -> bool:
    return doc.drawing.layer_locked(e.layer) or editstate.locked_entity(doc, e)


def three(p, dz=0.0) -> list:
    return [float(p[0]), float(p[1]), (float(p[2]) if len(p) > 2 else 0.0) + dz]


def affine_entity(c, aff) -> bool:
    P = aff.point
    if isinstance(c, Line):
        c.start, c.end = P(c.start), P(c.end)
    elif isinstance(c, Point):
        c.position = P(c.position)
    elif isinstance(c, Polyline3d):
        c.points = [P(p) for p in c.points]
    elif isinstance(c, Spline):
        c.control_points = [P(p) for p in c.control_points]
        c.fit_points = [P(p) for p in c.fit_points]
        for name in ("start_tangent", "end_tangent"):
            tv = getattr(c, name)
            if tv:
                setattr(c, name, aff.vector(tv))
    elif isinstance(c, NurbsCurve):
        c.poles = [P(p) for p in c.poles]
    else:
        return False
    return True


def planar_entity(c, aff) -> bool:
    if aff.kind == "move":
        d = aff.t
        c.move_by([float(d[0]), float(d[1]), float(d[2])])
        if abs(float(d[2])) > 1e-14:
            if c.kind == "lwpolyline":
                c.elevation = float(c.elevation) + float(d[2])
            else:
                for name in c.POINTS:
                    v = getattr(c, name, None)
                    if v is not None and len(v) == 2:
                        setattr(c, name, three(v, float(d[2])))
        return True
    if aff.kind == "rotate" and aff.axis is not None and abs(abs(float(aff.axis[2])) - 1.0) < 1e-9:
        angle = math.radians(aff.degrees) * (1.0 if aff.axis[2] > 0 else -1.0)
        rotate_fn([float(aff.o[0]), float(aff.o[1])], angle)(c)
        return True
    if aff.kind == "scale" and aff.factor:
        scale_fn([float(aff.o[0]), float(aff.o[1])], aff.factor, float(aff.o[2]))(c)
        return True
    return False


def transform_entity(doc, e, aff, copy_flag: bool) -> int:
    d = doc.drawing
    c = e.copy_as_new()
    try:
        done = affine_entity(c, aff)
        if not done:
            if e.kind in TWO_D:
                done = planar_entity(c, aff)
            elif aff.kind == "move":
                c.move_by(aff.t.tolist())
                done = True
            elif (aff.kind == "rotate" and aff.axis is not None and abs(abs(float(aff.axis[2])) - 1.0) < 1e-9) or (aff.kind == "scale" and aff.factor):
                done = planar_entity(c, aff)
    except (grips.GripError, ValueError, ZeroDivisionError):
        return 0
    if not done or not c.valid():
        return 0
    if copy_flag:
        try:
            return d.add_entity(c, e.owner)
        except ValueError:
            return 0
    grips._assign(d.modify(e.handle), c)
    return e.handle


def solid_params(aff, s: float) -> dict:
    if aff.kind == "move":
        return {"translate": [float(v) for v in aff.t]}
    if aff.kind == "rotate":
        return {"rotate": {"origin": [float(v) for v in aff.o], "axis": [float(v) for v in aff.axis], "degrees": float(aff.degrees)}}
    return {}


def worker_params(aff, s: float) -> dict:
    if aff.kind == "move":
        return {"translate": [float(v) * s for v in aff.t]}
    if aff.kind == "rotate":
        return {"rotate": {"origin": [float(v) * s for v in aff.o], "axis": [float(v) for v in aff.axis], "degrees": float(aff.degrees)}}
    if aff.factor:
        return {"scale": float(aff.factor), "scale_origin": [float(v) * s for v in aff.o]}
    return {}


def transform_solid(doc, body, aff, copy_flag: bool):
    d = doc.drawing
    s = work.mm(d)
    owned = multibody.part_owner(d, [body])[1]
    if owned and aff.kind == "scale":
        raise OpError("The body of a part with a feature tree cannot be scaled here; copy it first.")
    try:
        if aff.kind in ("move", "rotate"):
            params = solid_params(aff, s)
            if copy_flag:
                got = multibody.copy_bodies(d, [body.handle], params, 1)
                return list(got.get("handles") or [])
            got = multibody.move(d, [body.handle], params)
            return list(got.get("handles") or [])
        wid = work.worker_id(d, body)
        if aff.kind == "scale" and not aff.factor:
            rows = aff.rows12()
            mm_rows = [rows[0], rows[1], rows[2], rows[3] * s, rows[4], rows[5], rows[6], rows[7] * s, rows[8], rows[9], rows[10], rows[11] * s]
            res = work.kcall("an_affine", {"id": wid, "matrix": mm_rows}, work.LONG)
        else:
            res = work.kcall("transform", {**worker_params(aff, s), "id": wid}, work.LONG)
        if copy_flag:
            new = work.new_body(d, res["id"], res["summary"], body.name, dict(body.source, copied=True), body.rgb)
            new.material = body.material
            handle = d.add_entity(new, body.owner)
            d.modify(handle).layer = body.layer
            return [handle]
        inputs = res.get("history", {}).get("inputs", [])
        target = d.modify(body.handle)
        work.apply_result(d, target, res["id"], res["summary"], dict(body.source, moved=True), [(body.face_ids, body.edge_ids, inputs[0] if inputs else {})], body.lineage)
        return [body.handle]
    except (SolidError, multibody.BodyError) as err:
        raise OpError(str(err))


def check_op(op: dict) -> None:
    kind = str(op.get("type", op.get("op", ""))).lower()
    if kind == "scale":
        for key in ("factor",):
            if op.get(key) is not None:
                f = float(op[key])
                if not MIN_FACTOR <= f <= MAX_FACTOR:
                    raise OpError("The scale factor must be from %g to %g." % (MIN_FACTOR, MAX_FACTOR))
        if op.get("factors") is not None and not all(MIN_FACTOR <= float(f) <= MAX_FACTOR for f in op["factors"]):
            raise OpError("The scale factors must be from %g to %g." % (MIN_FACTOR, MAX_FACTOR))


def apply(doc, op: dict, handles=None, copy_flag: bool = False) -> dict:
    d = doc.drawing
    picked = state.selection_handles(doc, handles)
    if not picked:
        raise OpError("Select the objects to transform first.")
    desc = state.describe(doc, picked)
    if desc["origin"] is None:
        raise OpError("The selection has no geometry to transform.")
    try:
        check_op(op)
        aff = fr.build(op, desc["axes"], np.asarray(desc["origin"], dtype=np.float64))
    except (fr.FrameError, TypeError, ValueError) as err:
        raise OpError(str(err))
    made, skipped = [], 0
    for h in picked:
        e = d.get(h)
        if e is None:
            continue
        if locked(doc, e):
            skipped += 1
            continue
        if e.kind == "solidbody":
            made.extend(transform_solid(doc, e, aff, copy_flag))
        else:
            got = transform_entity(doc, e, aff, copy_flag)
            if got:
                made.append(got)
            else:
                skipped += 1
    st = state.memory(doc)
    if st["manual"] and st.get("origin"):
        st["origin"] = aff.point(st["origin"])
    state.touch(st)
    return {"handles": made, "skipped": skipped, "matrix": aff.rows12(), "kind": aff.kind, "origin": state.describe(doc, picked)["origin"]}
