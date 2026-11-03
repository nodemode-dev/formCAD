import math

from app.part.registry import PartError
from app.weld import shapes

MAX_MEMBERS = 200
MAX_TAN_DEG = 85.0
TREATMENTS = ("miter", "butt", "cope", "none")


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def mul(a, k):
    return [a[0] * k, a[1] * k, a[2] * k]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n < 1e-12:
        raise PartError("A direction has zero length.")
    return [a[0] / n, a[1] / n, a[2] / n]


def point3(v, mm, what):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise PartError("%s must be three numbers." % what)
    try:
        out = [float(c) * mm for c in v]
    except (TypeError, ValueError):
        raise PartError("%s must be three numbers." % what)
    if not all(math.isfinite(c) and abs(c) < 1e7 for c in out):
        raise PartError("%s is out of range." % what)
    return out


def frame_of(direction, rot_deg):
    ref = [0.0, 0.0, 1.0] if abs(direction[2]) < 0.999 else [1.0, 0.0, 0.0]
    u = unit(cross(ref, direction))
    v = cross(direction, u)
    a = math.radians(rot_deg)
    c, s = math.cos(a), math.sin(a)
    return [u[i] * c + v[i] * s for i in range(3)], [-u[i] * s + v[i] * c for i in range(3)]


def support(m, d):
    best = -1e18
    for pu, pv in m["pts"]:
        w = pu * dot(m["u"], d) + pv * dot(m["v"], d)
        best = max(best, w)
    return best


def end_dir(m, end):
    return mul(m["dir"], -1.0) if end == "s" else list(m["dir"])


def into_dir(m, end):
    return list(m["dir"]) if end == "s" else mul(m["dir"], -1.0)


def end_point(m, end):
    return list(m["a"]) if end == "s" else list(m["b"])


def read_members(raw, mm, profile_of):
    if not isinstance(raw, list) or not raw:
        raise PartError("Give at least one member.")
    if len(raw) > MAX_MEMBERS:
        raise PartError("A frame holds at most %d members." % MAX_MEMBERS)
    out, seen = [], set()
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            raise PartError("Member %d is not an object." % (i + 1))
        mid = str(r.get("id") or "M%d" % (i + 1))
        if mid in seen:
            raise PartError("Member id %s is used twice." % mid)
        seen.add(mid)
        a = point3(r.get("a"), mm, "Member %s start" % mid)
        b = point3(r.get("b"), mm, "Member %s end" % mid)
        vec = sub(b, a)
        length = norm(vec)
        if length < 1e-6:
            raise PartError("Member %s has zero length." % mid)
        d = [c / length for c in vec]
        try:
            rot = float(r.get("rotation") or 0.0)
        except (TypeError, ValueError):
            raise PartError("Member %s rotation must be a number." % mid)
        loc = r.get("locate") or [0.0, 0.0]
        if not isinstance(loc, (list, tuple)) or len(loc) != 2:
            raise PartError("Member %s locate is two numbers." % mid)
        regions, label = profile_of(r.get("profile"), mid)
        du, dv = float(loc[0]) * mm, float(loc[1]) * mm
        regions = shapes.shifted(regions, du, dv)
        u, v = frame_of(d, rot)
        pts = shapes.points_of(regions)
        out.append({"id": mid, "idx": i, "a": a, "b": b, "dir": d, "L": length, "u": u, "v": v, "regions": regions, "pts": pts, "radius": max(math.hypot(p[0], p[1]) for p in pts), "profile": label, "group": str(r.get("group") or ""), "label": str(r.get("label") or mid), "trim": {"s": r.get("start_trim"), "e": r.get("end_trim")}, "ends": {}, "ext": {"s": 0.0, "e": 0.0}, "over": {"s": 0.0, "e": 0.0}, "cuts": {"s": None, "e": None}, "trims": [], "notes": []})
    return out


def cluster(members, tol):
    pts = []
    for m in members:
        pts.append((m["idx"], "s", m["a"]))
        pts.append((m["idx"], "e", m["b"]))
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if norm(sub(pts[i][2], pts[j][2])) <= tol:
                parent[find(i)] = find(j)
    groups = {}
    for i, p in enumerate(pts):
        groups.setdefault(find(i), []).append(p)
    nodes = []
    for g in groups.values():
        pos = [sum(p[2][k] for p in g) / len(g) for k in range(3)]
        nodes.append({"pos": pos, "ends": [(p[0], p[1]) for p in g], "through": []})
    nodes.sort(key=lambda n: (n["ends"][0][0], n["ends"][0][1]))
    for node in nodes:
        have = {e[0] for e in node["ends"]}
        for m in members:
            if m["idx"] in have:
                continue
            rel = sub(node["pos"], m["a"])
            t = dot(rel, m["dir"])
            if tol < t < m["L"] - tol:
                off = sub(rel, mul(m["dir"], t))
                if norm(off) <= tol:
                    node["through"].append(m["idx"])
    return [n for n in nodes if len(n["ends"]) + len(n["through"]) >= 2]


