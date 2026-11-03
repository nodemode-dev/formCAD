import copy
import math

from app.core import guard
from app.costing import finding as FD
from app.solid import work

HEADER = "DFMRULE"
HUBS = "Hubs, How to design parts for CNC machining (hubs.com/knowledge-base/how-design-parts-cnc-machining), read 2026-11-03; vendor design guide, not a standard"
PROTO = "Protolabs, Sheet Metal Design Guidelines (protolabs.com/services/sheet-metal-fabrication/design-guidelines), read 2026-11-03; vendor design guide, not a standard"

RULES = {
    "wall_min_mm": {"value": 0.8, "process": "machining", "unit": "mm", "source": HUBS, "single": True, "note": "metal walls; 1.5 mm for plastics"},
    "wall_sample_margin_mm": {"value": 1.0, "process": "machining", "unit": "mm", "source": "FormCAD decision: wall samples are taken no closer than this to a face edge, because the sphere method reads small values at sharp corners", "single": False, "note": "measurement setting, not a design limit"},
    "hole_depth_ratio_warn": {"value": 10.0, "process": "machining", "unit": "x diameter", "source": HUBS, "single": True, "note": "about 4x is best, about 10x typical"},
    "hole_depth_ratio_error": {"value": 40.0, "process": "machining", "unit": "x diameter", "source": HUBS, "single": True, "note": "up to 40x only with special drills"},
    "corner_radius_ratio_min": {"value": 1.0 / 3.0, "process": "machining", "unit": "x cavity depth", "source": HUBS, "single": True, "note": "internal vertical corner radius at least one third of the cavity depth"},
    "thread_length_ratio_min": {"value": 1.5, "process": "machining", "unit": "x diameter", "source": HUBS, "single": True, "note": "3x recommended"},
    "sheet_hole_min_factor": {"value": 1.0, "process": "sheet_metal", "unit": "x thickness", "source": PROTO, "single": True, "note": "hole diameter at least the material thickness; a minimum hole size is also a common checker rule"},
    "sheet_feature_to_bend_factor": {"value": 4.0, "process": "sheet_metal", "unit": "x thickness", "source": PROTO, "single": True, "note": "features within about 4x thickness of a bend are at risk; one source (hole-to-bend)"},
    "sheet_edge_thin_mm": {"value": 1.574, "process": "sheet_metal", "unit": "mm", "source": PROTO, "single": True, "note": "hole to edge when the thickness is at most the thin limit"},
    "sheet_edge_thick_mm": {"value": 3.175, "process": "sheet_metal", "unit": "mm", "source": PROTO, "single": True, "note": "hole to edge for thicker sheet"},
    "sheet_thin_limit_mm": {"value": 0.914, "process": "sheet_metal", "unit": "mm", "source": PROTO, "single": True, "note": "thickness that switches the hole-to-edge distance"},
}


class DfmError(ValueError):
    pass


def current(d) -> dict:
    out = copy.deepcopy(RULES)
    raw = d.header.get(HEADER)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in out:
                out[k]["value"] = float(v)
                out[k]["user"] = True
    return out


def put(d, update: dict) -> dict:
    if not isinstance(update, dict):
        raise DfmError("The DFM thresholds are an object of numbers.")
    stored = d.header.get(HEADER)
    stored = dict(stored) if isinstance(stored, dict) else {}
    for k, v in update.items():
        if k not in RULES:
            raise DfmError("There is no DFM threshold %s." % k)
        if v is None:
            stored.pop(k, None)
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise DfmError("%s needs a number." % k)
        if not math.isfinite(x) or x < 0 or x > 1e6:
            raise DfmError("%s must be between 0 and 1000000." % k)
        stored[k] = x
    d.set_header(HEADER, stored or None)
    return current(d)


def fnd(rules, key, severity, message, part, ref=None, measured=None, limit=None):
    r = rules[key]
    return FD.make(key, severity, message, ref=ref, measured=measured, limit=limit, source=r["source"], category="dfm:" + r["process"], single_source=r["single"], part=part)


