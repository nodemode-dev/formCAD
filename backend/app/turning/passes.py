import math

import pyclipper as pc

from app.turning import profile as PF
from app.turning.profile import SC, TurnError

ARC_TOL = 0.002
MAX_PASSES = 4000
MAX_SAMPLES = 4000
THREAD_FLANK = 29.5


def ints(pts):
    return [(int(round(z * SC)), int(round(x * SC))) for z, x in pts]


def floats(path):
    return [(a / SC, b / SC) for a, b in path]


def area(path):
    return pc.Area(path)


def offset_ring(poly, delta):
    co = pc.PyclipperOffset(2.0, ARC_TOL * SC)
    co.AddPath(ints(poly), pc.JT_ROUND, pc.ET_CLOSEDPOLYGON)
    res = co.Execute(delta * SC)
    return [floats(r) for r in res]


def offset_chain(profile, off, z_last):
    poly = PF.polygon(profile)
    rings = offset_ring(poly, off)
    if not rings:
        raise TurnError("The profile collapses under the tool offset.")
    ring = ints(max(rings, key=lambda r: abs(area(ints(r)))))
    big = 10 ** 11
    c = pc.Pyclipper()
    c.AddPath(ring, pc.PT_SUBJECT, True)
    c.AddPath([(-big, 0), (big, 0), (big, big), (-big, big)], pc.PT_CLIP, True)
    sol = c.Execute(pc.CT_INTERSECTION, pc.PFT_NONZERO, pc.PFT_NONZERO)
    if not sol:
        raise TurnError("The tool offset path lies below the axis.")
    pts = floats(max(sol, key=lambda r: abs(area(r))))
    n = len(pts)
    on = [p[1] <= 1e-6 for p in pts]
    if not any(on) or all(on):
        raise TurnError("The tool offset path has no clear run above the axis.")
    start = None
    for i in range(n):
        if on[i] and not on[i - 1]:
            start = i
    run = []
    i = start
    while on[i % n]:
        run.append(i % n)
        i += 1
    first_off = (run[-1] + 1) % n
    chain = [pts[(first_off + k) % n] for k in range(n - len(run))]
    chain.insert(0, pts[run[-1]])
    chain.append(pts[run[0]])
    if chain[0][0] < chain[-1][0]:
        chain.reverse()
    out = []
    for p in chain:
        if p[0] < z_last - 1e-9:
            if out and out[-1][0] > z_last + 1e-9:
                a = out[-1]
                t = (a[0] - z_last) / (a[0] - p[0])
                out.append((z_last, a[1] + (p[1] - a[1]) * t))
            break
        out.append(p)
    res = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - res[-1][0], p[1] - res[-1][1]) > 1e-6:
            res.append(p)
    return res


def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts
    lo = []
    for p in pts:
        while len(lo) >= 2 and (lo[-1][0] - lo[-2][0]) * (p[1] - lo[-2][1]) - (lo[-1][1] - lo[-2][1]) * (p[0] - lo[-2][0]) <= 0:
            lo.pop()
        lo.append(p)
    up = []
    for p in reversed(pts):
        while len(up) >= 2 and (up[-1][0] - up[-2][0]) * (p[1] - up[-2][1]) - (up[-1][1] - up[-2][1]) * (p[0] - up[-2][0]) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def insert_hull(c, rn, tip, lead, size):
    s = math.radians(lead - 90.0)
    e = s + math.radians(tip)
    pts = [(c[0] + rn * math.cos(2 * math.pi * k / 32), c[1] + rn * math.sin(2 * math.pi * k / 32)) for k in range(32)]
    pts.append((c[0] + size * math.cos(s), c[1] + size * math.sin(s)))
    pts.append((c[0] + size * math.cos(e), c[1] + size * math.sin(e)))
    return convex_hull(pts)