def junction_override(spec, node, tol):
    for j in spec or []:
        if not isinstance(j, dict):
            continue
        at = j.get("_at")
        if at is not None and norm(sub(at, node["pos"])) <= max(tol, 1e-6):
            return j
    return None


def plane_cut(m, end, p, n_out):
    e = end_dir(m, end)
    c = dot(n_out, e)
    if c <= 1e-6:
        raise PartError("The cut at the %s of member %s is parallel to the member." % ("start" if end == "s" else "end", m["id"]))
    t = dot(n_out, sub(p, end_point(m, end))) / c
    m["cuts"][end] = {"p": p, "n": n_out, "t": t}
    ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
    rot = math.degrees(math.atan2(dot(n_out, m["v"]), dot(n_out, m["u"]))) if ang > 1e-6 else 0.0
    return ang, rot


def set_end(m, end, kind, angle=0.0, rot=0.0, node=None, against=None):
    m["ends"][end] = {"kind": kind, "angle": angle, "rot": rot, "node": node, "against": against or []}


def solve(members, corner, junction_specs, tol, mm):
    by_id = {m["id"]: m for m in members}
    nodes = cluster(members, tol)
    for j in junction_specs or []:
        if isinstance(j, dict) and j.get("at") is not None:
            j["_at"] = point3(j["at"], mm, "Junction position")
    seen = set()
    for node in nodes:
        spec = junction_override(junction_specs, node, tol) or {}
        kind = spec.get("treatment") or corner
        if kind not in TREATMENTS:
            raise PartError("Treatment %s is not one of %s." % (kind, ", ".join(TREATMENTS)))
        ends = [(members[i], e) for i, e in node["ends"]]
        thr = [members[i] for i in node["through"]]
        for m, e in ends:
            seen.add((m["idx"], e))
        label = "(%.3f, %.3f, %.3f)" % tuple(c / mm for c in node["pos"])
        if kind == "none":
            for m, e in ends:
                set_end(m, e, "none", node=label)
            continue
        if kind == "miter" and thr:
            kind = "butt"
        if kind == "miter":
            if len(ends) != 2:
                raise PartError("A miter joins exactly two members; the junction at %s has %d. Use butt or cope." % (label, len(ends)))
            (m1, e1), (m2, e2) = ends
            if m1 is m2:
                raise PartError("A member meets itself at %s." % label)
            u1, u2 = into_dir(m1, e1), into_dir(m2, e2)
            n = sub(u1, u2)
            if norm(n) < 1e-6:
                raise PartError("Members %s and %s fold back on each other at %s." % (m1["id"], m2["id"], label))
            n = unit(n)
            a1, r1 = plane_cut(m1, e1, node["pos"], mul(n, -1.0))
            a2, r2 = plane_cut(m2, e2, node["pos"], n)
            set_end(m1, e1, "miter", a1, r1, label, [m2["id"]])
            set_end(m2, e2, "miter", a2, r2, label, [m1["id"]])
            continue
        rank = {m["id"]: (0, m["idx"]) for m in thr}
        for m, _ in ends:
            rank[m["id"]] = (1, -m["L"], m["idx"])
        order = sorted(rank, key=lambda k: rank[k])
        want = [str(x) for x in (spec.get("order") or [])]
        for x in want:
            if x not in by_id:
                raise PartError("The order at %s names %s, which is not a member." % (label, x))
        want = [x for x in want if x in rank]
        thr_ids = [m["id"] for m in thr]
        head = [x for x in want if x in thr_ids] + [x for x in order if x in thr_ids and x not in want]
        tail = [x for x in want if x not in thr_ids] + [x for x in order if x not in thr_ids and x not in want]
        order = head + tail
        top = by_id[order[0]]
        top_end = next((e for m, e in ends if m is top), None)
        lowers = [(m, e) for m, e in ends if m is not top]
        if not lowers and not thr:
            raise PartError("The junction at %s has nothing to trim." % label)
        if top_end is not None:
            out = end_dir(top, top_end)
            ext = 0.0
            for m, e in lowers:
                ext = max(ext, support(m, out))
            top["ext"][top_end] = max(ext, 0.0)
            set_end(top, top_end, "through", node=label, against=[m["id"] for m, _ in lowers])
        for m, e in lowers:
            uA = into_dir(m, e)
            cands = [top["u"], mul(top["u"], -1.0), top["v"], mul(top["v"], -1.0)]
            n = max(cands, key=lambda c: dot(c, uA))
            if kind == "butt":
                if dot(n, uA) < 0.2:
                    raise PartError("Member %s runs almost parallel to member %s at %s; use cope." % (m["id"], top["id"], label))
                h = support(top, n)
                p = add(node["pos"], mul(n, h))
                ang, rot = plane_cut(m, e, p, mul(n, -1.0))
                set_end(m, e, "butt", ang, rot, label, [top["id"]])
            else:
                depth = support(top, n) + support(top, mul(n, -1.0))
                m["over"][e] = max(m["over"][e], 0.45 * depth)
                higher = order[: order.index(m["id"])]
                m["trims"].extend(x for x in higher if x not in m["trims"])
                cosang = abs(dot(m["dir"], top["dir"]))
                ang = abs(90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cosang)))))
                set_end(m, e, "cope", ang, 0.0, label, [top["id"]])
    for m in members:
        for end in ("s", "e"):
            trim = m["trim"][end]
            if end in m["ends"]:
                if trim:
                    raise PartError("Member %s has a trim plane at an end that is already joined; remove the junction treatment or the trim." % m["id"])
                continue
            if trim:
                pl = (trim or {}).get("plane") if isinstance(trim, dict) else None
                if not pl:
                    raise PartError("A trim is {plane: {point, normal}}.")
                p = point3(pl.get("point"), mm, "Trim plane point")
                n = unit(point3(pl.get("normal"), mm, "Trim plane normal"))
                if dot(n, end_dir(m, end)) < 0:
                    n = mul(n, -1.0)
                ang, rot = plane_cut(m, end, p, n)
                set_end(m, end, "trim_to", ang, rot, None, [])
            else:
                set_end(m, end, "free")
    for m in members:
        for end in ("s", "e"):
            cut = m["cuts"][end]
            R = m["radius"]
            if cut is not None:
                ang = m["ends"][end]["angle"]
                tan = math.tan(math.radians(min(ang, MAX_TAN_DEG)))
                m["over"][end] = max(m["over"][end], max(cut["t"], 0.0) + R * tan + 1.0)
    return nodes


