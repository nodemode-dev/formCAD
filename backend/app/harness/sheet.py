import csv
import io
import math

from app.doc import layouts as L
from app.doc import tableops as O
from app.doc.entities import Circle, Line, Text
from app.doc.model import layout_space
from app.harness.store import HarnessError

LAYER = "HARNESS"
LAYER_TABLE = "HARNESS-TABLE"
TEXT_H = 2.5
SHEETS = [("ISO A3", 420.0, 297.0), ("ISO A2", 594.0, 420.0), ("ISO A1", 841.0, 594.0), ("ISO A0", 1189.0, 841.0)]
MAX_CSV_BYTES = 8 * 1024 * 1024


def f1(x) -> str:
    return "%.1f" % x


def end_name(e) -> str:
    return "%s.%s" % (e["node"], e["pin"]) if e["pin"] else e["node"]


def tables(h, report) -> dict:
    wires = report["wires"]
    wl = [[w["id"], w["cable"], w["gauge"], w["colour"], "%.2f" % w["od"], end_name(w["from"]), end_name(w["to"]), w["net"], f1(w["run"]), f1(w["allowance"]), f1(w["cut"])] for w in wires]
    ft = sorted([[end_name(w["from"]), end_name(w["to"]), w["id"], w["net"], f1(w["cut"])] for w in wires], key=lambda r: (r[0], r[1]))
    segs = [[s["id"], s["a"], s["b"], str(s["count"]), f1(s["length"]), "%.2f" % s["od"], f1(s["required_radius"]), "-" if s["tightest"] is None else f1(s["tightest"]), "ok" if s["ok"] else "TIGHT"] for s in report["segments"]]
    pins = []
    for n in h["nodes"].values():
        if n["kind"] != "connector":
            continue
        used = {}
        for w in wires:
            for a, b in ((w["from"], w["to"]), (w["to"], w["from"])):
                if a["node"] == n["id"]:
                    used.setdefault(a["pin"], []).append((w["id"], end_name(b)))
        for p in n["pins"]:
            hits = used.get(p["id"], [])
            if not hits:
                pins.append([n["id"], p["id"], p["label"], "", ""])
            for wid, other in hits:
                pins.append([n["id"], p["id"], p["label"], wid, other])
    return {
        "wirelist": {"title": "WIRE LIST", "header": ["Wire", "Cable", "Gauge", "Colour", "OD mm", "From", "To", "Net", "Run mm", "Allow mm", "Cut mm"], "rows": wl},
        "fromto": {"title": "FROM-TO", "header": ["From", "To", "Wire", "Net", "Cut mm"], "rows": ft},
        "segments": {"title": "SEGMENTS", "header": ["Segment", "From", "To", "Wires", "Length mm", "OD mm", "Min R mm", "Tightest R", "Bend"], "rows": segs},
        "connectors": {"title": "CONNECTORS", "header": ["Conn", "Pin", "Label", "Wire", "To"], "rows": pins},
    }


def csv_text(tab: dict, sep=",") -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator="\n")
    w.writerow(tab["header"])
    for r in tab["rows"]:
        w.writerow(r)
    out = buf.getvalue()
    if len(out.encode("utf-8")) > MAX_CSV_BYTES:
        raise HarnessError("The table is larger than the 8 MB export limit.")
    return out


def make_table(d, tab, at):
    rows = tab["rows"] or [[""] * len(tab["header"])]
    ncol = len(tab["header"])
    t = O.build(d, "Standard", len(rows), ncol, at)
    for c in range(ncol):
        wide = max([len(str(tab["header"][c]))] + [len(str(r[c])) for r in rows])
        t.col_widths[c] = round(max(10.0, wide * TEXT_H * 0.72 + 4.0), 2)
    O.set_cell(d, t, 0, 0, tab["title"], "text")
    for c, name in enumerate(tab["header"]):
        O.set_cell(d, t, 1, c, name, "text")
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            O.set_cell(d, t, r + 2, c, val, "text")
    O.ensure_heights(d, t)
    return t


def segment_fractions(report, seg):
    pos = report["nodes"]
    ids = [seg["a"]] + list(seg["via"]) + [seg["b"]]
    cum, tot = [0.0], 0.0
    for i in range(len(ids) - 1):
        a, b = pos[ids[i]]["p"], pos[ids[i + 1]]["p"]
        tot += math.dist(a, b)
        cum.append(tot)
    return [(ids[i], (cum[i] / tot) if tot else 0.0) for i in range(1, len(ids) - 1)]


def clear(d, h):
    for hd in h["sheet"].get("handles", []):
        if d.get(hd) is not None:
            d.erase_entity(hd)
    h["sheet"]["handles"] = []


