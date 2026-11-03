import math

from app.part import store
from app.part.registry import FeatureType, Param, PartError, RefSlot, register
from app.sheetmetal import bend, records, rule
from app.solid import work

POSITIONS = ["material_inside", "material_outside", "bend_outside"]
DATUMS = ["outside", "inside", "tangent"]
WIDTHS = ["full", "centered", "offsets"]
HEMS = ["closed", "open", "teardrop", "rolled"]
MAX_ANGLE_DEG = 175.0
HEM_LIKE = ("hem", "teardrop", "rolled")


def resolve(eff, theta, radius, thickness):
    try:
        return bend.resolve_bend(eff, theta, r=radius, t=thickness)
    except bend.BendError as err:
        raise PartError(str(err))


def common(step, root=False):
    rl = rule.for_step(step)
    if root:
        eff, R, given = dict(rl), rl["inner_radius_mm"], {}
    else:
        eff, R, given = rule.effective(step, rl)
    step.sm = {"rule": rl, "eff": eff, "T": rl["thickness_mm"], "R": R, "given": given, "root": root}
    return rl, eff, R, rl["thickness_mm"]


def frame_point(frame, u, v):
    o, x, n = frame["origin"], frame["xdir"], frame["normal"]
    y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]]
    return [o[i] + x[i] * u + y[i] * v for i in range(3)]


def sketch_line(prof):
    segs = None
    for loop in prof.get("open") or []:
        if loop.get("segs"):
            segs = loop["segs"]
            break
    if segs:
        s = segs[0]
        if s.get("t") != "line" and abs(float(s.get("bulge", 0.0) or 0.0)) > 1e-12:
            raise PartError("The bend line must be a straight line.")
        a, b = s["a"], s["b"]
    else:
        lines = list((prof.get("axis_lines") or {}).values())
        if not lines:
            raise PartError("Draw one straight line in the sketch to mark the bend.")
        a, b = lines[0]
    fr = prof["frame"]
    return {"a": frame_point(fr, a[0], a[1]), "b": frame_point(fr, b[0], b[1])}


def flange_common(step, rl, eff, R, T):
    return {
        "thickness": T, "radius": R, "flip": bool(step.p("flip")), "ref_face": rule.ref_index(step, rl),
        "relief": rule.relief_for(step, rl), "position": step.p("position"), "offset": step.length("offset") or 0.0,
        "width_mode": step.p("width_mode") or "full", "width": step.length("width"), "offset1": step.length("offset1") or 0.0, "offset2": step.length("offset2") or 0.0,
        "min_gap": rl["min_gap_mm"],
    }


def edge_flange_plan(step):
    rl, eff, R, T = common(step)
    p = flange_common(step, rl, eff, R, T)
    p.update({"edges": step.edges("edges"), "angle": step.p("angle"), "length": step.length("length"), "length_ref": step.p("length_ref")})
    resolve(eff, math.radians(float(step.p("angle") or 90.0)), R, T)
    return {"method": "sm_edge_flange", "params": p}


def miter_plan(step):
    rl, eff, R, T = common(step)
    p = flange_common(step, rl, eff, R, T)
    gap = step.length("gap")
    p.update({"edges": step.edges("edges"), "angle": step.p("angle"), "length": step.length("length"), "length_ref": step.p("length_ref"), "gap": rl["min_gap_mm"] if gap is None else gap})
    resolve(eff, math.radians(float(step.p("angle") or 90.0)), R, T)
    return {"method": "sm_miter_flange", "params": p}


def hem_plan(step):
    rl, eff, R, T = common(step)
    p = flange_common(step, rl, eff, R, T)
    p.update({"edges": step.edges("edges"), "hem": step.p("hem"), "gap": step.length("gap"), "length": step.length("length"), "angle": step.p("angle"), "hem_radius": step.length("hem_radius")})
    return {"method": "sm_hem", "params": p}


def base_plan(step):
    rl, eff, R, T = common(step, root=True)
    prof = step.profile("sketch")
    p = {"profile": prof, "thickness": T, "radius": R, "side": step.p("side"), "depth": step.length("depth"), "depth_mode": step.p("depth_mode"), "flip_depth": bool(step.p("flip_depth"))}
    if prof.get("regions"):
        p["profile"] = dict(prof, open=[])
    return {"method": "sm_base_flange", "params": p}


