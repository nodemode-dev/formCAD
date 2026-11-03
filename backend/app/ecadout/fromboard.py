import math

from app.ecadout import view as V
from app.pcb import model as M
from app.pcb import store as PS
from app.pcb import zones as Z


def rot_pt(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def world(part, lx, ly):
    if part.get("side") == "bottom":
        lx = -lx
    x, y = rot_pt(lx, ly, part.get("rot", 0.0))
    return part["x"] + x, part["y"] + y


def silk_rows(part):
    rows = []
    bottom = part.get("side") == "bottom"
    layer = "B.Silk" if bottom else "F.Silk"
    for s in part.get("silk") or []:
        t = s.get("t")
        w = float(s.get("w", 0.12))
        if t == "line" and len(s.get("pts") or []) >= 2:
            pts = [world(part, p[0], p[1]) for p in s["pts"]]
            for i in range(len(pts) - 1):
                rows.append({"layer": layer, "kind": "line", "a": list(pts[i]), "b": list(pts[i + 1]), "width": w})
        elif t == "circle":
            cx, cy = world(part, s["c"][0], s["c"][1])
            rows.append({"layer": layer, "kind": "circle", "c": [cx, cy], "r": float(s["r"]), "width": w})
    return rows


def component_row(part):
    body = part.get("body") or {}
    size = body.get("size") or [1.0, 1.0, 0.5]
    pos = body.get("pos") or [0.0, 0.0]
    if body.get("shape") == "cyl":
        dia, hgt = float(size[0]), float(size[1])
        w = d = dia
    else:
        w, d, hgt = float(size[0]), float(size[1]), float(size[2]) if len(size) > 2 else 0.5
    cx, cy = world(part, pos[0], pos[1])
    return {"ref": part["refdes"], "x": part["x"], "y": part["y"], "rot": part.get("rot", 0.0), "side": part.get("side", "top"), "w": w, "d": d, "h": hgt, "cx": pos[0], "cy": pos[1], "wx": cx, "wy": cy, "z0": float(body.get("z0", 0.0)), "package": part.get("footprint") or part["refdes"], "part": part.get("value") or part.get("footprint") or "NONE", "shape": body.get("shape", "box")}


def view_of(h: dict, fills=None) -> dict:
    b = h["board"]
    if len(b["outline"]) < 3:
        raise V.OutputError("The board has no outline yet.")
    layers = PS.copper_layers(b["layers"])
    loops = [{"outer": True, "verts": [[p[0], p[1], 0.0] for p in b["outline"]]}]
    for c in b["cutouts"]:
        loops.append({"outer": False, "verts": [[p[0], p[1], 0.0] for p in c]})
    pads = []
    for part in h["parts"]:
        for item, pad in zip(M.world_pads(part), part["pads"]):
            on = item["layers"]
            row = {"ref": item["ref"], "num": item["number"], "x": item["x"], "y": item["y"], "rot": item["rot"], "shape": item["shape_name"], "w": item["w"], "h": item["h"], "net": item["net"], "layers": list(on), "side": "bottom" if on and on[0] == "B.Cu" else "top", "ratio": pad.get("roundrect_ratio", 0.25), "mask_margin": pad.get("mask_margin"), "paste_margin": pad.get("paste_margin")}
            if item["shape_name"] == "poly":
                row["pts"] = [list(p) for p in item["shape"][1]]
            if item.get("drill"):
                row["drill"] = item["drill"]
                row["plated"] = item["plated"]
                if item.get("slot"):
                    sw, sh = float(item["slot"][0]), float(item["slot"][1])
                    row["drill"] = min(sw, sh)
                    row["slot"] = max(sw, sh)
                    row["rot"] = item["rot"] + (0.0 if sw >= sh else 90.0)
                    row["w"], row["h"] = (row["w"], row["h"])
            pads.append(row)
    holes = []
    for hh in h["holes"]:
        if hh.get("plated"):
            pads.append({"ref": "", "num": "", "x": hh["x"], "y": hh["y"], "shape": "circle", "w": hh["dia"], "h": hh["dia"], "rot": 0.0, "net": "", "layers": list(layers), "drill": hh["drill"], "plated": True})
        else:
            holes.append({"x": hh["x"], "y": hh["y"], "d": hh["drill"], "plated": False})
    tracks = [{"layer": t["layer"], "net": t["net"], "width": t["width"], "pts": [t["a"], t["b"]]} for t in h["tracks"]]
    vias = [{"x": v["x"], "y": v["y"], "dia": v["dia"], "drill": v["drill"], "net": v["net"], "from": v["from"], "to": v["to"]} for v in h["vias"]]
    silk = []
    for part in h["parts"]:
        silk.extend(silk_rows(part))
    zones = []
    for res in fills if fills is not None else Z.fill_all(h):
        zones.append({"layer": res["layer"], "net": res["net"], "polys": [[[tuple(p) for p in poly["outline"]]] + [[tuple(p) for p in hole] for hole in poly["holes"]] for poly in res["polygons"]]})
    return {"name": "board", "thickness": PS.board_thickness(b), "layers": layers, "outline": {"loops": loops}, "pads": pads, "vias": vias, "tracks": tracks, "zones": zones, "silk": silk, "holes": holes, "components": [component_row(p) for p in h["parts"]]}
