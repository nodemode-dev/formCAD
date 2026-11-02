import math

from app.display import flatten
from app.doc import geom as G
from app.text import fonts, mtext, single

BUILDERS = {}
ELLIPSE_FALLBACK_STEPS = 96


def builder(kind):
    def wrap(fn):
        BUILDERS[kind] = fn
        return fn

    return wrap


def xy(p):
    return [float(p[0]), float(p[1])]


def box(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def grip_list(items):
    return [{"id": i, "p": [p[0], p[1]], "kind": k} for i, (p, k) in enumerate(items)]


def _b(t):
    return [float(t[0]), float(t[1]), float(t[2]), float(t[3])] if t else None


@builder("line")
def line(e, ctx):
    p1, p2 = xy(e.start), xy(e.end)
    mid = [(p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0]
    return {"type": "line", "p1": p1, "p2": p2}, [], grip_list([(p1, "end"), (p2, "end"), (mid, "mid")]), [min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])]


@builder("circle")
def circle(e, ctx):
    c, r = xy(e.center), float(e.radius)
    g = {"type": "circle", "c": c, "r": r}
    quad = [([c[0] + r, c[1]], "quad"), ([c[0], c[1] + r], "quad"), ([c[0] - r, c[1]], "quad"), ([c[0], c[1] - r], "quad")]
    return g, [], grip_list([(c, "cen")] + quad), [c[0] - r, c[1] - r, c[0] + r, c[1] + r]


@builder("arc")
def arc(e, ctx):
    c, r = xy(e.center), float(e.radius)
    a0, a1 = float(e.start_angle), float(e.end_angle)
    sweep = G.ccw_sweep(a0, a1)
    mid = a0 + sweep / 2.0
    pts = [([c[0] + r * math.cos(a0), c[1] + r * math.sin(a0)], "end"), ([c[0] + r * math.cos(mid), c[1] + r * math.sin(mid)], "mid"), ([c[0] + r * math.cos(a1), c[1] + r * math.sin(a1)], "end"), (c, "cen")]
    return {"type": "arc", "c": c, "r": r, "a0": a0, "a1": a1}, [], grip_list(pts), _b(G.arc_bounds(c, r, a0, a1))


@builder("ellipse")
def ellipse(e, ctx):
    c = xy(e.center)
    major = xy(e.major)
    ratio = float(e.ratio)
    g = {"type": "ellipse", "c": c, "major": major, "ratio": ratio, "a0": float(e.start_param), "a1": float(e.end_param)}
    minor = [-major[1] * ratio, major[0] * ratio]
    grips = [(c, "cen"), ([c[0] + major[0], c[1] + major[1]], "quad"), ([c[0] - major[0], c[1] - major[1]], "quad"), ([c[0] + minor[0], c[1] + minor[1]], "quad"), ([c[0] - minor[0], c[1] - minor[1]], "quad")]
    pts = flatten.ellipse_pts(c, major, ratio, g["a0"], g["a1"], ELLIPSE_FALLBACK_STEPS)
    return g, [], grip_list(grips), box(pts)


def _widths(e, v):
    sw = float(v.get("sw", 0.0) or 0.0)
    ew = float(v.get("ew", 0.0) or 0.0)
    cw = float(getattr(e, "const_width", 0.0) or 0.0)
    if sw == 0.0 and ew == 0.0 and cw > 0.0:
        return cw, cw
    return sw, ew


def band_rings(verts, closed):
    rings = []
    n = len(verts)
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        pts = flatten.bulge_pts(a, b, a[2])
        total = sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(len(pts) - 1)) or 1.0
        run = 0.0
        for k in range(len(pts) - 1):
            p, q = pts[k], pts[k + 1]
            seg = math.hypot(q[0] - p[0], q[1] - p[1])
            if seg < 1e-12:
                continue
            w0 = a[3] + (a[4] - a[3]) * run / total
            run += seg
            w1 = a[3] + (a[4] - a[3]) * run / total
            if w0 <= 0 and w1 <= 0:
                continue
            ux, uy = (q[0] - p[0]) / seg, (q[1] - p[1]) / seg
            nx, ny = -uy, ux
            rings.append([p[0] + nx * w0 / 2, p[1] + ny * w0 / 2, q[0] + nx * w1 / 2, q[1] + ny * w1 / 2, q[0] - nx * w1 / 2, q[1] - ny * w1 / 2, p[0] - nx * w0 / 2, p[1] - ny * w0 / 2])
    return rings


