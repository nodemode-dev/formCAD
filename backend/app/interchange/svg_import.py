import gzip
import io
import math
import re
import xml.etree.ElementTree as ET

from app.interchange.errors import InterchangeError, Report

MM_PER_PX = 25.4 / 96.0
MAX_BYTES = 64 * 1024 * 1024
MAX_ELEMENTS = 500_000
MAX_SEGMENTS = 100_000
MAX_VERTS = 100_001
MAX_GROUP_DEPTH = 64
MAX_XML_DEPTH = 400
MAX_LAYERS = 256
MAX_GENERATED = 8_000_000
MAX_CHORDS = 10_000
INK = "http://www.inkscape.org/namespaces/inkscape"
SVGNS = "http://www.w3.org/2000/svg"
NUM = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
UNITS = {"px": MM_PER_PX, "mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0, "pc": 25.4 / 6.0, "": MM_PER_PX}
CONTAINERS = {"g", "svg", "a", "switch"}
SKIPPED = {"defs", "symbol", "clippath", "mask", "pattern", "marker", "lineargradient", "radialgradient", "filter", "title", "desc", "metadata", "style", "script", "namedview"}
SHAPES = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"}
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def parse_length(text, default=None):
    if text is None:
        return default
    t = str(text).strip()
    mt = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)$", t)
    if not mt:
        return default
    unit = mt.group(2).lower()
    if unit == "%" or unit not in UNITS:
        return default
    return float(mt.group(1)) * UNITS[unit]


