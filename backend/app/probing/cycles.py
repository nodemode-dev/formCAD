import math

from app.probing import expr as E


class ProbeError(ValueError):
    pass


KINDS = ("surface", "edge", "bore", "boss", "width", "corner", "skew")
MODES = {"toward": "g38.2", "toward_soft": "g38.3", "away": "g38.4", "away_soft": "g38.5"}

COMMON = {"slot": 1, "update": True, "radius": 1.0, "feed": 100.0, "refine_feed": 25.0, "touches": 2, "backoff": 1.0, "travel": 10.0, "clearance": 20.0, "z": 0.0, "depth": 5.0, "approach": 8.0, "rounds": 2}

SPECIFIC = {
    "surface": {"axis": "x", "direction": 1, "x": 0.0, "y": 0.0, "nominal": 0.0},
    "edge": {"axis": "x", "direction": 1, "x": -10.0, "y": 0.0, "nominal": 0.0},
    "bore": {"cx": 0.0, "cy": 0.0, "diameter": 20.0},
    "boss": {"cx": 0.0, "cy": 0.0, "diameter": 20.0},
    "width": {"axis": "x", "cx": 0.0, "cy": 0.0, "width": 20.0, "inside": True},
    "corner": {"cx": 0.0, "cy": 0.0, "qx": 1, "qy": 1, "offset": 10.0},
    "skew": {"axis": "x", "direction": 1, "x": -10.0, "y": 0.0, "span": 40.0, "nominal": 0.0},
}

LIMITS = {"radius": (0.05, 20.0), "feed": (1.0, 5000.0), "refine_feed": (1.0, 5000.0), "backoff": (0.1, 20.0), "travel": (0.5, 200.0), "clearance": (-1000.0, 1000.0), "depth": (0.0, 500.0), "approach": (1.0, 100.0), "span": (1.0, 2000.0), "offset": (0.0, 1000.0), "diameter": (0.1, 2000.0), "width": (0.1, 2000.0)}


def defaults(kind: str) -> dict:
    if kind not in KINDS:
        raise ProbeError("A probing cycle is one of %s." % ", ".join(KINDS))
    d = dict(COMMON)
    d.update(SPECIFIC[kind])
    return d


def clean(kind: str, raw: dict) -> dict:
    p = defaults(kind)
    for k, v in (raw or {}).items():
        if k not in p:
            raise ProbeError("The %s cycle has no parameter called %s." % (kind, k))
        p[k] = v
    for k, v in p.items():
        if isinstance(p[k], bool) or k in ("axis", "update", "inside"):
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
            raise ProbeError("%s needs a number." % k)
        p[k] = float(v) if not isinstance(defaults(kind)[k], int) or k in ("cx", "cy") else v
        if k in LIMITS and not LIMITS[k][0] <= float(p[k]) <= LIMITS[k][1]:
            raise ProbeError("%s must be between %g and %g." % (k, LIMITS[k][0], LIMITS[k][1]))
    p["slot"] = int(p["slot"])
    if not 1 <= p["slot"] <= 9:
        raise ProbeError("The work offset slot is 1 to 9.")
    p["touches"] = int(p["touches"])
    p["rounds"] = int(p["rounds"])
    if p["touches"] not in (1, 2):
        raise ProbeError("Touches is 1 or 2.")
    if p["rounds"] not in (1, 2):
        raise ProbeError("Rounds is 1 or 2.")
    if "axis" in p and p["axis"] not in ("x", "y", "z"):
        raise ProbeError("The axis is x, y or z.")
    if kind in ("skew", "width") and p["axis"] == "z":
        raise ProbeError("%s works in the XY plane: axis x or y." % kind)
    for k in ("direction", "qx", "qy"):
        if k in p and p[k] not in (1, -1, 1.0, -1.0):
            raise ProbeError("%s is 1 or -1." % k)
        if k in p:
            p[k] = int(p[k])
    if p["refine_feed"] > p["feed"]:
        raise ProbeError("The refine feed is above the first feed.")
    return p


def offset_param(slot: int, axis: str) -> str:
    base = 5221 + 20 * (slot - 1)
    return "p%d" % (base + {"x": 0, "y": 1, "z": 2, "r": 9}[axis])


