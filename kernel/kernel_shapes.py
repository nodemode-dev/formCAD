import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_CompCurve, BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeSolid,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_RightCorner,
    BRepBuilderAPI_RoundCorner,
    BRepBuilderAPI_Sewing,
    BRepBuilderAPI_Transform,
    BRepBuilderAPI_Transformed,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFill import BRepFill_Contact, BRepFill_ContactOnBorder, BRepFill_NoContact
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle, BRepOffsetAPI_MakeFilling, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.GC import GC_MakeArcOfCircle
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GProp import GProp_GProps
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.GeomAbs import GeomAbs_C0, GeomAbs_C1
from OCP.Law import Law_Linear
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_SOLID, TopAbs_WIRE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS as _TopoDS
from OCP.collections import HArray1_gp_Pnt, HSequence_TopoDS_Shape, List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec

import kernel_feat as feat
import kernel_ops as ops
import kernel_store as store


class TopoDS:
    Edge_s = staticmethod(_TopoDS.Edge)
    Face_s = staticmethod(_TopoDS.Face)
    Wire_s = staticmethod(_TopoDS.Wire)
    Shell_s = staticmethod(_TopoDS.Shell)
    Vertex_s = staticmethod(_TopoDS.Vertex)


MIN_SIZE = 1e-7
MAX_STATIONS = 400
MAX_SECTIONS = 64
MAX_HOLES = 5000
MODES = ("corrected_frenet", "frenet", "fixed", "binormal", "auxiliary")
CORNERS = {"transformed": BRepBuilderAPI_Transformed, "right": BRepBuilderAPI_RightCorner, "round": BRepBuilderAPI_RoundCorner}
CONTACTS = {"none": BRepFill_NoContact, "contact": BRepFill_Contact, "border": BRepFill_ContactOnBorder}
SOLID_TOL = 1e-6


def num(p, key, default=None, lo=None, hi=None):
    v = p.get(key, default)
    if v is None:
        raise RuntimeError("%s is required." % key)
    v = float(v)
    if not math.isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise RuntimeError("%s is out of range." % key)
    return v


def volume_of(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def shell_area(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props.Mass()


def wire_from_edges(edges):
    maker = BRepBuilderAPI_MakeWire()
    for e in edges:
        maker.Add(e)
    if maker.IsDone():
        return maker.Wire()
    wires = connect_edges(edges, 1e-6)
    if len(wires) != 1:
        raise RuntimeError("The curves do not join into one connected chain.")
    return wires[0]


def connect_edges(edges, tolerance):
    seq = HSequence_TopoDS_Shape()
    for e in edges:
        seq.Append(e)
    out = HSequence_TopoDS_Shape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq, tolerance, False, out)
    return [TopoDS.Wire_s(out.Value(i)) for i in range(1, out.Length() + 1)]


def open_chain(vertices, ax, closed=False):
    loc = ax.Location()
    xd, yd = ax.XDirection(), ax.YDirection()

    def to3(x, y):
        return gp_Pnt(loc.X() + x * xd.X() + y * yd.X(), loc.Y() + x * xd.Y() + y * yd.Y(), loc.Z() + x * xd.Z() + y * yd.Z())

    n = len(vertices)
    if n < 2:
        raise RuntimeError("A path needs at least two vertices.")
    edges = []
    last = n if closed else n - 1
    for i in range(last):
        a, b = vertices[i], vertices[(i + 1) % n]
        pa, pb = to3(float(a[0]), float(a[1])), to3(float(b[0]), float(b[1]))
        if pa.Distance(pb) <= MIN_SIZE:
            continue
        bulge = float(a[2]) if len(a) > 2 else 0.0
        if abs(bulge) > 1e-12:
            chord = pa.Distance(pb)
            sag = abs(bulge) * chord / 2.0
            dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
            ln = math.hypot(dx, dy)
            sign = 1.0 if bulge > 0 else -1.0
            mid = to3((float(a[0]) + float(b[0])) / 2.0 + sign * dy / ln * sag, (float(a[1]) + float(b[1])) / 2.0 - sign * dx / ln * sag)
            arc = GC_MakeArcOfCircle(pa, mid, pb)
            if not arc.IsDone():
                raise RuntimeError("An arc segment of the path is degenerate.")
            edges.append(BRepBuilderAPI_MakeEdge(arc.Value()).Edge())
        else:
            edges.append(BRepBuilderAPI_MakeEdge(pa, pb).Edge())
    if not edges:
        raise RuntimeError("The path has no length.")
    return wire_from_edges(edges)


def spline_edge(points, tangents=None, closed=False):
    pts = [ops.pnt(q) for q in points]
    if len(pts) < 2:
        raise RuntimeError("A spline needs at least two points.")
    arr = HArray1_gp_Pnt(1, len(pts))
    for i, q in enumerate(pts):
        arr.SetValue(i + 1, q)
    it = GeomAPI_Interpolate(arr, bool(closed), 1e-7)
    if tangents and len(tangents) == 2 and not closed:
        it.Load(gp_Vec(*[float(c) for c in tangents[0]]), gp_Vec(*[float(c) for c in tangents[1]]), True)
    it.Perform()
    if not it.IsDone():
        raise RuntimeError("The spline through the points could not be built.")
    return BRepBuilderAPI_MakeEdge(it.Curve()).Edge()


def segment_edges(segments):
    edges = []
    for seg in segments:
        if "line" in seg:
            a, b = seg["line"]
            edges.append(BRepBuilderAPI_MakeEdge(ops.pnt(a), ops.pnt(b)).Edge())
        elif "arc" in seg:
            a, m, b = seg["arc"]
            arc = GC_MakeArcOfCircle(ops.pnt(a), ops.pnt(m), ops.pnt(b))
            if not arc.IsDone():
                raise RuntimeError("An arc of the curve is degenerate.")
            edges.append(BRepBuilderAPI_MakeEdge(arc.Value()).Edge())
        elif "spline" in seg:
            s = seg["spline"]
            edges.append(spline_edge(s.get("points") or [], s.get("tangents"), s.get("closed", False)))
        elif "circle" in seg:
            c = seg["circle"]
            r = float(c["r"])
            if r <= MIN_SIZE:
                raise RuntimeError("A circle in the curve has no radius.")
            edges.append(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(ops.pnt(c["c"]), ops.direction(c.get("normal"))), r)).Edge())
        else:
            raise RuntimeError("A curve segment must be a line, arc, spline or circle.")
    if not edges:
        raise RuntimeError("The curve has no segments.")
    return edges


