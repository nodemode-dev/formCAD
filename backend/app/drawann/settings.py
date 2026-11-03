import copy

KEY = "FC_DRAWANN"
ORDER_NAMES = ("characteristic", "tolerance", "datum1", "datum2", "datum3")
BOM_COLUMNS = ("item", "part_number", "description", "material", "qty")
COLUMN_TITLES = {"item": "ITEM", "part_number": "PART NUMBER", "description": "DESCRIPTION", "material": "MATERIAL", "qty": "QTY"}

DEFAULTS = {
    "text_height": 3.5,
    "gdt_order": list(ORDER_NAMES),
    "balloon_diameter": 9.525,
    "balloon_end": "arrow",
    "arrow_size": 2.5,
    "center_extension": 2.0,
    "center_gap": 1.0,
    "center_long": 6.0,
    "center_short": 1.5,
    "finish_height": 3.5,
    "balloon_ring": 12.0,
    "balloon_spacing": 14.0,
    "bom_columns": list(BOM_COLUMNS),
    "bom_text_height": 3.0,
    "bom_row_height": 7.0,
    "hatch_pattern": "ANSI31",
    "hatch_scale": 1.0,
}

NUMERIC = ("text_height", "balloon_diameter", "arrow_size", "center_extension", "center_gap", "center_long", "center_short", "finish_height", "balloon_ring", "balloon_spacing", "bom_text_height", "bom_row_height", "hatch_scale")


class SettingsError(Exception):
    pass


def check_order(order) -> list:
    if not isinstance(order, (list, tuple)) or not order:
        raise SettingsError("The compartment order is a list of names.")
    names = [str(x).strip().lower() for x in order]
    for n in names:
        if n not in ORDER_NAMES:
            raise SettingsError("Compartment %s is not known; use %s." % (n, ", ".join(ORDER_NAMES)))
    if len(set(names)) != len(names):
        raise SettingsError("A compartment appears twice.")
    if "characteristic" not in names or "tolerance" not in names:
        raise SettingsError("The order must hold characteristic and tolerance.")
    return names


def check_columns(cols) -> list:
    if not isinstance(cols, (list, tuple)) or not cols:
        raise SettingsError("The BOM columns are a list of names.")
    names = [str(x).strip().lower() for x in cols]
    for n in names:
        if n not in BOM_COLUMNS:
            raise SettingsError("Column %s is not known; use %s." % (n, ", ".join(BOM_COLUMNS)))
    if len(set(names)) != len(names):
        raise SettingsError("A column appears twice.")
    return names


def clean(changes: dict) -> dict:
    out = {}
    for k, v in (changes or {}).items():
        if k not in DEFAULTS:
            raise SettingsError("Unknown setting %s." % k)
        if k == "gdt_order":
            out[k] = check_order(v)
        elif k == "bom_columns":
            out[k] = check_columns(v)
        elif k == "balloon_end":
            if str(v).lower() not in ("arrow", "dot"):
                raise SettingsError("The balloon end is arrow or dot.")
            out[k] = str(v).lower()
        elif k == "hatch_pattern":
            out[k] = str(v)
        else:
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise SettingsError("%s is a number." % k)
            if not 0.01 <= f <= 1000.0:
                raise SettingsError("%s is between 0.01 and 1000." % k)
            out[k] = f
    return out


def get(d) -> dict:
    out = copy.deepcopy(DEFAULTS)
    saved = d.header.get(KEY)
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in out:
                out[k] = copy.deepcopy(v)
    return out


def put(d, changes: dict) -> dict:
    new = clean(changes)
    cur = get(d)
    cur.update(new)
    d.set_header(KEY, cur)
    return cur