class Prog:
    def __init__(self, p):
        self.p = p
        self.m = []
        self.n = 0
        self.pos = None
        self.notes = []
        self.outputs = {}

    def comment(self, t):
        self.m.append(["comment", t])

    def rapid(self, x, y, z, k="link", expr=None):
        o = {"k": k}
        if expr:
            o["expr"] = expr
        self.m.append(["rapid", float(x), float(y), float(z), o])
        self.pos = (x, y, z)

    def feed(self, x, y, z, f, k="link", expr=None):
        o = {"k": k}
        if expr:
            o["expr"] = expr
        self.m.append(["feed", float(x), float(y), float(z), float(f), o])
        self.pos = (x, y, z)

    def probe(self, x, y, z, f, name, mode="toward", expr=None):
        o = {"k": "probe", "probe": MODES[mode], "store": name}
        if expr:
            o["expr"] = expr
        self.m.append(["feed", float(x), float(y), float(z), float(f), o])
        self.pos = (x, y, z)

    def param(self, name, expression):
        E.to_ngc(expression)
        self.m.append(["param", name, expression])

    def wcs_set(self, slot, sets):
        for v in sets.values():
            E.to_ngc(v)
        self.m.append(["wcs_set", int(slot), dict(sets)])
        self.m.append(["wcs", int(slot)])

    def out(self, name, expression, label, unit="mm"):
        self.param(name, expression)
        self.outputs[name] = {"expr": expression, "label": label, "unit": unit}

    def touch(self, name, start, direction_vec, travel, sexpr=None):
        p = self.p
        sx, sy, sz = start
        dv = direction_vec
        target = (sx + dv[0] * travel, sy + dv[1] * travel, sz + dv[2] * travel)
        texpr = None
        if sexpr:
            texpr = {}
            for i, ax in enumerate("xyz"):
                if ax in sexpr:
                    texpr[ax] = plus(sexpr[ax], dv[i] * travel)
        self.probe(target[0], target[1], target[2], p["feed"], name, expr=texpr)
        if p["touches"] == 2:
            b = p["backoff"]
            back = {ax: plus("%s_%s" % (name, ax), -dv[i] * b) for i, ax in enumerate("xyz")}
            fwd = {ax: plus("%s_%s" % (name, ax), dv[i] * b) for i, ax in enumerate("xyz")}
            self.rapid(target[0] - dv[0] * b, target[1] - dv[1] * b, target[2] - dv[2] * b, "retract", back)
            self.probe(target[0] + dv[0] * b, target[1] + dv[1] * b, target[2] + dv[2] * b, p["refine_feed"], name, expr=fwd)
        self.rapid(sx, sy, sz, "retract", sexpr)


def plus(e, v):
    v = float(v)
    if abs(v) < 1e-12:
        return e
    return "%s + %s" % (e, repr(v)) if v > 0 else "%s - %s" % (e, repr(-v))


def axis_vec(axis, s):
    return {"x": (s, 0, 0), "y": (0, s, 0), "z": (0, 0, s)}[axis]


def surface(p, edge=False):
    g = Prog(p)
    ax = p["axis"]
    s = p["direction"]
    r = p["radius"]
    if ax == "z":
        start = (p["x"], p["y"], p["clearance"])
    else:
        start = (p["x"], p["y"], p["z"] - p["depth"])
    g.comment("Probe surface %s%s" % ("+" if s > 0 else "-", ax.upper()))
    if ax != "z":
        g.rapid(start[0], start[1], p["clearance"], "approach")
        g.rapid(start[0], start[1], start[2], "approach")
    else:
        g.rapid(start[0], start[1], start[2], "approach")
    g.touch("c1", start, axis_vec(ax, s), p["travel"])
    g.out("surface_" + ax, "c1_%s + %g" % (ax, s * r), "Measured surface %s" % ax.upper())
    g.out("error_" + ax, "surface_%s - %g" % (ax, p["nominal"]), "Error against nominal %s" % ax.upper())
    if p["update"]:
        g.param("old_" + ax, offset_param(p["slot"], ax))
        g.wcs_set(p["slot"], {ax: "old_%s + error_%s" % (ax, ax)})
    if ax != "z":
        g.rapid(start[0], start[1], p["clearance"], "retract")
    return g


