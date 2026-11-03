import math

import pyclipper as pc

from app.cutting import shapes as S
from app.cutting.shapes import CutError

MAX_LOOPS_PLAN = 6000
CUT_TOL = 0.01


def _unit(vx, vy):
    d = math.hypot(vx, vy)
    if d < 1e-12:
        return 1.0, 0.0
    return vx / d, vy / d


def material_regions(part, e):
    outer = S.offset([part["loops"][0]["pts"]], e) if e else [part["loops"][0]["pts"]]
    holes = []
    for lp in part["loops"][1:]:
        h = S.offset([S.orient(lp["pts"], True)], -e) if e else [S.orient(lp["pts"], True)]
        holes.extend(h)
    return [S.to_ints(p) for p in outer], [S.to_ints(p) for p in holes]


def in_material(pt, regions) -> bool:
    ip = (int(round(pt[0] * S.SCALE)), int(round(pt[1] * S.SCALE)))
    for outer, holes in regions:
        if any(pc.PointInPolygon(ip, p) == 1 for p in outer) and not any(pc.PointInPolygon(ip, h) != 0 for h in holes):
            return True
    return False


def circle_elems(c, r, start, ccw):
    cx, cy = c
    p0 = (cx + r * math.cos(start), cy + r * math.sin(start))
    p1 = (cx - r * math.cos(start), cy - r * math.sin(start))
    d = "ccw" if ccw else "cw"
    return [("A", p0, p1, (cx, cy), d), ("A", p1, p0, (cx, cy), d)]


def poly_elems(pts):
    n = len(pts)
    return [("L", pts[i], pts[(i + 1) % n]) for i in range(n)]


def elem_len(e):
    if e[0] == "L":
        return math.hypot(e[2][0] - e[1][0], e[2][1] - e[1][1])
    c = e[3]
    r = math.hypot(e[1][0] - c[0], e[1][1] - c[1])
    a0 = math.atan2(e[1][1] - c[1], e[1][0] - c[0])
    a1 = math.atan2(e[2][1] - c[1], e[2][0] - c[0])
    sw = (a1 - a0) % (2 * math.pi) if e[4] == "ccw" else (a0 - a1) % (2 * math.pi)
    if sw < 1e-9:
        sw = 2 * math.pi
    return r * sw


def split_elem(e, dist):
    L = elem_len(e)
    if e[0] == "L":
        t = dist / L
        m = (e[1][0] + (e[2][0] - e[1][0]) * t, e[1][1] + (e[2][1] - e[1][1]) * t)
        return ("L", e[1], m), ("L", m, e[2])
    c = e[3]
    r = math.hypot(e[1][0] - c[0], e[1][1] - c[1])
    a0 = math.atan2(e[1][1] - c[1], e[1][0] - c[0])
    ang = dist / r * (1 if e[4] == "ccw" else -1)
    m = (c[0] + r * math.cos(a0 + ang), c[1] + r * math.sin(a0 + ang))
    return ("A", e[1], m, c, e[4]), ("A", m, e[2], c, e[4])


def tangent_at_start(e):
    if e[0] == "L":
        return _unit(e[2][0] - e[1][0], e[2][1] - e[1][1])
    c = e[3]
    rx, ry = e[1][0] - c[0], e[1][1] - c[1]
    return _unit(-ry, rx) if e[4] == "ccw" else _unit(ry, -rx)


def rotate_start(elems, dist):
    acc = 0.0
    for i, e in enumerate(elems):
        L = elem_len(e)
        if acc + L >= dist - 1e-9:
            off = dist - acc
            if off < 1e-6:
                return elems[i:] + elems[:i]
            if L - off < 1e-6:
                j = (i + 1) % len(elems)
                return elems[j:] + elems[:j]
            a, b = split_elem(e, off)
            return [b] + elems[i + 1:] + elems[:i] + [a]
        acc += L
    return elems


def trim_elems(elems, length):
    out = []
    acc = 0.0
    for e in elems:
        L = elem_len(e)
        if acc + L <= length + 1e-9:
            out.append(e)
            acc += L
        else:
            a, _ = split_elem(e, length - acc)
            out.append(a)
            break
    return out


def total_len(elems):
    return sum(elem_len(e) for e in elems)


