import datetime
import math
import re

from app import __version__
from app.ecadout import view as V

SCALE = 1000000
EXT = {"F.Cu": ".gtl", "B.Cu": ".gbl", "F.Mask": ".gts", "B.Mask": ".gbs", "F.Paste": ".gtp", "B.Paste": ".gbp", "F.Silk": ".gto", "B.Silk": ".gbo", "Edge": ".gm1"}
EXTENSIONS = (".gtl", ".gbl", ".gts", ".gbs", ".gtp", ".gbp", ".gto", ".gbo", ".gm1", ".g1", ".g2", ".g3", ".g4", ".g5", ".g6", ".g7", ".g8", ".g9", ".g10", ".g11", ".g12", ".g13", ".g14", ".gbr")
MACROS = {
    "RR": "%AMRR*21,1,$1,$2-2x$3,0,0,$4*21,1,$1-2x$3,$2,0,0,$4*1,1,2x$3,$1/2-$3,$2/2-$3,$4*1,1,2x$3,-$1/2+$3,$2/2-$3,$4*1,1,2x$3,-$1/2+$3,-$2/2+$3,$4*1,1,2x$3,$1/2-$3,-$2/2+$3,$4*%",
    "RT": "%AMRT*21,1,$1,$2,0,0,$3*%",
    "OV": "%AMOV*21,1,$1-$2,$2,0,0,$3*1,1,$2,$1/2-$2/2,0,$3*1,1,$2,-$1/2+$2/2,0,$3*%",
}


def esc(text: str) -> str:
    out = []
    for ch in str(text):
        if ch in "\\%*,":
            out.append("\\u%04X" % ord(ch))
        elif ord(ch) < 32 or ord(ch) > 126:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def fmt(v: float) -> str:
    return str(int(round(v * SCALE)))


def dec(v: float) -> str:
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


