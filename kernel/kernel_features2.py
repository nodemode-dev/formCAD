import math

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffset import BRepOffset_Skin
from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle, BRepOffsetAPI_MakeThickSolid
from OCP.ChFi3d import ChFi3d_Polynomial, ChFi3d_QuasiAngular, ChFi3d_Rational
from OCP.ChFiDS import ChFiDS_Ok, ChFiDS_StartsolFailure, ChFiDS_TwistedSurface, ChFiDS_WalkingFailure
from OCP.Draft import Draft_NoError
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_BSplineSurface, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Intersection, GeomAbs_Plane, GeomAbs_Shape
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.collections import Array1_gp_Pnt2d as Pnt2dArray
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as AncestorMap
from OCP.collections import List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pln, gp_Pnt, gp_Pnt2d, gp_Trsf, gp_Vec

import kernel_ops as ops
import kernel_store as store

MAX_INSTANCES = 5000
MAX_ISOLATE = 64
TOL = 1e-6

STRIPE_TEXT = {
    ChFiDS_StartsolFailure: "the computation could not start; the radius is probably too large for this chain of edges",
    ChFiDS_TwistedSurface: "the blend surface twists; the geometry around this chain is too complex for the radius",
    ChFiDS_WalkingFailure: "the blend could not be followed along the whole chain; reduce the radius or split the chain",
}


def issue(message, edges=None, faces=None, vertices=None, code=None):
    out = {"message": message}
    if code:
        out["code"] = code
    if edges:
        out["edges"] = sorted(set(edges))
    if faces:
        out["faces"] = sorted(set(faces))
    if vertices:
        out["vertices"] = sorted(set(vertices))
    return out


def failure(message, errors=None, warnings=None, failed=None):
    return {"ok": False, "message": message, "errors": errors or [issue(message)], "warnings": warnings or [], "failed": failed or {"edges": [], "faces": []}}


def positive_number(p, key):
    try:
        v = float(p.get(key))
    except (TypeError, ValueError):
        raise RuntimeError("%s must be a number." % key)
    if not math.isfinite(v) or v <= ops.MIN_SIZE:
        raise RuntimeError("%s must be positive." % key)
    return v


def sub_items(sid, key, indices, label):
    m = store.maps_of(sid)[key]
    out = []
    for raw in indices:
        i = int(raw)
        if i < 0 or i >= m.Extent():
            raise RuntimeError("%s %d is not in the shape (it has %d)." % (label, i, m.Extent()))
        shape = m.FindKey(i + 1)
        out.append(TopoDS.Edge(shape) if key == "edges" else TopoDS.Face(shape))
    return out


def index_in(sid, key, shape):
    return store.maps_of(sid)[key].FindIndex(shape) - 1


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def ancestors(shape, parent, child):
    m = AncestorMap()
    TopExp.MapShapesAndAncestors_s(shape, parent, child, m)
    return m


def edge_valence(shape):
    m = ancestors(shape, TopAbs_VERTEX, TopAbs_EDGE)
    out = {}
    for i in range(1, m.Extent() + 1):
        seen = []
        for e in m.FindFromIndex(i):
            if not any(e.IsSame(s) for s in seen):
                seen.append(e)
        out[i - 1] = len(seen)
    return out


def sub_shapes(shape, kind):
    m = store.ShapeMap()
    TopExp.MapShapes_s(shape, kind, m)
    return [m.FindKey(i) for i in range(1, m.Extent() + 1)]


def face_neighbours(shape, edge):
    m = ancestors(shape, TopAbs_EDGE, TopAbs_FACE)
    i = m.FindIndex(edge)
    if i <= 0:
        return []
    seen = []
    for f in m.FindFromIndex(i):
        if not any(f.IsSame(s) for s in seen):
            seen.append(f)
    return seen


def surface_kind(face):
    return BRepAdaptor_Surface(face).GetType()


def surface_problem(face):
    kind = surface_kind(face)
    try:
        surf = BRep_Tool.Surface_s(face)
        cont = surf.Continuity()
    except Exception:
        return None
    if kind == GeomAbs_BSplineSurface and cont == GeomAbs_Shape.GeomAbs_C0:
        return "c0"
    if cont in (GeomAbs_Shape.GeomAbs_C0, GeomAbs_Shape.GeomAbs_G1):
        return "below_c1" if cont == GeomAbs_Shape.GeomAbs_C0 else None
    return None


def valid_solid(shape):
    try:
        return bool(BRepCheck_Analyzer(shape).IsValid()) and store.count_of(shape, TopAbs_SOLID) > 0
    except Exception:
        return False


