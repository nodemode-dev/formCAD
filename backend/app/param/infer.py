import math

from app.doc import curvepath, nurbs
from app.param import adapt, ops
from app.param import store as S

MAX_OBJECTS = 200
MAX_CANDIDATES = 2000
PRIORITY = ("coincident", "midpoint", "concentric", "tangent", "horizontal", "vertical", "collinear", "perpendicular", "parallel", "equal")
INFERABLE = ("coincident", "midpoint", "horizontal", "vertical", "perpendicular", "tangent")


def end_points(ent) -> list:
    k = ent.kind
    if k == "line":
        return [("start", ent.start), ("end", ent.end)]
    if k == "arc":
        c, r = ent.center, ent.radius
        return [("start", [c[0] + r * math.cos(ent.start_angle), c[1] + r * math.sin(ent.start_angle)]), ("end", [c[0] + r * math.cos(ent.end_angle), c[1] + r * math.sin(ent.end_angle)])]
    if k == "point":
        return [("whole", ent.position)]
    if k == "spline" and not ent.closed:
        c = curvepath.spline_curve(ent)
        return [] if c is None else [("start", nurbs.point_at(c, c.domain()[0])), ("end", nurbs.point_at(c, c.domain()[1]))]
    if k == "lwpolyline":
        n = len(ent.vertices)
        return [("v%d" % i, v["p"]) for i, v in enumerate(ent.vertices)] if n <= 64 else []
    return []


def mid_of(ent):
    if ent.kind == "line":
        return [(ent.start[0] + ent.end[0]) / 2.0, (ent.start[1] + ent.end[1]) / 2.0]
    if ent.kind == "arc":
        a = ent.start_angle + ((ent.end_angle - ent.start_angle) % math.tau) / 2.0
        return [ent.center[0] + ent.radius * math.cos(a), ent.center[1] + ent.radius * math.sin(a)]
    return None


def centers(ent):
    if ent.kind in ("circle", "arc", "ellipse"):
        return ent.center
    return None


def dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def curve_gap(ent, p) -> float:
    if ent.kind == "line":
        dx, dy = ent.end[0] - ent.start[0], ent.end[1] - ent.start[1]
        length = math.hypot(dx, dy)
        if length < 1e-12:
            return float("inf")
        t = ((p[0] - ent.start[0]) * dx + (p[1] - ent.start[1]) * dy) / (length * length)
        if t < -1e-9 or t > 1 + 1e-9:
            return float("inf")
        return abs(dx * (p[1] - ent.start[1]) - dy * (p[0] - ent.start[0])) / length
    if ent.kind in ("circle", "arc"):
        gap = abs(dist(ent.center, p) - ent.radius)
        if ent.kind == "arc":
            a = math.atan2(p[1] - ent.center[1], p[0] - ent.center[0])
            sweep = (ent.end_angle - ent.start_angle) % math.tau
            if (a - ent.start_angle) % math.tau > sweep + 1e-9:
                return float("inf")
        return gap
    return float("inf")


def line_angle(ent) -> float:
    return math.atan2(ent.end[1] - ent.start[1], ent.end[0] - ent.start[0])


def angle_gap(a: float, b: float) -> float:
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def usable(d, handles) -> list:
    out = []
    for h in handles:
        e = d.get(h)
        if e is not None and adapt.constrainable(e) and e.kind != "lwpolyline":
            out.append(e)
    return out


def existing_keys(d) -> set:
    keys = set()
    for r in S.constraints(d):
        keys.add((r["kind"], tuple(sorted((int(a), str(b)) for a, b in r["refs"]))))
    return keys


