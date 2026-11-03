import copy
import math
import re

HEADER = "COSTING"
EXAMPLE = "Example rates, not market data: every price and rate below is a placeholder the user replaces."
MAX_MATERIALS = 200

COMMON = {
    "rate_per_h": 60.0,
    "setup_h": 1.0,
    "labour_per_h": 40.0,
    "post_min": 2.0,
    "tooling": 0.0,
    "defect_pct": 2.0,
    "overhead_pct": 15.0,
    "margin_pct": 10.0,
}

DEFAULTS = {
    "currency": "USD",
    "batch": 100,
    "volume": 1000,
    "scrap": 0.05,
    "default_price_per_kg": 3.0,
    "fallback_density": None,
    "materials": {},
    "processes": {
        "machining": {**COMMON, "mrr_cm3_min": 8.0, "stock_allowance_mm": 2.0, "tool_life_min": 120.0, "tool_change_min": 2.0, "tool_price": 15.0, "use_cam": True},
        "sheet_metal": {**COMMON, "rate_per_h": 80.0, "setup_h": 0.5, "cut_speed_mm_min": 3000.0, "pierce_s": 0.5, "bend_time_s": 8.0, "utilisation": 0.75},
        "additive": {**COMMON, "rate_per_h": 12.0, "setup_h": 0.5, "build_rate_cm3_h": 8.0, "support_fraction": 0.15, "recoat_s_per_layer": 8.0, "layer_height_mm": 0.2, "use_slicer": True},
        "purchased": {"overhead_pct": 0.0, "margin_pct": 0.0, "defect_pct": 0.0},
    },
    "defined": False,
    "note": EXAMPLE,
}

SOURCES = {
    "structure": "material + machine rate x time + setup / batch + tooling / volume, then overhead and margin: University of Tennessee MTRC (MC2 paper), NIST Design-for-Cost, MDPI Sustainability 13(1) 319 (CC BY 3.0); read 2026-11-03",
    "machining_tool_term": "cycle time / tool life x (tool change time x rate + tool price): University of Tennessee MTRC, A New Machining Cost Calculator (MC2)",
    "sheet_metal": "blank cut from stock with sheet utilisation: MIT DSpace 1721.1/152646; the bend time term is a FormCAD placeholder (no source found)",
    "additive": "scan or build time from the slicer when present, otherwise volume / build rate; recoat per layer: MDPI Sustainability 13(1) 319",
    "values": "every number in the shipped profile is an example placeholder, not market data",
}


class ProfileError(ValueError):
    pass


def current(d) -> dict:
    out = copy.deepcopy(DEFAULTS)
    raw = d.header.get(HEADER)
    if isinstance(raw, dict):
        merge(out, raw)
        if entered(raw, DEFAULTS):
            out["defined"] = True
            out["note"] = ""
    return out


def entered(raw: dict, base: dict) -> bool:
    for k, v in raw.items():
        if k in ("currency", "batch", "volume", "defined", "note"):
            continue
        if k == "materials":
            if v:
                return True
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            if entered(v, base[k]):
                return True
        elif k in base and v != base[k]:
            return True
    return False


def merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if k == "materials" and isinstance(v, dict):
            base["materials"] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        elif k in base:
            base[k] = v


def number(v, label: str, low: float = 0.0, high: float = 1e9, none_ok: bool = False):
    if v is None and none_ok:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ProfileError("%s needs a number." % label)
    if not math.isfinite(x) or x < low or x > high:
        raise ProfileError("%s must be between %g and %g." % (label, low, high))
    return x


def clean_update(update: dict, base: dict) -> dict:
    if not isinstance(update, dict):
        raise ProfileError("The costing profile is an object.")
    out: dict = {}
    for k, v in update.items():
        if k in ("defined", "note"):
            continue
        if k == "currency":
            s = str(v or "").strip()
            if not (re.fullmatch(r"[A-Za-z]{1,8}", s) or s in ("$", chr(0x20AC), chr(0xA3), chr(0xA5), chr(0x20B9))):
                raise ProfileError("The currency is a short code of letters or a currency symbol.")
            out[k] = s
        elif k in ("batch", "volume"):
            out[k] = int(number(v, k, 1, 1e9))
        elif k == "scrap":
            out[k] = number(v, "Scrap", 0.0, 5.0)
        elif k == "default_price_per_kg":
            out[k] = number(v, "Default material price", 0.0, 1e6)
        elif k == "fallback_density":
            out[k] = number(v, "Fallback density", 0.0, 30000.0, True)
        elif k == "materials":
            if not isinstance(v, dict) or len(v) > MAX_MATERIALS:
                raise ProfileError("Materials is an object of up to %d entries." % MAX_MATERIALS)
            mats = {}
            for name, row in v.items():
                n = str(name).strip()
                if not n or len(n) > 80 or not isinstance(row, dict):
                    raise ProfileError("A material entry has a name and an object of prices.")
                m = {"price_per_kg": number(row.get("price_per_kg"), "Price per kg of %s" % n, 0.0, 1e6)}
                if row.get("density") is not None:
                    m["density"] = number(row.get("density"), "Density of %s" % n, 0.0, 30000.0)
                mats[n] = m
            out[k] = mats
        elif k == "processes":
            if not isinstance(v, dict):
                raise ProfileError("Processes is an object.")
            procs = {}
            for pname, row in v.items():
                if pname not in base["processes"] or not isinstance(row, dict):
                    raise ProfileError("The processes are machining, sheet_metal, additive and purchased.")
                cleaned = {}
                for key, val in row.items():
                    if key not in base["processes"][pname]:
                        raise ProfileError("%s has no setting %s." % (pname, key))
                    if isinstance(base["processes"][pname][key], bool):
                        cleaned[key] = bool(val)
                    else:
                        hi = 100.0 if key in ("utilisation",) else 1e7
                        cleaned[key] = number(val, "%s %s" % (pname, key), 0.0, hi)
                procs[pname] = cleaned
            out[k] = procs
        else:
            raise ProfileError("The costing profile has no setting %s." % k)
    return out


def put(d, update: dict) -> dict:
    base = current(d)
    cleaned = clean_update(update, base)
    stored = d.header.get(HEADER)
    stored = copy.deepcopy(stored) if isinstance(stored, dict) else {}
    merge_store(stored, cleaned)
    d.set_header(HEADER, stored)
    return current(d)


def merge_store(stored: dict, cleaned: dict) -> None:
    for k, v in cleaned.items():
        if k == "processes":
            procs = stored.setdefault("processes", {})
            for pn, row in v.items():
                procs.setdefault(pn, {}).update(row)
        else:
            stored[k] = v


def reset(d) -> None:
    if HEADER in d.header:
        d.set_header(HEADER, None)
