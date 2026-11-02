import math
import re

from app.doc import geom, measure, planar, purge
from app.doc.model import SPACE_MODEL, block_space, layout_space

DEFAULT_LIMIT = 200
MAX_LIMIT = 5000
MAX_EDGES = 4000
DEFAULT_PAIRS = 1_000_000
MAX_PAIRS = 100_000_000
MAX_NAMES = 5000
MAX_OBJECTS = 5_000_000
SLACK = 1.0001

_CODE_ARG = re.compile(r"\\[fFcCtTqQwWaAhH][^;]*;")
_STACK = re.compile(r"\\[sS]([^;]*);")
_TOGGLE = re.compile(r"\\[LlOoKk]")


def plain_text(src: str) -> str:
    t = str(src or "")
    t = t.replace("\\\\", "\x00").replace("\\{", "\x01").replace("\\}", "\x02")
    t = _STACK.sub(lambda m: m.group(1).replace("^", "/").replace("#", "/"), t)
    t = _CODE_ARG.sub("", t)
    t = _TOGGLE.sub("", t)
    t = re.sub(r"\\[pP]", "\n", t).replace("\\~", " ").replace("\\X", "\n")
    t = re.sub(r"\\[A-Za-z]", "", t)
    t = t.replace("{", "").replace("}", "")
    return t.replace("\x00", "\\").replace("\x01", "{").replace("\x02", "}")


def clamp(limit, default=DEFAULT_LIMIT) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, MAX_LIMIT))


def space_of(doc, name=None) -> str:
    if not name:
        return doc.current_space
    low = str(name).strip()
    if low.lower() == "model":
        return SPACE_MODEL
    for rec in doc.drawing.tables["layouts"].values():
        if rec["name"].casefold() == low.casefold():
            return layout_space(rec["name"])
    raise ValueError('There is no space named "%s".' % name)


def rnd(v):
    if isinstance(v, float):
        return round(v, 9) + 0.0
    if isinstance(v, (list, tuple)):
        return [rnd(x) for x in v]
    if isinstance(v, dict):
        return {k: rnd(x) for k, x in v.items()}
    return v


def geometry(e) -> dict:
    k = e.kind
    out = {}
    if k == "line":
        out = {"start": e.start, "end": e.end, "length": geom.dist(e.start, e.end)}
    elif k == "circle":
        out = {"center": e.center, "radius": e.radius}
    elif k == "arc":
        out = {"center": e.center, "radius": e.radius, "start_angle": math.degrees(e.start_angle), "end_angle": math.degrees(e.end_angle)}
    elif k == "ellipse":
        out = {"center": e.center, "major": e.major, "ratio": e.ratio}
    elif k == "point":
        out = {"position": e.position}
    elif k == "lwpolyline":
        out = {"vertices": len(e.vertices), "closed": bool(e.closed)}
        try:
            area, perim = measure.entity_measure(e)
            out["length"] = perim
            if e.closed:
                out["area"] = area
        except measure.NoArea:
            pass
    elif k == "text":
        out = {"text": e.text, "position": e.position, "height": e.height}
    elif k == "mtext":
        out = {"text": plain_text(e.contents), "position": e.position, "height": e.height}
    elif k == "insert":
        out = {"block": e.block, "position": e.position, "rotation": math.degrees(e.rotation), "scale": e.scale}
    elif k == "hatch":
        out = {"pattern": getattr(e, "pattern", "")}
    elif k == "dimension":
        out = {"measurement": getattr(e, "measurement", None)}
    elif k == "spline":
        out = {"degree": e.degree, "closed": bool(e.closed), "points": len(e.fit_points or e.control_points)}
    b = e.bounds()
    if b is not None:
        out["bounds"] = list(b)
    return rnd(out)


def entity_row(e) -> dict:
    return {"handle": e.handle, "type": e.kind, "layer": e.layer, "color": e.color, "transparency": e.transparency, "space": e.owner, "geometry": geometry(e)}


def inspect_drawing(doc, limit=DEFAULT_LIMIT) -> dict:
    d = doc.drawing
    n = clamp(limit)
    counts = {}
    for e in d.ents.values():
        counts[e.kind] = counts.get(e.kind, 0) + 1
    box = d.extents(doc.current_space if doc.current_space in d.spaces else SPACE_MODEL)
    labels = [s.label for s in doc.undo.steps[-10:]]
    return {
        "title": doc.name,
        "path": doc.path,
        "unsaved": bool(doc.dirty),
        "rev": doc.rev,
        "editing_block": bool(d.tables["blocks"].values() and any(r.get("edit") for r in d.tables["blocks"].values())),
        "space": doc.current_space,
        "objects": len(d.ents),
        "counts": dict(sorted(counts.items())),
        "extents": list(box) if box else None,
        "recent_undo": labels,
        "layers": [{"name": r["name"], "color": r["color"], "on": r["on"], "frozen": r["frozen"], "locked": r["locked"]} for r in d.tables["layers"].values()][:n],
        "layer_count": len(d.tables["layers"]),
        "layouts": [r["name"] for r in d.tables["layouts"].values()],
    }


