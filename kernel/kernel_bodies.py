import math

from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Splitter
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
from OCP.TopAbs import TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.collections import List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

import kernel_ops as ops
import kernel_store as store

CONFUSION = 1e-7
MAX_PIECES = 4096

STATUS_TEXT = {
    "SelfIntersect": "the body intersects itself",
    "SmallEdge": "the body has an edge that is too small",
    "BadType": "a body is not a solid or shell the operation can use",
    "NotValid": "the body is not a valid shape",
    "RebuildFace": "a face of the body cannot be rebuilt",
    "TangentFaces": "two bodies touch along tangent faces",
    "CurveOnSurfaceMismatch": "an edge does not lie on its face",
    "InvalidCurveOnSurface": "an edge does not lie on its face",
    "NotValidCurve": "an edge has bad geometry",
    "C0": "a face joins its neighbour with a break in continuity",
}


def shapes_list(items):
    out = ShapeList()
    for s in items:
        out.Append(s)
    return out


def status_name(raw) -> str:
    text = str(raw)
    return text.split(".")[-1].replace("BOPAlgo_", "")


def friendly(name: str) -> str:
    key = name[3:] if name.startswith("Bad") and name not in STATUS_TEXT else name
    return STATUS_TEXT.get(name) or STATUS_TEXT.get(key) or ("a geometry problem (%s)" % name)


def analyse_arguments(first, second=None) -> list:
    problems = {}
    for a, b in ((first, second),) if second is not None else ((first, None),):
        an = BOPAlgo_ArgumentAnalyzer()
        an.SetShape1(a)
        if b is not None:
            an.SetShape2(b)
        an.ArgumentTypeMode = True
        an.SelfInterMode = True
        an.SmallEdgeMode = True
        an.RebuildFaceMode = True
        an.TangentMode = b is not None
        an.ContinuityMode = True
        an.CurveOnSurfaceMode = True
        an.StopOnFirstFaulty = False
        an.Perform()
        if an.HasFaulty():
            for res in an.GetCheckResult():
                name = status_name(res.GetCheckStatus())
                problems[name] = problems.get(name, 0) + 1
    return [{"status": k, "count": v, "message": friendly(k)} for k, v in sorted(problems.items())]


def solids_of(shape) -> list:
    out = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        out.append(exp.Current())
        exp.Next()
    return out


def check_result(shape, label: str) -> None:
    if not BRepCheck_Analyzer(shape).IsValid():
        raise RuntimeError("The %s is not a valid solid, so it was not kept." % label)


def run_boolean(op: str, base, tools, fuzzy: float):
    cls = {"add": BRepAlgoAPI_Fuse, "subtract": BRepAlgoAPI_Cut, "common": BRepAlgoAPI_Common}[op]
    maker = cls()
    maker.SetArguments(shapes_list([base]))
    maker.SetTools(shapes_list(tools))
    maker.SetRunParallel(True)
    maker.SetNonDestructive(True)
    maker.SetFuzzyValue(max(fuzzy, CONFUSION))
    maker.SetToFillHistory(True)
    maker.Build()
    return maker


def has_errors(maker) -> bool:
    probe = getattr(maker, "HasErrors", None)
    return bool(probe()) if callable(probe) else False


def report_text(maker) -> str:
    probe = getattr(maker, "DumpErrorsToString", None)
    if not callable(probe):
        return ""
    try:
        return str(probe()).strip()[:200]
    except Exception:
        return ""