def cut_loop_path(loop, outer, kerf, good_side):
    half = kerf / 2.0
    if loop.get("circle"):
        c = loop["circle"]["c"]
        r = loop["circle"]["r"] + (half if outer else -half)
        if r <= 1e-6:
            return None
        ccw = (good_side == "left") if outer else (good_side == "right")
        if good_side == "none":
            ccw = not outer
        return {"kind": "circle", "c": tuple(c), "r": r, "ccw": ccw, "outer": outer}
    pts = loop["pts"]
    if half > 0:
        res = S.offset([S.orient(pts, True)], half if outer else -half, True, CUT_TOL)
        if not res:
            return None
        pts = max(res, key=lambda p: abs(S.area(p)))
    else:
        pts = S.orient(pts, True)
    pts = S.clean(pts, 0.0005) or pts
    ccw = (good_side == "left") if outer else (good_side == "right")
    if good_side == "none":
        ccw = not outer
    pts = S.orient(pts, ccw)
    return {"kind": "poly", "pts": pts, "ccw": ccw, "outer": outer}


def candidates(cp):
    if cp["kind"] == "circle":
        return [(math.pi * 1.5, "angle"), (math.pi, "angle"), (0.0, "angle"), (math.pi * 0.5, "angle")]
    pts = cp["pts"]
    n = len(pts)
    edges = []
    acc = 0.0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        edges.append((L, acc))
        acc += L
    order = sorted(range(n), key=lambda i: -edges[i][0])[:8]
    return [(edges[i][1] + edges[i][0] / 2.0, "dist") for i in order]


def lead_geometry(P, T, N, lead, kind, outgoing):
    L = lead["length"]
    if L <= 0 or kind == "none":
        return None
    if kind == "arc":
        C = (P[0] + N[0] * L, P[1] + N[1] * L)
        if not outgoing:
            A = (C[0] - T[0] * L, C[1] - T[1] * L)
            e1 = (-N[0], -N[1])
            cross = e1[0] * T[1] - e1[1] * T[0]
            return [("A", A, P, C, "ccw" if cross > 0 else "cw")], A
        B = (C[0] + T[0] * L, C[1] + T[1] * L)
        e1 = (-N[0], -N[1])
        cross = e1[0] * T[1] - e1[1] * T[0]
        return [("A", P, B, C, "ccw" if cross > 0 else "cw")], B
    ang = math.radians(lead.get("angle", 45.0))
    d = (N[0] * math.sin(ang) - T[0] * math.cos(ang), N[1] * math.sin(ang) - T[1] * math.cos(ang)) if not outgoing else (N[0] * math.sin(ang) + T[0] * math.cos(ang), N[1] * math.sin(ang) + T[1] * math.cos(ang))
    A = (P[0] + d[0] * L, P[1] + d[1] * L)
    return [("L", A, P)] if not outgoing else [("L", P, A)], A


def sample_elems(elems, step=0.5):
    pts = []
    for e in elems:
        L = elem_len(e)
        n = max(1, int(L / step))
        for i in range(n + 1):
            t = i / n
            if e[0] == "L":
                pts.append((e[1][0] + (e[2][0] - e[1][0]) * t, e[1][1] + (e[2][1] - e[1][1]) * t))
            else:
                c = e[3]
                r = math.hypot(e[1][0] - c[0], e[1][1] - c[1])
                a0 = math.atan2(e[1][1] - c[1], e[1][0] - c[0])
                a1 = math.atan2(e[2][1] - c[1], e[2][0] - c[0])
                sw = (a1 - a0) % (2 * math.pi) if e[4] == "ccw" else -((a0 - a1) % (2 * math.pi))
                pts.append((c[0] + r * math.cos(a0 + sw * t), c[1] + r * math.sin(a0 + sw * t)))
    return pts


