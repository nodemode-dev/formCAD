import math

import numpy as np

from app.pipe.geometry import turn_frame, unit
from app.pipe.limits import PipeError
from app.solid import work

TYPES = ("elbow", "tee", "reducer", "flange")
LABEL = "Fittings are generated from parameters only: outside diameter, wall, centre-to-end and a few proportions. No standard or catalogue dimension table is shipped; the proportions below are FormCAD's own generic examples."
DEFAULTS = {
    "elbow": {"od": 20.0, "wall": 2.0, "clr": 30.0, "angle": 90.0},
    "tee": {"od": 20.0, "wall": 2.0, "c": 30.0, "branch_c": 30.0, "branch_od": None},
    "reducer": {"od": 20.0, "od_to": 14.0, "wall": 2.0, "wall_to": 2.0, "length": 40.0},
    "flange": {"od": 20.0, "wall": 2.0, "thickness": 8.0, "flange_od": 44.0, "bolt_circle": 32.0, "bolts": 4, "bolt_diameter": 4.5},
}
LIMITS = {"od": (0.5, 5000.0), "wall": (0.05, 500.0), "clr": (0.5, 20000.0), "angle": (1.0, 179.0), "c": (0.5, 20000.0), "branch_c": (0.5, 20000.0), "od_to": (0.5, 5000.0), "wall_to": (0.05, 500.0), "length": (0.5, 20000.0), "thickness": (0.2, 2000.0), "flange_od": (1.0, 10000.0), "bolt_circle": (1.0, 10000.0), "bolt_diameter": (0.2, 500.0)}


def clean(kind: str, raw: dict | None) -> dict:
    if kind not in TYPES:
        raise PipeError("A fitting is one of %s." % ", ".join(TYPES))
    p = dict(DEFAULTS[kind])
    for k, v in (raw or {}).items():
        if k in p and v is not None:
            p[k] = v
    out = {}
    for k, v in p.items():
        if v is None:
            out[k] = None
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise PipeError("%s must be a number." % k)
        if k == "bolts":
            if x != int(x) or not 0 <= x <= 64:
                raise PipeError("The bolt count is a whole number from 0 to 64.")
            out[k] = int(x)
            continue
        lo, hi = LIMITS.get(k, (0.5, 5000.0))
        if not math.isfinite(x) or x < lo or x > hi:
            raise PipeError("%s must be between %g and %g." % (k, lo, hi))
        out[k] = x
    for a, b in (("od", "wall"), ("od_to", "wall_to")):
        if a in out and out.get(a) is not None and out[b] * 2 >= out[a]:
            raise PipeError("The wall must be less than half the outside diameter.")
    if kind == "elbow" and out["clr"] <= out["od"] / 2:
        raise PipeError("The centreline radius must exceed the tube radius.")
    if kind == "reducer" and abs(out["od"] - out["od_to"]) < 1e-6:
        raise PipeError("A reducer needs two different diameters.")
    if kind == "flange":
        if out["flange_od"] <= out["od"]:
            raise PipeError("The flange must be wider than the pipe.")
        if out["bolts"] and out["bolt_circle"] + out["bolt_diameter"] >= out["flange_od"]:
            raise PipeError("The bolt holes do not fit inside the flange diameter.")
    return out


def matrix(ex, ey, t, scale: float) -> list:
    ex = unit(np.array(ex, dtype=float))
    ey = np.array(ey, dtype=float)
    ey = unit(ey - float(np.dot(ey, ex)) * ex)
    ez = np.cross(ex, ey)
    t = np.array(t, dtype=float) * scale
    return [float(ex[0]), float(ey[0]), float(ez[0]), float(t[0]), float(ex[1]), float(ey[1]), float(ez[1]), float(t[1]), float(ex[2]), float(ey[2]), float(ez[2]), float(t[2])]


