from app.part import registry, store
from app.part.registry import Param, PartError
from app.param import units as U
from app.sheetmetal import bend, records, tables

ROOTS = ("base_flange", "convert_sheet")
METHOD_CHOICES = ["kfactor", "allowance", "deduction", "table"]
RELIEF_CHOICES = ["rect", "obround", "tear", "none"]
DEFAULT_RELIEF_RATIO = 0.5
DEFAULT_RELIEF_EXTRA_MM = 0.5

RULE_PARAMS = [
    Param("thickness", "length", None, min=0.0, label="Thickness"),
    Param("radius", "length", None, min=0.0, label="Inside radius"),
    Param("bend_method", "enum", "kfactor", choices=METHOD_CHOICES, label="Bend method"),
    Param("k_factor", "length", 0.44, min=0.0, max=1.0, label="K-factor", unit=""),
    Param("ba", "length", 0.0, min=0.0, label="Bend allowance at 90 degrees"),
    Param("bd", "length", 0.0, min=0.0, label="Bend deduction at 90 degrees"),
    Param("table_id", "text", "", label="Bend table"),
    Param("table_out_of_range", "enum", "clamp_warn", choices=["clamp_warn", "backup_k"], label="Outside the table"),
    Param("backup_k", "length", 0.44, min=0.0, max=1.0, label="Backup K-factor", unit=""),
    Param("relief_type", "enum", "rect", choices=RELIEF_CHOICES, label="Relief type"),
    Param("relief_width_ratio", "length", DEFAULT_RELIEF_RATIO, min=0.0, max=10.0, label="Relief width (times thickness)", unit=""),
    Param("relief_extra", "length", DEFAULT_RELIEF_EXTRA_MM, min=0.0, label="Relief depth past the bend"),
    Param("relief_remnant", "length", 0.0, min=0.0, label="Smallest remnant kept beside a relief"),
    Param("auto_relief", "bool", True, label="Relieve automatically"),
    Param("min_gap", "length", None, min=0.0, label="Smallest gap at miters and closed hems"),
]

OVERRIDE_PARAMS = [
    Param("radius", "length", None, min=0.0, label="Inside radius"),
    Param("bend_method", "enum", None, choices=METHOD_CHOICES, label="Bend method"),
    Param("k_factor", "length", None, min=0.0, max=1.0, label="K-factor", unit=""),
    Param("ba", "length", None, min=0.0, label="Bend allowance at 90 degrees"),
    Param("bd", "length", None, min=0.0, label="Bend deduction at 90 degrees"),
    Param("table_id", "text", "", label="Bend table"),
]

RELIEF_PARAMS = [
    Param("relief_mode", "enum", "rule", choices=["rule", "on", "off"], label="Relief"),
    Param("relief_type", "enum", None, choices=RELIEF_CHOICES, label="Relief type"),
    Param("relief_width_ratio", "length", None, min=0.0, max=10.0, label="Relief width (times thickness)", unit=""),
    Param("relief_extra", "length", None, min=0.0, label="Relief depth past the bend"),
]


def root_record(d):
    for rec in store.ordered(d):
        if rec["type"] in ROOTS and not rec.get("suppressed"):
            return rec
    return None


def evaluated(d, rec) -> dict:
    from app.part import rebuild

    return rebuild.evaluate(d, registry.get(rec["type"]), rec.get("params"))


def pick(value, default):
    return default if value is None else value


def build(d, values, mm, ref_key=None, row=None) -> dict:
    T = values.get("thickness")
    if T is None and row is not None:
        T = row.get("thickness")
        T = None if T is None else float(T)
    else:
        T = None if T is None else float(T) * mm
    if T is None or T <= 0:
        raise PartError("The sheet thickness must be above zero.")
    R = values.get("radius")
    if R is None and values.get("thickness") is None and row is not None and row.get("radius"):
        R = float(row["radius"])
    else:
        R = T if R is None else float(R) * mm
    if R <= 0:
        raise PartError("The inside radius must be above zero.")
    method = values.get("bend_method") or "kfactor"
    tid = str(values.get("table_id") or "")
    table = None
    if method == "table" or tid:
        table = tables.get(d, tid)
        if method == "table" and table is None:
            raise PartError("The bend method is table but %s is not a bend table." % (tid or "no table"))
    gap = values.get("min_gap")
    return {
        "thickness_mm": T,
        "inner_radius_mm": R,
        "bend_method": method,
        "k_factor": float(pick(values.get("k_factor"), bend.DEFAULT_K)),
        "ba_mm": float(pick(values.get("ba"), 0.0)) * mm,
        "bd_mm": float(pick(values.get("bd"), 0.0)) * mm,
        "table_id": tid,
        "table": table,
        "table_out_of_range": values.get("table_out_of_range") or "clamp_warn",
        "backup_k": float(pick(values.get("backup_k"), bend.DEFAULT_K)),
        "relief_type": values.get("relief_type") or "rect",
        "relief_width_ratio": float(pick(values.get("relief_width_ratio"), DEFAULT_RELIEF_RATIO)),
        "relief_extra_mm": float(pick(values.get("relief_extra"), DEFAULT_RELIEF_EXTRA_MM)) * mm,
        "relief_remnant_mm": float(pick(values.get("relief_remnant"), 0.0)) * mm,
        "auto_relief": bool(values.get("auto_relief", True)),
        "min_gap_mm": T / 10.0 if gap is None else float(gap) * mm,
        "ref_key": ref_key,
    }