def combine(p):
    op = str(p.get("op", ""))
    if op not in ("add", "subtract", "common"):
        raise RuntimeError("Combine needs op add, subtract or common.")
    ids = [str(i) for i in (p.get("bodies") or [])]
    if len(ids) < 2 or len(set(ids)) != len(ids):
        raise RuntimeError("Combine needs at least two different bodies.")
    shapes = [store.shape_of(i) for i in ids]
    fuzzy = float(p.get("fuzzy", CONFUSION) or CONFUSION)
    diagnostics = {"fuzzy": max(fuzzy, CONFUSION), "retried": False, "arguments": [], "pairs": []}
    if p.get("analyze", True):
        for i, s in zip(ids, shapes):
            for row in analyse_arguments(s):
                diagnostics["arguments"].append({"id": i, **row})
        for i, s in zip(ids[1:], shapes[1:]):
            for row in analyse_arguments(shapes[0], s):
                if row["status"] == "TangentFaces":
                    diagnostics["pairs"].append({"id": i, **row})
        if diagnostics["arguments"] and not p.get("force"):
            first = diagnostics["arguments"][0]
            raise RuntimeError("The kernel cannot combine these bodies: %s." % first["message"])
    maker = run_boolean(op, shapes[0], shapes[1:], fuzzy)
    failed = (not maker.IsDone()) or has_errors(maker)
    result = None if failed else maker.Shape()
    if (failed or result is None or (not solids_of(result) and op != "subtract")) and p.get("retry", True):
        bigger = max(fuzzy * 100.0, 1e-5)
        retry = run_boolean(op, shapes[0], shapes[1:], bigger)
        if retry.IsDone() and not has_errors(retry) and solids_of(retry.Shape()):
            maker, failed, result = retry, False, retry.Shape()
            diagnostics.update(retried=True, fuzzy=bigger)
    if failed or result is None:
        raise RuntimeError("The combine failed (%s)." % (report_text(maker) or "the kernel could not resolve the overlap"))
    if p.get("unify", True):
        maker.SimplifyResult(True, True, 1e-6)
        result = maker.Shape()
    if not solids_of(result):
        raise RuntimeError("The result is empty: the bodies do not overlap that way.")
    check_result(result, "result")
    ident = store.put(result)
    out_maps = store.maps_of(ident)
    inputs = [{"id": sid, **ops.input_history(maker, store.shape_of(sid), store.maps_of(sid), out_maps)} for sid in ids]
    return {"id": ident, "summary": store.summarize(result), "history": {"inputs": inputs}, "diagnostics": diagnostics}


def plane_tool(spec, reach: float):
    origin = spec.get("origin") or [0, 0, 0]
    pln = gp_Pln(ops.pnt(origin), ops.direction(spec.get("normal")))
    return BRepBuilderAPI_MakeFace(pln, -reach, reach, -reach, reach).Face()


def split(p):
    ident = str(p.get("body"))
    body = store.shape_of(ident)
    box = store.bbox_of(body)
    if box is None:
        raise RuntimeError("The body has no extent.")
    centre = [(box[i] + box[i + 3]) / 2.0 for i in range(3)]
    diag = math.dist(box[:3], box[3:])
    tools = []
    for spec in p.get("planes") or []:
        o = spec.get("origin") or [0, 0, 0]
        reach = 4.0 * diag + math.dist(o, centre) + 1.0
        tools.append(plane_tool(spec, reach))
    for tid in p.get("tools") or []:
        tools.append(store.shape_of(tid))
    if not tools:
        raise RuntimeError("Split needs a plane or a surface to cut with.")
    if p.get("analyze", True):
        bad = analyse_arguments(body)
        if bad and not p.get("force"):
            raise RuntimeError("The kernel cannot split this body: %s." % bad[0]["message"])
    fuzzy = max(float(p.get("fuzzy", CONFUSION) or CONFUSION), CONFUSION)
    maker = BRepAlgoAPI_Splitter()
    maker.SetArguments(shapes_list([body]))
    maker.SetTools(shapes_list(tools))
    maker.SetRunParallel(True)
    maker.SetNonDestructive(True)
    maker.SetFuzzyValue(fuzzy)
    maker.SetToFillHistory(True)
    maker.Build()
    if not maker.IsDone() or has_errors(maker):
        raise RuntimeError("The split failed (%s)." % (report_text(maker) or "the kernel could not cut here"))
    pieces = solids_of(maker.Shape())
    if len(pieces) < 2:
        raise RuntimeError("The cutting surface does not pass through the body, so nothing was split.")
    if len(pieces) > MAX_PIECES:
        raise RuntimeError("The split would make more than %d pieces." % MAX_PIECES)
    src_maps = store.maps_of(ident)
    out = []
    for piece in pieces:
        check_result(piece, "piece")
        pid = store.put(piece)
        out.append({"id": pid, "summary": store.summarize(piece), **ops.input_history(maker, body, src_maps, store.maps_of(pid))})
    return {"pieces": out, "diagnostics": {"fuzzy": fuzzy}}


def vec(v):
    return [v.X(), v.Y(), v.Z()]