def finish(maker, source_id, result, extra=None, expect=None):
    if not valid_solid(result):
        return None, "The kernel produced a shape that is not a valid solid; change the size or the selection."
    if expect:
        v0 = volume_of(store.shape_of(source_id))
        v1 = volume_of(result)
        bad = expect(v0, v1)
        if bad:
            return None, bad
    ident = store.put(result)
    out_maps = store.maps_of(ident)
    inputs = [{"id": source_id, **ops.input_history(maker, store.shape_of(source_id), store.maps_of(source_id), out_maps)}]
    out = {"ok": True, "id": ident, "summary": store.summarize(result), "history": {"inputs": inputs}, "errors": [], "warnings": [], "failed": {"edges": [], "faces": []}}
    touched = set()
    for key in ("faces", "edges"):
        for row in inputs[0][key].values():
            touched.update((key, t) for t in row["to"])
    out["created"] = {
        "faces": [i for i in range(out_maps["faces"].Extent()) if ("faces", i) not in touched],
        "edges": [i for i in range(out_maps["edges"].Extent()) if ("edges", i) not in touched],
    }
    if extra:
        out.update(extra)
    return out, None


def edge_specs(p, defaults):
    specs = []
    for item in p.get("edges") or []:
        spec = dict(item) if isinstance(item, dict) else {"edge": item}
        if "edge" not in spec:
            raise RuntimeError("An edge entry needs an edge index.")
        spec["edge"] = int(spec["edge"])
        for key in defaults:
            if spec.get(key) is None and p.get(key) is not None:
                spec[key] = p[key]
        specs.append(spec)
    return specs


def face_boundary_edges(sid, faces):
    shape = store.shape_of(sid)
    out = []
    for f in sub_items(sid, "faces", faces, "Face"):
        for e in sub_shapes(f, TopAbs_EDGE):
            idx = index_in(sid, "edges", e)
            if idx >= 0 and idx not in out and len(face_neighbours(shape, e)) > 1:
                out.append(idx)
    return out


def merge_selection(p, defaults):
    specs = edge_specs(p, defaults)
    known = {s["edge"] for s in specs}
    if p.get("faces"):
        base = {k: p.get(k) for k in defaults if p.get(k) is not None}
        for idx in face_boundary_edges(p["id"], p["faces"]):
            if idx not in known:
                specs.append({"edge": idx, **base})
                known.add(idx)
    if not specs:
        raise RuntimeError("Choose at least one edge or face.")
    return specs


def contour_report(maker, sid, count_fn=None):
    rows = []
    for ic in range(1, maker.NbContours() + 1):
        edges = []
        for j in range(1, maker.NbEdges(ic) + 1):
            edges.append(index_in(sid, "edges", maker.Edge(ic, j)))
        row = {"index": ic - 1, "edges": sorted(set(edges)), "closed": bool(maker.Closed(ic))}
        try:
            row["first_vertex"] = index_in(sid, "vertices", maker.FirstVertex(ic))
            row["last_vertex"] = index_in(sid, "vertices", maker.LastVertex(ic))
        except Exception:
            pass
        rows.append(row)
    return rows


def contour_warnings(maker, sid, label):
    shape = store.shape_of(sid)
    valence = edge_valence(shape)
    warnings = []
    for row in contour_report(maker, sid):
        if row["closed"]:
            continue
        for key in ("first_vertex", "last_vertex"):
            v = row.get(key)
            if v is not None and valence.get(v, 0) >= 4:
                warnings.append(issue("A chain of edges for the %s ends at a vertex where %d edges meet; the kernel does not handle that case and may fail." % (label, valence[v]), edges=row["edges"], vertices=[v], code="vertex_valence"))
    return warnings


def fillet_shape_of(name):
    return {"rational": ChFi3d_Rational, "quasi_angular": ChFi3d_QuasiAngular, "polynomial": ChFi3d_Polynomial}.get(str(name or "rational"), ChFi3d_Rational)


def build_fillet(p, sid, specs):
    shape = store.shape_of(sid)
    maker = BRepFilletAPI_MakeFillet(shape, fillet_shape_of(p.get("profile")))
    skipped = []
    for spec in specs:
        edge = sub_items(sid, "edges", [spec["edge"]], "Edge")[0]
        if maker.Contour(edge) > 0:
            skipped.append(spec["edge"])
            continue
        if spec.get("points"):
            pts = spec["points"]
            if len(pts) < 2:
                raise RuntimeError("A variable radius needs at least two (position, radius) pairs.")
            arr = Pnt2dArray(1, len(pts))
            for k, pair in enumerate(pts):
                if float(pair[1]) <= ops.MIN_SIZE:
                    raise RuntimeError("Every radius must be positive.")
                arr.SetValue(k + 1, gp_Pnt2d(float(pair[0]), float(pair[1])))
            maker.Add(arr, edge)
        elif spec.get("radius1") is not None and spec.get("radius2") is not None:
            r1, r2 = float(spec["radius1"]), float(spec["radius2"])
            if min(r1, r2) <= ops.MIN_SIZE:
                raise RuntimeError("Both radii must be positive.")
            maker.Add(r1, r2, edge)
        else:
            r = positive_number(spec, "radius")
            maker.Add(r, edge)
    return maker, skipped


def fillet_precheck_maker(p, specs):
    sid = p["id"]
    maker, skipped = build_fillet(p, sid, specs)
    warnings = contour_warnings(maker, sid, "fillet")
    return maker, skipped, warnings


