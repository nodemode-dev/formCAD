import io
import math

from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer, BOPAlgo_BOP, BOPAlgo_COMMON, BOPAlgo_CUT, BOPAlgo_FUSE
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_NoError
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GeomAbs import GeomAbs_C1, GeomAbs_C2
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.ShapeFix import ShapeFix_Shape
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.collections import Array1_gp_Pnt2d
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as AncestorMap
from OCP.gp import gp_Pnt2d

import kernel_store as store
from kernel_ops import input_history
from kernel_surf import TopoDS, finish, kind_edges, tol_audit, tolerances

OPS = {"fuse": BOPAlgo_FUSE, "cut": BOPAlgo_CUT, "common": BOPAlgo_COMMON}
MAX_LISTED = 200
MAX_POLY_POINTS = 400


def edge_polyline(edge, tol):
    ad = BRepAdaptor_Curve(edge)
    first, last = ad.FirstParameter(), ad.LastParameter()
    if not (math.isfinite(first) and math.isfinite(last)):
        return []
    try:
        disc = GCPnts_QuasiUniformDeflection(ad, max(tol * 5.0, 1e-3), first, last)
        if disc.IsDone() and disc.NbPoints() >= 2:
            n = min(disc.NbPoints(), MAX_POLY_POINTS)
            return [[disc.Value(i + 1).X(), disc.Value(i + 1).Y(), disc.Value(i + 1).Z()] for i in range(n)]
    except Exception:
        pass
    pts = [ad.Value(first + (last - first) * i / 16.0) for i in range(17)]
    return [[q.X(), q.Y(), q.Z()] for q in pts]


def free_edge_polylines(shape, tol):
    out = []
    try:
        fb = ShapeAnalysis_FreeBounds(shape, max(tol, 1e-6), False, False)
    except Exception:
        return out
    for group in (fb.GetClosedWires(), fb.GetOpenWires()):
        for edge in kind_edges(group, TopAbs_EDGE):
            if len(out) >= MAX_LISTED:
                return out
            out.append(edge_polyline(TopoDS.Edge_s(edge), tol))
    return out


def status_names(analyzer, shape):
    out = []
    for kind in (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_SOLID):
        ex = TopExp_Explorer(shape, kind)
        seen = store.ShapeMap()
        while ex.More():
            sub = ex.Current()
            if seen.FindIndex(sub) == 0:
                seen.Add(sub)
                res = analyzer.Result(sub)
                if res is not None:
                    names = []
                    try:
                        for st in res.Status():
                            if st != BRepCheck_NoError:
                                names.append(st.name)
                    except Exception:
                        pass
                    if names and len(out) < MAX_LISTED:
                        kind_name = {TopAbs_FACE: "face", TopAbs_EDGE: "edge", TopAbs_VERTEX: "vertex", TopAbs_SOLID: "solid"}[kind]
                        out.append({"kind": kind_name, "statuses": sorted(set(names))})
            ex.Next()
    return out


def check_shape(shape):
    try:
        analyzer = BRepCheck_Analyzer(shape, True)
    except Exception:
        return {"valid": False, "invalid": [{"kind": "shape", "statuses": ["CheckFail"]}]}
    valid = bool(analyzer.IsValid())
    return {"valid": valid, "invalid": [] if valid else status_names(analyzer, shape)}


