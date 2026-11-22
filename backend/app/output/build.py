import json
import math

import numpy as np

from app import display
from app.display import palette
from app.display.resolve import Context
from app.display.state import make_entry, session_values, space_key, state_for
from app.doc import annotation, layouts as L, nurbs
from app.doc.model import layout_space
from app.output import pdfwrite, plotstyle, request as R, textrun
from app.output.fontembed import EmbedFont
from app.output.sheet import MAX_OPS, Sheet, Style, canon_dash, clip_polyline, clip_ring, rect_ring

TEXT_KINDS = ("text", "mtext", "insert", "dimension", "leader", "mleader", "table")
CHORD_MM = 0.004
MIN_REPEAT_MM = 0.15
MAX_REPEATS = 50000
FILL_CELLS = 60000
ACI = {}
for _i in range(255, 0, -1):
    ACI[palette.TABLE[_i]] = _i


def aci_of(rgb, c7):
    if c7:
        return 7
    rgb = tuple(rgb)
    hit = ACI.get(rgb)
    return hit if hit is not None else palette.nearest_index(rgb)


def arc_points(cx, cy, r, a0, sweep, tol):
    r = abs(r)
    if r < 1e-12 or sweep == 0:
        return np.array([[cx, cy]])
    step = 2.0 * math.acos(max(-1.0, 1.0 - tol / r)) if tol < r else math.pi / 2.0
    n = max(2, min(8192, int(math.ceil(abs(sweep) / max(step, 1e-6)))))
    t = a0 + sweep * np.arange(n + 1) / n
    return np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])


def bulge_points(p0, p1, bulge, tol):
    if abs(bulge) < 1e-12:
        return np.array([[p0[0], p0[1]], [p1[0], p1[1]]])
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if chord < 1e-12:
        return np.array([[p0[0], p0[1]]])
    theta = 4.0 * math.atan(bulge)
    r = chord / (2.0 * math.sin(abs(theta) / 2.0))
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    ux, uy = (p1[0] - p0[0]) / chord, (p1[1] - p0[1]) / chord
    off = r * math.cos(theta / 2.0)
    side = 1.0 if bulge > 0 else -1.0
    cx, cy = mx - uy * off * side, my + ux * off * side
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    pts = arc_points(cx, cy, r, a0, theta, tol)
    pts[0] = (p0[0], p0[1])
    pts[-1] = (p1[0], p1[1])
    return pts


def poly_points(verts, closed, tol):
    n = len(verts)
    if n == 0:
        return np.zeros((0, 2))
    parts = []
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        seg = bulge_points(a, b, a[2] if len(a) > 2 else 0.0, tol)
        parts.append(seg if not parts else seg[1:])
    if not parts:
        return np.array([[verts[0][0], verts[0][1]]])
    out = np.vstack(parts)
    if closed and len(out) > 1 and np.allclose(out[0], out[-1], atol=1e-12):
        out = out[:-1]
    return out


def band_rings(verts, closed, tol):
    n = len(verts)
    count = n if closed else n - 1
    rings = []
    thin = []
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        w0 = float(a[3]) if len(a) > 3 else 0.0
        w1 = float(a[4]) if len(a) > 4 else 0.0
        pts = bulge_points(a, b, a[2] if len(a) > 2 else 0.0, tol)
        if w0 <= 0 and w1 <= 0 or len(pts) < 2:
            thin.append(pts)
            continue
        k = len(pts) - 1
        left, right = [], []
        for j, p in enumerate(pts):
            q0 = pts[max(j - 1, 0)]
            q1 = pts[min(j + 1, k)]
            dx, dy = q1[0] - q0[0], q1[1] - q0[1]
            ln = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / ln, dx / ln
            w = (w0 + (w1 - w0) * j / k) / 2.0
            left.append((p[0] + nx * w, p[1] + ny * w))
            right.append((p[0] - nx * w, p[1] - ny * w))
        rings.append(np.array(left + right[::-1]))
    return rings, thin