def machining(target: dict, f: dict, rules: dict, out: list, checked: list, skipped: list) -> None:
    d = target["drawing"]
    part = target["label"]
    agent = bool(guard.CALLER.get())
    for b in f["bodies"][:8]:
        ent = d.get(int(b["handle"]))
        wid = work.worker_id(d, ent)
        ins = work.kcall("pl_inspect", {"id": wid, "pull": [0, 0, 1], "grid": 3}, work.LONG)
        ref = {"body": b["handle"]}
        for row in ins["faces"]:
            if row.get("kind") != "cylinder" or not row.get("concave") or not row.get("radius"):
                continue
            r = float(row["radius"])
            span = math.radians(float(row.get("span_deg") or 0.0))
            if span <= 0:
                continue
            length = float(row["area"]) / (r * span)
            if row["span_deg"] >= 300:
                ratio = length / (2 * r)
                at = dict(ref, face=row["face"])
                if ratio > rules["hole_depth_ratio_error"]["value"]:
                    out.append(fnd(rules, "hole_depth_ratio_error", "error", "Hole of %.3g mm diameter is %.3g mm deep (%.1fx); beyond %.0fx needs special drills." % (2 * r, length, ratio, rules["hole_depth_ratio_error"]["value"]), part, at, round(ratio, 3), rules["hole_depth_ratio_error"]["value"]))
                elif ratio > rules["hole_depth_ratio_warn"]["value"]:
                    out.append(fnd(rules, "hole_depth_ratio_warn", "warning", "Hole of %.3g mm diameter is %.3g mm deep (%.1fx); about %.0fx is typical." % (2 * r, length, ratio, rules["hole_depth_ratio_warn"]["value"]), part, at, round(ratio, 3), rules["hole_depth_ratio_warn"]["value"]))
            elif 60.0 <= row["span_deg"] <= 120.0:
                need = length * rules["corner_radius_ratio_min"]["value"]
                if r < need - 1e-9:
                    out.append(fnd(rules, "corner_radius_ratio_min", "warning", "Internal corner radius %.3g mm on a %.3g mm deep wall; the guide asks for at least %.3g mm (one third of the depth)." % (r, length, need), part, dict(ref, face=row["face"]), round(r, 4), round(need, 4)))
        checked.append("hole_depth_ratio")
        checked.append("corner_radius_ratio_min")
        wsamples = 400 if agent else 1200
        wall = work.kcall("pl_wall", {"id": wid, "method": "sphere", "samples": wsamples, "margin": rules["wall_sample_margin_mm"]["value"]}, work.LONG)
        vals = [(v, i) for i, v in enumerate(wall["thickness"]) if v is not None]
        if vals:
            lo, idx = min(vals)
            lim = rules["wall_min_mm"]["value"]
            if lo < lim - 1e-9:
                out.append(fnd(rules, "wall_min_mm", "warning", "Thinnest sampled wall is %.3g mm; the guide recommends at least %.3g mm for metal." % (lo, lim), part, dict(ref, at=wall["points"][idx]), round(lo, 4), lim))
        checked.append("wall_min_mm (sphere method, %d samples)" % wsamples)
    skipped.append("thread length (needs thread data on hole features), cavity depth to width, tool access: not measured in this version")


def seg_points(seg: dict) -> list:
    t = seg.get("t")
    if t == "line":
        return [seg["a"], seg["b"]]
    if t == "arc":
        c, r = seg["c"], seg["r"]
        a0, a1 = seg["a0"], seg["a1"]
        if a1 < a0:
            a1 += 2 * math.pi
        n = 16
        return [[c[0] + r * math.cos(a0 + (a1 - a0) * i / n), c[1] + r * math.sin(a0 + (a1 - a0) * i / n)] for i in range(n + 1)]
    if t == "poly":
        return list(seg["pts"])
    return []


def point_segment(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + u * dx), p[1] - (ay + u * dy))


def outline_distance(p, loop: dict) -> float:
    best = math.inf
    for seg in loop["segs"]:
        pts = seg_points(seg)
        for a, b in zip(pts, pts[1:]):
            best = min(best, point_segment(p, a, b))
    return best


