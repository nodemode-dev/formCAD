import re

from app.ecad import library
from app.ecad.store import ITEM_KINDS, MAX_ITEMS, MAX_PARTS, MAX_SHEETS, EcadError, count_items, natural, need_part, need_sheet, next_id, pt

ORIENT = {"U": (0, 1), "D": (0, -1), "L": (-1, 0), "R": (1, 0)}
LABEL_KINDS = ("local", "global", "hier")
SHEET_SYMBOL_LIMIT = 200
MAX_WIRE_POINTS = 500


def xform(p, placement) -> list:
    x, y = p
    if placement.get("mirror"):
        x = -x
    r = int(placement.get("rotation", 0)) % 360
    c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[r]
    X, Y = x * c - y * s, x * s + y * c
    return [round(X + placement["pos"][0], 4), round(Y + placement["pos"][1], 4)]


def rot_orient(o: str, placement) -> str:
    dx, dy = ORIENT[o]
    if placement.get("mirror"):
        dx = -dx
    r = int(placement.get("rotation", 0)) % 360
    for _ in range(r // 90):
        dx, dy = -dy, dx
    return {(0, 1): "U", (0, -1): "D", (-1, 0): "L", (1, 0): "R"}[(dx, dy)]


def pins_of(h: dict, part: dict, placement: dict, sym: dict | None = None) -> list:
    sym = sym or library.sym_in(h, part["symbol"])
    if sym is None:
        return []
    out = []
    for p in sym["pins"]:
        if p["unit"] not in (0, placement.get("unit", 1)):
            continue
        out.append({**p, "abs": xform(p["pos"], placement), "abs_orient": rot_orient(p["orient"], placement)})
    return out


def find_pin(h: dict, ref: str, sheet: str | None = None):
    m = re.fullmatch(r"\s*(.+?)\.([^.\s]+)\s*", str(ref))
    if not m:
        raise EcadError("A pin is written REFDES.PIN, for example R1.2.")
    part = need_part(h, m.group(1))
    for pl in part["placements"]:
        if sheet and pl["sheet"] != sheet:
            continue
        for p in pins_of(h, part, pl):
            if p["number"] == m.group(2):
                return part, pl, p
    raise EcadError("%s has no pin %s%s." % (part["refdes"], m.group(2), " on sheet " + sheet if sheet else ""))


def _check_budget(h):
    if count_items(h) >= MAX_ITEMS:
        raise EcadError("The design has reached the limit of %d drawn items." % MAX_ITEMS)


def next_refdes(h: dict, prefix: str) -> str:
    used = {p["refdes"] for p in h["parts"].values()}
    n = 1
    while "%s%d" % (prefix, n) in used:
        n += 1
    return "%s%d" % (prefix, n)


def add_part(h: dict, op: dict) -> dict:
    if len(h["parts"]) >= MAX_PARTS:
        raise EcadError("The design has reached the limit of %d parts." % MAX_PARTS)
    sym = library.sym_in(h, str(op.get("symbol", "")))
    if sym is None:
        raise EcadError("There is no symbol %s." % op.get("symbol"))
    sheet = op.get("sheet") or h["root"]
    need_sheet(h, sheet)
    pid = "P%d" % h["next"]["part"]
    h["next"]["part"] += 1
    prefix = sym["prefix"] or "U"
    ref = str(op.get("refdes") or "").strip()
    if not ref:
        ref = ("#PWR%d" % int(pid[1:])) if sym["power"] else next_refdes(h, prefix)
    if any(p["refdes"] == ref for p in h["parts"].values()) and not op.get("allow_duplicate"):
        raise EcadError("The reference %s is already used." % ref)
    value = op.get("value")
    if value is None:
        value = sym.get("default_value", "")
    rot = int(op.get("rotation", 0)) % 360
    if rot % 90:
        raise EcadError("Schematic rotation is a multiple of 90 degrees.")
    pl = {"unit": int(op.get("unit", 1)), "sheet": sheet, "pos": pt(op.get("pos", [0, 0])), "rotation": rot, "mirror": bool(op.get("mirror", False))}
    part = {
        "id": pid, "refdes": ref, "symbol": sym["id"], "value": str(value), "footprint": str(op.get("footprint", sym["default_footprint"] if not sym["power"] else "")),
        "fields": {str(k): str(v) for k, v in (op.get("fields") or {}).items()}, "dnp": bool(op.get("dnp", False)), "exclude_bom": bool(op.get("exclude_bom", sym["power"])),
        "exclude_netlist": bool(op.get("exclude_netlist", False)), "placements": [pl], "instances": {}, "note": str(op.get("note", "")),
    }
    h["parts"][pid] = part
    return part


def place_unit(h: dict, op: dict) -> dict:
    part = need_part(h, op.get("part"))
    sym = library.sym_in(h, part["symbol"])
    unit = int(op.get("unit", 1))
    if unit < 1 or unit > sym["units"]:
        raise EcadError("%s has units 1 to %d." % (part["refdes"], sym["units"]))
    if any(p["unit"] == unit for p in part["placements"]):
        raise EcadError("Unit %d of %s is already placed." % (unit, part["refdes"]))
    sheet = op.get("sheet") or h["root"]
    need_sheet(h, sheet)
    part["placements"].append({"unit": unit, "sheet": sheet, "pos": pt(op.get("pos", [0, 0])), "rotation": int(op.get("rotation", 0)) % 360, "mirror": bool(op.get("mirror", False))})
    return part


def set_part(h: dict, op: dict) -> dict:
    part = need_part(h, op.get("part"))
    for k in ("value", "footprint", "note"):
        if k in op:
            part[k] = str(op[k])
    if "refdes" in op:
        ref = str(op["refdes"]).strip()
        if not ref:
            raise EcadError("A reference cannot be empty.")
        if any(p["refdes"] == ref and p["id"] != part["id"] for p in h["parts"].values()):
            raise EcadError("The reference %s is already used." % ref)
        part["refdes"] = ref
    for k in ("dnp", "exclude_bom", "exclude_netlist"):
        if k in op:
            part[k] = bool(op[k])
    if "fields" in op:
        for k, v in op["fields"].items():
            if v is None:
                part["fields"].pop(str(k), None)
            else:
                part["fields"][str(k)] = str(v)
    if "symbol" in op:
        if library.sym_in(h, str(op["symbol"])) is None:
            raise EcadError("There is no symbol %s." % op["symbol"])
        part["symbol"] = str(op["symbol"])
    if "instance" in op:
        for path, ref in op["instance"].items():
            part["instances"][str(path)] = str(ref)
    return part


def move_part(h: dict, op: dict) -> dict:
    part = need_part(h, op.get("part"))
    pls = [p for p in part["placements"] if int(op.get("unit", p["unit"])) == p["unit"]]
    if not pls:
        raise EcadError("%s has no such unit placed." % part["refdes"])
    pl = pls[0]
    if "pos" in op:
        pl["pos"] = pt(op["pos"])
    if "delta" in op:
        d = pt(op["delta"])
        pl["pos"] = [round(pl["pos"][0] + d[0], 4), round(pl["pos"][1] + d[1], 4)]
    if "rotation" in op:
        r = int(op["rotation"]) % 360
        if r % 90:
            raise EcadError("Schematic rotation is a multiple of 90 degrees.")
        pl["rotation"] = r
    if "mirror" in op:
        pl["mirror"] = bool(op["mirror"])
    return part


def delete_part(h: dict, op: dict) -> dict:
    part = need_part(h, op.get("part"))
    del h["parts"][part["id"]]
    return {"deleted": part["id"]}


def _points(op, minimum=2):
    pts = [pt(p) for p in op.get("points", [])]
    if len(pts) < minimum or len(pts) > MAX_WIRE_POINTS:
        raise EcadError("A wire or bus has 2 to %d points." % MAX_WIRE_POINTS)
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    if len(out) < 2:
        raise EcadError("A wire needs two different points.")
    return out


def add_wire(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    w = {"id": next_id(h, "wire"), "points": _points(op)}
    sh["wires"].append(w)
    return w


def add_bus(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    b = {"id": next_id(h, "bus"), "points": _points(op)}
    sh["buses"].append(b)
    return b


def add_junction(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    j = {"id": next_id(h, "junction"), "pos": pt(op.get("pos"))}
    sh["junctions"].append(j)
    return j


def add_no_connect(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    if op.get("pin"):
        _p, _pl, p = find_pin(h, op["pin"], op.get("sheet"))
        pos = p["abs"]
    else:
        pos = pt(op.get("pos"))
    x = {"id": next_id(h, "no_connect"), "pos": pos}
    sh["no_connects"].append(x)
    return x


def add_label(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    kind = op.get("kind", "local")
    if kind not in LABEL_KINDS:
        raise EcadError("A label is local, global or hier.")
    text = str(op.get("text", "")).strip()
    if not text or len(text) > 64 or re.search(r"[\s\"]", text):
        raise EcadError("A label is 1 to 64 characters without spaces or quotes.")
    if op.get("pin"):
        _p, _pl, p = find_pin(h, op["pin"], op.get("sheet"))
        pos = p["abs"]
    else:
        pos = pt(op.get("pos"))
    etype = op.get("etype", "bidirectional")
    lb = {"id": next_id(h, "label"), "kind": kind, "text": text, "pos": pos, "rotation": int(op.get("rotation", 0)) % 360, "etype": etype}
    sh["labels"].append(lb)
    return lb


def add_bus_entry(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    d = op.get("dir", [2.54, -2.54])
    e = {"id": next_id(h, "bus_entry"), "pos": pt(op.get("pos")), "dir": pt(d)}
    sh["bus_entries"].append(e)
    return e


def add_text(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    _check_budget(h)
    t = {"id": next_id(h, "text"), "text": str(op.get("text", ""))[:1000], "pos": pt(op.get("pos", [0, 0])), "h": float(op.get("h", 1.27))}
    sh["texts"].append(t)
    return t


def _reaches(h, start, goal, seen=None):
    seen = seen or set()
    if start == goal:
        return True
    if start in seen:
        return False
    seen.add(start)
    for hs in h["sheets"][start]["sheet_symbols"]:
        if _reaches(h, hs["child"], goal, seen):
            return True
    return False


def child_labels(h: dict, child: str) -> list:
    return sorted({(l["text"], l.get("etype", "bidirectional")) for l in h["sheets"][child]["labels"] if l["kind"] == "hier"})


def layout_sheet_pins(pins: list, pos, size) -> list:
    left = [p for p in pins if p.get("side", "L") == "L"]
    right = [p for p in pins if p.get("side") == "R"]
    out = []
    for group, x in ((left, pos[0]), (right, pos[0] + size[0])):
        for i, p in enumerate(group):
            out.append({"name": p["name"], "etype": p.get("etype", "bidirectional"), "side": p.get("side", "L"), "pos": [round(x, 4), round(pos[1] - 2.54 * (i + 1), 4)]})
    return out


def add_sheet_symbol(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet") or h["root"])
    child = str(op.get("child") or "")
    need_sheet(h, child)
    if _reaches(h, child, sh["id"]):
        raise EcadError("That sheet contains this one, so placing it here would loop.")
    if len(sh["sheet_symbols"]) >= SHEET_SYMBOL_LIMIT:
        raise EcadError("Too many sheet symbols on one sheet.")
    pos = pt(op.get("pos", [0, 0]))
    pins = op.get("pins")
    if pins is None:
        labels = child_labels(h, child)
        pins = [{"name": t, "etype": e, "side": "L" if i % 2 == 0 else "R"} for i, (t, e) in enumerate(labels)]
    rows = max(1, (len(pins) + 1) // 2)
    size = pt(op.get("size", [25.4, 2.54 * (rows + 1)]))
    hs = {"id": next_id(h, "sheet_symbol"), "name": str(op.get("name") or h["sheets"][child]["name"]), "child": child, "pos": pos, "size": size, "pins": layout_sheet_pins(pins, pos, size)}
    sh["sheet_symbols"].append(hs)
    return hs


def sync_sheet_pins(h: dict, op: dict) -> dict:
    for sh in h["sheets"].values():
        for hs in sh["sheet_symbols"]:
            if hs["id"] == op.get("symbol"):
                labels = child_labels(h, hs["child"])
                old = {p["name"]: p for p in hs["pins"]}
                pins = [{"name": t, "etype": e, "side": old[t]["side"] if t in old else ("L" if i % 2 == 0 else "R")} for i, (t, e) in enumerate(labels)]
                hs["pins"] = layout_sheet_pins(pins, hs["pos"], hs["size"])
                return hs
    raise EcadError("There is no sheet symbol %s." % op.get("symbol"))


def add_sheet(h: dict, op: dict) -> dict:
    if len(h["sheets"]) >= MAX_SHEETS:
        raise EcadError("A design has at most %d sheets." % MAX_SHEETS)
    sid = "S%d" % h["next"]["sheet"]
    h["next"]["sheet"] += 1
    from app.ecad.store import new_sheet

    name = str(op.get("name") or sid)[:80]
    sh = new_sheet(sid, name)
    sh["title"] = str(op.get("title") or name)[:120]
    sh["paper"] = str(op.get("paper") or "A4")
    h["sheets"][sid] = sh
    return {"id": sid, "name": name}


def set_sheet(h: dict, op: dict) -> dict:
    sh = need_sheet(h, op.get("sheet"))
    for k in ("name", "title", "paper"):
        if k in op:
            sh[k] = str(op[k])[:120]
    return {"id": sh["id"], "name": sh["name"]}


def delete_sheet(h: dict, op: dict) -> dict:
    sid = op.get("sheet")
    sh = need_sheet(h, sid)
    if sid == h["root"]:
        raise EcadError("The root sheet cannot be deleted.")
    for o in h["sheets"].values():
        if any(hs["child"] == sid for hs in o["sheet_symbols"]):
            raise EcadError("Sheet %s is used by a sheet symbol; remove the symbol first." % sh["name"])
    for p in list(h["parts"].values()):
        p["placements"] = [pl for pl in p["placements"] if pl["sheet"] != sid]
        if not p["placements"]:
            del h["parts"][p["id"]]
    del h["sheets"][sid]
    return {"deleted": sid}


def delete_item(h: dict, op: dict) -> dict:
    iid = str(op.get("item", ""))
    code = iid[:1]
    key = {v: k for k, v in ITEM_KINDS.items()}.get(code)
    if not key:
        raise EcadError("There is no item %s." % iid)
    field = {"wire": "wires", "bus": "buses", "junction": "junctions", "no_connect": "no_connects", "label": "labels", "bus_entry": "bus_entries", "sheet_symbol": "sheet_symbols", "text": "texts"}[key]
    for sh in h["sheets"].values():
        for i, it in enumerate(sh[field]):
            if it["id"] == iid:
                del sh[field][i]
                return {"deleted": iid}
    raise EcadError("There is no item %s." % iid)


def move_item(h: dict, op: dict) -> dict:
    iid = str(op.get("item", ""))
    d = pt(op.get("delta", [0, 0]))
    for sh in h["sheets"].values():
        for field in ("wires", "buses", "junctions", "no_connects", "labels", "bus_entries", "sheet_symbols", "texts"):
            for it in sh[field]:
                if it["id"] == iid:
                    for key in ("points",):
                        if key in it:
                            it[key] = [[round(p[0] + d[0], 4), round(p[1] + d[1], 4)] for p in it[key]]
                    if "pos" in it:
                        it["pos"] = [round(it["pos"][0] + d[0], 4), round(it["pos"][1] + d[1], 4)]
                    for p in it.get("pins", []):
                        p["pos"] = [round(p["pos"][0] + d[0], 4), round(p["pos"][1] + d[1], 4)]
                    return it
    raise EcadError("There is no item %s." % iid)


def connect(h: dict, op: dict) -> dict:
    sheet = op.get("sheet")
    pa, pla, a = find_pin(h, op["a"], sheet)
    pb, plb, b = find_pin(h, op["b"], sheet)
    if pla["sheet"] != plb["sheet"]:
        raise EcadError("Both pins must be on the same sheet.")
    sid = pla["sheet"]
    start, end = a["abs"], b["abs"]
    pts = [start]
    via = [pt(p) for p in op.get("via", [])]
    for p in via:
        pts.append(p)
    last = pts[-1]
    if last[0] != end[0] and last[1] != end[1]:
        if a["abs_orient"] in ("L", "R") and not via:
            pts.append([end[0], last[1]])
        else:
            pts.append([last[0], end[1]])
    pts.append(end)
    return add_wire(h, {"sheet": sid, "points": pts})


def power_at(h: dict, op: dict) -> dict:
    _p, pl, p = find_pin(h, op["pin"], op.get("sheet"))
    name = str(op["net"])
    sid = "PWR:" + name if library.sym_in(h, "PWR_" + name) is None else "PWR_" + name
    return add_part(h, {"symbol": sid, "sheet": pl["sheet"], "pos": p["abs"], "value": name, "rotation": op.get("rotation", 0)})


def annotate(h: dict, op: dict) -> dict:
    only_unset = not op.get("all", False)
    changed = []
    parts = sorted(h["parts"].values(), key=lambda p: (list(h["sheets"]).index(p["placements"][0]["sheet"]), -p["placements"][0]["pos"][1], p["placements"][0]["pos"][0]))
    used = {p["refdes"] for p in parts if not (p["refdes"].endswith("?") or not p["refdes"]) or not only_unset}
    if not only_unset:
        used = set()
    counters = {}
    for p in parts:
        sym = library.sym_in(h, p["symbol"])
        if sym is None or sym["power"]:
            continue
        unset = p["refdes"].endswith("?") or not p["refdes"]
        if only_unset and not unset:
            continue
        prefix = (sym["prefix"] or "U").rstrip("?")
        n = counters.get(prefix, 0) + 1
        while "%s%d" % (prefix, n) in used:
            n += 1
        counters[prefix] = n
        new = "%s%d" % (prefix, n)
        used.add(new)
        if p["refdes"] != new:
            changed.append({"part": p["id"], "from": p["refdes"], "to": new})
            p["refdes"] = new
    return {"changed": changed}


def set_erc(h: dict, op: dict) -> dict:
    from app.ecad.store import ERC_RULES, SEVERITIES

    for rule, sev in (op.get("rules") or {}).items():
        if rule not in ERC_RULES or sev not in SEVERITIES:
            raise EcadError("ERC rules are %s with severity error, warning or ignore." % ", ".join(ERC_RULES))
        h["settings"]["erc"][rule] = sev
    return {"erc": dict(h["settings"]["erc"])}


def set_design(h: dict, op: dict) -> dict:
    if "name" in op:
        h["name"] = str(op["name"])[:120]
    return {"name": h["name"]}


OPS = {
    "add_part": add_part, "place_unit": place_unit, "set_part": set_part, "move_part": move_part, "delete_part": delete_part, "add_wire": add_wire, "add_bus": add_bus,
    "add_junction": add_junction, "add_no_connect": add_no_connect, "add_label": add_label, "add_bus_entry": add_bus_entry, "add_text": add_text,
    "add_sheet_symbol": add_sheet_symbol, "sync_sheet_pins": sync_sheet_pins, "add_sheet": add_sheet, "set_sheet": set_sheet, "delete_sheet": delete_sheet,
    "delete_item": delete_item, "move_item": move_item, "connect": connect, "power_at": power_at, "annotate": annotate, "set_erc": set_erc, "set_design": set_design,
}


def apply(h: dict, op: dict) -> dict:
    name = op.get("op")
    fn = OPS.get(name)
    if fn is None:
        raise EcadError("Unknown operation %s. Use one of: %s." % (name, ", ".join(sorted(OPS))))
    return fn(h, op)


def scene(h: dict, sid: str) -> dict:
    sh = need_sheet(h, sid)
    comps = []
    for part in sorted(h["parts"].values(), key=lambda p: natural(p["refdes"])):
        for pl in part["placements"]:
            if pl["sheet"] != sid:
                continue
            sym = library.sym_in(h, part["symbol"])
            if sym is None:
                comps.append({"part": part["id"], "refdes": part["refdes"], "symbol": part["symbol"], "missing": True, "placement": pl})
                continue
            gfx = []
            for g in sym["graphics"]:
                if g.get("unit", 0) not in (0, pl["unit"]):
                    continue
                if g["t"] == "rect":
                    pts = [[g["x0"], g["y0"]], [g["x1"], g["y0"]], [g["x1"], g["y1"]], [g["x0"], g["y1"]], [g["x0"], g["y0"]]]
                    gfx.append({"t": "line", "pts": [xform(p, pl) for p in pts]})
                elif g["t"] == "line":
                    gfx.append({"t": "line", "pts": [xform(p, pl) for p in g["pts"]]})
                elif g["t"] == "circle":
                    gfx.append({"t": "circle", "c": xform(g["c"], pl), "r": g["r"]})
                else:
                    gfx.append({"t": "text", "text": g["text"], "pos": xform(g["pos"], pl), "h": g.get("h", 1.27)})
            pins = [{"number": p["number"], "name": p["name"], "etype": p["etype"], "pos": p["abs"], "orient": p["abs_orient"], "length": p["length"], "hidden": p["hidden"]} for p in pins_of(h, part, pl, sym)]
            comps.append({"part": part["id"], "refdes": part["refdes"], "value": part["value"], "symbol": part["symbol"], "power": sym["power"], "unit": pl["unit"], "placement": pl, "graphics": gfx, "pins": pins})
    return {"sheet": {k: sh[k] for k in ("id", "name", "title", "paper")}, "components": comps, "wires": sh["wires"], "buses": sh["buses"], "junctions": sh["junctions"], "no_connects": sh["no_connects"], "labels": sh["labels"], "bus_entries": sh["bus_entries"], "sheet_symbols": sh["sheet_symbols"], "texts": sh["texts"]}


def expand_bus(text: str):
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*?)\[(\d+)\.\.(\d+)\]", text)
    if not m:
        return None
    a, b = int(m.group(2)), int(m.group(3))
    if abs(a - b) > 255:
        raise EcadError("A bus has at most 256 members.")
    rng = range(a, b + 1) if a <= b else range(a, b - 1, -1)
    return ["%s%d" % (m.group(1), i) for i in rng]
