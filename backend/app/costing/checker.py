import copy
import fnmatch
import math
import re

from app.costing import finding as FD
from app.part import store as pstore
from app.solid import work

HEADER = "DESIGNRULES"
MAX_RULES = 100
SOURCE = "user rule"

KINDS = {
    "property_required": {"fields": ("key",), "text": "A custom property must exist and not be empty."},
    "property_matches": {"fields": ("key", "equals", "one_of", "glob"), "text": "A property value must equal, be one of, or match a pattern."},
    "units": {"fields": ("expect",), "text": "The document unit must be the given one (mm, cm, m, in, ft)."},
    "name_pattern": {"fields": ("target", "glob", "forbid"), "text": "Names of features, bodies, sketches or components must match (or must not match) a pattern with * and ?."},
    "feature_forbidden": {"fields": ("types",), "text": "Listed feature types must not be used."},
    "feature_min_value": {"fields": ("type", "param", "min"), "text": "A numeric parameter of a feature type must be at least a value (document units)."},
    "feature_max_count": {"fields": ("type", "max"), "text": "At most this many features of a type."},
    "body_count": {"fields": ("min", "max"), "text": "The number of solid bodies must be within a range."},
    "mass_max": {"fields": ("kg",), "text": "The part mass must not exceed this many kilograms."},
    "bbox_max": {"fields": ("mm",), "text": "No bounding box side may exceed this many millimetres."},
    "closed_solids": {"fields": (), "text": "Every body must be a closed valid solid."},
    "material_set": {"fields": ("one_of",), "text": "The material must be one of the listed names."},
    "min_wall": {"fields": ("mm",), "text": "The thinnest sampled wall must be at least this many millimetres (geometry rule)."},
    "min_hole_diameter": {"fields": ("mm",), "text": "No round hole may be smaller than this many millimetres (geometry rule)."},
}
COMMON = ("id", "kind", "label", "severity", "enabled")


class RuleError(ValueError):
    pass


def current(d) -> list:
    raw = d.header.get(HEADER)
    return copy.deepcopy(raw) if isinstance(raw, list) else []


def text(v, label: str, n: int = 120) -> str:
    s = str(v if v is not None else "").strip()
    if not s or len(s) > n or any(ord(c) < 32 for c in s):
        raise RuleError("%s needs 1 to %d characters." % (label, n))
    return s


def num(v, label: str, low: float = 0.0, high: float = 1e9) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise RuleError("%s needs a number." % label)
    if not math.isfinite(x) or x < low or x > high:
        raise RuleError("%s must be between %g and %g." % (label, low, high))
    return x