def curve_wire(spec):
    if not isinstance(spec, dict):
        raise RuntimeError("A curve is described by an object.")
    if spec.get("shape"):
        shape = store.shape_of(spec["shape"])
        if shape.ShapeType() == TopAbs_WIRE:
            return TopoDS.Wire_s(shape)
        m = store.build_maps(shape)["edges"]
        return wire_from_edges([TopoDS.Edge_s(m.FindKey(i)) for i in range(1, m.Extent() + 1)])
    if spec.get("segments"):
        return wire_from_edges(segment_edges(spec["segments"]))
    if spec.get("nurbs"):
        import kernel_curves

        return wire_from_edges([BRepBuilderAPI_MakeEdge(kernel_curves.to_geom(spec["nurbs"])).Edge()])
    if spec.get("vertices"):
        return open_chain(spec["vertices"], ops.to_plane(spec), bool(spec.get("closed", False)))
    if spec.get("frame"):
        ax = frame_of(spec)
        loops = spec.get("open") or []
        if loops:
            return feat.build_wire(ax, loops[0], None)[0]
        regions = spec.get("regions") or []
        if regions:
            return feat.build_wire(ax, regions[0]["outer"], None)[0]
    raise RuntimeError("A curve needs a shape, segments, vertices or a sketch profile.")


def frame_of(spec):
    return feat.frame_ax2(spec.get("frame") or spec.get("plane"))


def sketch_open(spec):
    loops = spec.get("open")
    return bool(loops) and isinstance(loops[0], dict) and "segs" in loops[0]


def open_profile(spec):
    if sketch_open(spec):
        ax = frame_of(spec)
        return ax, feat.build_wire(ax, spec["open"][0], None)[0]
    ax = ops.to_plane(spec)
    return ax, open_chain(spec["open"], ax, False)


def side_name(role):
    role = role or "side"
    return role if role.startswith("side:") or role == "side" else "side:" + role


def wire_names(spec, ax, wires, prefix="L"):
    out = []
    loops = None
    if spec.get("regions"):
        region = spec["regions"][0]
        loops = [region["outer"]] + list(region.get("holes") or [])
    elif sketch_open(spec):
        loops = list(spec["open"])
    for i, w in enumerate(wires):
        if loops and i < len(loops):
            names = [side_name(role) for _e, role in feat.edge_roles_for(ax, w, feat.labels_of(loops[i]), False)]
        else:
            names = ["side:%s%d:E%d" % (prefix, i, j) for j in range(len(wire_edges(w)))]
        out.append(names)
    return out


def profile_loops(spec):
    if spec.get("regions"):
        ax = frame_of(spec)
        regions = spec["regions"]
        if len(regions) != 1:
            raise RuntimeError("The profile must be one closed region.")
        region = regions[0]
        wires = [feat.build_wire(ax, region["outer"], None)[0]]
        wires.extend(feat.build_wire(ax, h, None)[0] for h in region.get("holes") or [])
        return ax, wires
    ax = ops.to_plane(spec)
    loops = spec.get("loops") or []
    outers = [lp for lp in loops if lp.get("outer", True)]
    holes = [lp for lp in loops if not lp.get("outer", True)]
    if not outers:
        raise RuntimeError("The profile has no outer loop.")
    if len(outers) > 1:
        raise RuntimeError("The profile has more than one outer loop.")
    return ax, [ops.loop_wire(outers[0], ax)] + [ops.loop_wire(h, ax) for h in holes]


def wire_edges(wire):
    m = store.build_maps(wire)["edges"]
    return [TopoDS.Edge_s(m.FindKey(i)) for i in range(1, m.Extent() + 1)]


def wire_center(wire):
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(wire, props)
    c = props.CentreOfMass()
    return c


def face_center(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.CentreOfMass()


def finish_solid(shape, what):
    solids = store.count_of(shape, TopAbs_SOLID)
    if solids == 0:
        raise RuntimeError("The %s did not close into a solid." % what)
    if volume_of(shape) < 0:
        shape = shape.Reversed()
    return shape


def clean_check(shape, what):
    if not BRepCheck_Analyzer(shape).IsValid():
        raise RuntimeError("The %s produced an invalid shape; adjust the profile, path or sections." % what)


def side_origin(maker, solid, profile_edges, names, start, end):
    fmap = store.build_maps(solid)["faces"]
    origins = {}
    for j, e in enumerate(profile_edges):
        for g in maker.Generated(e):
            idx = fmap.FindIndex(g)
            if idx > 0:
                origins[idx - 1] = names[j]
    for i in range(1, fmap.Extent() + 1):
        if (i - 1) in origins:
            continue
        c = face_center(TopoDS.Face_s(fmap.FindKey(i)))
        origins[i - 1] = "cap:start" if c.Distance(start) <= c.Distance(end) else "cap:end"
    return origins


def role_pairs(shape, origins):
    fmap = store.build_maps(shape)["faces"]
    return [(TopoDS.Face_s(fmap.FindKey(idx + 1)), role) for idx, role in sorted(origins.items()) if idx + 1 <= fmap.Extent()]


def feature_result(p, tool, origins, warnings, what, extra=None):
    op = str(p.get("op", "add"))
    if op not in ("add", "cut", "new"):
        raise RuntimeError("op must be add, cut or new.")
    base_id = p.get("id")
    if op == "new" or not base_id:
        base_id, base = None, None
        if op == "cut":
            raise RuntimeError("There is no body to cut yet.")
    else:
        base = store.shape_of(base_id)
    build = feat.combine(base_id, base, tool, role_pairs(tool, origins or {}), "cut" if op == "cut" else "add", what)
    out = build()
    out["warnings"] = list(out.get("warnings") or []) + list(warnings or [])
    if extra:
        out.update(extra)
    return out


def merge_origins(final, parts, maker=None):
    fmap = store.build_maps(final)["faces"]
    out = {}
    for solid, origins in parts:
        smap = store.build_maps(solid)["faces"]
        for i in range(1, smap.Extent() + 1):
            face = smap.FindKey(i)
            targets = []
            if maker is not None:
                if maker.IsDeleted(face):
                    continue
                targets = [fmap.FindIndex(m) - 1 for m in maker.Modified(face) if fmap.FindIndex(m) > 0]
            if not targets:
                idx = fmap.FindIndex(face)
                if idx > 0:
                    targets = [idx - 1]
            for t in targets:
                out.setdefault(t, origins.get(i - 1, "face"))
    return out


def origins_list(final, origins):
    count = store.count_of(final, TopAbs_FACE)
    return [origins.get(i, "face") for i in range(count)]


def combine_loops(solids, maker_class=BRepAlgoAPI_Cut):
    outer = solids[0]
    if len(solids) == 1:
        return outer, None
    args = ShapeList()
    args.Append(outer)
    tools = ShapeList()
    for h in solids[1:]:
        tools.Append(h)
    cut = maker_class()
    cut.SetArguments(args)
    cut.SetTools(tools)
    cut.SetToFillHistory(True)
    cut.Build()
    if not cut.IsDone():
        raise RuntimeError("The inner loops of the profile could not be cut from the outer loop.")
    return cut.Shape(), cut


def result_payload(shape, origins, extra):
    ident = store.put(shape)
    out = {"id": ident, "summary": store.summarize(shape), "origins": origins_list(shape, origins) if origins is not None else None}
    out.update(extra)
    return out


def spine_samples(spine, count):
    curve = BRepAdaptor_CompCurve(spine)
    first, last = curve.FirstParameter(), curve.LastParameter()
    pts, tans, params = [], [], []
    for i in range(count + 1):
        u = first + (last - first) * i / count
        p = gp_Pnt()
        d = gp_Vec()
        curve.D1(u, p, d)
        if d.Magnitude() <= MIN_SIZE:
            raise RuntimeError("The path has a zero-length tangent.")
        pts.append(p)
        tans.append(d.Normalized())
        params.append(u)
    return pts, tans


def twisted_guide(spine, twist_deg, reference, reach, stations):
    pts, tans = spine_samples(spine, stations)
    lengths = [0.0]
    for i in range(1, len(pts)):
        lengths.append(lengths[-1] + pts[i].Distance(pts[i - 1]))
    total = lengths[-1]
    if total <= MIN_SIZE:
        raise RuntimeError("The path has no length.")
    ref = reference
    t0 = tans[0]
    ref = ref.Subtracted(t0.Multiplied(ref.Dot(t0)))
    if ref.Magnitude() <= 1e-9:
        ref = gp_Vec(1, 0, 0).Crossed(t0) if abs(t0.X()) < 0.9 else gp_Vec(0, 1, 0).Crossed(t0)
    n = ref.Normalized()
    arr = HArray1_gp_Pnt(1, len(pts))
    for i, (p, t) in enumerate(zip(pts, tans)):
        if i:
            n = n.Subtracted(t.Multiplied(n.Dot(t)))
            if n.Magnitude() <= 1e-9:
                raise RuntimeError("The path turns back on itself; the twist frame is lost.")
            n = n.Normalized()
        b = t.Crossed(n)
        a = math.radians(twist_deg) * lengths[i] / total
        q = gp_Pnt(
            p.X() + reach * (math.cos(a) * n.X() + math.sin(a) * b.X()),
            p.Y() + reach * (math.cos(a) * n.Y() + math.sin(a) * b.Y()),
            p.Z() + reach * (math.cos(a) * n.Z() + math.sin(a) * b.Z()),
        )
        arr.SetValue(i + 1, q)
    it = GeomAPI_Interpolate(arr, False, 1e-7)
    it.Perform()
    if not it.IsDone():
        raise RuntimeError("The twist guide could not be built.")
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(it.Curve()).Edge()).Wire()