def strip_plan(method, kind):
    def plan(step):
        rl, eff, R, T = common(step)
        theta = math.radians(float(step.p("angle") or 90.0))
        rb = resolve(eff, theta, R, T)
        prof = step.profile("sketch")
        p = {"face": step.face("face"), "line": sketch_line(prof), "thickness": T, "radius": R, "angle": step.p("angle"), "ba": rb["ba"], "flip": bool(step.p("flip")), "flip_side": bool(step.p("flip_side")), "ref_face": rule.ref_index(step, rl)}
        if kind == "jog":
            p["offset"] = step.length("offset")
        return {"method": method, "params": p}

    return plan


def bend_rows_for(step, ids):
    d = step.d
    out = []
    for bid in ids or []:
        row = records.bend(d, str(bid))
        if row is None:
            raise PartError("There is no bend %s; it may be later in the tree or its feature failed." % bid)
        out.append(row)
    if not out:
        raise PartError("Choose the bends first.")
    return out


def relief_plan(step):
    rl = rule.for_step(step)
    rows = bend_rows_for(step, step.p("bends"))
    spec = rule.relief_for(step, rl)
    step.sm = {"rule": rl, "eff": dict(rl), "T": rl["thickness_mm"], "R": rl["inner_radius_mm"], "given": {}, "root": False, "no_bends": True}
    if spec["type"] == "none":
        raise PartError("Choose a relief type other than none.")
    return {"method": "sm_bend_relief", "params": {"thickness": rl["thickness_mm"], "type": spec["type"], "width_ratio": spec["width_ratio"], "extra": spec["extra"], "gap": spec["gap"], "ends": step.p("ends"), "bends": [{k: r[k] for k in ("axis", "ref_normal_parent", "radius", "direction", "turn")} for r in rows]}}


def line_hit(o1, d1, o2, d2, n):
    def proj(v):
        k = sum(v[i] * n[i] for i in range(3))
        return [v[i] - k * n[i] for i in range(3)]

    a, b = proj(d1), proj(d2)
    w = [o2[i] - o1[i] for i in range(3)]
    cx = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    den = sum(c * c for c in cx)
    if den < 1e-12:
        return None
    wc = [w[1] * b[2] - w[2] * b[1], w[2] * b[0] - w[0] * b[2], w[0] * b[1] - w[1] * b[0]]
    s = sum(wc[i] * cx[i] for i in range(3)) / den
    return [o1[i] + a[i] * s for i in range(3)]


def corner_plan(step):
    rl = rule.for_step(step)
    spec = step.p("corners")
    if not isinstance(spec, list) or not spec:
        raise PartError("Give the bend pairs that meet at each corner.")
    T = rl["thickness_mm"]
    out = []
    for pair in spec:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise PartError("A corner is a pair of bend ids.")
        a, b = bend_rows_for(step, pair)
        n = a["ref_normal_parent"]
        hit = line_hit(a["axis"]["origin"], a["axis"]["dir"], b["axis"]["origin"], b["axis"]["dir"], n)
        if hit is None:
            raise PartError("Bends %s and %s are parallel; they do not meet in a corner." % (pair[0], pair[1]))
        up = a["direction"] == "up"
        r_ref = a["radius"] if up else a["radius"] + T
        sign = -1.0 if up else 1.0
        c0 = a["axis"]["origin"]
        height = sum((c0[i] + sign * n[i] * r_ref) * n[i] for i in range(3))
        base = sum(hit[i] * n[i] for i in range(3))
        point = [hit[i] + n[i] * (height - base) for i in range(3)]
        out.append({"point": point, "normal": n})
    size = step.length("size")
    if not size or size <= 0:
        raise PartError("The corner relief size must be positive.")
    step.sm = {"rule": rl, "eff": dict(rl), "T": T, "R": rl["inner_radius_mm"], "given": {}, "root": False, "no_bends": True}
    return {"method": "sm_corner_relief", "params": {"thickness": T, "type": step.p("shape"), "size": size, "corners": out}}


def convert_plan(step):
    face = step.face("face")
    info = work.kcall("sm_analyze", {"id": step.base, "face": face}, work.SHORT)
    vals = dict(step.values)
    if vals.get("thickness") is None:
        vals["thickness"] = info["thickness"] / step.mm
    if vals.get("radius") is None:
        radii = [b["radius"] for b in info["bends"]]
        vals["radius"] = (min(radii) if radii else info["thickness"]) / step.mm
    step.values = vals
    rl, eff, R, T = common(step, root=True)
    return {"method": "sm_convert", "params": {"face": face, "thickness": T}}


def to_float(v):
    return None if v is None else float(v)