def plan_contour(cp, kerf, process, regions, bounds, own_regions, margin_check):
    lead_in = process["lead_in"]
    lead_out = process["lead_out"]
    outer = cp["outer"]
    tries = []
    for pos, how in candidates(cp):
        tries.append(pos)
    scales = (1.0, 0.6, 0.35)
    for scale in scales:
        for pos in tries:
            if cp["kind"] == "circle":
                elems = circle_elems(cp["c"], cp["r"], pos, cp["ccw"])
            else:
                elems = rotate_start(poly_elems(cp["pts"]), pos)
            P = elems[0][1]
            T = tangent_at_start(elems[0])
            right = (T[1], -T[0])
            ccw = cp["ccw"]
            out_normal = right if ccw else (-right[0], -right[1])
            N = out_normal if outer else (-out_normal[0], -out_normal[1])
            li = dict(lead_in)
            li["length"] = lead_in["length"] * scale
            lo = dict(lead_out)
            lo["length"] = lead_out["length"] * scale
            if cp["kind"] == "circle" and not outer:
                li["length"] = min(li["length"], cp["r"] * 0.8)
                lo["length"] = min(lo["length"], cp["r"] * 0.8)
            g_in = lead_geometry(P, T, N, li, lead_in["type"], False)
            lead_elems = []
            start = P
            if g_in:
                lead_elems, start = g_in
            tail = []
            if lead_out["type"] == "overcut" and lo["length"] > 0:
                tail = trim_elems(elems, min(lo["length"], total_len(elems) * 0.9))
            elif lead_out["type"] in ("arc", "line") and lo["length"] > 0:
                g_out = lead_geometry(P, T, N, lo, lead_out["type"], True)
                if g_out:
                    tail = g_out[0]
            test = sample_elems(lead_elems, 0.4) + sample_elems(tail if lead_out["type"] != "overcut" else [], 0.4)
            ok = True
            for q in test:
                if bounds and not (bounds[0] <= q[0] <= bounds[2] and bounds[1] <= q[1] <= bounds[3]):
                    ok = False
                    break
                if in_material(q, regions):
                    ok = False
                    break
            if ok:
                return {"elems": elems, "lead_in": lead_elems, "start": start, "tail": tail, "scale": scale, "pos": P}
    return None


def elem_move(e, z, f, k):
    if e[0] == "L":
        return ["feed", round(e[2][0], 4), round(e[2][1], 4), z, f, {"k": k}]
    c = e[3]
    return ["arc", e[4], round(e[2][0], 4), round(e[2][1], 4), z, round(c[0], 4), round(c[1], 4), z, f, "xy", {"k": k}]