def candidates(d, ents, dist_tol, ang_tol, types):
    out = []
    seen = existing_keys(d)

    def push(kind, refs):
        if kind not in types or len(out) >= MAX_CANDIDATES:
            return
        key = (kind, tuple(sorted((int(a), str(b)) for a, b in refs)))
        if key in seen:
            return
        seen.add(key)
        out.append((kind, refs))

    for i, a in enumerate(ents):
        for b in ents[i + 1:]:
            for pa, p in end_points(a):
                for pb, q in end_points(b):
                    if dist(p, q) <= dist_tol:
                        push("coincident", [[a.handle, pa], [b.handle, pb]])
            for pa, p in end_points(a):
                if b.kind in ("line", "circle", "arc") and curve_gap(b, p) <= dist_tol and not any(dist(p, q) <= dist_tol for _n, q in end_points(b)):
                    m = mid_of(b)
                    push("midpoint" if m is not None and "midpoint" in types and dist(p, m) <= dist_tol else "coincident", [[a.handle, pa], [b.handle, "whole"]])
            for pb, q in end_points(b):
                if a.kind in ("line", "circle", "arc") and curve_gap(a, q) <= dist_tol and not any(dist(q, p) <= dist_tol for _n, p in end_points(a)):
                    m = mid_of(a)
                    push("midpoint" if m is not None and "midpoint" in types and dist(q, m) <= dist_tol else "coincident", [[b.handle, pb], [a.handle, "whole"]])
    for i, a in enumerate(ents):
        ca = centers(a)
        for b in ents[i + 1:]:
            cb = centers(b)
            if ca is not None and cb is not None and a.kind != "ellipse" and b.kind != "ellipse" and dist(ca, cb) <= dist_tol:
                push("concentric", [[a.handle, "whole"], [b.handle, "whole"]])
    for i, a in enumerate(ents):
        for b in ents[i + 1:]:
            ln, cv = (a, b) if a.kind == "line" else (b, a)
            if ln.kind == "line" and cv.kind in ("circle", "arc"):
                dx, dy = ln.end[0] - ln.start[0], ln.end[1] - ln.start[1]
                length = math.hypot(dx, dy)
                if length > 1e-12:
                    off = abs(dx * (cv.center[1] - ln.start[1]) - dy * (cv.center[0] - ln.start[0])) / length
                    t = ((cv.center[0] - ln.start[0]) * dx + (cv.center[1] - ln.start[1]) * dy) / (length * length)
                    if abs(off - cv.radius) <= dist_tol and -dist_tol / length <= t <= 1 + dist_tol / length:
                        push("tangent", [[ln.handle, "whole"], [cv.handle, "whole"]])
            elif a.kind in ("circle", "arc") and b.kind in ("circle", "arc"):
                dd = dist(a.center, b.center)
                if dd > dist_tol and (abs(dd - (a.radius + b.radius)) <= dist_tol or abs(dd - abs(a.radius - b.radius)) <= dist_tol):
                    push("tangent", [[a.handle, "whole"], [b.handle, "whole"]])
    for a in ents:
        if a.kind == "line" and dist(a.start, a.end) > 1e-12:
            ang = line_angle(a)
            if angle_gap(ang, 0.0) <= ang_tol:
                push("horizontal", [[a.handle, "whole"]])
            elif angle_gap(ang, math.pi / 2) <= ang_tol:
                push("vertical", [[a.handle, "whole"]])
    lines = [e for e in ents if e.kind == "line" and dist(e.start, e.end) > 1e-12]
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            gap = angle_gap(line_angle(a), line_angle(b))
            if gap <= ang_tol:
                far = max(curve_line_gap(a, b.start), curve_line_gap(a, b.end))
                if far <= dist_tol:
                    push("collinear", [[a.handle, "whole"], [b.handle, "whole"]])
                else:
                    push("parallel", [[a.handle, "whole"], [b.handle, "whole"]])
            elif abs(gap - math.pi / 2) <= ang_tol:
                push("perpendicular", [[a.handle, "whole"], [b.handle, "whole"]])
    for i, a in enumerate(ents):
        for b in ents[i + 1:]:
            if a.kind == "line" and b.kind == "line" and abs(dist(a.start, a.end) - dist(b.start, b.end)) <= dist_tol:
                push("equal", [[a.handle, "whole"], [b.handle, "whole"]])
            elif a.kind in ("circle", "arc") and b.kind in ("circle", "arc") and abs(a.radius - b.radius) <= dist_tol:
                push("equal", [[a.handle, "whole"], [b.handle, "whole"]])
    rank = {k: i for i, k in enumerate(PRIORITY)}
    out.sort(key=lambda c: rank[c[0]])
    return out


def curve_line_gap(ln, p) -> float:
    dx, dy = ln.end[0] - ln.start[0], ln.end[1] - ln.start[1]
    length = math.hypot(dx, dy)
    return abs(dx * (p[1] - ln.start[1]) - dy * (p[0] - ln.start[0])) / length


def autoconstrain(d, handles, dist_tol=None, ang_tol=None, types=None) -> dict:
    cfg = S.settings(d)
    dist_tol = cfg["distance_tol"] if dist_tol is None else float(dist_tol)
    ang_tol = math.radians(cfg["angle_tol"] if ang_tol is None else float(ang_tol))
    types = [t for t in (types or cfg["auto_types"]) if t in PRIORITY]
    ents = usable(d, handles)
    skipped_kinds = len(set(handles)) - len(ents)
    if len(ents) > MAX_OBJECTS:
        raise S.ParamError("AUTOCONSTRAIN handles at most %d objects at a time." % MAX_OBJECTS)
    applied = []
    skipped = 0
    touched = set()
    for kind, refs in candidates(d, ents, dist_tol, ang_tol, types):
        try:
            res = ops.add_constraint(d, kind, refs)
        except S.ParamError:
            skipped += 1
            continue
        applied.append(res["id"])
        touched.update(h for h, _ in refs)
    return {"applied": len(applied), "ids": applied, "objects": len(touched), "skipped": skipped, "ignored": skipped_kinds}


def fresh_candidates(d, new_handles):
    ents = usable(d, new_handles)
    if not ents:
        return []
    others = [e for e in d.entities(ents[0].owner) if e.handle not in new_handles and adapt.constrainable(e) and e.kind != "lwpolyline"]
    scale = max([1.0] + [abs(v) for e in ents for _n, p in end_points(e) for v in p[:2]])
    tol = 1e-9 * scale
    pool = ents + others
    found = candidates(d, pool[:MAX_OBJECTS], tol, 1e-9, list(INFERABLE))
    newset = set(new_handles)
    return [(k, r) for k, r in found if any(h in newset for h, _ in r)]


def infer_new(d, new_handles) -> int:
    n = 0
    for kind, refs in fresh_candidates(d, new_handles):
        try:
            ops.add_constraint(d, kind, refs)
            n += 1
        except S.ParamError:
            continue
    return n