def query_entities(doc, types=None, layers=None, selection=False, window=None, crossing=True, limit=DEFAULT_LIMIT, offset=0, space=None) -> dict:
    d = doc.drawing
    sp = space_of(doc, space)
    tset = {str(t).lower() for t in types} if types else None
    lset = {str(x).casefold() for x in layers} if layers else None
    sel = set(doc.selection) if selection else None
    box = None
    if window:
        if len(window) != 4 or not all(isinstance(v, (int, float)) for v in window):
            raise ValueError("The window is [x0, y0, x1, y1].")
        box = (min(window[0], window[2]), min(window[1], window[3]), max(window[0], window[2]), max(window[1], window[3]))
    found = []
    for e in d.entities(sp):
        if tset is not None and e.kind not in tset:
            continue
        if lset is not None and e.layer.casefold() not in lset:
            continue
        if sel is not None and e.handle not in sel:
            continue
        if box is not None:
            b = e.bounds()
            if b is None:
                continue
            if crossing:
                if not geom.boxes_overlap(b, box):
                    continue
            elif not geom.box_inside(b, box):
                continue
        found.append(e)
    n = clamp(limit)
    off = max(0, int(offset or 0))
    page = found[off : off + n]
    return {"space": sp, "matched": len(found), "returned": len(page), "offset": off, "limit": n, "entities": [entity_row(e) for e in page]}


def text_rows(d, sp) -> list:
    rows = []
    for e in d.entities(sp):
        k = e.kind
        if k == "text":
            rows.append({"handle": e.handle, "type": k, "text": e.text, "position": e.position, "height": e.height, "rotation": math.degrees(e.rotation), "style": e.style, "layer": e.layer})
        elif k == "mtext":
            rows.append({"handle": e.handle, "type": k, "text": plain_text(e.contents), "position": e.position, "height": e.height, "rotation": math.degrees(e.rotation), "style": e.style, "layer": e.layer})
        elif k == "mleader":
            rows.append({"handle": e.handle, "type": k, "text": plain_text(e.text), "position": e.content_pos, "height": e.text_height or 0.0, "rotation": 0.0, "style": e.text_style or e.style, "layer": e.layer})
        elif k == "insert":
            for a in e.attributes or []:
                at = a.get("at") or e.position
                rows.append({"handle": e.handle, "type": "attribute", "tag": a.get("tag", ""), "text": str(a.get("value", "")), "position": list(at), "height": a.get("height", 0.0), "rotation": math.degrees(e.rotation), "style": a.get("style", ""), "layer": a.get("layer", e.layer)})
    return rows


def query_texts(doc, contains="", layer="", window=None, limit=DEFAULT_LIMIT, space=None) -> dict:
    sp = space_of(doc, space)
    rows = text_rows(doc.drawing, sp)
    if contains:
        low = str(contains).lower()
        rows = [r for r in rows if low in r["text"].lower()]
    if layer:
        rows = [r for r in rows if str(r["layer"]).casefold() == str(layer).casefold()]
    if window:
        x0, y0, x1, y1 = min(window[0], window[2]), min(window[1], window[3]), max(window[0], window[2]), max(window[1], window[3])
        rows = [r for r in rows if x0 <= r["position"][0] <= x1 and y0 <= r["position"][1] <= y1]
    n = clamp(limit)
    return {"space": sp, "matched": len(rows), "returned": min(n, len(rows)), "texts": [rnd(r) for r in rows[:n]]}


def diagonal(d, sp) -> float:
    box = d.extents(sp)
    return math.hypot(box[2] - box[0], box[3] - box[1]) if box else 0.0


def ring_of(e):
    k = e.kind
    if k == "lwpolyline" and e.closed:
        return e.vertices
    if k == "circle":
        c, r = e.center, e.radius
        return [{"p": [c[0] + r, c[1]], "bulge": 1.0}, {"p": [c[0] - r, c[1]], "bulge": 1.0}]
    return None