def spline_points(g, tol):
    ctrl = g.get("ctrl") or []
    try:
        c = nurbs.Curve(int(g["degree"]), list(g["knots"]), [[p[0], p[1], 0.0] for p in ctrl], list(g["weights"]) if g.get("weights") else [], bool(g.get("closed")))
        if ctrl and c.valid():
            pts = np.array([[p[0], p[1]] for p in nurbs.sample(c, 48)])
            if g.get("closed") and len(pts) > 1 and not np.allclose(pts[0], pts[-1]):
                pts = np.vstack([pts, pts[:1]])
            return pts
    except Exception:
        pass
    src = ctrl if len(ctrl) >= 2 else (g.get("fit") or [])
    return np.array([[p[0], p[1]] for p in src]) if len(src) >= 2 else np.zeros((0, 2))


class Cache:
    def __init__(self, doc, include_off, want_text):
        self.doc = doc
        self.include_off = include_off
        self.want_text = want_text
        self.spaces = {}

    def get(self, key):
        hit = self.spaces.get(key)
        if hit is None:
            hit = self.build(key)
            self.spaces[key] = hit
        return hit

    def build(self, key):
        doc = self.doc
        ctx = Context(doc, session_values())
        if self.include_off:
            items = self.items_all(doc, key, ctx)
        else:
            items = display.build_items(doc, None, key)["items"]
        layers = ctx.layer_summary()
        texts = self.capture(doc, items, ctx) if self.want_text else {}
        return {"items": items, "layers": layers, "texts": texts, "ctx": ctx}

    def items_all(self, doc, key, ctx):
        class Everything(Context):
            def visible(self, ent, parent=None):
                return bool(ent.visible)

        loose = Everything(doc, session_values())
        loose.layers = ctx.layers
        st = state_for(doc, space_key(doc, key))
        seq = st.current_seq(doc)
        out = []
        for i, h in enumerate(seq):
            e = doc.drawing.ents[h]
            made = make_entry(e, loose, (i + 1) * 1024, doc.rev)
            if made is not None:
                out.append(json.loads(made.js))
        return out

    def capture(self, doc, items, ctx):
        out = {}
        d = doc.drawing
        todo = [it for it in items if it["kind"] in TEXT_KINDS]
        if not todo:
            return out
        cap = textrun.Capture()
        fonts = {}
        from app.display import shapes

        with textrun.Patched(cap):
            for it in todo:
                e = d.ents.get(it["h"])
                if e is None:
                    continue
                cctx = Context(doc, session_values())
                cctx.deps = set()
                shown = annotation.display_entity(cctx, e) if e.annotation_scales else e
                if shown is None:
                    continue
                try:
                    res = shapes.build(shown, cctx)
                except Exception:
                    continue
                if not res:
                    continue
                runs = cap.owned.get(id(res[1]))
                if not runs:
                    continue
                ok = True
                glyphs = []
                for (font, gid), m, ckey in runs:
                    fk = (font.path, font.index)
                    emb = fonts.get(fk)
                    if emb is None:
                        emb = EmbedFont(font)
                        fonts[fk] = emb
                    if not emb.ok:
                        ok = False
                        break
                    glyphs.append((emb, gid, m, ckey))
                if ok:
                    out[it["h"]] = {"geom": res[0], "prims": res[1], "glyphs": glyphs}
        return out


