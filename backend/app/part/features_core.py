from app.param import sketch as K
from app.part import profile
from app.part.registry import FeatureType, Param, PartError, RefLost, RefSlot, register
from app.solid import dressup, planes

PLANE_CHOICES = ["XY", "XZ", "YZ", "face", "source"]
PLANE_KIND = 0


def frame_of(origin, normal, xdir):
    return {"origin": list(origin), "normal": list(normal), "xdir": list(xdir)}


def project(point, origin, normal):
    d = sum((point[i] - origin[i]) * normal[i] for i in range(3))
    return [point[i] - d * normal[i] for i in range(3)]


def sketch_frame(step):
    mode = step.p("plane") or "XY"
    off = step.length("offset") or 0.0
    if mode in K.PLANES:
        pl = K.PLANES[mode]
        n = pl["normal"]
        return frame_of([pl["origin"][i] + n[i] * off for i in range(3)], n, pl["x"])
    if mode == "face":
        idx = step.face("face")
        sig = step.signatures("faces").get(str(idx))
        if not sig or sig.get("k") != PLANE_KIND or not sig.get("n"):
            raise PartError("A sketch can only be placed on a flat face.")
        n = [float(v) for v in sig["n"]]
        c = [float(v) for v in sig["c"]]
        raw = step.p("origin")
        origin = project([float(v) * step.mm for v in raw], c, n) if raw else c
        if off:
            origin = [origin[i] + n[i] * off for i in range(3)]
        xraw = step.p("xdir")
        if xraw:
            x = [float(v) for v in xraw]
            dot = sum(x[i] * n[i] for i in range(3))
            x = [x[i] - dot * n[i] for i in range(3)]
            ln = sum(v * v for v in x) ** 0.5
            x = [v / ln for v in x] if ln > 1e-9 else planes.on_face(origin, n)["x"]
        else:
            x = planes.on_face(origin, n)["x"]
        return frame_of(origin, n, x)
    if mode == "source":
        fr = step.plane("plane")
        return frame_of(fr["origin"], fr["z"], fr["x"])
    raise PartError("Unknown sketch plane %s." % mode)


def sketch_plan(step):
    name = step.p("sketch")
    if not name:
        raise PartError("The sketch feature has no sketch.")
    frame = sketch_frame(step)
    return {"profile": profile.build(step.d, name, frame)}


def thin_of(step):
    if not step.p("thin"):
        return None
    t1 = step.length("thin1")
    if not t1 or t1 <= 0:
        raise PartError("The thin wall thickness must be positive.")
    return {"mode": step.p("thin_mode") or "one", "t1": t1, "t2": step.length("thin2") or 0.0, "flip": bool(step.p("thin_flip"))}


def extrude_plan(op):
    def plan(step):
        prof = step.profile("sketch")
        end1 = step.p("end1") or "blind"
        p = {"op": op, "profile": prof, "flip": bool(step.p("flip")), "start_offset": step.length("start_offset") or 0.0}
        spec = {"type": end1}
        if end1 in ("blind", "mid"):
            depth = step.length("depth1")
            if not depth or depth <= 0:
                raise PartError("The extrusion depth must be positive.")
            spec["depth"] = depth
        if end1 == "face":
            spec["face"] = step.face("face1")
        p["end1"] = spec
        if step.p("two"):
            p["two"] = True
            e2 = step.p("end2") or "blind"
            spec2 = {"type": e2}
            if e2 == "blind":
                d2 = step.length("depth2")
                if not d2 or d2 <= 0:
                    raise PartError("The second direction depth must be positive.")
                spec2["depth"] = d2
            p["end2"] = spec2
        ang = step.p("draft") or 0.0
        if ang and step.p("draft_out"):
            ang = -ang
        p["draft1"] = ang
        p["draft2"] = ang
        thin = thin_of(step)
        if thin:
            p["thin"] = thin
        return {"method": "feat_extrude", "params": p}

    return plan


def axis_of(step, prof):
    spec = str(step.p("axis") or "y").strip()
    fr = prof["frame"]
    o, x, n = fr["origin"], fr["xdir"], fr["normal"]
    y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]]

    def world(u, v):
        return [o[i] + x[i] * u + y[i] * v for i in range(3)]

    def vec(du, dv):
        return [x[i] * du + y[i] * dv for i in range(3)]

    if spec.lower() == "x":
        return {"origin": world(0, 0), "dir": vec(1, 0)}
    if spec.lower() == "y":
        return {"origin": world(0, 0), "dir": vec(0, 1)}
    line = prof["axis_lines"].get(spec.lstrip("h"))
    if line is None:
        raise PartError("The revolve axis %s must be a construction line of the sketch, or x or y." % spec)
    (u0, v0), (u1, v1) = line
    return {"origin": world(u0, v0), "dir": vec(u1 - u0, v1 - v0)}