def finish(step, res):
    d = step.d
    sm = getattr(step, "sm", None)
    if sm is None:
        return
    fid = step.feat["id"]
    entry = getattr(step, "entry", None)
    keys = entry.faces if entry is not None else []

    def key(i):
        return keys[i] if isinstance(i, int) and 0 <= i < len(keys) else None

    eff, rl = sm["eff"], sm["rule"]
    rows, ids = [], []
    for n, b in enumerate(res.get("bends") or [], 1):
        seq = int(b.get("j") or n)
        bid = "%s.%d" % (fid, seq)
        theta, r, t = float(b["angle"]), float(b["radius"]), float(b["thickness"])
        warns = []
        if theta < math.pi - 1e-6:
            rb = resolve(eff, theta, r, t)
            warns = list(rb.get("warnings") or [])
            fields = {"method": rb["method"], "k": rb["k"], "neutral_radius": rb["neutral_radius"], "ba": rb["ba"], "bd": rb["bd"], "ossb": rb["ossb"], "issb": rb["issb"], "included": rb["included"]}
        else:
            k = float(eff.get("k_factor", bend.DEFAULT_K))
            fields = {"method": "kfactor", "k": k, "neutral_radius": r + k * t, "ba": bend.bend_allowance(theta, r, t, k), "bd": None, "ossb": None, "issb": None, "included": None}
            note = "A bend of 180 degrees or more has no setback; its allowance uses the K-factor %.4g." % k
            fields["note"] = note
        faces = b.get("faces") or {}
        row = {
            "id": bid, "seq": seq, "type": b.get("type") or "bend",
            "faces": {s: key(faces.get(s)) for s in ("inner", "outer", "parent", "child")},
            "radius": r, "thickness": t, "angle": theta, "direction": b["direction"], "turn": int(b["turn"]),
            "axis": b["axis"], "ref_normal_parent": b.get("ref_normal_parent"), "ref_normal_child": b.get("ref_normal_child"),
            "flat_parent": to_float(b.get("flat_parent")), "flat_child": to_float(b.get("flat_child")),
            "override": dict(sm["given"]), "table_id": eff.get("table_id") or None, "warnings": warns,
        }
        row.update(fields)
        for w in warns:
            step.warn("%s: %s" % (bid, w))
        rows.append(row)
        ids.append(bid)
    order = store.tree(d)["order"]
    frow = {
        "type": step.feat["type"], "order": order.index(fid) if fid in order else 0, "thickness": sm["T"], "radius": sm["R"],
        "rule_owner": bool(sm["root"] and rule.root_record(d) is not None and rule.root_record(d)["id"] == fid),
        "bends": ids, "reliefs": list(res.get("reliefs") or []), "detail": res.get("kind"),
        "sections": [{**s, "path": [dict(e, bend="%s.%d" % (fid, e["j"])) if e.get("t") == "bend" else e for e in s.get("path") or []]} for s in res.get("sections") or []],
        "warnings": list(step.warnings),
    }
    if frow["rule_owner"]:
        frow["rule"] = {k: v for k, v in rl.items() if k not in ("table",)}
        if step.feat["type"] == "base_flange":
            role = res.get("ref_role")
            frow["ref_key"] = "%s:%s" % (fid, role) if role else None
        else:
            frow["ref_key"] = step.base_faces[step.face("face")] if step.base_faces else None
    records.write(d, fid, frow, rows)


def flange_params(extra):
    return rule.OVERRIDE_PARAMS + rule.RELIEF_PARAMS + extra


WIDTH_PARAMS = [
    Param("width_mode", "enum", "full", choices=WIDTHS, label="Flange width"),
    Param("width", "length", 10.0, min=0.0, label="Width"),
    Param("offset1", "length", 0.0, min=0.0, label="Offset from the first end"),
    Param("offset2", "length", 0.0, min=0.0, label="Offset from the second end"),
]

FLANGE_PARAMS = [
    Param("angle", "angle", 90.0, min=0.5, max=MAX_ANGLE_DEG, label="Angle"),
    Param("length", "length", 10.0, min=0.0, label="Length"),
    Param("length_ref", "enum", "outside", choices=DATUMS, label="Length measured to"),
    Param("position", "enum", "material_inside", choices=POSITIONS, label="Position"),
    Param("offset", "length", 0.0, label="Offset"),
    Param("flip", "bool", False, label="Fold the other way"),
] + WIDTH_PARAMS

EDGE_REFS = [RefSlot("edges", "edge", multi=True, label="Edges")]
SKETCH_FACE_REFS = [RefSlot("sketch", "sketch", label="Sketch with the bend line"), RefSlot("face", "face", label="Face")]