class SheetBuilder:
    def __init__(self, doc, req, spec, table, cache, output):
        self.doc = doc
        self.d = doc.drawing
        self.req = req
        self.spec = spec
        self.table = table
        self.cache = cache
        self.output = output
        self.min_width = req.get("min_width", R.MIN_WIDTH_DEFAULT)
        self.real_text = output == "pdf" and req.get("text_mode", "text") == "text"
        self.use_layers = req.get("layers", True)
        self.include_off = req.get("include_off", False)
        self.alpha_on = spec["transparency"]
        self.styles = {}
        self.links = {}
        for h, url in req.get("links", []):
            if h not in self.links and pdfwrite.safe_url(url) is not None:
                self.links[h] = url
        self.sheet = Sheet(spec["name"], spec["width"], spec["height"], spec["printable"])
        self.ops = 0
        self.vp_state = None
        self.spaceKey = "model"

    def layer_key(self, name, on):
        if not self.use_layers:
            return None
        return self.sheet.layer(name, on)

    def style(self, rgb, c7, lw, lt, tr, layer, on, ent, ps_name, s, ltscale, kind="S"):
        key = (tuple(rgb), c7, lw, None if lt is None else (lt.get("name"), tuple(lt.get("pattern") or ()), lt.get("scale")), tr, layer.casefold(), on, ps_name, s, kind)
        hit = self.styles.get(key)
        if hit is not None:
            return hit
        aci = aci_of(rgb, c7)
        pstyle = plotstyle.lookup(self.table, aci, ps_name)
        out_rgb = plotstyle.printed_color(pstyle, rgb, c7)
        width = lw if self.spec["lineweights"] else self.min_width
        if self.spec["lineweights"] and pstyle is not None and pstyle["lineweight"] is not None:
            width = pstyle["lineweight"]
        width = max(width, self.min_width)
        cap = plotstyle.cap_code(pstyle["cap"]) if pstyle else 1
        join = plotstyle.join_code(pstyle["join"]) if pstyle else 1
        pat = None
        if pstyle is not None and pstyle["linetype"]:
            _nm, p = self.cache.get(self.spaceKey)["ctx"].lt_pattern(pstyle["linetype"])
            pat = (p, ltscale) if p else None
        elif lt is not None and lt.get("pattern"):
            pat = (lt["pattern"], lt.get("scale", 1.0))
        dash = None
        if pat is not None:
            d = canon_dash(pat[0], pat[1] * s)
            if d is not None and sum(d[0]) >= MIN_REPEAT_MM:
                dash = d
        alpha = 1.0 - max(0.0, min(0.9, tr)) if self.alpha_on else 1.0
        hit = Style(out_rgb, alpha, width, cap, join, dash, self.layer_key(layer, on))
        self.styles[key] = (hit, pstyle)
        return self.styles[key]

    def emit_polyline(self, pts, closed, st, M):
        s, tx, ty = M
        p = np.asarray(pts, dtype=float)
        if len(p) == 0:
            return
        q = p * s + np.array([tx, ty])
        if closed and len(q) > 2:
            q = np.vstack([q, q[:1]])
            closed = False
        x0, y0, x1, y1 = self.sheet.printable
        pad = 50.0
        rect = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        total = float(np.hypot(*np.diff(q, axis=0).T).sum()) if len(q) > 1 else 0.0
        if st.dash and total / max(sum(st.dash[0]), 1e-9) > MAX_REPEATS:
            st = st._replace(dash=None)
        if len(q) == 1:
            if rect[0] <= q[0][0] <= rect[2] and rect[1] <= q[0][1] <= rect[3]:
                self.sheet.stroke(np.vstack([q[0], q[0]]), False, st._replace(cap=1, dash=None, width=max(st.width, self.min_width)))
                self.ops += 1
            return
        for piece, start in clip_polyline(q, rect):
            sty = st
            if st.dash and start > 0:
                arr, phase = st.dash
                sty = st._replace(dash=(arr, (phase + start) % sum(arr)))
            self.sheet.stroke(piece, False, sty)
            self.ops += 1
        if self.ops > MAX_OPS:
            raise R.PlotError("The drawing is too large to plot.")

    def emit_fill(self, rings, st, pstyle, M, evenodd):
        s, tx, ty = M
        x0, y0, x1, y1 = self.sheet.printable
        rect = (x0 - 50.0, y0 - 50.0, x1 + 50.0, y1 + 50.0)
        out = []
        off = np.array([tx, ty])
        for r in rings:
            a = np.asarray(r, dtype=float)
            if len(a) < 3:
                continue
            q = a * s + off
            lo, hi = q.min(axis=0), q.max(axis=0)
            if hi[0] < rect[0] or hi[1] < rect[1] or lo[0] > rect[2] or lo[1] > rect[3]:
                continue
            if lo[0] < rect[0] or lo[1] < rect[1] or hi[0] > rect[2] or hi[1] > rect[3]:
                q = clip_ring(q, rect)
                if q is None:
                    continue
            out.append(q)
        if not out:
            return
        fill = pstyle["fill"] if pstyle else "object"
        if fill not in ("object", "solid"):
            if self.pattern_fill(out, st, fill, evenodd):
                return
        self.sheet.fill(out, st, evenodd)
        self.ops += 1

    def pattern_fill(self, rings, st, kind, evenodd):
        allp = np.vstack(rings)
        x0, y0 = allp.min(axis=0)
        x1, y1 = allp.max(axis=0)
        step = 1.5
        w, h = x1 - x0, y1 - y0
        if (w / step + 1) * (h / step + 1) > FILL_CELLS:
            return False
        self.sheet.push_clip(rings, evenodd)
        line = st._replace(width=0.1, dash=None, cap=0)
        fillst = st
        gx0, gy0 = math.floor(x0 / step) * step, math.floor(y0 / step) * step
        xs = np.arange(gx0, x1 + step, step)
        ys = np.arange(gy0, y1 + step, step)
        segs = []
        if kind in ("horizontal", "crosshatch"):
            segs += [np.array([[x0 - 1, y], [x1 + 1, y]]) for y in ys]
        if kind in ("vertical", "crosshatch"):
            segs += [np.array([[x, y0 - 1], [x, y1 + 1]]) for x in xs]
        if kind in ("slant_right", "diamonds"):
            segs += [np.array([[c - (y0 - 1), y0 - 1], [c - (y1 + 1), y1 + 1]]) for c in (np.arange(math.floor((x0 + y0) / step) * step, x1 + y1 + step, step))]
        if kind in ("slant_left", "diamonds"):
            segs += [np.array([[x0 - 1, (x0 - 1) - c], [x1 + 1, (x1 + 1) - c]]) for c in (np.arange(math.floor((x0 - y1) / step) * step, x1 - y0 + step, step))]
        for sg in segs:
            self.sheet.stroke(sg, False, line)
        if kind == "dots":
            sq = [np.array([[x - 0.2, y - 0.2], [x + 0.2, y - 0.2], [x + 0.2, y + 0.2], [x - 0.2, y + 0.2]]) for x in xs for y in ys]
            self.sheet.fill(sq, fillst, False)
        if kind == "checkerboard":
            cell = 2.0
            cx0, cy0 = math.floor(x0 / cell), math.floor(y0 / cell)
            sq = []
            for i in range(int((w) / cell) + 2):
                for j in range(int((h) / cell) + 2):
                    if (i + j) % 2 == 0:
                        ax, ay = (cx0 + i) * cell, (cy0 + j) * cell
                        sq.append(np.array([[ax, ay], [ax + cell, ay], [ax + cell, ay + cell], [ax, ay + cell]]))
            self.sheet.fill(sq, fillst, False)
        self.sheet.pop_clip()
        self.ops += len(segs) + 2
        return True

    def geom_lines(self, g, tol, M, item_pp, depth=0):
        t = g["type"]
        if t == "line":
            return [(np.array([g["p1"][:2], g["p2"][:2]], dtype=float), False)]
        if t == "circle":
            pts = arc_points(g["c"][0], g["c"][1], g["r"], 0.0, 2 * math.pi, tol)
            return [(pts, False)]
        if t == "arc":
            sweep = (g["a1"] - g["a0"]) % (2 * math.pi) or 2 * math.pi
            return [(arc_points(g["c"][0], g["c"][1], g["r"], g["a0"], sweep, tol), False)]
        if t == "ellipse":
            c, mj, ratio = g["c"], g["major"], g["ratio"]
            sweep = g["a1"] - g["a0"]
            if sweep <= 0:
                sweep += 2 * math.pi
            a = math.hypot(mj[0], mj[1])
            n = max(16, min(8192, int(math.ceil(sweep / (2 * math.acos(max(-1.0, 1.0 - tol / max(a, tol * 2))))))))
            tt = g["a0"] + sweep * np.arange(n + 1) / n
            ux, uy = mj[0], mj[1]
            vx, vy = -uy * ratio, ux * ratio
            return [(np.column_stack([c[0] + ux * np.cos(tt) + vx * np.sin(tt), c[1] + uy * np.cos(tt) + vy * np.sin(tt)]), False)]
        if t == "spline":
            return [(spline_points(g, tol), False)]
        if t in ("ray", "xline"):
            s, tx, ty = M
            p = np.array(g["p"][:2], dtype=float)
            dv = np.array(g["dir"][:2], dtype=float)
            x0, y0, x1, y1 = self.sheet.printable
            pm = p * s + np.array([tx, ty])
            far = (math.hypot(x1 - x0, y1 - y0) + float(np.hypot(*(pm - np.array([(x0 + x1) / 2, (y0 + y1) / 2]))))) * 2.0 / s
            a = p - dv * far if t == "xline" else p
            return [(np.array([a, p + dv * far]), False)]
        return []

    def emit_geom(self, g, item, pp, M, depth=0):
        t = g["type"]
        s = M[0]
        tol = max(CHORD_MM / s, 1e-12)
        if t == "compound":
            if depth > 4:
                return
            for part in g["parts"]:
                sub = pp
                if "lw" in part or "color" in part:
                    sub = pp.derive(part)
                self.emit_geom(part, item, sub, M, depth + 1)
            return
        if t == "text":
            return
        if t == "poly":
            verts = g["verts"]
            widths = any((len(v) > 3 and (v[3] > 0 or v[4] > 0)) for v in verts)
            if widths:
                rings, thin = band_rings(verts, g["closed"], tol)
                if rings:
                    st, ps = pp.fill_style()
                    self.emit_fill(rings, st, ps, M, False)
                st, _ps = pp.stroke_style()
                for pts in thin:
                    self.emit_polyline(pts, False, st, M)
                return
            st, _ps = pp.stroke_style()
            self.emit_polyline(poly_points(verts, g["closed"], tol), g["closed"], st, M)
            return
        if t == "point":
            self.emit_point(g, pp, M)
            return
        st, _ps = pp.stroke_style()
        for pts, closed in self.geom_lines(g, tol, M, pp):
            self.emit_polyline(pts, closed, st, M)

    def emit_point(self, g, pp, M):
        s, tx, ty = M
        mode = int(g.get("mode", 0))
        base = mode & 7
        size = g.get("size", 0.0)
        if size > 0:
            h = size * s / 2.0
        else:
            x0, y0, x1, y1 = self.sheet.printable
            h = (y1 - y0) * g.get("rel", 5.0) / 100.0 / 2.0
        cx, cy = g["p"][0] * s + tx, g["p"][1] * s + ty
        st, ps = pp.stroke_style()
        one = (1.0, 0.0, 0.0)

        def seg(a, b, c, d):
            self.sheet.stroke(np.array([[a, b], [c, d]]), False, st)
            self.ops += 1

        if base == 0:
            half = max(st.width, 0.3) / 2.0
            self.sheet.fill([np.array([[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]])], pp.fill_style()[0], False)
            self.ops += 1
        if base == 2:
            seg(cx - h, cy, cx + h, cy)
            seg(cx, cy - h, cx, cy + h)
        elif base == 3:
            seg(cx - h, cy - h, cx + h, cy + h)
            seg(cx - h, cy + h, cx + h, cy - h)
        elif base == 4:
            seg(cx, cy, cx, cy + h)
        if mode & 32:
            self.sheet.stroke(arc_points(cx, cy, h, 0.0, 2 * math.pi, CHORD_MM), False, st)
        if mode & 64:
            self.sheet.stroke(np.array([[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h], [cx - h, cy - h]]), False, st)

    def emit_image(self, p, pp, M):
        from app.doc import underlays as U

        e = self.d.ents.get(pp.item["h"])
        if e is None or e.kind != "underlay":
            return
        full = U.resolve(e.path, U.folder_of(self.doc))
        if not full or not U.kind_of(full):
            return
        s, tx, ty = M
        c = np.array(p["pts"], dtype=float).reshape(3, 2) * s + np.array([tx, ty])
        clip = None
        if p.get("clip"):
            clip = np.array(p["clip"], dtype=float).reshape(-1, 2) * s + np.array([tx, ty])
            self.sheet.push_clip([clip], False)
        alpha = 1.0 - max(0.0, min(100.0, float(p.get("fade", 0)))) / 100.0
        self.sheet.image({"path": full, "page": int(e.page), "source": e.source}, c, alpha, pp.layer_key())
        if clip is not None:
            self.sheet.pop_clip()
        self.ops += 3

    def emit_prims(self, prims, pp, M):
        for p in prims:
            if p.get("noplot"):
                continue
            sub = pp
            if "c" in p:
                sub = pp.derive({"color": p["c"], "color7": bool(p.get("c7"))})
            kind = p["t"]
            if kind == "img":
                self.emit_image(p, sub, M)
            elif kind == "pl":
                a = np.array(p["pts"], dtype=float).reshape(-1, 2)
                st, _ps = sub.stroke_style()
                self.emit_polyline(a, bool(p.get("closed")), st, M)
            elif kind == "tri":
                a = np.array(p["pts"], dtype=float).reshape(-1, 3, 2)
                st, ps = sub.fill_style()
                for k in range(0, len(a), 20000):
                    self.emit_fill(list(a[k:k + 20000]), st, ps, M, False)
            elif kind == "fill":
                rings = [np.array(r, dtype=float).reshape(-1, 2) for r in p["rings"]]
                if p.get("mask"):
                    st = Style((255, 255, 255), 1.0, 0.0, 1, 1, None, sub.layer_key())
                    self.emit_fill(rings, st, None, M, True)
                else:
                    st, ps = sub.fill_style()
                    self.emit_fill(rings, st, ps, M, True)

    def emit_glyphs(self, info, pp, M):
        s, tx, ty = M
        by = {}
        for emb, gid, m, ckey in info["glyphs"]:
            by.setdefault(id(emb), []).append((emb, gid, m, ckey))
        for run in by.values():
            groups = {}
            for emb, gid, m, ckey in run:
                groups.setdefault(ckey, []).append((emb, gid, m))
            for ckey, lst in groups.items():
                sub = pp
                if ckey is not None:
                    if ckey[0] == "i":
                        sub = pp.derive({"color": list(palette.index_rgb(ckey[1])), "color7": ckey[1] == 7})
                    elif ckey[0] == "c7":
                        sub = pp.derive({"color": [255, 255, 255], "color7": True})
                    else:
                        sub = pp.derive({"color": list(ckey[1:4]), "color7": False})
                st, _ps = sub.fill_style()
                emb = lst[0][0]
                glyphs = []
                for e2, gid, m in lst:
                    k = e2.em_over_cap
                    a, b, c, dd, e, f = m
                    glyphs.append((gid, a * k * s, b * k * s, c * k * s, dd * k * s, e * s + tx, f * s + ty))
                self.sheet.text(emb, glyphs, st)
                self.ops += 1

    def bounds_mm(self, b, M):
        s, tx, ty = M
        return [b[0] * s + tx, b[1] * s + ty, b[2] * s + tx, b[3] * s + ty]

    def item_ctx(self, item, M, vp, texts, layers):
        return ItemProps(self, item, M, vp, layers)

    def draw_items(self, key, M):
        src = self.cache.get(key)
        self.spaceKey = key
        self.draw_list(src["items"], src, M, key != "model")

    def draw_list(self, items, src, M, paper=False, vpm=None, vp=None):
        layers = src["layers"]
        texts = src["texts"] if self.real_text else {}
        saved = self.spaceKey
        for item in sorted(items, key=lambda it: it["kind"] != "underlay"):
            lname = item["layer"]
            rec = layers.get(lname)
            on = True if rec is None else bool(rec["on"])
            if rec is not None and rec.get("frozen"):
                continue
            if not on and not self.include_off:
                continue
            if not item.get("plot", True):
                continue
            if paper and item["kind"] == "viewport":
                self.draw_viewport(item, M)
                self.spaceKey = saved
            pp = ItemProps(self, item, M, vp, rec)
            info = texts.get(item["h"])
            if info is not None and vpm is not None:
                e = self.d.ents.get(item["h"])
                if e is None or e.annotation_scales or abs(vpm[1]) > 1e-12 or abs(vpm[2]) > 1e-12:
                    info = None
            if info is not None:
                M2 = M if vpm is None else (M[0] * vpm[0], M[0] * vpm[4] + M[1], M[0] * vpm[5] + M[2])
                self.emit_geom(info["geom"], item, pp, M2)
                self.emit_prims(info["prims"], pp, M2)
                self.emit_glyphs(info, pp, M2)
            elif item["kind"] == "underlay":
                self.emit_prims(item["prims"] or [], pp, M)
                self.emit_geom(item["geom"], item, pp, M)
            else:
                self.emit_geom(item["geom"], item, pp, M)
                if item["prims"]:
                    self.emit_prims(item["prims"], pp, M)
            self.note_link(item, M)

    def note_link(self, item, M):
        url = self.links.get(item["h"])
        if url is None:
            e = self.d.ents.get(item["h"])
            if e is not None and e.xdata:
                v = e.xdata.get("PE_URL")
                url = v if isinstance(v, str) else (v[0] if isinstance(v, (list, tuple)) and v and isinstance(v[0], str) else None)
        if url is None or item.get("bounds") is None:
            return
        r = self.bounds_mm(item["bounds"], M)
        x0, y0, x1, y1 = self.sheet.printable
        r = [max(r[0], x0), max(r[1], y0), min(r[2], x1), min(r[3], y1)]
        if r[2] > r[0] and r[3] > r[1]:
            self.sheet.link(r, url)

    def draw_viewport(self, item, M):
        from app.display import layout_view as LV

        vp = self.d.ents.get(item["h"])
        if vp is None or not vp.on:
            return
        rec = self.d.tables["layers"].get(vp.layer)
        if rec is not None and rec.get("frozen", False):
            return
        msrc = self.cache.get("model")
        if self.vp_state is None:
            ms = state_for(self.doc, "model")
            ms.update(self.doc)
            self.vp_state = ms
        items = LV.viewport_items(self.doc, vp, self.vp_state, msrc["ctx"])
        s, tx, ty = M
        outline = np.array(vp.outline_points(), dtype=float) * s + np.array([tx, ty])
        self.sheet.push_clip([outline], False)
        self.spaceKey = "model"
        self.draw_list(items, msrc, M, False, LV._matrix(vp), vp)
        self.sheet.pop_clip()

    def build(self):
        spec = self.spec
        d = self.d
        if spec["model"]:
            key = "model"
            src = self.cache.get(key)
            area = self.area_model(src)
            M = R.placement(spec, area)
            clip = None
            if spec["area"] == "window":
                s, tx, ty = M
                w = spec["window"]
                clip = rect_ring([w[0] * s + tx, w[1] * s + ty, w[2] * s + tx, w[3] * s + ty])
                self.sheet.push_clip([clip], False)
            self.draw_items(key, M)
            if clip is not None:
                self.sheet.pop_clip()
            if self.sheet.empty:
                raise R.PlotError("The plot area is empty.")
            return self.sheet
        key = "layout:" + spec["name"]
        wl, hl = L.sheet_units(d, spec["ps"])
        area = [0.0, 0.0, wl, hl]
        if spec["area"] not in ("layout",):
            src = self.cache.get(key)
            area = self.area_from(src, spec) or area
        M = R.placement(spec, area)
        self.draw_items(key, M)
        return self.sheet

    def plottable(self, src):
        out = []
        for it in src["items"]:
            rec = src["layers"].get(it["layer"])
            if rec is not None and (rec.get("frozen") or (not rec["on"] and not self.include_off)):
                continue
            if not it.get("plot", True) or it.get("bounds") is None:
                continue
            out.append(it["bounds"])
        return out

    def area_model(self, src):
        a = self.spec["area"]
        d = self.d
        if a == "window":
            return list(self.spec["window"])
        if a == "display":
            v = self.req.get("view") or self.doc.view
            h = float(v["height"])
            w = float(v.get("width") or 0.0) or h * 1.6
            c = v["center"]
            return [c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2]
        if a == "limits":
            lo = d.header.get("LIMMIN") or [0.0, 0.0]
            hi = d.header.get("LIMMAX")
            if hi and hi[0] > lo[0] and hi[1] > lo[1]:
                return [lo[0], lo[1], hi[0], hi[1]]
        return self.extents(src)

    def area_from(self, src, spec):
        a = spec["area"]
        if a == "window":
            return list(spec["window"])
        if a == "display":
            v = self.req.get("view") or self.doc.view
            h = float(v["height"])
            w = float(v.get("width") or 0.0) or h * 1.6
            c = v["center"]
            return [c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2]
        return self.extents(src)

    def extents(self, src):
        bs = self.plottable(src)
        if not bs:
            raise R.PlotError("The plot area is empty.")
        a = np.array(bs, dtype=float)
        return [float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 2].max()), float(a[:, 3].max())]