def faulty_report(maker, sid):
    failed_edges, errors = [], []
    for k in range(1, maker.NbFaultyContours() + 1):
        ic = maker.FaultyContour(k)
        status = maker.StripeStatus(ic)
        edges = []
        for j in range(1, maker.NbEdges(ic) + 1):
            edges.append(index_in(sid, "edges", maker.Edge(ic, j)))
        text = STRIPE_TEXT.get(status, "the blend could not be computed")
        errors.append(issue("The blend failed on a chain of %d edge(s): %s." % (len(set(edges)), text), edges=edges, code="stripe_%s" % str(status).split(".")[-1].lower()))
        failed_edges.extend(edges)
    vertices = []
    for k in range(1, maker.NbFaultyVertices() + 1):
        try:
            vertices.append(index_in(sid, "vertices", maker.FaultyVertex(k)))
        except Exception:
            pass
    if vertices:
        errors.append(issue("The corner blend failed at %d vertex(es) where several rounded edges meet." % len(vertices), vertices=vertices, code="corner"))
    return errors, sorted(set(failed_edges))


def fillet(p):
    sid = p.get("id")
    shape = store.shape_of(sid)
    specs = merge_selection(p, ("radius", "radius1", "radius2", "points"))
    maker, skipped, warnings = fillet_precheck_maker(p, specs)
    if skipped:
        warnings.append(issue("%d selected edge(s) lie on a chain already rounded by an earlier entry; the first size was used." % len(skipped), edges=skipped, code="propagated"))
    contours = contour_report(maker, sid)
    selected = {s["edge"] for s in specs}
    propagated = sorted({e for c in contours for e in c["edges"]} - selected)
    if propagated:
        warnings.append(issue("The fillet follows tangent edges, so %d more edge(s) are rounded too." % len(propagated), edges=propagated, code="tangent_propagation"))
    try:
        maker.Build()
    except Exception as err:
        return failure("The fillet failed: %s." % (str(err) or "the kernel raised an error"), warnings=warnings, failed={"edges": sorted(selected), "faces": []})
    if not maker.IsDone() or maker.NbFaultyContours() > 0:
        errors, failed_edges = faulty_report(maker, sid)
        if not errors:
            errors = [issue("The fillet could not be built; try a smaller radius.", edges=sorted(selected))]
            failed_edges = sorted(selected)
        return failure(errors[0]["message"], errors, warnings, {"edges": failed_edges, "faces": []})
    result = maker.Shape()
    out, bad = finish(maker, sid, result, expect=lambda v0, v1: "The fillet changed nothing; the radius may be too small or the edge may be a smooth one." if abs(v1 - v0) <= 1e-9 else None)
    if out is None:
        return failure(bad, warnings=warnings, failed={"edges": sorted(selected), "faces": []})
    new_faces = []
    rows = []
    out_maps = store.maps_of(out["id"])
    for c in contours:
        ic = c["index"] + 1
        faces = []
        for j in range(1, maker.NbEdges(ic) + 1):
            for g in maker.Generated(maker.Edge(ic, j)):
                k = out_maps["faces"].FindIndex(g) - 1
                if k >= 0 and k not in faces:
                    faces.append(k)
        rows.append({**c, "faces": sorted(faces)})
        new_faces.extend(faces)
    out["contours"] = rows
    out["blend_faces"] = sorted(set(new_faces))
    out["warnings"] = warnings
    out["kind"] = "fillet"
    return out


def isolate_chamfer(p, sid, specs):
    failed = []
    shape = store.shape_of(sid)
    done = set()
    for spec in specs[:MAX_ISOLATE]:
        if spec["edge"] in done:
            continue
        try:
            m = BRepFilletAPI_MakeChamfer(shape)
            add_chamfer(m, sid, spec)
            m.Build()
            ok = m.IsDone()
            for ic in range(1, m.NbContours() + 1):
                for j in range(1, m.NbEdges(ic) + 1):
                    done.add(index_in(sid, "edges", m.Edge(ic, j)))
        except Exception:
            ok = False
        if not ok:
            failed.append(spec["edge"])
    return failed


def add_chamfer(maker, sid, spec):
    shape = store.shape_of(sid)
    edge = sub_items(sid, "edges", [spec["edge"]], "Edge")[0]
    d1 = positive_number(spec, "distance")
    d2 = spec.get("distance2")
    angle = spec.get("angle")
    if d2 is None and angle is None:
        maker.Add(d1, edge)
        return "distance"
    face = None
    if spec.get("face") is not None:
        face = sub_items(sid, "faces", [spec["face"]], "Face")[0]
        if not any(face.IsSame(f) for f in face_neighbours(shape, edge)):
            raise RuntimeError("Face %d does not touch edge %d." % (int(spec["face"]), spec["edge"]))
    else:
        near = face_neighbours(shape, edge)
        if not near:
            raise RuntimeError("Edge %d has no face." % spec["edge"])
        face = TopoDS.Face(near[0])
    if d2 is not None:
        d2 = positive_number(spec, "distance2")
        maker.Add(d1, d2, edge, face)
        return "two_distances"
    a = float(angle)
    if not math.isfinite(a) or a <= 0.0 or a >= 90.0:
        raise RuntimeError("The chamfer angle must be between 0 and 90 degrees.")
    maker.AddDA(d1, math.radians(a), edge, face)
    return "distance_angle"