def gouge_check(chain, profile, tool, step=0.4, tol_area=0.0004, z_last=None):
    part = ints(PF.polygon(profile))
    out = {"samples": 0, "hits": 0, "worst_area": 0.0, "at": None}
    rn = tool["nose_radius"]
    tip = tool["tip_angle"]
    lead = tool["lead_angle"]
    size = tool["insert_size"]
    pts = []
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / step))
        for k in range(n):
            pts.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    pts.append(chain[-1])
    if len(pts) > MAX_SAMPLES:
        pts = pts[:: int(math.ceil(len(pts) / MAX_SAMPLES))]
    for c in pts:
        w = ints(insert_hull(c, rn * 0.999, tip, lead, size))
        cl = pc.Pyclipper()
        cl.AddPath(w, pc.PT_SUBJECT, True)
        cl.AddPath(part, pc.PT_CLIP, True)
        inter = cl.Execute(pc.CT_INTERSECTION, pc.PFT_NONZERO, pc.PFT_NONZERO)
        a = sum(abs(pc.Area(p)) for p in inter) / (SC * SC)
        out["samples"] += 1
        if a > tol_area:
            out["hits"] += 1
            if a > out["worst_area"]:
                out["worst_area"] = a
                out["at"] = [round(c[0], 3), round(c[1], 3)]
    return out


class Pen:
    def __init__(self, f, rpm_note=None):
        self.m = []
        self.pos = None
        self.fpr = f["fpr"]
        self.fmin = f["feed_min"]
        self.cut = 0.0
        self.rapid = 0.0

    def go(self, z, x):
        if self.pos is not None:
            self.rapid += math.hypot(z - self.pos[0], x - self.pos[1])
        self.m.append(["rapid", round(x, 4), 0.0, round(z, 4)])
        self.pos = (z, x)

    def rap(self, z, x, k="approach"):
        if self.pos is not None:
            self.rapid += math.hypot(z - self.pos[0], x - self.pos[1])
        self.m.append(["rapid", round(x, 4), 0.0, round(z, 4), {"k": k}])
        self.pos = (z, x)

    def feed(self, z, x, k="cut", fpr=None, sync=None):
        fp = self.fpr if fpr is None else fpr
        f = self.fmin * (fp / self.fpr) if self.fpr else self.fmin
        o = {"k": k, "fpr": round(fp, 5)}
        if sync is not None:
            o["sync"] = sync
        if self.pos is not None:
            self.cut += math.hypot(z - self.pos[0], x - self.pos[1])
        self.m.append(["feed", round(x, 4), 0.0, round(z, 4), round(f, 3), o])
        self.pos = (z, x)

    def feed_chain(self, chain, k="cut"):
        for z, x in chain:
            self.feed(z, x, k)


def feeds(p, d_ref):
    vc = float(p["vc"])
    rpm = min(float(p["max_rpm"]), 1000.0 * vc / (math.pi * max(d_ref, 1.0)))
    return {"rpm": rpm, "fpr": float(p["fpr"]), "feed_min": rpm * float(p["fpr"]), "vc": vc, "max_rpm": float(p["max_rpm"])}


def header(f, tool_number, name, label):
    return [["comment", label], ["tool", int(tool_number), round(f["rpm"], 1), name], ["spindle", round(f["rpm"], 1), "cw", {"css": {"vc": f["vc"], "max_rpm": f["max_rpm"]}}]]


def clearances(p):
    return float(p["clear_x"]), float(p["clear_z"]), float(p["retract"])


def check_stock(profile, stock_r):
    mx = max(pt[1] for pt in profile["pts"])
    if mx > stock_r + 1e-6:
        raise TurnError("The profile is larger than the stock (radius %.3f against %.3f)." % (mx, stock_r))


