from app.display import shapes
from app.display.insert import _flat_parts, part_props, xf_bounds, xf_geom, xf_prims
from app.doc.kinds import array as A


def _box(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _prepared(objs, ctx, pp, ov):
    out = []
    for child in objs:
        if ov:
            A.apply_override(child, ov)
        if not ctx.visible(child, pp):
            continue
        res = shapes.build(child, ctx)
        if not res:
            continue
        cp = ctx.props(child, pp)
        tag = None
        if cp.rgb != pp.rgb or cp.c7 != pp.c7:
            tag = {"c": list(cp.rgb)}
            if cp.c7:
                tag["c7"] = True
        out.append((cp, res, tag))
    return out


@shapes.builder("assoc_array")
def assoc_array(e, ctx):
    ctx.deps.add("*array")
    pp = ctx.props(e)
    cache = {}
    parts = []
    prims = []
    corners = []
    shown = 0
    editing = tuple(e.editing.get("item", ())) if e.editing else None
    for key, d, rot, about in e.frames():
        if editing is not None and tuple(key) == editing:
            continue
        ov = e.override_for(key)
        if ov is not None and ov.get("visible") is False:
            continue
        shown += 1
        if shown > A.DISPLAY_LIMIT:
            break
        rep = e.replacement_for(key)
        ck = (A.key_text(key) if (rep is not None or ov is not None) else "src")
        prep = cache.get(ck)
        if prep is None:
            prep = _prepared(e.item_objects(key), ctx, pp, ov)
            cache[ck] = prep
        m = A.frame_matrix(d, rot, about)
        for cp, res, tag in prep:
            g, pr, _grips, bb = res
            for gg in _flat_parts(xf_geom(g, m)):
                parts.append(part_props(gg, cp))
            prims.extend(xf_prims(pr, m, tag))
            nb = xf_bounds(bb, m)
            if nb is not None:
                corners.extend([[nb[0], nb[1]], [nb[2], nb[3]]])
    base = [float(e.base[0]), float(e.base[1])]
    bb = _box(corners) if corners else [base[0], base[1], base[0], base[1]]
    return {"type": "compound", "parts": parts}, prims, [], bb
