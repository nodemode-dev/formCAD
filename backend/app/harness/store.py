import copy
import math
import re

from app.harness import rules

SCHEMA = 1
HEADER = "HARNESS"
NODE_KINDS = ("connector", "clip", "splice", "branch", "waypoint")
PREFIX = {"connector": "J", "clip": "K", "splice": "SP", "branch": "B", "waypoint": "P"}
MAX = {"nodes": 1500, "segments": 3000, "wires": 5000, "cables": 500, "pins": 500}
AGENT_MAX = {"nodes": 300, "segments": 600, "wires": 1000, "cables": 100, "pins": 128}
MODES = ("fillet", "spline")
DEFAULTS = {"min_bend_factor": rules.MIN_BEND_FACTOR, "allowance": 0.0, "insulation": 0.25, "mode": "fillet", "branch_angle": 90.0, "clearance": 12.0, "layout": "Formboard"}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$")


class HarnessError(ValueError):
    pass


def blank() -> dict:
    return {"schema": SCHEMA, "next": {}, "settings": dict(DEFAULTS), "nodes": {}, "segments": {}, "wires": {}, "cables": {}, "flat": {"nodes": {}, "trunk": [], "cut": [], "overlaps": [], "scale": 1.0}, "sheet": {"layout": "", "handles": []}}


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        for k, v in copy.deepcopy(raw).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict) and k in ("settings", "flat", "sheet", "next"):
                out[k].update(v)
            else:
                out[k] = v
    if int(out.get("schema", 1)) > SCHEMA:
        raise HarnessError("This harness was written with schema %s by a newer FormCAD." % out.get("schema"))
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def has_harness(d) -> bool:
    return isinstance(d.header.get(HEADER), dict)


def num(v, what, lo=None, hi=None, default=None) -> float:
    if v in (None, ""):
        if default is not None:
            return float(default)
        raise HarnessError("%s is required." % what)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HarnessError("%s must be a number." % what)
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise HarnessError("%s is out of range." % what)
    return x


def vec(v, what, n=3, default=None):
    if v in (None, ""):
        if default is not None:
            return list(default)
        raise HarnessError("%s is required." % what)
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        raise HarnessError("%s must be a list of numbers." % what)
    if len(out) == 2 and n == 3:
        out.append(0.0)
    if len(out) != n or not all(math.isfinite(x) for x in out):
        raise HarnessError("%s needs %d finite numbers." % (what, n))
    return out


def text(v, limit=80) -> str:
    return re.sub(r"[\x00-\x1f]", " ", str(v or "")).strip()[:limit]


def limit(caller: str, name: str) -> int:
    return (AGENT_MAX if caller else MAX)[name]


def room(h: dict, name: str, caller: str = "", extra: int = 1) -> None:
    if len(h[name]) + extra > limit(caller, name):
        raise HarnessError("The harness is limited to %d %s%s." % (limit(caller, name), name, " for a macro or agent" if caller else ""))


def new_id(h: dict, prefix: str, wanted, table: str) -> str:
    if wanted not in (None, ""):
        i = str(wanted).strip()
        if not ID_RE.match(i):
            raise HarnessError("An id is letters, digits, hyphen and underscore, starting with a letter.")
        for t in ("nodes", "segments", "wires", "cables"):
            if i in h[t]:
                raise HarnessError("The id %s is already used." % i)
        return i
    while True:
        n = int(h["next"].get(prefix, 1))
        h["next"][prefix] = n + 1
        i = "%s%d" % (prefix, n)
        if not any(i in h[t] for t in ("nodes", "segments", "wires", "cables")):
            return i


def need(h: dict, table: str, i) -> dict:
    rec = h[table].get(str(i or "").strip())
    if rec is None:
        raise HarnessError("There is no %s %s." % (table.rstrip("s").replace("segment", "segment"), i))
    return rec


def pins_of(spec, caller="") -> list:
    cap = limit(caller, "pins")
    if isinstance(spec, bool) or spec in (None, ""):
        return []
    if isinstance(spec, (int, float)):
        n = int(spec)
        if not 0 <= n <= cap:
            raise HarnessError("A connector has 0 to %d pins." % cap)
        return [{"id": str(i), "label": ""} for i in range(1, n + 1)]
    out, seen = [], set()
    for p in spec:
        rec = {"id": text(p.get("id") if isinstance(p, dict) else p, 16), "label": text(p.get("label", "") if isinstance(p, dict) else "", 40)}
        if not rec["id"] or rec["id"] in seen:
            raise HarnessError("Pin ids must be present and unique.")
        seen.add(rec["id"])
        out.append(rec)
    if len(out) > cap:
        raise HarnessError("A connector has 0 to %d pins." % cap)
    return out


