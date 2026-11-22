from app.display import palette
from app.display.insert import part_props
from app.display.shapes import builder, grip_list, xy
from app.doc.entities import Line
from app.doc.kinds import mline as ML


def _box(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


@builder("helix")
def helix(e, ctx):
    ctrl = [xy(p) for p in e.control_points]
    knots = [float(k) for k in e.knots]
    g = {"type": "spline", "degree": int(e.degree), "knots": knots, "ctrl": ctrl, "weights": None, "fit": None, "closed": False}
    c = xy(e.center)
    r = max(abs(float(e.base_radius)), abs(float(e.top_radius)))
    top = ctrl[-1] if ctrl else c
    grips = [(c, "cen"), (xy(ctrl[0]) if ctrl else c, "end"), (xy(top), "end")]
    bb = [c[0] - r, c[1] - r, c[0] + r, c[1] + r]
    return g, [], grip_list(grips), bb


@builder("wipeout")
def wipeout(e, ctx):
    pts = [xy(p) for p in e.points]
    mode = int(ctx.d.header.get("WIPEOUTFRAME", 1)) if e.frame is None else int(e.frame)
    verts = [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts]
    parts = [{"type": "poly", "verts": verts, "closed": True, "elev": 0.0}] if mode > 0 else []
    prims = [{"t": "fill", "rings": [[v for p in pts for v in p]], "mask": True}] if len(pts) >= 3 else []
    return {"type": "compound", "parts": parts}, prims, grip_list([(p, "vtx") for p in pts]), _box(pts)


@builder("underlay")
def underlay(e, ctx):
    from app.doc import underlays as U

    full = U.resolve(e.path, U.folder_of(ctx.doc))
    found = bool(full) and U.kind_of(full) in (("pdf",) if e.source == "pdf" else ("png", "jpeg"))
    ring = e.clip_ring() or e.outline()
    flat = [v for p in ring for v in xy(p)]
    mode = int(ctx.d.header.get("PDFFRAME" if e.source == "pdf" else "IMAGEFRAME", 1))
    if not found:
        mode = 1
    verts = [[p[0], p[1], 0.0, 0.0, 0.0] for p in ring]
    parts = [{"type": "poly", "verts": verts, "closed": True, "elev": 0.0}] if mode == 1 else []
    prims = []
    if mode == 2:
        prims.append({"t": "pl", "pts": flat + flat[:2], "noplot": True})
    if found and e.show:
        o, r, t = (xy(p) for p in e.corners)
        clip = e.clip_ring()
        prims.append({"t": "img", "pts": o + r + t, "clip": [v for p in clip for v in xy(p)] if clip else None, "fade": int(e.fade), "v": "%s-%d" % (U.stamp(full), int(e.page))})
    return {"type": "compound", "parts": parts}, prims, grip_list([(xy(e.corners[0]), "ins")]), _box([xy(p) for p in ring])


def _flat(points):
    return [v for p in points for v in p]


@builder("mline")
def mline(e, ctx):
    pp = ctx.props(e)
    parts = []
    allp = []
    els = e.elements()
    for k, runs in enumerate(ML.element_runs(e)):
        spec = els[k]
        probe = Line(layer=e.layer, color=0 if spec.get("color", 256) in (256, 0) else spec["color"], linetype="ByBlock" if str(spec.get("linetype", "BYLAYER")).upper() == "BYLAYER" else spec["linetype"], lineweight=-2)
        cp = ctx.props(probe, pp)
        for run in runs:
            if len(run["pts"]) < 2:
                continue
            allp.extend(run["pts"])
            part = {"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in run["pts"]], "closed": run["closed"], "elev": 0.0}
            parts.append(part_props(part, cp))
    for kind, a, b, sign in ML.cap_shapes(e):
        allp.extend([a, b])
        verts = [[a[0], a[1], sign if kind == "arc" else 0.0, 0.0, 0.0], [b[0], b[1], 0.0, 0.0, 0.0]]
        parts.append(part_props({"type": "poly", "verts": verts, "closed": False, "elev": 0.0}, pp))
    for a, b in ML.joint_lines(e):
        parts.append(part_props({"type": "line", "p1": [a[0], a[1]], "p2": [b[0], b[1]]}, pp))
    prims = []
    ring = ML.fill_ring(e)
    if ring and ctx.fillmode:
        prims.append({"t": "fill", "rings": [_flat(r) for r in ring], "c": _fill_rgb(e)})
    grips = [(xy(v["p"]), "vtx") for v in e.vertices]
    bb = _box(allp) or _box([v["p"] for v in e.vertices])
    return {"type": "compound", "parts": parts}, prims, grip_list(grips), bb


def _fill_rgb(e):
    rgb, _c7 = palette.resolve(e.style_def.get("fill"), 7, None)
    return list(rgb)