def perpendicular(axis):
    axis = unit(np.array(axis, dtype=float))
    pick = np.array([0.0, 0.0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    return unit(np.cross(axis, np.cross(pick, axis)))


def cyl(origin, axis, r, h):
    return work.kcall("primitive", {"kind": "cylinder", "origin": origin, "axis": axis, "radius": r, "height": h})["id"]


def cut(base, tools):
    return work.kcall("boolean", {"op": "cut", "base": base, "tools": tools}, work.LONG)["id"]


def fuse(base, tools):
    return work.kcall("boolean", {"op": "fuse", "base": base, "tools": tools}, work.LONG)["id"]


def build_elbow(p, s):
    r, od, wall, ang = p["clr"] * s, p["od"] * s, p["wall"] * s, math.radians(p["angle"])
    ro = work.kcall("primitive", {"kind": "torus", "major": r, "minor": od / 2.0})["id"]
    ri = work.kcall("primitive", {"kind": "torus", "major": r, "minor": od / 2.0 - wall})["id"]
    ring = cut(ro, [ri])
    m = (r + od) * 2.0
    rho = m / math.cos(ang / 8.0)
    verts = [[0.0, 0.0, 0.0]] + [[rho * math.cos(ang * k / 4.0), rho * math.sin(ang * k / 4.0), 0.0] for k in range(5)]
    h = od * 2.0
    wedge = work.kcall("primitive", {"kind": "extrude", "loops": [{"vertices": verts, "outer": True}], "plane": {"origin": [0.0, 0.0, -h], "normal": [0, 0, 1], "xdir": [1, 0, 0]}, "height": 2 * h})["id"]
    return work.kcall("boolean", {"op": "common", "base": ring, "tools": [wedge]}, work.LONG)["id"]


def build_tee(p, s):
    od, wall, c = p["od"] * s, p["wall"] * s, p["c"] * s
    bod = (p.get("branch_od") or p["od"]) * s
    bc = p["branch_c"] * s
    outer = fuse(cyl([-c, 0, 0], [1, 0, 0], od / 2.0, 2 * c), [cyl([0, 0, 0], [0, 1, 0], bod / 2.0, bc)])
    bores = [cyl([-c - 1.0, 0, 0], [1, 0, 0], od / 2.0 - wall, 2 * c + 2.0), cyl([0, 0, 0], [0, 1, 0], bod / 2.0 - wall, bc + 1.0)]
    return cut(outer, bores)


def build_reducer(p, s):
    r1, r2, wall, wall2, ln = p["od"] * s / 2.0, p["od_to"] * s / 2.0, p["wall"] * s, p["wall_to"] * s, p["length"] * s
    outer = work.kcall("primitive", {"kind": "cone", "origin": [0, 0, 0], "axis": [1, 0, 0], "radius1": r1, "radius2": r2, "height": ln})["id"]
    i1, i2 = r1 - wall, r2 - wall2
    if abs(i1 - i2) < 1e-6:
        inner = cyl([-1.0, 0, 0], [1, 0, 0], i1, ln + 2.0)
    else:
        k = 1.0 / ln
        inner = work.kcall("primitive", {"kind": "cone", "origin": [-1.0, 0, 0], "axis": [1, 0, 0], "radius1": i1 - (i2 - i1) * k, "radius2": i2 + (i2 - i1) * k, "height": ln + 2.0})["id"]
    return cut(outer, [inner])


def build_flange(p, s):
    fo, t = p["flange_od"] * s, p["thickness"] * s
    bore = (p["od"] - 2 * p["wall"]) * s / 2.0
    disk = cyl([0, 0, 0], [1, 0, 0], fo / 2.0, t)
    tools = [cyl([-1.0, 0, 0], [1, 0, 0], bore, t + 2.0)]
    for k in range(int(p["bolts"])):
        a = 2.0 * math.pi * k / p["bolts"]
        y, z = p["bolt_circle"] * s / 2.0 * math.cos(a), p["bolt_circle"] * s / 2.0 * math.sin(a)
        tools.append(cyl([-1.0, y, z], [1, 0, 0], p["bolt_diameter"] * s / 2.0, t + 2.0))
    return cut(disk, tools)


BUILDERS = {"elbow": build_elbow, "tee": build_tee, "reducer": build_reducer, "flange": build_flange}


def place_matrix(kind: str, p: dict, place: dict, s: float):
    if not place:
        return None
    pt = np.array(place["point"], dtype=float)
    if kind == "elbow":
        u_in = unit(np.array(place["u_in"], dtype=float))
        u_out = unit(np.array(place["u_out"], dtype=float))
        theta = math.acos(max(-1.0, min(1.0, float(np.dot(u_in, u_out)))))
        d, _n = turn_frame(u_in, u_out)
        r = p["clr"]
        rot_x, rot_y = -d, u_in
        local = np.array([r, r * math.tan(theta / 2.0), 0.0])
        ez = np.cross(rot_x, rot_y)
        t = pt - (rot_x * local[0] + rot_y * local[1] + ez * local[2])
        return matrix(rot_x, rot_y, t, s)
    axis = np.array(place["axis"], dtype=float)
    if kind == "tee":
        br = place.get("branch")
        br = np.array(br, dtype=float) if br is not None else perpendicular(axis)
        return matrix(axis, br, pt, s)
    return matrix(axis, perpendicular(axis), pt, s)


def make(d, kind: str, raw: dict | None, name: str, place: dict | None = None):
    p = clean(kind, raw)
    if kind == "elbow" and place:
        u_in = unit(np.array(place["u_in"], dtype=float))
        u_out = unit(np.array(place["u_out"], dtype=float))
        p["angle"] = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(u_in, u_out))))))
    s = work.mm(d)
    work.reset_if_restarted()
    wid = BUILDERS[kind](p, s)
    mtx = place_matrix(kind, p, place or {}, s)
    if mtx:
        wid = work.kcall("transform", {"id": wid, "matrix": mtx}, work.LONG)["id"]
    summary = work.kcall("shape_summary", {"id": wid})["summary"]
    body = work.new_body(d, wid, summary, name, {"op": "pipe_fitting", "kind": kind, "params": p})
    handle = d.add_entity(body)
    return handle, p, summary


def straight_body(d, p0, p1, od: float, wall: float, name: str):
    s = work.mm(d)
    work.reset_if_restarted()
    a = np.array(p0, dtype=float)
    v = np.array(p1, dtype=float) - a
    ln = float(np.linalg.norm(v))
    if ln < 1e-6:
        raise PipeError("A straight piece has no length.")
    axis = (v / ln).tolist()
    org = (a * s).tolist()
    outer = cyl(org, axis, od * s / 2.0, ln * s)
    inner = cyl((a * s - np.array(axis) * 1.0).tolist(), axis, (od - 2 * wall) * s / 2.0, ln * s + 2.0)
    wid = cut(outer, [inner])
    summary = work.kcall("shape_summary", {"id": wid})["summary"]
    body = work.new_body(d, wid, summary, name, {"op": "pipe_straight", "od": od, "wall": wall})
    return d.add_entity(body), summary
