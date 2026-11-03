import math

import numpy as np

from app.pipe.limits import PipeError

EPS = 1e-9
MAX_TURN = math.radians(179.0)
MIN_TURN = 1e-4


def unit(v):
    n = float(np.linalg.norm(v))
    if n < EPS:
        raise PipeError("Two consecutive route points coincide.")
    return v / n


def clamp_angle(c: float) -> float:
    return math.acos(max(-1.0, min(1.0, c)))


def bend_length(radius: float, theta: float, table, notes: list) -> float:
    if not table:
        return radius * theta
    rows = sorted(((float(r["clr"]), float(r["developed90"])) for r in table), key=lambda r: r[0])
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    if radius < xs[0] - EPS or radius > xs[-1] + EPS:
        if "table_extrapolated" not in notes:
            notes.append("table_extrapolated")
    if len(rows) == 1:
        d90 = ys[0] * radius / xs[0]
    else:
        d90 = float(np.interp(radius, xs, ys))
        if radius < xs[0]:
            d90 = ys[0] + (ys[1] - ys[0]) * (radius - xs[0]) / (xs[1] - xs[0])
        if radius > xs[-1]:
            d90 = ys[-1] + (ys[-1] - ys[-2]) * (radius - xs[-1]) / (xs[-1] - xs[-2])
    return d90 * theta / (math.pi / 2.0)


def corners(points, radii, default_r):
    pts = [np.array([float(c) for c in p], dtype=float) for p in points]
    if len(pts) < 2:
        raise PipeError("A route needs at least two points.")
    dirs = []
    lens = []
    for a, b in zip(pts[:-1], pts[1:]):
        d = b - a
        n = float(np.linalg.norm(d))
        if n < EPS:
            raise PipeError("Two consecutive route points coincide.")
        dirs.append(d / n)
        lens.append(n)
    out = {}
    for i in range(1, len(pts) - 1):
        theta = clamp_angle(float(np.dot(dirs[i - 1], dirs[i])))
        if theta < MIN_TURN:
            continue
        if theta > MAX_TURN:
            raise PipeError("The route turns back on itself at point %d." % (i + 1))
        r = radii[i - 1] if radii and i - 1 < len(radii) and radii[i - 1] not in (None, 0) else default_r
        out[i] = {"vertex": i, "theta": theta, "radius": float(r), "point": pts[i], "u_in": dirs[i - 1], "u_out": dirs[i]}
    return pts, dirs, lens, out


def merge_collinear(points, radii):
    pts = [np.array([float(c) for c in p], dtype=float) for p in points]
    rad = list(radii or [])
    while len(rad) < max(len(pts) - 2, 0):
        rad.append(None)
    keep = [0]
    out_r = []
    for i in range(1, len(pts) - 1):
        a = pts[i] - pts[keep[-1]]
        b = pts[i + 1] - pts[i]
        if float(np.linalg.norm(a)) < EPS or float(np.linalg.norm(b)) < EPS:
            raise PipeError("Two consecutive route points coincide.")
        if clamp_angle(float(np.dot(a, b)) / float(np.linalg.norm(a) * np.linalg.norm(b))) < MIN_TURN:
            continue
        keep.append(i)
        out_r.append(rad[i - 1])
    keep.append(len(pts) - 1)
    return [pts[i] for i in keep], out_r


def turn_frame(u_in, u_out):
    d = u_out - float(np.dot(u_out, u_in)) * u_in
    d = unit(d)
    n = np.cross(u_in, u_out)
    return d, unit(n)


def signed_angle(a, b, axis) -> float:
    return math.atan2(float(np.dot(np.cross(a, b), axis)), float(np.dot(a, b)))


