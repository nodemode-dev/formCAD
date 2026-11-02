import math

from app.display import insert as ins
from app.dim import arrows
from app.display import palette
from app.display.shapes import _catmull, box, builder, fontset, grip_list, xy
from app.doc import tableops
from app.doc.entities import Insert
from app.text import mtext

SPLINE_STEPS = 12


def _rgb(color):
    rgb, _c7 = palette.resolve(color, 7, None)
    return list(rgb)


def _poly(pts, closed=False):
    return {"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts], "closed": closed, "elev": 0.0}


def _flat(pts):
    return [v for p in pts for v in p]


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else (1.0, 0.0)


def leader_run(pts, arrow, size, spline):
    pts = [xy(p) for p in pts]
    parts, fills = [], []
    start = pts[0]
    if arrow and len(pts) >= 2 and size > 0:
        u = _unit(pts[1], pts[0])
        a = arrows.build(arrow, pts[0], u, size)
        for ring, closed in a.polys:
            parts.append(_poly(ring, closed))
        for p, q in a.segs:
            parts.append({"type": "line", "p1": [p[0], p[1]], "p2": [q[0], q[1]]})
        for c, r, filled in a.circles:
            parts.append({"type": "circle", "c": [c[0], c[1]], "r": r})
            if filled:
                fills.append(_flat([(c[0] + r * math.cos(k * math.pi / 12.0), c[1] + r * math.sin(k * math.pi / 12.0)) for k in range(24)]))
        for ring in a.fills:
            fills.append(_flat(ring))
        if a.fills and not a.polys:
            for ring in a.fills:
                parts.append(_poly(ring, True))
        seg = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
        trim = min(a.trim, seg * 0.95)
        start = [pts[0][0] - u[0] * trim, pts[0][1] - u[1] * trim]
    line = [start] + pts[1:]
    if spline and len(line) >= 3:
        line = _catmull(line, False, SPLINE_STEPS)
    parts.append(_poly(line))
    return parts, fills, line


def _block_state(e, ctx, name, pos, scale, rotation, attach, pp, side):
    rec = ctx.d.table_get("blocks", name)
    if rec is None:
        return None
    probe = Insert(block=name, position=[0.0, 0.0, 0.0], scale=[scale, scale, scale], rotation=rotation)
    st0 = ins.run(probe, ctx, name, ins.copies(probe, rec, ctx), pp)
    if not st0["bounds"]:
        return None
    pts = st0["bounds"]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    if attach == "corner":
        origin = [pos[0] - x0, pos[1] - y1]
    elif attach == "insertion":
        origin = [pos[0], pos[1]]
    else:
        near = x0 if side > 0 else (x1 if side < 0 else (x0 + x1) / 2.0)
        origin = [pos[0] - near, pos[1] - (y0 + y1) / 2.0]
    real = Insert(block=name, position=[origin[0], origin[1], 0.0], scale=[scale, scale, scale], rotation=rotation)
    st = ins.run(real, ctx, name, ins.copies(real, rec, ctx), pp)
    return st, (x0 + origin[0], y0 + origin[1], x1 + origin[0], y1 + origin[1])


@builder("mleader")
def mleader(e, ctx):
    d = ctx.d
    style = d.table_get("mleaderstyles", e.style) or d.table_get("mleaderstyles", "Standard") or {}
    f = float(getattr(e, "anno_factor", 1.0))
    pp = ctx.props(e)
    arrow = e.arrow or style.get("arrowhead", "closed filled")
    asz = e.size_of("arrow_size", style, f)
    gap = e.size_of("landing_gap", style, f)
    dog = e.size_of("dogleg_length", style, f)
    th = e.size_of("text_height", style, f)
    parts, prims, pts_all, grips = [], [], [], []
    if arrow == "none":
        asz = 0.0
    spline = e.leader_type == "spline"
    for i, ld in enumerate(e.leaders):
        lp, lf, line = leader_run(ld["pts"], arrow if e.leader_type != "none" else None, asz, spline)
        parts.extend(lp)
        if lf:
            prims.append({"t": "fill", "rings": lf})
        pts_all.extend(line)
        pts_all.extend(xy(p) for p in ld["pts"])
        grips.append((xy(ld["pts"][0]), "end"))
    land = xy(e.landing)
    end = [land[0] + e.dogleg_dir * dog, land[1]] if e.has_landing else land
    if e.leaders:
        if e.has_landing and dog > 0:
            parts.append(_poly([land, end]))
        pts_all.extend([land, end])
        grips.append((land, "node"))
        anchor = [end[0] + e.dogleg_dir * gap, end[1]]
        side = 1.0 if e.dogleg_dir >= 0 else -1.0
        attach_mt = 4 if e.dogleg_dir >= 0 else 6
    else:
        anchor = xy(e.content_pos)
        side = 0.0
        attach_mt = 1
    if e.content_type == "mtext" and e.text:
        style_name = e.text_style or style.get("text_style", "Standard")
        rec, fs = fontset(ctx, style_name)
        laid = mtext.layout(fs, e.text, th, 0.0, attach_mt, 0.0, anchor, 1.0, 1, {}, float(rec.get("width_factor", 1.0) or 1.0), float(rec.get("oblique", 0.0) or 0.0), bool(ctx.textfill), fs.desc)
        prims.extend(laid.prims)
        if laid.bounds:
            pts_all.extend([[laid.bounds[0], laid.bounds[1]], [laid.bounds[2], laid.bounds[3]]])
        pts_all.extend([xy(p) for p in laid.box])
        grips.append((xy(anchor), "insert"))
    elif e.content_type == "block" and e.block:
        bs = float(e.block_scale) * f
        main_attach = "corner" if e.more_blocks else e.block_attach
        got = _block_state(e, ctx, e.block, xy(e.content_pos) if e.more_blocks else anchor, bs, float(e.block_rotation), main_attach, pp, side)
        blocks = [got] if got else []
        for mb in e.more_blocks:
            extra = _block_state(e, ctx, mb["block"], mb["pos"], float(mb.get("scale", 1.0)) * f, float(mb.get("rotation", 0.0)), "corner", pp, 0.0)
            if extra:
                blocks.append(extra)
        for st, bb in blocks:
            parts.extend(st["parts"])
            prims.extend(st["prims"])
            pts_all.extend([[bb[0], bb[1]], [bb[2], bb[3]]])
        grips.append((xy(anchor), "insert"))
    if not pts_all:
        pts_all = [land]
    return {"type": "compound", "parts": parts}, prims, grip_list(grips), box(pts_all)


@builder("leader")
def leader(e, ctx):
    d = ctx.d
    style = d.table_get("dimstyles", e.style) or {}
    blk = (style.get("vars") or {}).get("DIMLDRBLK", "") or "closed filled"
    size = float(e.arrow_size or 0.0)
    parts, fills, line = leader_run(e.points, blk if e.arrowhead else None, size, bool(e.spline))
    prims = [{"t": "fill", "rings": fills}] if fills else []
    pts = [xy(p) for p in e.points] + line
    return {"type": "compound", "parts": parts}, prims, grip_list([(xy(p), "vtx") for p in e.points]), box(pts)


def _rotator(e):
    px, py = e.position[0], e.position[1]
    if not e.rotation:
        return lambda x, y: [x, y]
    c, s = math.cos(e.rotation), math.sin(e.rotation)
    return lambda x, y: [px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c]


@builder("table")
def table(e, ctx):
    d = ctx.d
    ts = tableops.style_rec(d, e.style) or {}
    pp = ctx.props(e)
    P = _rotator(e)
    cover = e.cover()
    xs = [0.0]
    for w in e.col_widths:
        xs.append(xs[-1] + w)
    parts, prims, allp = [], [], []
    px, py = e.position[0], e.position[1]
    grips = []
    for k, part in enumerate(e.parts()):
        rows = part["rows"]
        ox, oy = px + part["dx"], py + part["dy"]
        ys = [0.0]
        for r in rows:
            ys.append(ys[-1] - e.row_heights[r])
        grips.append((P(ox, oy), "insert"))
        local = {}
        for v, r in enumerate(rows):
            for c in range(e.cols()):
                an = cover.get((r, c))
                if an is not None and an[0] in rows[:v]:
                    local[(v, c)] = None
                    continue
                cell = e.cells[r][c]
                rs, cs = cell.get("span", [1, 1])
                rs_eff = 1
                while rs_eff < rs and v + rs_eff < len(rows) and rows[v + rs_eff] == r + rs_eff:
                    rs_eff += 1
                local[(v, c)] = (r, rs_eff, min(cs, e.cols() - c))
        for (v, c), info in local.items():
            if info is None:
                continue
            r, rs, cs = info
            x0, x1 = ox + xs[c], ox + xs[c + cs]
            y0, y1 = oy + ys[v], oy + ys[v + rs]
            eff = tableops.effective(d, e, r, c)
            if eff["fill"] is not None:
                ring = [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]
                prims.append({"t": "fill", "rings": [[q for p in ring for q in p]], "c": _rgb(eff["fill"])})
            text = e.cells[r][c].get("text", "")
            if text.strip() != "":
                mh, mv = eff["margin_h"], eff["margin_v"]
                a = eff["align"]
                col = (a - 1) % 3
                row = (a - 1) // 3
                tx = x0 + mh if col == 0 else ((x0 + x1) / 2.0 if col == 1 else x1 - mh)
                ty = y0 - mv if row == 0 else ((y0 + y1) / 2.0 if row == 1 else y1 + mv)
                rec, fs = fontset(ctx, eff["text_style"])
                width = max(0.0, (x1 - x0) - 2 * mh)
                laid = mtext.layout(fs, text, eff["text_height"], width, a, e.rotation, P(tx, ty), 1.0, 1, {}, float(rec.get("width_factor", 1.0) or 1.0), float(rec.get("oblique", 0.0) or 0.0), bool(ctx.textfill), fs.desc)
                tc = eff["text_color"]
                tag = None if tc in (0, 256, None) else _rgb(tc)
                for pr in laid.prims:
                    if tag is not None and "c" not in pr and "ci" not in pr:
                        pr["c"] = list(tag)
                    prims.append(pr)
                if laid.bounds:
                    allp.extend([[laid.bounds[0], laid.bounds[1]], [laid.bounds[2], laid.bounds[3]]])
        n_rows = len(rows)
        hunits = {}
        for v in range(n_rows + 1):
            up = rows[v - 1] if v > 0 else None
            lo = rows[v] if v < n_rows else None
            for c in range(e.cols()):
                spec = tableops.edge_border(d, e, ts, "h", (up, lo), c, cover)
                if spec is None or not spec.get("visible", True):
                    continue
                hunits.setdefault((v, _key(spec)), []).append((c, spec))
        vunits = {}
        for v, r in enumerate(rows):
            for c in range(e.cols() + 1):
                lf = c - 1 if c > 0 else None
                rt = c if c < e.cols() else None
                spec = tableops.edge_border(d, e, ts, "v", (lf, rt), r, cover)
                if spec is None or not spec.get("visible", True):
                    continue
                vunits.setdefault((c, _key(spec)), []).append((v, spec))
        for (v, _k), items in hunits.items():
            for run in _runs([i[0] for i in items]):
                spec = items[0][1]
                a, b = P(ox + xs[run[0]], oy + ys[v]), P(ox + xs[run[1] + 1], oy + ys[v])
                parts.append(_edge(a, b, spec, pp))
                allp.extend([a, b])
        for (c, _k), items in vunits.items():
            for run in _runs([i[0] for i in items]):
                spec = items[0][1]
                a, b = P(ox + xs[c], oy + ys[run[0]]), P(ox + xs[c], oy + ys[run[1] + 1])
                parts.append(_edge(a, b, spec, pp))
                allp.extend([a, b])
        allp.extend([P(ox, oy), P(ox + xs[-1], oy + ys[-1])])
    return {"type": "compound", "parts": parts}, prims, grip_list(grips), box(allp or [xy(e.position)])


def _key(spec):
    return (str(spec.get("color", 0)), int(spec.get("lineweight", -2)))


def _runs(idx):
    out = []
    for i in sorted(idx):
        if out and out[-1][1] == i - 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def _edge(a, b, spec, pp):
    part = {"type": "line", "p1": a, "p2": b}
    col = spec.get("color", 0)
    lw = spec.get("lineweight", -2)
    rgb, c7 = (pp.rgb, pp.c7) if col in (0, 256, None) else palette.resolve(col, 7, None)
    part["color"] = list(rgb)
    part["color7"] = c7
    part["lw"] = pp.lw if lw in (-2, -1, -3, None) else max(0.0, lw / 100.0)
    part["lt"] = pp.lt
    return part
