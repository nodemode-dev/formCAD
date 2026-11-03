import copy

DATE_READ = "2026-11-03"
KEYS = {
    "clearance": ("Copper clearance (different nets)", 0.0, 5.0),
    "track_width": ("Minimum and default track width", 0.02, 10.0),
    "annular_ring": ("Minimum annular ring", 0.0, 3.0),
    "drill": ("Minimum drill diameter", 0.05, 10.0),
    "via_dia": ("Via pad diameter", 0.1, 10.0),
    "via_drill": ("Via drill diameter", 0.05, 10.0),
    "hole_to_hole": ("Minimum hole edge to hole edge", 0.0, 5.0),
    "edge_clearance": ("Copper to board edge", 0.0, 10.0),
}
SOURCES = {
    "jlcpcb": "JLCPCB, PCB Manufacturing and Assembly Capabilities, https://jlcpcb.com/capabilities/Capabilities",
    "pcbway": "PCBWay, PCB Capabilities, https://www.pcbway.com/capabilities.html",
    "oshpark": "OSH Park, 2 Layer Prototype Service, https://docs.oshpark.com/services/two-layer/",
    "generic": "FormCAD decision, R26 section 2.4: looser than all three fabricators so it passes at each",
}


def _v(value, src, note=""):
    return {"value": value, "source": src, "note": note}


PROFILES = {
    "generic": {
        "name": "FormCAD generic 2-layer",
        "read": DATE_READ,
        "values": {
            "clearance": _v(0.16, "generic", "R26 gave 0.15; raised to 0.16 so it is also looser than the 6 mil (0.1524 mm) OSH Park limit"),
            "track_width": _v(0.16, "generic", "same reason as clearance"),
            "annular_ring": _v(0.20, "generic"),
            "drill": _v(0.30, "generic"),
            "via_dia": _v(0.7, "generic", "R26 gave 0.6; 0.7 over a 0.3 drill gives the 0.20 ring the profile requires"),
            "via_drill": _v(0.3, "generic"),
            "hole_to_hole": _v(0.5, "generic"),
            "edge_clearance": _v(0.4, "generic"),
        },
    },
    "jlcpcb": {
        "name": "JLCPCB standard 2-layer 1 oz",
        "read": DATE_READ,
        "values": {
            "clearance": _v(0.10, "jlcpcb", "min track and space 0.10 mm for 1 and 2 layers"),
            "track_width": _v(0.10, "jlcpcb"),
            "annular_ring": _v(0.20, "jlcpcb", "page lists 0.20 minimum, 0.25 recommended, 0.18 absolute; the larger minimum is used, 0.18 is the advanced value"),
            "drill": _v(0.15, "jlcpcb", "0.10 costs more and needs thin boards"),
            "via_dia": _v(None, None, "the page asks only 0.10 mm over the hole, which is below the 0.20 ring used here; generic value used"),
            "via_drill": _v(None, None, "generic value used"),
            "hole_to_hole": _v(0.20, "jlcpcb", "via to via 0.20, pad hole 0.45; the pad value is not applied separately"),
            "edge_clearance": _v(None, None, "not read on the page; the generic value is used"),
        },
    },
    "pcbway": {
        "name": "PCBWay standard",
        "read": DATE_READ,
        "values": {
            "clearance": _v(0.10, "pcbway"),
            "track_width": _v(0.10, "pcbway"),
            "annular_ring": _v(0.15, "pcbway"),
            "drill": _v(0.15, "pcbway", "finished size, CNC"),
            "via_dia": _v(None, None, "not read; generic value used"),
            "via_drill": _v(None, None, "not read; generic value used"),
            "hole_to_hole": _v(None, None, "not read; generic value used"),
            "edge_clearance": _v(None, None, "not read; generic value used"),
        },
    },
    "oshpark": {
        "name": "OSH Park 2-layer",
        "read": DATE_READ,
        "values": {
            "clearance": _v(0.1524, "oshpark", "6 mil"),
            "track_width": _v(0.1524, "oshpark", "6 mil"),
            "annular_ring": _v(0.127, "oshpark", "5 mil"),
            "drill": _v(0.254, "oshpark", "10 mil"),
            "via_dia": _v(None, None, "not read; generic value used"),
            "via_drill": _v(None, None, "not read; generic value used"),
            "hole_to_hole": _v(0.127, "oshpark", "5 mil recommended between holes"),
            "edge_clearance": _v(0.381, "oshpark", "15 mil"),
        },
    },
}


class RuleError(ValueError):
    pass


def describe_profiles() -> dict:
    out = {}
    for pid, prof in PROFILES.items():
        vals = {}
        for k, v in prof["values"].items():
            eff = v["value"] if v["value"] is not None else PROFILES["generic"]["values"][k]["value"]
            vals[k] = {"value": eff, "source": SOURCES.get(v["source"]) if v["source"] else None, "fallback": v["value"] is None, "note": v["note"]}
        out[pid] = {"id": pid, "name": prof["name"], "read": prof["read"], "values": vals}
    return {"profiles": out, "keys": {k: {"label": t[0], "min": t[1], "max": t[2]} for k, t in KEYS.items()}, "note": "Fabricator values come from public marketing pages read on %s and change; they are starting points, edit them for your fabricator." % DATE_READ}


def values_of(profile: str) -> dict:
    prof = PROFILES.get(profile)
    if prof is None:
        raise RuleError("Unknown rule profile %s. Use one of: %s." % (profile, ", ".join(PROFILES)))
    out = {}
    for k, v in prof["values"].items():
        out[k] = v["value"] if v["value"] is not None else PROFILES["generic"]["values"][k]["value"]
    return out


def default_rules(profile: str = "generic") -> dict:
    return {"profile": profile, "values": values_of(profile), "overrides": {}, "classes": {}}


def effective(rules: dict) -> dict:
    out = values_of(rules.get("profile", "generic"))
    out.update(rules.get("overrides") or {})
    return out


def clean_overrides(raw) -> dict:
    if not isinstance(raw, dict):
        raise RuleError("Overrides is an object of rule values in millimetres.")
    out = {}
    for k, v in raw.items():
        if k not in KEYS:
            raise RuleError("Unknown rule %s. Rules are: %s." % (k, ", ".join(KEYS)))
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise RuleError("Rule %s must be a number." % k)
        lo, hi = KEYS[k][1], KEYS[k][2]
        if not lo <= f <= hi:
            raise RuleError("Rule %s is between %g and %g mm." % (k, lo, hi))
        out[k] = round(f, 4)
    return out


def clean_classes(raw) -> dict:
    if not isinstance(raw, dict):
        raise RuleError("Classes is an object of net name to {width, clearance}.")
    if len(raw) > 256:
        raise RuleError("At most 256 net classes.")
    out = {}
    for net, spec in raw.items():
        if not isinstance(spec, dict):
            raise RuleError("A net class is an object.")
        row = {}
        for key in ("width", "clearance"):
            if spec.get(key) is not None:
                f = float(spec[key])
                if not 0.02 <= f <= 10.0:
                    raise RuleError("Net %s %s is between 0.02 and 10 mm." % (net, key))
                row[key] = round(f, 4)
        out[str(net)[:80]] = row
    return out


def snapshot(rules: dict) -> dict:
    return copy.deepcopy(rules)