def solve_tube(points, radii, default_r, spec: dict, ends: dict) -> dict:
    points, radii = merge_collinear(points, radii)
    pts, dirs, lens, bends = corners(points, radii, default_r)
    od = float(spec["od"])
    min_r = float(spec.get("min_clr_factor", 0.0)) * od
    min_s = float(spec.get("min_straight_factor", 0.0)) * od
    table = spec.get("bend_table") or []
    springback = float(spec.get("springback", 0.0))
    notes = []
    violations = []
    flange_a = float(ends.get("a_len", 0.0))
    flange_b = float(ends.get("b_len", 0.0))
    nseg = len(dirs)
    t_at = [0.0] * (len(pts))
    for i, b in bends.items():
        b["setback"] = b["radius"] * math.tan(b["theta"] / 2.0)
        t_at[i] = b["setback"]
        if min_r and b["radius"] < min_r - EPS:
            violations.append({"code": "bend_radius", "where": "bend at point %d" % (i + 1), "severity": "warning", "message": "Bend radius %.4g is below the minimum %.4g for this tube." % (b["radius"], min_r)})
    straights = []
    for i in range(nseg):
        ts = t_at[i]
        te = t_at[i + 1]
        s0 = pts[i] + dirs[i] * ts
        s1 = pts[i + 1] - dirs[i] * te
        length = lens[i] - ts - te
        if length < -1e-7:
            violations.append({"code": "no_room", "where": "segment %d" % (i + 1), "severity": "error", "message": "Segment %d is %.4g long but its two bends need %.4g; reduce the radius or lengthen the segment." % (i + 1, lens[i], ts + te)})
        straights.append({"seg": i, "start": s0, "end": s1, "length": length})
    first_end = straights[0]
    if flange_a:
        first_end["length"] -= flange_a
    if flange_b:
        straights[-1]["length"] -= flange_b
    for k, s in enumerate(straights):
        if s["length"] < -1e-7 and not any(v["code"] == "no_room" and v["where"] == "segment %d" % (k + 1) for v in violations):
            violations.append({"code": "no_room", "where": "segment %d" % (k + 1), "severity": "error", "message": "The end fitting is longer than segment %d allows." % (k + 1)})
        if min_s and 0 <= s["length"] < min_s - EPS and len(bends) > 0:
            violations.append({"code": "straight", "where": "segment %d" % (k + 1), "severity": "warning", "message": "The straight of %.4g between bends is below the minimum %.4g (grip length)." % (s["length"], min_s)})
    arcs = []
    rows = []
    order = sorted(bends)
    prev_normal = None
    lead = straights[0]["length"]
    cursor = 0.0
    for idx, i in enumerate(order):
        b = bends[i]
        d, n = turn_frame(b["u_in"], b["u_out"])
        tin = b["point"] - b["u_in"] * b["setback"]
        tout = b["point"] + b["u_out"] * b["setback"]
        centre = tin + d * b["radius"]
        mid_dir = unit(b["point"] - centre)
        mid = centre + mid_dir * b["radius"]
        arc_len = bend_length(b["radius"], b["theta"], table, notes)
        arcs.append({"vertex": i, "start": tin, "end": tout, "mid": mid, "centre": centre, "radius": b["radius"], "angle": b["theta"], "length": arc_len})
        before = straights[i - 1]
        lrow = before["length"]
        if prev_normal is None:
            rot = 0.0
        else:
            rot = math.degrees(signed_angle(prev_normal, n, b["u_in"])) % 360.0
        prev_normal = n
        rows.append({"bend": idx + 1, "vertex": i + 1, "length": lrow, "rotation": rot, "angle": math.degrees(b["theta"]), "machine_angle": math.degrees(b["theta"]) + springback, "radius": b["radius"], "setback": b["setback"], "arc": arc_len, "mark": cursor + lrow})
        cursor += lrow + arc_len
    after = straights[-1]["length"]
    total = sum(max(s["length"], 0.0) for s in straights) + sum(a["length"] for a in arcs)
    pieces = [{"n": 1, "kind": "tube", "od": od, "wall": float(spec["wall"]), "length": total, "bends": len(arcs), "from": pts[0], "to": pts[-1]}]
    return {"style": "tube", "points": pts, "straights": straights, "arcs": arcs, "bender": rows, "tail": after if order else 0.0, "lead": lead, "total": total, "pieces": pieces, "fittings": [], "violations": violations, "notes": notes}


def elbow_c(spec: dict, theta: float, radius: float | None = None) -> tuple:
    od = float(spec["od"])
    r = float(radius) if radius else float(spec.get("elbow_clr_factor", 1.5)) * od
    return r, r * math.tan(theta / 2.0)


