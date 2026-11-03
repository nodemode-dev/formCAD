from app.ecad import library, schematic
from app.ecad.store import EcadError, header, natural

MAX_INSTANCES = 2000
CELL = 10000


class UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        p = self.p
        if a not in p:
            p[a] = a
            return a
        root = a
        while p[root] != root:
            root = p[root]
        while p[a] != root:
            p[a], a = root, p[a]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def q(p):
    return (round(p[0] * 1000), round(p[1] * 1000))


def on_segment(a, b, p, tol=0.6):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    ln2 = dx * dx + dy * dy
    if ln2 == 0:
        return abs(px - ax) <= tol and abs(py - ay) <= tol
    t = ((px - ax) * dx + (py - ay) * dy) / ln2
    if t < 0 or t > 1:
        return False
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2 <= tol * tol


class SegIndex:
    def __init__(self):
        self.cells = {}

    def add(self, a, b, tag):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        for cx in range(x0 // CELL, x1 // CELL + 1):
            for cy in range(y0 // CELL, y1 // CELL + 1):
                self.cells.setdefault((cx, cy), []).append((a, b, tag))

    def hits(self, p):
        out = []
        for a, b, tag in self.cells.get((p[0] // CELL, p[1] // CELL), ()):
            if on_segment(a, b, p):
                out.append((a, b, tag))
        return out


def instances(h: dict) -> list:
    out = []

    def walk(sid, path, depth):
        if len(out) >= MAX_INSTANCES:
            raise EcadError("The hierarchy expands to more than %d sheet instances." % MAX_INSTANCES)
        if depth > 32:
            raise EcadError("The sheet hierarchy is more than 32 levels deep.")
        out.append((path, sid))
        for hs in h["sheets"][sid]["sheet_symbols"]:
            if hs["child"] in h["sheets"]:
                walk(hs["child"], (path.rstrip("/") + "/" + hs["id"]), depth + 1)

    walk(h["root"], "/", 0)
    return out


def depth_of(path):
    return 0 if path == "/" else path.count("/")


def qualified(path, text):
    return text if path == "/" else path + "/" + text


def analyse(h: dict) -> dict:
    uf = UF()
    findings = []
    comps = {}
    pins = {}
    named = {}
    power_names = set()
    labels_seen = []
    nc_points = set()
    att = {}
    busmembers = {}
    entries = []
    sheet_pin_checks = []
    insts = instances(h)

    def pk(path, p):
        return ("p", path, p)

    def attach(path, p, kind, ref=None):
        att.setdefault((path, p), []).append((kind, ref))

    for path, sid in insts:
        sh = h["sheets"][sid]
        wires = SegIndex()
        buses = SegIndex()
        for w in sh["wires"]:
            pts = [q(p) for p in w["points"]]
            first = pk(path, pts[0])
            for i, p in enumerate(pts):
                uf.union(pk(path, p), first)
                attach(path, p, "wire_end" if i in (0, len(pts) - 1) else "wire_vertex", w["id"])
                if i:
                    wires.add(pts[i - 1], p, (w["id"], first))
        for b in sh["buses"]:
            pts = [q(p) for p in b["points"]]
            first = ("bp", path, pts[0])
            for i, p in enumerate(pts):
                uf.union(("bp", path, p), first)
                if i:
                    buses.add(pts[i - 1], p, (b["id"], first))

        def join_wires(point, key, wid=None):
            for a, b, (w2, first) in wires.hits(point):
                if w2 != wid:
                    uf.union(key, first)

        for part in sorted(h["parts"].values(), key=lambda x: int(x["id"][1:])):
            for pl in part["placements"]:
                if pl["sheet"] != sid:
                    continue
                sym = library.sym_in(h, part["symbol"])
                if sym is None:
                    findings.append({"rule": "unknown_symbol", "message": "%s uses the unknown symbol %s." % (part["refdes"], part["symbol"]), "sheet": sid, "pos": pl["pos"], "refs": [part["refdes"]]})
                    continue
                ck = (part["id"], path)
                ref = part["instances"].get(path, part["refdes"])
                c = comps.setdefault(ck, {"part": part, "sym": sym, "path": path, "sheet": sid, "ref": ref, "units": 0, "pos": pl["pos"]})
                c["units"] += 1
                for pin in schematic.pins_of(h, part, pl, sym):
                    node = ("n", part["id"], path, pin["number"])
                    pos = q(pin["abs"])
                    uf.union(node, pk(path, pos))
                    join_wires(pos, pk(path, pos))
                    attach(path, pos, "pin", node)
                    if node in pins:
                        continue
                    info = {"ref": ref, "uuid": part["id"] if path == "/" else "%s@%s" % (part["id"], path), "pin": pin["number"], "pinname": pin["name"], "pintype": pin["etype"], "hidden": pin["hidden"], "power_symbol": sym["power"], "pos": pin["abs"], "sheet": sid, "path": path, "ckey": ck}
                    pins[node] = info
                    if sym["power"]:
                        name = part["value"] or pin["name"]
                        uf.union(node, ("g", name))
                        named[("g", name)] = ("power", name, 0)
                        power_names.add(name)
                    elif pin["hidden"] and pin["etype"] in ("power_in", "power_out"):
                        uf.union(node, ("g", pin["name"]))
                        named.setdefault(("g", pin["name"]), ("power", pin["name"], 0))
                        power_names.add(pin["name"])
        for x in sh["no_connects"]:
            nc_points.add((path, q(x["pos"])))
            attach(path, q(x["pos"]), "nc")
        for j in sh["junctions"]:
            p = q(j["pos"])
            key = pk(path, p)
            uf.find(key)
            attach(path, p, "junction")
            join_wires(p, key)
        for lb in sh["labels"]:
            p = q(lb["pos"])
            key = pk(path, p)
            members = schematic.expand_bus(lb["text"])
            attach(path, p, "label", lb["id"])
            on_bus = buses.hits(p)
            if members is not None or on_bus:
                if on_bus and members is not None:
                    busmembers.setdefault(uf.find(on_bus[0][2][1]), set()).update(members)
                    labels_seen.append(("bus", path, lb["text"], lb, sid))
                continue
            join_wires(p, key)
            kind = lb["kind"]
            nk = ("g", lb["text"]) if kind == "global" else (("l", path, lb["text"]) if kind == "local" else ("h", path, lb["text"]))
            uf.union(key, nk)
            if kind == "global":
                named.setdefault(nk, ("power" if lb["text"] in power_names else "global", lb["text"], 0))
            else:
                named[nk] = ("local", qualified(path, lb["text"]), depth_of(path))
            labels_seen.append((kind, path, lb["text"], lb, sid))
        for hs in sh["sheet_symbols"]:
            cpath = path.rstrip("/") + "/" + hs["id"]
            for sp in hs["pins"]:
                p = q(sp["pos"])
                key = pk(path, p)
                attach(path, p, "sheet_pin")
                join_wires(p, key)
                members = schematic.expand_bus(sp["name"])
                if members is not None:
                    for m in members:
                        uf.union(("l", path, m), ("l", cpath, m))
                else:
                    uf.union(key, ("h", cpath, sp["name"]))
                    named.setdefault(("h", cpath, sp["name"]), ("local", qualified(cpath, sp["name"]), depth_of(cpath)))
            sheet_pin_checks.append((path, sid, hs))
        for e in sh["bus_entries"]:
            a, b = q(e["pos"]), q([e["pos"][0] + e["dir"][0], e["pos"][1] + e["dir"][1]])
            attach(path, a, "bus_entry")
            attach(path, b, "bus_entry")
            join_wires(b, pk(path, b))
            on_bus = buses.hits(a)
            entries.append({"path": path, "sheet": sid, "id": e["id"], "wire_key": pk(path, b), "bus_root": uf.find(on_bus[0][2][1]) if on_bus else None, "pos": e["pos"]})
        for w in sh["wires"]:
            pts = [q(p) for p in w["points"]]
            ends = {pts[0], pts[-1]}
            for e in ends:
                others = [k for k, r in att.get((path, e), []) if not (r == w["id"] and k in ("wire_end", "wire_vertex"))]
                hit = [t for t in wires.hits(e) if t[2][0] != w["id"]]
                if not others and not hit:
                    findings.append({"rule": "dangling_wire", "message": "Wire %s ends at (%g, %g) without touching anything." % (w["id"], e[0] / 1000, e[1] / 1000), "sheet": sid, "pos": [e[0] / 1000, e[1] / 1000], "refs": [w["id"]]})
                elif hit and not others:
                    findings.append({"rule": "wire_end_on_wire", "message": "Wire %s ends on wire %s at (%g, %g) with no junction, so they are not joined." % (w["id"], hit[0][2][0], e[0] / 1000, e[1] / 1000), "sheet": sid, "pos": [e[0] / 1000, e[1] / 1000], "refs": [w["id"], hit[0][2][0]]})

    groups = {}
    for node, info in pins.items():
        groups.setdefault(uf.find(node), {"pins": [], "names": [], "has_power": False})["pins"].append(node)
    for nk, nm in named.items():
        g = groups.setdefault(uf.find(nk), {"pins": [], "names": [], "has_power": False})
        g["names"].append(nm)
        if nm[0] == "power":
            g["has_power"] = True

    comps_out = []
    for ck, c in comps.items():
        if c["sym"]["power"] or c["part"]["exclude_netlist"]:
            continue
        part = c["part"]
        comps_out.append({"ref": c["ref"], "uuid": part["id"] if c["path"] == "/" else "%s@%s" % (part["id"], c["path"]), "symbol": part["symbol"], "value": part["value"], "footprint": part["footprint"], "fields": dict(part["fields"]), "dnp": part["dnp"], "sheet": c["path"], "units": c["units"]})
    comps_out.sort(key=lambda c: natural(c["ref"]))

    extras = set()
    for (path, p), items in att.items():
        if any(kind not in ("pin", "nc") for kind, _r in items):
            extras.add(uf.find(pk(path, p)))
    nets = []
    unconnected = []
    used_names = set()
    for root, g in groups.items():
        real = [n for n in g["pins"] if not pins[n]["power_symbol"]]
        if not real:
            continue
        real.sort(key=lambda n: (natural(pins[n]["ref"]), natural(pins[n]["pin"])))
        classes = {"power": 0, "global": 1, "local": 2}
        best = None
        if g["names"]:
            best = min(g["names"], key=lambda t: (classes[t[0]], t[2], t[1]))
        if len(real) == 1 and best is None and root not in extras:
            for n in real:
                if not pins[n]["hidden"]:
                    unconnected.append({"ref": pins[n]["ref"], "uuid": pins[n]["uuid"], "pin": pins[n]["pin"], "pinname": pins[n]["pinname"], "pintype": pins[n]["pintype"], "nc": (pins[n]["path"], q(pins[n]["pos"])) in nc_points})
            continue
        if best:
            name, kind = best[1], best[0]
        else:
            first = pins[real[0]]
            name, kind = "Net-(%s-%s)" % (first["ref"], first["pin"]), "unnamed"
        base, k = name, 2
        while name in used_names:
            name = "%s_%d" % (base, k)
            k += 1
        used_names.add(name)
        nets.append({"name": name, "kind": kind, "nodes": [{"ref": pins[n]["ref"], "uuid": pins[n]["uuid"], "pin": pins[n]["pin"], "pinname": pins[n]["pinname"], "pintype": pins[n]["pintype"]} for n in real], "_root": root})
    nets.sort(key=lambda n: natural(n["name"]))
    for i, n in enumerate(nets, 1):
        n["code"] = i
    unconnected.sort(key=lambda u: (natural(u["ref"]), natural(u["pin"])))
    public = [{"code": n["code"], "name": n["name"], "kind": n["kind"], "nodes": n["nodes"]} for n in nets]
    nl = {"schema": 1, "design": h["name"], "units": h["units"], "components": comps_out, "nets": public, "unconnected": unconnected, "warnings": []}
    return {
        "netlist": nl, "nets": nets, "groups": groups, "pins": pins, "comps": comps, "findings": findings, "named": named, "labels": labels_seen, "uf": uf, "att": att, "nc": nc_points,
        "busmembers": busmembers, "entries": entries, "sheet_pin_checks": sheet_pin_checks, "power_names": power_names,
    }


def extract(d) -> dict:
    return analyse(header(d))["netlist"]
