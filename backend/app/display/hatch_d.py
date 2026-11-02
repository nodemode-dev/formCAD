from app.display import palette
from app.display.shapes import box, builder
from app.doc import hatchfill as H
from app.doc import patterns

FILL_ARC_STEP = 0.05


def _rgb_of(value, fallback):
    if value is None:
        return list(fallback), False
    rgb, c7 = palette.resolve(value, 7, None)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and int(value) in (0, 256):
        return list(fallback), False
    return list(rgb), bool(c7)


def _tri_prim(pts, color=None, c7=False, lod=False):
    p = {"t": "tri", "pts": [round(v, 6) for v in pts]}
    if color is not None:
        p["c"] = list(color)
        if c7:
            p["c7"] = True
    if lod:
        p["lod"] = "solid"
    return p


def loop_parts(e):
    parts = []
    for loop in e.loops:
        verts = loop.get("vertices", [])
        if len(verts) >= 2:
            parts.append({"type": "poly", "verts": [[float(v["p"][0]), float(v["p"][1]), float(v.get("bulge", 0.0) or 0.0), 0.0, 0.0] for v in verts], "closed": True, "elev": 0.0})
    return parts


def gradient_prims(e, rings, fallback):
    g = e.gradient
    name = str(g.get("name", "LINEAR")).upper()
    if name not in H.GRADIENT_NAMES:
        name = "LINEAR"
    c1, c1_7 = _rgb_of(g.get("color1"), fallback)
    if g.get("one") or g.get("color2") is None:
        c2 = H.tinted(c1, float(g.get("tint", 1.0)))
        c2_7 = False
    else:
        c2, c2_7 = _rgb_of(g.get("color2"), fallback)
    angle = float(g.get("angle", 0.0) or 0.0)
    groups = H.gradient_groups(rings, name, angle, bool(g.get("centered", True)))
    prims = [_tri_prim(H.fill_triangles(rings), H.lerp_color(c1, c2, 0.5))]
    for idx in sorted(groups):
        t = idx / float(H.STEPS - 1)
        c7 = (c1_7 and t < 0.01) or (c2_7 and t > 0.99)
        prims.append(_tri_prim(groups[idx], H.lerp_color(c1, c2, t), c7))
    return prims


def pattern_prims(e, rings, ctx, fallback):
    prims = []
    if e.background is not None:
        col, c7 = _rgb_of(e.background, fallback)
        prims.append(_tri_prim(H.fill_triangles(rings), col, c7))
    fams = patterns.families_of(e)
    unit = patterns.scale_unit(ctx.metric)
    scale = float(e.pattern_scale) if e.pattern_scale else 1.0
    if getattr(e, "annotative", False):
        try:
            scale *= ctx.d.scale_value(str(ctx.d.header.get("CANNOSCALE", "1:1")))
        except Exception:
            pass
    origin = H.resolve_origin(e.origin, getattr(e, "origin_mode", "current"), rings)
    segs, dense = H.pattern_segments(rings, fams, scale, float(e.pattern_angle), origin, unit, H.DISPLAY_RUNS)
    if dense:
        prims.append(_tri_prim(H.fill_triangles(rings), None, False, True))
        return prims
    for row in segs.round(6).tolist():
        prims.append({"t": "pl", "pts": row, "closed": False})
    return prims


@builder("hatch")
def hatch(e, ctx):
    rings = H.rings_of(e.loops, FILL_ARC_STEP)
    parts = loop_parts(e)
    prims = []
    allp = [p for r in rings for p in r]
    pp = ctx.props(e)
    fallback = pp.rgb
    if rings:
        if e.gradient:
            if ctx.fillmode:
                prims = gradient_prims(e, rings, fallback)
        elif e.solid or patterns.is_solid(e.pattern):
            if ctx.fillmode:
                prims = [_tri_prim(H.fill_triangles(rings))]
        else:
            prims = pattern_prims(e, rings, ctx, fallback)
    return {"type": "compound", "parts": parts}, prims, [], box(allp)


@builder("region")
def region(e, ctx):
    rings = H.rings_of(e.loops, FILL_ARC_STEP)
    allp = [p for r in rings for p in r]
    return {"type": "compound", "parts": loop_parts(e)}, [], [], box(allp)
