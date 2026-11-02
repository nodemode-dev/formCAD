from app.part.registry import FeatureType, Param, PartError, RefLost, RefSlot, register
from app.solid import holes

SWEEP_MODES = ["corrected_frenet", "frenet", "fixed", "binormal"]
CORNERS = ["transformed", "right", "round"]
CONTACTS = ["none", "contact", "border"]
END_KINDS = ["none", "normal", "direction"]
SIDES = ["both", "first", "second"]


def profiles_of(step, slot):
    refs = step.refs(slot)
    if not refs:
        if step.required(slot):
            raise RefLost("Choose the sketches for %s." % step.ft.label, slot)
        return []
    out = []
    for ref in refs:
        fid = ref.get("id")
        entry = step.rb.cache.entries.get(fid)
        if entry is None or entry.error or entry.profile is None:
            raise RefLost("The sketch %s in %s is missing or failed." % (fid, slot), slot)
        out.append(entry.profile)
    return out


def world_points(prof, flip=False):
    fr = prof["frame"]
    o, x, n = fr["origin"], fr["xdir"], fr["normal"]
    y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]]
    pts = [[o[i] + x[i] * q["u"] + y[i] * q["v"] for i in range(3)] for q in prof.get("points") or []]
    return pts, ([-c for c in n] if flip else list(n)), list(x)


def sweep_plan(op):
    def plan(step):
        p = {"op": op, "profile": step.profile("sketch"), "path": step.profile("path"), "mode": step.p("mode") or "corrected_frenet", "twist": step.p("twist") or 0.0, "scale_end": step.p("scale_end") or 1.0, "transition": step.p("transition") or "transformed"}
        if p["mode"] == "binormal":
            b = step.p("binormal")
            if not b or not any(b):
                raise PartError("Enter the binormal direction for this mode.")
            p["binormal"] = [float(c) for c in b]
        if step.refs("guide"):
            p["guide"] = step.profile("guide")
            p["guide_contact"] = step.p("guide_contact") or "none"
        return {"method": "feat_sweep", "params": p}

    return plan


def loft_plan(op):
    def plan(step):
        sections = profiles_of(step, "sections")
        tail = step.p("apex")
        if tail and any(tail):
            sections = sections + [{"point": [float(c) * step.mm for c in tail]}]
        if len(sections) < 2:
            raise PartError("A loft needs at least two sections.")
        p = {"op": op, "sections": sections, "ruled": bool(step.p("ruled")), "smoothing": bool(step.p("smoothing")), "check_compatibility": bool(step.p("check"))}
        for which in ("start", "end"):
            kind = step.p(which + "_kind") or "none"
            if kind != "none":
                cond = {"kind": kind, "magnitude": step.p(which + "_magnitude") or 0.3}
                if kind == "direction":
                    d = step.p(which + "_dir")
                    if not d or not any(d):
                        raise PartError("Enter the %s direction." % which)
                    cond["direction"] = [float(c) for c in d]
                p[which] = cond
        guides = profiles_of(step, "guides")
        if guides:
            p["guides"] = guides
            step.warn("Guide curves are recorded but the kernel loft uses the sections only.")
        return {"method": "feat_loft", "params": p}

    return plan


def curve_record(step, handle):
    e = step.d.get(int(handle))
    if e is None or e.kind != "nurbscurve":
        raise PartError("The curve %s is not a NURBS curve." % handle)
    rec = e.record()
    rec["poles"] = [[c * step.mm for c in q] for q in rec["poles"]]
    return {"nurbs": rec}


def boundary_plan(step):
    groups = []
    for prof in profiles_of(step, "boundaries"):
        groups.append({"curves": [prof]})
    for group in step.p("curves") or []:
        if not isinstance(group, list) or len(group) < 3:
            raise PartError("Each boundary needs at least three curves.")
        groups.append({"curves": [curve_record(step, h) for h in group]})
    if not groups:
        raise RefLost("Choose the boundary sketches or curves.", "boundaries")
    p = {"op": "add", "surfaces": groups, "cap_planar": bool(step.p("cap_planar")), "tolerance": step.length("tolerance") or 1e-4}
    return {"method": "feat_boundary", "params": p}


def rib_plan(step):
    prof = step.profile("sketch")
    if not prof.get("open"):
        raise PartError("A rib needs an open sketch profile.")
    p = {"profile": {"frame": prof["frame"], "open": [prof["open"][0]]}, "thickness": step.length("thickness"), "thickness_side": step.p("thickness_side") or "both", "grow": step.p("grow") or "one", "flip": bool(step.p("flip")), "draft": step.p("draft") or 0.0, "draft_outward": bool(step.p("draft_out"))}
    if not p["thickness"] or p["thickness"] <= 0:
        raise PartError("The rib thickness must be positive.")
    return {"method": "feat_rib", "params": p}


def hole_plan(step):
    prof = step.profile("sketch")
    pts, normal, xdir = world_points(prof, bool(step.p("flip")))
    if not pts:
        raise PartError("Place at least one point in the hole sketch.")
    values = {p.name: step.p(p.name) for p in step.ft.params}
    spec, info, notes = holes.resolve(values, step.mm)
    for n in notes:
        step.warn(n)
    return {"method": "feat_hole", "params": {"spec": spec, "positions": pts, "normal": normal, "xdir": xdir}}


def hole_finish(step, res):
    cache = step.rb.cache
    store = getattr(cache, "cosmetic", None)
    if store is None:
        store = {}
        cache.cosmetic = store
    if step.p("cosmetic") is False:
        store.pop(step.feat["id"], None)
    else:
        store[step.feat["id"]] = res.get("cosmetic_threads") or []


