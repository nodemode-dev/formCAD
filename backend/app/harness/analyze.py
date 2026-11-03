import heapq
import math

import numpy as np

from app.harness import rules
from app.harness.store import HarnessError
from app.routing import path as rpath


def world_matrices(doc) -> dict:
    from app.assembly import walk

    return {i.key: i.world for i in walk.instances(doc) if not i.suppressed}


def node_world(d, node, mats, mpu) -> tuple:
    p = np.array(node["p"], float)
    ax = np.array(node["axis"], float)
    ax = ax / np.linalg.norm(ax)
    comp = node.get("component")
    if not comp:
        return p, ax
    m = mats.get(comp)
    if m is None:
        raise HarnessError("%s sits on component %s, which is not in the assembly (or is suppressed)." % (node["id"], comp))
    r = m[:3, :3]
    return r @ p + m[:3, 3] * mpu, r @ ax


def positions(doc, h) -> dict:
    from app.param.units import mm_per_unit

    d = doc.drawing if hasattr(doc, "drawing") else doc
    mats = world_matrices(doc) if any(n.get("component") for n in h["nodes"].values()) else {}
    mpu = mm_per_unit(d)
    return {i: node_world(d, n, mats, mpu) for i, n in h["nodes"].items()}


def seg_points(h, seg, pos) -> list:
    ids = [seg["a"]] + list(seg["via"]) + [seg["b"]]
    return [pos[i][0] for i in ids]


def chord_length(points) -> float:
    return float(sum(np.linalg.norm(np.array(points[i + 1]) - np.array(points[i])) for i in range(len(points) - 1)))


def route(h, graph, a, b):
    dist = {a: 0.0}
    prev = {}
    heap = [(0.0, a)]
    while heap:
        dd, u = heapq.heappop(heap)
        if dd > dist.get(u, math.inf):
            continue
        if u == b:
            break
        for v, sid, w in graph.get(u, ()):
            nd = dd + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = (u, sid)
                heapq.heappush(heap, (nd, v))
    if b not in dist:
        return None
    out, cur = [], b
    while cur != a:
        u, sid = prev[cur]
        out.append(sid)
        cur = u
    return out[::-1]


def run(doc, h) -> dict:
    pos = positions(doc, h)
    st = h["settings"]
    segs = h["segments"]
    pts = {sid: seg_points(h, s, pos) for sid, s in segs.items()}
    graph = {}
    for sid, s in segs.items():
        w = chord_length(pts[sid])
        graph.setdefault(s["a"], []).append((s["b"], sid, w))
        graph.setdefault(s["b"], []).append((s["a"], sid, w))
    warnings = []
    cable_of = {w: c["id"] for c in h["cables"].values() for w in c["cores"]}
    routes = {}
    for wid, w in h["wires"].items():
        r = route(h, graph, w["from"]["node"], w["to"]["node"])
        if r is None:
            raise HarnessError("Wire %s has no route from %s to %s through the segments." % (wid, w["from"]["node"], w["to"]["node"]))
        routes[wid] = r
    carried = {sid: [] for sid in segs}
    cable_routes = {}
    for cid, c in h["cables"].items():
        cable_routes[cid] = routes[c["cores"][0]]
        for sid in cable_routes[cid]:
            carried[sid].append(("cable", cid, c["od"], c["min_radius"]))
    for wid, w in h["wires"].items():
        if wid in cable_of:
            continue
        for sid in routes[wid]:
            carried[sid].append(("wire", wid, w["od"], w["min_radius"]))
    seg_rep = {}
    for sid, s in segs.items():
        items = carried[sid]
        ods = [i[2] for i in items]
        try:
            auto = rules.bundle_diameter(ods, s["shield"] or any(h["cables"][i[1]]["shield"] for i in items if i[0] == "cable"), s["covering"])
        except rules.RuleError as err:
            if not s["diameter"]:
                raise HarnessError("%s: %s" % (sid, err))
            auto = s["diameter"]
        od = s["diameter"] or auto
        override = max([s["min_radius"]] + [i[3] for i in items])
        required = max(st["min_bend_factor"] * od, override)
        requested = max(s["radius"], required)
        if s["radius"] and s["radius"] < required:
            requested = s["radius"]
        p = pts[sid]
        if len(set(map(tuple, np.round(p, 6)))) < len(p):
            raise HarnessError("%s passes through the same point twice." % sid)
        try:
            res = rpath.fillet_polyline(p, requested, required) if s["mode"] == "fillet" else rpath.spline_path(p, required)
        except rpath.PathError as err:
            raise HarnessError("%s: %s" % (sid, err))
        if s["radius"] and s["radius"] < required and s["mode"] == "fillet":
            res["violations"].append({"index": -1, "point": p[0].tolist(), "radius": round(s["radius"], 4), "required": round(required, 4), "note": "set radius is below the minimum"})
            res["ok"] = False
        if not items:
            warnings.append("%s carries no wires." % sid)
        seg_rep[sid] = {"id": sid, "a": s["a"], "b": s["b"], "via": list(s["via"]), "mode": s["mode"], "length": res["length"], "chord": round(chord_length(p), 4), "od": round(od, 3), "od_auto": round(auto, 3), "count": len(items), "required_radius": round(required, 3), "radius_used": requested, "tightest": res["tightest"], "ok": res["ok"], "violations": res["violations"], "path": res, "carries": [i[1] for i in items]}
    wires = []
    for wid, w in h["wires"].items():
        run_len = sum(seg_rep[s]["length"] for s in routes[wid])
        cut = w["length"] if w["length"] else run_len + w["allowance_from"] + w["allowance_to"]
        wires.append({"id": wid, "cable": w.get("cable", ""), "from": w["from"], "to": w["to"], "gauge": w["gauge"], "colour": w["colour"], "net": w["net"], "od": round(w["od"], 3), "route": routes[wid], "run": round(run_len, 4), "allowance": round(w["allowance_from"] + w["allowance_to"], 4), "cut": round(cut, 4), "override": bool(w["length"])})
    for n in h["nodes"].values():
        if n["kind"] == "connector":
            used = {}
            for w in h["wires"].values():
                for e in (w["from"], w["to"]):
                    if e["node"] == n["id"]:
                        used.setdefault(e["pin"], []).append(w["id"])
            for pin, ws in used.items():
                if len(ws) > 1:
                    warnings.append("%s pin %s carries %d wires (%s)." % (n["id"], pin, len(ws), ", ".join(ws)))
    bad = [s for s in seg_rep.values() if not s["ok"]]
    return {"nodes": {i: {"p": [round(float(x), 4) for x in p], "axis": [round(float(x), 5) for x in a]} for i, (p, a) in pos.items()}, "segments": list(seg_rep.values()), "wires": wires, "cables": [{"id": c["id"], "od": c["od"], "cores": c["cores"], "route": cable_routes[c["id"]]} for c in h["cables"].values()], "violations": sum(len(s["violations"]) for s in bad), "segments_over": [s["id"] for s in bad], "warnings": warnings, "flags": rules.FLAGS, "totals": {"nodes": len(h["nodes"]), "segments": len(segs), "wires": len(h["wires"]), "cables": len(h["cables"]), "wire_length": round(sum(w["cut"] for w in wires), 2)}}