def for_step(step) -> dict:
    d = step.d
    root = root_record(d)
    if root is None:
        raise PartError("Add a base flange or convert a solid to sheet metal first; the sheet metal rule lives on that feature.")
    mm = U.mm_per_unit(d)
    row = records.feature(d, root["id"])
    if root["id"] == step.feat["id"]:
        return build(d, step.values, mm, None, row)
    return build(d, evaluated(d, root), mm, (row or {}).get("ref_key"), row)


def refresh(doc, table_id=None) -> None:
    from app.part import tree

    d = doc.drawing
    root = root_record(d)
    if root is None or not store.has_part(d):
        return
    used = False
    for rec in store.ordered(d):
        if rec["type"] in registry.TYPES and registry.TYPES[rec["type"]].group == "sheetmetal":
            params = rec.get("params") or {}
            if table_id is None or params.get("table_id") == table_id:
                used = True
                break
    if used:
        tree.after_edit(doc, start=root["id"])


def save_table(doc, tid, body) -> dict:
    out = tables.put(doc.drawing, tid, body)
    refresh(doc, tid)
    return out


def drop_table(doc, tid) -> None:
    tables.remove(doc.drawing, tid)
    refresh(doc, tid)


def rule_of_part(d):
    root = root_record(d)
    if root is None:
        return None
    try:
        row = records.feature(d, root["id"])
        return build(d, evaluated(d, root), U.mm_per_unit(d), (row or {}).get("ref_key"), row)
    except PartError:
        return None


def effective(step, rule) -> tuple:
    d = step.d
    mm = step.mm
    eff = dict(rule)
    given = {}
    v = step.p("bend_method")
    if v:
        eff["bend_method"] = v
        given["bend_method"] = v
    for name, key in (("k_factor", "k_factor"),):
        if step.p(name) is not None:
            eff[key] = float(step.p(name))
            given[name] = eff[key]
    if step.p("ba") is not None:
        eff["ba_mm"] = float(step.p("ba")) * mm
        given["ba_mm"] = eff["ba_mm"]
    if step.p("bd") is not None:
        eff["bd_mm"] = float(step.p("bd")) * mm
        given["bd_mm"] = eff["bd_mm"]
    tid = str(step.p("table_id") or "")
    if tid:
        t = tables.get(d, tid)
        if t is None:
            raise PartError("There is no bend table %s." % tid)
        eff["table"], eff["table_id"] = t, tid
        given["table_id"] = tid
    if eff["bend_method"] == "table" and not eff.get("table"):
        raise PartError("The bend method is table but no bend table is set.")
    radius = step.p("radius")
    R = float(radius) * mm if radius is not None else rule["inner_radius_mm"]
    if R <= 0:
        raise PartError("The inside radius must be above zero.")
    if radius is not None:
        given["radius"] = R
    return eff, R, given


def relief_for(step, rule) -> dict:
    mode = step.p("relief_mode") or "rule"
    kind = step.p("relief_type") or rule["relief_type"]
    ratio = step.p("relief_width_ratio")
    extra = step.p("relief_extra")
    auto = rule["auto_relief"] if mode == "rule" else mode == "on"
    return {
        "type": kind,
        "width_ratio": rule["relief_width_ratio"] if ratio is None else float(ratio),
        "extra": rule["relief_extra_mm"] if extra is None else float(extra) * step.mm,
        "remnant": rule["relief_remnant_mm"],
        "auto": bool(auto),
        "gap": rule["min_gap_mm"],
    }


def ref_index(step, rule):
    key = rule.get("ref_key")
    if not key or step.base is None:
        return None
    keys = step.base_faces
    if key in keys:
        return keys.index(key)
    for i, k in enumerate(keys):
        if k and k.split("#", 1)[0] == key:
            return i
    raise PartError("The sheet's reference face %s is gone; the bend directions can no longer be told." % key)
