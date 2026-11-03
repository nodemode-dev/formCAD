import copy
import math

from app.pcb import rules as R
from app.pcb.geom import area, self_intersects

SCHEMA = 1
HEADER = "ECAD_PCB"
MAX_PARTS = 2000
MAX_PADS = 20000
MAX_TRACKS = 40000
MAX_VIAS = 8000
MAX_ZONES = 64
MAX_KEEPOUTS = 128
MAX_HOLES = 256
MAX_POINTS = 4000
MAX_NETS = 4000
MACRO_FACTOR = 4
COORD = 1000000.0
SHAPES = ("circle", "rect", "roundrect", "oval", "poly")
CONNECT = ("thermal", "solid", "none")
COPPER_NAMES = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"]


class PcbRecordError(ValueError):
    pass


def copper_layers(n: int) -> list:
    n = int(n)
    if n == 2:
        return ["F.Cu", "B.Cu"]
    return ["F.Cu"] + ["In%d.Cu" % i for i in range(1, n - 1)] + ["B.Cu"]


def default_stackup(n: int = 2) -> list:
    layers = copper_layers(n)
    out = [{"kind": "mask", "name": "F.Mask", "thickness": 0.015, "material": "solder resist"}]
    for i, name in enumerate(layers):
        out.append({"kind": "copper", "name": name, "thickness": 0.035, "material": "copper 1 oz"})
        if i < len(layers) - 1:
            if i % 2 == 0:
                out.append({"kind": "core", "name": "Core %d" % (i // 2 + 1), "thickness": 1.53 if n == 2 else 0.4, "material": "FR-4", "epsilon_r": 4.5})
            else:
                out.append({"kind": "prepreg", "name": "Prepreg %d" % (i // 2 + 1), "thickness": 0.2, "material": "FR-4 prepreg", "epsilon_r": 4.4})
    out.append({"kind": "mask", "name": "B.Mask", "thickness": 0.015, "material": "solder resist"})
    return out


def blank() -> dict:
    return {
        "schema": SCHEMA,
        "next": 1,
        "board": {"outline": [], "cutouts": [], "layers": 2, "stackup": default_stackup(2), "finish": "HASL"},
        "rules": R.default_rules(),
        "netlist": {"nets": [], "parts": []},
        "parts": [],
        "tracks": [],
        "vias": [],
        "zones": [],
        "keepouts": [],
        "holes": [],
        "last": {},
    }


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    for k in ("parts", "tracks", "vias", "zones", "keepouts", "holes"):
        if not isinstance(out.get(k), list):
            out[k] = []
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def mint(h: dict, prefix: str) -> str:
    n = int(h.get("next", 1))
    h["next"] = n + 1
    return "%s%d" % (prefix, n)


def num(v, label: str, lo=-1e6, hi=1e6) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise PcbRecordError("%s must be a number." % label)
    if not math.isfinite(f) or not lo <= f <= hi:
        raise PcbRecordError("%s is between %g and %g." % (label, lo, hi))
    return round(f, 6)


def point(v, label="point") -> list:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise PcbRecordError("A %s is [x, y] in millimetres." % label)
    return [num(v[0], label, -5000, 5000), num(v[1], label, -5000, 5000)]


def polygon(v, label="outline", minimum=3) -> list:
    if not isinstance(v, (list, tuple)) or len(v) < minimum:
        raise PcbRecordError("A %s needs at least %d points." % (label, minimum))
    if len(v) > MAX_POINTS:
        raise PcbRecordError("A %s holds at most %d points." % (label, MAX_POINTS))
    pts = [point(p, label) for p in v]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < minimum:
        raise PcbRecordError("A %s needs at least %d distinct points." % (label, minimum))
    return pts


def find(h: dict, kind: str, rid: str):
    for rec in h[kind]:
        if rec.get("id") == str(rid or "").upper():
            return rec
    return None


def need(h: dict, kind: str, rid: str) -> dict:
    rec = find(h, kind, rid)
    if rec is None:
        raise PcbRecordError("There is no %s %s." % (kind.rstrip("s"), rid))
    return rec


def part_of(h: dict, refdes: str):
    for p in h["parts"]:
        if p["refdes"] == refdes:
            return p
    return None


def limit(count: int, cap: int, what: str, runner_locked: bool = False) -> None:
    top = cap // MACRO_FACTOR if runner_locked else cap
    if count >= top:
        raise PcbRecordError("A board holds at most %d %s here." % (top, what))


def set_outline(d, body: dict) -> dict:
    h = header(d)
    b = h["board"]
    if body.get("outline") is not None:
        out = polygon(body["outline"], "outline")
        if self_intersects(out):
            raise PcbRecordError("The board outline crosses itself.")
        if abs(area(out)) < 1.0:
            raise PcbRecordError("The board outline has no area.")
        b["outline"] = out
    if body.get("rect") is not None:
        r = body["rect"]
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            raise PcbRecordError("rect is [x, y, width, height].")
        x, y, w, hh = [num(v, "rect", -5000, 5000) for v in r]
        if w <= 1.0 or hh <= 1.0:
            raise PcbRecordError("The board is larger than 1 mm each way.")
        rad = num(body.get("corner_radius", 0.0), "corner_radius", 0, min(w, hh) / 2)
        if rad > 0:
            pts = []
            for cx, cy, a0 in ((x + w - rad, y + rad, -90), (x + w - rad, y + hh - rad, 0), (x + rad, y + hh - rad, 90), (x + rad, y + rad, 180)):
                for i in range(7):
                    a = math.radians(a0 + 15 * i)
                    pts.append([round(cx + rad * math.cos(a), 5), round(cy + rad * math.sin(a), 5)])
            b["outline"] = pts
        else:
            b["outline"] = [[x, y], [x + w, y], [x + w, y + hh], [x, y + hh]]
    if body.get("cutouts") is not None:
        cuts = body["cutouts"]
        if not isinstance(cuts, list) or len(cuts) > 64:
            raise PcbRecordError("Cutouts is a list of at most 64 polygons.")
        b["cutouts"] = [polygon(c, "cutout") for c in cuts]
    if body.get("layers") is not None:
        n = int(body["layers"])
        if n not in (2, 4, 6, 8):
            raise PcbRecordError("Layers is 2, 4, 6 or 8.")
        if n != b["layers"]:
            b["layers"] = n
            b["stackup"] = default_stackup(n)
    if body.get("stackup") is not None:
        b["stackup"] = clean_stackup(body["stackup"], b["layers"])
    if body.get("finish") is not None:
        b["finish"] = str(body["finish"])[:40]
    save(d, h)
    return describe_board(h)


def clean_stackup(raw, n: int) -> list:
    if not isinstance(raw, list) or len(raw) > 40:
        raise PcbRecordError("Stackup is a list of at most 40 layers.")
    out = []
    coppers = 0
    for row in raw:
        if not isinstance(row, dict) or row.get("kind") not in ("copper", "core", "prepreg", "mask"):
            raise PcbRecordError("A stackup layer has a kind: copper, core, prepreg or mask.")
        item = {"kind": row["kind"], "name": str(row.get("name", row["kind"]))[:40], "thickness": num(row.get("thickness", 0.035), "thickness", 0.001, 10), "material": str(row.get("material", ""))[:60]}
        if row.get("epsilon_r") is not None:
            item["epsilon_r"] = num(row["epsilon_r"], "epsilon_r", 1, 100)
        if row["kind"] == "copper":
            coppers += 1
        out.append(item)
    if coppers != n:
        raise PcbRecordError("The stackup has %d copper layers but the board has %d." % (coppers, n))
    return out


def board_thickness(b: dict) -> float:
    return round(sum(r["thickness"] for r in b["stackup"] if r["kind"] != "mask"), 4)


def describe_board(h: dict) -> dict:
    b = h["board"]
    return {"outline": b["outline"], "cutouts": b["cutouts"], "layers": b["layers"], "copper": copper_layers(b["layers"]), "stackup": b["stackup"], "thickness": board_thickness(b), "finish": b.get("finish", "HASL")}


def set_rules(d, body: dict) -> dict:
    h = header(d)
    r = h["rules"]
    if body.get("profile") is not None:
        if body["profile"] not in R.PROFILES:
            raise PcbRecordError("Unknown rule profile %s." % body["profile"])
        r["profile"] = body["profile"]
        if body.get("overrides") is None:
            r["overrides"] = {}
    if body.get("overrides") is not None:
        r["overrides"] = R.clean_overrides(body["overrides"])
    if body.get("classes") is not None:
        r["classes"] = R.clean_classes(body["classes"])
    r["values"] = R.effective(r)
    save(d, h)
    return r


def clean_pad(p: dict, i: int) -> dict:
    shape = p.get("shape", "rect")
    if shape not in SHAPES:
        raise PcbRecordError("Pad shape is one of: %s." % ", ".join(SHAPES))
    w = num(p.get("w", p.get("size", 1.0)), "pad width", 0.01, 100)
    hh = num(p.get("h", w), "pad height", 0.01, 100)
    drill = num(p.get("drill", 0.0) or 0.0, "pad drill", 0, 50)
    layers = p.get("layers")
    if layers is None:
        layers = ["F.Cu", "B.Cu"] if drill > 0 else ["F.Cu"]
    poly = None
    if shape == "poly":
        poly = polygon(p.get("poly"), "pad polygon")
        xs = [q[0] for q in poly]
        ys = [q[1] for q in poly]
        w, hh = round(max(xs) - min(xs), 6) or 0.01, round(max(ys) - min(ys), 6) or 0.01
    return {
        "poly": poly,
        "roundrect_ratio": num(p.get("roundrect_ratio", 0.25) or 0.25, "roundrect ratio", 0, 0.5),
        "mask_margin": None if p.get("mask_margin") is None else num(p["mask_margin"], "mask margin", -5, 5),
        "paste_margin": None if p.get("paste_margin") is None else num(p["paste_margin"], "paste margin", -5, 5),
        "layers_all": [str(x) for x in (p.get("layers_all") or layers)][:16],
        "number": str(p.get("number", i + 1))[:16],
        "shape": shape,
        "x": num(p.get("x", 0.0), "pad x", -1000, 1000),
        "y": num(p.get("y", 0.0), "pad y", -1000, 1000),
        "w": w,
        "h": hh,
        "rot": num(p.get("rot", 0.0), "pad rotation", -720, 720),
        "drill": drill,
        "slot": [num(p["slot"][0], "slot", 0, 50), num(p["slot"][1], "slot", 0, 50)] if isinstance(p.get("slot"), (list, tuple)) and len(p["slot"]) == 2 else None,
        "plated": bool(p.get("plated", True)),
        "layers": [str(x) for x in layers][:8],
        "zone_connect": p.get("zone_connect") if p.get("zone_connect") in CONNECT else None,
        "net": str(p.get("net", ""))[:80],
    }


def clean_part(body: dict, existing=None) -> dict:
    refdes = str(body.get("refdes", "")).strip()[:32]
    if not refdes:
        raise PcbRecordError("A placed footprint needs a reference designator.")
    pads_raw = body.get("pads")
    if pads_raw is None and existing is not None:
        pads = existing["pads"]
    else:
        if not isinstance(pads_raw, list) or not pads_raw:
            raise PcbRecordError("A footprint needs a pads list.")
        pads = [clean_pad(p, i) for i, p in enumerate(pads_raw)]
    court = body.get("courtyard", existing.get("courtyard") if existing else None)
    if court is not None:
        court = polygon(court, "courtyard")
    side = body.get("side", existing.get("side") if existing else "top")
    if side not in ("top", "bottom"):
        raise PcbRecordError("Side is top or bottom.")
    base = existing or {}
    return {
        "refdes": refdes,
        "uuid": str(body.get("uuid", base.get("uuid", "")))[:64],
        "footprint": str(body.get("footprint", base.get("footprint", "")))[:120],
        "value": str(body.get("value", base.get("value", "")))[:120],
        "x": num(body.get("x", base.get("x", 0.0)), "x", -5000, 5000),
        "y": num(body.get("y", base.get("y", 0.0)), "y", -5000, 5000),
        "rot": num(body.get("rot", base.get("rot", 0.0)), "rotation", -720, 720),
        "side": side,
        "locked": bool(body.get("locked", base.get("locked", False))),
        "pads": pads,
        "courtyard": court,
        "body": body.get("body", base.get("body")) if isinstance(body.get("body", base.get("body")), dict) else None,
        "silk": body.get("silk", base.get("silk")) if isinstance(body.get("silk", base.get("silk")), list) else [],
    }


def place_part(d, body: dict, locked: bool = False) -> dict:
    h = header(d)
    part = clean_part(body)
    if part_of(h, part["refdes"]) is not None:
        raise PcbRecordError("%s is already placed; move it or remove it first." % part["refdes"])
    limit(len(h["parts"]), MAX_PARTS, "footprints", locked)
    total = sum(len(p["pads"]) for p in h["parts"]) + len(part["pads"])
    if total > (MAX_PADS // MACRO_FACTOR if locked else MAX_PADS):
        raise PcbRecordError("A board holds at most %d pads here." % (MAX_PADS // MACRO_FACTOR if locked else MAX_PADS))
    assign_nets(h, [part])
    h["parts"].append(part)
    save(d, h)
    return part


def edit_part(d, refdes: str, body: dict) -> dict:
    h = header(d)
    old = part_of(h, refdes)
    if old is None:
        raise PcbRecordError("%s is not placed." % refdes)
    if old.get("locked") and set(body) - {"locked"}:
        raise PcbRecordError("%s is locked; unlock it first." % refdes)
    new = clean_part(dict(body, refdes=refdes), old)
    assign_nets(h, [new])
    h["parts"][h["parts"].index(old)] = new
    save(d, h)
    return new


def remove_part(d, refdes: str) -> dict:
    h = header(d)
    old = part_of(h, refdes)
    if old is None:
        raise PcbRecordError("%s is not placed." % refdes)
    h["parts"].remove(old)
    save(d, h)
    return old


def assign_nets(h: dict, parts: list) -> None:
    pinnet = pin_nets(h["netlist"])
    if not pinnet:
        return
    for part in parts:
        for pad in part["pads"]:
            net = pinnet.get((part["refdes"], pad["number"]))
            if net is not None:
                pad["net"] = net


def pin_nets(netlist: dict) -> dict:
    out = {}
    for net in netlist.get("nets", []):
        for ref, pin in net.get("pins", []):
            out[(ref, str(pin))] = net["name"]
    return out


def set_netlist(d, netlist: dict) -> dict:
    h = header(d)
    nets = []
    seen = set()
    if not isinstance(netlist.get("nets"), list):
        raise PcbRecordError("A netlist has a nets list.")
    if len(netlist["nets"]) > MAX_NETS:
        raise PcbRecordError("A board holds at most %d nets." % MAX_NETS)
    for n in netlist["nets"]:
        name = str(n.get("name", "")).strip()[:80]
        if not name or name in seen:
            raise PcbRecordError("Every net needs a unique name.")
        seen.add(name)
        pins = []
        for pr in n.get("pins", []):
            if isinstance(pr, dict):
                pr = [pr.get("ref", pr.get("refdes")), pr.get("pin", pr.get("number"))]
            if not isinstance(pr, (list, tuple)) or len(pr) != 2:
                raise PcbRecordError("A net pin is [refdes, pin number].")
            pins.append([str(pr[0])[:32], str(pr[1])[:16]])
        nets.append({"name": name, "pins": pins})
    parts = []
    for p in netlist.get("parts", []):
        parts.append({"refdes": str(p.get("refdes", ""))[:32], "uuid": str(p.get("uuid", ""))[:64], "footprint": str(p.get("footprint", ""))[:120], "value": str(p.get("value", ""))[:120]})
    h["netlist"] = {"nets": nets, "parts": parts}
    for part in h["parts"]:
        for pad in part["pads"]:
            pad["net"] = ""
    assign_nets(h, h["parts"])
    save(d, h)
    return h["netlist"]


def clean_track(h: dict, body: dict, locked: bool = False) -> dict:
    layers = copper_layers(h["board"]["layers"])
    layer = body.get("layer", "F.Cu")
    if layer not in layers:
        raise PcbRecordError("Layer is one of: %s." % ", ".join(layers))
    eff = R.effective(h["rules"])
    width = num(body.get("width", eff["track_width"]), "width", 0.02, 20)
    return {"net": str(body.get("net", ""))[:80], "layer": layer, "width": width, "a": point(body.get("a"), "track start"), "b": point(body.get("b"), "track end")}


def add_track(d, body: dict, locked: bool = False) -> dict:
    h = header(d)
    limit(len(h["tracks"]), MAX_TRACKS, "track segments", locked)
    rec = clean_track(h, body)
    if rec["a"] == rec["b"]:
        raise PcbRecordError("A track has length.")
    rec["id"] = mint(h, "T")
    h["tracks"].append(rec)
    save(d, h)
    return rec


def add_polyline(d, body: dict, locked: bool = False) -> list:
    h = header(d)
    pts = body.get("points")
    if not isinstance(pts, list) or len(pts) < 2 or len(pts) > 1000:
        raise PcbRecordError("points is a list of 2 to 1000 [x, y] points.")
    out = []
    for i in range(len(pts) - 1):
        limit(len(h["tracks"]), MAX_TRACKS, "track segments", locked)
        rec = clean_track(h, dict(body, a=pts[i], b=pts[i + 1]))
        if rec["a"] == rec["b"]:
            continue
        rec["id"] = mint(h, "T")
        h["tracks"].append(rec)
        out.append(rec)
    save(d, h)
    return out


def edit_track(d, tid: str, body: dict) -> dict:
    h = header(d)
    rec = need(h, "tracks", tid)
    merged = dict(rec)
    merged.update({k: v for k, v in body.items() if v is not None})
    new = clean_track(h, merged)
    new["id"] = rec["id"]
    h["tracks"][h["tracks"].index(rec)] = new
    save(d, h)
    return new


def clean_via(h: dict, body: dict) -> dict:
    eff = R.effective(h["rules"])
    layers = copper_layers(h["board"]["layers"])
    a = body.get("from", layers[0])
    b = body.get("to", layers[-1])
    if a not in layers or b not in layers:
        raise PcbRecordError("A via spans copper layers: %s." % ", ".join(layers))
    dia = num(body.get("dia", eff["via_dia"]), "via diameter", 0.1, 20)
    drill = num(body.get("drill", eff["via_drill"]), "via drill", 0.05, 20)
    if drill >= dia:
        raise PcbRecordError("The via drill is smaller than its pad.")
    return {"net": str(body.get("net", ""))[:80], "x": num(body.get("x"), "via x", -5000, 5000), "y": num(body.get("y"), "via y", -5000, 5000), "dia": dia, "drill": drill, "from": a, "to": b}


def add_via(d, body: dict, locked: bool = False) -> dict:
    h = header(d)
    limit(len(h["vias"]), MAX_VIAS, "vias", locked)
    rec = clean_via(h, body)
    rec["id"] = mint(h, "V")
    h["vias"].append(rec)
    save(d, h)
    return rec


def edit_via(d, vid: str, body: dict) -> dict:
    h = header(d)
    rec = need(h, "vias", vid)
    merged = dict(rec)
    merged.update({k: v for k, v in body.items() if v is not None})
    new = clean_via(h, merged)
    new["id"] = rec["id"]
    h["vias"][h["vias"].index(rec)] = new
    save(d, h)
    return new


def clean_zone(h: dict, body: dict, base=None) -> dict:
    base = base or {}
    layers = copper_layers(h["board"]["layers"])
    eff = R.effective(h["rules"])
    layer = body.get("layer", base.get("layer", "B.Cu"))
    if layer not in layers:
        raise PcbRecordError("Layer is one of: %s." % ", ".join(layers))
    poly = polygon(body.get("polygon", base.get("polygon")), "zone outline")
    connect = body.get("connect", base.get("connect", "thermal"))
    if connect not in CONNECT:
        raise PcbRecordError("Pad connection is one of: %s." % ", ".join(CONNECT))
    return {
        "net": str(body.get("net", base.get("net", "")))[:80],
        "layer": layer,
        "polygon": poly,
        "clearance": num(body.get("clearance", base.get("clearance", eff["clearance"])), "zone clearance", 0, 5),
        "min_width": num(body.get("min_width", base.get("min_width", eff["track_width"])), "zone minimum width", 0.02, 5),
        "connect": connect,
        "gap": num(body.get("gap", base.get("gap", 0.3)), "thermal gap", 0.02, 3),
        "spoke": num(body.get("spoke", base.get("spoke", 0.3)), "spoke width", 0.02, 3),
        "spokes": int(num(body.get("spokes", base.get("spokes", 4)), "spoke count", 2, 8)),
        "min_island": num(body.get("min_island", base.get("min_island", 0.5)), "minimum island area", 0, 1000),
        "priority": int(num(body.get("priority", base.get("priority", 0)), "priority", 0, 100)),
    }


def add_zone(d, body: dict, locked: bool = False) -> dict:
    h = header(d)
    limit(len(h["zones"]), MAX_ZONES, "zones", locked)
    rec = clean_zone(h, body)
    rec["id"] = mint(h, "Z")
    h["zones"].append(rec)
    save(d, h)
    return rec


def edit_zone(d, zid: str, body: dict) -> dict:
    h = header(d)
    rec = need(h, "zones", zid)
    new = clean_zone(h, body, rec)
    new["id"] = rec["id"]
    h["zones"][h["zones"].index(rec)] = new
    save(d, h)
    return new


def clean_keepout(h: dict, body: dict, base=None) -> dict:
    base = base or {}
    layers = copper_layers(h["board"]["layers"])
    ls = body.get("layers", base.get("layers", layers))
    if not isinstance(ls, list) or any(x not in layers for x in ls):
        raise PcbRecordError("Keepout layers are copper layers: %s." % ", ".join(layers))
    return {
        "polygon": polygon(body.get("polygon", base.get("polygon")), "keepout"),
        "layers": ls,
        "tracks": bool(body.get("tracks", base.get("tracks", True))),
        "vias": bool(body.get("vias", base.get("vias", True))),
        "pours": bool(body.get("pours", base.get("pours", True))),
        "footprints": bool(body.get("footprints", base.get("footprints", False))),
        "name": str(body.get("name", base.get("name", "")))[:60],
    }


def add_keepout(d, body: dict, locked: bool = False) -> dict:
    h = header(d)
    limit(len(h["keepouts"]), MAX_KEEPOUTS, "keepouts", locked)
    rec = clean_keepout(h, body)
    rec["id"] = mint(h, "K")
    h["keepouts"].append(rec)
    save(d, h)
    return rec


def edit_keepout(d, kid: str, body: dict) -> dict:
    h = header(d)
    rec = need(h, "keepouts", kid)
    new = clean_keepout(h, body, rec)
    new["id"] = rec["id"]
    h["keepouts"][h["keepouts"].index(rec)] = new
    save(d, h)
    return new


def add_hole(d, body: dict, locked: bool = False) -> dict:
    h = header(d)
    limit(len(h["holes"]), MAX_HOLES, "mounting holes", locked)
    drill = num(body.get("drill", 3.2), "hole drill", 0.1, 50)
    rec = {"id": mint(h, "H"), "x": num(body.get("x"), "hole x", -5000, 5000), "y": num(body.get("y"), "hole y", -5000, 5000), "drill": drill, "plated": bool(body.get("plated", False)), "dia": num(body.get("dia", drill + 1.0 if body.get("plated") else drill), "hole pad diameter", drill, 100)}
    h["holes"].append(rec)
    save(d, h)
    return rec


def remove_record(d, kind: str, rid: str) -> dict:
    h = header(d)
    rec = need(h, kind, rid)
    h[kind].remove(rec)
    save(d, h)
    return rec


def remove_net_copper(d, net: str, tracks=True, vias=True) -> dict:
    h = header(d)
    t0, v0 = len(h["tracks"]), len(h["vias"])
    if tracks:
        h["tracks"] = [t for t in h["tracks"] if t["net"] != net]
    if vias:
        h["vias"] = [v for v in h["vias"] if v["net"] != net]
    save(d, h)
    return {"tracks": t0 - len(h["tracks"]), "vias": v0 - len(h["vias"])}


def set_last(d, key: str, value) -> None:
    h = header(d)
    h["last"][key] = value
    save(d, h)