def sweep_options(p):
    mode = str(p.get("mode", "corrected_frenet"))
    if mode not in MODES:
        raise RuntimeError("Unknown sweep mode %s." % mode)
    transition = str(p.get("transition", "transformed"))
    if transition not in CORNERS:
        raise RuntimeError("Unknown corner transition %s." % transition)
    contact = str(p.get("guide_contact", "none"))
    if contact not in CONTACTS:
        raise RuntimeError("Unknown guide contact %s." % contact)
    twist = num(p, "twist", 0.0, -36000.0, 36000.0)
    scale_end = num(p, "scale_end", 1.0, 1e-3, 1000.0)
    if mode == "auxiliary" and not p.get("guide"):
        raise RuntimeError("The auxiliary-spine mode needs a guide curve.")
    if p.get("guide") and mode != "auxiliary":
        mode = "auxiliary"
    return mode, transition, contact, twist, scale_end


def configure_pipe(pipe, p, mode, transition, contact, twist, scale_end, spine, ax, reach, warnings):
    pipe.SetTolerance(num(p, "tolerance", 1e-6, 1e-9, 1.0), num(p, "tolerance", 1e-6, 1e-9, 1.0), num(p, "angular_tolerance", 1e-3, 1e-6, 0.5))
    pipe.SetMaxDegree(int(num(p, "max_degree", 11, 3, 25)))
    pipe.SetMaxSegments(int(num(p, "max_segments", 60, 1, 500)))
    pipe.SetTransitionMode(CORNERS[transition])
    if transition == "right" and abs(scale_end - 1.0) > 1e-12:
        warnings.append("A right-corner transition can fail when the section is scaled along the path.")
    if mode == "frenet":
        pipe.SetMode(True)
    elif mode == "corrected_frenet":
        pipe.SetMode(False)
    elif mode == "fixed":
        pipe.SetMode(ax)
    elif mode == "binormal":
        pipe.SetMode(ops.direction(p.get("binormal")))
    elif mode == "auxiliary":
        if p.get("guide"):
            pipe.SetMode(curve_wire(p["guide"]), bool(p.get("guide_equivalence", False)), CONTACTS[contact])
            if contact != "none":
                warnings.append("A guide curve held in contact with the section gives a surface that is only C0 continuous.")
            if abs(twist) > 1e-12:
                warnings.append("The twist is ignored because the guide curve defines the section rotation.")
        else:
            raise RuntimeError("The auxiliary-spine mode needs a guide curve.")
    elif mode == "twist":
        pass


def sweep_tool(p):
    pspec = p.get("profile")
    if not pspec:
        raise RuntimeError("A sweep needs a profile.")
    spine = curve_wire(p.get("path") or {})
    mode, transition, contact, twist, scale_end = sweep_options(p)
    warnings = []
    spine_start = BRepAdaptor_CompCurve(spine).Value(BRepAdaptor_CompCurve(spine).FirstParameter())
    spine_end = BRepAdaptor_CompCurve(spine).Value(BRepAdaptor_CompCurve(spine).LastParameter())
    as_solid = bool(p.get("solid", True))
    if pspec.get("open") and not pspec.get("regions") and not pspec.get("loops"):
        ax, wire = open_profile(pspec)
        wires = [wire]
        as_solid = False
    else:
        ax, wires = profile_loops(pspec)
    names = wire_names(pspec, ax, wires)
    use_guide_twist = abs(twist) > 1e-12 and not p.get("guide") and mode in ("corrected_frenet", "frenet", "fixed", "binormal")
    guide_wire = None
    if use_guide_twist:
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(wires[0], props)
        reach = max(1.0, 2.0 * math.sqrt(max(shell_area(BRepBuilderAPI_MakeFace(gp_Pln(ax.Location(), ax.Direction()), wires[0]).Face()), 1e-6)) + 1.0) if as_solid else 10.0
        guide_wire = twisted_guide(spine, twist, gp_Vec(ax.XDirection()), reach, int(num(p, "twist_stations", 96, 8, MAX_STATIONS)))
    solids, parts = [], []
    edges_by_loop = [wire_edges(w) for w in wires]
    for i, w in enumerate(wires):
        pipe = BRepOffsetAPI_MakePipeShell(spine)
        eff_mode = mode
        if guide_wire is not None:
            pipe.SetTolerance(1e-6, 1e-6, 1e-3)
            pipe.SetMaxDegree(int(num(p, "max_degree", 11, 3, 25)))
            pipe.SetMaxSegments(int(num(p, "max_segments", 60, 1, 500)))
            pipe.SetTransitionMode(CORNERS[transition])
            pipe.SetMode(guide_wire, False, BRepFill_NoContact)
        else:
            configure_pipe(pipe, p, eff_mode, transition, contact, twist, scale_end, spine, ax, 0.0, warnings if i == 0 else [])
        with_contact = bool(p.get("with_contact", False))
        with_correction = bool(p.get("with_correction", transition == "round"))
        if abs(scale_end - 1.0) > 1e-12:
            law = Law_Linear()
            law.Set(0.0, 1.0, 1.0, scale_end)
            pipe.SetLaw(w, law, with_contact, with_correction)
        else:
            pipe.Add(w, with_contact, with_correction)
        pipe.Build()
        if not pipe.IsDone():
            raise RuntimeError("The sweep failed (%s)." % str(pipe.GetStatus()).split(".")[-1])
        if as_solid:
            if not pipe.MakeSolid():
                raise RuntimeError("The sweep did not close into a solid; the profile must be a closed loop.")
        shape = pipe.Shape()
        if as_solid:
            shape = finish_solid(shape, "sweep")
            parts.append((shape, side_origin(pipe, shape, edges_by_loop[i], names[i], spine_start, spine_end)))
        else:
            smap = store.build_maps(shape)["faces"]
            o = {}
            for j, e in enumerate(edges_by_loop[i]):
                for g in pipe.Generated(e):
                    idx = smap.FindIndex(g)
                    if idx > 0:
                        o[idx - 1] = names[i][j]
            parts.append((shape, o))
        solids.append(shape)
    if as_solid:
        final, cut = combine_loops(solids)
        origins = merge_origins(final, parts, cut)
    else:
        final = solids[0]
        origins = parts[0][1]
    clean_check(final, "sweep")
    extra = {"warnings": warnings, "mode": "twisted_guide" if guide_wire is not None else mode, "twist": twist, "scale_end": scale_end}
    if as_solid:
        extra["volume"] = volume_of(final)
    return final, origins, extra


