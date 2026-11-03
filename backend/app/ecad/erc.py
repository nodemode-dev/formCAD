from app.ecad import library, netlist
from app.ecad.store import natural

CONFLICT = {
    ("output", "output"): "error", ("output", "power_out"): "error", ("power_out", "power_out"): "error", ("output", "tri_state"): "warning", ("power_out", "tri_state"): "warning",
    ("open_collector", "output"): "warning", ("open_collector", "power_out"): "warning", ("bidirectional", "power_out"): "warning",
}
DRIVERS = {"output", "bidirectional", "tri_state", "passive", "power_out", "open_collector"}
SOURCES = {"power_out", "output"}
MAX_PAIRS = 40


def _v(rule, sev, message, sheet="", pos=None, refs=None):
    return {"rule": rule, "severity": sev, "message": message, "sheet": sheet, "pos": pos, "refs": refs or []}


def run(h: dict, ana: dict | None = None) -> dict:
    ana = ana or netlist.analyse(h)
    sev = h["settings"]["erc"]
    out = []

    def add(rule, message, sheet="", pos=None, refs=None, override=None):
        level = override or sev.get(rule, "warning")
        if sev.get(rule) == "ignore":
            return
        out.append(_v(rule, level, message, sheet, pos, refs))

    for f in ana["findings"]:
        add(f["rule"], f["message"], f.get("sheet", ""), f.get("pos"), f.get("refs"))

    pins = ana["pins"]
    uf = ana["uf"]
    for net in ana["nets"]:
        nodes = [n for n in ana["groups"][net["_root"]]["pins"]]
        real = [n for n in nodes if not pins[n]["power_symbol"]]
        types = [pins[n]["pintype"] for n in real]
        has_power = ana["groups"][net["_root"]]["has_power"]
        sheet = pins[real[0]]["sheet"]
        pos = pins[real[0]]["pos"]
        count = 0
        for i in range(len(real)):
            for j in range(i + 1, len(real)):
                a, b = pins[real[i]], pins[real[j]]
                key = tuple(sorted((a["pintype"], b["pintype"])))
                lvl = CONFLICT.get(key)
                if a["pintype"] == "unconnected" or b["pintype"] == "unconnected":
                    lvl = "error"
                if lvl and count < MAX_PAIRS:
                    count += 1
                    add("pin_conflict", "Net %s joins %s %s (%s) and %s %s (%s)." % (net["name"], a["ref"], a["pin"], a["pintype"], b["ref"], b["pin"], b["pintype"]), a["sheet"], a["pos"], [a["ref"], b["ref"]], override=lvl if sev.get("pin_conflict") != "warning" else "warning")
        if "input" in types and not (set(types) & DRIVERS) and not has_power:
            ins = [pins[n] for n in real if pins[n]["pintype"] == "input"]
            add("input_no_driver", "Net %s has input pins (%s) and nothing drives it." % (net["name"], ", ".join("%s.%s" % (p["ref"], p["pin"]) for p in ins[:4])), sheet, pos, sorted({p["ref"] for p in ins}))
        if "power_in" in types and not (set(types) & SOURCES) and not has_power:
            ins = [pins[n] for n in real if pins[n]["pintype"] == "power_in"]
            add("power_not_driven", "Power input %s on net %s has no power output or power symbol." % (", ".join("%s.%s" % (p["ref"], p["pin"]) for p in ins[:4]), net["name"]), sheet, pos, sorted({p["ref"] for p in ins}))
        if len(real) == 1 and not any(p == (pins[real[0]]["path"], netlist.q(pins[real[0]]["pos"])) for p in ana["nc"]) and not has_power:
            p = pins[real[0]]
            add("single_node_net", "Net %s has only one pin (%s.%s)." % (net["name"], p["ref"], p["pin"]), p["sheet"], p["pos"], [p["ref"]])
        names = ana["groups"][net["_root"]]["names"]
        if names:
            classes = {"power": 0, "global": 1, "local": 2}
            top = min((classes[t[0]], t[2]) for t in names)
            distinct = sorted({t[1] for t in names if (classes[t[0]], t[2]) == top})
            if len(distinct) > 1:
                add("multiple_names", "Net %s carries several names: %s." % (net["name"], ", ".join(distinct)), sheet, pos, [])

    by_id = {(p["uuid"], p["pin"]): p for p in pins.values()}
    for u in ana["netlist"]["unconnected"]:
        if u["nc"] or u["pintype"] == "unconnected":
            continue
        pin = by_id[(u["uuid"], u["pin"])]
        add("pin_not_connected", "Pin %s.%s (%s) is not connected." % (u["ref"], u["pin"], u["pinname"]), pin["sheet"], pin["pos"], [u["ref"]])

    seen = {}
    for c in ana["comps"].values():
        if c["sym"]["power"]:
            continue
        seen.setdefault(c["ref"], []).append(c)
        part = c["part"]
        if c["ref"].endswith("?") or not c["ref"]:
            add("unannotated", "A part of symbol %s has no reference number." % part["symbol"], c["sheet"], c["pos"], [part["id"]])
        if not part["exclude_netlist"]:
            if not part["footprint"]:
                add("missing_footprint", "%s has no footprint." % c["ref"], c["sheet"], c["pos"], [c["ref"]])
            elif library.fp_in(h, part["footprint"]) is None:
                add("unknown_footprint", "%s uses the unknown footprint %s." % (c["ref"], part["footprint"]), c["sheet"], c["pos"], [c["ref"]])
            if not part["value"]:
                add("missing_value", "%s has no value." % c["ref"], c["sheet"], c["pos"], [c["ref"]])
    for ref, cs in seen.items():
        if len(cs) > 1:
            add("duplicate_refdes", "The reference %s is used by %d different parts." % (ref, len(cs)), cs[0]["sheet"], cs[0]["pos"], [ref])

    counts = {}
    for kind, path, text, lb, sid in ana["labels"]:
        if kind == "bus":
            continue
        key = ("g", text) if kind == "global" else (kind, path, text)
        counts[key] = counts.get(key, 0) + 1
    for kind, path, text, lb, sid in ana["labels"]:
        if kind in ("bus", "hier"):
            continue
        key = ("g", text) if kind == "global" else (kind, path, text)
        if counts[key] == 1:
            root = uf.find(("g", text) if kind == "global" else ("l", path, text))
            pinsn = [n for n in ana["groups"].get(root, {"pins": []})["pins"] if not pins[n]["power_symbol"]]
            if len(pinsn) < 2:
                add("single_label", "Label %s is used only once and joins fewer than two pins." % text, sid, lb["pos"], [lb["id"]])

    for e in ana["entries"]:
        if e["bus_root"] is None:
            add("bus_member_mismatch", "Bus entry %s is not on a bus." % e["id"], e["sheet"], e["pos"], [e["id"]])
            continue
        members = ana["busmembers"].get(uf.find(e["bus_root"]), set())
        if not members:
            continue
        wire_root = uf.find(e["wire_key"])
        names = {n[1] if n[0] == "g" else n[2] for n, t in ana["named"].items() if n[0] in ("l", "g") and uf.find(n) == wire_root and (n[0] == "g" or n[1] == e["path"])}
        for nm in names:
            if nm not in members:
                add("bus_member_mismatch", "Bus entry %s carries %s, which is not a member of the bus." % (e["id"], nm), e["sheet"], e["pos"], [e["id"]])

    for path, sid, hs in ana["sheet_pin_checks"]:
        child = h["sheets"][hs["child"]]
        have = {l["text"] for l in child["labels"] if l["kind"] == "hier"}
        pin_names = {p["name"] for p in hs["pins"]}
        for n in sorted(pin_names - have):
            add("sheet_pin_mismatch", "Sheet symbol %s has pin %s but sheet %s has no hierarchical label %s." % (hs["id"], n, child["name"], n), sid, hs["pos"], [hs["id"]])
        for n in sorted(have - pin_names):
            add("sheet_pin_mismatch", "Sheet %s has hierarchical label %s with no pin on sheet symbol %s." % (child["name"], n, hs["id"]), sid, hs["pos"], [hs["id"]])
    root = h["sheets"][h["root"]]
    for lb in root["labels"]:
        if lb["kind"] == "hier":
            add("sheet_pin_mismatch", "Hierarchical label %s on the root sheet has no parent sheet." % lb["text"], root["id"], lb["pos"], [lb["id"]])

    out.sort(key=lambda v: ({"error": 0, "warning": 1}.get(v["severity"], 2), v["rule"], natural(v["message"])))
    summary = {"error": sum(1 for v in out if v["severity"] == "error"), "warning": sum(1 for v in out if v["severity"] == "warning")}
    return {"violations": out, "summary": summary, "rules": dict(sev)}
