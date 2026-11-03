import json
import math

from app.pcb import drc, jobs, route
from app.pcb import geom as G
from app.pcb import model as M
from app.pcb import rules as R
from app.pcb import store
from app.pcb import zones as Z


def pad_from_library(p: dict) -> dict:
    drill = p.get("drill")
    slot = None
    d = 0.0
    if isinstance(drill, dict):
        if "d" in drill:
            d = float(drill["d"])
        else:
            w, hh = float(drill.get("w", 0.0)), float(drill.get("h", 0.0))
            d = min(w, hh)
            slot = [w, hh]
    layers = []
    for name in p.get("layers", []):
        if name == "*.Cu":
            layers += ["F.Cu", "B.Cu"]
        elif name in ("F.Cu", "B.Cu") or (name.endswith(".Cu") and name.startswith("In")):
            layers.append(name)
    if not layers:
        layers = ["F.Cu", "B.Cu"] if d > 0 else ["F.Cu"]
    size = p.get("size") or [1.0, 1.0]
    pos = p.get("pos") or [0.0, 0.0]
    full = []
    for name in p.get("layers", []):
        full += ["F.Cu", "B.Cu"] if name == "*.Cu" else ["F.Mask", "B.Mask"] if name == "*.Mask" else [name]
    return {
        "number": p.get("number", "1"),
        "shape": p.get("shape", "rect"),
        "x": pos[0],
        "y": pos[1],
        "w": size[0],
        "h": size[1],
        "rot": p.get("rot", 0.0) or 0.0,
        "drill": d,
        "slot": slot,
        "plated": p.get("plated", True),
        "layers": layers,
        "layers_all": full or layers,
        "mask_margin": p.get("mask_margin"),
        "paste_margin": p.get("paste_margin"),
        "roundrect_ratio": p.get("roundrect_ratio") or 0.25,
        "poly": p.get("poly"),
    }


def part_body(refdes: str, comp: dict, fp: dict, x=0.0, y=0.0, rot=0.0, side="top") -> dict:
    return {
        "refdes": refdes,
        "uuid": comp.get("uuid", ""),
        "footprint": fp.get("id", comp.get("footprint", "")),
        "value": comp.get("value", ""),
        "x": x,
        "y": y,
        "rot": rot,
        "side": side,
        "pads": [pad_from_library(p) for p in fp.get("pads", [])],
        "courtyard": fp.get("courtyard") or None,
        "body": fp.get("body"),
        "silk": fp.get("silk") or [],
    }


