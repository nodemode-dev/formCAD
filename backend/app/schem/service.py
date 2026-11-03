import csv
import io

from app.core import outputs
from app.doc.entities import Circle, Line, Text
from app.schem import errors, numbering, store, symbols
from app.schem.errors import SchemError

TAG = "formcad_schem"
FRAME = (420.0, 297.0)
LAYERS = {"symbols": "SCHEM-SYMBOLS", "wires": "SCHEM-WIRES", "text": "SCHEM-TEXT", "frame": "SCHEM-FRAME"}
HEAD = ["name", "number", "from", "to", "gauge", "colour", "signal_class", "net", "sheet", "node"]


def overview(d) -> dict:
    devs = store.rows(d, "device")
    wires = [store.public(w) for w in store.rows(d, "wire")]
    return {"devices": devs, "wires": wires, "kinds": list(symbols.KINDS), "settings": store.settings(d), "sheets": sorted({x["sheet"] for x in devs} | {w["sheet"] for w in wires}), "limits": errors.get(), "labels": {"symbols": symbols.LABEL}}


def refmap(d) -> dict:
    return {r["id"]: r for r in store.rows(d, "device")}


def end_text(devs: dict, e: dict) -> str:
    dev = devs[e["device"]]
    if dev["type"] in ("junction", "ground"):
        return dev["refdes"]
    return "%s:%s" % (dev["refdes"], e["pin"])


def wirelist(d) -> list:
    devs = refmap(d)
    node_of = {}
    for n in numbering.nodes(d):
        for w in n["wires"]:
            node_of[w] = n["node"]
    rows_ = []
    for w in store.rows(d, "wire"):
        rows_.append({"id": w["id"], "name": w["wire"], "number": w["number"], "from": end_text(devs, w["from"]), "to": end_text(devs, w["to"]), "gauge": w["gauge"], "colour": w["colour"], "signal_class": w["signal_class"], "net": w["net"], "sheet": w["sheet"], "node": node_of.get(w["id"]), "length": w["length"]})
    rows_.sort(key=lambda r: (r["number"] or "~", r["name"]))
    errors.need(len(rows_), "rows", "Wire list rows")
    return rows_


def check(d) -> dict:
    devs = store.rows(d, "device")
    wires = store.rows(d, "wire")
    used = {(w[e]["device"], w[e]["pin"]) for w in wires for e in ("from", "to")}
    problems = []
    for dev in devs:
        if dev["type"] in ("ground", "junction"):
            continue
        open_pins = [p["id"] for p in dev["pins"] if (dev["id"], p["id"]) not in used]
        if open_pins:
            problems.append({"code": "open_pin", "severity": "warning", "message": "%s has pins with no wire: %s." % (dev["refdes"], ", ".join(open_pins))})
    seen = {}
    for w in wires:
        key = frozenset([(w["from"]["device"], w["from"]["pin"]), (w["to"]["device"], w["to"]["pin"])])
        if key in seen:
            problems.append({"code": "duplicate_wire", "severity": "warning", "message": "Wires %s and %s join the same two pins." % (seen[key], w["id"])})
        seen[key] = w["id"]
    for p in numbering.check_numbers(d):
        problems.append({**p, "severity": "warning" if p["code"] == "unnumbered" else "error"})
    return {"problems": problems, "errors": sum(1 for p in problems if p["severity"] == "error"), "devices": len(devs), "wires": len(wires)}


def harness_rows(d, supplied=None) -> list:
    if supplied is not None:
        return supplied
    from app.harness import store as hstore

    if not hstore.has_harness(d):
        raise SchemError("This drawing has no harness; pass the harness wire rows to compare.")
    h = hstore.header(d)

    def label(spec):
        node = h["nodes"].get(spec["node"], {})
        name = node.get("label") or spec["node"]
        return "%s:%s" % (name, spec["pin"]) if spec.get("pin") else name

    return [{"name": w["id"], "from": label(w["from"]), "to": label(w["to"]), "gauge": w.get("gauge", ""), "colour": w.get("colour", ""), "net": w.get("net", ""), "node_from": w["from"]["node"], "node_to": w["to"]["node"]} for w in h["wires"].values()]


def compare(d, supplied=None, sheets=None) -> dict:
    want = {int(s) for s in sheets} if sheets else None
    sch = {r["name"].casefold(): r for r in wirelist(d) if r["name"] and (want is None or r["sheet"] in want)}
    har = {str(r["name"]).casefold(): r for r in harness_rows(d, supplied)}
    diffs = []
    matched = 0
    for k, s in sch.items():
        h = har.get(k)
        if h is None:
            continue
        issues = []
        if {s["from"].casefold(), s["to"].casefold()} != {str(h["from"]).casefold(), str(h["to"]).casefold()}:
            issues.append({"field": "ends", "schematic": [s["from"], s["to"]], "harness": [h["from"], h["to"]]})
        for f in ("gauge", "colour"):
            if s[f] and h.get(f) and str(s[f]).casefold() != str(h[f]).casefold():
                issues.append({"field": f, "schematic": s[f], "harness": h[f]})
        if issues:
            diffs.append({"name": s["name"], "issues": issues})
        else:
            matched += 1
    only_s = sorted(sch[k]["name"] for k in sch if k not in har)
    only_h = sorted(str(har[k]["name"]) for k in har if k not in sch)
    return {"matched": matched, "differences": diffs, "only_schematic": only_s, "only_harness": only_h, "ok": not diffs and not only_s and not only_h, "schematic_wires": len(sch), "harness_wires": len(har)}


