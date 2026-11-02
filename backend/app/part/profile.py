import json
import math

from app.doc import curves2d as C
from app.doc import planar as P
from app.part.registry import PartError
from app.param import store as S
from app.param import units as U

MAX_ENTITIES = 20000


def role(handle, seg=None) -> str:
    return "h%d" % handle if seg is None else "h%d.s%d" % (handle, seg)


def arc_ends(e):
    a = [e.center[0] + e.radius * math.cos(e.start_angle), e.center[1] + e.radius * math.sin(e.start_angle)]
    b = [e.center[0] + e.radius * math.cos(e.end_angle), e.center[1] + e.radius * math.sin(e.end_angle)]
    sweep = (e.end_angle - e.start_angle) % (2.0 * math.pi)
    if sweep == 0.0:
        sweep = 2.0 * math.pi
    return a, b, math.tan(sweep / 4.0)


def poly_segments(e, handle, scale):
    verts = e.vertices
    n = len(verts)
    count = n if e.closed else n - 1
    out = []
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        pa = [float(a["p"][0]) * scale, float(a["p"][1]) * scale]
        pb = [float(b["p"][0]) * scale, float(b["p"][1]) * scale]
        if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= 1e-9:
            continue
        out.append({"t": "line" if not float(a.get("bulge", 0.0) or 0.0) else "arc", "a": pa, "b": pb, "bulge": float(a.get("bulge", 0.0) or 0.0), "role": role(handle, i)})
    return out


def loop_ring(segs):
    verts = [{"p": s["a"], "bulge": s.get("bulge", 0.0)} for s in segs]
    return P.flatten_loop(verts)


def chain(segments, tol):
    def key(pt):
        return (round(pt[0] / tol), round(pt[1] / tol))

    nodes = {}
    for i, s in enumerate(segments):
        for end in ("a", "b"):
            nodes.setdefault(key(s[end]), []).append((i, end))
    for k, lst in nodes.items():
        if len(lst) > 2:
            raise PartError("The sketch branches at (%.4g, %.4g); a profile needs simple loops." % (k[0] * tol, k[1] * tol))
    used = [False] * len(segments)
    closed, opened = [], []

    def oriented(s, forward):
        if forward:
            return dict(s)
        return {"t": s["t"], "a": s["b"], "b": s["a"], "bulge": -float(s.get("bulge", 0.0) or 0.0), "role": s["role"]}

    def other(k, i):
        for j, end in nodes.get(k, []):
            if j != i and not used[j]:
                return j, end
        return None

    for i0 in range(len(segments)):
        if used[i0]:
            continue
        used[i0] = True
        run = [oriented(segments[i0], True)]
        while True:
            nxt = other(key(run[-1]["b"]), -1)
            if nxt is None:
                break
            j, end = nxt
            used[j] = True
            run.append(oriented(segments[j], end == "a"))
            if key(run[-1]["b"]) == key(run[0]["a"]):
                break
        if key(run[-1]["b"]) != key(run[0]["a"]):
            while True:
                nxt = other(key(run[0]["a"]), -1)
                if nxt is None:
                    break
                j, end = nxt
                used[j] = True
                run.insert(0, oriented(segments[j], end == "b"))
        if key(run[-1]["b"]) == key(run[0]["a"]) and len(run) >= 2:
            closed.append({"closed": True, "segs": run})
        elif key(run[-1]["b"]) == key(run[0]["a"]) and len(run) == 1 and run[0]["t"] == "arc":
            closed.append({"closed": True, "segs": run})
        else:
            opened.append({"closed": False, "segs": run})
    return closed, opened


