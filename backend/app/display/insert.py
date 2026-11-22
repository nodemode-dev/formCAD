import math

from app.display import flatten, shapes
from app.text.model import affine, compose

MAX_DEPTH = 6
MAX_PARTS = 20000


def _lin(m):
    return m[0], m[1], m[2], m[3]


def _pt(m, p):
    return [m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5]]


def _vec(m, v):
    return [m[0] * v[0] + m[2] * v[1], m[1] * v[0] + m[3] * v[1]]


def _kind(m):
    sx = math.hypot(m[0], m[1])
    sy = math.hypot(m[2], m[3])
    dot = m[0] * m[2] + m[1] * m[3]
    similar = abs(sx - sy) <= 1e-9 * max(sx, sy, 1e-12) and abs(dot) <= 1e-9 * max(sx * sy, 1e-12)
    det = m[0] * m[3] - m[1] * m[2]
    return similar, det < 0, math.sqrt(abs(det)), math.atan2(m[1], m[0])


def _sample(points, closed, m):
    pts = [_pt(m, p) for p in points]
    return {"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts], "closed": closed, "elev": 0.0}


def xf_geom(g, m):
    similar, mirror, k, theta = _kind(m)
    t = g["type"]
    if t == "line":
        return {"type": "line", "p1": _pt(m, g["p1"]), "p2": _pt(m, g["p2"])}
    if t == "circle":
        if similar:
            return {"type": "circle", "c": _pt(m, g["c"]), "r": g["r"] * k}
        n = flatten.arc_steps(g["r"], 2 * math.pi, 16)
        return _sample(flatten.arc_pts(g["c"][0], g["c"][1], g["r"], 0.0, 2 * math.pi, n)[:-1], True, m)
    if t == "arc":
        if similar:
            a0, a1 = g["a0"], g["a1"]
            if mirror:
                a0, a1 = theta - g["a1"], theta - g["a0"]
            else:
                a0, a1 = a0 + theta, a1 + theta
            return {"type": "arc", "c": _pt(m, g["c"]), "r": g["r"] * k, "a0": a0, "a1": a1}
        sweep = flatten.ccw(g["a0"], g["a1"]) or 2 * math.pi
        return _sample(flatten.arc_pts(g["c"][0], g["c"][1], g["r"], g["a0"], sweep), False, m)
    if t == "ellipse":
        if similar and not mirror:
            return {"type": "ellipse", "c": _pt(m, g["c"]), "major": _vec(m, g["major"]), "ratio": g["ratio"], "a0": g["a0"], "a1": g["a1"]}
        return _sample(flatten.ellipse_pts(g["c"], g["major"], g["ratio"], g["a0"], g["a1"]), False, m)
    if t == "poly":
        if similar:
            verts = []
            for v in g["verts"]:
                p = _pt(m, v)
                verts.append([p[0], p[1], -v[2] if mirror else v[2], v[3] * k, v[4] * k])
            return {"type": "poly", "verts": verts, "closed": g["closed"], "elev": g["elev"]}
        return _sample(flatten.poly_pts(g["verts"], g["closed"]), g["closed"], m)
    if t == "spline":
        out = dict(g)
        out["ctrl"] = [_pt(m, p) for p in g["ctrl"]]
        out["fit"] = [_pt(m, p) for p in g["fit"]] if g["fit"] else None
        return out
    if t == "point":
        out = dict(g)
        out["p"] = _pt(m, g["p"])
        out["size"] = g["size"] * k
        out["rot"] = g.get("rot", 0.0) + theta
        return out
    if t == "text":
        return {"type": "text", "insert": _pt(m, g["insert"]), "height": g["height"] * k, "rot": g["rot"] + (-theta if mirror else theta), "box": [_pt(m, p) for p in g["box"]]}
    if t in ("ray", "xline"):
        d = _vec(m, g["dir"])
        n = math.hypot(d[0], d[1]) or 1.0
        return {"type": t, "p": _pt(m, g["p"]), "dir": [d[0] / n, d[1] / n]}
    if t == "compound":
        return {"type": "compound", "parts": [xf_geom(p, m) for p in g["parts"]]}
    return g


def xf_prims(prims, m, tag):
    out = []
    for p in prims:
        q = dict(p)
        if p["t"] == "fill":
            q["rings"] = [_flat([_pt(m, (r[i], r[i + 1])) for i in range(0, len(r), 2)]) for r in p["rings"]]
        else:
            pts = p["pts"]
            q["pts"] = _flat([_pt(m, (pts[i], pts[i + 1])) for i in range(0, len(pts), 2)])
        if p.get("clip"):
            c = p["clip"]
            q["clip"] = _flat([_pt(m, (c[i], c[i + 1])) for i in range(0, len(c), 2)])
        if tag and "c" not in q and "ci" not in q:
            q.update(tag)
        out.append(q)
    return out


def _flat(points):
    out = []
    for p in points:
        out.append(p[0])
        out.append(p[1])
    return out


def _box(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def xf_bounds(b, m):
    if b is None:
        return None
    return _box([_pt(m, (b[0], b[1])), _pt(m, (b[2], b[1])), _pt(m, (b[2], b[3])), _pt(m, (b[0], b[3]))])


def part_props(part, cp):
    part["color"] = list(cp.rgb)
    part["color7"] = cp.c7
    part["lw"] = cp.lw
    part["lt"] = cp.lt
    return part


def expand(rec, m, ctx, pp, depth, state):
    if depth > MAX_DEPTH or rec is None:
        return
    ctx.deps.add(rec["name"].casefold())
    space = "block:" + rec["name"]
    for child in ctx.d.entities(space):
        if state["count"] >= MAX_PARTS:
            return
        if not ctx.visible(child, pp):
            continue
        if child.kind == "attdef":
            continue
        cp = ctx.props(child, pp)
        if child.kind == "insert":
            sub = ctx.d.table_get("blocks", child.block)
            cms = copies(child, sub, ctx)
            for cm in cms:
                state["count"] += 1
                expand(sub, compose(m, cm), ctx, cp, depth + 1, state)
            if sub is not None and cms and depth < MAX_DEPTH:
                from app.display import attribs as attribs_d

                attribs_d.add_attributes(ctx, child, compose(m, cms[0]), cp, state)
            continue
        res = ctx.shape_cache.get(child.handle)
        if res is None:
            res = shapes.build(child, ctx)
            ctx.shape_cache[child.handle] = res or False
        if not res:
            continue
        g, prims, _grips, bb = res
        state["count"] += 1
        tag = None
        if cp.rgb != pp.rgb or cp.c7 != pp.c7:
            tag = {"c": list(cp.rgb)}
            if cp.c7:
                tag["c7"] = True
        for gg in _flat_parts(xf_geom(g, m)):
            state["parts"].append(part_props(gg, cp))
        state["prims"].extend(xf_prims(prims, m, tag))
        nb = xf_bounds(bb, m)
        if nb is not None:
            state["bounds"].extend([[nb[0], nb[1]], [nb[2], nb[3]]])


def _flat_parts(g):
    if g["type"] == "compound":
        out = []
        for p in g["parts"]:
            out.extend(_flat_parts(p))
        return out
    return [g]


def copies(ent, rec, ctx):
    base = rec["base"] if rec else [0.0, 0.0, 0.0]
    sx = float(ent.scale[0]) if ent.scale else 1.0
    sy = float(ent.scale[1]) if ent.scale and len(ent.scale) > 1 else sx
    ca, sa = math.cos(ent.rotation), math.sin(ent.rotation)
    core = compose(affine(ca, sa, -sa, ca, ent.position[0], ent.position[1]), compose(affine(sx, 0.0, 0.0, sy, 0.0, 0.0), affine(1, 0, 0, 1, -base[0], -base[1])))
    arr = ent.array or {}
    rows = max(1, min(int(arr.get("rows", 1) or 1), 100))
    cols = max(1, min(int(arr.get("cols", arr.get("columns", 1)) or 1), 100))
    rs = float(arr.get("row_spacing", 0.0) or 0.0)
    cs = float(arr.get("col_spacing", arr.get("column_spacing", 0.0)) or 0.0)
    out = []
    for r in range(rows):
        for c in range(cols):
            dx, dy = c * cs, r * rs
            off = affine(1, 0, 0, 1, dx * ca - dy * sa, dx * sa + dy * ca)
            out.append(compose(off, core))
    return out


def run(ent, ctx, block_name, ms, pp):
    rec = ctx.d.table_get("blocks", block_name)
    ctx.deps.add(str(block_name).casefold())
    state = {"parts": [], "prims": [], "bounds": [], "count": 0}
    if rec is not None:
        for m in ms:
            expand(rec, m, ctx, pp, 0, state)
    return state


@shapes.builder("insert")
def insert(e, ctx):
    pp = ctx.props(e)
    rec = ctx.d.table_get("blocks", e.block)
    ms = copies(e, rec, ctx)
    state = run(e, ctx, e.block, ms, pp)
    if rec is not None and ms:
        from app.display import attribs as attribs_d

        attribs_d.add_attributes(ctx, e, ms[0], pp, state)
    p = [float(e.position[0]), float(e.position[1])]
    bb = _box(state["bounds"]) if state["bounds"] else [p[0], p[1], p[0], p[1]]
    return {"type": "compound", "parts": state["parts"]}, state["prims"], [{"id": 0, "p": p, "kind": "ins"}], bb


@shapes.builder("dimension")
def dimension(e, ctx):
    base = shapes.dimension_base(e, ctx)
    if not e.block or ctx.d.table_get("blocks", e.block) is None:
        return base
    pp = ctx.props(e)
    state = run(e, ctx, e.block, [affine()], pp)
    bb = _box(state["bounds"]) if state["bounds"] else base[3]
    return {"type": "compound", "parts": state["parts"]}, state["prims"], base[2], bb