def small_edges(shape, tol):
    out = []
    m = store.build_maps(shape)["edges"]
    for i in range(1, m.Extent() + 1):
        e = TopoDS.Edge_s(m.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        ad = BRepAdaptor_Curve(e)
        try:
            from OCP.GCPnts import GCPnts_AbscissaPoint

            length = GCPnts_AbscissaPoint.Length_s(ad)
        except Exception:
            continue
        if length < tol and len(out) < MAX_LISTED:
            out.append({"index": i - 1, "length": length})
    return out


ANALYZER_MODES = ("ArgumentTypeMode", "SelfInterMode", "SmallEdgeMode", "RebuildFaceMode", "TangentMode", "MergeVertexMode", "MergeEdgeMode", "ContinuityMode", "CurveOnSurfaceMode")


def run_analyzer(shape_a, shape_b, fuzzy):
    an = BOPAlgo_ArgumentAnalyzer()
    an.SetShape1(shape_a)
    if shape_b is not None:
        an.SetShape2(shape_b)
    an.SetFuzzyValue(fuzzy)
    for name in ANALYZER_MODES:
        setattr(an, name, True)
    an.Perform()
    found = []
    for r in an.GetCheckResult():
        found.append({"status": r.GetCheckStatus().name, "faulty_first": len(list(r.GetFaultyShapes1())), "faulty_second": len(list(r.GetFaultyShapes2())), "max_distance": r.GetMaxDistance1()})
    return found


def classify(found):
    out = {"self_intersections": [], "small_edges": [], "other": []}
    for f in found:
        s = f["status"]
        if "SelfIntersect" in s:
            out["self_intersections"].append(f)
        elif "TooSmallEdge" in s:
            out["small_edges"].append(f)
        else:
            out["other"].append(f)
    return out


def alert_names(maker):
    names = {"errors": [], "warnings": [], "error_text": "", "warning_text": ""}
    from OCP.Message import Message_Gravity

    rep = maker.GetReport()
    for grav, key in ((Message_Gravity.Message_Fail, "errors"), (Message_Gravity.Message_Warning, "warnings")):
        for alert in rep.GetAlerts(grav):
            names[key].append(str(alert.GetMessageKey()))
    buf = io.BytesIO()
    maker.DumpErrors(buf)
    names["error_text"] = buf.getvalue().decode("utf-8", "replace").strip()
    buf = io.BytesIO()
    maker.DumpWarnings(buf)
    names["warning_text"] = buf.getvalue().decode("utf-8", "replace").strip()
    return names


class Chain:
    def __init__(self, first, unify):
        self.first = first
        self.unify = unify
        self.hist = unify.History() if unify is not None else None

    def _map(self, shapes):
        if self.hist is None:
            return shapes
        out = []
        for s in shapes:
            if self.hist.IsRemoved(s):
                continue
            nxt = list(self.hist.Modified(s))
            out.extend(nxt if nxt else [s])
        return out

    def IsDeleted(self, s):
        return bool(self.first.IsDeleted(s))

    def Modified(self, s):
        return self._map(list(self.first.Modified(s)) or ([] if self.first.IsDeleted(s) else [s]))

    def Generated(self, s):
        return self._map(list(self.first.Generated(s)))


def fix_shape(shape, tol):
    fx = ShapeFix_Shape(shape)
    fx.SetPrecision(tol)
    fx.SetMaxTolerance(tol * 10.0)
    fx.Perform()
    return fx.Shape()


def run_boolean(op, base, tools, fuzzy):
    mk = BOPAlgo_BOP()
    mk.AddArgument(base)
    for t in tools:
        mk.AddTool(t)
    mk.SetOperation(OPS[op])
    mk.SetFuzzyValue(fuzzy)
    mk.SetRunParallel(True)
    mk.SetNonDestructive(True)
    mk.SetToFillHistory(True)
    mk.Perform()
    return mk


def boolean_report(p):
    tol, ang = tolerances(p)
    op = str(p.get("op", ""))
    if op not in OPS:
        raise RuntimeError("op is fuse, cut or common.")
    base_id = str(p.get("base", ""))
    tool_ids = [str(t) for t in (p.get("tools") or [])]
    if not base_id or not tool_ids:
        raise RuntimeError("A boolean needs a base and at least one tool.")
    fuzzy = float(p["fuzzy"]) if p.get("fuzzy") is not None else tol
    base = store.shape_of(base_id)
    tools = [store.shape_of(t) for t in tool_ids]
    record = {"op": op, "tol": tol, "angtol": ang, "fuzzy": fuzzy, "arguments": [], "ladder": []}
    found = []
    for i, shape in enumerate([base] + tools):
        entry = {"id": ([base_id] + tool_ids)[i], **check_shape(shape)}
        entry["small_edges"] = small_edges(shape, tol)
        entry["naked_edges"] = free_edge_polylines(shape, tol)
        record["arguments"].append(entry)
    for t in tools:
        found.extend(run_analyzer(base, t, fuzzy))
    record["analysis"] = classify(found)
    if bool(p.get("check_only", False)):
        record["performed"] = False
        record["ok"] = not found and all(a["valid"] for a in record["arguments"])
        return record
    cap = float(p.get("max_fuzzy", tol))
    steps = [("as given", base, tools, fuzzy)]
    if bool(p.get("retry", True)):
        steps.append(("inputs repaired", fix_shape(base, tol), [fix_shape(t, tol) for t in tools], fuzzy))
        if cap > fuzzy:
            steps.append(("larger fuzzy value", fix_shape(base, tol), [fix_shape(t, tol) for t in tools], min(cap, fuzzy * 10.0)))
    chosen = None
    for label, b, ts, fz in steps:
        mk = run_boolean(op, b, ts, fz)
        alerts = alert_names(mk)
        step = {"step": label, "fuzzy": fz, "has_errors": bool(mk.HasErrors()), "has_warnings": bool(mk.HasWarnings()), "alerts": alerts}
        record["ladder"].append(step)
        if not mk.HasErrors() and not mk.Shape().IsNull():
            chosen = (mk, b, ts, fz, label)
            break
    if chosen is None:
        record["performed"] = True
        record["ok"] = False
        last = record["ladder"][-1]["alerts"]
        record["message"] = "The boolean operation failed (%s)." % ("; ".join(last["errors"]) or "no result")
        return record
    mk, b, ts, fz, label = chosen
    result = mk.Shape()
    unify = None
    if bool(p.get("unify", True)):
        unify = ShapeUpgrade_UnifySameDomain(result, True, True, False)
        unify.SetLinearTolerance(max(tol, 1e-6))
        unify.SetAngularTolerance(max(ang, 1e-6))
        unify.Build()
        result = unify.Shape()
    record["fuzzy_used"] = fz
    record["performed"] = True
    record["warnings"] = record["ladder"][-1]["alerts"]["warnings"]
    record["warning_text"] = record["ladder"][-1]["alerts"]["warning_text"]
    check = check_shape(result)
    record["result"] = {**check, "small_edges": small_edges(result, tol), "naked_edges": free_edge_polylines(result, tol)}
    if store.count_of(result, TopAbs_SOLID) == 0 and store.count_of(result, TopAbs_FACE) == 0:
        record["ok"] = False
        record["message"] = "The result is empty; the shapes may not overlap."
        return record
    ident = store.put(result)
    out_maps = store.maps_of(ident)
    inputs = []
    if label == "as given":
        chain = Chain(mk, unify)
        for sid, src in zip([base_id] + tool_ids, [base] + tools):
            inputs.append({"id": sid, **input_history(chain, src, store.maps_of(sid), out_maps)})
    record["repaired"] = label != "as given"
    record["ok"] = check["valid"]
    record["audit"] = tol_audit(result, tol)
    record["result"]["summary"] = store.summarize(result)
    out = {"id": ident, "summary": store.summarize(result), "report": record}
    if inputs:
        out["history"] = {"inputs": inputs}
    return out


def boolean_diag(p):
    out = boolean_report(p)
    if "id" in out:
        return out
    return {"id": None, "report": out}


def edges_of(shape_id, indices):
    m = store.maps_of(shape_id)["edges"]
    out = []
    for i in indices:
        i = int(i)
        if not 0 <= i < m.Extent():
            raise RuntimeError("The edge index is outside the shape.")
        out.append(TopoDS.Edge_s(m.FindKey(i + 1)))
    if not out:
        raise RuntimeError("Select at least one edge.")
    return out


def finish_edges(op, shape_id, maker, tol, ang, report):
    if not maker.IsDone():
        raise RuntimeError("The %s failed; the edges may be too short for the size, or meet at a corner the kernel cannot round." % op)
    result = maker.Shape()
    src = store.shape_of(shape_id)
    ident_maps = store.build_maps(result)
    hist = {"inputs": [{"id": shape_id, **input_history(maker, src, store.maps_of(shape_id), ident_maps)}]}
    check = check_shape(result)
    report = dict(report)
    report["valid"] = check["valid"]
    report["invalid"] = check["invalid"]
    return finish(op, result, tol, ang, report, hist)


def fillet_edge(p):
    tol, ang = tolerances(p)
    sid = str(p["id"])
    shape = store.shape_of(sid)
    edges = edges_of(sid, p.get("edges") or [])
    mk = BRepFilletAPI_MakeFillet(shape)
    cont = str(p.get("continuity", "g1")).lower()
    mk.SetContinuity(GeomAbs_C2 if cont in ("g2", "c2") else GeomAbs_C1, ang)
    radii = p.get("radii")
    for e in edges:
        if radii and len(radii) >= 2:
            pts = Array1_gp_Pnt2d(1, len(radii))
            for i, r in enumerate(radii):
                pts.SetValue(i + 1, gp_Pnt2d(float(r[0]), float(r[1])))
            mk.Add(pts, e)
        elif p.get("radius2") is not None:
            mk.Add(float(p["radius"]), float(p["radius2"]), e)
        else:
            r = float(p["radius"])
            if r <= tol:
                raise RuntimeError("The radius must be larger than the tolerance.")
            mk.Add(r, e)
    mk.Build()
    return finish_edges("fillet_edge", sid, mk, tol, ang, {"edges": len(edges), "continuity": "g2" if cont in ("g2", "c2") else "g1"})


def chamfer_edge(p):
    tol, ang = tolerances(p)
    sid = str(p["id"])
    shape = store.shape_of(sid)
    edges = edges_of(sid, p.get("edges") or [])
    mk = BRepFilletAPI_MakeChamfer(shape)
    ancestors = AncestorMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)
    d1 = float(p["distance"])
    if d1 <= tol:
        raise RuntimeError("The distance must be larger than the tolerance.")
    for e in edges:
        faces = ancestors.FindFromKey(e)
        if faces.Extent() < 1:
            raise RuntimeError("An edge has no face to measure from.")
        face = TopoDS.Face_s(faces.First())
        if p.get("angle") is not None:
            mk.AddDA(d1, math.radians(float(p["angle"])), e, face)
        elif p.get("distance2") is not None:
            mk.Add(d1, float(p["distance2"]), e, face)
        else:
            mk.Add(d1, e)
    mk.Build()
    return finish_edges("chamfer_edge", sid, mk, tol, ang, {"edges": len(edges)})


def naked(p):
    tol, ang = tolerances(p)
    shape = store.shape_of(p["id"])
    return {"naked_edges": free_edge_polylines(shape, tol), "check": check_shape(shape), "small_edges": small_edges(shape, tol), "audit": tol_audit(shape, tol)}


METHODS = {"bool_diag": boolean_diag, "fillet_edge": fillet_edge, "chamfer_edge": chamfer_edge, "surf_naked": naked}