def rough(profile, p, tool, stock_r, z_front, ctx_check=None):
    rn = tool["nose_radius"]
    z_last = profile["pts"][-1][0]
    check_stock(profile, stock_r)
    if not PF.check_direction(profile):
        raise TurnError("The profile runs back toward the front (an undercut). Rough turning needs z to fall from the front to the back; cut the undercut with a groove operation.")
    doc = float(p["doc"])
    allow = float(p["allowance"])
    cx, cz, ret = clearances(p)
    f = feeds(p, 2 * stock_r * 0.75)
    pen = Pen(f)
    pen.m.extend(header(f, tool["number"], tool["name"], p.get("label") or "Rough turning"))
    forbid = [ints(r) for r in offset_ring(PF.polygon(profile, z_front, None), rn + allow)]
    if not forbid:
        raise TurnError("The profile collapses under the tool offset.")
    z_start = z_front + rn + cz
    z_stop = z_last - 1.0
    r_min = min(pt[1] for pt in profile["pts"])
    lines = []
    s = stock_r - doc
    guard = 0
    warnings = []
    while s > r_min + allow - 1e-6 and guard < MAX_PASSES:
        lines.append(s)
        s -= doc
        guard += 1
    final = r_min + allow
    if final < stock_r - 1e-9 and (not lines or lines[-1] > final + 1e-6):
        lines.append(final)
    pen.go(z_start, stock_r + rn + cx)
    passes = 0
    for sk in lines:
        if ctx_check:
            ctx_check()
        xc = sk + rn
        cl = pc.Pyclipper()
        cl.AddPath(ints([(z_start, xc), (z_stop, xc)]), pc.PT_SUBJECT, False)
        cl.AddPaths(forbid, pc.PT_CLIP, True)
        tree = cl.Execute2(pc.CT_DIFFERENCE, pc.PFT_NONZERO, pc.PFT_NONZERO)
        segs = [floats(path) for path in pc.OpenPathsFromPolyTree(tree)]
        reach = None
        for sg in segs:
            za, zb = sg[0][0], sg[-1][0]
            hi, lo = max(za, zb), min(za, zb)
            if hi >= z_start - 1e-3:
                reach = (hi, lo)
        if reach is None or reach[0] - reach[1] < 1e-4:
            continue
        hi, lo = reach
        if len(segs) > 1:
            warnings.append("Some material at radius %.3f lies behind a shoulder and is left for a groove operation." % sk)
        pen.rap(z_start, xc + ret)
        pen.rap(z_start, xc)
        pen.feed(lo, xc, "cut")
        wall = lo > z_stop + 1e-6
        pen.rap(lo + (ret if wall else 0.0), xc + ret, "retract")
        pen.rap(z_start, xc + ret)
        passes += 1
    chain = None
    if p.get("contour_pass", True):
        chain = offset_chain(profile, rn + allow, z_last)
        pen.rap(z_start, chain[0][1] + ret if chain[0][1] > 0 else ret)
        pen.rap(chain[0][0] + cz, chain[0][1])
        pen.feed_chain(chain, "cut")
    pen.rap(pen.pos[0] + ret, stock_r + rn + cx, "retract")
    pen.rap(z_start, stock_r + rn + cx)
    return {"moves": pen.m, "stats": {"passes": passes, "cut_length": pen.cut, "rapid_length": pen.rapid, "rpm": f["rpm"]}, "warnings": sorted(set(warnings)), "chain": chain}


def finish(profile, p, tool, stock_r, z_front):
    rn = tool["nose_radius"]
    z_last = profile["pts"][-1][0]
    check_stock(profile, stock_r)
    cx, cz, ret = clearances(p)
    allow = float(p.get("allowance", 0.0))
    f = feeds(p, 2 * stock_r * 0.6)
    pen = Pen(f)
    pen.m.extend(header(f, tool["number"], tool["name"], p.get("label") or "Finish turning"))
    chain = offset_chain(profile, rn + allow, z_last)
    pen.go(z_front + rn + cz, stock_r + rn + cx)
    pen.rap(z_front + rn + cz, chain[0][1] + ret)
    pen.rap(chain[0][0] + cz, chain[0][1])
    pen.feed_chain(chain, "cut")
    pen.rap(pen.pos[0], pen.pos[1] + ret, "retract")
    pen.rap(pen.pos[0] + ret, stock_r + rn + cx, "retract")
    pen.rap(z_front + rn + cz, stock_r + rn + cx)
    warn = []
    gg = gouge_check(chain, profile, tool) if p.get("check_insert", True) else None
    if gg and gg["hits"]:
        warn.append("The insert shape touches the profile at %d of %d sample points (worst overlap %.3f mm2 near z %.2f, radius %.2f); the profile has a back cut the tool cannot reach." % (gg["hits"], gg["samples"], gg["worst_area"], gg["at"][0], gg["at"][1]))
    return {"moves": pen.m, "stats": {"cut_length": pen.cut, "rapid_length": pen.rapid, "points": len(chain), "rpm": f["rpm"], "gouge": gg}, "warnings": warn, "chain": chain}


