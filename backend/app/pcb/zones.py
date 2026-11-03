import math

import pyclipper as pc

from app.pcb import geom as G
from app.pcb import model as M
from app.pcb import rules as R

SC = 10000.0
ARC = 0.003 * SC


def up(poly):
    return [(int(round(x * SC)), int(round(y * SC))) for x, y in poly]


def down(poly):
    return [(x / SC, y / SC) for x, y in poly]


def offset(paths, delta, join=pc.JT_ROUND):
    if not paths:
        return []
    co = pc.PyclipperOffset(2.0, ARC)
    co.AddPaths(paths, join, pc.ET_CLOSEDPOLYGON)
    return co.Execute(int(round(delta * SC)))


def union(paths):
    if not paths:
        return []
    c = pc.Pyclipper()
    c.AddPaths(paths, pc.PT_SUBJECT, True)
    return c.Execute(pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO)


def combine(subject, clip, op):
    c = pc.Pyclipper()
    if subject:
        c.AddPaths(subject, pc.PT_SUBJECT, True)
    if clip:
        c.AddPaths(clip, pc.PT_CLIP, True)
    return c.Execute(op, pc.PFT_NONZERO, pc.PFT_NONZERO)


def tree_polys(paths):
    c = pc.Pyclipper()
    c.AddPaths(paths, pc.PT_SUBJECT, True)
    tree = c.Execute2(pc.CT_UNION, pc.PFT_EVENODD, pc.PFT_EVENODD)
    out = []

    def walk(node):
        for child in node.Childs:
            if not child.IsHole:
                out.append({"outline": [list(p) for p in child.Contour], "holes": [[list(p) for p in g.Contour] for g in child.Childs if g.IsHole]})
            walk(child)

    walk(tree)
    return out


def rect_path(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def spoke_paths(item, zone, count):
    reach = max(item["w"], item["h"]) / 2.0 + zone["gap"] + max(zone["spoke"], 0.2)
    base = item["rot"] + 45.0 if count == 4 else item["rot"]
    out = []
    for i in range(count):
        a = base + 360.0 * i / count
        w = zone["spoke"] / 2.0
        pts = [(0.0, -w), (reach, -w), (reach, w), (0.0, w)]
        out.append(up([(item["x"] + G.rot(px, py, a)[0], item["y"] + G.rot(px, py, a)[1]) for px, py in pts]))
    return out


def fill_zone(h: dict, zone: dict, earlier: list, items: list) -> dict:
    eff = R.effective(h["rules"])
    clr = max(zone["clearance"], eff["clearance"])
    layer = zone["layer"]
    net = zone["net"]
    base = [up(zone["polygon"])]
    outline = h["board"]["outline"]
    if len(outline) >= 3:
        inner = offset([up(outline)], -eff["edge_clearance"])
        base = combine(base, inner, pc.CT_INTERSECTION)
    cuts = [up(c) for c in h["board"]["cutouts"]]
    if cuts:
        grown = offset(cuts, eff["edge_clearance"])
        base = combine(base, grown, pc.CT_DIFFERENCE)
    for k in h["keepouts"]:
        if k.get("pours") and layer in k["layers"]:
            base = combine(base, [up(k["polygon"])], pc.CT_DIFFERENCE)
    zb = G.bbox(zone["polygon"])
    pad = clr + 2.0
    obstacles = []
    rings = []
    spokes = []
    for it in items:
        if layer not in it["layers"]:
            continue
        bb = M.shape_bbox(it["shape"], pad)
        if bb[2] < zb[0] or bb[0] > zb[2] or bb[3] < zb[1] or bb[1] > zb[3]:
            continue
        poly = up(M.shape_polygon(it["shape"]))
        same = net != "" and it["net"] == net
        if not same:
            obstacles.append(poly)
            continue
        if it["kind"] == "pad":
            mode = it.get("zone_connect") or zone["connect"]
            if mode == "none":
                obstacles.append(poly)
            elif mode == "thermal":
                rings.append(poly)
                spokes.extend(spoke_paths(it, zone, zone["spokes"]))
    for earlier_net, earlier_polys in earlier:
        if earlier_net == net and net != "":
            continue
        for fp in earlier_polys:
            obstacles.append(up(fp["outline"]))
    fixed = union(obstacles)
    avoid = offset(fixed, clr) if fixed else []
    ring_ob = offset(union(rings), zone["gap"]) if rings else []
    region = combine(base, union(avoid + ring_ob), pc.CT_DIFFERENCE) if (avoid or ring_ob) else base
    allowed = combine(base, avoid, pc.CT_DIFFERENCE) if avoid else base
    mw = zone["min_width"]
    opened = offset(offset(region, -mw / 2.0), mw / 2.0) if region else []
    if spokes:
        sp = combine(union(spokes), allowed, pc.CT_INTERSECTION)
        opened = union(opened + sp)
    polys = tree_polys(opened) if opened else []
    keep = []
    for p in polys:
        outline_pts = down(p["outline"])
        if abs(G.area(outline_pts)) < zone["min_island"]:
            continue
        if net != "":
            if not connected_island(outline_pts, [down(g) for g in p["holes"]], net, layer, items, h):
                continue
        keep.append({"outline": [[round(x, 4), round(y, 4)] for x, y in outline_pts], "holes": [[[round(x, 4), round(y, 4)] for x, y in down(g)] for g in p["holes"]]})
    return {"id": zone.get("id", ""), "layer": layer, "net": net, "polygons": keep}


def connected_island(outline, holes, net, layer, items, h) -> bool:
    def inside(pt):
        if not G.pt_in_poly(pt, outline):
            return False
        return not any(G.pt_in_poly(pt, hole) for hole in holes)

    for it in items:
        if it["net"] != net or layer not in it["layers"]:
            continue
        shape = it["shape"]
        pts = [shape[1], shape[2]] if shape[0] == "cap" else [(it["x"], it["y"])] if it["kind"] == "pad" else list(shape[1])
        if any(inside(p) for p in pts):
            return True
    return False


def fill_all(h: dict, only=None) -> list:
    items = M.copper_items(h)
    order = sorted(h["zones"], key=lambda z: (-z.get("priority", 0), z["id"]))
    done = {}
    out = []
    for z in order:
        earlier = done.setdefault(z["layer"], [])
        res = fill_zone(h, z, [(e["net"], e["polygons"]) for e in earlier], items)
        earlier.append(res)
        out.append(res)
    if only is not None:
        out = [r for r in out if r["id"] in only]
    return out


def fill_area(res: dict) -> float:
    total = 0.0
    for p in res["polygons"]:
        total += abs(G.area(p["outline"])) - sum(abs(G.area(g)) for g in p["holes"])
    return total


def point_in_fill(res: dict, pt) -> bool:
    for p in res["polygons"]:
        if G.pt_in_poly(pt, p["outline"]) and not any(G.pt_in_poly(pt, g) for g in p["holes"]):
            return True
    return False
