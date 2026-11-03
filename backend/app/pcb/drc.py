import math
import time

import pyclipper as pc

from app.pcb import geom as G
from app.pcb import model as M
from app.pcb import rules as R
from app.pcb import zones as Z

CELL = 4.0
TOL = 1e-4
MAX_VIOLATIONS = 2000


def class_clearance(h: dict, eff: dict, *nets) -> float:
    clr = eff["clearance"]
    classes = h["rules"].get("classes", {})
    for n in nets:
        c = classes.get(n, {}).get("clearance")
        if c:
            clr = max(clr, c)
    return clr


def candidate_pairs(items, margin: float):
    grid = {}
    for idx, it in enumerate(items):
        x0, y0, x1, y1 = M.shape_bbox(it["shape"], margin)
        it["_bb"] = (x0, y0, x1, y1)
        for gx in range(int(math.floor(x0 / CELL)), int(math.floor(x1 / CELL)) + 1):
            for gy in range(int(math.floor(y0 / CELL)), int(math.floor(y1 / CELL)) + 1):
                grid.setdefault((gx, gy), []).append(idx)
    seen = set()
    for bucket in grid.values():
        n = len(bucket)
        for a in range(n):
            for b in range(a + 1, n):
                i, j = bucket[a], bucket[b]
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                A, B = items[key[0]]["_bb"], items[key[1]]["_bb"]
                if A[2] < B[0] or B[2] < A[0] or A[3] < B[1] or B[3] < A[1]:
                    continue
                yield key


def shared_layer(a, b):
    for layer in a["layers"]:
        if layer in b["layers"]:
            return layer
    return None


def mid(a, b):
    return [round((a[0] + b[0]) / 2, 4), round((a[1] + b[1]) / 2, 4)]


def center(it):
    s = it["shape"]
    if s[0] == "cap":
        return [round((s[1][0] + s[2][0]) / 2, 4), round((s[1][1] + s[2][1]) / 2, 4)]
    return [round(sum(p[0] for p in s[1]) / len(s[1]), 4), round(sum(p[1] for p in s[1]) / len(s[1]), 4)]


def label(it) -> str:
    if it["kind"] == "pad":
        return "%s.%s" % (it["ref"], it["number"])
    return it.get("id", it["kind"])


def connectivity(h: dict, fills: list, items=None):
    items = items if items is not None else [i for i in M.copper_items(h) if i["layers"]]
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, j in candidate_pairs(items, 0.01):
        a, b = items[i], items[j]
        if shared_layer(a, b) is None:
            continue
        if M.shape_dist(a["shape"], b["shape"]) <= TOL:
            join(i, j)
    for fill in fills:
        if not fill["net"] or not fill["polygons"]:
            continue
        anchor = None
        for i, it in enumerate(items):
            if it["net"] != fill["net"] or fill["layer"] not in it["layers"]:
                continue
            s = it["shape"]
            pts = [s[1], s[2]] if s[0] == "cap" else [(it["x"], it["y"])] if it["kind"] == "pad" else list(s[1])
            if any(Z.point_in_fill(fill, p) for p in pts):
                if anchor is None:
                    anchor = i
                else:
                    join(anchor, i)
    return items, find


def ratsnest(h: dict, fills: list, items=None, limit: int = 4000) -> list:
    items, find = connectivity(h, fills, items)
    nets = {}
    for i, it in enumerate(items):
        if it["kind"] == "pad" and it["net"]:
            nets.setdefault(it["net"], []).append(i)
    out = []
    for net, idxs in sorted(nets.items()):
        groups = {}
        for i in idxs:
            groups.setdefault(find(i), []).append(i)
        if len(groups) < 2:
            continue
        keys = list(groups)
        comp = {k: k for k in keys}

        def root(k):
            while comp[k] != k:
                comp[k] = comp[comp[k]]
                k = comp[k]
            return k

        edges = []
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                best = None
                for i in groups[keys[a]][:60]:
                    for j in groups[keys[b]][:60]:
                        d = math.hypot(items[i]["x"] - items[j]["x"], items[i]["y"] - items[j]["y"])
                        if best is None or d < best[0]:
                            best = (d, i, j)
                edges.append(best)
        edges.sort()
        for d, i, j in edges:
            ra, rb = root(find(i)), root(find(j))
            if ra == rb:
                continue
            comp[ra] = rb
            out.append({"net": net, "a": [round(items[i]["x"], 4), round(items[i]["y"], 4)], "b": [round(items[j]["x"], 4), round(items[j]["y"], 4)], "from": label(items[i]), "to": label(items[j]), "length": round(d, 4)})
            if len(out) >= limit:
                return out
    return out