def face(p, tool, stock_r, z_front, z_target):
    rn = tool["nose_radius"]
    cx, cz, ret = clearances(p)
    doc = float(p["doc"])
    if z_front < z_target + 1e-9:
        raise TurnError("There is nothing to face: the stock front is at z %.3f and the finished face at z %.3f." % (z_front, z_target))
    allow = float(p["allowance"])
    f = feeds(p, 2 * stock_r * 0.5)
    pen = Pen(f)
    pen.m.extend(header(f, tool["number"], tool["name"], p.get("label") or "Facing"))
    levels = []
    z = z_front - doc
    while z > z_target + allow + 1e-9 and len(levels) < MAX_PASSES:
        levels.append(z)
        z -= doc
    if allow > 0 or not levels or levels[-1] > z_target + 1e-9:
        levels.append(z_target + allow)
    pen.go(z_front + rn + cz, stock_r + rn + cx)
    over = float(p.get("overtravel", 0.0))
    for zs in levels:
        zc = zs + rn
        pen.rap(z_front + rn + cz, stock_r + rn + cx)
        pen.rap(zc, stock_r + rn + cx)
        pen.feed(zc, -over, "cut")
        pen.rap(zc + ret, ret - over, "retract")
        pen.rap(zc + ret, stock_r + rn + cx, "retract")
    pen.rap(z_front + rn + cz, stock_r + rn + cx)
    return {"moves": pen.m, "stats": {"passes": len(levels), "cut_length": pen.cut, "rapid_length": pen.rapid, "rpm": f["rpm"]}, "warnings": []}


def groove(p, tool, stock_r):
    tw = tool["width"]
    z_a = float(p["z_start"])
    w = float(p["width"])
    z_b = z_a - w
    r_b = float(p["bottom_diameter"]) / 2.0
    r_top = float(p["top_diameter"]) / 2.0 if p.get("top_diameter") else stock_r
    if tw > w + 1e-9:
        raise TurnError("The groove tool is %.3f wide, wider than the %.3f groove." % (tw, w))
    if r_b >= r_top:
        raise TurnError("The groove bottom is not below its top.")
    cx, cz, ret = clearances(p)
    allow = float(p["allowance"])
    f = feeds(p, 2 * r_top * 0.5)
    pen = Pen(f)
    pen.m.extend(header(f, tool["number"], tool["name"], p.get("label") or "Groove"))
    ov = float(p["overlap"])
    step = max(tw * (1.0 - ov), 0.01)
    lo = z_b + tw / 2.0 + allow
    hi = z_a - tw / 2.0 - allow
    if hi < lo - 1e-9:
        lo = hi = (z_a + z_b) / 2.0
    n = 1 if hi - lo < 1e-9 else int(math.ceil((hi - lo) / step - 1e-9)) + 1
    zs = [lo + (hi - lo) * i / max(n - 1, 1) for i in range(n)] if n > 1 else [lo]
    peck = float(p["peck"])
    x_floor = r_b + allow
    x_clear = r_top + cx
    count = 0
    for zc in zs:
        pen.rap(zc, x_clear)
        x = r_top
        while x > x_floor + 1e-9:
            x = max(x - peck, x_floor)
            pen.feed(zc, x, "plunge")
            if x > x_floor + 1e-9:
                pen.rap(zc, x + ret, "retract")
                pen.rap(zc, x, "approach")
        pen.rap(zc, x_clear, "retract")
        count += 1
    if allow > 0 or n == 1:
        zl, zr = z_b + tw / 2.0, z_a - tw / 2.0
        pen.rap(zl + ret * 0.0, x_clear)
        pen.rap(zl, r_top + ret)
        pen.feed(zl, r_b, "cut")
        pen.feed(zr, r_b, "cut")
        pen.feed(zr, r_top + ret, "cut")
        pen.rap(zr, x_clear, "retract")
    return {"moves": pen.m, "stats": {"plunges": count, "cut_length": pen.cut, "rapid_length": pen.rapid, "rpm": f["rpm"]}, "warnings": []}