def bore(p):
    g = Prog(p)
    r = p["radius"]
    zp = p["z"] - p["depth"]
    g.comment("Probe bore")
    cx, cy = p["cx"], p["cy"]
    g.rapid(cx, cy, p["clearance"], "approach")
    g.rapid(cx, cy, zp, "approach")
    reach = p["diameter"] / 2.0 + p["travel"]
    names = ("c1", "c2", "c3", "c4")
    for rnd in range(p["rounds"]):
        sfx = "" if rnd == 0 else "b"
        sexpr = None
        if rnd == 1:
            sexpr = {"x": "xc", "y": "yc"}
            g.rapid(cx, cy, zp, "link", sexpr)
        for i, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
            g.touch(names[i] + sfx, (cx, cy, zp), (dx, dy, 0), reach, sexpr)
        cn = [n + sfx for n in names]
        g.param("xc", "(%s_x + %s_x) / 2" % (cn[0], cn[1]))
        g.param("yc", "(%s_y + %s_y) / 2" % (cn[2], cn[3]))
    last = ["c1b", "c2b", "c3b", "c4b"] if p["rounds"] == 2 else ["c1", "c2", "c3", "c4"]
    g.out("center_x", "xc", "Bore centre X")
    g.out("center_y", "yc", "Bore centre Y")
    g.out("diameter_x", "%s_x - %s_x + %g" % (last[0], last[1], 2 * r), "Bore diameter along X")
    g.out("diameter_y", "%s_y - %s_y + %g" % (last[2], last[3], 2 * r), "Bore diameter along Y")
    g.out("diameter", "(diameter_x + diameter_y) / 2", "Bore diameter")
    g.out("error_x", "center_x - %g" % cx, "Centre error X")
    g.out("error_y", "center_y - %g" % cy, "Centre error Y")
    if p["update"]:
        g.param("old_x", offset_param(p["slot"], "x"))
        g.param("old_y", offset_param(p["slot"], "y"))
        g.wcs_set(p["slot"], {"x": "old_x + error_x", "y": "old_y + error_y"})
    g.rapid(cx, cy, p["clearance"], "retract")
    return g


def boss(p):
    g = Prog(p)
    r = p["radius"]
    zp = p["z"] - p["depth"]
    cx, cy = p["cx"], p["cy"]
    R = p["diameter"] / 2.0
    ap = R + p["approach"]
    g.comment("Probe boss")
    for rnd in range(p["rounds"]):
        sfx = "" if rnd == 0 else "b"
        for i, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
            nm = ("c1", "c2", "c3", "c4")[i] + sfx
            sx, sy = cx - dx * ap, cy - dy * ap
            sexpr = None
            if rnd == 1:
                sexpr = {"x": plus("xc", -dx * ap), "y": plus("yc", -dy * ap)}
            g.rapid(sx, sy, p["clearance"], "approach", sexpr)
            g.rapid(sx, sy, zp, "approach", sexpr)
            g.touch(nm, (sx, sy, zp), (dx, dy, 0), p["approach"] + p["travel"], sexpr)
            g.rapid(sx, sy, p["clearance"], "retract", sexpr)
        cn = [n + sfx for n in ("c1", "c2", "c3", "c4")]
        g.param("xc", "(%s_x + %s_x) / 2" % (cn[0], cn[1]))
        g.param("yc", "(%s_y + %s_y) / 2" % (cn[2], cn[3]))
    last = ["c1b", "c2b", "c3b", "c4b"] if p["rounds"] == 2 else ["c1", "c2", "c3", "c4"]
    g.out("center_x", "xc", "Boss centre X")
    g.out("center_y", "yc", "Boss centre Y")
    g.out("diameter_x", "%s_x - %s_x - %g" % (last[1], last[0], 2 * r), "Boss diameter along X")
    g.out("diameter_y", "%s_y - %s_y - %g" % (last[3], last[2], 2 * r), "Boss diameter along Y")
    g.out("diameter", "(diameter_x + diameter_y) / 2", "Boss diameter")
    g.out("error_x", "center_x - %g" % cx, "Centre error X")
    g.out("error_y", "center_y - %g" % cy, "Centre error Y")
    if p["update"]:
        g.param("old_x", offset_param(p["slot"], "x"))
        g.param("old_y", offset_param(p["slot"], "y"))
        g.wcs_set(p["slot"], {"x": "old_x + error_x", "y": "old_y + error_y"})
    g.rapid(cx, cy, p["clearance"], "retract")
    return g


