import math
import os

from app.drawann import viewsrc

STYLE = {"sharp_v": "visible", "sharp_h": "hidden", "smooth_v": "tangent", "smooth_h": "hidden", "sewn_v": "tangent", "sewn_h": "hidden", "outline_v": "silhouette", "outline_h": "hidden"}
ORDER = ("sharp_v", "outline_v", "smooth_v", "sewn_v", "sharp_h", "smooth_h", "sewn_h", "outline_h")
NORMAL_ROLE = ((0.0, -1.0, 0.0, "front"), (0.0, 1.0, 0.0, "back"), (1.0, 0.0, 0.0, "right"), (-1.0, 0.0, 0.0, "left"), (0.0, 0.0, 1.0, "top"), (0.0, 0.0, -1.0, "bottom"))


def _dot(a, b):
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def frame(view):
    cache = view.cache or {}
    fr = cache.get("frame")
    if fr and fr.get("x") and fr.get("y"):
        return [float(c) for c in fr["x"]], [float(c) for c in fr["y"]]
    up = [float(c) for c in view.vup]
    n = [float(c) for c in view.vnormal]
    return _cross(up, n), up


def origin(view):
    o = (view.cache or {}).get("origin") or view.origin
    return [float(c) for c in o]


def unit_mm(d, view):
    return float(getattr(view, "unit_mm", 1.0) or 1.0)


def to_paper(d, view, p):
    k = float(view.scale) / unit_mm(d, view)
    return [float(view.position[0]) + k * p[0], float(view.position[1]) + k * p[1]]


def local_of(view, pt):
    x, y = frame(view)
    o = origin(view)
    v = [float(pt[i]) - o[i] for i in range(3)]
    return [_dot(v, x), _dot(v, y)]


def _component(view, rec):
    s = rec.get("s")
    items = (view.cache or {}).get("items") or []
    if s and 0 <= int(s[0]) < len(items):
        it = items[int(s[0])]
        return str(it.get("component") or it.get("handle") or "")
    return ""


def _ident(cls, i, rec):
    if rec.get("pid"):
        return "p%s" % rec["pid"]
    return "%s.%d" % (cls, i)


def _poly_edges(d, view, cls, i, rec, comp):
    pts = rec["pts"]
    return [{"id": "%s.%d" % (_ident(cls, i, rec), k), "type": "line", "p": [to_paper(d, view, pts[k]), to_paper(d, view, pts[k + 1])], "style": STYLE[cls], "component": comp} for k in range(len(pts) - 1)]


def edge_records(d, view) -> list:
    out = []
    used = set()
    classes = (view.cache or {}).get("classes") or {}
    for cls in ORDER:
        for i, rec in enumerate(classes.get(cls) or []):
            t = rec.get("t")
            comp = _component(view, rec)
            ident = _ident(cls, i, rec)
            if ident in used:
                ident = "%s.%d" % (ident, i)
            used.add(ident)
            base = {"id": ident, "style": STYLE[cls], "component": comp, "cls": cls}
            if t == "line":
                out.append(dict(base, type="line", p=[to_paper(d, view, rec["a"]), to_paper(d, view, rec["b"])]))
            elif t == "circle":
                out.append(dict(base, type="circle", c=to_paper(d, view, rec["c"]), r=float(rec["r"]) * float(view.scale) / unit_mm(d, view)))
            elif t == "arc":
                out.append(dict(base, type="arc", c=to_paper(d, view, rec["c"]), r=float(rec["r"]) * float(view.scale) / unit_mm(d, view), a0=float(rec["a0"]), a1=float(rec["a1"])))
            elif t == "poly":
                out.extend(_poly_edges(d, view, cls, i, rec, comp))
    return out


def _ends(rec):
    t = rec["t"]
    if t == "line":
        return list(rec["a"]), list(rec["b"])
    if t == "arc":
        c, r = rec["c"], float(rec["r"])
        return [c[0] + r * math.cos(rec["a0"]), c[1] + r * math.sin(rec["a0"])], [c[0] + r * math.cos(rec["a1"]), c[1] + r * math.sin(rec["a1"])]
    if t == "poly":
        return list(rec["pts"][0]), list(rec["pts"][-1])
    return list(rec["pts"][0]), list(rec["pts"][-1])


