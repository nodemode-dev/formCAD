import math

from app.solid import work

NOTE = "Sizes are entered by the user or imported from the user's own table. No standard, catalogue or section table ships with FormCAD; the shapes are generic parametric models and the designation text is a label only."
BULGE90 = math.tan(math.radians(90.0) / 4.0)

P = lambda name, default, lo, hi, label, derived=None: {"name": name, "default": default, "min": lo, "max": hi, "label": label, "derived": derived}

KINDS = {
    "socket_screw": {
        "group": "fastener", "label": "Socket head cap screw", "prefix": "SHCS",
        "params": [P("d", 6.0, 0.5, 200.0, "Nominal diameter"), P("length", 20.0, 1.0, 2000.0, "Length under the head"), P("head_d", None, 0.5, 400.0, "Head diameter", "1.5 d"), P("head_h", None, 0.3, 200.0, "Head height", "d"), P("socket_s", None, 0.3, 200.0, "Socket across flats", "0.8 d"), P("socket_depth", None, 0.2, 100.0, "Socket depth", "0.5 d"), P("pitch", 0.0, 0.0, 20.0, "Thread pitch (label only)")],
    },
    "hex_screw": {
        "group": "fastener", "label": "Hex head screw", "prefix": "HHS",
        "params": [P("d", 6.0, 0.5, 200.0, "Nominal diameter"), P("length", 20.0, 1.0, 2000.0, "Length under the head"), P("across_flats", None, 0.5, 400.0, "Head across flats", "1.6 d"), P("head_h", None, 0.3, 200.0, "Head height", "0.65 d"), P("pitch", 0.0, 0.0, 20.0, "Thread pitch (label only)")],
    },
    "hex_nut": {
        "group": "fastener", "label": "Hex nut", "prefix": "NUT",
        "params": [P("d", 6.0, 0.5, 200.0, "Nominal diameter"), P("across_flats", None, 0.5, 400.0, "Across flats", "1.6 d"), P("thickness", None, 0.3, 200.0, "Thickness", "0.8 d"), P("pitch", 0.0, 0.0, 20.0, "Thread pitch (label only)")],
    },
    "washer": {
        "group": "fastener", "label": "Flat washer", "prefix": "WSH",
        "params": [P("d", 6.4, 0.3, 200.0, "Inside diameter"), P("outer_d", None, 0.6, 600.0, "Outside diameter", "2 d"), P("thickness", None, 0.05, 50.0, "Thickness", "0.15 d")],
    },
    "pin": {
        "group": "fastener", "label": "Cylindrical pin", "prefix": "PIN",
        "params": [P("d", 6.0, 0.3, 200.0, "Diameter"), P("length", 20.0, 1.0, 2000.0, "Length"), P("chamfer", 0.0, 0.0, 20.0, "End chamfer")],
    },
    "bearing": {
        "group": "bearing", "label": "Rolling bearing (boundary dimensions)", "prefix": "BRG",
        "params": [P("d", 10.0, 1.0, 1000.0, "Bore diameter"), P("outer_d", 26.0, 2.0, 2000.0, "Outside diameter"), P("width", 8.0, 0.5, 500.0, "Width"), P("race_ratio", 0.28, 0.1, 0.45, "Ring thickness as a share of the radial section"), P("groove", 0.1, 0.0, 0.4, "Face groove depth as a share of the width")],
    },
    "i_beam": {
        "group": "shape", "label": "I or H section", "prefix": "IB",
        "params": [P("h", 100.0, 3.0, 3000.0, "Depth"), P("b", 50.0, 2.0, 1500.0, "Flange width"), P("tw", 4.0, 0.3, 200.0, "Web thickness"), P("tf", 6.0, 0.3, 200.0, "Flange thickness"), P("length", 1000.0, 1.0, 20000.0, "Length")],
    },
    "channel": {
        "group": "shape", "label": "Channel section", "prefix": "CH",
        "params": [P("h", 100.0, 3.0, 3000.0, "Depth"), P("b", 50.0, 2.0, 1500.0, "Flange width"), P("tw", 5.0, 0.3, 200.0, "Web thickness"), P("tf", 7.0, 0.3, 200.0, "Flange thickness"), P("length", 1000.0, 1.0, 20000.0, "Length")],
    },
    "angle": {
        "group": "shape", "label": "Angle section", "prefix": "L",
        "params": [P("a", 50.0, 2.0, 1500.0, "Leg a"), P("b", 50.0, 2.0, 1500.0, "Leg b"), P("t", 5.0, 0.3, 200.0, "Thickness"), P("length", 1000.0, 1.0, 20000.0, "Length")],
    },
    "rect_tube": {
        "group": "shape", "label": "Rectangular or square tube", "prefix": "RHS",
        "params": [P("h", 60.0, 2.0, 3000.0, "Depth"), P("b", 40.0, 2.0, 3000.0, "Width"), P("t", 3.0, 0.2, 200.0, "Wall"), P("outer_r", None, 0.0, 500.0, "Outer corner radius", "1.5 t"), P("length", 1000.0, 1.0, 20000.0, "Length")],
    },
    "round_tube": {
        "group": "shape", "label": "Round tube or pipe", "prefix": "CHS",
        "params": [P("od", 40.0, 1.0, 5000.0, "Outside diameter"), P("t", 3.0, 0.1, 500.0, "Wall"), P("length", 1000.0, 1.0, 20000.0, "Length")],
    },
    "flat_bar": {
        "group": "shape", "label": "Flat bar", "prefix": "FB",
        "params": [P("b", 40.0, 1.0, 3000.0, "Width"), P("t", 5.0, 0.2, 500.0, "Thickness"), P("length", 1000.0, 1.0, 20000.0, "Length")],
    },
}