class ItemProps:
    def __init__(self, sb, item, M, vp, rec, over=None):
        self.sb = sb
        self.item = item
        self.M = M
        self.vp = vp
        self.rec = rec
        self.rgb = tuple(item["color"])
        self.c7 = bool(item["color7"])
        self.lw = float(item["lw"])
        self.lt = item["lt"]
        self.tr = float(item["tr"])
        self.layer = item["layer"]
        self.on = True if rec is None else bool(rec["on"])
        self.ps_name = "Normal"
        e = sb.d.ents.get(item["h"])
        if e is not None:
            ps = e.plot_style
            if str(ps).casefold() in ("bylayer", ""):
                lrec = sb.d.table_get("layers", item["layer"])
                ps = lrec.get("plot_style") if lrec else "Normal"
            elif str(ps).casefold() == "byblock":
                ps = "Normal"
            self.ps_name = ps or "Normal"
        if vp is not None:
            ov = vp.overrides.get(item["layer"].casefold())
            if ov and ov.get("plot_style"):
                self.ps_name = ov["plot_style"]

    def derive(self, part):
        c = ItemProps.__new__(ItemProps)
        c.__dict__.update(self.__dict__)
        if "color" in part:
            c.rgb = tuple(part["color"])
            c.c7 = bool(part.get("color7", False) or part.get("c7", False))
        if "lw" in part:
            c.lw = float(part["lw"])
        if "lt" in part:
            c.lt = part["lt"]
        return c

    def layer_key(self):
        return self.sb.layer_key(self.layer, self.on)

    def stroke_style(self):
        return self.sb.style(self.rgb, self.c7, self.lw, self.lt, self.tr, self.layer, self.on, None, self.ps_name, self.M[0], self.sb.cache.get(self.sb.spaceKey)["ctx"].ltscale)

    def fill_style(self):
        st, ps = self.stroke_style()
        return st._replace(dash=None), ps