def choose_sheet(bw, bh, tw, th):
    for name, w, hh in SHEETS:
        if max(bw + 60, tw) + 20 <= w and bh + 50 + th + 20 <= hh:
            return name, w, hh, 1.0
    name, w, hh = SHEETS[-1]
    sx = (w - 80) / max(bw, 1.0)
    sy = (hh - 40 - th - 50) / max(bh, 1.0)
    s = max(0.02, min(1.0, sx, sy))
    return name, w, hh, round(s, 4)


def draw(d, h, report) -> dict:
    flat = h["flat"]
    if not flat["nodes"]:
        raise HarnessError("Flatten the harness first.")
    name = h["settings"]["layout"]
    space = layout_space(name)
    if L.find(d, name) is None:
        L.create(d, name)
    clear(d, h)
    tabs = tables(h, report)
    segs = [s for s in report["segments"] if s["id"] not in flat["cut"]]
    xs = [p[0] for p in flat["nodes"].values()]
    ys = [p[1] for p in flat["nodes"].values()]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    order = ["wirelist", "fromto", "connectors", "segments"]
    built = []
    at_x = 0.0
    probe = []
    for key in order:
        t = make_table(d, tabs[key], [0.0, 0.0])
        probe.append((key, t))
    tw = sum(t.width() for _k, t in probe) + 10.0 * (len(probe) - 1)
    th = max(t.height() for _k, t in probe)
    sheet, sw, sh, s = choose_sheet(bw, bh, tw, th)
    L.set_page_setup(d, name, {"paper": sheet, "margins": [5.0, 5.0, 5.0, 5.0], "scale": "1:1"})
    handles = []

    def add(ent, layer=LAYER):
        ent.layer = layer
        hd = d.add_entity(ent, space)
        handles.append(hd)
        return hd

    ox, oy = 30.0, sh - 30.0 - bh * s
    def P(n):
        x, y = flat["nodes"][n]
        return [ox + (x - min(xs)) * s, oy + (y - min(ys)) * s, 0.0]

    for sg in segs:
        a, b = P(sg["a"]), P(sg["b"])
        if math.dist(a, b) < 1e-6:
            continue
        add(Line(start=a, end=b))
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        if ang > math.pi / 2 or ang < -math.pi / 2:
            ang += math.pi
        nx, ny = -math.sin(ang), math.cos(ang)
        label = "%s  L %.1f  OD %.1f" % (sg["id"], sg["length"], sg["od"])
        if sg["via"]:
            label += "  clips %s" % ",".join(sg["via"])
        add(Text(position=[mx + nx * 2.0, my + ny * 2.0, 0.0], height=TEXT_H, text=label, rotation=ang))
        for cid, frac in segment_fractions(report, sg):
            cx, cy = a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac
            add(Circle(center=[cx, cy, 0.0], radius=1.2))
    for nid, n in h["nodes"].items():
        if nid not in flat["nodes"] or n["kind"] == "clip":
            continue
        p = P(nid)
        if n["kind"] == "connector":
            for dx, dy, ex, ey in ((-4, -4, 4, -4), (4, -4, 4, 4), (4, 4, -4, 4), (-4, 4, -4, -4)):
                add(Line(start=[p[0] + dx, p[1] + dy, 0.0], end=[p[0] + ex, p[1] + ey, 0.0]))
            add(Text(position=[p[0] - 4.0, p[1] + 6.0, 0.0], height=3.5, text="%s %s" % (nid, n["part"]) if n["part"] else nid))
            row = 0
            for w in report["wires"]:
                for e in (w["from"], w["to"]):
                    if e["node"] == nid and row < 14:
                        add(Text(position=[p[0] + 6.0, p[1] - 3.0 - row * 3.2, 0.0], height=2.2, text="%s:%s" % (e["pin"], w["id"])))
                        row += 1
        elif n["kind"] == "splice":
            add(Circle(center=p, radius=3.0))
            add(Text(position=[p[0] + 4.0, p[1] + 4.0, 0.0], height=TEXT_H, text=nid))
        else:
            add(Circle(center=p, radius=1.0))
            add(Text(position=[p[0] + 2.0, p[1] + 2.0, 0.0], height=TEXT_H, text=nid))
    add(Text(position=[ox, sh - 15.0, 0.0], height=4.0, text="HARNESS FORMBOARD   scale %s   lengths are true length%s" % ("1:1" if s >= 1.0 else "1:%.1f" % (1.0 / s), "" if s >= 1.0 else " (geometry reduced)")))
    cx = 10.0
    for key, probe_t in probe:
        t = make_table(d, tabs[key], [cx, 20.0 + th])
        t.layer = LAYER_TABLE
        handles.append(d.add_entity(t, space))
        cx += t.width() + 10.0
    h["sheet"] = {"layout": name, "handles": handles, "sheet": sheet, "scale": s}
    return {"layout": name, "sheet": sheet, "scale": s, "entities": len(handles), "tables": {k: len(v["rows"]) for k, v in tabs.items()}}
