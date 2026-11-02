import math

from app.dim import layout as DL
from app.dim import textmeasure
from app.dim import vars as DV
from app.display import insert, palette, shapes
from app.display.shapes import box, xy
from app.text import single

ROLE_COLOR = {"dim": "DIMCLRD", "arrow": "DIMCLRD", "ext1": "DIMCLRE", "ext2": "DIMCLRE", "text": "DIMCLRT"}
ROLE_WEIGHT = {"dim": "DIMLWD", "arrow": "DIMLWD", "ext1": "DIMLWE", "ext2": "DIMLWE"}
ROLE_TYPE = {"dim": "DIMLTYPE", "arrow": "", "ext1": "DIMLTEX1", "ext2": "DIMLTEX2"}
LW_BYLAYER, LW_BYBLOCK, LW_DEFAULT = -1, -2, -3


class RoleProps:
    __slots__ = ("rgb", "c7", "lw", "lt")

    def __init__(self, rgb, c7, lw, lt):
        self.rgb = rgb
        self.c7 = c7
        self.lw = lw
        self.lt = lt


def _color(ctx, pp, value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        if n == 0:
            return pp.rgb, pp.c7
        if n == 256:
            lp = ctx.layer_props(pp.layer)
            return lp[0], lp[1]
    rgb, c7 = palette.resolve(value, 7, None)
    return rgb, c7


def _weight(ctx, pp, value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return pp.lw
    if n == LW_BYBLOCK:
        return pp.lw
    if n == LW_BYLAYER:
        return ctx.layer_props(pp.layer)[2]
    if n == LW_DEFAULT:
        return ctx.lw_default
    return max(0.0, n / 100.0)


def _linetype(ctx, pp, name):
    nm = str(name or "")
    low = nm.casefold()
    if low in ("", "byblock"):
        return pp.lt
    if low == "bylayer":
        nm = ctx.layer_props(pp.layer)[3]
    elif low == "continuous":
        return None
    lname, pat = ctx.lt_pattern(nm)
    if pat is None:
        return None
    return {"name": lname, "pattern": pat, "scale": ctx.ltscale * pp.ltmul}


def role_props(ctx, pp, V, role, cache):
    hit = cache.get(role)
    if hit is not None:
        return hit
    rgb, c7 = _color(ctx, pp, V.get(ROLE_COLOR.get(role, "DIMCLRD"), 0))
    if role == "text":
        rp = RoleProps(rgb, c7, pp.lw, pp.lt)
    else:
        rp = RoleProps(rgb, c7, _weight(ctx, pp, V.get(ROLE_WEIGHT.get(role, "DIMLWD"), -2)), _linetype(ctx, pp, V.get(ROLE_TYPE.get(role, "DIMLTYPE"), "")))
    cache[role] = rp
    return rp


def _tag(rp, pp):
    if rp.rgb == pp.rgb and rp.c7 == pp.c7:
        return None
    t = {"c": list(rp.rgb)}
    if rp.c7:
        t["c7"] = True
    return t


def _flat(points):
    out = []
    for p in points:
        out.append(float(p[0]))
        out.append(float(p[1]))
    return out


def _circle_ring(c, r, n=28):
    return _flat([(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)])


def render(e, ctx, out, V, S, pp, rec, fs, ht):
    cache = {}
    parts = []
    prims = []
    allp = list(out.points())

    def add(part, role):
        rp = role_props(ctx, pp, V, role, cache)
        part["color"] = list(rp.rgb)
        part["color7"] = rp.c7
        part["lw"] = rp.lw
        part["lt"] = rp.lt
        parts.append(part)

    for p, q, role in out.segs:
        add({"type": "line", "p1": [p[0], p[1]], "p2": [q[0], q[1]]}, role)
    for c, r, a0, sw, role in out.arcs:
        if sw >= 2 * math.pi - 1e-9:
            add({"type": "circle", "c": [c[0], c[1]], "r": r}, role)
        else:
            a_s = a0 % (2 * math.pi)
            add({"type": "arc", "c": [c[0], c[1]], "r": r, "a0": a_s, "a1": (a_s + sw) % (2 * math.pi)}, role)
    for pts, closed, role in out.polys:
        add({"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts], "closed": closed, "elev": 0.0}, role)
    for c, r, filled, role in out.circles:
        if not filled:
            add({"type": "circle", "c": [c[0], c[1]], "r": r}, role)
    for pts, role in out.fills:
        rp = role_props(ctx, pp, V, role, cache)
        pr = {"t": "fill", "rings": [_flat(pts)]}
        t = _tag(rp, pp)
        if t:
            pr.update(t)
        prims.append(pr)
    for c, r, filled, role in out.circles:
        if filled:
            rp = role_props(ctx, pp, V, role, cache)
            pr = {"t": "fill", "rings": [_circle_ring(c, r)]}
            t = _tag(rp, pp)
            if t:
                pr.update(t)
            prims.append(pr)
    trp = role_props(ctx, pp, V, "text", cache)
    ttag = _tag(trp, pp)
    wf = float(rec.get("width_factor", 1.0) or 1.0)
    obl = float(rec.get("oblique", 0.0) or 0.0)
    for b in out.blocks:
        corners = b.corners()
        fillmode = int(V.get("DIMTFILL", 0))
        if fillmode in (1, 2):
            pad = abs(float(V["DIMGAP"])) * S * 0.5
            hw = b.width / 2.0
            ring = [b.to_world(-hw - pad, b.bottom - pad), b.to_world(hw + pad, b.bottom - pad), b.to_world(hw + pad, b.top + pad), b.to_world(-hw - pad, b.top + pad)]
            pr = {"t": "fill", "rings": [_flat(ring)]}
            if fillmode == 1:
                pr["mask"] = True
            else:
                rgb, _c7 = palette.resolve(V.get("DIMTFILLCLR", 0), 7, None)
                pr["c"] = list(rgb)
            prims.append(pr)
            allp += ring
        for text, cx, cy, h in b.parts:
            at = b.to_world(cx, cy)
            laid = single.layout(fs, text, float(h), wf, obl, bool(rec.get("backwards")), bool(rec.get("upside_down")), 1, 2, at, at, b.rot, bool(ctx.textfill))
            for pr in laid.prims:
                if ttag and "c" not in pr and "ci" not in pr:
                    pr.update(ttag)
                prims.append(pr)
            if laid.bounds:
                allp += [(laid.bounds[0], laid.bounds[1]), (laid.bounds[2], laid.bounds[3])]
        for x0, y0, x1, y1 in b.lines:
            pr = {"t": "pl", "pts": _flat([b.to_world(x0, y0), b.to_world(x1, y1)]), "closed": False}
            if ttag:
                pr.update(ttag)
            prims.append(pr)
        for cx, cy, r, a0, a1 in b.arcs:
            pts = [b.to_world(cx + r * math.cos(a), cy + r * math.sin(a)) for a in [a0 + (a1 - a0) * i / 12.0 for i in range(13)]]
            pr = {"t": "pl", "pts": _flat(pts), "closed": False}
            if ttag:
                pr.update(ttag)
            prims.append(pr)
        if not b.empty:
            c = b.center
            parts.append({"type": "text", "insert": [c[0], c[1]], "height": float(ht), "rot": b.rot, "box": [[p[0], p[1]] for p in corners]})
    return parts, prims, allp


@shapes.builder("dimension")
def dimension(e, ctx):
    if e.block and ctx.d.table_get("blocks", e.block) is not None and not e.marks.get("regen"):
        return insert.dimension(e, ctx)
    d = ctx.d
    V = DV.resolve(d, e.style, e.overrides)
    S = DV.scale_of(d, V)
    pp = ctx.props(e)
    measure, rec, fs = textmeasure.measurer(ctx, V.get("DIMTXSTY") or "Standard")
    ht = textmeasure.text_height(rec, V, S)
    out = DL.generate(e, V, S, measure, ht)
    parts, prims, allp = render(e, ctx, out, V, S, pp, rec, fs, ht)
    base = [xy(p) for p in (None if e.dim_type == "ordinate" else e.def_point, e.text_point if out.blocks else None, e.p13, e.p14, e.p15, e.p16) if p]
    allp += base
    bb = box(allp)
    return {"type": "compound", "parts": parts}, prims, [], bb