def add_node(h, args, caller=""):
    kind = str(args.get("kind") or "").lower()
    if kind not in NODE_KINDS:
        raise HarnessError("kind is one of %s." % ", ".join(NODE_KINDS))
    room(h, "nodes", caller)
    i = new_id(h, PREFIX[kind], args.get("id"), "nodes")
    rec = {"id": i, "kind": kind, "label": text(args.get("label"), 60) or i, "component": text(args.get("component"), 64), "p": vec(args.get("point", args.get("p")), "point"), "axis": vec(args.get("axis"), "axis", default=[1, 0, 0])}
    if math.sqrt(sum(a * a for a in rec["axis"])) < 1e-9:
        raise HarnessError("axis cannot be zero.")
    if kind == "connector":
        rec["part"] = text(args.get("part"), 80)
        rec["pins"] = pins_of(args.get("pins"), caller)
    if kind == "clip":
        rec["inner_d"] = num(args.get("inner_d"), "inner_d", 0.0, 1000.0, 0.0)
    h["nodes"][i] = rec
    return rec


def add_segment(h, args, caller=""):
    room(h, "segments", caller)
    a, b = str(args.get("a") or ""), str(args.get("b") or "")
    for n in (a, b):
        need(h, "nodes", n)
    if a == b:
        raise HarnessError("A segment joins two different nodes.")
    via = [str(v) for v in (args.get("via") or [])]
    for v in via:
        if need(h, "nodes", v)["kind"] not in ("clip", "waypoint"):
            raise HarnessError("%s is not a clip or waypoint; only those can be passed through." % v)
    if len(via) > 100 or len(set(via + [a, b])) != len(via) + 2:
        raise HarnessError("via lists distinct clips or waypoints, at most 100.")
    mode = str(args.get("mode") or h["settings"]["mode"]).lower()
    if mode not in MODES:
        raise HarnessError("mode is fillet or spline.")
    i = new_id(h, "S", args.get("id"), "segments")
    rec = {"id": i, "a": a, "b": b, "via": via, "mode": mode, "radius": num(args.get("radius"), "radius", 0.0, 10000.0, 0.0), "min_radius": num(args.get("min_radius"), "min_radius", 0.0, 10000.0, 0.0), "diameter": num(args.get("diameter"), "diameter", 0.0, 1000.0, 0.0), "shield": bool(args.get("shield", False)), "covering": num(args.get("covering"), "covering", 0.0, 50.0, 0.0)}
    h["segments"][i] = rec
    return rec


def endpoint(h, spec, what):
    if isinstance(spec, str):
        spec = {"node": spec}
    if not isinstance(spec, dict):
        raise HarnessError("%s is {node, pin}." % what)
    n = need(h, "nodes", spec.get("node"))
    pin = str(spec.get("pin") or "").strip()
    if n["kind"] == "connector":
        if pin not in {p["id"] for p in n.get("pins", [])}:
            raise HarnessError("%s has no pin %s." % (n["id"], pin or "(none given)"))
    else:
        pin = ""
    return {"node": n["id"], "pin": pin}


def add_wire(h, args, caller="", cable=""):
    room(h, "wires", caller)
    gauge = text(args.get("gauge"), 16)
    od = args.get("od")
    if od in (None, ""):
        awg = rules.parse_gauge(gauge)
        if awg is None:
            raise HarnessError("Give od, or a gauge in AWG such as 20 to derive it.")
        od = rules.conductor_mm(awg) + 2.0 * h["settings"]["insulation"]
    i = new_id(h, "W", args.get("id"), "wires")
    rec = {"id": i, "gauge": gauge, "od": num(od, "od", 0.05, 100.0), "colour": text(args.get("colour", args.get("color")), 24), "net": text(args.get("net"), 40), "from": endpoint(h, args.get("from"), "from"), "to": endpoint(h, args.get("to"), "to"), "allowance_from": num(args.get("allowance_from"), "allowance_from", 0.0, 1000.0, h["settings"]["allowance"]), "allowance_to": num(args.get("allowance_to"), "allowance_to", 0.0, 1000.0, h["settings"]["allowance"]), "length": num(args.get("length"), "length", 0.0, 1e6, 0.0), "min_radius": num(args.get("min_radius"), "min_radius", 0.0, 10000.0, 0.0), "cable": cable}
    if rec["from"]["node"] == rec["to"]["node"]:
        raise HarnessError("A wire joins two different nodes.")
    h["wires"][i] = rec
    return rec