def signed_area(verts) -> float:
    s = 0.0
    seg = 0.0
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        s += a["p"][0] * b["p"][1] - b["p"][0] * a["p"][1]
        seg += measure.segment_info(a["p"], b["p"], a.get("bulge", 0.0) or 0.0)[1]
    return s / 2.0 + seg


def centroid(verts):
    pts = planar.flatten_loop(verts, 0.02)
    a = 0.0
    cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    if abs(a) < 1e-300:
        return None
    return [cx / (3.0 * a), cy / (3.0 * a)]


def seg_cross(p, q, r, s):
    d1x, d1y = q[0] - p[0], q[1] - p[1]
    d2x, d2y = s[0] - r[0], s[1] - r[1]
    den = d1x * d2y - d1y * d2x
    if abs(den) < 1e-18:
        return None
    t = ((r[0] - p[0]) * d2y - (r[1] - p[1]) * d2x) / den
    u = ((r[0] - p[0]) * d1y - (r[1] - p[1]) * d1x) / den
    if 1e-12 < t < 1 - 1e-12 and 1e-12 < u < 1 - 1e-12:
        return [p[0] + t * d1x, p[1] + t * d1y]
    return None


def first_self_intersection(pts):
    n = len(pts)
    if n > MAX_EDGES:
        return None
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, e = pts[j], pts[(j + 1) % n]
            hit = seg_cross(a, b, c, e)
            if hit:
                return hit
    return None


def analyze_shapes(doc, types=None, layers=None, window=None, crossing=True, limit=DEFAULT_LIMIT, offset=0, space=None) -> dict:
    d = doc.drawing
    sp = space_of(doc, space)
    tset = {str(t).lower() for t in types} if types else None
    lset = {str(x).casefold() for x in layers} if layers else None
    diag = diagonal(d, sp)
    tol = 1e-9 * diag
    box = d.extents(sp)
    cap = (box[2] - box[0]) * (box[3] - box[1]) if box else 0.0
    rows = []
    skipped = {}
    suspicious = []
    seen = 0
    for e in d.entities(sp):
        if tset is not None and e.kind not in tset:
            continue
        if lset is not None and e.layer.casefold() not in lset:
            continue
        if window:
            b = e.bounds()
            w = (min(window[0], window[2]), min(window[1], window[3]), max(window[0], window[2]), max(window[1], window[3]))
            if b is None or not (geom.boxes_overlap(b, w) if crossing else geom.box_inside(b, w)):
                continue
        seen += 1
        verts = ring_of(e)
        if verts is None and e.kind == "ellipse" and abs(e.end_param - e.start_param) >= geom.TAU - 1e-12:
            pts = [(p[0], p[1]) for p in e.sample(96)][:-1]
            area, perim = measure.entity_measure(e)
            row = {"handle": e.handle, "type": e.kind, "perimeter": perim, "area": area, "centroid": rnd(list(e.center[:2])), "winding": "counterclockwise", "self_intersection": None, "near_duplicates": []}
            rows.append(row)
            if cap and area > cap * SLACK * 4:
                suspicious.append(e.handle)
            continue
        if verts is None and e.kind == "spline" and e.closed:
            try:
                area, perim = measure.entity_measure(e)
            except measure.NoArea:
                skipped["spline without area"] = skipped.get("spline without area", 0) + 1
                continue
            rows.append({"handle": e.handle, "type": e.kind, "perimeter": perim, "area": area, "centroid": None, "winding": None, "self_intersection": None, "near_duplicates": []})
            continue
        if verts is None:
            why = "open polyline" if e.kind == "lwpolyline" else ("%s is not a closed shape" % e.kind)
            skipped[why] = skipped.get(why, 0) + 1
            continue
        area, perim = measure.polygon_measure(verts, True)
        sa = signed_area(verts)
        pts = planar.flatten_loop(verts, 0.05)
        dups = []
        for i, v in enumerate(verts):
            w = verts[(i + 1) % len(verts)]
            if len(verts) > 2 and geom.dist(v["p"], w["p"]) <= max(tol, 1e-300):
                dups.append(i)
        cen = centroid(verts) if abs(sa) > 1e-300 else None
        rows.append({"handle": e.handle, "type": e.kind, "perimeter": perim, "area": area, "centroid": rnd(cen) if cen else None, "winding": None if sa == 0 else ("counterclockwise" if sa > 0 else "clockwise"), "self_intersection": rnd(first_self_intersection(pts)) if len(pts) <= MAX_EDGES else None, "self_intersection_checked": len(pts) <= MAX_EDGES, "near_duplicates": dups})
        if cap and area > cap * SLACK:
            suspicious.append(e.handle)
    n = clamp(limit)
    off = max(0, int(offset or 0))
    page = rows[off : off + n]
    return {
        "space": sp,
        "shapes": [rnd(r) for r in page],
        "matched": len(rows),
        "returned": len(page),
        "self_check": {"objects_found": seen, "analysed": len(rows), "skipped": skipped, "capped": len(rows) > off + n, "impossible_values": suspicious, "tolerance": tol},
    }


