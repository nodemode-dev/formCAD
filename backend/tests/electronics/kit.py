import math
from pathlib import Path

from tests.electronics.drill_reader import Drill
from tests.electronics.gerber_reader import Gerber


def schematic(doc, *ops):
    doc.post("/ecad/init")
    if ops:
        return doc.post("/ecad/batch", {"ops": list(ops)})["result"]
    return []


def part(symbol, x, y, **extra):
    return {"op": "add_part", "symbol": symbol, "pos": [x, y], **extra}


def wire(a, b):
    return {"op": "connect", "a": a, "b": b}


def label(pin, text, kind="local"):
    return {"op": "add_label", "pin": pin, "text": text, "kind": kind}


def symbol(doc, sid, pins):
    doc.post("/ecad/init")
    return doc.post("/ecad/library/symbols/generate", {"kind": "ic", "id": sid, "pins": pins, "prefix": "U"})


def nets(netlist) -> dict:
    return {n["name"]: frozenset("%s.%s" % (x["ref"], x["pin"]) for x in n["nodes"]) for n in netlist["nets"]}


def groups(netlist) -> set:
    return set(nets(netlist).values())


def board(doc, rect=(0.0, 0.0, 40.0, 30.0), rules=None, stackup=None):
    body = {"rect": list(rect)}
    if stackup is not None:
        body["stackup"] = stackup
    doc.put("/pcb/board", body)
    if rules is not None:
        doc.put("/pcb/rules", {"profile": "generic", "overrides": rules})


def netlist(doc, table: dict, parts=()):
    doc.post("/pcb/netlist", {"nets": [{"name": n, "pins": [p.split(".") for p in pins]} for n, pins in table.items()], "parts": [{"refdes": r} for r in parts]})


def smd(number, x, y, w, h, shape="rect"):
    return {"number": str(number), "shape": shape, "x": x, "y": y, "w": w, "h": h}


def tht(number, x, y, size, drill, shape="circle"):
    return {"number": str(number), "shape": shape, "x": x, "y": y, "w": size, "h": size, "drill": drill, "layers": ["F.Cu", "B.Cu"]}


def place(doc, refdes, x, y, pads, rot=0.0, side="top", body=None, value="", footprint="", courtyard=None):
    rec = {"refdes": refdes, "x": x, "y": y, "rot": rot, "side": side, "pads": pads, "value": value, "footprint": footprint or refdes}
    if body is not None:
        rec["body"] = body
    if courtyard is not None:
        rec["courtyard"] = courtyard
    return doc.post("/pcb/parts", rec)


def world(px, py, local, rot=0.0, side="top"):
    lx, ly = local
    if side == "bottom":
        lx = -lx
    a = math.radians(rot)
    return (px + lx * math.cos(a) - ly * math.sin(a), py + lx * math.sin(a) + ly * math.cos(a))


def pad_nets(doc) -> dict:
    return {(p["refdes"], pad["number"]): pad["net"] for p in doc.get("/pcb")["parts"] for pad in p["pads"]}


def gerbers(doc, out: Path, **options) -> dict:
    report = doc.post("/ecad/export/gerber", {"out": str(out), "options": options or None})
    layers = {}
    drills = []
    for path in report["files"]:
        if path.endswith(".drl"):
            drills.append(Drill.read(path))
        else:
            g = Gerber.read(path)
            layers[g.function()] = g
    return {"layers": layers, "drills": drills, "files": report["files"]}


def near(a, b, tol=1e-6) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def flat_bbox(bbox) -> list:
    flat = []
    for part in bbox:
        flat.extend(part if isinstance(part, (list, tuple)) else [part])
    return [float(v) for v in flat]


U_PADS = [smd(1, -2.0, 0.0, 1.0, 0.6), smd(2, 2.0, 0.0, 1.0, 0.6)]
Q_PADS = [smd(1, 2.0, 0.0, 1.2, 0.5), smd(2, -2.0, 0.0, 1.2, 0.5)]
R_PADS = [smd(1, 1.5, 0.5, 0.8, 1.0), smd(2, -1.5, 0.5, 0.8, 1.0)]
J_PADS = [tht(1, 0.0, 0.0, 1.7, 1.0, "rect"), tht(2, 0.0, -2.54, 1.7, 1.0)]
PARTS = {
    "U1": {"x": 10.0, "y": 10.0, "rot": 0.0, "side": "top", "pads": U_PADS, "value": "LM1", "footprint": "SO2"},
    "Q1": {"x": 10.0, "y": 22.0, "rot": 90.0, "side": "top", "pads": Q_PADS, "value": "Q", "footprint": "SOT2"},
    "R1": {"x": 20.0, "y": 10.0, "rot": 0.0, "side": "bottom", "pads": R_PADS, "value": "1k", "footprint": "R0805"},
    "J1": {"x": 30.0, "y": 20.0, "rot": 0.0, "side": "top", "pads": J_PADS, "value": "HDR", "footprint": "HDR2"},
}
NETS = {"A": ["U1.1", "J1.1", "Q1.2"], "B": ["U1.2", "R1.1", "J1.2"], "C": ["Q1.1", "R1.2"]}
VIA = {"net": "B", "x": 15.0, "y": 25.0, "dia": 0.7, "drill": 0.3}
HOLE = {"x": 35.0, "y": 5.0, "drill": 3.2}
TRACK_A = {"net": "A", "layer": "F.Cu", "width": 0.3, "points": [[8, 10], [8, 15], [30, 15], [30, 20]]}
TRACK_B = {"net": "B", "layer": "B.Cu", "width": 0.4, "points": [[18.5, 10.5], [15, 10.5], [15, 25]]}


def output_board(doc, origin=(0.0, 0.0)):
    ox, oy = origin
    board(doc, (ox, oy, 40.0, 30.0))
    netlist(doc, NETS)
    for ref, p in PARTS.items():
        place(doc, ref, p["x"] + ox, p["y"] + oy, p["pads"], p["rot"], p["side"], value=p["value"], footprint=p["footprint"])
    doc.post("/pcb/vias", dict(VIA, x=VIA["x"] + ox, y=VIA["y"] + oy))
    doc.post("/pcb/holes", dict(HOLE, x=HOLE["x"] + ox, y=HOLE["y"] + oy))
    for t in (TRACK_A, TRACK_B):
        doc.post("/pcb/tracks", dict(t, points=[[x + ox, y + oy] for x, y in t["points"]]))


def expected_pads(layer):
    out = {}
    for ref, p in PARTS.items():
        for q in p["pads"]:
            layers = q.get("layers") or ["F.Cu"]
            if p["side"] == "bottom":
                layers = [{"F.Cu": "B.Cu", "B.Cu": "F.Cu"}[n] for n in layers]
            if layer not in layers:
                continue
            w, h = (q["h"], q["w"]) if p["rot"] % 180 == 90 else (q["w"], q["h"])
            out[(ref, q["number"])] = (world(p["x"], p["y"], (q["x"], q["y"]), p["rot"], p["side"]), (w, h), q)
    return out