def solve_pipe(points, spec: dict, ends: dict, taps, reducers, clr=None) -> dict:
    pts, dirs, lens, bends = corners(points, None, 0.0)
    od0 = float(spec["od"])
    wall = float(spec["wall"])
    violations = []
    fittings = []
    c_at = [0.0] * len(pts)
    for i, b in bends.items():
        r, c = elbow_c(spec, b["theta"], clr)
        b["radius"] = r
        c_at[i] = c
        fittings.append({"kind": "elbow", "vertex": i, "point": pts[i], "angle": math.degrees(b["theta"]), "radius": r, "c": c, "od": od0, "wall": wall, "u_in": b["u_in"], "u_out": b["u_out"]})
    end_a = ends.get("a") or "plain"
    end_b = ends.get("b") or "plain"
    nseg = len(dirs)
    cons_a = float(ends.get("a_len", 0.0))
    cons_b = float(ends.get("b_len", 0.0))
    if end_a == "flange":
        fittings.append({"kind": "flange", "vertex": 0, "point": pts[0], "axis": dirs[0], "thickness": cons_a, "od": od0, "wall": wall})
    if end_b == "flange":
        fittings.append({"kind": "flange", "vertex": len(pts) - 1, "point": pts[-1], "axis": -dirs[-1], "thickness": cons_b, "od": od0, "wall": wall})
    events = {i: [] for i in range(nseg)}
    for k, t in enumerate(taps or []):
        s = int(t["segment"])
        if not 0 <= s < nseg:
            raise PipeError("Tap %d names segment %d, which does not exist." % (k + 1, s + 1))
        c = float(t.get("c") or float(spec.get("tee_c_factor", 1.5)) * od0)
        events[s].append({"kind": "tee", "d": float(t["distance"]), "lo": float(t["distance"]) - c, "hi": float(t["distance"]) + c, "c": c, "branch": t.get("branch"), "tap": k})
    for k, r in enumerate(reducers or []):
        s = int(r["segment"])
        if not 0 <= s < nseg:
            raise PipeError("Reducer %d names segment %d, which does not exist." % (k + 1, s + 1))
        ln = float(r.get("length") or 2.0 * od0)
        events[s].append({"kind": "reducer", "d": float(r["distance"]), "lo": float(r["distance"]), "hi": float(r["distance"]) + ln, "length": ln, "od_to": float(r["od_to"]), "wall_to": float(r.get("wall_to") or wall), "red": k})
    pieces = []
    n = 0
    od_now = od0
    wall_now = wall
    for s in range(nseg):
        a_off = c_at[s] if s > 0 else (cons_a if end_a == "flange" else 0.0)
        b_off = c_at[s + 1] if s < nseg - 1 else (cons_b if end_b == "flange" else 0.0)
        lo = a_off
        hi = lens[s] - b_off
        if hi - lo < -1e-7:
            violations.append({"code": "no_room", "where": "segment %d" % (s + 1), "severity": "error", "message": "Segment %d is %.4g long but its end fittings need %.4g." % (s + 1, lens[s], a_off + b_off)})
        evs = sorted(events[s], key=lambda e: e["lo"])
        cur = lo
        for e in evs:
            if e["lo"] < cur - 1e-7 or e["hi"] > hi + 1e-7:
                violations.append({"code": "no_room", "where": "segment %d at %.4g" % (s + 1, e["d"]), "severity": "error", "message": "A %s at %.4g along segment %d overlaps another fitting or leaves the segment." % (e["kind"], e["d"], s + 1)})
            if e["lo"] - cur > 1e-7:
                n += 1
                pieces.append({"n": n, "kind": "pipe", "od": od_now, "wall": wall_now, "length": e["lo"] - cur, "bends": 0, "seg": s, "from": pts[s] + dirs[s] * cur, "to": pts[s] + dirs[s] * e["lo"]})
            elif e["lo"] - cur < -1e-7:
                pass
            cur = max(cur, e["hi"])
            at = pts[s] + dirs[s] * e["d"]
            if e["kind"] == "tee":
                fittings.append({"kind": "tee", "segment": s, "point": at, "axis": dirs[s], "c": e["c"], "od": od_now, "wall": wall_now, "branch": e.get("branch"), "tap": e["tap"]})
            else:
                fittings.append({"kind": "reducer", "segment": s, "point": at, "axis": dirs[s], "length": e["length"], "od": od_now, "od_to": e["od_to"], "wall": wall_now, "wall_to": e["wall_to"], "red": e["red"]})
                od_now = e["od_to"]
                wall_now = e["wall_to"]
        if hi - cur > 1e-7:
            n += 1
            pieces.append({"n": n, "kind": "pipe", "od": od_now, "wall": wall_now, "length": hi - cur, "bends": 0, "seg": s, "from": pts[s] + dirs[s] * cur, "to": pts[s] + dirs[s] * hi})
    total = sum(p["length"] for p in pieces)
    return {"style": "pipe", "points": pts, "straights": [], "arcs": [], "bender": [], "tail": 0.0, "lead": 0.0, "total": total, "pieces": pieces, "fittings": fittings, "violations": violations, "notes": []}