def revolve_plan(op):
    def plan(step):
        prof = step.profile("sketch")
        p = {"op": op, "profile": prof, "axis": axis_of(step, prof), "flip": bool(step.p("flip"))}
        a1 = step.p("angle1")
        p["angle1"] = 360.0 if a1 is None else a1
        p["angle2"] = step.p("angle2") or 0.0
        p["mid"] = bool(step.p("mid"))
        thin = thin_of(step)
        if thin:
            p["thin"] = thin
        return {"method": "feat_revolve", "params": p}

    return plan


THIN = [
    Param("thin", "bool", False, label="Thin wall"),
    Param("thin_mode", "enum", "one", choices=["one", "two", "mid"], label="Wall sides"),
    Param("thin1", "length", 1.0, min=0.0, label="Thickness"),
    Param("thin2", "length", 0.0, min=0.0, label="Second thickness"),
    Param("thin_flip", "bool", False, label="Other side"),
]

register(FeatureType("sketch", "Sketch", group="sketch", needs_body=False, sketch=True, plan=sketch_plan, params=[
    Param("sketch", "text", "", label="Sketch"),
    Param("plane", "enum", "XY", choices=PLANE_CHOICES, label="Plane"),
    Param("offset", "length", 0.0, label="Offset"),
    Param("origin", "vector", None, label="Origin on face"),
    Param("xdir", "vector", None, label="X direction on face"),
], refs=[RefSlot("face", "face", required=False, label="Face"), RefSlot("plane", "plane", required=False, label="Plane")]))

EXTRUDE_PARAMS = [
    Param("end1", "enum", "blind", choices=["blind", "through", "face", "next", "mid"], label="End condition"),
    Param("depth1", "length", 10.0, min=0.0, label="Depth"),
    Param("flip", "bool", False, label="Reverse direction"),
    Param("two", "bool", False, label="Second direction"),
    Param("end2", "enum", "blind", choices=["blind", "through"], label="Second end condition"),
    Param("depth2", "length", 10.0, min=0.0, label="Second depth"),
    Param("draft", "angle", 0.0, min=0.0, max=88.0, label="Draft angle"),
    Param("draft_out", "bool", False, label="Draft outward"),
    Param("start_offset", "length", 0.0, label="Start offset"),
] + THIN
EXTRUDE_REFS = [RefSlot("sketch", "sketch", label="Sketch"), RefSlot("face1", "face", required=False, label="Up to face")]
EXTRUDE_ROLES = ("side:*", "cap:start", "cap:end", "cap:end2")

register(FeatureType("extrude", "Extruded boss", group="sketch features", needs_body=False, params=EXTRUDE_PARAMS, refs=EXTRUDE_REFS, roles=EXTRUDE_ROLES, plan=extrude_plan("add")))
register(FeatureType("extrude_cut", "Extruded cut", group="sketch features", needs_body=True, params=EXTRUDE_PARAMS, refs=EXTRUDE_REFS, roles=EXTRUDE_ROLES, plan=extrude_plan("cut")))

REVOLVE_PARAMS = [
    Param("axis", "text", "y", label="Axis"),
    Param("angle1", "angle", 360.0, min=0.0, max=360.0, label="Angle"),
    Param("angle2", "angle", 0.0, min=0.0, max=360.0, label="Second angle"),
    Param("mid", "bool", False, label="Mid plane"),
    Param("flip", "bool", False, label="Reverse direction"),
] + THIN
REVOLVE_REFS = [RefSlot("sketch", "sketch", label="Sketch")]
REVOLVE_ROLES = ("side:*", "cap:start", "cap:end", "cap:end2")

register(FeatureType("revolve", "Revolved boss", group="sketch features", needs_body=False, params=REVOLVE_PARAMS, refs=REVOLVE_REFS, roles=REVOLVE_ROLES, plan=revolve_plan("add")))
register(FeatureType("revolve_cut", "Revolved cut", group="sketch features", needs_body=True, params=REVOLVE_PARAMS, refs=REVOLVE_REFS, roles=REVOLVE_ROLES, plan=revolve_plan("cut")))


def dress_plan(kind, build):
    def plan(step):
        raw = build(step)
        raw = {k: v for k, v in raw.items() if v is not None}
        return {"method": dressup.SCHEMAS[kind]["method"], "params": dressup.metric(kind, raw, step.mm)}

    return plan


def edge_entries(step, slot="edges"):
    edges = step.edges(slot) if step.refs(slot) else []
    sizes = step.p("sizes") or []
    out = []
    for i, idx in enumerate(edges):
        sz = sizes[i] if i < len(sizes) and isinstance(sizes[i], dict) else None
        out.append({"edge": idx, **sz} if sz else idx)
    return out


def fillet_build(step):
    edges = edge_entries(step)
    faces = step.faces("faces") if step.refs("faces") else []
    if not edges and not faces:
        raise RefLost("Choose the edges or faces to round.", "edges")
    return {"edges": edges or None, "faces": faces or None, "radius": step.p("radius"), "profile": step.p("profile")}


