import math

import numpy as np

from app.pcb import geom as G


def flip_layer(name: str) -> str:
    if name == "F.Cu":
        return "B.Cu"
    if name == "B.Cu":
        return "F.Cu"
    return name


def world_pads(part: dict) -> list:
    out = []
    bottom = part.get("side") == "bottom"
    for pad in part["pads"]:
        lx, ly = pad["x"], pad["y"]
        prot = pad.get("rot", 0.0)
        if bottom:
            lx = -lx
            prot = -prot
        x, y = G.rot(lx, ly, part["rot"])
        layers = [flip_layer(n) for n in pad["layers"]] if bottom else list(pad["layers"])
        out.append(pad_item(part["refdes"], pad, part["x"] + x, part["y"] + y, part["rot"] + prot, layers, bottom))
    return out


def pad_item(ref: str, pad: dict, x: float, y: float, rot: float, layers: list, mirror: bool = False) -> dict:
    w, h = pad["w"], pad["h"]
    if pad["shape"] == "poly" and pad.get("poly"):
        pts = []
        for px, py in pad["poly"]:
            qx, qy = G.rot(-px if mirror else px, py, rot)
            pts.append((x + qx, y + qy))
        shape = ("poly", pts)
    elif pad["shape"] == "circle":
        shape = ("cap", (x, y), (x, y), max(w, h) / 2.0)
    elif pad["shape"] == "oval":
        if w >= h:
            ex, ey = G.rot((w - h) / 2.0, 0.0, rot)
            r = h / 2.0
        else:
            ex, ey = G.rot(0.0, (h - w) / 2.0, rot)
            r = w / 2.0
        shape = ("cap", (x - ex, y - ey), (x + ex, y + ey), r)
    else:
        shape = ("poly", G.rect_poly(x, y, w, h, rot))
    return {"kind": "pad", "ref": ref, "number": pad["number"], "net": pad.get("net", ""), "layers": layers, "shape": shape, "x": x, "y": y, "drill": pad.get("drill", 0.0), "plated": pad.get("plated", True), "w": w, "h": h, "rot": rot, "shape_name": pad["shape"], "zone_connect": pad.get("zone_connect"), "slot": pad.get("slot")}


def all_pads(h: dict) -> list:
    out = []
    for part in h["parts"]:
        out.extend(world_pads(part))
    return out


def track_item(t: dict) -> dict:
    return {"kind": "track", "id": t["id"], "net": t["net"], "layers": [t["layer"]], "shape": ("cap", tuple(t["a"]), tuple(t["b"]), t["width"] / 2.0), "width": t["width"]}


def via_item(v: dict, layers: list) -> dict:
    return {"kind": "via", "id": v["id"], "net": v["net"], "layers": layers, "shape": ("cap", (v["x"], v["y"]), (v["x"], v["y"]), v["dia"] / 2.0), "x": v["x"], "y": v["y"], "drill": v["drill"], "dia": v["dia"], "plated": True}


def via_layers(h: dict, v: dict) -> list:
    from app.pcb.store import copper_layers

    names = copper_layers(h["board"]["layers"])
    i, j = names.index(v["from"]), names.index(v["to"])
    lo, hi = min(i, j), max(i, j)
    return names[lo:hi + 1]


def hole_item(hh: dict) -> dict:
    layers = ["F.Cu", "B.Cu"] if hh.get("plated") else []
    shape = ("cap", (hh["x"], hh["y"]), (hh["x"], hh["y"]), hh["dia"] / 2.0 if hh.get("plated") else 0.0)
    return {"kind": "hole", "id": hh["id"], "net": "", "layers": layers, "shape": shape, "x": hh["x"], "y": hh["y"], "drill": hh["drill"], "plated": hh.get("plated", False)}


def copper_items(h: dict, skip_tracks: bool = False) -> list:
    items = all_pads(h)
    if not skip_tracks:
        for t in h["tracks"]:
            items.append(track_item(t))
        for v in h["vias"]:
            items.append(via_item(v, via_layers(h, v)))
    for hh in h["holes"]:
        items.append(hole_item(hh))
    return items


def shape_dist(a, b) -> float:
    if a[0] == "cap" and b[0] == "cap":
        return G.seg_seg(a[1], a[2], b[1], b[2]) - a[3] - b[3]
    if a[0] == "cap":
        return G.seg_poly(a[1], a[2], b[1]) - a[3]
    if b[0] == "cap":
        return G.seg_poly(b[1], b[2], a[1]) - b[3]
    return G.poly_poly(a[1], b[1])


def shape_bbox(s, pad=0.0):
    if s[0] == "cap":
        r = s[3] + pad
        return (min(s[1][0], s[2][0]) - r, min(s[1][1], s[2][1]) - r, max(s[1][0], s[2][0]) + r, max(s[1][1], s[2][1]) + r)
    x0, y0, x1, y1 = G.bbox(s[1])
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def shape_field(s, xs, ys):
    if s[0] == "cap":
        return G.seg_dist_field(xs, ys, s[1], s[2]) - s[3]
    return G.poly_dist_field(xs, ys, s[1])


def shape_polygon(s, n=16) -> list:
    if s[0] == "poly":
        return list(s[1])
    (ax, ay), (bx, by), r = s[1], s[2], s[3]
    if (ax, ay) == (bx, by):
        return G.circle_poly(ax, ay, max(r, 1e-6), n)
    ang = math.atan2(by - ay, bx - ax)
    pts = []
    for i in range(n // 2 + 1):
        a = ang - math.pi / 2 + math.pi * i / (n // 2)
        pts.append((bx + r * math.cos(a), by + r * math.sin(a)))
    for i in range(n // 2 + 1):
        a = ang + math.pi / 2 + math.pi * i / (n // 2)
        pts.append((ax + r * math.cos(a), ay + r * math.sin(a)))
    return pts


def outline_loops(h: dict) -> list:
    b = h["board"]
    loops = []
    if b["outline"]:
        loops.append([tuple(p) for p in b["outline"]])
    for c in b["cutouts"]:
        loops.append([tuple(p) for p in c])
    return loops


def board_bbox(h: dict):
    pts = h["board"]["outline"]
    if not pts:
        return None
    return G.bbox(pts)


def inside_board(h: dict, p) -> bool:
    o = h["board"]["outline"]
    if len(o) < 3:
        return True
    if not G.pt_in_poly(p, o):
        return False
    for c in h["board"]["cutouts"]:
        if G.pt_in_poly(p, c):
            return False
    return True


def edge_dist(h: dict, s) -> float:
    best = 1e18
    for loop in outline_loops(h):
        for a, b in G.poly_edges(loop):
            if s[0] == "cap":
                v = G.seg_seg(s[1], s[2], a, b) - s[3]
            else:
                v = G.seg_poly(a, b, s[1])
            best = min(best, v)
    return best