def sweep(p):
    final, origins, extra = sweep_tool(p)
    return result_payload(final, origins, extra)


def feat_sweep(p):
    final, origins, extra = sweep_tool(p)
    if not extra.get("volume"):
        raise RuntimeError("A sweep feature needs a closed profile.")
    return feature_result(p, final, origins, extra.pop("warnings", []), "sweep", {"sweep": {k: v for k, v in extra.items() if k != "volume"}})


def sample_wire(wire, deflection):
    out = []
    for e in wire_edges(wire):
        curve = BRepAdaptor_Curve(e)
        disc = GCPnts_QuasiUniformDeflection(curve, deflection)
        if not disc.IsDone():
            continue
        out.append([[disc.Value(k).X(), disc.Value(k).Y(), disc.Value(k).Z()] for k in range(1, disc.NbPoints() + 1)])
    return out


def sweep_preview(p):
    pspec = p.get("profile")
    if not pspec:
        raise RuntimeError("A sweep needs a profile.")
    spine = curve_wire(p.get("path") or {})
    mode, transition, contact, twist, scale_end = sweep_options(p)
    warnings = []
    if pspec.get("open") and not pspec.get("regions") and not pspec.get("loops"):
        ax, wire = open_profile(pspec)
    else:
        ax, wires = profile_loops(pspec)
        wire = wires[0]
    pipe = BRepOffsetAPI_MakePipeShell(spine)
    guide = None
    if abs(twist) > 1e-12 and not p.get("guide") and mode in ("corrected_frenet", "frenet", "fixed", "binormal"):
        guide = twisted_guide(spine, twist, gp_Vec(ax.XDirection()), 10.0, int(num(p, "twist_stations", 96, 8, MAX_STATIONS)))
        pipe.SetMode(guide, False, BRepFill_NoContact)
    else:
        configure_pipe(pipe, p, mode, transition, contact, twist, scale_end, spine, ax, 0.0, warnings)
    if abs(scale_end - 1.0) > 1e-12:
        law = Law_Linear()
        law.Set(0.0, 1.0, 1.0, scale_end)
        pipe.SetLaw(wire, law, bool(p.get("with_contact", False)), bool(p.get("with_correction", False)))
    else:
        pipe.Add(wire, bool(p.get("with_contact", False)), bool(p.get("with_correction", False)))
    count = int(num(p, "sections", 12, 2, MAX_SECTIONS))
    res = ShapeList()
    pipe.Simulate(count, res)
    defl = num(p, "deflection", 0.1, 1e-4, 100.0)
    return {"sections": [sample_wire(TopoDS.Wire_s(w), defl) for w in res], "warnings": warnings}


def loop_inners(spec):
    ax, wires = profile_loops(spec)
    return wires


def section_wires(spec):
    if spec.get("point"):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex

        return None, BRepBuilderAPI_MakeVertex(ops.pnt(spec["point"])).Vertex(), []
    if spec.get("loops") or spec.get("regions"):
        ax, wires = profile_loops(spec)
        return ax, wires[0], wires[1:]
    return None, curve_wire(spec), []


def translated(shape, v):
    t = gp_Trsf()
    t.SetTranslation(v)
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def end_condition(cond, first_wire, ax, here, there, reverse):
    if not cond:
        return None
    kind = cond.get("kind", "none")
    if kind in ("none", None):
        return None
    mag = num(cond, "magnitude", 0.3, 0.01, 2.0)
    towards = gp_Vec(here, there)
    dist = towards.Magnitude()
    if dist <= MIN_SIZE:
        return None
    if kind == "normal":
        if ax is None:
            raise RuntimeError("A normal end condition needs a planar section.")
        d = gp_Vec(ax.Direction())
        if d.Dot(towards) < 0:
            d.Reverse()
    elif kind == "direction":
        d = gp_Vec(ops.direction(cond.get("direction")))
    else:
        raise RuntimeError("Unknown loft end condition %s." % kind)
    if d.Magnitude() <= MIN_SIZE:
        return None
    return translated(first_wire, d.Normalized().Multiplied(mag * dist))