def plan_sheet(parts, process, order_mode="part", bounds=None, home=(0.0, 0.0), start_z=0.0):
    kerf = float(process["kerf"])
    pid = process
    zc = float(pid["z_clearance"]) if pid["z_control"] else 0.0
    zp = float(pid["pierce_height"]) if pid["z_control"] else 0.0
    zk = float(pid["cut_height"]) if pid["z_control"] else 0.0
    if process["kind"] == "router":
        zc, zp, zk = float(pid["z_clearance"]), -float(pid["thickness"]), -float(pid["thickness"])
        if process["z_control"]:
            zk = -float(pid["thickness"])
    nloops = sum(len(p["loops"]) for p in parts)
    if nloops > MAX_LOOPS_PLAN:
        raise CutError("%d profile loops is more than the limit of %d." % (nloops, MAX_LOOPS_PLAN))
    half = kerf / 2.0
    regions = [material_regions(p, half * 0.5) for p in parts]
    contours = []
    warnings = []
    for pi, p in enumerate(parts):
        for li, lp in enumerate(p["loops"]):
            cp = cut_loop_path(lp, li == 0, kerf, process["good_side"])
            if cp is None:
                warnings.append("%s: a loop of %s collapses under the kerf offset and is not cut." % (p["name"], "the outline" if li == 0 else "an inner cut"))
                continue
            cp["part"] = pi
            cp["loop"] = li
            cp["name"] = p["name"]
            others = [r for j, r in enumerate(regions)]
            res = plan_contour(cp, kerf, process, others, bounds, None, None)
            if res is None:
                warnings.append("%s: no lead-in fits in scrap for %s; it starts on the contour." % (p["name"], "the outline" if li == 0 else "inner cut %d" % li))
                if cp["kind"] == "circle":
                    elems = circle_elems(cp["c"], cp["r"], math.pi * 1.5, cp["ccw"])
                else:
                    elems = poly_elems(cp["pts"])
                res = {"elems": elems, "lead_in": [], "start": elems[0][1], "tail": [], "scale": 0.0, "pos": elems[0][1]}
            cp.update(res)
            contours.append(cp)
    seq = order_contours(contours, parts, order_mode, home)
    moves = []
    stats = {"pierces": 0, "cut_length": 0.0, "rapid_length": 0.0, "lead_length": 0.0, "contours": len(seq), "dwell_s": 0.0}
    cur = (home[0], home[1], zc)
    moves.append(["rapid", home[0], home[1], zc])
    if process["kind"] == "router":
        moves.append(["spindle", process["power"], "cw"])
    for cp in seq:
        small = False
        if cp["kind"] == "circle" and not cp["outer"]:
            small = 2 * cp["r"] <= process["small_hole_ratio"] * process["thickness"] and process["small_hole_ratio"] > 0
        f = process["feed"] * (process["small_hole_factor"] if small else 1.0)
        sx, sy = cp["start"]
        moves.append(["rapid", round(sx, 4), round(sy, 4), zc, {"k": "approach"}])
        stats["rapid_length"] += math.hypot(sx - cur[0], sy - cur[1]) + abs(zc - cur[2])
        if process["z_control"] and zp != zc:
            moves.append(["feed", round(sx, 4), round(sy, 4), zp, process["pierce_feed"], {"k": "plunge"}])
        kind = process["kind"]
        if kind == "router":
            moves.append(["feed", round(sx, 4), round(sy, 4), zk, process["pierce_feed"], {"k": "plunge"}])
        else:
            moves.append(["spindle", process["power"], "cw", {"k": "pierce"}])
            if process["pierce_delay"] > 0:
                moves.append(["dwell", process["pierce_delay"]])
                stats["dwell_s"] += process["pierce_delay"]
            if process["z_control"] and zk != zp:
                moves.append(["feed", round(sx, 4), round(sy, 4), zk, process["pierce_feed"], {"k": "plunge"}])
        stats["pierces"] += 1
        for e in cp["lead_in"]:
            moves.append(elem_move(e, zk, f, "lead"))
            stats["lead_length"] += elem_len(e)
        for e in cp["elems"]:
            moves.append(elem_move(e, zk, f, "cut"))
            stats["cut_length"] += elem_len(e)
        for e in cp["tail"]:
            moves.append(elem_move(e, zk, f, "lead"))
            stats["lead_length"] += elem_len(e)
        endp = cp["tail"][-1][2] if cp["tail"] else cp["elems"][-1][2]
        if kind != "router":
            moves.append(["spindle", 0, "off"])
        moves.append(["rapid", round(endp[0], 4), round(endp[1], 4), zc, {"k": "retract"}])
        cur = (endp[0], endp[1], zc)
    if process["kind"] == "router":
        moves.append(["spindle", 0, "off"])
    moves.append(["rapid", home[0], home[1], zc])
    stats["rapid_length"] += math.hypot(cur[0] - home[0], cur[1] - home[1])
    return {"moves": moves, "stats": stats, "warnings": warnings, "order": [(c["name"], c["loop"]) for c in seq]}


def order_contours(contours, parts, mode, home):
    remaining = list(contours)
    out = []
    cur = home

    def nearest(cands):
        return min(cands, key=lambda c: math.hypot(c["start"][0] - cur[0], c["start"][1] - cur[1]))

    if mode == "all-inner-first":
        inner = [c for c in remaining if not c["outer"]]
        outer = [c for c in remaining if c["outer"]]
        for group in (inner, outer):
            group = list(group)
            while group:
                c = nearest(group)
                group.remove(c)
                out.append(c)
                cur = c["start"]
        return out
    by_part = {}
    for c in remaining:
        by_part.setdefault(c["part"], []).append(c)
    parts_left = set(by_part)
    while parts_left:
        pi = min(parts_left, key=lambda k: min(math.hypot(c["start"][0] - cur[0], c["start"][1] - cur[1]) for c in by_part[k]))
        parts_left.discard(pi)
        inner = [c for c in by_part[pi] if not c["outer"]]
        outer = [c for c in by_part[pi] if c["outer"]]
        while inner:
            c = nearest(inner)
            inner.remove(c)
            out.append(c)
            cur = c["start"]
        for c in outer:
            out.append(c)
            cur = c["start"]
    return out