def sheet_metal(target: dict, f: dict, rules: dict, out: list, checked: list, skipped: list) -> None:
    from app.sheetmetal import flat

    d = target["drawing"]
    part = target["label"]
    if not f.get("sheet"):
        skipped.append("sheet metal rules: the part has no flat pattern")
        return
    res = flat.compute(d, f["bodies"][0]["handle"])
    t = float(res["thickness"])
    loops = res["loops"]
    outers = [lp for lp in loops if lp.get("outer")]
    holes = []
    for lp in loops:
        if lp.get("outer") or len(lp["segs"]) != 1 or lp["segs"][0].get("t") != "circle":
            continue
        s = lp["segs"][0]
        holes.append((s["c"], float(s["r"])))
    min_hole = rules["sheet_hole_min_factor"]["value"] * t
    edge_need = rules["sheet_edge_thin_mm"]["value"] if t <= rules["sheet_thin_limit_mm"]["value"] else rules["sheet_edge_thick_mm"]["value"]
    bend_zone = rules["sheet_feature_to_bend_factor"]["value"] * t
    for i, (c, r) in enumerate(holes):
        ref = {"hole": i, "at": [round(c[0], 3), round(c[1], 3)]}
        if 2 * r < min_hole - 1e-9:
            out.append(fnd(rules, "sheet_hole_min_factor", "warning", "Hole diameter %.3g mm is below the thickness %.3g mm." % (2 * r, t), part, ref, round(2 * r, 4), round(min_hole, 4)))
        if outers:
            gap = min(outline_distance(c, lp) for lp in outers) - r
            if gap < edge_need - 1e-9:
                key = "sheet_edge_thin_mm" if t <= rules["sheet_thin_limit_mm"]["value"] else "sheet_edge_thick_mm"
                out.append(fnd(rules, key, "warning", "Hole edge is %.3g mm from the outline; the guide asks for %.3g mm." % (gap, edge_need), part, ref, round(gap, 4), edge_need))
        for b in res["bends"]:
            gap = point_segment(c, b["a"], b["b"]) - r - float(b["ba"]) / 2.0
            if gap < bend_zone - 1e-9:
                out.append(fnd(rules, "sheet_feature_to_bend_factor", "warning", "Hole edge is %.3g mm from bend %s; features within %.3g mm (%gx thickness) are at risk." % (max(gap, 0.0), b["id"], bend_zone, rules["sheet_feature_to_bend_factor"]["value"]), part, dict(ref, bend=b["id"]), round(gap, 4), round(bend_zone, 4)))
    checked.extend(["sheet_hole_min_factor", "sheet edge distance", "sheet_feature_to_bend_factor (distance to the bend line minus half the bend allowance)"])
    skipped.append("minimum flange length (flange height is not in the flat pattern data): not measured in this version")


def molding(target: dict, f: dict, rules: dict, out: list, checked: list, skipped: list) -> None:
    from app.plastic import check, rule

    doc = target.get("doc")
    if doc is None:
        skipped.append("molding rules run on the open part only (not on an assembly component)")
        return
    if not rule.current(doc.drawing).get("defined"):
        skipped.append("molding rules: no plastic rule is saved in the part (set one in the plastic rule record first)")
        return
    res = check.run(doc, {"method": "sphere", "samples": 400 if guard.CALLER.get() else 1500})
    for x in res["findings"]:
        out.append(FD.make("plastic:" + str(x.get("tag") or x.get("kind")), x["severity"], x["message"], ref={k: x[k] for k in ("face", "face_key", "feature") if k in x}, measured=x.get("value"), limit=x.get("limit"), source="PL1 plastic rule record (cited per value in the plastic data)", category="dfm:molding", part=part))
    checked.append("plastic wall, draft, corners, ribs and bosses (PL1)")


def additive(target: dict, f: dict, rules: dict, out: list, checked: list, skipped: list) -> None:
    from app.additive import service, store

    doc = target.get("doc")
    if doc is None:
        skipped.append("additive rules run on the open part only (not on an assembly component)")
        return
    h = store.header(doc.drawing)
    handles = {int(b["handle"]) for b in f["bodies"]}
    done = 0
    for plate in h["plates"]:
        if not handles & {int(it["body"]) for it in plate.get("items", [])}:
            continue
        prof = store.find(h, "profiles", plate["profile"])
        if prof is None:
            continue
        for x in service.do_checks(doc, plate, prof):
            out.append(FD.make("additive:" + x["kind"], x["severity"], x["message"], ref=x.get("where"), source="AM1 print checks (slicer profile settings)", category="dfm:additive", part=part_label(target)))
        done += 1
    if not done:
        skipped.append("additive rules: the part is on no plate; place it on a plate first")
    else:
        checked.append("additive plate checks (AM1) on %d plate(s)" % done)


def part_label(target: dict) -> str:
    return target["label"]


RUNNERS = {"machining": machining, "sheet_metal": sheet_metal, "molding": molding, "additive": additive}


def run(target: dict, f: dict, process: str, rules: dict) -> dict:
    if process not in RUNNERS:
        raise DfmError("DFM processes are machining, sheet_metal, additive and molding.")
    out: list = []
    checked: list = []
    skipped: list = []
    RUNNERS[process](target, f, rules, out, checked, skipped)
    return {"part": target["label"], "process": process, "findings": out, "checked": checked, "skipped": skipped, "summary": FD.counts(out)}