def chamfer(p):
    sid = p.get("id")
    shape = store.shape_of(sid)
    specs = merge_selection(p, ("distance", "distance2", "angle", "face"))
    maker = BRepFilletAPI_MakeChamfer(shape)
    skipped, modes = [], {}
    for spec in specs:
        edge = sub_items(sid, "edges", [spec["edge"]], "Edge")[0]
        if maker.Contour(edge) > 0:
            skipped.append(spec["edge"])
            continue
        modes[spec["edge"]] = add_chamfer(maker, sid, spec)
    warnings = contour_warnings(maker, sid, "chamfer")
    if skipped:
        warnings.append(issue("%d selected edge(s) lie on a chain already chamfered by an earlier entry; the first size was used." % len(skipped), edges=skipped, code="propagated"))
    contours = contour_report(maker, sid)
    selected = {s["edge"] for s in specs}
    propagated = sorted({e for c in contours for e in c["edges"]} - selected)
    if propagated:
        warnings.append(issue("The chamfer follows tangent edges, so %d more edge(s) are cut too." % len(propagated), edges=propagated, code="tangent_propagation"))
    try:
        maker.Build()
        done = bool(maker.IsDone())
    except Exception:
        done = False
    if not done:
        bad = isolate_chamfer(p, sid, specs)
        names = bad or sorted(selected)
        message = "The chamfer failed on edge(s) %s; the distances are probably too large for the neighbouring faces." % ", ".join(str(i) for i in names)
        return failure(message, [issue(message, edges=names, code="chamfer_failed")], warnings, {"edges": names, "faces": []})
    result = maker.Shape()
    out, bad = finish(maker, sid, result, expect=lambda v0, v1: "The chamfer removed no material." if v1 >= v0 - 1e-9 else None)
    if out is None:
        return failure(bad, warnings=warnings, failed={"edges": sorted(selected), "faces": []})
    out_maps = store.maps_of(out["id"])
    rows, blend = [], []
    for c in contours:
        ic = c["index"] + 1
        faces = []
        for j in range(1, maker.NbEdges(ic) + 1):
            for g in maker.Generated(maker.Edge(ic, j)):
                k = out_maps["faces"].FindIndex(g) - 1
                if k >= 0 and k not in faces:
                    faces.append(k)
        rows.append({**c, "faces": sorted(faces)})
        blend.extend(faces)
    out.update({"contours": rows, "blend_faces": sorted(set(blend)), "warnings": warnings, "kind": "chamfer", "modes": {str(k): v for k, v in modes.items()}})
    return out


def shell_checks(p, sid):
    shape = store.shape_of(sid)
    errors, warnings = [], []
    maps = store.maps_of(sid)
    bad_c0, bad_low = [], []
    for i in range(maps["faces"].Extent()):
        face = TopoDS.Face(maps["faces"].FindKey(i + 1))
        problem = surface_problem(face)
        if problem == "c0":
            bad_c0.append(i)
        elif problem == "below_c1":
            bad_low.append(i)
    if bad_c0:
        errors.append(issue("Face(s) %s are spline surfaces with only point continuity; the offset cannot be built on them." % ", ".join(map(str, bad_c0)), faces=bad_c0, code="c0_bspline"))
    if bad_low:
        errors.append(issue("Face(s) %s are not smooth enough (below tangent continuity) for an offset." % ", ".join(map(str, bad_low)), faces=bad_low, code="below_c1"))
    valence = edge_valence(shape)
    heavy = [v for v, n in valence.items() if n > 3]
    if heavy:
        warnings.append(issue("%d vertex(es) have more than three edges; the offset may fail there." % len(heavy), vertices=heavy, code="vertex_valence"))
    box = store.bbox_of(shape)
    t = abs(float(p.get("thickness", 0.0) or 0.0))
    if box and t > 0 and p.get("direction", "inward") != "outward":
        smallest = min(box[3] - box[0], box[4] - box[1], box[5] - box[2])
        if t * 2.0 > smallest + 1e-9:
            warnings.append(issue("The wall thickness is more than half the smallest overall size of the body; the walls may meet or the result may fail.", code="thick_wall"))
    return errors, warnings


def precheck_shell(p):
    sid = p.get("id")
    errors, warnings = shell_checks(p, sid)
    remove = [int(i) for i in p.get("faces") or []]
    n = store.maps_of(sid)["faces"].Extent()
    for i in remove:
        if i < 0 or i >= n:
            errors.append(issue("Face %d is not in the shape." % i, code="bad_index"))
    try:
        positive_number(p, "thickness")
    except RuntimeError as err:
        errors.append(issue(str(err), code="thickness"))
    return errors, warnings