def face_geometry(maps, index: int) -> dict:
    face = TopoDS.Face(maps["faces"].FindKey(index + 1))
    ad = BRepAdaptor_Surface(face)
    kind = ad.GetType()
    flip = face.Orientation() == TopAbs_REVERSED
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, area)
    c = area.CentreOfMass()
    out = {"centroid": [c.X(), c.Y(), c.Z()], "area": area.Mass()}
    if kind == GeomAbs_Plane:
        pos = ad.Plane().Position()
        n = pos.Direction()
        sign = -1.0 if flip else 1.0
        out.update(kind="plane", origin=[c.X(), c.Y(), c.Z()], normal=[sign * n.X(), sign * n.Y(), sign * n.Z()], xdir=vec(pos.XDirection()))
    elif kind == GeomAbs_Cylinder:
        ax = ad.Cylinder().Axis()
        out.update(kind="cylinder", axis_origin=vec(ax.Location()), axis=vec(ax.Direction()), radius=ad.Cylinder().Radius())
    elif kind == GeomAbs_Cone:
        ax = ad.Cone().Axis()
        out.update(kind="cone", axis_origin=vec(ax.Location()), axis=vec(ax.Direction()), radius=ad.Cone().RefRadius())
    elif kind == GeomAbs_Sphere:
        sp = ad.Sphere()
        out.update(kind="sphere", centre=vec(sp.Location()), radius=sp.Radius())
    elif kind == GeomAbs_Torus:
        t = ad.Torus()
        out.update(kind="torus", centre=vec(t.Location()), axis=vec(t.Axis().Direction()), major=t.MajorRadius(), minor=t.MinorRadius())
    else:
        out.update(kind="other")
    return out


def edge_geometry(maps, index: int) -> dict:
    edge = TopoDS.Edge(maps["edges"].FindKey(index + 1))
    ad = BRepAdaptor_Curve(edge)
    a, b = ad.Value(ad.FirstParameter()), ad.Value(ad.LastParameter())
    m = ad.Value((ad.FirstParameter() + ad.LastParameter()) / 2.0)
    out = {"start": [a.X(), a.Y(), a.Z()], "end": [b.X(), b.Y(), b.Z()], "mid": [m.X(), m.Y(), m.Z()]}
    kind = ad.GetType()
    if kind == GeomAbs_Line:
        out.update(kind="line", direction=vec(ad.Line().Direction()))
    elif kind == GeomAbs_Circle:
        circ = ad.Circle()
        out.update(kind="circle", centre=vec(circ.Location()), axis=vec(circ.Axis().Direction()), radius=circ.Radius())
    else:
        out.update(kind="other")
    return out


def vertex_geometry(maps, index: int) -> dict:
    v = TopoDS.Vertex(maps["vertices"].FindKey(index + 1))
    p = BRep_Tool.Pnt_s(v)
    return {"kind": "vertex", "point": [p.X(), p.Y(), p.Z()]}


def geometry(p):
    maps = store.maps_of(p.get("id"))
    for key, fn, mapname in (("face", face_geometry, "faces"), ("edge", edge_geometry, "edges"), ("vertex", vertex_geometry, "vertices")):
        if p.get(key) is not None:
            index = int(p[key])
            if not 0 <= index < maps[mapname].Extent():
                raise RuntimeError("The %s index %d is outside the body." % (key, index))
            return fn(maps, index)
    raise RuntimeError("Give face, edge or vertex.")


def inertia_rows(props):
    m = props.MatrixOfInertia()
    return [[m.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)]


def body_props(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    eps = float(p.get("eps", 1e-9))
    summary = store.summarize(shape)
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, area, eps, False)
    out = {"area": area.Mass(), "solids": summary["solids"], "closed": summary["closed"], "valid": summary["valid"], "volume": None, "centroid": None, "inertia": None, "principal": None, "axes": None}
    if summary["solids"] == 0:
        out["note"] = "The body has no solid, so it has no volume."
        return out
    if not summary["closed"] or not summary["valid"]:
        out["note"] = "The body is not a closed valid solid, so the volume is not reported."
        return out
    vol = GProp_GProps()
    err = BRepGProp.VolumeProperties_s(shape, vol, eps, False, False)
    c = vol.CentreOfMass()
    pr = vol.PrincipalProperties()
    out.update(
        volume=vol.Mass(),
        centroid=[c.X(), c.Y(), c.Z()],
        inertia=inertia_rows(vol),
        principal=list(pr.Moments()),
        axes=[vec(pr.FirstAxisOfInertia()), vec(pr.SecondAxisOfInertia()), vec(pr.ThirdAxisOfInertia())],
        error=err,
    )
    return out


METHODS = {"combine": combine, "split": split, "geometry": geometry, "body_props": body_props}