def width(p):
    g = Prog(p)
    r = p["radius"]
    zp = p["z"] - p["depth"]
    ax = p["axis"]
    cx, cy = p["cx"], p["cy"]
    half = p["width"] / 2.0
    other = "y" if ax == "x" else "x"
    g.comment("Probe %s width along %s" % ("slot" if p["inside"] else "web", ax.upper()))
    c0 = cx if ax == "x" else cy
    fixed = cy if ax == "x" else cx

    def at(a_val):
        return (a_val, fixed, zp) if ax == "x" else (fixed, a_val, zp)

    if p["inside"]:
        s = at(c0)
        g.rapid(s[0], s[1], p["clearance"], "approach")
        g.rapid(s[0], s[1], zp, "approach")
        reach = half + p["travel"]
        t1 = at(c0 + reach)
        t2 = at(c0 - reach)
        g.touch("c1", s, axis_vec(ax, 1), reach)
        g.touch("c2", s, axis_vec(ax, -1), reach)
        g.out("center", "(c1_%s + c2_%s) / 2" % (ax, ax), "Slot centre %s" % ax.upper())
        g.out("width", "c1_%s - c2_%s + %g" % (ax, ax, 2 * r), "Slot width")
    else:
        ap = half + p["approach"]
        s1 = at(c0 - ap)
        s2 = at(c0 + ap)
        reach = p["approach"] + p["travel"]
        g.rapid(s1[0], s1[1], p["clearance"], "approach")
        g.rapid(s1[0], s1[1], zp, "approach")
        g.touch("c1", s1, axis_vec(ax, 1), reach)
        g.rapid(s1[0], s1[1], p["clearance"], "retract")
        g.rapid(s2[0], s2[1], p["clearance"], "approach")
        g.rapid(s2[0], s2[1], zp, "approach")
        g.touch("c2", s2, axis_vec(ax, -1), reach)
        g.out("center", "(c1_%s + c2_%s) / 2" % (ax, ax), "Web centre %s" % ax.upper())
        g.out("width", "c2_%s - c1_%s - %g" % (ax, ax, 2 * r), "Web width")
    g.out("error", "center - %g" % c0, "Centre error %s" % ax.upper())
    if p["update"]:
        g.param("old_" + ax, offset_param(p["slot"], ax))
        g.wcs_set(p["slot"], {ax: "old_%s + error" % ax})
    g.rapid(cx, cy, p["clearance"], "retract")
    return g


def corner(p):
    g = Prog(p)
    r = p["radius"]
    zp = p["z"] - p["depth"]
    cx, cy = p["cx"], p["cy"]
    qx, qy = p["qx"], p["qy"]
    ap = p["approach"]
    off = p["offset"]
    g.comment("Probe corner")
    sx = (cx - qx * ap, cy + qy * off, zp)
    g.rapid(sx[0], sx[1], p["clearance"], "approach")
    g.rapid(sx[0], sx[1], zp, "approach")
    g.touch("c1", sx, axis_vec("x", qx), ap + p["travel"])
    g.rapid(sx[0], sx[1], p["clearance"], "retract")
    sy = (cx + qx * off, cy - qy * ap, zp)
    g.rapid(sy[0], sy[1], p["clearance"], "approach")
    g.rapid(sy[0], sy[1], zp, "approach")
    g.touch("c2", sy, axis_vec("y", qy), ap + p["travel"])
    g.rapid(sy[0], sy[1], p["clearance"], "retract")
    g.out("corner_x", "c1_x + %g" % (qx * r), "Corner X")
    g.out("corner_y", "c2_y + %g" % (qy * r), "Corner Y")
    g.out("error_x", "corner_x - %g" % cx, "Error X")
    g.out("error_y", "corner_y - %g" % cy, "Error Y")
    if p["update"]:
        g.param("old_x", offset_param(p["slot"], "x"))
        g.param("old_y", offset_param(p["slot"], "y"))
        g.wcs_set(p["slot"], {"x": "old_x + error_x", "y": "old_y + error_y"})
    return g


def skew(p):
    g = Prog(p)
    r = p["radius"]
    ax = p["axis"]
    s = p["direction"]
    zp = p["z"] - p["depth"]
    g.comment("Probe skew")
    along = "y" if ax == "x" else "x"
    a1 = (p["x"], p["y"], zp)
    a2 = (p["x"], p["y"] + p["span"], zp) if ax == "x" else (p["x"] + p["span"], p["y"], zp)
    for nm, st in (("c1", a1), ("c2", a2)):
        g.rapid(st[0], st[1], p["clearance"], "approach")
        g.rapid(st[0], st[1], zp, "approach")
        g.touch(nm, st, axis_vec(ax, s), p["travel"])
        g.rapid(st[0], st[1], p["clearance"], "retract")
    g.out("surface_1", "c1_%s + %g" % (ax, s * r), "Surface at the first point")
    g.out("surface_2", "c2_%s + %g" % (ax, s * r), "Surface at the second point")
    if ax == "x":
        g.out("angle", "0 - atan2(surface_2 - surface_1, %g)" % p["span"], "Skew angle (counter-clockwise positive)", "deg")
    else:
        g.out("angle", "atan2(surface_2 - surface_1, %g)" % p["span"], "Skew angle (counter-clockwise positive)", "deg")
    if p["update"]:
        g.wcs_set(p["slot"], {"r": "angle"})
    return g


def build(kind: str, raw: dict) -> dict:
    p = clean(kind, raw)
    fn = {"surface": lambda q: surface(q), "edge": lambda q: surface(q, True), "bore": bore, "boss": boss, "width": width, "corner": corner, "skew": skew}[kind]
    g = fn(p)
    return {"kind": kind, "params": p, "moves": g.m, "outputs": g.outputs}