def loft_tool(p):
    specs = p.get("sections") or []
    if len(specs) < 2 or len(specs) > MAX_SECTIONS:
        raise RuntimeError("A loft needs between two and %d sections." % MAX_SECTIONS)
    ruled = bool(p.get("ruled", False))
    as_solid = bool(p.get("solid", True))
    built = [section_wires(s) for s in specs]
    inner_counts = {len(b[2]) for b in built if b[1].ShapeType() != 0}
    if len({len(b[2]) for b in built if b[0] is not None or b[2]}) > 1:
        raise RuntimeError("Every section needs the same number of inner loops.")
    warnings = []
    if p.get("guides"):
        warnings.append("Guide curves were not applied: the loft algorithm of the kernel accepts sections only. The loft interpolates the sections.")
    for b in built[1:-1]:
        if b[1].ShapeType() == 7:
            raise RuntimeError("A point section can only be the first or last section.")
    centers = []
    for ax, w, _h in built:
        centers.append(wire_center(w) if w.ShapeType() == TopAbs_WIRE else BRep_Tool.Pnt_s(TopoDS.Vertex_s(w)))

    def build(index_set, tolerance):
        gen = BRepOffsetAPI_ThruSections(as_solid, ruled, tolerance)
        gen.CheckCompatibility(bool(p.get("check_compatibility", True)))
        if not ruled:
            gen.SetSmoothing(bool(p.get("smoothing", True)))
            gen.SetMaxDegree(int(num(p, "max_degree", 8, 2, 25)))
        extras = {}
        seq = []
        for k in index_set:
            seq.append((k, built[k][1], built[k][0]))
        if not ruled:
            start = end_condition(p.get("start"), built[0][1], built[0][0], centers[0], centers[1], False) if built[0][1].ShapeType() == TopAbs_WIRE else None
            end = end_condition(p.get("end"), built[-1][1], built[-1][0], centers[-1], centers[-2], True) if built[-1][1].ShapeType() == TopAbs_WIRE else None
            if start is not None and index_set[0] == 0:
                seq.insert(1, (-1, start, None))
            if end is not None and index_set[-1] == len(built) - 1:
                seq.insert(len(seq) - 1, (-2, end, None))
        for _k, w, _ax in seq:
            if w.ShapeType() == TopAbs_WIRE:
                gen.AddWire(TopoDS.Wire_s(w))
            else:
                gen.AddVertex(TopoDS.Vertex_s(w))
        gen.Build()
        if not gen.IsDone():
            raise RuntimeError("The loft failed; check that the sections are compatible and in a sensible order.")
        return gen

    tol = num(p, "tolerance", 1e-6, 1e-9, 1.0)
    outer_gen = build(list(range(len(built))), tol)
    outer = outer_gen.Shape()
    start_c, end_c = centers[0], centers[-1]
    first_edges = wire_edges(built[0][1]) if built[0][1].ShapeType() == TopAbs_WIRE else []
    if as_solid:
        outer = finish_solid(outer, "loft")
    origins = {}
    fmap = store.build_maps(outer)["faces"]
    first_names = wire_names(specs[0], built[0][0], [built[0][1]])[0] if first_edges and built[0][0] is not None else ["side:L0:E%d" % j for j in range(len(first_edges))]
    for j, e in enumerate(first_edges):
        try:
            g = outer_gen.GeneratedFace(e)
        except Exception:
            continue
        idx = fmap.FindIndex(g)
        if idx > 0:
            origins[idx - 1] = first_names[j]
    for i in range(1, fmap.Extent() + 1):
        if (i - 1) not in origins:
            c = face_center(TopoDS.Face_s(fmap.FindKey(i)))
            origins[i - 1] = "cap:start" if c.Distance(start_c) <= c.Distance(end_c) else "cap:end"
    final = outer
    if as_solid and built[0][2]:
        count = len(built[0][2])
        parts = [(outer, origins)]
        tools = []
        for h in range(count):
            hole_specs = []
            for ax, w, inner in built:
                hole_specs.append(inner[h])
            gen = BRepOffsetAPI_ThruSections(True, ruled, tol)
            gen.CheckCompatibility(True)
            if not ruled:
                gen.SetSmoothing(bool(p.get("smoothing", True)))
            for w in hole_specs:
                gen.AddWire(TopoDS.Wire_s(w))
            gen.Build()
            if not gen.IsDone():
                raise RuntimeError("An inner loop of the loft failed.")
            tools.append(finish_solid(gen.Shape(), "inner loft"))
            tmap = store.build_maps(tools[-1])["faces"]
            parts.append((tools[-1], {k: "side:hole%d" % h for k in range(tmap.Extent())}))
        final, cut = combine_loops([outer] + tools)
        origins = merge_origins(final, parts, cut)
    clean_check(final, "loft")
    extra = {"warnings": warnings, "ruled": ruled, "guides_applied": False}
    if as_solid:
        extra["volume"] = volume_of(final)
    return final, origins, extra


def loft(p):
    final, origins, extra = loft_tool(p)
    return result_payload(final, origins, extra)


def feat_loft(p):
    final, origins, extra = loft_tool(p)
    if not extra.get("volume"):
        raise RuntimeError("A loft feature needs closed sections and the solid option.")
    return feature_result(p, final, origins, extra.pop("warnings", []), "loft", {"loft": {k: v for k, v in extra.items() if k != "volume"}})


def fill_face(curves, orders, tolerance, degree, points_per_curve, iterations):
    edges = []
    for spec in curves:
        edges.extend(wire_edges(curve_wire(spec)))
    if len(edges) < 3:
        raise RuntimeError("A boundary surface needs at least three boundary curves.")
    maker = BRepOffsetAPI_MakeFilling(degree, points_per_curve, iterations, False, 1e-5, tolerance, 0.01, 0.1, 8, 9)
    for e in edges:
        maker.Add(e, GeomAbs_C0)
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The boundary curves do not make a surface; check that they form a closed loop.")
    return maker.Shape(), maker.G0Error(), len(edges)


def cap_free_loops(shape, tolerance):
    free = ShapeAnalysis_FreeBounds(shape, tolerance, False, False)
    wires = free.GetClosedWires()
    caps = []
    m = store.build_maps(wires)["edges"]
    edges = [m.FindKey(i) for i in range(1, m.Extent() + 1)]
    for w in connect_edges(edges, tolerance):
        mk = BRepBuilderAPI_MakeFace(w, True)
        if mk.IsDone():
            caps.append(mk.Face())
    return caps


def free_edge_count(shape):
    anc = feat.AncestorMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, anc)
    count = 0
    for i in range(1, anc.Extent() + 1):
        edge = TopoDS.Edge_s(anc.FindKey(i))
        if BRep_Tool.Degenerated_s(edge):
            continue
        faces = list(anc.FindFromIndex(i))
        if len(faces) == 1 and not BRep_Tool.IsClosed_s(edge, TopoDS.Face_s(faces[0])):
            count += 1
    return count


