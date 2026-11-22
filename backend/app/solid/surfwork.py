import math

from app.param.units import mm_per_unit
from app.solid import work
from app.solid.work import SolidError, kcall, new_body, worker_id

DEFAULT_TOL = 1e-3
DEFAULT_ANGLE = 1e-3
FLOOR_TOL = 1e-6
FLOOR_ANGLE = 1e-7
POLYLINES_KEPT = 24
POINTS_KEPT = 120
LIST_KEPT = 400
TAU = 2.0 * math.pi


def scale(d) -> float:
    return mm_per_unit(d)


def model_tolerance(d) -> dict:
    s = scale(d)
    doc_abs = float(d.tolerances.get("absolute", 0.0))
    doc_ang = float(d.tolerances.get("angular", 0.0))
    tol, tol_src = (doc_abs * s, "document") if doc_abs * s >= FLOOR_TOL else (DEFAULT_TOL, "default")
    ang, ang_src = (doc_ang, "document") if doc_ang >= FLOOR_ANGLE else (DEFAULT_ANGLE, "default")
    return {"tol": tol, "angtol": ang, "absolute_source": tol_src, "angular_source": ang_src, "unit_mm": s, "tol_units": tol / s}


def call(d, method: str, params: dict, timeout: float = work.LONG):
    t = model_tolerance(d)
    return kcall(method, {**params, "tol": t["tol"], "angtol": t["angtol"]}, timeout)


def p3(q, s: float, z: float = 0.0) -> list:
    return [float(q[0]) * s, float(q[1]) * s, (float(q[2]) if len(q) > 2 else z) * s]


def bulge_mid(a, b, bulge: float) -> list:
    dx, dy = b[0] - a[0], b[1] - a[1]
    chord = math.hypot(dx, dy)
    sag = bulge * chord / 2.0
    return [(a[0] + b[0]) / 2.0 + dy / chord * sag, (a[1] + b[1]) / 2.0 - dx / chord * sag]


def flat_knots(knots, mults) -> list:
    out = []
    for k, m in zip(knots, mults):
        out.extend([float(k)] * int(m))
    return out


def polyline_spec(points, closed: bool, s: float) -> dict:
    pts = [p3(q, s) for q in points]
    if closed and len(pts) > 2:
        pts.append(pts[0])
    segs = [{"line": [pts[i], pts[i + 1]]} for i in range(len(pts) - 1) if math.dist(pts[i], pts[i + 1]) > 1e-9]
    if not segs:
        raise SolidError("The polyline has no length.")
    return {"kind": "path", "segments": segs}


def lwpolyline_spec(ent, s: float) -> dict:
    verts = ent.vertices
    n = len(verts)
    count = n if ent.closed else n - 1
    z = float(ent.elevation)
    segs = []
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        pa, pb = a["p"], b["p"]
        if math.hypot(pb[0] - pa[0], pb[1] - pa[1]) <= 1e-12:
            continue
        bulge = float(a.get("bulge", 0.0) or 0.0)
        if abs(bulge) > 1e-12:
            mid = bulge_mid(pa, pb, bulge)
            segs.append({"arc": [p3(pa, s, z), p3(mid, s, z), p3(pb, s, z)]})
        else:
            segs.append({"line": [p3(pa, s, z), p3(pb, s, z)]})
    if not segs:
        raise SolidError("The polyline has no length.")
    return {"kind": "path", "segments": segs}


def curve_spec(d, ent) -> dict:
    s = scale(d)
    k = ent.kind
    if k == "line":
        return {"kind": "line", "a": p3(ent.start, s), "b": p3(ent.end, s)}
    if k == "circle":
        return {"kind": "circle", "center": p3(ent.center, s), "normal": [0, 0, 1], "radius": ent.radius * s}
    if k == "arc":
        return {"kind": "circle", "center": p3(ent.center, s), "normal": [0, 0, 1], "radius": ent.radius * s, "a0": ent.start_angle, "a1": ent.end_angle}
    if k == "ellipse":
        spec = {"kind": "ellipse", "center": p3(ent.center, s), "normal": [0, 0, 1], "major": p3(ent.major, s), "ratio": ent.ratio}
        if abs(ent.end_param - ent.start_param) < TAU - 1e-9:
            spec["p0"], spec["p1"] = ent.start_param, ent.end_param
        return spec
    if k == "lwpolyline":
        return lwpolyline_spec(ent, s)
    if k == "polyline3d":
        return polyline_spec(ent.points, ent.closed, s)
    if k == "spline":
        if not ent.control_points or not ent.knots:
            raise SolidError("The spline has no control points; convert it to a NURBS curve first.")
        return {"kind": "bspline", "degree": int(ent.degree), "knots": [float(v) for v in ent.knots], "poles": [p3(q, s) for q in ent.control_points], "weights": [float(w) for w in ent.weights]}
    if k == "nurbscurve":
        if ent.periodic:
            raise SolidError("A periodic NURBS curve cannot be used here; make it non-periodic first.")
        return {"kind": "bspline", "degree": int(ent.degree), "knots": flat_knots(ent.knots, ent.mults), "poles": [p3(q, s) for q in ent.poles], "weights": [float(w) for w in ent.weights]}
    raise SolidError("A %s cannot be used as a curve here." % k)


def entity_of(d, handle):
    ent = d.get(int(handle))
    if ent is None:
        raise SolidError("Object %s does not exist." % handle)
    return ent


def body_of(d, handle):
    ent = entity_of(d, handle)
    if ent.kind != "solidbody":
        raise SolidError("Object %s is not a solid or surface." % handle)
    return ent