def worker_member(m):
    s0 = -(m["ext"]["s"] + m["over"]["s"])
    s1 = m["L"] + m["ext"]["e"] + m["over"]["e"]
    cuts = []
    for end in ("s", "e"):
        c = m["cuts"][end]
        if c is not None:
            cuts.append({"p": c["p"], "n": c["n"]})
    return {
        "id": m["id"], "origin": add(m["a"], mul(m["dir"], s0)), "axis": m["dir"], "u": m["u"], "length": s1 - s0,
        "regions": m["regions"], "cuts": cuts, "trims": list(m["trims"]), "extent": 2.0 * m["radius"],
        "start_normal": None if m["cuts"]["s"] is None else m["cuts"]["s"]["n"], "end_normal": None if m["cuts"]["e"] is None else m["cuts"]["e"]["n"],
    }


def flip_v(regions):
    def loop(lp):
        segs = []
        for s in lp["segs"]:
            q = dict(s)
            if s["t"] == "circle":
                q["c"] = [s["c"][0], -s["c"][1]]
            else:
                q["a"] = [s["a"][0], -s["a"][1]]
                q["b"] = [s["b"][0], -s["b"][1]]
                q["bulge"] = -float(s.get("bulge", 0.0) or 0.0)
            segs.append(q)
        return {"segs": segs, "closed": lp.get("closed", True)}

    return [{"outer": loop(r["outer"]), "holes": [loop(h) for h in r.get("holes") or []]} for r in regions]


