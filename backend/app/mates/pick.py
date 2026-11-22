import math

from app.assembly import parts, walk
from app.mates import eqs
from app.mates.eqs import AX, CV, PL, PT
from app.param.units import mm_per_unit
from app.solid import work

ORIGINS = {
    "xy": (PL, [0, 0, 1]), "yz": (PL, [1, 0, 0]), "xz": (PL, [0, 1, 0]),
    "x": (AX, [1, 0, 0]), "y": (AX, [0, 1, 0]), "z": (AX, [0, 0, 1]), "origin": (PT, None),
}


class PickError(ValueError):
    pass


def _vec(v, s=1.0):
    return [float(x) * s for x in v]


def from_geometry(g: dict, inv: float) -> dict:
    k = g.get("kind")
    if k == "plane":
        return {"kind": PL, "p": _vec(g["origin"], inv), "d": _vec(g["normal"])}
    if k in ("cylinder", "cone"):
        return {"kind": AX, "p": _vec(g["axis_origin"], inv), "d": _vec(g["axis"]), "r": float(g["radius"]) * inv}
    if k == "sphere":
        return {"kind": PT, "p": _vec(g["centre"], inv), "r": float(g["radius"]) * inv}
    if k == "torus":
        return {"kind": AX, "p": _vec(g["centre"], inv), "d": _vec(g["axis"])}
    if k == "line":
        return {"kind": AX, "p": _vec(g["mid"], inv), "d": _vec(g["direction"])}
    if k == "circle":
        return {"kind": AX, "p": _vec(g["centre"], inv), "d": _vec(g["axis"]), "r": float(g["radius"]) * inv}
    if k == "vertex":
        return {"kind": PT, "p": _vec(g["point"], inv)}
    raise PickError("That face or edge has no plane, axis or point to mate; pick a flat face, a cylinder, a sphere, a circle, a straight edge or a vertex.")


def explicit(g: dict, inv: float) -> dict:
    kind = str(g.get("kind") or "").lower()
    kind = {"face": PL, "line": AX, "center": PT, "centre": PT, "polyline": CV, "path": CV, "profile": CV}.get(kind, kind)
    if kind not in (PL, AX, PT, CV):
        raise PickError("A reference geometry needs kind plane, axis, point or curve.")
    if kind == CV:
        pts = g.get("pts")
        if not isinstance(pts, list) or len(pts) < 2 or any(not isinstance(q, (list, tuple)) or len(q) not in (2, 3) for q in pts):
            raise PickError("A curve needs pts: a list of at least 2 points of x, y and optional z.")
        pts = [_vec(list(q) + [0.0] * (3 - len(q)), inv) for q in pts]
        return {"kind": CV, "p": pts[0], "pts": pts, "closed": bool(g.get("closed", False))}
    out = {"kind": kind, "p": _vec(g.get("p") or g.get("origin") or [0, 0, 0], inv)}
    if kind != PT:
        d = g.get("d") or g.get("normal") or g.get("axis")
        if d is None:
            raise PickError("A %s needs a direction." % kind)
        out["d"] = _vec(d)
    if g.get("r") is not None:
        out["r"] = float(g["r"]) * inv
    return out


def instance_of(doc, cid: str):
    for inst in walk.instances(doc):
        if inst.cid == cid and inst.depth == 0 and not inst.index:
            return inst
    raise PickError("There is no component %s to pick on." % cid)


def body_shape(doc, cid: str, body_handle=None):
    inst = instance_of(doc, cid)
    lp = inst.part
    if lp is None:
        raise PickError("The part of %s is missing, so nothing can be picked on it." % cid)
    if getattr(lp, "is_assembly", False):
        raise PickError("%s is a sub-assembly; pick on its parts or lock it as a unit." % cid)
    if not lp.bodies:
        raise PickError("The part of %s has no solid." % cid)
    body = lp.bodies[0]
    if body_handle is not None:
        hit = [b for b in lp.bodies if b.handle == int(body_handle)]
        if not hit:
            raise PickError("%s has no body %s." % (cid, body_handle))
        body = hit[0]
    try:
        return parts.shapes(lp, body)
    except work.SolidError as err:
        raise PickError(str(err))


def resolve(doc, ref: dict) -> dict:
    if not isinstance(ref, dict):
        raise PickError("A mate reference is an object with comp and a face, edge, vertex, origin or geom.")
    d = doc.drawing
    inv = 1.0 / mm_per_unit(d)
    cid = ref.get("comp")
    if cid in (None, "", "world", "ground"):
        if not ref.get("geom"):
            raise PickError("A world reference needs a geom.")
        out = explicit(ref["geom"], 1.0)
        out["comp"] = None
        return out
    cid = str(cid)
    if ref.get("geom"):
        out = explicit(ref["geom"], inv)
    elif ref.get("origin"):
        key = str(ref["origin"]).lower()
        if key not in ORIGINS:
            raise PickError("Origin reference %s is not one of %s." % (key, ", ".join(ORIGINS)))
        kind, direction = ORIGINS[key]
        out = {"kind": kind, "p": [0.0, 0.0, 0.0]}
        if direction:
            out["d"] = [float(v) for v in direction]
    else:
        which = [k for k in ("face", "edge", "vertex") if ref.get(k) is not None]
        if len(which) != 1:
            raise PickError("Give exactly one of face, edge, vertex, origin or geom for a reference.")
        wid = body_shape(doc, cid, ref.get("body"))
        try:
            g = work.kcall("geometry", {"id": wid, which[0]: int(ref[which[0]])}, work.SHORT)
        except work.SolidError as err:
            raise PickError(str(err))
        out = from_geometry(g, inv)
    for k in ("r",):
        if ref.get(k) is not None:
            out[k] = float(ref[k]) * inv
    out["comp"] = cid
    return out


def side_of(spec: dict) -> eqs.Side:
    try:
        return eqs.Side(spec.get("comp"), spec["kind"], spec["p"], spec.get("d"), spec.get("r"), spec.get("pts"), spec.get("closed", False))
    except (ValueError, KeyError, TypeError) as err:
        raise PickError(str(err))


def finite(spec: dict) -> None:
    for k in ("p", "d"):
        for v in spec.get(k) or []:
            if not math.isfinite(float(v)):
                raise PickError("A reference has a non-finite number.")
    for q in spec.get("pts") or []:
        if not all(math.isfinite(float(v)) for v in q):
            raise PickError("A reference has a non-finite number.")
    if len(spec.get("pts") or []) > eqs.MAX_CURVE_POINTS:
        raise PickError("A curve reference takes at most %d points." % eqs.MAX_CURVE_POINTS)