def chamfer_build(step):
    edges = edge_entries(step)
    faces = step.faces("faces") if step.refs("faces") else []
    if not edges and not faces:
        raise RefLost("Choose the edges or faces to chamfer.", "edges")
    return {"edges": edges or None, "faces": faces or None, "distance": step.p("distance"), "distance2": step.p("distance2") or None, "angle": step.p("angle") or None, "face": step.face("face") if step.refs("face") else None}


def shell_build(step):
    thickness = step.p("thickness")
    if not thickness or thickness <= 0:
        raise PartError("The shell thickness must be positive.")
    return {"faces": step.faces("faces") if step.refs("faces") else [], "thickness": thickness, "direction": step.p("direction"), "join": step.p("join")}


def draft_build(step):
    return {"faces": step.faces("faces"), "angle": step.p("angle"), "pull": step.p("pull") or [0, 0, 1], "neutral_plane": step.p("neutral"), "allow_partial": bool(step.p("allow_partial"))}


def pattern_build(step):
    return {"pattern": step.p("pattern"), "op": step.p("op"), "directions": step.p("directions"), "axis": step.p("axis"), "count": step.p("count"), "angle": step.p("angle"), "step": step.p("step") or None, "skip": step.p("skip"), "include_seed": bool(step.p("include_seed")), "seed": step.seed("seed")}


def mirror_build(step):
    seed = step.seed("seed") if step.refs("seed") else None
    return {"mode": step.p("mode"), "plane": step.p("plane"), "op": step.p("op"), "merge": bool(step.p("merge")), "seed": seed}


register(FeatureType("fillet", "Fillet", group="dressup", plan=dress_plan("fillet", fillet_build), params=[
    Param("radius", "length", 1.0, min=0.0, label="Radius"),
    Param("profile", "enum", "rational", choices=["rational", "quasi_angular", "polynomial"], label="Profile"),
    Param("sizes", "json", None, label="Per edge sizes"),
], refs=[RefSlot("edges", "edge", multi=True, required=False, label="Edges"), RefSlot("faces", "face", multi=True, required=False, label="Faces")], roles=("~",)))

register(FeatureType("chamfer", "Chamfer", group="dressup", plan=dress_plan("chamfer", chamfer_build), params=[
    Param("distance", "length", 1.0, min=0.0, label="Distance"),
    Param("distance2", "length", None, min=0.0, label="Second distance"),
    Param("angle", "angle", None, min=0.0, max=90.0, label="Angle"),
    Param("sizes", "json", None, label="Per edge sizes"),
], refs=[RefSlot("edges", "edge", multi=True, required=False, label="Edges"), RefSlot("faces", "face", multi=True, required=False, label="Faces"), RefSlot("face", "face", required=False, label="Distance face")], roles=("~",)))

register(FeatureType("shell", "Shell", group="dressup", plan=dress_plan("shell", shell_build), params=[
    Param("thickness", "length", 1.0, min=0.0, label="Thickness"),
    Param("direction", "enum", "inward", choices=["inward", "outward"], label="Direction"),
    Param("join", "enum", "arc", choices=["arc", "intersection"], label="Corners"),
], refs=[RefSlot("faces", "face", multi=True, required=False, label="Faces to remove")], roles=("~",)))

register(FeatureType("draft", "Draft", group="dressup", plan=dress_plan("draft", draft_build), params=[
    Param("angle", "angle", 1.0, label="Angle"),
    Param("pull", "vector", [0, 0, 1], label="Pull direction"),
    Param("neutral", "json", None, label="Neutral plane"),
    Param("allow_partial", "bool", False, label="Keep faces that worked"),
], refs=[RefSlot("faces", "face", multi=True, label="Faces")], roles=("~",)))

register(FeatureType("pattern", "Pattern", group="dressup", plan=dress_plan("pattern", pattern_build), params=[
    Param("pattern", "enum", "linear", choices=["linear", "circular"], label="Kind"),
    Param("op", "enum", "fuse", choices=["fuse", "cut"], label="Operation"),
    Param("directions", "json", None, label="Directions"),
    Param("axis", "json", None, label="Axis"),
    Param("count", "int", 2, min=1, label="Count"),
    Param("angle", "angle", 360.0, label="Angle"),
    Param("step", "angle", None, label="Step angle"),
    Param("skip", "json", None, label="Skipped instances"),
    Param("include_seed", "bool", False, label="Include the seed"),
], refs=[RefSlot("seed", "feature", label="Feature to repeat")], roles=("~",)))

register(FeatureType("mirror", "Mirror", group="dressup", plan=dress_plan("mirror", mirror_build), params=[
    Param("mode", "enum", "feature", choices=["feature", "body"], label="Mirror"),
    Param("plane", "json", None, label="Plane"),
    Param("op", "enum", "fuse", choices=["fuse", "cut"], label="Operation"),
    Param("merge", "bool", False, label="Merge"),
], refs=[RefSlot("seed", "feature", required=False, label="Feature to mirror")], roles=("~",)))