def index_of(ids: list, pid, what: str) -> int:
    try:
        return ids.index(int(pid))
    except (ValueError, TypeError):
        raise SolidError("That %s no longer exists." % what)


def face_ref(d, ref: dict) -> tuple:
    body = body_of(d, ref["body"])
    idx = int(ref["face_index"]) if ref.get("face_index") is not None else index_of(body.face_ids, ref.get("face"), "face")
    return body, {"id": worker_id(d, body), "index": idx}


def edge_ref(d, ref: dict) -> tuple:
    body = body_of(d, ref["body"])
    idx = int(ref["edge_index"]) if ref.get("edge_index") is not None else index_of(body.edge_ids, ref.get("edge"), "edge")
    return body, {"id": worker_id(d, body), "index": idx}


def edge_curve(d, ref: dict) -> dict:
    return {"kind": "shape_edge", **edge_ref(d, ref)[1]}


def curves_of(d, handles, edges=()) -> list:
    out = [curve_spec(d, entity_of(d, h)) for h in handles or []]
    out.extend(edge_curve(d, r) for r in edges or [])
    return out


def side_of(d, ref: dict) -> dict:
    body, edge = edge_ref(d, ref)
    if ref.get("face") is not None or ref.get("face_index") is not None:
        _fb, face = face_ref(d, {"body": ref["body"], "face": ref.get("face"), "face_index": ref.get("face_index")})
        return {"face": face, "edge": edge, "body": body}
    rows = kcall("surf_edges", {"id": edge["id"]}, work.SHORT)["edges"]
    faces = rows[edge["index"]].get("faces") or []
    if len(faces) != 1:
        raise SolidError("That edge borders %d faces; choose an edge on the outer boundary of one surface, or name the face." % len(faces))
    return {"face": {"id": edge["id"], "index": faces[0]}, "edge": edge, "body": body}


def side_params(side: dict) -> dict:
    return {"face": side["face"], "edge": side["edge"]}


def thin(poly: list) -> list:
    if len(poly) <= POINTS_KEPT:
        return poly
    step = (len(poly) - 1) / float(POINTS_KEPT - 1)
    return [poly[int(round(i * step))] for i in range(POINTS_KEPT)]


def compact(value, key: str = ""):
    if isinstance(value, dict):
        return {k: compact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        if key == "naked_edges":
            return {"count": len(value), "polylines": [thin(p) for p in value[:POLYLINES_KEPT]]}
        if len(value) > LIST_KEPT:
            step = len(value) / float(LIST_KEPT)
            return [compact(value[int(i * step)], key) for i in range(LIST_KEPT)]
        return [compact(v, key) for v in value]
    return value


def source_for(op: str, res: dict, extra: dict | None = None) -> dict:
    src = {"op": op, "surface": True, "report": compact(res.get("report") or {})}
    if extra:
        src.update(extra)
    return src


def add_result(ctx, res: dict, name: str, op: str, extra: dict | None = None):
    body = new_body(ctx.d, res["id"], res["summary"], name, source_for(op, res, extra))
    ctx.add(body)
    return body


def replace_result(ctx, body, res: dict, op: str, extra: dict | None = None):
    d = ctx.d
    inputs = (res.get("history") or {}).get("inputs") or []
    parts = [(body.face_ids, body.edge_ids, inputs[0])] if inputs else None
    target = d.modify(body.handle)
    work.apply_result(d, target, res["id"], res["summary"], {**source_for(op, res), "from": [body.name]}, parts, body.lineage)
    return target


def single_face(body) -> bool:
    return len(body.face_ids) == 1


def edit_surface(ctx, body, res: dict, op: str, extra: dict | None = None):
    if single_face(body):
        return replace_result(ctx, body, res, op, extra), True
    return add_result(ctx, res, "%s %s" % (body.name or "Surface", op), op, extra), False


def merge_bodies(ctx, bodies: list, res: dict, op: str):
    d = ctx.d
    inputs = (res.get("history") or {}).get("inputs") or []
    parts = [(b.face_ids, b.edge_ids, inputs[i] if i < len(inputs) else {}) for i, b in enumerate(bodies)]
    keep = {}
    for b in bodies:
        keep.update(b.lineage)
    target = d.modify(bodies[0].handle)
    work.apply_result(d, target, res["id"], res["summary"], {**source_for(op, res), "from": [b.name for b in bodies]}, parts, keep)
    for b in bodies[1:]:
        d.erase_entity(b.handle)
    return target


def surface_label(summary: dict) -> str:
    kind = "solid" if summary.get("solids") else "surface"
    return "%s with %d faces and %d edges" % (kind, summary.get("faces", 0), summary.get("edges", 0))


def seam_line(rep: dict) -> str:
    line = "%s, gap %.3g mm, normal angle %.3g rad, curvature gap %.3g" % (rep.get("level", "none").upper(), rep.get("max_gap", 0.0), rep.get("max_angle", 0.0), rep.get("max_curvature_gap", 0.0))
    rate = rep.get("max_curvature_rate_gap")
    return line if rate is None else "%s, curvature rate gap %.3g" % (line, rate)


def audit_line(report: dict) -> str:
    a = report.get("audit") or {}
    if not a:
        return ""
    state = "above the limit" if a.get("exceeded") else "within the limit"
    return "Stored tolerances %s: vertex %.3g, edge %.3g, face %.3g mm against %.3g." % (state, a.get("vertex", 0.0), a.get("edge", 0.0), a.get("face", 0.0), a.get("limit", 0.0))