class GenError(ValueError):
    pass


def kinds() -> list:
    return [{"kind": k, "group": v["group"], "label": v["label"], "params": [dict(p) for p in v["params"]], "note": NOTE} for k, v in KINDS.items()]


def _defaults(kind: str, p: dict) -> dict:
    d = p.get("d")
    if kind == "socket_screw":
        p["head_d"] = p["head_d"] or 1.5 * d
        p["head_h"] = p["head_h"] or d
        p["socket_s"] = p["socket_s"] or 0.8 * d
        p["socket_depth"] = p["socket_depth"] or 0.5 * d
    elif kind == "hex_screw":
        p["across_flats"] = p["across_flats"] or 1.6 * d
        p["head_h"] = p["head_h"] or 0.65 * d
    elif kind == "hex_nut":
        p["across_flats"] = p["across_flats"] or 1.6 * d
        p["thickness"] = p["thickness"] or 0.8 * d
    elif kind == "washer":
        p["outer_d"] = p["outer_d"] or 2.0 * d
        p["thickness"] = p["thickness"] or 0.15 * d
    elif kind == "rect_tube" and p.get("outer_r") is None:
        p["outer_r"] = 1.5 * p["t"]
    return p


def clean(kind: str, raw: dict | None) -> dict:
    spec = KINDS.get(kind)
    if spec is None:
        raise GenError("The kind is one of %s." % ", ".join(KINDS))
    raw = raw or {}
    unknown = [k for k in raw if k not in {q["name"] for q in spec["params"]} and k not in ("name", "source", "designation")]
    if unknown:
        raise GenError("%s has no parameter %s." % (spec["label"], ", ".join(map(str, unknown))))
    out = {}
    for q in spec["params"]:
        v = raw.get(q["name"])
        if v in (None, ""):
            v = q["default"]
        if v is None:
            out[q["name"]] = None
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise GenError("%s must be a number." % q["label"])
        if not math.isfinite(x) or x < q["min"] or x > q["max"]:
            raise GenError("%s must be between %g and %g." % (q["label"], q["min"], q["max"]))
        out[q["name"]] = x
    out = _defaults(kind, out)
    _relations(kind, out)
    return out