def clean_rule(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise RuleError("A rule is an object.")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise RuleError("The rule kinds are: %s." % ", ".join(KINDS))
    for k in raw:
        if k not in COMMON and k not in KINDS[kind]["fields"]:
            raise RuleError("The %s rule has no field %s." % (kind, k))
    out = {"id": text(raw.get("id"), "A rule id", 40), "kind": kind, "label": str(raw.get("label") or raw.get("id") or "")[:160], "severity": raw.get("severity") or "error", "enabled": bool(raw.get("enabled", True))}
    if out["severity"] not in FD.SEVERITIES:
        raise RuleError("Severity is error, warning or info.")
    if kind in ("property_required", "property_matches"):
        out["key"] = re.sub(r"[\s\-]+", "_", text(raw.get("key"), "The property key", 64).lower())
    if kind == "property_matches":
        if raw.get("equals") is not None:
            out["equals"] = text(raw["equals"], "equals", 200)
        if raw.get("one_of") is not None:
            out["one_of"] = [text(x, "one_of", 80) for x in list(raw["one_of"])[:50]]
        if raw.get("glob") is not None:
            out["glob"] = text(raw["glob"], "glob", 80)
        if not any(k in out for k in ("equals", "one_of", "glob")):
            raise RuleError("property_matches needs equals, one_of or glob.")
    if kind == "units":
        out["expect"] = text(raw.get("expect"), "The unit", 12).lower()
    if kind == "name_pattern":
        out["target"] = raw.get("target") or "feature"
        if out["target"] not in ("feature", "body", "sketch", "component", "document"):
            raise RuleError("The name target is feature, body, sketch, component or document.")
        if raw.get("glob") is not None:
            out["glob"] = text(raw["glob"], "glob", 80)
        if raw.get("forbid") is not None:
            out["forbid"] = text(raw["forbid"], "forbid", 80)
        if "glob" not in out and "forbid" not in out:
            raise RuleError("name_pattern needs glob or forbid.")
    if kind == "feature_forbidden":
        types = raw.get("types")
        if not isinstance(types, list) or not types or len(types) > 50:
            raise RuleError("types is a list of feature type names.")
        out["types"] = [text(t, "A feature type", 40) for t in types]
    if kind == "feature_min_value":
        out["type"] = text(raw.get("type"), "The feature type", 40)
        out["param"] = text(raw.get("param"), "The parameter", 40)
        out["min"] = num(raw.get("min"), "min", -1e9)
    if kind == "feature_max_count":
        out["type"] = text(raw.get("type"), "The feature type", 40)
        out["max"] = int(num(raw.get("max"), "max", 0, 100000))
    if kind == "body_count":
        out["min"] = int(num(raw.get("min", 0), "min", 0, 100000))
        out["max"] = int(num(raw.get("max", 100000), "max", 0, 100000))
    if kind == "mass_max":
        out["kg"] = num(raw.get("kg"), "kg", 0, 1e9)
    if kind == "bbox_max":
        out["mm"] = num(raw.get("mm"), "mm", 0, 1e9)
    if kind == "material_set":
        out["one_of"] = [text(x, "one_of", 80) for x in list(raw.get("one_of") or [])[:50]]
        if not out["one_of"]:
            raise RuleError("material_set needs one_of.")
    if kind in ("min_wall", "min_hole_diameter"):
        out["mm"] = num(raw.get("mm"), "mm", 0, 1e6)
    return out


def put(d, rules) -> list:
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise RuleError("The rules are a list of at most %d." % MAX_RULES)
    cleaned = [clean_rule(r) for r in rules]
    ids = [r["id"] for r in cleaned]
    if len(set(i.casefold() for i in ids)) != len(ids):
        raise RuleError("Rule ids must be unique.")
    d.set_header(HEADER, cleaned or None)
    return cleaned


def add_names(d, target: str) -> list:
    out = []
    if target in ("feature", "sketch"):
        for rec in pstore.ordered(d):
            is_sketch = rec["type"] == "sketch"
            if (target == "sketch") == is_sketch:
                out.append((rec.get("label") or rec["id"], {"feature": rec["id"]}))
    return out


def evaluate_part(t: dict, f: dict, rules: list, geometry) -> list:
    d = t["drawing"]
    part = t["label"]
    out: list = []
    props = f["props"]

    def add(rule, message, ref=None, measured=None, limit=None):
        out.append(FD.make("check:" + rule["id"], rule["severity"], message, ref=ref, measured=measured, limit=limit, source=SOURCE, category="design", part=part))

    recs = pstore.ordered(d)
    for r in rules:
        if not r.get("enabled", True):
            continue
        k = r["kind"]
        if t.get("purchased") and k in ("min_wall", "min_hole_diameter", "closed_solids"):
            continue
        if k == "property_required":
            if not str(props.get(r["key"], "")).strip():
                add(r, "%s: property %s is missing or empty." % (r["label"], r["key"]), {"property": r["key"]})
        elif k == "property_matches":
            v = str(props.get(r["key"], ""))
            ok = True
            if "equals" in r:
                ok = ok and v == r["equals"]
            if "one_of" in r:
                ok = ok and v in r["one_of"]
            if "glob" in r:
                ok = ok and fnmatch.fnmatchcase(v, r["glob"])
            if not ok:
                add(r, "%s: property %s is %r." % (r["label"], r["key"], v), {"property": r["key"]}, v)
        elif k == "units":
            from app.interchange import fileunits

            name = fileunits.document_unit(d)[0]
            if str(name).lower() != r["expect"]:
                add(r, "%s: the document unit is %s, expected %s." % (r["label"], name, r["expect"]), None, name, r["expect"])
        elif k == "name_pattern":
            if r["target"] == "document":
                names = [(t["label"], {})]
            elif r["target"] == "body":
                names = [(b["name"] or "", {"body": b["handle"]}) for b in f["bodies"]]
            elif r["target"] == "component":
                names = [] if not t.get("component_names") else [(n, {}) for n in t["component_names"]]
            else:
                names = add_names(d, r["target"])
            for nm, ref in names:
                if "glob" in r and not fnmatch.fnmatchcase(nm, r["glob"]):
                    add(r, "%s: %s name %r does not match %s." % (r["label"], r["target"], nm, r["glob"]), ref, nm, r["glob"])
                if "forbid" in r and fnmatch.fnmatchcase(nm, r["forbid"]):
                    add(r, "%s: %s name %r matches the forbidden pattern %s." % (r["label"], r["target"], nm, r["forbid"]), ref, nm, r["forbid"])
        elif k == "feature_forbidden":
            for rec in recs:
                if rec["type"] in r["types"] and not rec.get("suppressed"):
                    add(r, "%s: feature %s is a forbidden %s." % (r["label"], rec.get("label") or rec["id"], rec["type"]), {"feature": rec["id"]}, rec["type"])
        elif k == "feature_min_value":
            for rec in recs:
                if rec["type"] != r["type"] or rec.get("suppressed"):
                    continue
                v = (rec.get("params") or {}).get(r["param"])
                if isinstance(v, dict):
                    v = v.get("value")
                if isinstance(v, (int, float)) and v < r["min"] - 1e-12:
                    add(r, "%s: %s of %s is %g, the minimum is %g." % (r["label"], r["param"], rec.get("label") or rec["id"], v, r["min"]), {"feature": rec["id"]}, v, r["min"])
        elif k == "feature_max_count":
            n = sum(1 for rec in recs if rec["type"] == r["type"] and not rec.get("suppressed"))
            if n > r["max"]:
                add(r, "%s: %d features of type %s, at most %d allowed." % (r["label"], n, r["type"], r["max"]), None, n, r["max"])
        elif k == "body_count":
            n = len(f["bodies"])
            if n < r["min"] or n > r["max"]:
                add(r, "%s: %d bodies, expected %d to %d." % (r["label"], n, r["min"], r["max"]), None, n, [r["min"], r["max"]])
        elif k == "mass_max":
            if f.get("mass") is not None and f["mass"] > r["kg"]:
                add(r, "%s: mass %.4g kg exceeds %.4g kg." % (r["label"], f["mass"], r["kg"]), None, round(f["mass"], 6), r["kg"])
        elif k == "bbox_max":
            if f.get("bbox"):
                side = max(f["bbox"][3 + i] - f["bbox"][i] for i in range(3))
                if side > r["mm"]:
                    add(r, "%s: longest side %.4g mm exceeds %.4g mm." % (r["label"], side, r["mm"]), None, round(side, 4), r["mm"])
        elif k == "closed_solids":
            for w in f["warnings"]:
                if "closed" in w:
                    add(r, "%s: %s" % (r["label"], w))
        elif k == "material_set":
            if f["material"] not in r["one_of"]:
                add(r, "%s: material %r is not in the allowed set." % (r["label"], f["material"]), None, f["material"], r["one_of"])
        elif k in ("min_wall", "min_hole_diameter"):
            for x in geometry(t, f, k, r["mm"]):
                add(r, "%s: %s" % (r["label"], x[0]), x[1], x[2], r["mm"])
    return out


def geometry_measure(t: dict, f: dict, kind: str, limit: float) -> list:
    out = []
    d = t["drawing"]
    for b in f["bodies"][:8]:
        wid = work.worker_id(d, d.get(int(b["handle"])))
        if kind == "min_wall":
            wall = work.kcall("pl_wall", {"id": wid, "method": "sphere", "samples": 800, "margin": 1.0}, work.LONG)
            vals = [v for v in wall["thickness"] if v is not None]
            if vals and min(vals) < limit - 1e-9:
                out.append(("thinnest sampled wall %.3g mm." % min(vals), {"body": b["handle"]}, round(min(vals), 4)))
        else:
            ins = work.kcall("pl_inspect", {"id": wid, "pull": [0, 0, 1], "grid": 3}, work.LONG)
            for row in ins["faces"]:
                if row.get("kind") == "cylinder" and row.get("concave") and (row.get("span_deg") or 0) >= 300 and 2 * float(row["radius"]) < limit - 1e-9:
                    out.append(("hole of %.3g mm diameter." % (2 * float(row["radius"])), {"body": b["handle"], "face": row["face"]}, round(2 * float(row["radius"]), 4)))
    return out