def nest(loops):
    rings = [loop_ring(l["segs"]) if l["segs"][0]["t"] != "circle" else None for l in loops]
    reps = []
    for l, r in zip(loops, rings):
        if l["segs"][0]["t"] == "circle":
            c = l["segs"][0]["c"]
            reps.append((c[0] + l["segs"][0]["r"], c[1]))
            continue
        a, b = r[0], r[1 % len(r)]
        reps.append(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))

    def inside(i, j):
        if loops[j]["segs"][0]["t"] == "circle":
            c = loops[j]["segs"][0]
            pt = reps[i]
            return math.hypot(pt[0] - c["c"][0], pt[1] - c["c"][1]) < c["r"]
        return P.point_in_ring(reps[i][0], reps[i][1], rings[j])

    def area(l):
        s = l["segs"][0]
        if s["t"] == "circle":
            return math.pi * s["r"] ** 2
        return abs(P.loop_area([{"p": x["a"], "bulge": x.get("bulge", 0.0)} for x in l["segs"]]))

    n = len(loops)
    depth = [0] * n
    parent = [None] * n
    for i in range(n):
        containers = [j for j in range(n) if j != i and inside(i, j)]
        depth[i] = len(containers)
        if containers:
            parent[i] = min(containers, key=lambda j: area(loops[j]))
    regions = {}
    order = []
    for i in range(n):
        if depth[i] % 2 == 0:
            regions[i] = {"outer": loops[i], "holes": []}
            order.append(i)
    for i in range(n):
        if depth[i] % 2 == 1 and parent[i] in regions:
            regions[parent[i]]["holes"].append(loops[i])
    return [regions[i] for i in order]


def build(d, sketch_name, frame_mm, exclude=()) -> dict:
    rec = S.get_sketch(d, sketch_name)
    if rec is None:
        raise PartError("The sketch %s does not exist." % sketch_name)
    scale = U.mm_per_unit(d)
    if len(rec["entities"]) > MAX_ENTITIES:
        raise PartError("The sketch is too large.")
    skip = {int(h) for h in rec.get("construction", [])} | {int(h) for h in exclude}
    segments, closed, points, axis_lines = [], [], [], {}
    for h in rec["entities"]:
        e = d.get(int(h))
        if e is None:
            continue
        if e.kind == "line" and int(h) in skip:
            axis_lines[int(h)] = [[e.start[0] * scale, e.start[1] * scale], [e.end[0] * scale, e.end[1] * scale]]
            continue
        if int(h) in skip:
            continue
        k = e.kind
        if k == "point":
            points.append({"role": role(h), "u": e.position[0] * scale, "v": e.position[1] * scale})
        elif k == "line":
            segments.append({"t": "line", "a": [e.start[0] * scale, e.start[1] * scale], "b": [e.end[0] * scale, e.end[1] * scale], "bulge": 0.0, "role": role(h)})
        elif k == "arc":
            a, b, bulge = arc_ends(e)
            segments.append({"t": "arc", "a": [a[0] * scale, a[1] * scale], "b": [b[0] * scale, b[1] * scale], "bulge": bulge, "role": role(h)})
        elif k == "circle":
            closed.append({"closed": True, "segs": [{"t": "circle", "c": [e.center[0] * scale, e.center[1] * scale], "r": e.radius * scale, "role": role(h)}]})
        elif k == "lwpolyline":
            segs = poly_segments(e, int(h), scale)
            if e.closed and len(segs) >= 2:
                closed.append({"closed": True, "segs": segs})
            else:
                segments.extend(segs)
        elif k in ("ellipse", "spline"):
            cl = C.closed_loop_of(e)
            if cl is None:
                raise PartError("An open %s cannot be part of a profile; close it or make it construction geometry." % k)
            verts = [{"p": [v["p"][0] * scale, v["p"][1] * scale], "bulge": 0.0} for v in cl]
            segs = []
            for i in range(len(verts)):
                segs.append({"t": "line", "a": verts[i]["p"], "b": verts[(i + 1) % len(verts)]["p"], "bulge": 0.0, "role": role(h, i)})
            closed.append({"closed": True, "segs": segs})
    tol = 1e-6 * max(1.0, scale)
    more_closed, opened = chain(segments, tol) if segments else ([], [])
    closed.extend(more_closed)
    return {"frame": frame_mm, "regions": nest(closed) if closed else [], "open": opened, "points": points, "axis_lines": {str(k): v for k, v in axis_lines.items()}}


def digest(profile: dict) -> str:
    return json.dumps(profile, sort_keys=True, separators=(",", ":"))