def _relations(kind: str, p: dict) -> None:
    if kind == "socket_screw":
        if p["socket_s"] >= p["head_d"] * 0.95:
            raise GenError("The socket is too wide for the head.")
        if p["socket_depth"] >= p["head_h"]:
            raise GenError("The socket is deeper than the head is high.")
        if p["head_d"] <= p["d"]:
            raise GenError("The head must be wider than the shank.")
    elif kind == "hex_screw" and p["across_flats"] <= p["d"]:
        raise GenError("The head must be wider than the shank.")
    elif kind == "hex_nut" and p["across_flats"] <= p["d"]:
        raise GenError("The nut must be wider than its bore.")
    elif kind == "washer" and p["outer_d"] <= p["d"] + 0.1:
        raise GenError("The outside diameter must exceed the inside diameter.")
    elif kind == "pin" and p["chamfer"] * 2 >= p["d"]:
        raise GenError("The chamfer is larger than the pin.")
    elif kind == "bearing":
        if p["outer_d"] <= p["d"] + 0.5:
            raise GenError("The outside diameter must exceed the bore.")
    elif kind == "i_beam":
        if p["tf"] * 2 >= p["h"] or p["tw"] >= p["b"]:
            raise GenError("The flanges and web leave no section.")
    elif kind == "channel":
        if p["tf"] * 2 >= p["h"] or p["tw"] >= p["b"]:
            raise GenError("The flanges and web leave no section.")
    elif kind == "angle":
        if p["t"] >= min(p["a"], p["b"]):
            raise GenError("The thickness must be less than both legs.")
    elif kind == "rect_tube":
        if p["t"] * 2 >= min(p["h"], p["b"]):
            raise GenError("The wall leaves no opening.")
        if p["outer_r"] > min(p["h"], p["b"]) / 2.0:
            raise GenError("The outer radius is larger than half the width.")
    elif kind == "round_tube" and p["t"] * 2 >= p["od"]:
        raise GenError("The wall leaves no bore.")
    elif kind == "flat_bar" and p["t"] > p["b"] * 4:
        raise GenError("The thickness is out of proportion to the width.")


def designation(kind: str, p: dict) -> str:
    pre = KINDS[kind]["prefix"]

    def g(v):
        return ("%.4f" % v).rstrip("0").rstrip(".")

    if kind in ("socket_screw", "hex_screw"):
        return "%s M%s x %s" % (pre, g(p["d"]), g(p["length"]))
    if kind == "hex_nut":
        return "%s M%s" % (pre, g(p["d"]))
    if kind == "washer":
        return "%s %s x %s x %s" % (pre, g(p["d"]), g(p["outer_d"]), g(p["thickness"]))
    if kind == "pin":
        return "%s %s x %s" % (pre, g(p["d"]), g(p["length"]))
    if kind == "bearing":
        return "%s %s x %s x %s" % (pre, g(p["d"]), g(p["outer_d"]), g(p["width"]))
    if kind == "i_beam":
        return "%s %s x %s x %s x %s" % (pre, g(p["h"]), g(p["b"]), g(p["tw"]), g(p["tf"]))
    if kind == "channel":
        return "%s %s x %s x %s x %s" % (pre, g(p["h"]), g(p["b"]), g(p["tw"]), g(p["tf"]))
    if kind == "angle":
        return "%s %s x %s x %s" % (pre, g(p["a"]), g(p["b"]), g(p["t"]))
    if kind == "rect_tube":
        return "%s %s x %s x %s" % (pre, g(p["h"]), g(p["b"]), g(p["t"]))
    if kind == "round_tube":
        return "%s %s x %s" % (pre, g(p["od"]), g(p["t"]))
    return "%s %s x %s" % (pre, g(p["b"]), g(p["t"]))


def safe_name(text: str) -> str:
    out = "".join(c if c.isalnum() or c in "._-" else "_" for c in text.strip().replace(" x ", "x").replace(" ", "_"))
    return out.strip("._")[:80] or "part"


def hex_loop(af: float) -> dict:
    r = af / math.sqrt(3.0)
    return {"vertices": [[r * math.cos(math.radians(60 * k)), r * math.sin(math.radians(60 * k)), 0.0] for k in range(6)], "outer": True}


def rect_loop(x0, y0, x1, y1, outer=True) -> dict:
    return {"vertices": [[x0, y0, 0.0], [x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0]], "outer": outer}


def rounded_rect(x0, y0, x1, y1, r: float, outer=True) -> dict:
    if r <= 1e-9:
        return rect_loop(x0, y0, x1, y1, outer)
    return {"vertices": [[x0 + r, y0, 0.0], [x1 - r, y0, BULGE90], [x1, y0 + r, 0.0], [x1, y1 - r, BULGE90], [x1 - r, y1, 0.0], [x0 + r, y1, BULGE90], [x0, y1 - r, 0.0], [x0, y0 + r, BULGE90]], "outer": outer}