@builder("lwpolyline")
def lwpolyline(e, ctx):
    verts = []
    for v in e.vertices:
        sw, ew = _widths(e, v)
        verts.append([float(v["p"][0]), float(v["p"][1]), float(v.get("bulge", 0.0) or 0.0), sw, ew])
    g = {"type": "poly", "verts": verts, "closed": bool(e.closed), "elev": float(e.elevation)}
    prims = []
    if ctx.fillmode and any(v[3] > 0 or v[4] > 0 for v in verts):
        rings = band_rings(verts, bool(e.closed))
        if rings:
            prims.append({"t": "fill", "rings": rings})
    pts = flatten.poly_pts(verts, bool(e.closed))
    grips = [(xy(v), "vtx") for v in verts]
    n = len(verts)
    for i in range(n if e.closed else n - 1):
        a, b = verts[i], verts[(i + 1) % n]
        grips.append(([(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0], "mid"))
    bb = box(pts)
    if prims:
        extra = [(p[0], p[1]) for r in prims[0]["rings"] for p in zip(r[0::2], r[1::2])]
        bb = box(pts + extra)
    return g, prims, grip_list(grips), bb


@builder("polyline3d")
def polyline3d(e, ctx):
    verts = [[float(p[0]), float(p[1]), 0.0, 0.0, 0.0] for p in e.points]
    g = {"type": "poly", "verts": verts, "closed": bool(e.closed), "elev": 0.0}
    return g, [], grip_list([(xy(p), "vtx") for p in e.points]), box(verts)


def _clamped_knots(n_ctrl, degree):
    n = n_ctrl + degree + 1
    inner = n_ctrl - degree - 1
    return [0.0] * (degree + 1) + [float(i + 1) for i in range(max(inner, 0))] + [float(max(inner, 0) + 1)] * (degree + 1)


def _catmull(points, closed, per=12):
    pts = [xy(p) for p in points]
    if len(pts) < 3:
        return pts
    ext = pts[:]
    if closed:
        ext = [pts[-1]] + pts + [pts[0], pts[1]]
    else:
        ext = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for k in range(per):
            t = k / per
            t2, t3 = t * t, t * t * t
            out.append([0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(2)])
    out.append(pts[0] if closed else pts[-1])
    return out


@builder("spline")
def spline(e, ctx):
    ctrl = [xy(p) for p in e.control_points]
    fit = [xy(p) for p in e.fit_points]
    knots = [float(k) for k in e.knots]
    degree = int(e.degree)
    if ctrl and len(knots) != len(ctrl) + degree + 1 and not e.closed:
        knots = _clamped_knots(len(ctrl), degree)
    weights = [float(w) for w in e.weights] if e.weights and len(e.weights) == len(ctrl) else None
    g = {"type": "spline", "degree": degree, "knots": knots, "ctrl": ctrl, "weights": weights, "fit": fit or None, "closed": bool(e.closed)}
    prims = []
    base = ctrl or fit
    if not ctrl and fit:
        curve = _catmull(fit, bool(e.closed))
        prims.append({"t": "pl", "pts": flatten.flat_xy(curve), "closed": False})
        base = curve
    grips = [(p, "fit" if not ctrl else "ctrl") for p in (fit if not ctrl else ctrl)]
    return g, prims, grip_list(grips), box(base)


def _unit(d):
    m = math.hypot(d[0], d[1])
    if m < 1e-12:
        return [1.0, 0.0]
    return [d[0] / m, d[1] / m]


@builder("ray")
def ray(e, ctx):
    p = xy(e.base)
    return {"type": "ray", "p": p, "dir": _unit(e.direction)}, [], grip_list([(p, "ins")]), [p[0], p[1], p[0], p[1]]


@builder("xline")
def xline(e, ctx):
    p = xy(e.base)
    return {"type": "xline", "p": p, "dir": _unit(e.direction)}, [], grip_list([(p, "ins")]), [p[0], p[1], p[0], p[1]]


@builder("point")
def point(e, ctx):
    p = xy(e.position)
    size = ctx.pdsize
    g = {"type": "point", "p": p, "mode": ctx.pdmode, "size": size if size > 0 else 0.0, "rel": (abs(size) if size < 0 else 5.0) if size <= 0 else 0.0, "rot": float(e.angle)}
    return g, [], grip_list([(p, "ins")]), [p[0], p[1], p[0], p[1]]


_FACES = {}


def fontset(ctx, style_name):
    rec = ctx.textstyle(style_name)
    key = str(rec.get("font", "txt")).casefold()
    fs = _FACES.get(key)
    if fs is None:
        fs = fonts.FontSet(fonts.resolve(rec.get("font", "txt")))
        if len(_FACES) > 64:
            _FACES.clear()
        _FACES[key] = fs
    return rec, fs


def reset_fonts():
    _FACES.clear()


def _laid_result(laid, e, ctx):
    ins = [laid.origin[0], laid.origin[1]]
    g = {"type": "text", "insert": ins, "height": laid.height, "rot": float(e.rotation), "box": [[float(p[0]), float(p[1])] for p in laid.box]}
    bb = laid.bounds
    pts = laid.box
    allp = list(pts)
    if bb:
        allp += [(bb[0], bb[1]), (bb[2], bb[3])]
    return g, laid.prims, grip_list([(ins, "ins")]), box(allp)


@builder("text")
def text(e, ctx):
    rec, fs = fontset(ctx, e.style)
    height = float(rec.get("height") or 0.0) or float(e.height)
    wf = float(e.width_factor or 1.0) * float(rec.get("width_factor", 1.0) or 1.0)
    obl = float(e.oblique or 0.0) + float(rec.get("oblique", 0.0) or 0.0)
    pos = xy(e.position)
    ap = xy(e.align_point) if e.align_point else None
    laid = single.layout(fs, e.text or "", height, wf, obl, bool(rec.get("backwards")), bool(rec.get("upside_down")), int(e.halign), int(e.valign), pos, ap, float(e.rotation), bool(ctx.textfill), bool(rec.get("vertical")))
    return _laid_result(laid, e, ctx)


@builder("mtext")
def mtext_kind(e, ctx):
    rec, fs = fontset(ctx, e.style)
    height = float(rec.get("height") or 0.0) or float(e.height)
    pos = xy(e.position)
    laid = mtext.layout(fs, e.contents or "", height, float(e.width or 0.0), int(e.attachment or 1), float(e.rotation), pos, float(e.line_spacing or 1.0), int(e.line_spacing_style or 1), e.columns or {}, float(rec.get("width_factor", 1.0) or 1.0), float(rec.get("oblique", 0.0) or 0.0), bool(ctx.textfill), fs.desc)
    return _laid_result(laid, e, ctx)


@builder("solid")
def solid(e, ctx):
    c = [xy(p) for p in e.corners]
    if len(c) == 4:
        order = [c[0], c[1], c[3], c[2]]
    else:
        order = c
    verts = [[p[0], p[1], 0.0, 0.0, 0.0] for p in order]
    g = {"type": "compound", "parts": [{"type": "poly", "verts": verts, "closed": True, "elev": 0.0}]}
    prims = []
    if ctx.fillmode and len(order) >= 3:
        prims.append({"t": "fill", "rings": [flatten.flat_xy(order)]})
    return g, prims, grip_list([(p, "vtx") for p in c]), box(order)


def hatch_rings(e):
    rings = []
    for loop in e.loops:
        verts = [[float(v["p"][0]), float(v["p"][1]), float(v.get("bulge", 0.0) or 0.0)] for v in loop.get("vertices", [])]
        if len(verts) >= 2:
            pts = flatten.poly_pts(verts, True)
            if len(pts) >= 3:
                rings.append(pts)
    return rings


@builder("hatch")
def hatch(e, ctx):
    rings = hatch_rings(e)
    parts = [{"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in r], "closed": True, "elev": 0.0} for r in rings]
    prims = []
    allp = [p for r in rings for p in r]
    if e.solid or str(e.pattern).upper() == "SOLID":
        if ctx.fillmode and rings:
            prims.append({"t": "fill", "rings": [flatten.flat_xy(r) for r in rings]})
    elif rings:
        name = str(e.pattern).upper()
        base = {"ANSI31": 45.0, "ANSI32": 45.0, "ANSI33": 45.0, "ANSI34": 45.0, "ANSI35": 45.0, "ANSI36": 45.0, "ANSI37": 45.0, "ANSI38": 45.0, "LINE": 0.0, "NET": 0.0, "NET3": 0.0, "ANGLE": 0.0, "STEEL": 45.0, "ESCHER": 45.0}.get(name, 45.0)
        unit = 3.175 if ctx.metric else 0.125
        spacing = unit * (float(e.pattern_scale) or 1.0)
        ang = math.radians(base) + float(e.pattern_angle)
        segs = flatten.hatch_lines(rings, ang, spacing)
        if name in ("ANSI37", "NET", "NET3"):
            segs += flatten.hatch_lines(rings, ang + math.pi / 2.0, spacing)
        for s in segs:
            prims.append({"t": "pl", "pts": s, "closed": False})
    return {"type": "compound", "parts": parts}, prims, [], box(allp)


@builder("dimension")
def dimension(e, ctx):
    pts = [xy(p) for p in (e.def_point, e.text_point, e.p13, e.p14, e.p15, e.p16) if p]
    return {"type": "compound", "parts": []}, [], grip_list([(p, "ins") for p in pts[:2]]), box(pts)


dimension_base = dimension


def build(e, ctx):
    fn = BUILDERS.get(e.kind)
    if fn is None:
        return None
    return fn(e, ctx)