def shell(p):
    sid = p.get("id")
    shape = store.shape_of(sid)
    errors, warnings = precheck_shell(p)
    if errors:
        return failure(errors[0]["message"], errors, warnings, {"edges": [], "faces": sorted({f for e in errors for f in e.get("faces", [])})})
    thickness = positive_number(p, "thickness")
    outward = str(p.get("direction", "inward")) == "outward"
    join = GeomAbs_Intersection if str(p.get("join", "arc")) == "intersection" else GeomAbs_Arc
    remove_idx = sorted({int(i) for i in p.get("faces") or []})
    closing = ShapeList()
    for f in sub_items(sid, "faces", remove_idx, "Face"):
        closing.Append(f)
    maker = BRepOffsetAPI_MakeThickSolid()
    try:
        maker.MakeThickSolidByJoin(shape, closing, thickness if outward else -thickness, float(p.get("tolerance", 1e-4)), BRepOffset_Skin, False, False, join)
        maker.Build()
    except Exception as err:
        return failure("The shell failed: %s." % (str(err) or "the kernel could not offset these faces"), warnings=warnings, failed={"edges": [], "faces": remove_idx})
    if not maker.IsDone():
        return failure("The shell could not be built; try a thinner wall, other faces to remove, or the other join type.", warnings=warnings, failed={"edges": [], "faces": remove_idx})
    result = maker.Shape()
    sign = 1.0 if outward else -1.0

    def check(v0, v1):
        if v1 <= 1e-9:
            return "The shell has no volume; the wall is too thick for this body."
        if sign < 0 and v1 >= v0 - 1e-9:
            return "The shell did not remove material; the offset turned inside out, so use a thinner wall."
        return None

    out, bad = finish(maker, sid, result, expect=check)
    if out is None:
        return failure(bad, warnings=warnings, failed={"edges": [], "faces": remove_idx})
    out.update({"warnings": warnings, "kind": "shell", "removed_faces": remove_idx})
    return out


def draft_pre(p, sid):
    errors, warnings = [], []
    faces = [int(i) for i in p.get("faces") or []]
    if not faces:
        errors.append(issue("Choose at least one face to draft.", code="no_faces"))
    n = store.maps_of(sid)["faces"].Extent()
    bad_type, parallel, bad_index = [], [], []
    pull = p.get("pull") or [0, 0, 1]
    try:
        pd = ops.direction(pull)
    except RuntimeError as err:
        errors.append(issue(str(err), code="pull"))
        pd = None
    for i in faces:
        if i < 0 or i >= n:
            bad_index.append(i)
            continue
        face = TopoDS.Face(store.maps_of(sid)["faces"].FindKey(i + 1))
        ad = BRepAdaptor_Surface(face)
        kind = ad.GetType()
        if kind not in (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone):
            bad_type.append(i)
        elif kind == GeomAbs_Plane and pd is not None:
            nrm = ad.Plane().Axis().Direction()
            if abs(nrm.Dot(pd)) > 0.99995:
                parallel.append(i)
    if bad_index:
        errors.append(issue("Face(s) %s are not in the shape." % ", ".join(map(str, bad_index)), code="bad_index"))
    if bad_type:
        errors.append(issue("Face(s) %s cannot be drafted; only flat, cylindrical and conical faces can." % ", ".join(map(str, bad_type)), faces=bad_type, code="face_type"))
    if parallel:
        errors.append(issue("Face(s) %s face along the pull direction, so a draft would not tilt them." % ", ".join(map(str, parallel)), faces=parallel, code="face_parallel_pull"))
    try:
        a = float(p.get("angle"))
        if not math.isfinite(a) or abs(a) < 1e-9 or abs(a) >= 89.0:
            errors.append(issue("The draft angle must be non-zero and below 89 degrees.", code="angle"))
    except (TypeError, ValueError):
        errors.append(issue("The draft angle must be a number.", code="angle"))
    return errors, warnings


def neutral_plane(p):
    plane = p.get("neutral_plane") or {}
    origin = ops.pnt(plane.get("origin") or [0, 0, 0])
    normal = plane.get("normal") or p.get("pull") or [0, 0, 1]
    return gp_Pln(origin, ops.direction(normal))


def isolate_draft(sid, faces, pull, angle, plane, flag):
    shape = store.shape_of(sid)
    bad = []
    for i in faces[:MAX_ISOLATE]:
        try:
            m = BRepOffsetAPI_DraftAngle(shape)
            m.Add(sub_items(sid, "faces", [i], "Face")[0], pull, angle, plane, flag)
            ok = bool(m.AddDone())
            if ok:
                m.Build()
                ok = bool(m.IsDone())
        except Exception:
            ok = False
        if not ok:
            bad.append(i)
    return bad