def boundary_tool(p):
    groups = p.get("surfaces") or []
    shapes = p.get("shapes") or []
    if not groups and not shapes:
        raise RuntimeError("A boundary surface needs boundary curves or existing faces.")
    tol = num(p, "tolerance", 1e-4, 1e-7, 1.0)
    sew = BRepBuilderAPI_Sewing(max(tol, 1e-6), True, True, True, False)
    errors = []
    filled = []
    for g in groups:
        face, err, n = fill_face(g.get("curves") or [], g.get("orders"), tol, int(num(g, "degree", 3, 2, 8)), int(num(g, "points", 15, 5, 60)), int(num(g, "iterations", 2, 1, 10)))
        errors.append(err)
        filled.append(face)
        sew.Add(face)
    for sid in shapes:
        sew.Add(store.shape_of(sid))
    sew.Perform()
    sewn = sew.SewedShape()
    if sewn.IsNull():
        raise RuntimeError("The surfaces could not be joined.")
    caps = 0
    if p.get("cap_planar", True):
        cap_list = cap_free_loops(sewn, max(tol, 1e-6))
        if cap_list:
            sew2 = BRepBuilderAPI_Sewing(max(tol, 1e-6), True, True, True, False)
            sew2.Add(sewn)
            for c in cap_list:
                sew2.Add(c)
            sew2.Perform()
            sewn = sew2.SewedShape()
            caps = len(cap_list)
    shells = store.count_of(sewn, TopAbs_SHELL)
    open_edges = free_edge_count(sewn)
    closed = shells == 1 and open_edges == 0
    result = sewn
    if closed and p.get("to_solid", True):
        shell = None
        m = ShapeList()
        sm = store.build_maps(sewn)
        from OCP.TopExp import TopExp_Explorer

        ex = TopExp_Explorer(sewn, TopAbs_SHELL)
        shell = TopoDS.Shell_s(ex.Current())
        solid = BRepBuilderAPI_MakeSolid(shell).Solid()
        fixer = ShapeFix_Solid(solid)
        fixer.Perform()
        solid = fixer.Solid()
        result = finish_solid(solid, "boundary surface")
        if abs(volume_of(result)) < 1e-9:
            result = sewn
    clean_check(result, "boundary surface")
    origins = {}
    rmap = store.build_maps(result)["faces"]
    for gi, face in enumerate(filled):
        for cand in (sew.Modified(face), face):
            idx = rmap.FindIndex(cand)
            if idx > 0:
                origins.setdefault(idx - 1, "surface:%d" % gi)
                break
    for i in range(rmap.Extent()):
        origins.setdefault(i, "cap:%d" % i)
    extra = {"closed": closed, "open_edges": open_edges, "caps_added": caps, "fill_error": max(errors) if errors else 0.0, "engine": "filling", "warnings": []}
    if closed and p.get("to_solid", True) and not store.count_of(result, TopAbs_SOLID):
        closed = False
        extra["closed"] = False
        extra["warnings"].append("The surfaces enclose no volume.")
    if not closed and open_edges:
        extra["warnings"].append("The surfaces do not close a volume (%d free edges); the result stays a surface." % open_edges)
    if store.count_of(result, TopAbs_SOLID):
        extra["volume"] = volume_of(result)
    return result, origins, extra


def boundary_solid(p):
    result, origins, extra = boundary_tool(p)
    return result_payload(result, origins, extra)


def feat_boundary(p):
    result, origins, extra = boundary_tool(p)
    if not extra.get("closed") or not extra.get("volume"):
        raise RuntimeError("The boundary surfaces do not close into a solid (%d free edges); add the missing faces or planar caps." % extra["open_edges"] if extra["open_edges"] else "The boundary surfaces enclose no volume; add the missing faces.")
    return feature_result(p, result, origins, extra.pop("warnings", []), "boundary solid", {"boundary": {k: v for k, v in extra.items() if k != "volume"}})


def plane_axes(p):
    plane = p.get("plane") or {}
    origin = ops.pnt(plane.get("origin") or [0, 0, 0])
    normal = ops.direction(plane.get("normal"))
    xdir = plane.get("xdir")
    ax = gp_Ax2(origin, normal, ops.direction(xdir)) if xdir else gp_Ax2(origin, normal)
    return ax


def vec_in(ax, x, y):
    return gp_Vec(ax.XDirection()).Multiplied(x).Added(gp_Vec(ax.YDirection()).Multiplied(y))


def rib_tool(p):
    body_id = p.get("id") or p.get("base")
    if not body_id:
        raise RuntimeError("A rib needs the body it grows from.")
    base = store.shape_of(body_id)
    spec = p.get("profile") or {}
    thickness = num(p, "thickness", None, 1e-6, 1e6)
    if sketch_open(spec):
        ax, wire = open_profile(spec)
        segs = spec["open"][0]["segs"]
        vertices = [segs[0]["a"]] + [s["b"] for s in segs if s.get("t") != "circle"]
        if any(s.get("t") == "circle" for s in segs):
            raise RuntimeError("A rib profile cannot contain a circle.")
    else:
        vertices = spec.get("open") or spec.get("vertices")
        if not vertices or len(vertices) < 2:
            raise RuntimeError("A rib needs an open profile of at least two points.")
        ax = plane_axes(spec)
        wire = open_chain(vertices, ax, False)
    box = store.bbox_of(base)
    if box is None:
        raise RuntimeError("The body is empty.")
    diag = math.sqrt((box[3] - box[0]) ** 2 + (box[4] - box[1]) ** 2 + (box[5] - box[2]) ** 2)
    reach = diag * 1.5 + 2.0 * thickness
    pts2 = [(float(v[0]), float(v[1])) for v in vertices]
    sx, sy = pts2[0]
    ex, ey = pts2[-1]
    chord = (ex - sx, ey - sy)
    if math.hypot(*chord) <= MIN_SIZE:
        raise RuntimeError("The rib profile starts and ends at the same point.")
    if p.get("direction"):
        gx, gy = float(p["direction"][0]), float(p["direction"][1])
    else:
        gx, gy = -chord[1], chord[0]
    gl = math.hypot(gx, gy)
    if gl <= MIN_SIZE:
        raise RuntimeError("The growth direction has no length.")
    gx, gy = gx / gl, gy / gl
    if p.get("flip"):
        gx, gy = -gx, -gy
    for (x0, y0), (x1, y1) in zip(pts2, pts2[1:]):
        if abs((x1 - x0) * gy - (y1 - y0) * gx) <= 1e-9 * max(1.0, math.hypot(x1 - x0, y1 - y0)):
            raise RuntimeError("A profile segment runs along the growth direction, so the rib has no width there.")
    both_ways = str(p.get("grow", "one")) == "both"
    side = str(p.get("thickness_side", "both"))
    if side not in ("both", "first", "second"):
        raise RuntimeError("thickness_side must be both, first or second.")
    draft = num(p, "draft", 0.0, -45.0, 45.0)
    normal = gp_Vec(ax.Direction())
    if side == "both":
        lo, hi = -thickness / 2.0, thickness / 2.0
    elif side == "first":
        lo, hi = 0.0, thickness
    else:
        lo, hi = -thickness, 0.0
    gdir = vec_in(ax, gx, gy)
    if abs(draft) > 1e-9 and (draft > 0) != bool(p.get("draft_outward", False)):
        half = thickness / 2.0 if side == "both" else thickness
        reach = min(reach, 0.98 * half / math.tan(math.radians(abs(draft))))
    pieces_dirs =[gdir] + ([gdir.Reversed()] if both_ways else [])
    pieces = []
    far_wires = []
    for d in pieces_dirs:
        lead = thickness if abs(draft) > 1e-9 else 0.0
        start_wire = translated(wire, d.Multiplied(-lead)) if lead else wire
        strip = BRepPrimAPI_MakePrism(start_wire, d.Multiplied(reach + lead)).Shape()
        far_wires.append(translated(wire, d.Multiplied(reach)))
        base_off = translated(strip, normal.Multiplied(lo))
        web = BRepPrimAPI_MakePrism(base_off, normal.Multiplied(hi - lo)).Shape()
        web = finish_solid(web, "rib web")
        if abs(draft) > 1e-9:
            web = draft_web(web, wire, ax, d, thickness, lo, hi, draft, bool(p.get("draft_outward", False)))
            origin = BRep_Tool.Pnt_s(TopoDS.Vertex_s(_vertices_of(wire)[0]))
            gax = gp_Ax2(origin, gp_Dir(d))
            big = reach * 4.0
            corner = gp_Pnt(origin.X() - big * gax.XDirection().X() - big * gax.YDirection().X(), origin.Y() - big * gax.XDirection().Y() - big * gax.YDirection().Y(), origin.Z() - big * gax.XDirection().Z() - big * gax.YDirection().Z())
            half = BRepPrimAPI_MakeBox(gp_Ax2(corner, gp_Dir(d), gax.XDirection()), 2.0 * big, 2.0 * big, 2.0 * reach + lead).Shape()
            web = BRepAlgoAPI_Common(web, half).Shape()
        pieces.append(web)
    if len(pieces) > 1:
        web = BRepAlgoAPI_Fuse(pieces[0], pieces[1]).Shape()
    else:
        web = pieces[0]
    cut = BRepAlgoAPI_Cut(web, base)
    cut.Build()
    if not cut.IsDone():
        raise RuntimeError("The rib could not be trimmed to the body.")
    free_space = cut.Shape()
    kept = ShapeList()
    smap = store.build_maps(free_space)
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.TopExp import TopExp_Explorer

    ex = TopExp_Explorer(free_space, TopAbs_SOLID)
    tol = max(1e-5, 1e-7 * diag)
    while ex.More():
        s = ex.Current()
        dist = BRepExtrema_DistShapeShape(s, wire)
        dist.Perform()
        if dist.IsDone() and dist.Value() <= tol:
            kept.Append(s)
        ex.Next()
    if kept.Size() == 0:
        raise RuntimeError("The rib profile does not lie in the free space of the body or on its surface.")
    piece = list(kept)[0]
    if kept.Size() > 1:
        piece = BRepAlgoAPI_Fuse(list(kept)[0], list(kept)[1]).Shape()
    for fw in far_wires:
        dist = BRepExtrema_DistShapeShape(piece, fw)
        dist.Perform()
        if dist.IsDone() and dist.Value() <= tol:
            raise RuntimeError("The rib is not closed in by the body on the growth side; extend the body or shorten the profile.")
    piece = finish_solid(piece, "rib")
    origins = rib_origins(piece, spec, ax, wire, normal, (lo + hi) / 2.0, tol)
    return piece, origins, {"warnings": []}