def poly(points, outer=True) -> dict:
    return {"vertices": [[float(x), float(y), 0.0] for x, y in points], "outer": outer}


def profile(kind: str, p: dict) -> list:
    if kind == "i_beam":
        h, b, tw, tf = p["h"], p["b"], p["tw"], p["tf"]
        x, w, y = b / 2.0, tw / 2.0, h / 2.0
        return [poly([(-x, -y), (x, -y), (x, -y + tf), (w, -y + tf), (w, y - tf), (x, y - tf), (x, y), (-x, y), (-x, y - tf), (-w, y - tf), (-w, -y + tf), (-x, -y + tf)])]
    if kind == "channel":
        h, b, tw, tf = p["h"], p["b"], p["tw"], p["tf"]
        y = h / 2.0
        return [poly([(0, -y), (b, -y), (b, -y + tf), (tw, -y + tf), (tw, y - tf), (b, y - tf), (b, y), (0, y), (0, -y)][:-1])]
    if kind == "angle":
        a, b, t = p["a"], p["b"], p["t"]
        return [poly([(0, 0), (b, 0), (b, t), (t, t), (t, a), (0, a)])]
    if kind == "rect_tube":
        h, b, t, ro = p["h"], p["b"], p["t"], p["outer_r"]
        ri = max(ro - t, 0.0)
        return [rounded_rect(-b / 2.0, -h / 2.0, b / 2.0, h / 2.0, ro), rounded_rect(-b / 2.0 + t, -h / 2.0 + t, b / 2.0 - t, h / 2.0 - t, ri, False)]
    if kind == "round_tube":
        return [{"circle": {"c": [0.0, 0.0], "r": p["od"] / 2.0}, "outer": True}, {"circle": {"c": [0.0, 0.0], "r": p["od"] / 2.0 - p["t"]}, "outer": False}]
    if kind == "flat_bar":
        return [rect_loop(-p["b"] / 2.0, -p["t"] / 2.0, p["b"] / 2.0, p["t"] / 2.0)]
    raise GenError("%s has no section profile." % kind)


def section_area(kind: str, p: dict) -> float:
    if kind == "i_beam":
        return 2 * p["b"] * p["tf"] + (p["h"] - 2 * p["tf"]) * p["tw"]
    if kind == "channel":
        return 2 * p["b"] * p["tf"] + (p["h"] - 2 * p["tf"]) * p["tw"]
    if kind == "angle":
        return (p["a"] + p["b"] - p["t"]) * p["t"]
    if kind == "rect_tube":
        ro, t = p["outer_r"], p["t"]
        ri = max(ro - t, 0.0)
        return p["h"] * p["b"] - (4 - math.pi) * ro * ro - ((p["h"] - 2 * t) * (p["b"] - 2 * t) - (4 - math.pi) * ri * ri)
    if kind == "round_tube":
        return math.pi / 4.0 * (p["od"] ** 2 - (p["od"] - 2 * p["t"]) ** 2)
    if kind == "flat_bar":
        return p["b"] * p["t"]
    raise GenError("%s has no section." % kind)


def expected_volume(kind: str, p: dict) -> float:
    if kind in ("i_beam", "channel", "angle", "rect_tube", "round_tube", "flat_bar"):
        return section_area(kind, p) * p["length"]
    if kind == "socket_screw":
        hexa = 3.0 * math.sqrt(3.0) / 2.0 * (p["socket_s"] / math.sqrt(3.0)) ** 2
        return math.pi / 4.0 * p["head_d"] ** 2 * p["head_h"] + math.pi / 4.0 * p["d"] ** 2 * p["length"] - hexa * p["socket_depth"]
    if kind == "hex_screw":
        r = p["across_flats"] / math.sqrt(3.0)
        return 3.0 * math.sqrt(3.0) / 2.0 * r * r * p["head_h"] + math.pi / 4.0 * p["d"] ** 2 * p["length"]
    if kind == "hex_nut":
        r = p["across_flats"] / math.sqrt(3.0)
        return 3.0 * math.sqrt(3.0) / 2.0 * r * r * p["thickness"] - math.pi / 4.0 * p["d"] ** 2 * p["thickness"]
    if kind == "washer":
        return math.pi / 4.0 * (p["outer_d"] ** 2 - p["d"] ** 2) * p["thickness"]
    if kind == "pin":
        c = p["chamfer"]
        vol = math.pi / 4.0 * p["d"] ** 2 * p["length"]
        if c > 0:
            r = p["d"] / 2.0
            vol -= 2 * math.pi * c * (r * r - (r * r + r * (r - c) + (r - c) ** 2) / 3.0)
        return vol
    if kind == "bearing":
        ro, ri = p["outer_d"] / 2.0, p["d"] / 2.0
        ring = (ro - ri) * p["race_ratio"]
        vol = math.pi * (ro * ro - ri * ri) * p["width"]
        if p["width"] * p["groove"] > 1e-6 and ro - ri - 2 * ring > 1e-6:
            vol -= 2 * math.pi * ((ro - ring) ** 2 - (ri + ring) ** 2) * p["width"] * p["groove"]
        return vol
    raise GenError("Unknown kind.")