class Layer:
    def __init__(self, view, function, polarity="Positive"):
        self.view = view
        self.ox, self.oy = view["origin"]
        self.function = function
        self.polarity = polarity
        self.aps = {}
        self.body = []
        self.flashes = 0
        self.draws = 0
        self.regions = 0
        self.attrs = ""
        self.cur = None

    def xy(self, x, y):
        return "X%sY%s" % (fmt(x - self.ox), fmt(y - self.oy))

    def aperture(self, key, defn, func=""):
        k = (key, func)
        if k not in self.aps:
            self.aps[k] = (10 + len(self.aps), defn, func)
        return self.aps[k][0]

    def select(self, code):
        if self.cur != code:
            self.body.append("D%d*" % code)
            self.cur = code

    def circle(self, d, func=""):
        return self.aperture(("C", dec(d)), "C,%s" % dec(d), func)

    def pad_shape(self, shape, w, h, rot, ratio, func):
        rot = rot % 360.0
        quarter = abs(rot / 90.0 - round(rot / 90.0)) < 1e-9
        if quarter:
            q = int(round(rot / 90.0)) % 4
            if q % 2 == 1:
                w, h = h, w
            rot = 0.0
        if shape == "circle":
            return self.circle(max(w, h) if abs(w - h) < 1e-9 else min(w, h), func)
        if shape == "rect":
            if rot == 0.0:
                return self.aperture(("R", dec(w), dec(h)), "R,%sX%s" % (dec(w), dec(h)), func)
            return self.aperture(("RT", dec(w), dec(h), dec(rot)), "RT,%sX%sX%s" % (dec(w), dec(h), dec(rot)), func)
        if shape == "oval":
            if abs(w - h) < 1e-9:
                return self.circle(w, func)
            if rot == 0.0:
                return self.aperture(("O", dec(w), dec(h)), "O,%sX%s" % (dec(w), dec(h)), func)
            lo, sh, r2 = (w, h, rot) if w >= h else (h, w, rot + 90.0)
            return self.aperture(("OV", dec(lo), dec(sh), dec(r2)), "OV,%sX%sX%s" % (dec(lo), dec(sh), dec(r2)), func)
        if shape == "roundrect":
            r = max(0.0, min(ratio, 0.5)) * min(w, h)
            if r < 1e-6:
                return self.pad_shape("rect", w, h, rot, 0.0, func)
            return self.aperture(("RR", dec(w), dec(h), dec(r), dec(rot)), "RR,%sX%sX%sX%s" % (dec(w), dec(h), dec(r), dec(rot)), func)
        raise V.OutputError("Unknown pad shape %s." % shape)

    def flash(self, code, x, y):
        self.select(code)
        self.body.append("%s%s*" % (self.xy(x, y), "D03"))
        self.flashes += 1

    def move(self, x, y):
        self.body.append("%sD02*" % self.xy(x, y))

    def line(self, x, y):
        self.body.append("%sD01*" % self.xy(x, y))
        self.draws += 1

    def arc(self, a, b, c, ccw):
        self.body.append("%s%s" % ("G03*" if ccw else "G02*", ""))
        self.body.append("%sI%sJ%sD01*" % (self.xy(b[0], b[1]), fmt(c[0] - a[0]), fmt(c[1] - a[1])))
        self.body.append("G01*")
        self.draws += 1

    def objattr(self, net=None, ref=None, pin=None):
        lines = []
        if net is not None:
            lines.append("%%TO.N,%s*%%" % (esc(net) if net or not ref else "N/C"))
        if ref:
            lines.append("%%TO.C,%s*%%" % esc(ref))
        if ref and pin is not None:
            lines.append("%%TO.P,%s,%s*%%" % (esc(ref), esc(pin)))
        self.body.extend(lines)
        return bool(lines)

    def clear_attr(self):
        self.body.append("%TD*%")

    def region(self, ring_list, func=None):
        for ring in ring_list:
            pts = list(ring)
            if len(pts) < 3:
                continue
            self.body.append("G36*")
            self.move(*pts[0])
            for p in pts[1:]:
                self.line(*p)
            self.line(*pts[0])
            self.body.append("G37*")
            self.regions += 1

    def text(self):
        v = self.view
        head = ["G04 Gerber X2 written by FormCAD %s*" % __version__, "%MOMM*%", "%FSLAX36Y36*%"]
        head.append("%%TF.GenerationSoftware,FormCAD,FormCAD,%s*%%" % __version__)
        head.append("%%TF.CreationDate,%s*%%" % (v["created"] or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")))
        head.append("%%TF.ProjectId,%s,00000000-0000-0000-0000-000000000000,%s*%%" % (esc(v["name"]), __version__))
        head.append("%TF.SameCoordinates,Original*%")
        head.append("%%TF.FileFunction,%s*%%" % self.function)
        head.append("%%TF.FilePolarity,%s*%%" % self.polarity)
        used = {d[1].split(",")[0] for d in self.aps.values() if d[1].split(",")[0] in MACROS}
        for name in sorted(used):
            head.append(MACROS[name])
        by_func = {}
        for (key, func), (code, defn, f) in self.aps.items():
            by_func.setdefault(func, []).append((code, defn))
        for func in sorted(by_func, key=lambda f: (f != "", f)):
            if func:
                head.append("%%TA.AperFunction,%s*%%" % func)
            for code, defn in sorted(by_func[func]):
                head.append("%%ADD%d%s*%%" % (code, defn))
            if func:
                head.append("%TD.AperFunction*%")
        head.append("G75*")
        head.append("G01*")
        head.append("%LPD*%")
        return "\n".join(head + self.body + ["M02*"]) + "\n"


def pad_layers(pad, view):
    if pad.get("drill"):
        return list(pad.get("layers") or view["layers"])
    side = pad.get("side", "top")
    return list(pad.get("layers") or (["F.Cu"] if side == "top" else ["B.Cu"]))


def pad_func(pad):
    return "ComponentPad" if pad.get("drill") else "SMDPad,CuDef"


def flash_pad(lay, pad, grow=0.0, func=""):
    shape = pad.get("shape", "circle")
    if shape == "poly":
        return False
    w = V.num(pad.get("w"), "pad width") + 2 * grow
    h = V.num(pad.get("h", pad.get("w")), "pad height") + 2 * grow
    if w <= 0 or h <= 0:
        return True
    code = lay.pad_shape(shape, w, h, float(pad.get("rot", 0.0)), float(pad.get("ratio", 0.25)), func)
    lay.flash(code, float(pad["x"]), float(pad["y"]))
    return True


def poly_pad(lay, pad, grow=0.0):
    pts = [(float(p[0]), float(p[1])) for p in pad["pts"]]
    if grow:
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        pts = [(p[0] + (grow if p[0] > cx else -grow), p[1] + (grow if p[1] > cy else -grow)) for p in pts]
    lay.region([pts])


def bridge_rings(rings):
    outer = list(rings[0])
    holes = [list(h) for h in rings[1:]]
    clear = []
    for h in holes:
        best = None
        for i, p in enumerate(outer):
            for j, q in enumerate(h):
                d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                if best is None or d < best[0]:
                    best = (d, i, j)
        d, i, j = best
        if crosses(outer[i], h[j], outer, holes):
            clear.append(h)
            continue
        seq = h[j:] + h[:j]
        outer = outer[: i + 1] + seq + [seq[0]] + outer[i:]
    return outer, clear


def crosses(a, b, outer, holes):
    def inter(p1, p2, p3, p4):
        def o(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
        return d1 * d2 < -1e-12 and d3 * d4 < -1e-12

    for ring in [outer] + holes:
        for k in range(len(ring)):
            c, d = ring[k], ring[(k + 1) % len(ring)]
            if inter(a, b, c, d):
                return True
    return False


def copper(view, name):
    lay = Layer(view, "Copper,L%d,%s" % (view["layers"].index(name) + 1, "Top" if name == "F.Cu" else "Bot" if name == "B.Cu" else "Inr"))
    cond = "Conductor"
    for z in view["zones"]:
        if z.get("layer") != name:
            continue
        lay.body.append("%%TA.AperFunction,%s*%%" % cond)
        lay.objattr(net=z.get("net", ""))
        for poly in z.get("polys") or []:
            if not poly:
                continue
            outer, clear = bridge_rings(poly) if len(poly) > 1 else (poly[0], [])
            lay.region([outer])
            if clear:
                lay.body.append("%LPC*%")
                lay.region(clear)
                lay.body.append("%LPD*%")
        lay.clear_attr()
    segs = [t for t in view["tracks"] if t.get("layer") == name]
    segs.sort(key=lambda t: (str(t.get("net", "")), float(t["width"])))
    last = object()
    for t in segs:
        code = lay.circle(float(t["width"]), cond)
        net = str(t.get("net", ""))
        if net != last:
            if last is not object():
                lay.clear_attr()
            lay.objattr(net=net)
            last = net
        lay.select(code)
        if t.get("arc"):
            a, m, b = t["arc"]
            geo = V.arc_through(a, m, b)
            if geo is None:
                lay.move(*a)
                lay.line(*b)
            else:
                lay.move(*a)
                lay.arc(a, b, (geo[0], geo[1]), geo[3])
        else:
            pts = t["pts"]
            lay.move(*pts[0])
            for p in pts[1:]:
                lay.line(*p)
    if last is not object():
        lay.clear_attr()
    for v in view["vias"]:
        f, to = v.get("from", "F.Cu"), v.get("to", "B.Cu")
        idx = view["layers"].index
        if idx(f) <= idx(name) <= idx(to):
            code = lay.circle(float(v["dia"]), "ViaPad")
            lay.objattr(net=str(v.get("net", "")))
            lay.flash(code, float(v["x"]), float(v["y"]))
            lay.clear_attr()
    for p in view["pads"]:
        if name not in pad_layers(p, view):
            continue
        lay.objattr(net=str(p.get("net", "")), ref=p.get("ref"), pin=p.get("num"))
        if not flash_pad(lay, p, 0.0, pad_func(p)):
            poly_pad(lay, p)
        lay.clear_attr()
    return lay


def mask(view, side):
    lay = Layer(view, "Soldermask,%s" % ("Top" if side == "F" else "Bot"), "Negative")
    cu = "F.Cu" if side == "F" else "B.Cu"
    m = view["mask_margin"]
    for p in view["pads"]:
        if cu in pad_layers(p, view):
            mm = float(p["mask_margin"]) if p.get("mask_margin") is not None else m
            if not flash_pad(lay, p, mm):
                poly_pad(lay, p, mm)
    if not view["tent_vias"]:
        for v in view["vias"]:
            lay.flash(lay.circle(float(v["dia"]) + 2 * m), float(v["x"]), float(v["y"]))
    for h in view["holes"]:
        if not h.get("plated", False):
            lay.flash(lay.circle(float(h["d"]) + 2 * m), float(h["x"]), float(h["y"]))
    return lay


def paste(view, side):
    lay = Layer(view, "Paste,%s" % ("Top" if side == "F" else "Bot"))
    cu = "F.Cu" if side == "F" else "B.Cu"
    for p in view["pads"]:
        if p.get("drill") or cu not in pad_layers(p, view) or p.get("paste") is False:
            continue
        pm = float(p["paste_margin"]) if p.get("paste_margin") is not None else view["paste_margin"]
        if not flash_pad(lay, p, pm):
            poly_pad(lay, p, pm)
    return lay


def silk(view, side):
    lay = Layer(view, "Legend,%s" % ("Top" if side == "F" else "Bot"))
    want = "F.Silk" if side == "F" else "B.Silk"
    for s in view["silk"]:
        if s.get("layer") != want:
            continue
        w = float(s.get("width", 0.15))
        code = lay.circle(w, "NonConductor")
        lay.select(code)
        kind = s.get("kind", "line")
        if kind == "line":
            lay.move(s["a"][0], s["a"][1])
            lay.line(s["b"][0], s["b"][1])
        elif kind == "arc":
            geo = V.arc_through(s["a"], s["m"], s["b"])
            lay.move(*s["a"])
            if geo is None:
                lay.line(*s["b"])
            else:
                lay.arc(s["a"], s["b"], (geo[0], geo[1]), geo[3])
        elif kind == "circle":
            cx, cy, r = float(s["c"][0]), float(s["c"][1]), float(s["r"])
            lay.move(cx + r, cy)
            lay.arc((cx + r, cy), (cx + r, cy), (cx, cy), True)
        elif kind == "poly":
            lay.region([[(float(p[0]), float(p[1])) for p in s["pts"]]])
    return lay


def profile(view):
    lay = Layer(view, "Profile,NP")
    code = lay.circle(0.1, "Profile")
    lay.select(code)
    for loop in view["outline"]["loops"]:
        verts = loop["verts"]
        n = len(verts)
        lay.move(verts[0][0], verts[0][1])
        for i in range(n):
            a, b = verts[i], verts[(i + 1) % n]
            bulge = a[2] if len(a) > 2 else 0.0
            arc = V.bulge_arc((a[0], a[1]), (b[0], b[1]), bulge) if abs(bulge) > 1e-12 else None
            if arc:
                lay.arc((a[0], a[1]), (b[0], b[1]), (arc[0], arc[1]), bulge > 0)
            else:
                lay.line(b[0], b[1])
    return lay


def build(view: dict) -> list:
    out = []
    names = view["layers"]
    for i, name in enumerate(names):
        ext = EXT.get(name) or ".g%d" % i
        out.append((name, ext, copper(view, name)))
    out.append(("F.Mask", EXT["F.Mask"], mask(view, "F")))
    out.append(("B.Mask", EXT["B.Mask"], mask(view, "B")))
    out.append(("F.Paste", EXT["F.Paste"], paste(view, "F")))
    out.append(("B.Paste", EXT["B.Paste"], paste(view, "B")))
    out.append(("F.Silk", EXT["F.Silk"], silk(view, "F")))
    out.append(("B.Silk", EXT["B.Silk"], silk(view, "B")))
    out.append(("Edge.Cuts", EXT["Edge"], profile(view)))
    return out


def file_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "board"