def parse_transform(text):
    m = IDENT
    if not text:
        return m
    for fn, args in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", text):
        vals = [float(v) for v in NUM.findall(args)]
        fn = fn.lower()
        if fn == "matrix" and len(vals) == 6:
            t = tuple(vals)
        elif fn == "translate" and vals:
            t = (1.0, 0.0, 0.0, 1.0, vals[0], vals[1] if len(vals) > 1 else 0.0)
        elif fn == "scale" and vals:
            t = (vals[0], 0.0, 0.0, vals[1] if len(vals) > 1 else vals[0], 0.0, 0.0)
        elif fn == "rotate" and vals:
            a = math.radians(vals[0])
            c, s = math.cos(a), math.sin(a)
            t = (c, s, -s, c, 0.0, 0.0)
            if len(vals) >= 3:
                t = mul(mul((1.0, 0.0, 0.0, 1.0, vals[1], vals[2]), t), (1.0, 0.0, 0.0, 1.0, -vals[1], -vals[2]))
        elif fn == "skewx" and vals:
            t = (1.0, 0.0, math.tan(math.radians(vals[0])), 1.0, 0.0, 0.0)
        elif fn == "skewy" and vals:
            t = (1.0, math.tan(math.radians(vals[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = mul(m, t)
    return m


def tokenize_path(d: str):
    i, n = 0, len(d)
    out = []
    cmd = None
    argc = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}
    while i < n:
        ch = d[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch.isalpha():
            if ch.lower() not in argc:
                raise ValueError("bad command " + ch)
            cmd = ch
            i += 1
            if ch.lower() == "z":
                out.append((ch, []))
                cmd = None
            continue
        if cmd is None:
            raise ValueError("number before command")
        k = argc[cmd.lower()]
        vals = []
        for j in range(k):
            while i < n and d[i] in " \t\r\n,":
                i += 1
            if cmd.lower() == "a" and j in (3, 4):
                if i < n and d[i] in "01":
                    vals.append(float(d[i]))
                    i += 1
                    continue
                raise ValueError("bad arc flag")
            m = NUM.match(d, i)
            if not m:
                raise ValueError("bad number")
            vals.append(float(m.group(0)))
            i = m.end()
        out.append((cmd, vals))
        if cmd == "m":
            cmd = "l"
        elif cmd == "M":
            cmd = "L"
    return out


def arc_center(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2):
    if rx == 0 or ry == 0:
        return None
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg % 360.0)
    c, s = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = c * dx2 + s * dy2
    y1p = -s * dx2 + c * dy2
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        k = math.sqrt(lam)
        rx, ry = rx * k, ry * k
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = c * cxp - s * cyp + (x1 + x2) / 2.0
    cy = s * cxp + c * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    th1 = ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    return cx, cy, rx, ry, phi, th1, dth


def arc_to_cubics(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2):
    cen = arc_center(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2)
    if cen is None:
        return None
    cx, cy, rx, ry, phi, th1, dth = cen
    n = max(1, int(math.ceil(abs(dth) / (math.pi / 2) - 1e-9)))
    step = dth / n
    t = 4.0 / 3.0 * math.tan(step / 4.0)
    c, s = math.cos(phi), math.sin(phi)
    segs = []
    a = th1
    for _ in range(n):
        b = a + step
        pts = []
        for ang_, k in ((a, 0), (b, 1)):
            pass
        p0 = (math.cos(a), math.sin(a))
        p3 = (math.cos(b), math.sin(b))
        p1 = (p0[0] - t * p0[1], p0[1] + t * p0[0])
        p2 = (p3[0] + t * p3[1], p3[1] - t * p3[0])
        mp = []
        for px, py in (p1, p2, p3):
            X, Y = rx * px, ry * py
            mp.append((c * X - s * Y + cx, s * X + c * Y + cy))
        segs.append(tuple(mp))
        a = b
    return segs


class Importer:
    def __init__(self, report: Report):
        self.r = report
        self.ents = []
        self.layers = []
        self.elements = 0
        self.generated = 0
        self.skipped = {}
        self.notes = set()
        self.layer_names = {}
        self.page = (1.0, 1.0)

    def skip(self, what: str) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + 1

    def load(self, root) -> None:
        w = parse_length(root.get("width"))
        h = parse_length(root.get("height"))
        vb = None
        if root.get("viewBox"):
            v = [float(x) for x in NUM.findall(root.get("viewBox"))]
            if len(v) == 4 and v[2] > 0 and v[3] > 0:
                vb = v
        if vb is not None:
            if w is None and h is None:
                w, h = vb[2] * MM_PER_PX, vb[3] * MM_PER_PX
            elif w is None:
                w = h * vb[2] / vb[3]
            elif h is None:
                h = w * vb[3] / vb[2]
        else:
            w = w if w is not None else 210.0
            h = h if h is not None else 297.0
        self.page = (w, h)
        if vb is not None:
            par = (root.get("preserveAspectRatio") or "xMidYMid meet").split()
            par = [p for p in par if p != "defer"]
            align = par[0] if par else "xMidYMid"
            sx, sy = w / vb[2], h / vb[3]
            if align == "none":
                m = (sx, 0.0, 0.0, sy, -vb[0] * sx, -vb[1] * sy)
            else:
                slice_ = len(par) > 1 and par[1] == "slice"
                s = max(sx, sy) if slice_ else min(sx, sy)
                tx = (w - vb[2] * s)
                ty = (h - vb[3] * s)
                fx = {"xMin": 0.0, "xMid": 0.5, "xMax": 1.0}.get(align[:4], 0.5)
                fy = {"YMin": 0.0, "YMid": 0.5, "YMax": 1.0}.get(align[4:], 0.5)
                m = (s, 0.0, 0.0, s, -vb[0] * s + tx * fx, -vb[1] * s + ty * fy)
        else:
            m = (MM_PER_PX, 0.0, 0.0, MM_PER_PX, 0.0, 0.0)
        flip = (1.0, 0.0, 0.0, -1.0, 0.0, h)
        base = mul(flip, m)
        self.walk(root, base, 0, "0", True)

    def tag(self, el) -> str:
        t = el.tag
        if isinstance(t, str) and "}" in t:
            t = t.split("}", 1)[1]
        return str(t).lower()

    def hidden(self, el) -> bool:
        if (el.get("display") or "").strip().lower() == "none":
            return True
        style = el.get("style") or ""
        for part in style.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                if k.strip().lower() == "display" and v.strip().lower() == "none":
                    return True
        return False

    def layer_for(self, el, current: str) -> str:
        if el.get("{%s}groupmode" % INK) == "layer":
            label = el.get("{%s}label" % INK) or el.get("id") or "Layer"
            label = re.sub(r'[<>/\\":;?*|,=`]', "_", label).strip() or "Layer"
            key = label.casefold()
            if key not in self.layer_names:
                if len(self.layer_names) >= MAX_LAYERS:
                    self.notes.add("More than %d layers: the rest went to layer 0." % MAX_LAYERS)
                    return current
                self.layer_names[key] = label
                self.layers.append(label)
            return self.layer_names[key]
        return current

    def walk(self, el, m, depth, layer, is_root=False):
        if depth > MAX_GROUP_DEPTH:
            raise InterchangeError("The SVG nests groups deeper than %d levels." % MAX_GROUP_DEPTH, "toodeep")
        for ch in list(el):
            t = self.tag(ch)
            if not isinstance(ch.tag, str):
                continue
            if t in SKIPPED:
                if t not in ("title", "desc", "metadata", "namedview", "style"):
                    self.skip(t)
                elif t == "style" and (ch.text or "").strip():
                    self.skip("style rules")
                continue
            if self.hidden(ch):
                continue
            self.elements += 1
            if self.elements > MAX_ELEMENTS:
                raise InterchangeError("The SVG has more than %d elements." % MAX_ELEMENTS, "toolarge")
            if t in CONTAINERS:
                cm = mul(m, parse_transform(ch.get("transform")))
                if t == "svg" and ch.get("x") is not None:
                    pass
                self.walk(ch, cm, depth + 1, self.layer_for(ch, layer))
            elif t in SHAPES:
                try:
                    self.shape(ch, t, mul(m, parse_transform(ch.get("transform"))), layer)
                except InterchangeError:
                    raise
                except Exception as err:
                    self.skip("shapes that could not be read")
                    self.notes.add("A %s was skipped: %s" % (t, err))
            elif t in ("use", "text", "image", "foreignobject", "tspan"):
                self.skip({"use": "use references", "text": "text", "image": "embedded images", "foreignobject": "foreign objects", "tspan": "text"}[t])
            else:
                self.skip(t)

    def add(self, ent, layer) -> None:
        ent.layer = layer
        self.ents.append(ent)

    def count(self, n: int) -> None:
        self.generated += n
        if self.generated > MAX_GENERATED:
            raise InterchangeError("The SVG would create more than %d vertices." % MAX_GENERATED, "toolarge")

    def shape(self, el, t, m, layer) -> None:
        from app.doc.entities import Circle, Ellipse, Line, LwPolyline

        f = lambda k, dflt=0.0: (parse_length(el.get(k), None) / MM_PER_PX if parse_length(el.get(k), None) is not None else dflt)
        if t == "line":
            a = apply(m, f("x1"), f("y1"))
            b = apply(m, f("x2"), f("y2"))
            if math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-12:
                self.add(Line(start=[a[0], a[1], 0.0], end=[b[0], b[1], 0.0]), layer)
        elif t == "rect":
            x, y, w, h = f("x"), f("y"), f("width"), f("height")
            if w <= 0 or h <= 0:
                return
            if (el.get("rx") not in (None, "0") or el.get("ry") not in (None, "0")):
                self.skip("rounded rectangle corners")
            pts = [apply(m, x, y), apply(m, x + w, y), apply(m, x + w, y + h), apply(m, x, y + h)]
            self.add(LwPolyline.from_points(pts, closed=True), layer)
        elif t in ("circle", "ellipse"):
            if t == "circle":
                rx = ry = f("r")
            else:
                rx, ry = f("rx"), f("ry")
            if rx <= 0 or ry <= 0:
                return
            cx, cy = f("cx"), f("cy")
            a, b, c, d = m[0], m[1], m[2], m[3]
            ax, ay = a * rx, b * rx
            bx, by = c * ry, d * ry
            ctr = apply(m, cx, cy)
            sa = math.hypot(ax, ay)
            sb = math.hypot(bx, by)
            dot = ax * bx + ay * by
            if t == "circle" and abs(sa - sb) <= 1e-9 * max(sa, sb) and abs(dot) <= 1e-9 * sa * sb:
                self.add(Circle(center=[ctr[0], ctr[1], 0.0], radius=sa), layer)
                return
            if abs(sa - sb) <= 1e-9 * max(sa, sb) and abs(dot) <= 1e-9 * sa * sb:
                self.add(Circle(center=[ctr[0], ctr[1], 0.0], radius=sa), layer)
                return
            # singular value decomposition of [[ax, bx], [ay, by]]
            E = (ax + by) / 2.0
            F = (ax - by) / 2.0
            G = (ay + bx) / 2.0
            H = (ay - bx) / 2.0
            q = math.hypot(E, H)
            r = math.hypot(F, G)
            smax, smin = q + r, abs(q - r)
            a1 = math.atan2(G, F)
            a2 = math.atan2(H, E)
            theta = (a2 - a1) / 2.0
            if smax <= 1e-12:
                return
            ratio = max(smin / smax, 1e-6)
            major = [smax * math.cos(theta + 0), smax * math.sin(theta + 0), 0.0]
            beta = (a2 + a1) / 2.0
            major = [smax * math.cos(beta), smax * math.sin(beta), 0.0]
            self.add(Ellipse(center=[ctr[0], ctr[1], 0.0], major=major, ratio=ratio), layer)
        elif t in ("polyline", "polygon"):
            vals = [float(v) for v in NUM.findall(el.get("points") or "")]
            pts = [apply(m, vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]
            if len(pts) > MAX_VERTS:
                pts = pts[:MAX_VERTS]
                self.notes.add("A polyline was cut to %d vertices." % MAX_VERTS)
            self.count(len(pts))
            if len(pts) >= 2:
                self.add(LwPolyline.from_points(pts, closed=(t == "polygon")), layer)
        elif t == "path":
            self.path(el.get("d") or "", m, layer)

    def path(self, d: str, m, layer) -> None:
        try:
            toks = tokenize_path(d)
        except ValueError as err:
            self.notes.add("A path stopped at an error (%s); the part before it was kept." % err)
            toks = []
            try:
                toks = self.partial_tokens(d)
            except Exception:
                toks = []
        if len(toks) > MAX_SEGMENTS:
            raise InterchangeError("A path has more than %d segments." % MAX_SEGMENTS, "toolarge")
        subs = []
        cur = None
        pos = (0.0, 0.0)
        start = (0.0, 0.0)
        last_c = None
        last_q = None
        prev = ""
        first = True
        for cmd, v in toks:
            lo = cmd.lower()
            rel = cmd.islower()
            if first and lo != "m":
                break
            first = False
            ox, oy = (pos if rel else (0.0, 0.0))
            if lo == "m":
                p = (ox + v[0], oy + v[1]) if not (rel and not subs and cur is None and False) else (v[0], v[1])
                cur = {"start": p, "segs": [], "closed": False}
                subs.append(cur)
                pos = start = p
                last_c = last_q = None
            elif lo == "z":
                if cur is not None:
                    cur["closed"] = True
                    if math.hypot(pos[0] - start[0], pos[1] - start[1]) > 1e-12:
                        cur["segs"].append(("L", pos, start))
                    pos = start
                    cur = {"start": pos, "segs": [], "closed": False}
                    subs.append(cur)
                last_c = last_q = None
            else:
                if cur is None:
                    break
                if lo == "l":
                    p = (ox + v[0], oy + v[1])
                    cur["segs"].append(("L", pos, p))
                    pos = p
                    last_c = last_q = None
                elif lo == "h":
                    p = ((pos[0] + v[0]) if rel else v[0], pos[1])
                    cur["segs"].append(("L", pos, p))
                    pos = p
                    last_c = last_q = None
                elif lo == "v":
                    p = (pos[0], (pos[1] + v[0]) if rel else v[0])
                    cur["segs"].append(("L", pos, p))
                    pos = p
                    last_c = last_q = None
                elif lo == "c":
                    c1, c2, p = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3]), (ox + v[4], oy + v[5])
                    cur["segs"].append(("C", pos, c1, c2, p))
                    pos, last_c, last_q = p, c2, None
                elif lo == "s":
                    c1 = (2 * pos[0] - last_c[0], 2 * pos[1] - last_c[1]) if last_c is not None else pos
                    c2, p = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3])
                    cur["segs"].append(("C", pos, c1, c2, p))
                    pos, last_c, last_q = p, c2, None
                elif lo == "q":
                    q, p = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3])
                    cur["segs"].append(self.quad(pos, q, p))
                    pos, last_q, last_c = p, q, None
                elif lo == "t":
                    q = (2 * pos[0] - last_q[0], 2 * pos[1] - last_q[1]) if last_q is not None else pos
                    p = (ox + v[0], oy + v[1])
                    cur["segs"].append(self.quad(pos, q, p))
                    pos, last_q, last_c = p, q, None
                elif lo == "a":
                    p = (ox + v[5], oy + v[6])
                    if math.hypot(p[0] - pos[0], p[1] - pos[1]) > 1e-15:
                        cur["segs"].append(("A", pos, v[0], v[1], v[2], int(v[3]), int(v[4]), p))
                    pos = p
                    last_c = last_q = None
        for sub in subs:
            if sub["segs"]:
                self.emit(sub, m, layer)

    def partial_tokens(self, d: str):
        out = []
        for i in range(len(d), 0, -1):
            try:
                return tokenize_path(d[:i])
            except ValueError:
                continue
        return out

    def quad(self, p0, q, p):
        c1 = (p0[0] + 2.0 / 3.0 * (q[0] - p0[0]), p0[1] + 2.0 / 3.0 * (q[1] - p0[1]))
        c2 = (p[0] + 2.0 / 3.0 * (q[0] - p[0]), p[1] + 2.0 / 3.0 * (q[1] - p[1]))
        return ("C", p0, c1, c2, p)

    def emit(self, sub, m, layer) -> None:
        from app.doc.entities import Line, LwPolyline, Spline

        a, b, c, d = m[0], m[1], m[2], m[3]
        sa, sb = math.hypot(a, b), math.hypot(c, d)
        similar = abs(sa - sb) <= 1e-9 * max(sa, sb, 1e-300) and abs(a * c + b * d) <= 1e-9 * max(sa * sb, 1e-300)
        det = a * d - b * c
        runs = []
        for seg in sub["segs"]:
            kind = seg[0]
            if kind == "A":
                _k, p0, rx, ry, phi, fa, fs, p1 = seg
                circ = abs(abs(rx) - abs(ry)) <= 1e-9 * max(abs(rx), abs(ry), 1e-300)
                cen = arc_center(p0[0], p0[1], rx, ry, phi, fa, fs, p1[0], p1[1])
                if cen is None:
                    seg = ("L", p0, p1)
                    kind = "L"
                elif circ and similar:
                    runs.append(("P", ("arc", p0, p1, cen)))
                    continue
                elif circ:
                    n = max(4, min(MAX_CHORDS, int(abs(cen[6]) / (math.pi / 36)) + 1))
                    pts = [(cen[0] + cen[2] * math.cos(cen[5] + cen[6] * i / n), cen[1] + cen[2] * math.sin(cen[5] + cen[6] * i / n)) for i in range(1, n + 1)]
                    self.count(n)
                    prevp = p0
                    for q in pts:
                        runs.append(("P", ("line", prevp, q)))
                        prevp = q
                    continue
                else:
                    cubs = arc_to_cubics(p0[0], p0[1], rx, ry, phi, fa, fs, p1[0], p1[1])
                    q0 = p0
                    for c1, c2, q in cubs:
                        runs.append(("B", (q0, c1, c2, q)))
                        q0 = q
                    continue
            if kind == "L":
                runs.append(("P", ("line", seg[1], seg[2])))
            elif kind == "C":
                runs.append(("B", (seg[1], seg[2], seg[3], seg[4])))
        groups = []
        for typ, data in runs:
            if groups and groups[-1][0] == typ:
                groups[-1][1].append(data)
            else:
                groups.append((typ, [data]))
        whole = len(groups) == 1
        for typ, items in groups:
            if typ == "P":
                verts = []
                for idx, it in enumerate(items):
                    p0 = apply(m, it[1][0], it[1][1])
                    bulge = 0.0
                    if it[0] == "arc":
                        cen = it[3]
                        bulge = math.tan(cen[6] / 4.0)
                        if det < 0:
                            bulge = -bulge
                    verts.append({"p": [p0[0], p0[1]], "bulge": bulge, "sw": 0.0, "ew": 0.0})
                    if idx == len(items) - 1:
                        pe = apply(m, it[2][0], it[2][1])
                        verts.append({"p": [pe[0], pe[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0})
                closed = False
                if whole and sub["closed"] and len(verts) > 2:
                    f0, l0 = verts[0]["p"], verts[-1]["p"]
                    if math.hypot(f0[0] - l0[0], f0[1] - l0[1]) < 1e-9:
                        verts.pop()
                        closed = True
                if len(verts) > MAX_VERTS:
                    verts = verts[:MAX_VERTS]
                    self.notes.add("A path was cut to %d vertices." % MAX_VERTS)
                self.count(len(verts))
                if len(verts) >= 2:
                    if len(verts) == 2 and not closed and abs(verts[0]["bulge"]) < 1e-15:
                        self.add(Line(start=[verts[0]["p"][0], verts[0]["p"][1], 0.0], end=[verts[1]["p"][0], verts[1]["p"][1], 0.0]), layer)
                    else:
                        self.add(LwPolyline(vertices=verts, closed=closed), layer)
            else:
                ctrl = []
                n = len(items)
                if n > MAX_VERTS // 3:
                    items = items[: MAX_VERTS // 3]
                    n = len(items)
                    self.notes.add("A curve was cut to %d control points." % MAX_VERTS)
                p = apply(m, items[0][0][0], items[0][0][1])
                ctrl.append([p[0], p[1], 0.0])
                for it in items:
                    for q in it[1:]:
                        pq = apply(m, q[0], q[1])
                        ctrl.append([pq[0], pq[1], 0.0])
                knots = [0.0] * 4
                for i in range(1, n):
                    knots += [float(i)] * 3
                knots += [float(n)] * 4
                self.count(len(ctrl))
                sp = Spline(degree=3, knots=knots, control_points=ctrl, closed=False)
                self.add(sp, layer)


def read_svg_bytes(data: bytes, gz: bool = False):
    if gz or data[:2] == b"\x1f\x8b":
        if data[:2] != b"\x1f\x8b":
            raise InterchangeError("The SVGZ file is not a valid gzip stream.", "badgzip")
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                data = g.read(MAX_BYTES + 1)
        except (OSError, EOFError, ValueError) as err:
            raise InterchangeError("The SVGZ file is not a valid gzip stream: %s" % err, "badgzip")
        if len(data) > MAX_BYTES:
            raise InterchangeError("The SVGZ file expands to more than 64 MiB.", "toolarge")
    if len(data) > MAX_BYTES:
        raise InterchangeError("The SVG file is larger than 64 MiB.", "toolarge")
    head = data[:65536].lower()
    if b"<!doctype" in head or b"<!entity" in data[:1048576].lower():
        raise InterchangeError("The SVG declares a document type or entities, which are not accepted.", "unsafe")
    depth = 0
    root = None
    try:
        parser = ET.XMLParser()
        it = ET.iterparse(io.BytesIO(data), events=("start", "end"), parser=parser)
        for ev, el in it:
            if ev == "start":
                depth += 1
                if depth > MAX_XML_DEPTH:
                    raise InterchangeError("The SVG nests elements deeper than %d levels." % MAX_XML_DEPTH, "toodeep")
                if root is None:
                    root = el
            else:
                depth -= 1
    except ET.ParseError as err:
        raise InterchangeError("The SVG is not well formed XML: %s" % err, "badxml")
    if root is None or not str(root.tag).lower().endswith("svg"):
        raise InterchangeError("The file is not an SVG document.", "notsvg")
    return root


def import_svg(path_or_bytes, report: Report | None = None, gz: bool = False):
    report = report or Report()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        import os

        p = os.path.expanduser(str(path_or_bytes))
        try:
            if os.path.getsize(p) > MAX_BYTES * (1 if not (gz or p.lower().endswith(".svgz")) else 1) and not (gz or p.lower().endswith(".svgz")):
                raise InterchangeError("The SVG file is larger than 64 MiB.", "toolarge")
            with open(p, "rb") as fh:
                data = fh.read(MAX_BYTES + 1 if not (gz or p.lower().endswith(".svgz")) else 512 * 1024 * 1024)
        except OSError as err:
            raise InterchangeError("Cannot open the file: %s" % err, "io")
        gz = gz or p.lower().endswith(".svgz")
    root = read_svg_bytes(data, gz)
    imp = Importer(report)
    imp.load(root)
    for what, n in imp.skipped.items():
        report.drop(what, n)
    for note in sorted(imp.notes):
        report.note(note)
    if imp.skipped:
        report.note("Not read: " + ", ".join(sorted(imp.skipped)) + ".")
    report.note("Page %.2f by %.2f mm." % imp.page)
    return imp.ents, imp.layers, imp.page, report