def rib_origins(piece, spec, ax, wire, normal, middle, tol):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.GeomAbs import GeomAbs_Plane

    edges = wire_edges(wire)
    names = wire_names(spec, ax, [wire], "R")[0] if edges else []
    fmap = store.build_maps(piece)["faces"]
    origins = {}
    ends = 0
    nvec = normal.Normalized()
    for i in range(1, fmap.Extent() + 1):
        face = TopoDS.Face_s(fmap.FindKey(i))
        surf = BRepAdaptor_Surface(face)
        centre = face_center(face)
        offset = gp_Vec(ax.Location(), centre).Dot(nvec)
        if surf.GetType() == GeomAbs_Plane and abs(abs(gp_Vec(surf.Plane().Axis().Direction()).Dot(nvec)) - 1.0) < 1e-6:
            origins[i - 1] = "rib:side:high" if offset >= middle else "rib:side:low"
            continue
        best, role = None, None
        for j, e in enumerate(edges):
            curve = BRepAdaptor_Curve(e)
            mid = BRepBuilderAPI_MakeVertex(curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()))).Vertex()
            dist = BRepExtrema_DistShapeShape(face, mid)
            dist.Perform()
            if dist.IsDone() and dist.Value() <= tol and (best is None or dist.Value() < best):
                best, role = dist.Value(), "rib:" + names[j]
        if role is None:
            role = "rib:end:%d" % ends
            ends += 1
        origins[i - 1] = role
    return origins


def rib(p):
    piece, origins, extra = rib_tool(p)
    ident = store.put(piece)
    return {"id": ident, "summary": store.summarize(piece), "volume": volume_of(piece), "warnings": [], "origins": origins_list(piece, origins)}


def feat_rib(p):
    piece, origins, extra = rib_tool(p)
    return feature_result(dict(p, op="add"), piece, origins, extra.get("warnings"), "rib")


def draft_web(web, wire, ax, gdir, thickness, lo, hi, angle, outward):
    pts = [BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)) for v in _vertices_of(wire)]
    zs = [gp_Vec(pts[0], q).Dot(gdir) for q in pts]
    if max(zs) - min(zs) > 1e-6:
        raise RuntimeError("A drafted rib needs its profile on a line square to the growth direction.")
    neutral = gp_Pln(pts[0], gp_Dir(gdir))
    maker = BRepOffsetAPI_DraftAngle(web)
    normal = gp_Vec(ax.Direction())
    fmap = store.build_maps(web)["faces"]
    count = 0
    sign = -1.0 if outward else 1.0
    for i in range(1, fmap.Extent() + 1):
        face = TopoDS.Face_s(fmap.FindKey(i))
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane

        surf = BRepAdaptor_Surface(face)
        if surf.GetType() != GeomAbs_Plane:
            continue
        n = surf.Plane().Axis().Direction()
        if abs(gp_Vec(n).Dot(normal.Normalized())) < 1.0 - 1e-6:
            continue
        pt = surf.Value(0.5 * (surf.FirstUParameter() + surf.LastUParameter()), 0.5 * (surf.FirstVParameter() + surf.LastVParameter()))
        offset = gp_Vec(ax.Location(), pt).Dot(normal.Normalized())
        if abs(offset) < 1e-9 or abs(abs(offset) - thickness / 2.0) > thickness + 1e-6 and False:
            continue
        maker.Add(face, gp_Dir(gdir), math.radians(sign * angle), neutral, True)
        if not maker.AddDone():
            raise RuntimeError("The draft angle on the rib failed; try a smaller angle.")
        count += 1
    if count == 0:
        raise RuntimeError("The rib has no side faces to draft.")
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("The draft on the rib failed.")
    return maker.Shape()


def _vertices_of(shape):
    from OCP.TopAbs import TopAbs_VERTEX

    m = store.build_maps(shape)["vertices"]
    return [m.FindKey(i) for i in range(1, m.Extent() + 1)]


def hole_profile(spec):
    kind = str(spec.get("kind", "simple"))
    d = num(spec, "diameter", None, 1e-6, 1e5)
    r = d / 2.0
    depth = spec.get("depth")
    through = depth is None or bool(spec.get("through", False))
    depth = None if through else num(spec, "depth", None, 1e-6, 1e6)
    tip = num(spec, "tip_angle", 0.0, 0.0, 179.0)
    return kind, r, depth, through, tip