def draft(p):
    sid = p.get("id")
    shape = store.shape_of(sid)
    errors, warnings = draft_pre(p, sid)
    if errors:
        return failure(errors[0]["message"], errors, warnings, {"edges": [], "faces": sorted({f for e in errors for f in e.get("faces", [])})})
    pull = ops.direction(p.get("pull") or [0, 0, 1])
    angle = math.radians(float(p["angle"]))
    plane = neutral_plane(p)
    maker = BRepOffsetAPI_DraftAngle(shape)
    failed, errs, connected = [], [], {}
    for i in sorted({int(f) for f in p["faces"]}):
        face = sub_items(sid, "faces", [i], "Face")[0]
        try:
            maker.Add(face, pull, angle, plane, bool(p.get("flag", True)))
            ok = bool(maker.AddDone())
        except Exception:
            ok = False
        if ok:
            try:
                connected[str(i)] = sorted(index_in(sid, "faces", f) for f in maker.ConnectedFaces(face))
            except Exception:
                pass
            continue
        where = []
        try:
            prob = maker.ProblematicShape()
            if not prob.IsNull():
                where = [k for k in (index_in(sid, "faces", f) for f in sub_shapes(prob, TopAbs_FACE)) if k >= 0]
        except Exception:
            where = []
        try:
            maker.Remove(face)
        except Exception:
            pass
        failed.append(i)
        errs.append(issue("Face %d could not be drafted: the neighbouring faces cannot absorb the tilt (status %s)." % (i, str(maker.Status()).split(".")[-1]), faces=[i] + where, code="draft_add"))
    if failed and not p.get("allow_partial"):
        return failure(errs[0]["message"], errs, warnings, {"edges": [], "faces": failed})
    if failed:
        warnings.extend(errs)
    try:
        maker.Build()
    except Exception as err:
        return failure("The draft failed: %s." % (str(err) or "the kernel could not rebuild the shape"), warnings=warnings, failed={"edges": [], "faces": failed})
    if not maker.IsDone():
        status = str(maker.Status()).split(".")[-1]
        asked = sorted({int(f) for f in p["faces"]} - set(failed))
        bad = isolate_draft(sid, asked, pull, angle, plane, bool(p.get("flag", True)))
        names = bad or asked
        message = "The draft could not be completed on face(s) %s (kernel status %s); the neighbouring faces cannot follow the tilt. Try a smaller angle or fewer faces." % (", ".join(map(str, names)), status)
        return failure(message, [issue(message, faces=names, code="draft_build")], warnings, {"edges": [], "faces": names})
    result = maker.Shape()
    out, bad = finish(maker, sid, result)
    if out is None:
        return failure(bad, warnings=warnings, failed={"edges": [], "faces": sorted(failed)})
    try:
        modified = sorted(index_in(sid, "faces", f) for f in maker.ModifiedFaces())
    except Exception:
        modified = []
    out.update({"warnings": warnings, "kind": "draft", "drafted_faces": modified, "connected": connected, "skipped_faces": failed})
    return out


def precheck(p):
    kind = str(p.get("kind", ""))
    sid = p.get("id")
    store.shape_of(sid)
    errors, warnings = [], []
    if kind in ("fillet", "chamfer"):
        specs = merge_selection(p, ("radius", "radius1", "radius2", "points", "distance", "distance2", "angle", "face"))
        shape = store.shape_of(sid)
        maker = BRepFilletAPI_MakeFillet(shape) if kind == "fillet" else BRepFilletAPI_MakeChamfer(shape)
        for spec in specs:
            edge = sub_items(sid, "edges", [spec["edge"]], "Edge")[0]
            if maker.Contour(edge) > 0:
                continue
            try:
                if kind == "fillet":
                    maker.Add(max(float(spec.get("radius") or spec.get("radius1") or 1.0), 1e-6), edge)
                else:
                    maker.Add(max(float(spec.get("distance") or 1.0), 1e-6), edge)
            except Exception as err:
                errors.append(issue(str(err), edges=[spec["edge"]]))
        warnings = contour_warnings(maker, sid, kind)
    elif kind == "shell":
        errors, warnings = precheck_shell(p)
    elif kind == "draft":
        errors, warnings = draft_pre(p, sid)
    elif kind in ("pattern", "mirror"):
        errors, warnings = [], []
    else:
        raise RuntimeError("Unknown feature kind %s." % kind)
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def instance_matrices(p):
    mode = str(p.get("pattern", ""))
    out = []
    if mode == "linear":
        dirs = p.get("directions") or []
        if not dirs or len(dirs) > 2:
            raise RuntimeError("A linear pattern needs one or two directions.")
        axes = []
        for d in dirs:
            v = d.get("vector")
            if not v or len(v) != 3:
                raise RuntimeError("A pattern direction needs a vector.")
            unit = ops.direction(v)
            count = int(d.get("count", 1))
            if count < 1:
                raise RuntimeError("The instance count must be at least 1.")
            if d.get("spacing") is not None:
                step = float(d["spacing"])
            elif d.get("length") is not None and count > 1:
                step = float(d["length"]) / (count - 1)
            else:
                step = 0.0
            if count > 1 and abs(step) <= ops.MIN_SIZE:
                raise RuntimeError("The spacing must not be zero.")
            axes.append((gp_Vec(unit), count, step))
        total = 1
        for _v, c, _s in axes:
            total *= c
        if total > MAX_INSTANCES:
            raise RuntimeError("A pattern is limited to %d instances." % MAX_INSTANCES)
        a = axes[0]
        b = axes[1] if len(axes) > 1 else (gp_Vec(0, 0, 0), 1, 0.0)
        k = 0
        for j in range(b[1]):
            for i in range(a[1]):
                t = gp_Trsf()
                v = a[0].Multiplied(a[2] * i).Added(b[0].Multiplied(b[2] * j))
                t.SetTranslation(v)
                out.append((k, t, {"i": i, "j": j}))
                k += 1
        return out
    if mode == "circular":
        ax = p.get("axis") or {}
        origin = ops.pnt(ax.get("origin") or [0, 0, 0])
        axis = gp_Ax1(origin, ops.direction(ax.get("direction") or [0, 0, 1]))
        count = int(p.get("count", 1))
        if count < 1 or count > MAX_INSTANCES:
            raise RuntimeError("The instance count must be between 1 and %d." % MAX_INSTANCES)
        total = float(p.get("angle", 360.0))
        if p.get("step") is not None:
            step = float(p["step"])
        elif abs(abs(total) - 360.0) < 1e-9:
            step = total / count
        else:
            step = total / (count - 1) if count > 1 else 0.0
        if count > 1 and abs(step) <= 1e-9:
            raise RuntimeError("The angle between instances must not be zero.")
        for k in range(count):
            t = gp_Trsf()
            t.SetRotation(axis, math.radians(step * k))
            out.append((k, t, {"i": k, "j": 0}))
        return out
    raise RuntimeError("The pattern kind must be linear or circular.")


