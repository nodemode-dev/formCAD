import math

from app.part.registry import FeatureType, Param, PartError, RefSlot, register
from app.plastic import records, rule, snap

FACE = [RefSlot("face", "face", label="Face to stand on")]
RIM = [RefSlot("face", "face", label="Rim face")]


def point_mm(step, name, label):
    v = step.p(name)
    if v is None:
        raise PartError("Give the %s as three numbers." % label)
    try:
        out = [float(c) * step.mm for c in v]
    except (TypeError, ValueError):
        raise PartError("The %s needs three numbers." % label)
    if len(out) != 3 or not all(math.isfinite(c) for c in out):
        raise PartError("The %s needs three finite numbers." % label)
    return out


def pick(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def boss_plan(step):
    rl = rule.current(step.d)
    screw = step.length("screw_diameter")
    hole = step.length("hole_diameter")
    od = step.length("outer_diameter")
    if hole is None:
        hole = screw
    if hole is None:
        raise PartError("Give the screw diameter or the hole diameter of the boss.")
    if od is None:
        ratio = rl["boss_od_ratio_insert"] if step.p("insert") else rl["boss_od_ratio"]
        od = ratio * (screw if screw is not None else hole)
    h = step.length("height")
    depth = pick(step.length("hole_depth"), h)
    draft = pick(step.p("draft"), rl["min_draft"])
    fillet = pick(step.length("base_fillet"), rl["boss_base_fillet"])
    step.pl = {"kind": "boss", "outer_diameter": od, "hole_diameter": hole, "screw_diameter": screw, "height": h, "hole_depth": depth, "draft": draft, "base_fillet": fillet, "insert": bool(step.p("insert"))}
    return {"method": "pl_boss", "params": {"face": step.face("face"), "point": point_mm(step, "point", "boss centre"), "outer_diameter": od, "hole_diameter": hole, "height": h, "hole_depth": depth, "draft": draft, "base_fillet": fillet}}


def rib_plan(step):
    rl = rule.current(step.d)
    t = step.length("thickness")
    if t is None:
        t = rl["rib_ratio_min"] * rule.need_wall(rl, "rib thickness")
    draft = pick(step.p("draft"), rl["min_draft"])
    fillet = pick(step.length("base_fillet"), max(rl["rib_base_fillet_ratio"] * t, rl["corner_radius_min"] or 0.0))
    h = step.length("height")
    step.pl = {"kind": "rib", "thickness": t, "height": h, "draft": draft, "base_fillet": fillet}
    return {"method": "pl_rib", "params": {"face": step.face("face"), "start": point_mm(step, "start", "rib start"), "end": point_mm(step, "end", "rib end"), "thickness": t, "height": h, "draft": draft, "base_fillet": fillet}}


def hook_plan(step):
    rl = rule.current(step.d)
    L, h, b, y = step.length("beam_length"), step.length("root_thickness"), step.length("width"), step.length("undercut")
    ratio = step.p("tip_ratio")
    lead = step.p("lead_angle")
    ret = step.p("return_angle")
    fillet = pick(step.length("root_fillet"), max(rl["snap_root_radius_min"] or 0.0, h / 2.0))
    d = step.p("direction")
    if d is None or len(d) != 3 or not any(abs(float(c)) > 0 for c in d):
        raise PartError("Give the direction the hook projects, three numbers lying in the face.")
    k = snap.taper_k(ratio)
    eps = snap.strain_pct(L, h, y, ratio)
    allow = rl["snap_strain_allowable"]
    step.pl = {"kind": "snap_hook", "beam_length": L, "root_thickness": h, "tip_ratio": ratio, "width": b, "undercut": y, "lead_angle": lead, "return_angle": ret, "root_fillet": fillet, "taper_k": k, "strain_pct": eps, "allowable_pct": allow}
    return {"method": "pl_snap_hook", "params": {"face": step.face("face"), "point": point_mm(step, "point", "hook position"), "direction": [float(c) for c in d], "beam_length": L, "root_thickness": h, "tip_ratio": ratio, "width": b, "undercut": y, "lead_angle": lead, "return_angle": ret, "root_fillet": fillet}}


def ring_values(step, rl, groove):
    wall = pick(step.length("wall"), rl["nominal_wall"])
    lip_w = pick(step.length("lip_width"), rl["lip_width_ratio"] * wall if wall else None) if groove else None
    lip_h = pick(step.length("lip_height"), rl["lip_height_ratio"] * wall if wall else None) if groove else None
    if groove:
        width = step.length("width")
        if width is None:
            if lip_w is None:
                raise PartError("Give the groove width or the lip width, or set the nominal wall in the plastic rule.")
            width = lip_w + rl["groove_extra_width"]
        depth = step.length("depth")
        if depth is None:
            if lip_h is None:
                raise PartError("Give the groove depth or the lip height, or set the nominal wall in the plastic rule.")
            welded = bool(step.p("welded"))
            depth = lip_h + (-rl["groove_extra_depth"] if welded else rl["groove_extra_depth"])
        height = depth
    else:
        width = step.length("width")
        height = step.length("height")
        if width is None:
            width = rl["lip_width_ratio"] * rule.need_wall(rl, "lip width")
        if height is None:
            height = rl["lip_height_ratio"] * rule.need_wall(rl, "lip height")
    offset = step.length("offset")
    if offset is None:
        if not wall:
            raise PartError("Give the offset from the outer edge, or set the nominal wall in the plastic rule to centre the ring on the wall.")
        offset = (wall - width) / 2.0
    if offset < 0:
        raise PartError("The ring would start outside the rim; the offset is negative (wall %.3g mm, width %.3g mm)." % (wall or 0.0, width))
    return wall, width, height, offset


def lip_plan(step):
    rl = rule.current(step.d)
    wall, width, height, offset = ring_values(step, rl, False)
    draft = pick(step.p("draft"), rl["lip_draft"])
    step.pl = {"kind": "lip", "wall": wall, "width": width, "height": height, "offset": offset, "draft": draft}
    return {"method": "pl_lip", "params": {"face": step.face("face"), "width": width, "height": height, "offset": offset, "draft": draft}}


def groove_plan(step):
    rl = rule.current(step.d)
    wall, width, depth, offset = ring_values(step, rl, True)
    draft = pick(step.p("draft"), rl["lip_draft"])
    step.pl = {"kind": "groove", "wall": wall, "width": width, "depth": depth, "offset": offset, "draft": draft, "welded": bool(step.p("welded"))}
    return {"method": "pl_groove", "params": {"face": step.face("face"), "width": width, "depth": depth, "offset": offset, "draft": draft}}


def finish(step, res):
    pl = getattr(step, "pl", None)
    if pl is None:
        return
    row = {"kind": pl["kind"], "type": step.feat["type"], "values": dict(pl), "warnings": list(step.warnings)}
    row["result"] = {k: res[k] for k in ("hook_length", "tip_thickness", "top_diameter", "top_thickness", "length", "ring_area", "volume", "volume_before") if k in res}
    records.write(step.d, step.feat["id"], row)


register(FeatureType("plastic_boss", "Boss", group="plastic", plan=boss_plan, finish=finish, params=[
    Param("point", "vector", None, label="Centre point"),
    Param("screw_diameter", "length", None, min=0.0, label="Screw diameter"),
    Param("outer_diameter", "length", None, min=0.0, label="Outer diameter"),
    Param("hole_diameter", "length", None, min=0.0, label="Hole diameter"),
    Param("insert", "bool", False, label="For a pressed-in insert"),
    Param("height", "length", 8.0, min=0.0, label="Height"),
    Param("hole_depth", "length", None, min=0.0, label="Hole depth"),
    Param("draft", "angle", None, min=0.0, max=15.0, label="Draft"),
    Param("base_fillet", "length", None, min=0.0, label="Base fillet"),
], refs=FACE, roles=("top", "side", "bore", "floor")))

register(FeatureType("plastic_rib", "Rib", group="plastic", plan=rib_plan, finish=finish, params=[
    Param("start", "vector", None, label="Start point"),
    Param("end", "vector", None, label="End point"),
    Param("thickness", "length", None, min=0.0, label="Thickness at the base"),
    Param("height", "length", 6.0, min=0.0, label="Height"),
    Param("draft", "angle", None, min=0.0, max=15.0, label="Draft per side"),
    Param("base_fillet", "length", None, min=0.0, label="Base fillet"),
], refs=FACE, roles=("top", "side:l", "side:r", "end:start", "end:end")))

register(FeatureType("snap_hook", "Snap-Fit Hook", group="plastic", plan=hook_plan, finish=finish, params=[
    Param("point", "vector", None, label="Root position"),
    Param("direction", "vector", [1, 0, 0], label="Hook direction"),
    Param("beam_length", "length", 10.0, min=0.0, label="Beam length"),
    Param("root_thickness", "length", 1.5, min=0.0, label="Thickness at the root"),
    Param("tip_ratio", "length", 1.0, min=0.1, max=1.0, label="Tip thickness over root thickness", unit=""),
    Param("width", "length", 5.0, min=0.0, label="Width"),
    Param("undercut", "length", 1.0, min=0.0, label="Undercut (deflection)"),
    Param("lead_angle", "angle", 30.0, min=5.0, max=80.0, label="Lead-in angle"),
    Param("return_angle", "angle", 90.0, min=20.0, max=90.0, label="Return angle"),
    Param("root_fillet", "length", None, min=0.0, label="Root fillet"),
], refs=FACE, roles=("beam:front", "beam:back", "beam:l", "beam:r", "tip", "hook:return", "hook:lead")))

register(FeatureType("plastic_lip", "Lip", group="plastic", plan=lip_plan, finish=finish, params=[
    Param("width", "length", None, min=0.0, label="Width"),
    Param("height", "length", None, min=0.0, label="Height"),
    Param("offset", "length", None, min=0.0, label="Offset from the outer edge"),
    Param("wall", "length", None, min=0.0, label="Wall thickness"),
    Param("draft", "angle", None, min=0.0, max=15.0, label="Sidewall draft"),
], refs=RIM, roles=("top", "inner", "outer")))

register(FeatureType("plastic_groove", "Groove", group="plastic", plan=groove_plan, finish=finish, params=[
    Param("width", "length", None, min=0.0, label="Width"),
    Param("depth", "length", None, min=0.0, label="Depth"),
    Param("offset", "length", None, min=0.0, label="Offset from the outer edge"),
    Param("wall", "length", None, min=0.0, label="Wall thickness"),
    Param("draft", "angle", None, min=0.0, max=15.0, label="Sidewall draft"),
    Param("lip_width", "length", None, min=0.0, label="Width of the mating lip"),
    Param("lip_height", "length", None, min=0.0, label="Height of the mating lip"),
    Param("welded", "bool", False, label="Welded joint (shallower groove)"),
], refs=RIM, roles=("floor", "inner", "outer")))
