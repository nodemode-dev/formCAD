import math

from app.display import palette, shapes
from app.display.insert import xf_geom, xf_prims
from app.display.shapes import builder
from app.doc import hatchfill as H
from app.doc import patterns
from app.text import single
from app.text.model import affine
from app.views import geom2d, model

TEXT_H_MM = 3.5
ARROW_MM = 3.0
MAX_PARTS = 60000


class Look:
    __slots__ = ("rgb", "c7", "lw", "lt")

    def __init__(self, rgb, c7, lw, lt):
        self.rgb, self.c7, self.lw, self.lt = rgb, c7, lw, lt


def look_for(ctx, layer: str, over: dict | None):
    rgb, c7, lw, lt_name, _tr, _plot = ctx.layer_props(layer)
    lt_use = lt_name
    if over:
        if over.get("color") not in (None, ""):
            rgb, c7 = palette.resolve(over["color"], 7, None)
        if over.get("lineweight") not in (None, ""):
            v = float(over["lineweight"])
            lw = ctx.lw_default if v < 0 else v / 100.0
        if over.get("linetype"):
            lt_use = over["linetype"]
    name, pat = ctx.lt_pattern(lt_use)
    lt = {"name": name, "pattern": pat, "scale": ctx.ltscale} if pat is not None else None
    return Look(list(rgb), c7, lw, lt)


def layer_on(ctx, name: str) -> bool:
    rec = ctx.layers.get(name)
    return rec is None or (rec.get("on", True) and not rec.get("frozen", False))


def stamp(part: dict, look) -> dict:
    part["color"] = list(look.rgb)
    part["color7"] = look.c7
    part["lw"] = look.lw
    part["lt"] = look.lt
    return part


def tag_of(look) -> dict:
    t = {"c": list(look.rgb)}
    if look.c7:
        t["c7"] = True
    return t


def text_prims(ctx, text: str, at, height: float, look, rot: float = 0.0):
    rec, fs = shapes.fontset(ctx, "Standard")
    wf = float(rec.get("width_factor", 1.0) or 1.0)
    obl = float(rec.get("oblique", 0.0) or 0.0)
    laid = single.layout(fs, text, float(height), wf, obl, False, False, 1, 2, tuple(at), tuple(at), rot, bool(ctx.textfill))
    tag = tag_of(look)
    out = []
    for pr in laid.prims:
        q = dict(pr)
        if "c" not in q and "ci" not in q:
            q.update(tag)
        out.append(q)
    return out, laid.bounds


def hatch_prims(ctx, e, faces, k: float, look):
    prims = []
    fams = patterns.LIBRARY["ANSI31"]
    unit = patterns.scale_unit(True) / (e.unit_mm or 1.0)
    for face in faces:
        rings_local = geom2d.rings(face)
        if not rings_local:
            continue
        rings = [[[e.position[0] + p[0] * k, e.position[1] + p[1] * k] for p in r] for r in rings_local]
        origin = rings[0][0]
        segs, dense = H.pattern_segments(rings, fams, 1.0, 0.0, origin, unit, H.DISPLAY_RUNS)
        if dense:
            continue
        tag = tag_of(look)
        for row in segs.round(6).tolist():
            pr = {"t": "pl", "pts": row, "closed": False}
            pr.update(tag)
            prims.append(pr)
    return prims


def arrow_ring(tip, direction, size):
    ux, uy = direction
    nx, ny = -uy, ux
    b = [tip[0] - ux * size, tip[1] - uy * size]
    return [tip[0], tip[1], b[0] + nx * size * 0.3, b[1] + ny * size * 0.3, b[0] - nx * size * 0.3, b[1] - ny * size * 0.3]