SWEEP_PARAMS = [
    Param("mode", "enum", "corrected_frenet", choices=SWEEP_MODES, label="Orientation"),
    Param("binormal", "vector", None, label="Binormal direction"),
    Param("twist", "angle", 0.0, min=-36000.0, max=36000.0, label="Twist along path"),
    Param("scale_end", "length", 1.0, min=0.001, max=1000.0, label="End scale", unit="x"),
    Param("transition", "enum", "transformed", choices=CORNERS, label="Path corners"),
    Param("guide_contact", "enum", "none", choices=CONTACTS, label="Guide contact"),
]
SWEEP_REFS = [RefSlot("sketch", "sketch", label="Profile"), RefSlot("path", "sketch", label="Path"), RefSlot("guide", "sketch", required=False, label="Guide curve")]
SWEEP_ROLES = ("side:*", "cap:start", "cap:end")

register(FeatureType("sweep", "Swept boss", group="shape features", needs_body=False, params=SWEEP_PARAMS, refs=SWEEP_REFS, roles=SWEEP_ROLES, plan=sweep_plan("add")))
register(FeatureType("sweep_cut", "Swept cut", group="shape features", needs_body=True, params=SWEEP_PARAMS, refs=SWEEP_REFS, roles=SWEEP_ROLES, plan=sweep_plan("cut")))

LOFT_PARAMS = [
    Param("ruled", "bool", False, label="Straight between sections"),
    Param("smoothing", "bool", True, label="Smooth fit"),
    Param("check", "bool", True, label="Match section starts"),
    Param("apex", "vector", None, label="End point"),
    Param("start_kind", "enum", "none", choices=END_KINDS, label="Start tangent"),
    Param("start_magnitude", "length", 0.3, min=0.01, max=2.0, label="Start strength", unit="x"),
    Param("start_dir", "vector", None, label="Start direction"),
    Param("end_kind", "enum", "none", choices=END_KINDS, label="End tangent"),
    Param("end_magnitude", "length", 0.3, min=0.01, max=2.0, label="End strength", unit="x"),
    Param("end_dir", "vector", None, label="End direction"),
]
LOFT_REFS = [RefSlot("sections", "sketch", multi=True, label="Sections"), RefSlot("guides", "sketch", multi=True, required=False, label="Guide curves")]
LOFT_ROLES = ("side:*", "cap:start", "cap:end")

register(FeatureType("loft", "Lofted boss", group="shape features", needs_body=False, params=LOFT_PARAMS, refs=LOFT_REFS, roles=LOFT_ROLES, plan=loft_plan("add")))
register(FeatureType("loft_cut", "Lofted cut", group="shape features", needs_body=True, params=LOFT_PARAMS, refs=LOFT_REFS, roles=LOFT_ROLES, plan=loft_plan("cut")))

register(FeatureType("boundary_solid", "Boundary surface to solid", group="shape features", needs_body=False, plan=boundary_plan, params=[
    Param("curves", "json", None, label="Curve groups"),
    Param("cap_planar", "bool", True, label="Close flat openings"),
    Param("tolerance", "length", 0.0001, min=0.0000001, label="Fit tolerance"),
], refs=[RefSlot("boundaries", "sketch", multi=True, required=False, label="Boundary sketches")], roles=("surface:*", "cap:*")))

register(FeatureType("rib", "Rib", group="shape features", needs_body=True, plan=rib_plan, params=[
    Param("thickness", "length", 3.0, min=0.0, label="Thickness"),
    Param("thickness_side", "enum", "both", choices=SIDES, label="Thickness sides"),
    Param("grow", "enum", "one", choices=["one", "both"], label="Grows"),
    Param("flip", "bool", False, label="Other direction"),
    Param("draft", "angle", 0.0, min=-45.0, max=45.0, label="Draft angle"),
    Param("draft_out", "bool", False, label="Draft outward"),
], refs=[RefSlot("sketch", "sketch", label="Profile")], roles=("rib:*",)))

register(FeatureType("hole", "Hole builder", group="shape features", needs_body=True, plan=hole_plan, finish=hole_finish, params=[
    Param("kind", "enum", "simple", choices=list(holes.KINDS), label="Hole type"),
    Param("standard", "text", "iso_metric_coarse", label="Standard"),
    Param("size", "text", "", label="Size"),
    Param("fit", "enum", "medium", choices=list(holes.FITS), label="Clearance series"),
    Param("diameter", "length", None, min=0.0, label="Diameter"),
    Param("end", "enum", "blind", choices=["blind", "through"], label="End condition"),
    Param("depth", "length", 10.0, min=0.0, label="Depth"),
    Param("tip_angle", "angle", 0.0, min=0.0, max=179.0, label="Drill point angle"),
    Param("cbore_diameter", "length", None, min=0.0, label="Counterbore diameter"),
    Param("cbore_depth", "length", None, min=0.0, label="Counterbore depth"),
    Param("csk_diameter", "length", None, min=0.0, label="Countersink diameter"),
    Param("csk_angle", "angle", 90.0, min=10.0, max=170.0, label="Countersink angle"),
    Param("tap_drill", "length", None, min=0.0, label="Tap drill diameter"),
    Param("thread_nominal", "length", None, min=0.0, label="Thread nominal diameter"),
    Param("thread_pitch", "length", None, min=0.0, label="Thread pitch"),
    Param("thread_depth", "length", None, min=0.0, label="Thread depth"),
    Param("cosmetic", "bool", True, label="Cosmetic thread"),
    Param("flip", "bool", False, label="Other direction"),
], refs=[RefSlot("sketch", "sketch", label="Hole centres")], roles=("hole*:*",)))