def mirror_trsf(p):
    plane = p.get("plane") or {}
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(ops.pnt(plane.get("origin") or [0, 0, 0]), ops.direction(plane.get("normal"))))
    return t


def copy_with_history(seed_id, trsf):
    seed = store.shape_of(seed_id)
    maker = BRepBuilderAPI_Transform(seed, trsf, True)
    if not maker.IsDone():
        raise RuntimeError("An instance could not be placed.")
    shape = maker.Shape()
    ident = store.put(shape)
    hist = ops.input_history(maker, seed, store.maps_of(seed_id), store.maps_of(ident))
    return ident, shape, hist


def compose(first, second):
    out = {}
    for key in ("faces", "edges"):
        rows = {}
        for src, row in first[key].items():
            to = []
            for mid in row["to"]:
                for fin in (second[key].get(str(mid)) or {"to": []})["to"]:
                    if fin not in to:
                        to.append(fin)
            rows[src] = {"to": to, "deleted": not to}
        out[key] = rows
    return out


def combine(base_id, instance_ids, op, unify=True):
    cls = BRepAlgoAPI_Cut if op == "cut" else BRepAlgoAPI_Fuse
    args = ShapeList()
    args.Append(store.shape_of(base_id))
    tools = ShapeList()
    for i in instance_ids:
        tools.Append(store.shape_of(i))
    maker = cls()
    maker.SetArguments(args)
    maker.SetTools(tools)
    maker.SetRunParallel(True)
    maker.SetNonDestructive(True)
    maker.SetToFillHistory(True)
    maker.Build()
    if not maker.IsDone():
        return maker, None
    if unify:
        maker.SimplifyResult(True, True, 1e-6)
    return maker, maker.Shape()


def cleanup(ids):
    store.free(ids)


def apply_instances(p, label):
    base_id = p.get("id")
    seed_id = p.get("seed")
    if not base_id or not seed_id:
        raise RuntimeError("A %s needs a body (id) and a seed shape." % label)
    store.shape_of(base_id)
    store.shape_of(seed_id)
    return base_id, seed_id


def finish_combined(p, base_id, instance_ids, seed_hist, op, extra):
    maker, result = combine(base_id, instance_ids, op, bool(p.get("unify", True)))
    if result is None or not valid_solid(result):
        cleanup(instance_ids)
        return failure("The %s could not be combined with the body; an instance may touch it only along an edge or miss it." % extra["kind"], warnings=extra.get("warnings"))
    v0 = volume_of(store.shape_of(base_id))
    v1 = volume_of(result)
    if op == "cut" and v1 >= v0 - 1e-9:
        cleanup(instance_ids)
        return failure("No instance removes material from the body; check that the seed overlaps it.", warnings=extra.get("warnings"))
    if op == "fuse" and v1 <= v0 + 1e-9:
        cleanup(instance_ids)
        return failure("No instance adds material to the body; check that the seed touches it.", warnings=extra.get("warnings"))
    ident = store.put(result)
    out_maps = store.maps_of(ident)
    inputs = [{"id": base_id, "role": "base", **ops.input_history(maker, store.shape_of(base_id), store.maps_of(base_id), out_maps)}]
    mapped = {}
    for k, iid in zip(extra["instance_index"], instance_ids):
        hist = ops.input_history(maker, store.shape_of(iid), store.maps_of(iid), out_maps)
        inputs.append({"id": iid, "role": "instance", "instance": k, **hist})
        mapped[str(k)] = compose(seed_hist[k], hist)
    out = {"ok": True, "id": ident, "summary": store.summarize(result), "history": {"inputs": inputs}, "instance_faces": mapped, "errors": [], "failed": {"edges": [], "faces": []}}
    out.update({k: v for k, v in extra.items() if k != "instance_index"})
    touched = set()
    for key in ("faces", "edges"):
        for inp in inputs:
            for row in inp[key].values():
                touched.update((key, t) for t in row["to"])
    out["created"] = {"faces": [i for i in range(out_maps["faces"].Extent()) if ("faces", i) not in touched], "edges": [i for i in range(out_maps["edges"].Extent()) if ("edges", i) not in touched]}
    cleanup(instance_ids)
    return out