def segment_ends(e):
    if e.kind == "line":
        return [e.start[0], e.start[1]], [e.end[0], e.end[1]]
    c, r = e.center, e.radius
    return [c[0] + r * math.cos(e.start_angle), c[1] + r * math.sin(e.start_angle)], [c[0] + r * math.cos(e.end_angle), c[1] + r * math.sin(e.end_angle)]


def segment_bulge(e) -> float:
    if e.kind != "arc":
        return 0.0
    return math.tan(geom.ccw_sweep(e.start_angle, e.end_angle) / 4.0)


def implied_loops(doc, tolerance=None, max_pairs=DEFAULT_PAIRS, space=None) -> dict:
    d = doc.drawing
    sp = space_of(doc, space)
    diag = diagonal(d, sp)
    tol = float(tolerance) if tolerance else max(1e-9 * diag, 1e-12)
    cap = min(int(max_pairs or DEFAULT_PAIRS), MAX_PAIRS)
    segs = [e for e in d.entities(sp) if e.kind in ("line", "arc")]
    ends = []
    for i, e in enumerate(segs):
        a, b = segment_ends(e)
        ends.append((a, i, 0))
        ends.append((b, i, 1))
    n = len(ends)
    pairs = n * (n - 1) // 2
    out = {"space": sp, "tolerance": tol, "segments": len(segs), "loops": [], "chains": [], "junctions": [], "spurs": [], "state": "complete", "pairs": pairs, "max_pairs": cap}
    if pairs > cap:
        out["state"] = "capped"
        return out
    order = sorted(range(n), key=lambda k: ends[k][0][0])
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for oi in range(n):
        i = order[oi]
        pi = ends[i][0]
        for oj in range(oi + 1, n):
            j = order[oj]
            pj = ends[j][0]
            if pj[0] - pi[0] > tol:
                break
            if abs(pj[1] - pi[1]) <= tol:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb
    node_of = {}
    node_pts = {}
    for k in range(n):
        r = find(k)
        node_of[k] = r
        node_pts.setdefault(r, []).append(ends[k][0])
    seg_nodes = {}
    for k in range(n):
        seg_nodes.setdefault(ends[k][1], [None, None])[ends[k][2]] = node_of[k]
    degree = {}
    for si, (a, b) in seg_nodes.items():
        if a == b:
            continue
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    junction_nodes = {nd for nd, dg in degree.items() if dg >= 3}
    for nd in sorted(junction_nodes):
        pts = node_pts[nd]
        out["junctions"].append({"point": rnd([sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]), "ends": degree[nd], "handles": sorted({segs[si].handle for si, (a, b) in seg_nodes.items() if nd in (a, b) and a != b})})
    live = {}
    for si, (a, b) in seg_nodes.items():
        if a == b:
            out["spurs"].append(segs[si].handle)
            continue
        if a in junction_nodes or b in junction_nodes:
            continue
        live[si] = (a, b)
    adj = {}
    for si, (a, b) in live.items():
        adj.setdefault(a, []).append(si)
        adj.setdefault(b, []).append(si)
    used = set()

    def walk(start_node, first_seg):
        order_s = []
        node = start_node
        si = first_seg
        while si is not None and si not in used:
            used.add(si)
            a, b = live[si]
            nxt = b if a == node else a
            order_s.append((si, a == node))
            node = nxt
            si = next((x for x in adj.get(node, []) if x not in used), None)
        return order_s, node

    def verts_of(order_s):
        verts = []
        for si, fwd in order_s:
            e = segs[si]
            a, b = segment_ends(e)
            bg = segment_bulge(e)
            if fwd:
                verts.append({"p": a, "bulge": bg})
            else:
                verts.append({"p": b, "bulge": -bg})
        return verts

    for nd in sorted(adj, key=lambda x: str(x)):
        if len(adj[nd]) == 1:
            first = adj[nd][0]
            if first in used:
                continue
            order_s, end_node = walk(nd, first)
            p0 = node_pts[nd][0]
            p1 = node_pts[end_node][0]
            gap = geom.dist(p0, p1)
            out["chains"].append({"handles": [segs[si].handle for si, _f in order_s], "gap": gap, "location": rnd([(p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0]), "ends": rnd([p0, p1]), "length": sum(measure.segment_info(*segment_ends(segs[si]), segment_bulge(segs[si]))[0] for si, _f in order_s)})
    for nd in sorted(adj, key=lambda x: str(x)):
        for first in list(adj[nd]):
            if first in used:
                continue
            order_s, end_node = walk(nd, first)
            verts = verts_of(order_s)
            if end_node != nd or len(verts) < 2:
                out["chains"].append({"handles": [segs[si].handle for si, _f in order_s], "gap": 0.0, "location": rnd(node_pts[nd][0]), "ends": rnd([node_pts[nd][0], node_pts[end_node][0]]), "length": 0.0})
                continue
            sa = signed_area(verts)
            area, perim = measure.polygon_measure(verts, True)
            out["loops"].append({"handles": [segs[si].handle for si, _f in order_s], "perimeter": perim, "area": abs(sa), "signed_area": sa, "winding": "counterclockwise" if sa > 0 else "clockwise"})
    out["loops"] = rnd(out["loops"])
    out["chains"] = rnd(out["chains"])
    return out


def usage_spaces(d):
    yield "model", d.entities(SPACE_MODEL)
    for rec in d.tables["layouts"].values():
        yield "layout", d.entities(layout_space(rec["name"]))
    for rec in d.tables["blocks"].values():
        yield "block", d.entities(block_space(rec["name"]))


def analyze_usage(doc, kind="all", limit=DEFAULT_LIMIT, offset=0) -> dict:
    d = doc.drawing
    cats = {"layers": "layers", "blocks": "blocks", "textstyles": "textstyles", "linetypes": "linetypes"}
    pick = list(cats) if kind in ("all", "", None) else [kind] if kind in cats else None
    if pick is None:
        raise ValueError("Type is layers, blocks, textstyles, linetypes or all.")
    counts = {c: {} for c in pick}
    seen = 0
    incomplete = False
    for where, ents in usage_spaces(d):
        for e in ents:
            seen += 1
            if seen > MAX_OBJECTS:
                incomplete = True
                break
            keys = []
            if "layers" in pick:
                keys.append(("layers", e.layer))
            if "linetypes" in pick and e.linetype and e.linetype.lower() not in ("bylayer", "byblock"):
                keys.append(("linetypes", e.linetype))
            if "blocks" in pick and e.kind == "insert":
                keys.append(("blocks", e.block))
            if "textstyles" in pick and getattr(e, "style", None) and e.kind in ("text", "mtext", "attdef"):
                keys.append(("textstyles", e.style))
            for cat, name in keys:
                slot = counts[cat].setdefault(str(name).casefold(), {"model": 0, "layout": 0, "block": 0})
                slot[where] += 1
        if incomplete:
            break
    result = {}
    current = {"layers": d.header.get("CLAYER", "0"), "textstyles": d.header.get("TEXTSTYLE", "Standard"), "linetypes": d.header.get("CELTYPE", "ByLayer"), "blocks": ""}
    for cat in pick:
        table = d.tables[cat]
        rows = []
        unused = set(n.casefold() for n in purge.candidates(d, cat)) if cat in purge.CATEGORIES else set()
        refs = purge.referenced(d, cat) if cat in purge.CATEGORIES else set()
        refs = {str(x).casefold() for x in refs}
        for rec in table.values():
            nm = rec["name"]
            if cat == "blocks" and (rec.get("anonymous") or rec.get("xref")):
                continue
            c = counts[cat].get(nm.casefold(), {"model": 0, "layout": 0, "block": 0})
            outside = c["model"] + c["layout"]
            if outside:
                status = "used"
            elif c["block"]:
                status = "used only inside blocks"
            elif nm.casefold() in refs:
                status = "referenced by other objects"
            elif nm.casefold() in unused:
                status = "unused"
            else:
                status = "empty"
            rows.append({"name": nm, "model": c["model"], "layouts": c["layout"], "in_blocks": c["block"], "status": status, "current": nm.casefold() == str(current[cat]).casefold(), "referenced_by_objects": nm.casefold() in refs})
        summary = {}
        for r in rows:
            summary[r["status"]] = summary.get(r["status"], 0) + 1
        n = clamp(limit)
        off = max(0, int(offset or 0))
        result[cat] = {"total": len(rows), "summary": summary, "items": rows[off : off + n], "unused": [r["name"] for r in rows if r["status"] == "unused"][:MAX_NAMES]}
    return {"incomplete": incomplete, "objects_read": min(seen, MAX_OBJECTS), "usage": result}