def thread(p, tool, major_r):
    pitch = float(p["pitch"])
    depth = float(p["depth"]) if p.get("depth") else 0.6134 * pitch
    n = int(p["passes"])
    z_a = float(p["z_start"])
    z_b = float(p["z_end"])
    if z_b >= z_a:
        raise TurnError("The thread ends at z %.3f, not behind its start at z %.3f." % (z_b, z_a))
    cx, cz, ret = clearances(p)
    lead_in = float(p["lead_in"]) if p.get("lead_in") else 3.0 * pitch
    f = feeds({"vc": p["vc"], "fpr": pitch, "max_rpm": p["max_rpm"]}, 2 * major_r)
    fixed_rpm = min(float(p["max_rpm"]), 1000.0 * float(p["vc"]) / (math.pi * 2 * major_r))
    f["rpm"] = fixed_rpm
    f["feed_min"] = fixed_rpm * pitch
    pen = Pen(f)
    pen.m.append(["comment", p.get("label") or "Thread M%g x %g" % (2 * major_r, pitch)])
    pen.m.append(["tool", int(tool["number"]), round(fixed_rpm, 1), tool["name"]])
    pen.m.append(["spindle", round(fixed_rpm, 1), "cw"])
    infeed = p["infeed"]
    shift_k = math.tan(math.radians(THREAD_FLANK))
    first = float(p["first_depth"]) if p.get("first_depth") else None
    depths = []
    for k in range(1, n + 1):
        d = depth * math.sqrt(k / n)
        if first is not None and k == 1:
            d = min(first, depth)
        depths.append(d)
    for _ in range(int(p["spring_passes"])):
        depths.append(depth)
    x_clear = major_r + cx
    pen.go(z_a + lead_in, x_clear)
    for d in depths:
        sh = (d - 0.0) * shift_k if infeed == "flank" else 0.0
        xp = major_r - d
        pen.rap(z_a + lead_in + sh, x_clear)
        pen.rap(z_a + lead_in + sh, xp)
        pen.feed(z_b + sh, xp, "cut", fpr=pitch, sync=pitch)
        pen.rap(z_b + sh, x_clear, "retract")
        pen.rap(z_a + lead_in, x_clear, "retract")
    return {"moves": pen.m, "stats": {"passes": len(depths), "depth": depth, "cut_length": pen.cut, "rapid_length": pen.rapid, "rpm": fixed_rpm, "pitch": pitch, "lead_in": lead_in}, "warnings": []}


def partoff(p, tool, stock_r):
    tw = tool["width"]
    z_end = float(p["z"])
    zc = z_end - tw / 2.0
    cx, cz, ret = clearances(p)
    to_r = float(p["to_diameter"]) / 2.0
    f = feeds(p, 2 * stock_r * 0.7)
    pen = Pen(f)
    pen.m.extend(header(f, tool["number"], tool["name"], p.get("label") or "Part off"))
    peck = float(p["peck"])
    slow_r = float(p["slow_radius"])
    slow = float(p["slow_factor"])
    pen.go(zc, stock_r + cx)
    x = stock_r
    pen.rap(zc, x + ret)
    while x > to_r + 1e-9:
        nx = max(x - peck, to_r)
        if nx < slow_r and slow < 1.0:
            seg_f = f["fpr"] * slow
        else:
            seg_f = f["fpr"]
        pen.feed(zc, nx, "plunge", seg_f)
        x = nx
        if x > to_r + 1e-9 and peck < stock_r:
            pen.rap(zc, x + ret, "retract")
            pen.rap(zc, x, "approach")
    pen.rap(zc, stock_r + cx, "retract")
    if p.get("stop_after"):
        pen.m.append(["stop", "optional"])
    return {"moves": pen.m, "stats": {"cut_length": pen.cut, "rapid_length": pen.rapid, "rpm": f["rpm"]}, "warnings": []}
