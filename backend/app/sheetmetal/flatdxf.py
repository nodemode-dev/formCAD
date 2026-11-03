import math

import ezdxf

from app.core import outputs

PROFILES = ("cutting", "bending")
VERSIONS = ("R2000", "R2004", "R2007", "R2010", "R2013", "R2018")
LAYERS_BENDING = {"outer": "OUTER", "inner": "INNER", "up": "BEND_UP", "down": "BEND_DOWN", "note": "BEND_NOTE"}
LAYERS_CUTTING = {"outer": "CUT", "inner": "CUT"}


class FlatDxfError(ValueError):
    pass


def bulge_of(seg) -> float:
    sweep = (seg["a1"] - seg["a0"]) % (2.0 * math.pi)
    if sweep <= 0:
        sweep = 2.0 * math.pi
    b = math.tan(sweep / 4.0)
    return b if seg["ccw"] else -b


def loop_vertices(segs) -> list:
    out = []
    for s in segs:
        t = s["t"]
        if t == "line":
            out.append((s["a"][0], s["a"][1], 0.0))
        elif t == "arc":
            out.append((s["a"][0], s["a"][1], bulge_of(s)))
        elif t == "poly":
            pts = s["pts"]
            for p in pts[:-1]:
                out.append((p[0], p[1], 0.0))
    return out


def note_text(b, report) -> str:
    angle = math.degrees(b["angle"] if report != "open" else math.pi - b["angle"])
    return "%s %.1f DEG R%.3g K%.3g" % (b["direction"].upper(), angle, b["radius"], b["k"])


def build(flat, profile="bending", version="R2018", notes=False, bend_extent=False) -> "ezdxf.document.Drawing":
    if profile not in PROFILES:
        raise FlatDxfError("profile is cutting or bending.")
    if version not in VERSIONS:
        raise FlatDxfError("version is one of %s." % ", ".join(VERSIONS))
    doc = ezdxf.new(version, setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.units = 4
    layers = LAYERS_BENDING if profile == "bending" else LAYERS_CUTTING
    for name in sorted(set(layers.values())):
        if name not in doc.layers:
            doc.layers.add(name)
    if profile == "bending":
        for name in ("BEND_UP", "BEND_DOWN"):
            doc.layers.get(name).dxf.linetype = "CENTER"
            doc.layers.get(name).dxf.color = 3 if name == "BEND_UP" else 5
        doc.layers.get("OUTER").dxf.color = 7
        doc.layers.get("INNER").dxf.color = 1
    msp = doc.modelspace()
    for lp in flat["loops"]:
        layer = layers["outer"] if lp["outer"] else layers["inner"]
        segs = lp["segs"]
        if len(segs) == 1 and segs[0]["t"] == "circle":
            c = segs[0]
            msp.add_circle((c["c"][0], c["c"][1]), c["r"], dxfattribs={"layer": layer})
            continue
        verts = loop_vertices(segs)
        pl = msp.add_lwpolyline(verts, format="xyb", close=True, dxfattribs={"layer": layer})
        pl.closed = True
    if profile == "bending":
        for b in flat["bends"]:
            layer = layers["up"] if b["direction"] == "up" else layers["down"]
            msp.add_line((b["a"][0], b["a"][1], 0.0), (b["b"][0], b["b"][1], 0.0), dxfattribs={"layer": layer, "linetype": "CENTER"})
            if notes:
                mx, my = (b["a"][0] + b["b"][0]) / 2.0, (b["a"][1] + b["b"][1]) / 2.0
                dx, dy = b["b"][0] - b["a"][0], b["b"][1] - b["a"][1]
                ang = math.degrees(math.atan2(dy, dx))
                h = max(1.5, min(5.0, flat["thickness"]))
                msp.add_text(note_text(b, flat.get("angle_report", "bend")), height=h, rotation=ang, dxfattribs={"layer": layers["note"], "insert": (mx + h * 0.8 * -math.sin(math.radians(ang)), my + h * 0.8 * math.cos(math.radians(ang)))})
    return doc


def export(flat, path, profile="bending", version="R2018", notes=False) -> dict:
    try:
        full = outputs.checked(path, (".dxf",), ".dxf")
    except outputs.OutputRefused as err:
        raise FlatDxfError(str(err))
    doc = build(flat, profile, version, notes)
    doc.saveas(full)
    return {"path": full, "profile": profile, "version": version, "layers": sorted(l.dxf.name for l in doc.layers if l.dxf.name not in ("0", "Defpoints")), "outer_loops": sum(1 for l in flat["loops"] if l["outer"]), "inner_loops": sum(1 for l in flat["loops"] if not l["outer"]), "bend_lines": len(flat["bends"]) if profile == "bending" else 0, "bbox": flat["bbox"], "units": "mm"}