def court_size(part: dict):
    court = part.get("courtyard")
    if court:
        xs = [p[0] for p in court]
        ys = [p[1] for p in court]
        return max(xs) - min(xs), max(ys) - min(ys), (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0
    xs = [p["x"] + p["w"] / 2 for p in part["pads"]] + [p["x"] - p["w"] / 2 for p in part["pads"]]
    ys = [p["y"] + p["h"] / 2 for p in part["pads"]] + [p["y"] - p["h"] / 2 for p in part["pads"]]
    return max(xs) - min(xs) + 1.0, max(ys) - min(ys) + 1.0, (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0


def netlist_for_board(nl: dict) -> dict:
    nets = []
    for n in nl.get("nets", []):
        pins = [[x["ref"], x["pin"]] for x in n.get("nodes", [])]
        nets.append({"name": n["name"], "pins": pins})
    parts = [{"refdes": c["ref"], "uuid": c.get("uuid", ""), "footprint": c.get("footprint", ""), "value": c.get("value", "")} for c in nl.get("components", [])]
    return {"nets": nets, "parts": parts}


def sync_ecad(d, place: bool = True, margin: float = 1.0) -> dict:
    from app.ecad import library, netlist

    nl = netlist.extract(d)
    board_nl = netlist_for_board(nl)
    store.set_netlist(d, board_nl)
    h = store.header(d)
    added, updated, missing, orphans = [], [], [], []
    by_uuid = {p.get("uuid"): p for p in h["parts"] if p.get("uuid")}
    by_ref = {p["refdes"]: p for p in h["parts"]}
    seen = set()
    for comp in nl.get("components", []):
        ref = comp["ref"]
        fid = comp.get("footprint") or ""
        if not fid:
            missing.append({"refdes": ref, "reason": "no footprint assigned"})
            continue
        try:
            fp = library.get_footprint(d, fid)
        except Exception:
            fp = None
        if not fp:
            missing.append({"refdes": ref, "reason": "footprint %s is not in a library" % fid})
            continue
        old = by_uuid.get(comp.get("uuid")) or by_ref.get(ref)
        seen.add(ref)
        if old is None:
            body = part_body(ref, comp, fp)
            store.place_part(d, body)
            added.append(ref)
        else:
            body = part_body(ref, comp, fp, old["x"], old["y"], old["rot"], old["side"])
            body["locked"] = old.get("locked", False)
            if old["refdes"] != ref or old["footprint"] != body["footprint"] or old["value"] != body["value"]:
                store.remove_part(d, old["refdes"])
                store.place_part(d, body)
                updated.append(ref)
    h = store.header(d)
    for p in h["parts"]:
        if p["refdes"] not in seen:
            orphans.append(p["refdes"])
    store.set_netlist(d, board_nl)
    laid = None
    if place and added:
        laid = auto_place(d, only=set(added), margin=margin)
    return {"added": added, "updated": updated, "missing": missing, "orphans": orphans, "placed": laid, "nets": len(board_nl["nets"]), "components": len(board_nl["parts"])}


def connectivity_order(h: dict, parts: list) -> list:
    net_parts = {}
    for n in h["netlist"]["nets"]:
        if len(n["pins"]) > 20 or n["name"].upper() in ("GND", "VCC", "VDD", "+5V", "+3V3", "VSS"):
            continue
        refs = {r for r, _ in n["pins"]}
        for r in refs:
            net_parts.setdefault(r, set()).update(refs - {r})
    size = {p["refdes"]: (court_size(p)[0] * court_size(p)[1]) for p in parts}
    left = {p["refdes"]: p for p in parts}
    order = []
    while left:
        seed = max(left, key=lambda r: (len(net_parts.get(r, ())) * 1000 + size[r], r))
        stack = [seed]
        while stack:
            r = stack.pop(0)
            if r not in left:
                continue
            order.append(left.pop(r))
            nxt = sorted((x for x in net_parts.get(r, ()) if x in left), key=lambda x: (-size[x], x))
            stack.extend(nxt)
    return order


def auto_place(d, only=None, margin: float = 1.0, edge: float = 2.0) -> dict:
    h = store.header(d)
    outline = h["board"]["outline"]
    if len(outline) < 3:
        raise store.PcbRecordError("Draw the board outline before placing.")
    x0, y0, x1, y1 = G.bbox(outline)
    x0, y0, x1, y1 = x0 + edge, y0 + edge, x1 - edge, y1 - edge
    todo = [p for p in h["parts"] if (only is None or p["refdes"] in only) and not p.get("locked")]
    fixed = [p for p in h["parts"] if p not in todo]
    taken = []
    for p in fixed:
        w = drc.world_courtyard(p)
        if w:
            taken.append(G.bbox(w))
    for hh in h["holes"]:
        r = max(hh["dia"], hh["drill"]) / 2.0 + 0.5
        taken.append((hh["x"] - r, hh["y"] - r, hh["x"] + r, hh["y"] + r))
    for k in h["keepouts"]:
        if k.get("footprints"):
            taken.append(G.bbox(k["polygon"]))
    ordered = connectivity_order(h, todo)
    ordered.sort(key=lambda p: -len(p["pads"]) if p["refdes"].startswith("J") else 0)
    cx, cy = x0, y0
    row_h = 0.0
    placed = []
    unplaced = []
    for part in ordered:
        w, hh, ox, oy = court_size(part)
        rot = 0.0
        if w > (x1 - x0) and hh <= (x1 - x0):
            rot = 90.0
            w, hh, ox, oy = hh, w, -oy, ox
        while True:
            if cx + w > x1 + 1e-9:
                cx = x0
                cy += row_h + margin
                row_h = 0.0
            if cy + hh > y1 + 1e-9:
                unplaced.append(part["refdes"])
                break
            box = (cx, cy, cx + w, cy + hh)
            clash = next((t for t in taken if not (t[2] + margin <= box[0] or box[2] + margin <= t[0] or t[3] + margin <= box[1] or box[3] + margin <= t[1])), None)
            if clash is not None:
                cx = clash[2] + margin
                continue
            part["x"] = round(cx + w / 2.0 - ox, 3)
            part["y"] = round(cy + hh / 2.0 - oy, 3)
            part["rot"] = rot
            taken.append(box)
            placed.append(part["refdes"])
            cx += w + margin
            row_h = max(row_h, hh)
            break
    store.save(d, h)
    return {"placed": placed, "unplaced": unplaced}


def fills_of(h: dict) -> list:
    return Z.fill_all(h)


def describe(h: dict) -> dict:
    return {
        "board": store.describe_board(h),
        "rules": dict(h["rules"], values=R.effective(h["rules"])),
        "counts": {"parts": len(h["parts"]), "pads": sum(len(p["pads"]) for p in h["parts"]), "tracks": len(h["tracks"]), "vias": len(h["vias"]), "zones": len(h["zones"]), "keepouts": len(h["keepouts"]), "holes": len(h["holes"]), "nets": len(h["netlist"]["nets"])},
        "parts": h["parts"],
        "tracks": h["tracks"],
        "vias": h["vias"],
        "zones": h["zones"],
        "keepouts": h["keepouts"],
        "holes": h["holes"],
        "netlist": h["netlist"],
        "last": h.get("last", {}),
    }


def snapshot_key(h: dict) -> str:
    return json.dumps({k: h[k] for k in ("board", "rules", "parts", "tracks", "vias", "zones", "keepouts", "holes")}, sort_keys=True)


def run_drc(d, act=None) -> dict:
    h = store.header(d)
    return drc.run(h, act)


def commit_routes(d, res: dict, replace_nets=None, runner_locked=False) -> dict:
    h = store.header(d)
    if replace_nets:
        h["tracks"] = [t for t in h["tracks"] if t["net"] not in replace_nets]
        h["vias"] = [v for v in h["vias"] if v["net"] not in replace_nets]
    tcap = store.MAX_TRACKS // (store.MACRO_FACTOR if runner_locked else 1)
    vcap = store.MAX_VIAS // (store.MACRO_FACTOR if runner_locked else 1)
    if len(h["tracks"]) + len(res["tracks"]) > tcap or len(h["vias"]) + len(res["vias"]) > vcap:
        raise store.PcbRecordError("The routed copper would exceed the track or via limit.")
    for t in res["tracks"]:
        t = dict(t)
        t["id"] = store.mint(h, "T")
        h["tracks"].append(t)
    for v in res["vias"]:
        v = dict(v)
        v["id"] = store.mint(h, "V")
        h["vias"].append(v)
    store.save(d, h)
    return {"tracks": len(res["tracks"]), "vias": len(res["vias"])}


def autoroute_job(doc, act, opts: dict, runner=None) -> dict:
    with doc.lock:
        h = store.header(doc.drawing)
        before = snapshot_key(h)
    res = route.autoroute(h, act, opts, runner)
    return {"result": res, "before": before}