register(FeatureType("base_flange", "Base Flange", group="sheetmetal", needs_body=False, plan=base_plan, finish=finish, params=rule.RULE_PARAMS + [
    Param("side", "enum", "side1", choices=["side1", "side2", "mid"], label="Thickness side"),
    Param("depth", "length", 20.0, min=0.0, label="Width of a bent section"),
    Param("depth_mode", "enum", "blind", choices=["blind", "mid"], label="Width direction"),
    Param("flip_depth", "bool", False, label="Reverse width direction"),
], refs=[RefSlot("sketch", "sketch", label="Profile sketch")], roles=("seg*:ref", "seg*:opp", "bend*:in", "bend*:out", "end:start", "end:end", "cap:w0", "cap:w1")))

register(FeatureType("edge_flange", "Edge Flange", group="sheetmetal", plan=edge_flange_plan, finish=finish, params=flange_params(FLANGE_PARAMS), refs=EDGE_REFS, roles=("seg*:ref", "seg*:opp", "bend*:in", "bend*:out", "end:end", "cap:w0", "cap:w1")))

register(FeatureType("miter_flange", "Miter Flange", group="sheetmetal", plan=miter_plan, finish=finish, params=flange_params(FLANGE_PARAMS + [Param("gap", "length", None, min=0.0, label="Gap at the miter")]), refs=EDGE_REFS, roles=("seg*:ref", "seg*:opp", "bend*:in", "bend*:out", "end:end", "cap:w0", "cap:w1")))

register(FeatureType("hem", "Hem", group="sheetmetal", plan=hem_plan, finish=finish, params=flange_params([
    Param("hem", "enum", "closed", choices=HEMS, label="Hem type"),
    Param("gap", "length", None, min=0.0, label="Gap of an open hem"),
    Param("length", "length", 8.0, min=0.0, label="Return length"),
    Param("angle", "angle", 215.0, min=181.0, max=330.0, label="Angle of a teardrop or rolled hem"),
    Param("hem_radius", "length", None, min=0.0, label="Inside radius of a teardrop or rolled hem"),
    Param("position", "enum", "bend_outside", choices=POSITIONS, label="Position"),
    Param("offset", "length", 0.0, label="Offset"),
    Param("flip", "bool", False, label="Fold the other way"),
] + WIDTH_PARAMS), refs=EDGE_REFS, roles=("seg*:ref", "seg*:opp", "bend*:in", "bend*:out", "end:end", "cap:w0", "cap:w1")))

register(FeatureType("jog", "Jog", group="sheetmetal", plan=strip_plan("sm_jog", "jog"), finish=finish, params=rule.OVERRIDE_PARAMS + [
    Param("offset", "length", 10.0, min=0.0, label="Offset"),
    Param("angle", "angle", 90.0, min=0.5, max=MAX_ANGLE_DEG, label="Angle"),
    Param("flip", "bool", False, label="Fold the other way"),
    Param("flip_side", "bool", False, label="Move the other side"),
], refs=SKETCH_FACE_REFS, roles=("seg*:ref", "seg*:opp", "bend*:in", "bend*:out")))

register(FeatureType("sketched_bend", "Sketched Bend", group="sheetmetal", plan=strip_plan("sm_sketched_bend", "sketched_bend"), finish=finish, params=rule.OVERRIDE_PARAMS + [
    Param("angle", "angle", 90.0, min=0.5, max=MAX_ANGLE_DEG, label="Angle"),
    Param("flip", "bool", False, label="Fold the other way"),
    Param("flip_side", "bool", False, label="Move the other side"),
], refs=SKETCH_FACE_REFS, roles=("bend*:in", "bend*:out")))

register(FeatureType("bend_relief", "Bend Relief", group="sheetmetal", plan=relief_plan, finish=finish, params=rule.RELIEF_PARAMS + [
    Param("bends", "json", None, label="Bends"),
    Param("ends", "enum", "both", choices=["both", "start", "end"], label="Bend ends"),
], roles=("~",)))

register(FeatureType("corner_relief", "Corner Relief", group="sheetmetal", plan=corner_plan, finish=finish, params=[
    Param("corners", "json", None, label="Bend pairs"),
    Param("shape", "enum", "round", choices=["round", "square", "tear"], label="Shape"),
    Param("size", "length", 3.0, min=0.0, label="Size"),
], roles=("~",)))

register(FeatureType("convert_sheet", "Convert to Sheet Metal", group="sheetmetal", plan=convert_plan, finish=finish, params=rule.RULE_PARAMS, refs=[RefSlot("face", "face", label="Fixed face")], roles=("~",)))