def write_csv(path: str, rows_: list) -> dict:
    full = outputs.checked(path, (".csv",), ".csv")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEAD)
    for r in rows_:
        w.writerow([r.get(k, "") if r.get(k) is not None else "" for k in HEAD])
    with open(full, "w", encoding="utf-8", newline="") as fh:
        fh.write(buf.getvalue())
    return {"path": full, "rows": len(rows_)}


def route_points(a, b, via):
    pts = [a] + [tuple(v) for v in via] + [b]
    if via:
        return pts
    if abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9:
        return pts
    mx = (a[0] + b[0]) / 2.0
    return [a, (mx, a[1]), (mx, b[1]), b]


class Painter:
    def __init__(self, d, ox):
        self.d = d
        self.ox = ox
        self.count = 0
        self.handles = []

    def tag(self, ent, layer, tag):
        ent.layer = layer
        ent.xdata = {TAG: tag}
        errors.need(self.count + 1, "entities", "Drawing entities")
        self.handles.append(self.d.add_entity(ent))
        self.count += 1

    def line(self, p, q, layer, tag):
        if abs(p[0] - q[0]) < 1e-9 and abs(p[1] - q[1]) < 1e-9:
            return
        self.tag(Line(start=[p[0], p[1], 0.0], end=[q[0], q[1], 0.0]), layer, tag)

    def text(self, p, s, h, layer, tag, rot=0.0):
        if s:
            self.tag(Text(position=[p[0], p[1], 0.0], text=s, height=h, rotation=rot), layer, tag)

    def circle(self, c, r, layer, tag):
        self.tag(Circle(center=[c[0], c[1], 0.0], radius=r), layer, tag)


def erase_old(d) -> int:
    old = [h for h, e in d.ents.items() if isinstance(e.xdata, dict) and TAG in e.xdata]
    for h in old:
        d.erase_entity(h)
    return len(old)


def draw(d) -> dict:
    devs = store.rows(d, "device")
    wires = store.rows(d, "wire")
    cfg = store.settings(d)
    removed = erase_old(d)
    dmap = {x["id"]: x for x in devs}
    sheets = sorted({x["sheet"] for x in devs} | {w["sheet"] for w in wires})
    counts = {"symbols": 0, "wires": 0, "frames": 0, "labels": 0}
    handles = []
    for sh in sheets:
        ox = (sh - 1) * cfg["sheet_pitch"]
        p = Painter(d, ox)
        w0, h0 = FRAME
        corners = [(ox, 0.0), (ox + w0, 0.0), (ox + w0, h0), (ox, h0)]
        for i in range(4):
            p.line(corners[i], corners[(i + 1) % 4], LAYERS["frame"], "frame%d" % sh)
        p.text((ox + 4.0, 4.0), "SHEET %d" % sh, 3.5, LAYERS["frame"], "frame%d" % sh)
        counts["frames"] += 1
        for dev in [x for x in devs if x["sheet"] == sh]:
            _pins, prims = symbols.build(dev["type"], dev.get("pin_count"))
            tag = dev["id"]

            def tr(x, y, dev=dev, ox=ox):
                rx, ry = symbols.rotate(x, y, dev["rotation"])
                return (ox + dev["x"] + rx, dev["y"] + ry)

            ys = [pt[1] for pt in [(q["dx"], q["dy"]) for q in dev["pins"]]] or [0.0]
            top = max(ys + [6.0])
            for pr in prims:
                if pr[0] == "line":
                    p.line(tr(*pr[1]), tr(*pr[2]), LAYERS["symbols"], tag)
                elif pr[0] == "circle":
                    p.circle(tr(*pr[1]), pr[2], LAYERS["symbols"], tag)
                else:
                    p.text(tr(*pr[1]), pr[2], pr[3], LAYERS["symbols"], tag)
            counts["symbols"] += 1
            p.text(tr(-6.0, top + 3.0), dev["refdes"], 2.5, LAYERS["text"], tag)
            if dev["label"]:
                p.text(tr(-6.0, top + 6.5), dev["label"], 2.0, LAYERS["text"], tag)
            for pin in dev["pins"]:
                px, py = symbols.pin_world({**dev, "x": ox + dev["x"]}, pin)
                p.text((px + 0.8, py + 0.8), pin["id"], 1.6, LAYERS["text"], tag)
            counts["labels"] += 1
        for w in [x for x in wires if x["sheet"] == sh]:
            da, db = dmap[w["from"]["device"]], dmap[w["to"]["device"]]
            pa = next(q for q in da["pins"] if q["id"] == w["from"]["pin"])
            pb = next(q for q in db["pins"] if q["id"] == w["to"]["pin"])
            a = symbols.pin_world({**da, "x": ox + da["x"]}, pa)
            b = symbols.pin_world({**db, "x": ox + db["x"]}, pb)
            via = [[ox + v[0], v[1]] for v in w.get("via") or []]
            pts = route_points(a, b, via)
            for i in range(len(pts) - 1):
                p.line(pts[i], pts[i + 1], LAYERS["wires"], w["id"])
            counts["wires"] += 1
            if w["number"]:
                segs = [(abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]), i) for i in range(len(pts) - 1)]
                ln, i = max(segs)
                if ln > 0:
                    mid = ((pts[i][0] + pts[i + 1][0]) / 2.0, (pts[i][1] + pts[i + 1][1]) / 2.0)
                    vertical = abs(pts[i + 1][0] - pts[i][0]) < 1e-9
                    p.text((mid[0] - (1.0 if vertical else len(w["number"]) * 0.8), mid[1] + (0.0 if vertical else 1.2)), w["number"], 2.0, LAYERS["text"], w["id"], 1.5707963267948966 if vertical else 0.0)
                    counts["labels"] += 1
        handles.extend(p.handles)
    return {"removed": removed, "entities": len(handles), "counts": counts, "sheets": sheets}