def world_courtyard(part):
    court = part.get("courtyard")
    if not court:
        return None
    bottom = part.get("side") == "bottom"
    pts = []
    for px, py in court:
        lx = -px if bottom else px
        x, y = G.rot(lx, py, part["rot"])
        pts.append((part["x"] + x, part["y"] + y))
    return pts


def hole_radius(it) -> float:
    return it["drill"] / 2.0


def run(h: dict, act=None, include_zones: bool = True) -> dict:
    t0 = time.time()
    eff = R.effective(h["rules"])
    viol = []

    def add(kind, msg, at, layer="", ids=(), value=None, limit=None, severity="error"):
        if len(viol) < MAX_VIOLATIONS:
            viol.append({"type": kind, "severity": severity, "message": msg, "at": at, "layer": layer, "items": list(ids), "value": None if value is None else round(value, 4), "limit": None if limit is None else round(limit, 4)})

    items = M.copper_items(h)
    copper = [i for i in items if i["layers"] and not (i["kind"] == "hole" and not i["plated"])]
    if act:
        act.step("clearance", 0.1)
    for i, j in candidate_pairs(copper, eff["clearance"] + 3.0):
        a, b = copper[i], copper[j]
        layer = shared_layer(a, b)
        if layer is None:
            continue
        if a["net"] == b["net"] and a["net"] != "":
            continue
        if a["kind"] == "pad" and b["kind"] == "pad" and a["ref"] == b["ref"] and a["number"] == b["number"]:
            continue
        clr = class_clearance(h, eff, a["net"], b["net"])
        d = M.shape_dist(a["shape"], b["shape"])
        if d < clr - TOL:
            kind = "short" if d <= TOL else "clearance"
            add(kind, "%s and %s are %.3f mm apart on %s, the rule is %.3f mm." % (label(a), label(b), max(d, 0.0), layer, clr), mid(center(a), center(b)), layer, (label(a), label(b)), max(d, 0.0), clr)
    if act:
        act.step("sizes", 0.3)
    for t in h["tracks"]:
        if t["width"] < eff["track_width"] - TOL:
            add("track_width", "Track %s is %.3f mm wide, the minimum is %.3f mm." % (t["id"], t["width"], eff["track_width"]), mid(t["a"], t["b"]), t["layer"], (t["id"],), t["width"], eff["track_width"])
    for v in h["vias"]:
        ring = (v["dia"] - v["drill"]) / 2.0
        if ring < eff["annular_ring"] - TOL:
            add("annular_ring", "Via %s ring is %.3f mm, the minimum is %.3f mm." % (v["id"], ring, eff["annular_ring"]), [v["x"], v["y"]], "", (v["id"],), ring, eff["annular_ring"])
        if v["drill"] < eff["drill"] - TOL:
            add("drill", "Via %s drill is %.3f mm, the minimum is %.3f mm." % (v["id"], v["drill"], eff["drill"]), [v["x"], v["y"]], "", (v["id"],), v["drill"], eff["drill"])
    drilled = []
    for it in items:
        if it["kind"] == "pad" and it["drill"] > 0:
            ring = (min(it["w"], it["h"]) - it["drill"]) / 2.0
            if it["plated"] and ring < eff["annular_ring"] - TOL:
                add("annular_ring", "Pad %s ring is %.3f mm, the minimum is %.3f mm." % (label(it), ring, eff["annular_ring"]), [it["x"], it["y"]], "", (label(it),), ring, eff["annular_ring"])
            if it["drill"] < eff["drill"] - TOL:
                add("drill", "Pad %s drill is %.3f mm, the minimum is %.3f mm." % (label(it), it["drill"], eff["drill"]), [it["x"], it["y"]], "", (label(it),), it["drill"], eff["drill"])
            drilled.append(it)
        elif it["kind"] == "hole":
            if it["drill"] < eff["drill"] - TOL:
                add("drill", "Hole %s drill is %.3f mm, the minimum is %.3f mm." % (it["id"], it["drill"], eff["drill"]), [it["x"], it["y"]], "", (it["id"],), it["drill"], eff["drill"])
            drilled.append(it)
        elif it["kind"] == "via":
            drilled.append(it)
    if act:
        act.step("holes", 0.4)
    holes = [dict(it, shape=("cap", (it["x"], it["y"]), (it["x"], it["y"]), hole_radius(it)), layers=["*"]) for it in drilled]
    for i, j in candidate_pairs(holes, eff["hole_to_hole"] + 1.0):
        a, b = holes[i], holes[j]
        if a["kind"] == "pad" and b["kind"] == "pad" and a["ref"] == b["ref"] and a["number"] == b["number"]:
            continue
        d = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) - hole_radius(a) - hole_radius(b)
        if d < eff["hole_to_hole"] - TOL:
            add("hole_to_hole", "Holes %s and %s are %.3f mm apart, the rule is %.3f mm." % (label(a), label(b), max(d, 0.0), eff["hole_to_hole"]), mid((a["x"], a["y"]), (b["x"], b["y"])), "", (label(a), label(b)), max(d, 0.0), eff["hole_to_hole"])
    if act:
        act.step("edge", 0.5)
    if len(h["board"]["outline"]) >= 3:
        for it in copper + [dict(x, shape=("cap", (x["x"], x["y"]), (x["x"], x["y"]), hole_radius(x))) for x in drilled]:
            dist = M.edge_dist(h, it["shape"])
            c = center(it)
            if not M.inside_board(h, tuple(c)) and it["kind"] != "track":
                add("outside_board", "%s lies outside the board outline." % label(it), c, "", (label(it),), None, None)
                continue
            if it["kind"] == "track":
                s = it["shape"]
                if not (M.inside_board(h, s[1]) and M.inside_board(h, s[2])):
                    add("outside_board", "Track %s leaves the board outline." % it["id"], c, it["layers"][0], (it["id"],), None, None)
                    continue
            if dist < eff["edge_clearance"] - TOL:
                add("edge_clearance", "%s is %.3f mm from the board edge, the rule is %.3f mm." % (label(it), max(dist, 0.0), eff["edge_clearance"]), c, "", (label(it),), max(dist, 0.0), eff["edge_clearance"])
    else:
        add("outline", "The board has no outline.", [0, 0], "", (), None, None, "warning")
    if len(h["board"]["outline"]) >= 3 and G.self_intersects([tuple(p) for p in h["board"]["outline"]]):
        add("outline", "The board outline crosses itself.", [0, 0], "", (), None, None)
    for k in h["keepouts"]:
        poly = [tuple(p) for p in k["polygon"]]
        for it in items:
            if not it["layers"] and it["kind"] != "hole":
                continue
            hit_layers = [layer for layer in (it["layers"] or ["F.Cu", "B.Cu"]) if layer in k["layers"]]
            if not hit_layers:
                continue
            if it["kind"] == "track" and not k["tracks"]:
                continue
            if it["kind"] == "via" and not k["vias"]:
                continue
            if it["kind"] == "pad" and not k["footprints"]:
                continue
            s = it["shape"]
            d = G.seg_poly(s[1], s[2], poly) - s[3] if s[0] == "cap" else G.poly_poly(s[1], poly)
            if d <= 0.0:
                add("keepout", "%s is inside keepout %s." % (label(it), k["id"]), center(it), hit_layers[0], (label(it), k["id"]), None, None)
    if act:
        act.step("courtyards", 0.6)
    courts = []
    for part in h["parts"]:
        w = world_courtyard(part)
        if w:
            courts.append((part, w))
    for a in range(len(courts)):
        for b in range(a + 1, len(courts)):
            pa, wa = courts[a]
            pb, wb = courts[b]
            if pa["side"] != pb["side"]:
                continue
            ba, bb = G.bbox(wa), G.bbox(wb)
            if ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1]:
                continue
            inter = Z.combine([Z.up(wa)], [Z.up(wb)], pc.CT_INTERSECTION)
            ar = sum(abs(G.area(Z.down(p))) for p in inter)
            if ar > 1e-3:
                add("courtyard", "Courtyards of %s and %s overlap by %.2f mm2." % (pa["refdes"], pb["refdes"], ar), mid(G.bbox(wa)[:2], G.bbox(wb)[:2]), "", (pa["refdes"], pb["refdes"]), ar, 0.0, "warning")
    placed = {p["refdes"] for p in h["parts"]}
    for p in h["netlist"].get("parts", []):
        if p["refdes"] and p["refdes"] not in placed:
            add("unplaced", "%s is in the netlist but not on the board." % p["refdes"], [0, 0], "", (p["refdes"],), None, None, "warning")
    fills = Z.fill_all(h) if include_zones and h["zones"] else []
    if act:
        act.step("zones", 0.75)
    for fill in fills:
        zone = next(z for z in h["zones"] if z["id"] == fill["id"])
        clr = max(zone["clearance"], eff["clearance"])
        if not fill["polygons"]:
            continue
        fpaths = []
        for p in fill["polygons"]:
            fpaths.append(Z.up(p["outline"]))
            for g in p["holes"]:
                fpaths.append(Z.up(g))
        fb = [min(p[0] for q in fill["polygons"] for p in q["outline"]), min(p[1] for q in fill["polygons"] for p in q["outline"]), max(p[0] for q in fill["polygons"] for p in q["outline"]), max(p[1] for q in fill["polygons"] for p in q["outline"])]
        for it in copper:
            if fill["layer"] not in it["layers"] or (it["net"] == fill["net"] and it["net"] != ""):
                continue
            bb = M.shape_bbox(it["shape"], clr)
            if bb[2] < fb[0] or bb[0] > fb[2] or bb[3] < fb[1] or bb[1] > fb[3]:
                continue
            grown = Z.offset([Z.up(M.shape_polygon(it["shape"]))], clr - 0.002)
            c = pc.Pyclipper()
            c.AddPaths(fpaths, pc.PT_SUBJECT, True)
            c.AddPaths(grown, pc.PT_CLIP, True)
            res = c.Execute(pc.CT_INTERSECTION, pc.PFT_EVENODD, pc.PFT_NONZERO)
            ar = sum(abs(G.area(Z.down(p))) for p in res)
            if ar > 1e-4:
                add("clearance", "%s is closer than %.3f mm to the %s pour on %s." % (label(it), clr, zone["id"], fill["layer"]), center(it), fill["layer"], (label(it), zone["id"]), None, clr)
    if act:
        act.step("connectivity", 0.9)
    rats = ratsnest(h, fills, [i for i in items if i["layers"]])
    for r in rats:
        add("unconnected", "Net %s: %s is not connected to %s." % (r["net"], r["from"], r["to"]), mid(r["a"], r["b"]), "", (r["from"], r["to"]), r["length"], None)
    counts = {}
    for v in viol:
        counts[v["type"]] = counts.get(v["type"], 0) + 1
    errors = sum(1 for v in viol if v["severity"] == "error")
    return {"violations": viol, "counts": counts, "errors": errors, "warnings": len(viol) - errors, "passed": errors == 0, "rules": eff, "profile": h["rules"].get("profile"), "ratsnest": rats, "seconds": round(time.time() - t0, 3), "truncated": len(viol) >= MAX_VIOLATIONS}