def pattern(p):
    base_id, seed_id = apply_instances(p, "pattern")
    op = str(p.get("op", "fuse"))
    if op not in ("fuse", "cut", "copies"):
        raise RuntimeError("A pattern op is fuse, cut or copies.")
    rows = instance_matrices(p)
    skip = {int(i) for i in p.get("skip") or []}
    warnings = []
    made, indexes, seed_hist, shapes = [], [], {}, []
    for k, trsf, label in rows:
        if (k == 0 and not p.get("include_seed")) or k in skip:
            continue
        ident, shape, hist = copy_with_history(seed_id, trsf)
        made.append(ident)
        indexes.append(k)
        seed_hist[k] = hist
        shapes.append(shape)
    skipped = sorted(i for i in skip if i < len(rows) and i != 0)
    if skipped:
        warnings.append(issue("%d instance(s) are skipped." % len(skipped), code="skipped"))
    if op == "copies":
        out_rows = []
        for k, ident in zip(indexes, made):
            out_rows.append({"instance": k, "id": ident, "summary": store.summarize(store.shape_of(ident)), "history": {"inputs": [{"id": seed_id, **seed_hist[k]}]}})
        return {"ok": True, "kind": "pattern", "copies": out_rows, "instance_count": len(rows), "warnings": warnings, "errors": [], "failed": {"edges": [], "faces": []}}
    if not made:
        return failure("The pattern has no instance besides the seed.", warnings=warnings)
    seed_op = "cut" if op == "cut" else "fuse"
    return finish_combined(p, base_id, made, seed_hist, seed_op, {"kind": "pattern", "warnings": warnings, "instance_index": indexes, "instance_count": len(rows)})


def mirror(p):
    base_id = p.get("id")
    store.shape_of(base_id)
    mode = str(p.get("mode", "feature"))
    trsf = mirror_trsf(p)
    if mode == "body":
        source = p.get("seed") or base_id
        ident, shape, hist = copy_with_history(source, trsf)
        if not valid_solid(shape):
            cleanup([ident])
            return failure("The mirrored copy is not a valid solid.")
        if not p.get("merge"):
            return {"ok": True, "kind": "mirror", "mode": "body", "id": ident, "summary": store.summarize(shape), "history": {"inputs": [{"id": source, **hist}]}, "errors": [], "warnings": [], "failed": {"edges": [], "faces": []}}
        maker, result = combine(base_id, [ident], "fuse", bool(p.get("unify", True)))
        if result is None or not valid_solid(result):
            cleanup([ident])
            return failure("The mirrored body could not be merged; it must overlap or touch the original along a face.")
        out_ident = store.put(result)
        out_maps = store.maps_of(out_ident)
        mh = ops.input_history(maker, store.shape_of(ident), store.maps_of(ident), out_maps)
        inputs = [{"id": base_id, "role": "base", **ops.input_history(maker, store.shape_of(base_id), store.maps_of(base_id), out_maps)}, {"id": ident, "role": "instance", "instance": 1, **mh}]
        cleanup([ident])
        return {"ok": True, "kind": "mirror", "mode": "body", "id": out_ident, "summary": store.summarize(result), "history": {"inputs": inputs}, "instance_faces": {"1": compose(hist, mh)}, "errors": [], "warnings": [], "failed": {"edges": [], "faces": []}}
    seed_id = p.get("seed")
    if not seed_id:
        raise RuntimeError("A feature mirror needs the seed shape of the feature.")
    store.shape_of(seed_id)
    op = str(p.get("op", "fuse"))
    if op not in ("fuse", "cut"):
        raise RuntimeError("A feature mirror op is fuse or cut.")
    ident, _shape, hist = copy_with_history(seed_id, trsf)
    return finish_combined(p, base_id, [ident], {1: hist}, op, {"kind": "mirror", "mode": "feature", "warnings": [], "instance_index": [1]})


def feature_precheck(p):
    return precheck(p)


METHODS = {
    "feature_fillet": fillet,
    "feature_chamfer": chamfer,
    "feature_shell": shell,
    "feature_draft": draft,
    "feature_pattern": pattern,
    "feature_mirror": mirror,
    "feature_precheck": feature_precheck,
}
