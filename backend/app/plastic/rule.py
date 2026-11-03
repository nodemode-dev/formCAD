import copy
import math

from app.part import registry, store
from app.part.registry import PartError
from app.plastic import data

HEADER = "PLASTICRULE"
CLASSES = ("amorphous", "semicrystalline", "filled_amorphous", "filled_semicrystalline", "")

NUMBERS = {
    "nominal_wall": (0.05, 200.0),
    "wall_min": (0.0, 200.0),
    "wall_max": (0.0, 500.0),
    "wall_variation_pct": (0.0, 100.0),
    "adjacent_ratio_min": (0.0, 1.0),
    "min_draft": (0.0, 15.0),
    "recommended_draft": (0.0, 15.0),
    "texture_depth": (0.0, 5.0),
    "texture_draft_per_mm": (0.0, 200.0),
    "rib_ratio_min": (0.05, 3.0),
    "rib_ratio_max": (0.05, 3.0),
    "rib_height_max_ratio": (0.5, 30.0),
    "rib_spacing_min_ratio": (0.5, 30.0),
    "rib_base_fillet_ratio": (0.0, 2.0),
    "boss_od_ratio": (1.0, 6.0),
    "boss_od_ratio_insert": (1.0, 6.0),
    "boss_height_max_ratio": (0.5, 30.0),
    "boss_base_fillet": (0.0, 10.0),
    "corner_radius_ratio_min": (0.0, 3.0),
    "corner_radius_min": (0.0, 20.0),
    "snap_strain_allowable": (0.0, 100.0),
    "snap_repeat_factor": (0.05, 1.0),
    "snap_root_radius_min": (0.0, 10.0),
    "snap_friction": (0.0, 3.0),
    "snap_modulus": (1.0, 1.0e6),
    "lip_width_ratio": (0.02, 2.0),
    "lip_height_ratio": (0.02, 2.0),
    "groove_extra_width": (0.0, 5.0),
    "groove_extra_depth": (0.0, 5.0),
    "lip_clearance": (0.0, 5.0),
    "lip_draft": (0.0, 15.0),
    "lip_min_wall": (0.0, 50.0),
    "welded_min_wall": (0.0, 50.0),
}
NULLABLE = {"nominal_wall", "wall_min", "wall_max", "snap_strain_allowable", "snap_modulus"}
FROM_MATERIAL = (("wall_min", "wall_min"), ("wall_max", "wall_max"), ("wall_variation_pct", "wall_variation_pct"), ("rib_ratio_min", "rib_ratio_min"), ("rib_ratio_max", "rib_ratio_max"), ("snap_strain_allowable", "snap_strain_pct"))
KEYS = set(NUMBERS) | {"material", "material_class", "pull", "snap_repeated"}


def defaults() -> dict:
    out = {"material": "", "material_class": "", "pull": [0.0, 0.0, 1.0], "snap_repeated": False}
    for key in NUMBERS:
        out[key] = None
    out.update(data.rule_values())
    return out


def from_material(mid) -> dict:
    row = data.material(mid)
    if row is None:
        raise PartError("There is no material %s in the plastic table; the table has %s." % (mid, ", ".join(m["id"] for m in data.materials())))
    out = {"material": row["id"], "material_class": row.get("class") or ""}
    base = data.rule_values()
    for key, src in FROM_MATERIAL:
        val = (row.get(src) or {}).get("value") if isinstance(row.get(src), dict) else None
        out[key] = val if val is not None else (base.get(key) if key in base else None)
    if not isinstance(row.get("wall_variation_pct"), dict):
        out["wall_variation_pct"] = 12.5 if out["material_class"] in ("", "semicrystalline") else 25.0
    return out


def stored(d) -> dict | None:
    raw = d.header.get(HEADER)
    return copy.deepcopy(raw) if isinstance(raw, dict) else None


def current(d) -> dict:
    out = defaults()
    raw = stored(d)
    if raw:
        for key in KEYS:
            if key in raw:
                out[key] = raw[key]
    out["defined"] = raw is not None
    return out


def clean(key, value):
    if key == "material":
        mid = str(value or "")
        if mid and data.material(mid) is None:
            raise PartError("There is no material %s in the plastic table." % mid)
        return mid
    if key == "material_class":
        cls = str(value or "")
        if cls not in CLASSES:
            raise PartError("The material class is one of %s." % ", ".join(c for c in CLASSES if c))
        return cls
    if key == "snap_repeated":
        return bool(value)
    if key == "pull":
        try:
            v = [float(c) for c in value]
        except (TypeError, ValueError):
            raise PartError("The pull direction needs three numbers.")
        if len(v) != 3 or not all(math.isfinite(c) for c in v) or math.sqrt(sum(c * c for c in v)) < 1e-9:
            raise PartError("The pull direction needs three finite numbers that are not all zero.")
        return v
    lo, hi = NUMBERS[key]
    if value is None:
        if key in NULLABLE:
            return None
        raise PartError("%s needs a number." % key)
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise PartError("%s must be a number." % key)
    if not math.isfinite(v) or v < lo or v > hi:
        raise PartError("%s must be from %g to %g." % (key, lo, hi))
    return v


def consistent(rec: dict) -> None:
    if rec["wall_min"] is not None and rec["wall_max"] is not None and rec["wall_min"] > rec["wall_max"]:
        raise PartError("The smallest wall is above the largest wall.")
    if rec["rib_ratio_min"] > rec["rib_ratio_max"]:
        raise PartError("The smallest rib ratio is above the largest.")
    if rec["recommended_draft"] < rec["min_draft"]:
        raise PartError("The recommended draft is below the minimum draft.")


def put(d, values: dict) -> dict:
    if not isinstance(values, dict) or not values:
        raise PartError("Give the rule values to set.")
    bad = [k for k in values if k not in KEYS]
    if bad:
        raise PartError("%s is not a plastic rule value." % ", ".join(sorted(bad)))
    rec = current(d)
    rec.pop("defined", None)
    if values.get("material"):
        rec.update(from_material(values["material"]))
    for key, val in values.items():
        rec[key] = clean(key, val)
    consistent(rec)
    d.set_header(HEADER, copy.deepcopy(rec))
    return current(d)


def reset(d) -> None:
    if HEADER in d.header:
        d.set_header(HEADER, None)


def plastic_types() -> set:
    return {t.type for t in registry.TYPES.values() if t.group == "plastic"}


def first_feature(d):
    kinds = plastic_types()
    for rec in store.ordered(d):
        if rec["type"] in kinds and not rec.get("suppressed"):
            return rec
    return None


def refresh(doc) -> None:
    from app.part import tree

    d = doc.drawing
    first = first_feature(d)
    if first is not None and store.has_part(d):
        tree.after_edit(doc, start=first["id"])


def need_wall(rl, what) -> float:
    w = rl.get("nominal_wall")
    if not w:
        raise PartError("Set the nominal wall of the plastic rule first (PLASTICRULE nominal_wall) so the %s can take its size from it." % what)
    return float(w)