def cyl(origin, axis, r, h):
    return work.kcall("primitive", {"kind": "cylinder", "origin": origin, "axis": axis, "radius": r, "height": h})["id"]


def prism(loops, z0, height):
    return work.kcall("primitive", {"kind": "extrude", "loops": loops, "plane": {"origin": [0.0, 0.0, z0], "normal": [0, 0, 1], "xdir": [1, 0, 0]}, "height": height})["id"]


def boolean(op, base, tools):
    return work.kcall("boolean", {"op": op, "base": base, "tools": tools}, work.LONG)["id"]


def build(kind: str, p: dict) -> str:
    z = [0, 0, 1]
    if kind == "socket_screw":
        head = cyl([0, 0, 0], z, p["head_d"] / 2.0, p["head_h"])
        shank = cyl([0, 0, -p["length"]], z, p["d"] / 2.0, p["length"])
        body = boolean("fuse", head, [shank])
        sock = prism([hex_loop(p["socket_s"])], p["head_h"] - p["socket_depth"], p["socket_depth"] + 1.0)
        return boolean("cut", body, [sock])
    if kind == "hex_screw":
        head = prism([hex_loop(p["across_flats"])], 0.0, p["head_h"])
        shank = cyl([0, 0, -p["length"]], z, p["d"] / 2.0, p["length"])
        return boolean("fuse", head, [shank])
    if kind == "hex_nut":
        nut = prism([hex_loop(p["across_flats"])], 0.0, p["thickness"])
        bore = cyl([0, 0, -1.0], z, p["d"] / 2.0, p["thickness"] + 2.0)
        return boolean("cut", nut, [bore])
    if kind == "washer":
        disk = cyl([0, 0, 0], z, p["outer_d"] / 2.0, p["thickness"])
        bore = cyl([0, 0, -1.0], z, p["d"] / 2.0, p["thickness"] + 2.0)
        return boolean("cut", disk, [bore])
    if kind == "pin":
        c, r, ln = p["chamfer"], p["d"] / 2.0, p["length"]
        if c <= 0:
            return cyl([0, 0, -ln], z, r, ln)
        if c * 2 >= ln:
            raise GenError("The chamfers are longer than the pin.")
        low = work.kcall("primitive", {"kind": "cone", "origin": [0, 0, -ln], "axis": z, "radius1": r - c, "radius2": r, "height": c})["id"]
        top = work.kcall("primitive", {"kind": "cone", "origin": [0, 0, -c], "axis": z, "radius1": r, "radius2": r - c, "height": c})["id"]
        return boolean("fuse", cyl([0, 0, -ln + c], z, r, ln - 2 * c), [low, top])
    if kind == "bearing":
        ro, ri = p["outer_d"] / 2.0, p["d"] / 2.0
        section = ro - ri
        ring = section * p["race_ratio"]
        w = p["width"]
        body = boolean("cut", cyl([0, 0, 0], z, ro, w), [cyl([0, 0, -1.0], z, ri, w + 2.0)])
        gd = w * p["groove"]
        if gd > 1e-6 and section - 2 * ring > 1e-6:
            r0, r1 = ri + ring, ro - ring
            tools = []
            for z0 in (-1.0, w - gd):
                tools.append(boolean("cut", cyl([0, 0, z0], z, r1, gd + 1.0), [cyl([0, 0, z0 - 1.0], z, r0, gd + 3.0)]))
            body = boolean("cut", body, tools)
        return body
    loops = profile(kind, p)
    return prism(loops, 0.0, p["length"])