def _sampled(rec):
    t = rec["t"]
    if t == "ellipse":
        c, mj, q = rec["c"], rec["major"], float(rec["ratio"])
        a0, a1 = float(rec.get("a0", 0.0)), float(rec.get("a1", 2 * math.pi))
        if a1 <= a0:
            a1 += 2 * math.pi
        n = max(12, int(24 * (a1 - a0) / (2 * math.pi)) + 1)
        mn = [-mj[1] * q, mj[0] * q]
        return [[c[0] + mj[0] * math.cos(a0 + (a1 - a0) * k / n) + mn[0] * math.sin(a0 + (a1 - a0) * k / n), c[1] + mj[1] * math.cos(a0 + (a1 - a0) * k / n) + mn[1] * math.sin(a0 + (a1 - a0) * k / n)] for k in range(n + 1)]
    if t == "spline":
        pts = rec["ctrl"]
        return [list(p) for p in pts]
    return [list(p) for p in rec.get("pts", [])]


def _loop(curves, outer):
    verts = []
    if len(curves) == 1 and curves[0]["t"] == "circle":
        c, r = curves[0]["c"], float(curves[0]["r"])
        return {"vertices": [{"p": [c[0] + r, c[1]], "bulge": 1.0}, {"p": [c[0] - r, c[1]], "bulge": 1.0}], "outer": outer}
    cur = None
    for rec in curves:
        if rec["t"] in ("ellipse", "spline"):
            rec = {"t": "poly", "pts": _sampled(rec)}
        a, b = _ends(rec)
        rev = cur is not None and math.hypot(a[0] - cur[0], a[1] - cur[1]) > math.hypot(b[0] - cur[0], b[1] - cur[1])
        if rev:
            a, b = b, a
        if rec["t"] == "line":
            verts.append({"p": a, "bulge": 0.0})
        elif rec["t"] == "arc":
            sweep = (float(rec["a1"]) - float(rec["a0"])) % (2 * math.pi)
            bulge = math.tan(sweep / 4.0)
            verts.append({"p": a, "bulge": -bulge if rev else bulge})
        else:
            pts = rec["pts"][::-1] if rev else rec["pts"]
            for p in pts[:-1]:
                verts.append({"p": list(p), "bulge": 0.0})
        cur = b
    return {"vertices": verts, "outer": outer}


class DrawViewProvider:
    kinds = ("drawview",)

    def edges(self, d, view):
        return edge_records(d, view)

    def section_loops(self, d, view):
        out = []
        for fc in (view.cache or {}).get("faces") or []:
            comp = ""
            for loop, outer in [(fc.get("outer") or [], True)] + [(h, False) for h in fc.get("holes") or []]:
                if not loop:
                    continue
                lo = _loop(loop, outer)
                lo["vertices"] = [{"p": to_paper(d, view, v["p"]), "bulge": v["bulge"]} for v in lo["vertices"]]
                lo["component"] = comp
                out.append(lo)
        return out

    def scale_text(self, d, view):
        return str(view.scale_text or "")

    def scale(self, d, view):
        return float(view.scale) / unit_mm(d, view)

    def direction(self, d, view):
        return [float(c) for c in view.vnormal]

    def role(self, d, view):
        n = [float(c) for c in view.vnormal]
        for x, y, z, name in NORMAL_ROLE:
            if abs(n[0] * x + n[1] * y + n[2] * z) > 0.999:
                return name
        return "iso"

    def project(self, d, view, pt):
        return to_paper(d, view, local_of(view, pt))

    def model_drawing(self, d, view, base=""):
        src = view.source or {}
        path = src.get("doc") or ""
        if not path:
            return d
        from app.assembly import parts

        full = path if os.path.isabs(path) else os.path.join(os.path.dirname(base or ""), path)
        return parts.load(os.path.normpath(full)).drawing


viewsrc.register(DrawViewProvider())