def parent_marks(ctx, e, parts, prims, pts):
    parent = ctx.d.ents.get(e.parent) if e.parent else None
    if parent is None or parent.kind != "drawview" or not e.show.get("label", True):
        return
    unit = parent.unit_mm or 1.0
    k = float(parent.scale) / unit
    px, py = parent.position
    look = look_for(ctx, model.LAYER_SECTION, None)
    lab = look_for(ctx, model.LAYER_LABEL, None)
    th = TEXT_H_MM / unit
    if e.section.get("points") and not e.section.get("inherit") and layer_on(ctx, model.LAYER_SECTION):
        line = e.section["line"]
        pts_p = [[px + p[0] * k, py + p[1] * k] for p in line]
        name, pat = ctx.lt_pattern("PHANTOM")
        lk = Look(look.rgb, look.c7, look.lw, {"name": name, "pattern": pat, "scale": ctx.ltscale} if pat is not None else look.lt)
        parts.append(stamp({"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts_p], "closed": False, "elev": 0.0}, lk))
        pts.extend(pts_p)
        x, y, _n = model.view_frame(parent)
        a = e.section["keep"]
        al = [model.dot(a, x), model.dot(a, y)]
        ln = math.hypot(al[0], al[1]) or 1.0
        al = [al[0] / ln, al[1] / ln]
        size = ARROW_MM / unit
        for end in (pts_p[0], pts_p[-1]):
            tip = [end[0] + al[0] * size * 2.0, end[1] + al[1] * size * 2.0]
            prims.append(dict({"t": "fill", "rings": [arrow_ring(tip, al, size)]}, **tag_of(look)))
            parts.append(stamp({"type": "line", "p1": end, "p2": tip}, look))
            tp, tb = text_prims(ctx, e.section.get("letter", ""), [tip[0] + al[0] * th * 1.2, tip[1] + al[1] * th * 1.2], th, lab)
            prims.extend(tp)
            pts.append(tip)
    if e.detail.get("radius") and layer_on(ctx, model.LAYER_SECTION):
        c = e.detail["center"]
        cx, cy, r = px + c[0] * k, py + c[1] * k, e.detail["radius"] * k
        parts.append(stamp({"type": "circle", "c": [cx, cy], "r": r}, look))
        pts.extend([[cx - r, cy - r], [cx + r, cy + r]])
        tp, tb = text_prims(ctx, e.detail.get("letter", ""), [cx + r * 0.75, cy + r * 0.75 + th], th, lab)
        prims.extend(tp)


@builder("drawview")
def drawview(e, ctx):
    cache = e.cache or {}
    classes = cache.get("classes") or {}
    unit = e.unit_mm or 1.0
    k = float(e.scale) / unit
    m = affine(k, 0.0, 0.0, k, e.position[0], e.position[1])
    parts = []
    prims = []
    pts = []
    count = 0
    for cls in model.CLASSES:
        recs = classes.get(cls) or []
        if not recs or not model.class_enabled(e.show, cls):
            continue
        over = (e.style or {}).get(cls) or {}
        layer = over.get("layer") or model.CLASS_LAYER[cls]
        if not layer_on(ctx, layer):
            continue
        look = look_for(ctx, layer, over)
        for rec in recs:
            parts.append(stamp(xf_geom(geom2d.display(rec), m), look))
            count += 1
            if count > MAX_PARTS:
                break
    bends = cache.get("bends") or []
    if bends and layer_on(ctx, model.LAYER_BEND):
        look = look_for(ctx, model.LAYER_BEND, (e.style or {}).get("bend") or {})
        th = 2.5 / unit
        for bd in bends:
            parts.append(stamp(xf_geom({"type": "line", "p1": bd["a"], "p2": bd["b"]}, m), look))
            if e.show.get("label", True) and bd.get("note"):
                mx, my = e.position[0] + (bd["a"][0] + bd["b"][0]) / 2.0 * k, e.position[1] + (bd["a"][1] + bd["b"][1]) / 2.0 * k
                dx, dy = bd["b"][0] - bd["a"][0], bd["b"][1] - bd["a"][1]
                ang = math.atan2(dy, dx)
                tp, tb = text_prims(ctx, bd["note"], [mx - math.sin(ang) * th * 1.2, my + math.cos(ang) * th * 1.2], th, look, ang)
                prims.extend(tp)
    faces = cache.get("faces") or []
    if faces and e.show.get("hatch", True) and layer_on(ctx, model.LAYER_SECTION):
        look = look_for(ctx, model.LAYER_SECTION, None)
        prims.extend(hatch_prims(ctx, e, faces, k, look))
        for f in faces:
            for rec in f.get("outer") or []:
                parts.append(stamp(xf_geom(geom2d.display(rec), m), look_for(ctx, model.LAYER_VISIBLE, None)))
    extra = cache.get("extra") or []
    if extra and layer_on(ctx, model.LAYER_BREAK):
        look = look_for(ctx, model.LAYER_BREAK, None)
        for rec in extra:
            parts.append(stamp(xf_geom(geom2d.display(rec), m), look))
    if e.vtype == "detail" and e.detail.get("radius") and e.show.get("boundary", True) and layer_on(ctx, model.LAYER_VISIBLE):
        parts.append(stamp({"type": "circle", "c": [e.position[0], e.position[1]], "r": float(e.detail["radius"]) * k}, look_for(ctx, model.LAYER_VISIBLE, None)))
    b = e.bounds()
    pts.extend([[b[0], b[1]], [b[2], b[3]]])
    if e.label and e.show.get("label", True) and layer_on(ctx, model.LAYER_LABEL):
        lab = look_for(ctx, model.LAYER_LABEL, None)
        th = TEXT_H_MM / unit
        text = e.label if e.scale_text in ("", "1:1") and e.vtype not in ("section", "detail") else "%s  (%s)" % (e.label, e.scale_text)
        tp, tb = text_prims(ctx, text, [(b[0] + b[2]) / 2.0, b[1] - th * 1.8], th, lab)
        prims.extend(tp)
        if tb:
            pts.extend([[tb[0], tb[1]], [tb[2], tb[3]]])
    parent_marks(ctx, e, parts, prims, pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bb = [min(xs), min(ys), max(xs), max(ys)] if pts else [e.position[0], e.position[1], e.position[0], e.position[1]]
    grips = [{"id": 0, "p": [e.position[0], e.position[1]], "kind": "ins"}]
    return {"type": "compound", "parts": parts}, prims, grips, bb
