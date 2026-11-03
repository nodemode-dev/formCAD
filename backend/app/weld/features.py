import math

from app.part import store
from app.part.registry import FeatureType, Param, PartError, RefLost, RefSlot, register
from app.weld import joints, records, shapes

MAX_PARTS = 600


def profile_lookup(step):
    mm = step.mm
    listed = {r.get("id"): r for r in step.refs("profiles")}

    def lookup(spec, mid):
        if isinstance(spec, dict):
            try:
                return shapes.regions_of(spec, mm)
            except shapes.ShapeError as err:
                raise PartError("Member %s: %s" % (mid, err))
        if not spec:
            raise PartError("Member %s needs a profile: a sketch feature id or an inline shape." % mid)
        fid = str(spec)
        if fid not in listed:
            raise PartError("Member %s names profile %s, which is not in the frame's profile sketches." % (mid, fid))
        entry = step.rb.cache.entries.get(fid)
        rec = store.get(step.d, fid)
        if entry is None or rec is None:
            raise RefLost("The profile sketch %s no longer exists." % fid, "profiles")
        if entry.error or entry.profile is None:
            raise RefLost("The profile sketch %s failed or has no profile." % fid, "profiles")
        regions = entry.profile.get("regions") or []
        if not regions:
            raise PartError("The profile sketch %s has no closed region; close its outline." % fid)
        return regions, str(rec.get("label") or fid)

    return lookup


def plan(step):
    mm = step.mm
    tol = step.length("tolerance")
    tol = 0.01 * mm if tol is None else tol
    if not 1e-9 < tol < 1e4:
        raise PartError("The junction tolerance is out of range.")
    members = joints.read_members(step.p("members"), mm, profile_lookup(step))
    nodes = joints.solve(members, step.p("corner") or "miter", step.p("junctions"), tol, mm)
    caps = joints.build_caps(members, step.p("end_caps"), mm, "C")
    gussets = joints.build_gussets(members, nodes, step.p("gussets"), mm)
    if len(members) + len(caps) + len(gussets) > MAX_PARTS:
        raise PartError("A frame holds at most %d parts." % MAX_PARTS)
    step.weld = {"members": members, "caps": caps, "gussets": gussets}
    return {"method": "weld_frame", "params": {"members": [joints.worker_member(m) for m in members], "caps": [{k: c[k] for k in ("id", "origin", "axis", "u", "thickness", "regions")} for c in caps], "gussets": [{k: g[k] for k in ("id", "tri", "normal", "thickness", "cut_members")} for g in gussets]}}


def extent_of(regions):
    pts = shapes.points_of(regions)
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    return max(us) - min(us), max(vs) - min(vs)


def finish(step, res):
    w = getattr(step, "weld", None)
    if w is None:
        return
    info = res.get("info") or {}
    got = {m["id"]: m for m in info.get("members") or []}
    parts = {m["id"]: m for m in info.get("parts") or []}
    density = step.p("density")
    rows = []
    for m in w["members"]:
        g = got.get(m["id"])
        if g is None:
            raise PartError("The kernel returned no solid for member %s." % m["id"])
        if g.get("solids", 1) != 1:
            step.warn("Member %s came out as %d pieces; check its trims." % (m["id"], g["solids"]))
        s, e = m["ends"]["s"], m["ends"]["e"]
        rows.append({
            "key": m["id"], "kind": "member", "mid": m["id"], "label": m["label"], "profile": m["profile"], "group": m["group"],
            "a": m["a"], "b": m["b"], "nominal": m["L"], "length": g["length"], "volume": g["volume"], "density": density,
            "angle1": s["angle"], "angle2": e["angle"], "rot1": s["rot"], "rot2": e["rot"], "kind1": s["kind"], "kind2": e["kind"],
            "against1": s["against"], "against2": e["against"], "notes": m["notes"], "extend": [m["ext"]["s"], m["ext"]["e"]],
        })
    for c in w["caps"]:
        g = parts.get(c["id"])
        du, dv = extent_of(c["regions"])
        rows.append({"key": c["id"], "kind": "end_cap", "member": c["member"], "end": c["end"], "profile": "End cap %s" % c["kind"], "thickness": c["thickness"], "length": max(du, dv), "width": min(du, dv), "volume": g["volume"] if g else 0.0, "density": density, "label": c["label"]})
    for gu in w["gussets"]:
        g = parts.get(gu["id"])
        rows.append({"key": gu["id"], "kind": "gusset", "members": gu["members"], "profile": "Gusset", "thickness": gu["thickness"], "length": gu["leg"], "width": gu["leg"], "volume": g["volume"] if g else 0.0, "density": density, "label": gu["label"]})
        if g is not None and g.get("solids", 1) != 1:
            step.warn("Gusset %s came out as %d pieces; increase its leg." % (gu["id"], g["solids"]))
    records.write(step.d, step.feat["id"], rows)


register(FeatureType("weld_frame", "Weld Frame", group="weldment", needs_body=False, plan=plan, finish=finish, params=[
    Param("members", "json", None, label="Members"),
    Param("corner", "enum", "miter", choices=list(joints.TREATMENTS), label="Corner treatment"),
    Param("junctions", "json", None, label="Junction overrides"),
    Param("tolerance", "length", 0.01, min=0.0, label="Junction tolerance"),
    Param("gussets", "json", None, label="Gussets"),
    Param("end_caps", "json", None, label="End caps"),
    Param("density", "json", None, label="Density in kg per cubic metre"),
], refs=[RefSlot("profiles", "sketch", multi=True, required=False, label="Profile sketches")], roles=("M*:start", "M*:end", "M*:f*", "C*:f*", "G*:f*")))