def cap_regions(m, spec, mm):
    kind = spec.get("shape") or "match"
    try:
        off = float(spec.get("offset") or 0.0) * mm
    except (TypeError, ValueError):
        raise PartError("The cap offset must be a number.")
    if kind == "match":
        if abs(off) > 1e-9:
            raise PartError("A matching cap takes no offset; use rectangle or circle.")
        return shapes.shifted([{"outer": r["outer"], "holes": []} for r in m["regions"]], 0.0, 0.0), "match"
    pts = m["pts"]
    if kind == "rectangle":
        u0, u1 = min(p[0] for p in pts) - off, max(p[0] for p in pts) + off
        v0, v1 = min(p[1] for p in pts) - off, max(p[1] for p in pts) + off
        if u1 - u0 <= 1e-6 or v1 - v0 <= 1e-6:
            raise PartError("The cap offset leaves nothing.")
        return [{"outer": shapes.poly([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], "c"), "holes": []}], "rectangle"
    if kind == "circle":
        r = max(math.hypot(p[0], p[1]) for p in pts) + off
        if r <= 1e-6:
            raise PartError("The cap offset leaves nothing.")
        return [{"outer": shapes.circle(2.0 * r, "c"), "holes": []}], "circle"
    raise PartError("A cap shape is match, rectangle or circle.")


def build_caps(members, specs, mm, fid_prefix):
    by_id = {m["id"]: m for m in members}
    out = []
    for i, s in enumerate(specs or []):
        if not isinstance(s, dict):
            raise PartError("End cap %d is not an object." % (i + 1))
        m = by_id.get(str(s.get("member")))
        if m is None:
            raise PartError("End cap %d names member %s, which is not in the frame." % (i + 1, s.get("member")))
        end = "s" if str(s.get("end") or "end").lower() in ("s", "start") else "e"
        if m["cuts"][end] is not None or m["over"][end] > 0.0:
            raise PartError("An end cap needs a square end; the %s of member %s is cut or coped." % ("start" if end == "s" else "end", m["id"]))
        try:
            t = float(s.get("thickness")) * mm
        except (TypeError, ValueError):
            raise PartError("End cap %d needs a thickness." % (i + 1))
        if not 0 < t < 1e4:
            raise PartError("End cap %d thickness is out of range." % (i + 1))
        regions, kind = cap_regions(m, s, mm)
        e = end_dir(m, end)
        origin = add(end_point(m, end), mul(m["dir"], m["ext"][end] if end == "e" else -m["ext"][end]))
        if end == "s":
            regions = flip_v(regions)
        cid = "C%d" % (i + 1)
        out.append({"id": cid, "member": m["id"], "end": end, "kind": kind, "thickness": t, "origin": origin, "axis": e, "u": m["u"], "regions": regions, "label": str(s.get("label") or "")})
        m["notes"].append("End cap at %s" % ("start" if end == "s" else "end"))
    return out


def build_gussets(members, nodes, specs, mm):
    by_id = {m["id"]: m for m in members}
    out = []
    for i, s in enumerate(specs or []):
        if not isinstance(s, dict) or not isinstance(s.get("members"), list) or len(s["members"]) != 2:
            raise PartError("Gusset %d needs members: [idA, idB]." % (i + 1))
        a, b = by_id.get(str(s["members"][0])), by_id.get(str(s["members"][1]))
        if a is None or b is None or a is b:
            raise PartError("Gusset %d names members that are not two different members of the frame." % (i + 1))
        node = None
        for n in nodes:
            ids = {members[k]["id"] for k, _ in n["ends"]} | {members[k]["id"] for k in n["through"]}
            if a["id"] in ids and b["id"] in ids:
                node = n
                break
        if node is None:
            raise PartError("Members %s and %s do not meet at a junction." % (a["id"], b["id"]))

        def leg_dir(m):
            for k, e in node["ends"]:
                if members[k] is m:
                    return into_dir(m, e)
            return list(m["dir"]) if int(s.get("side") or 1) > 0 else mul(m["dir"], -1.0)

        ua, ub = leg_dir(a), leg_dir(b)
        nrm = cross(ua, ub)
        if norm(nrm) < 1e-3:
            raise PartError("Members %s and %s are parallel; a gusset needs an angle between them." % (a["id"], b["id"]))
        try:
            leg = float(s.get("leg")) * mm
            t = float(s.get("thickness")) * mm
        except (TypeError, ValueError):
            raise PartError("Gusset %d needs a leg and a thickness." % (i + 1))
        if not (0 < leg < 1e5 and 0 < t < 1e4):
            raise PartError("Gusset %d leg or thickness is out of range." % (i + 1))
        pos = node["pos"]
        out.append({"id": "G%d" % (i + 1), "members": [a["id"], b["id"]], "tri": [pos, add(pos, mul(ua, leg)), add(pos, mul(ub, leg))], "normal": unit(nrm), "thickness": t, "leg": leg, "cut_members": [a["id"], b["id"]], "label": str(s.get("label") or "")})
        a["notes"].append("Gusset")
        b["notes"].append("Gusset")
    return out