def add_cable(h, args, caller=""):
    room(h, "cables", caller)
    cores = args.get("cores")
    if not isinstance(cores, list) or not cores:
        raise HarnessError("A cable needs cores, a list of wire fields.")
    room(h, "wires", caller, len(cores))
    i = new_id(h, "CB", args.get("id"), "cables")
    frm, to = args.get("from"), args.get("to")
    ids = []
    for k, core in enumerate(cores, 1):
        c = dict(core)
        c.setdefault("from", {"node": (frm if isinstance(frm, str) else (frm or {}).get("node")), "pin": c.get("from_pin", "")}) if "from" not in c else None
        c.setdefault("to", {"node": (to if isinstance(to, str) else (to or {}).get("node")), "pin": c.get("to_pin", "")}) if "to" not in c else None
        c["id"] = c.get("id") or "%s-%d" % (i, k)
        w = add_wire(h, c, caller, cable=i)
        ids.append(w["id"])
    ends = {(h["wires"][w]["from"]["node"], h["wires"][w]["to"]["node"]) for w in ids}
    if len(ends) != 1:
        raise HarnessError("All cores of a cable run between the same two nodes.")
    rec = {"id": i, "cores": ids, "od": num(args.get("od"), "od", 0.1, 200.0), "shield": bool(args.get("shield", False)), "min_radius": num(args.get("min_radius"), "min_radius", 0.0, 10000.0, 0.0), "label": text(args.get("label"), 60)}
    h["cables"][i] = rec
    return rec


EDITABLE = {
    "nodes": ("label", "component", "p", "axis", "part", "pins", "inner_d"),
    "segments": ("via", "mode", "radius", "min_radius", "diameter", "shield", "covering"),
    "wires": ("gauge", "od", "colour", "net", "allowance_from", "allowance_to", "length", "min_radius"),
    "cables": ("od", "shield", "min_radius", "label"),
}
TABLES = {"node": "nodes", "segment": "segments", "wire": "wires", "cable": "cables"}


def edit(h, kind, ident, changes, caller=""):
    table = TABLES.get(str(kind).lower())
    if table is None:
        raise HarnessError("kind is node, segment, wire or cable.")
    rec = need(h, table, ident)
    if not isinstance(changes, dict) or not changes:
        raise HarnessError("changes is a dictionary of fields.")
    for k, v in changes.items():
        if k not in EDITABLE[table]:
            raise HarnessError("%s cannot be changed on a %s." % (k, kind))
        if k in ("p", "axis"):
            rec[k] = vec(v, k)
        elif k == "pins":
            rec[k] = pins_of(v, caller)
        elif k == "via":
            via = [str(x) for x in v]
            for x in via:
                if need(h, "nodes", x)["kind"] not in ("clip", "waypoint"):
                    raise HarnessError("%s is not a clip or waypoint." % x)
            rec[k] = via
        elif k == "mode":
            if str(v) not in MODES:
                raise HarnessError("mode is fillet or spline.")
            rec[k] = str(v)
        elif k in ("shield",):
            rec[k] = bool(v)
        elif k in ("label", "component", "part", "gauge", "colour", "net"):
            rec[k] = text(v, 80)
        else:
            rec[k] = num(v, k, 0.0, 1e6)
    return rec


def remove(h, kind, ident):
    table = TABLES.get(str(kind).lower())
    if table is None:
        raise HarnessError("kind is node, segment, wire or cable.")
    rec = need(h, table, ident)
    i = rec["id"]
    if table == "nodes":
        used = [s["id"] for s in h["segments"].values() if i in (s["a"], s["b"]) or i in s["via"]] + [w["id"] for w in h["wires"].values() if i in (w["from"]["node"], w["to"]["node"])]
        if used:
            raise HarnessError("%s is used by %s; remove those first." % (i, ", ".join(used[:6])))
    if table == "wires" and rec.get("cable"):
        raise HarnessError("%s is a core of cable %s; remove the cable." % (i, rec["cable"]))
    if table == "cables":
        for w in rec["cores"]:
            h["wires"].pop(w, None)
    del h[table][i]
    return i


def set_settings(h, changes):
    s = h["settings"]
    for k, v in (changes or {}).items():
        if k not in DEFAULTS:
            raise HarnessError("Unknown setting %s (%s)." % (k, ", ".join(DEFAULTS)))
        if k == "mode":
            if v not in MODES:
                raise HarnessError("mode is fillet or spline.")
            s[k] = v
        elif k == "layout":
            s[k] = text(v, 40) or DEFAULTS["layout"]
        else:
            s[k] = num(v, k, 0.0, 1000.0)
    return s