def hole_tool(spec, total):
    kind, r, depth, through, tip = hole_profile(spec)
    length = total if through else depth
    if kind == "tapped":
        r = num(spec, "tap_drill", spec.get("diameter"), 1e-6, 1e5) / 2.0
    pts = []
    if kind == "counterbore":
        cr = num(spec, "cbore_diameter", None, 1e-6, 1e5) / 2.0
        cd = num(spec, "cbore_depth", None, 1e-6, 1e6)
        if cr <= r:
            raise RuntimeError("The counterbore must be wider than the hole.")
        if not through and cd >= length:
            raise RuntimeError("The counterbore is as deep as the whole hole.")
        pts = [(0.0, 0.0), (cr, 0.0), (cr, -cd), (r, -cd), (r, -length)]
    elif kind == "countersink":
        sr = num(spec, "csk_diameter", None, 1e-6, 1e5) / 2.0
        ang = num(spec, "csk_angle", 90.0, 10.0, 170.0)
        if sr <= r:
            raise RuntimeError("The countersink must be wider than the hole.")
        sd = (sr - r) / math.tan(math.radians(ang) / 2.0)
        if not through and sd >= length:
            raise RuntimeError("The countersink is as deep as the whole hole.")
        pts = [(0.0, 0.0), (sr, 0.0), (r, -sd), (r, -length)]
    elif kind in ("simple", "tapped"):
        pts = [(0.0, 0.0), (r, 0.0), (r, -length)]
    else:
        raise RuntimeError("Unknown hole kind %s." % kind)
    tipped = tip > 0 and not through
    if tipped:
        pts.append((0.0, -length - r / math.tan(math.radians(tip) / 2.0)))
    else:
        pts.append((0.0, -length))
    lead = {"counterbore": ["top", "cbore_wall", "cbore_floor", "wall"], "countersink": ["top", "csk_cone", "wall"]}.get(kind, ["top", "wall"])
    return pts, lead + ["tip" if tipped else "bottom"], length, r


def revolved_tool(pts, names, origin, axis_dir, xdir, tag):
    ax = gp_Ax2(origin, axis_dir, xdir)
    z = gp_Vec(ax.Direction())
    x = gp_Vec(ax.XDirection())
    verts = []
    for rr, zz in pts:
        verts.append(gp_Pnt(origin.X() + x.X() * rr + z.X() * zz, origin.Y() + x.Y() * rr + z.Y() * zz, origin.Z() + x.Z() * rr + z.Z() * zz))
    wire = BRepBuilderAPI_MakeWire()
    made = []
    count = len(verts)
    for i in range(count):
        a, b = verts[i], verts[(i + 1) % count]
        if a.Distance(b) > MIN_SIZE:
            edge = BRepBuilderAPI_MakeEdge(a, b).Edge()
            wire.Add(edge)
            made.append((edge, names[i] if i < len(names) else "axis"))
    face = BRepBuilderAPI_MakeFace(wire.Wire()).Face()
    rev = BRepPrimAPI_MakeRevol(face, gp_Ax1(origin, axis_dir), 2.0 * math.pi)
    solid = finish_solid(rev.Shape(), "hole tool")
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    roles = []
    fmap = store.build_maps(solid)["faces"]
    faces = [TopoDS.Face_s(fmap.FindKey(i)) for i in range(1, fmap.Extent() + 1)]
    used = set()
    for edge, name in made:
        if name == "axis":
            continue
        curve = BRepAdaptor_Curve(edge)
        mid = BRepBuilderAPI_MakeVertex(curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()))).Vertex()
        best, hit = None, None
        for k, face in enumerate(faces):
            if k in used:
                continue
            dist = BRepExtrema_DistShapeShape(face, mid)
            dist.Perform()
            if dist.IsDone() and (best is None or dist.Value() < best):
                best, hit = dist.Value(), k
        if hit is not None and best <= 1e-6:
            used.add(hit)
            roles.append((faces[hit], "%s:%s" % (tag, name)))
    return solid, roles


def perpendicular(normal):
    ref = gp_Vec(1, 0, 0) if abs(normal.X()) < 0.9 else gp_Vec(0, 1, 0)
    v = gp_Vec(normal).Crossed(ref)
    return gp_Dir(v.X(), v.Y(), v.Z())


def hole_tools(p, base_id):
    base = store.shape_of(base_id)
    spec = p.get("spec") or {}
    places = p.get("positions") or []
    if not places or len(places) > MAX_HOLES:
        raise RuntimeError("A hole feature needs between one and %d positions." % MAX_HOLES)
    box = store.bbox_of(base)
    diag = math.sqrt((box[3] - box[0]) ** 2 + (box[4] - box[1]) ** 2 + (box[5] - box[2]) ** 2)
    pts, names, length, radius = hole_tool(spec, diag * 2.0 + 10.0)
    normal = ops.direction(p.get("normal"))
    xdir = ops.direction(p["xdir"]) if p.get("xdir") else perpendicular(normal)
    solids, roles = [], []
    for k, place in enumerate(places):
        solid, r = revolved_tool(pts, names, ops.pnt(place), normal, xdir, "hole%d" % k)
        solids.append(solid)
        roles.extend(r)
    kind, r, depth, through, tip = hole_profile(spec)
    threads = []
    if kind == "tapped":
        thread = spec.get("thread") or {}
        nominal = num(thread, "nominal", spec.get("diameter"), 1e-6, 1e5)
        pitch = num(thread, "pitch", None, 1e-6, 1e4)
        tdepth = num(thread, "depth", length, 1e-6, 1e6)
        if tdepth > length + 1e-9:
            raise RuntimeError("The thread is deeper than the drilled hole.")
        axis = [0.0 - normal.X(), 0.0 - normal.Y(), 0.0 - normal.Z()]
        for place in places:
            threads.append({"position": [float(c) for c in place[:3]], "axis": axis, "nominal": nominal, "pitch": pitch, "depth": tdepth, "minor_diameter_derived": nominal - 1.0825317547305482 * pitch, "tap_drill": 2.0 * radius})
    return solids, roles, {"cosmetic_threads": threads, "hole_length": length, "through": through}


def hole(p):
    base_id = p.get("base") or p.get("id")
    if not base_id:
        raise RuntimeError("A hole needs the body it is cut in.")
    solids, _roles, info = hole_tools(p, base_id)
    tools = [store.put(s) for s in solids]
    try:
        out = ops.boolean({"op": "cut", "base": base_id, "tools": tools, "unify": bool(p.get("unify", False))})
    finally:
        store.free(tools)
    out.update(info)
    return out


def feat_hole(p):
    base_id = p.get("id")
    if not base_id:
        raise RuntimeError("A hole needs the body it is cut in.")
    solids, roles, info = hole_tools(p, base_id)
    tool = feat.compound_of(solids)
    out = feat.combine(base_id, store.shape_of(base_id), tool, roles, "cut", "hole")()
    out.update(info)
    return out


METHODS = {
    "sweep": sweep,
    "sweep_preview": sweep_preview,
    "loft": loft,
    "boundary_solid": boundary_solid,
    "rib": rib,
    "hole": hole,
    "feat_sweep": feat_sweep,
    "feat_loft": feat_loft,
    "feat_boundary": feat_boundary,
    "feat_rib": feat_rib,
    "feat_hole": feat_hole,
}
