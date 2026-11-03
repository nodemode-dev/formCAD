import math

PATTERNS = ("rectilinear", "grid", "gyroid", "gyroid_waves")
SEAMS = ("nearest", "corner")
WALL_ORDERS = ("inner_first", "outer_first")
SUPPORT_STYLES = ("lines", "block")
FLAVOURS = ("marlin",)
START_MAX = 4000

DEFAULT_START = """M140 S{bed_temp}
M104 S{first_nozzle_temp}
G28
M190 S{bed_temp}
M109 S{first_nozzle_temp}
G90
M83
G92 E0
G1 Z2 F{travel_mm_min}
G1 X{prime_x} Y{prime_y} F{travel_mm_min}
G1 Z{first_layer_height} F600
G1 X{prime_x2} Y{prime_y} E8 F600
G92 E0"""

DEFAULT_END = """M104 S0
M140 S0
M107
G91
G1 Z5 F600
G90
G1 X0 Y{bed_y} F{travel_mm_min}
M84"""

SPEC = [
    ("nozzle", "number", 0.4, 0.1, 1.2, "mm", "printer", "Nozzle diameter"),
    ("filament_diameter", "number", 1.75, 1.0, 3.2, "mm", "printer", "Filament diameter"),
    ("bed", "vec2", [220.0, 220.0], 20.0, 1000.0, "mm", "printer", "Bed size"),
    ("max_height", "number", 250.0, 5.0, 1000.0, "mm", "printer", "Build height"),
    ("flavour", "choice", "marlin", None, None, "", "printer", "G-code dialect"),
    ("acceleration", "number", 1000.0, 50.0, 20000.0, "mm/s2", "printer", "Acceleration for the time estimate"),
    ("firmware_retraction", "bool", False, None, None, "", "printer", "Use G10 and G11 for retraction"),
    ("layer_height", "number", 0.2, 0.04, 1.0, "mm", "layers", "Layer height"),
    ("first_layer_height", "number", 0.3, 0.05, 1.2, "mm", "layers", "First layer height"),
    ("line_width", "number", 0.45, 0.1, 2.0, "mm", "layers", "Line width"),
    ("outer_width", "number", 0.45, 0.1, 2.0, "mm", "layers", "Outer wall width"),
    ("first_layer_width", "number", 0.5, 0.1, 2.0, "mm", "layers", "First layer line width"),
    ("perimeters", "int", 2, 0, 12, "", "shells", "Wall count"),
    ("top_layers", "int", 5, 0, 40, "", "shells", "Top solid layers"),
    ("bottom_layers", "int", 4, 0, 40, "", "shells", "Bottom solid layers"),
    ("wall_order", "choice", "inner_first", None, None, "", "shells", "Wall order"),
    ("seam", "choice", "nearest", None, None, "", "shells", "Seam position"),
    ("seam_point", "vec2", [0.0, 1000.0], -5000.0, 5000.0, "mm", "shells", "Seam target on the plate"),
    ("thin_walls", "bool", True, None, None, "", "shells", "Fill thin walls with a centre line"),
    ("infill_pattern", "choice", "gyroid", None, None, "", "infill", "Infill pattern"),
    ("infill_density", "number", 20.0, 0.0, 100.0, "%", "infill", "Infill density"),
    ("infill_angle", "number", 45.0, 0.0, 180.0, "deg", "infill", "Infill angle"),
    ("infill_overlap", "number", 15.0, 0.0, 50.0, "%", "infill", "Infill overlap with walls"),
    ("solid_area", "number", 12.0, 0.0, 500.0, "mm2", "infill", "Fill regions smaller than this solid"),
    ("flow", "number", 1.0, 0.5, 1.5, "", "extrusion", "Flow multiplier"),
    ("bridge_flow", "number", 1.0, 0.5, 1.5, "", "extrusion", "Bridge flow multiplier"),
    ("bridge_max_span", "number", 25.0, 2.0, 200.0, "mm", "supports", "Longest span printed as a bridge"),
    ("support", "bool", True, None, None, "", "supports", "Generate supports"),
    ("support_angle", "number", 45.0, 10.0, 80.0, "deg", "supports", "Overhang angle from vertical that needs support"),
    ("support_style", "choice", "lines", None, None, "", "supports", "Support style"),
    ("support_bridges", "bool", False, None, None, "", "supports", "Also support spans that can be bridged"),
    ("support_xy_gap", "number", 0.4, 0.0, 5.0, "mm", "supports", "Support to part gap sideways"),
    ("support_z_layers", "int", 1, 0, 6, "", "supports", "Support to part gap in layers"),
    ("support_density", "number", 15.0, 5.0, 100.0, "%", "supports", "Support density"),
    ("support_interface_layers", "int", 2, 0, 8, "", "supports", "Dense interface layers under overhangs"),
    ("support_walls", "int", 1, 0, 3, "", "supports", "Support outline loops"),
    ("support_min_area", "number", 1.5, 0.0, 200.0, "mm2", "supports", "Ignore overhangs smaller than this"),
    ("support_teeth", "number", 0.8, 0.0, 5.0, "mm", "supports", "Block support tooth pitch (0 for solid)"),
    ("skirt_loops", "int", 1, 0, 10, "", "adhesion", "Skirt loops"),
    ("skirt_distance", "number", 3.0, 0.0, 50.0, "mm", "adhesion", "Skirt distance"),
    ("brim_width", "number", 0.0, 0.0, 30.0, "mm", "adhesion", "Brim width"),
    ("speed_outer", "number", 30.0, 3.0, 400.0, "mm/s", "speeds", "Outer wall speed"),
    ("speed_inner", "number", 45.0, 3.0, 400.0, "mm/s", "speeds", "Inner wall speed"),
    ("speed_infill", "number", 60.0, 3.0, 400.0, "mm/s", "speeds", "Sparse infill speed"),
    ("speed_solid", "number", 45.0, 3.0, 400.0, "mm/s", "speeds", "Solid infill and skin speed"),
    ("speed_bridge", "number", 20.0, 3.0, 400.0, "mm/s", "speeds", "Bridge speed"),
    ("speed_support", "number", 50.0, 3.0, 400.0, "mm/s", "speeds", "Support speed"),
    ("speed_first_layer", "number", 20.0, 3.0, 400.0, "mm/s", "speeds", "First layer speed"),
    ("speed_travel", "number", 150.0, 10.0, 600.0, "mm/s", "speeds", "Travel speed"),
    ("min_layer_time", "number", 6.0, 0.0, 120.0, "s", "cooling", "Slow a layer down to take at least this long"),
    ("min_speed", "number", 10.0, 3.0, 100.0, "mm/s", "cooling", "Slowest speed the cooling slow-down may reach"),
    ("fan", "number", 100.0, 0.0, 100.0, "%", "cooling", "Fan speed"),
    ("bridge_fan", "number", 100.0, 0.0, 100.0, "%", "cooling", "Fan speed on bridges"),
    ("fan_start_layer", "int", 2, 0, 50, "", "cooling", "Layer where the fan starts"),
    ("nozzle_temp", "number", 205.0, 100.0, 450.0, "C", "temperatures", "Nozzle temperature"),
    ("first_nozzle_temp", "number", 210.0, 100.0, 450.0, "C", "temperatures", "First layer nozzle temperature"),
    ("bed_temp", "number", 60.0, 0.0, 200.0, "C", "temperatures", "Bed temperature"),
    ("retract_length", "number", 1.0, 0.0, 15.0, "mm", "retraction", "Retraction length"),
    ("retract_speed", "number", 35.0, 1.0, 200.0, "mm/s", "retraction", "Retraction speed"),
    ("retract_lift", "number", 0.2, 0.0, 5.0, "mm", "retraction", "Lift on retraction"),
    ("retract_min_travel", "number", 1.5, 0.0, 50.0, "mm", "retraction", "Shortest travel that retracts"),
    ("start_gcode", "text", DEFAULT_START, None, None, "", "gcode", "Start G-code"),
    ("end_gcode", "text", DEFAULT_END, None, None, "", "gcode", "End G-code"),
]

CHOICES = {"infill_pattern": PATTERNS, "seam": SEAMS, "wall_order": WALL_ORDERS, "support_style": SUPPORT_STYLES, "flavour": FLAVOURS}
KEYS = {row[0]: row for row in SPEC}

PRESETS = {
    "draft": {"layer_height": 0.3, "first_layer_height": 0.3, "infill_density": 12.0, "perimeters": 2, "top_layers": 4, "bottom_layers": 3, "speed_infill": 80.0, "speed_inner": 60.0, "infill_pattern": "rectilinear"},
    "standard": {},
    "fine": {"layer_height": 0.12, "first_layer_height": 0.2, "infill_density": 20.0, "perimeters": 3, "top_layers": 7, "bottom_layers": 6, "speed_outer": 25.0, "speed_inner": 35.0, "speed_infill": 50.0},
    "metal": {"layer_height": 0.05, "first_layer_height": 0.1, "support": True, "support_style": "block", "support_angle": 45.0, "support_density": 100.0, "support_xy_gap": 0.2, "support_z_layers": 0, "support_interface_layers": 3, "support_teeth": 1.0, "support_bridges": True, "perimeters": 1, "infill_density": 100.0, "infill_pattern": "rectilinear"},
}


class SettingError(ValueError):
    pass


def defaults() -> dict:
    return {row[0]: (list(row[2]) if isinstance(row[2], list) else row[2]) for row in SPEC}


def describe() -> dict:
    out = {}
    for key, kind, dflt, lo, hi, unit, group, label in SPEC:
        row = {"default": dflt, "kind": kind, "unit": unit, "group": group, "label": label}
        if lo is not None:
            row["min"] = lo
        if hi is not None:
            row["max"] = hi
        if key in CHOICES:
            row["choices"] = list(CHOICES[key])
        out[key] = row
    return out


def clean_one(key: str, value):
    if key not in KEYS:
        raise SettingError("There is no slicer setting named %s." % key)
    _, kind, dflt, lo, hi, _unit, _group, label = KEYS[key]
    if kind == "bool":
        if not isinstance(value, bool):
            raise SettingError("%s is on or off." % label)
        return value
    if kind == "choice":
        if value not in CHOICES[key]:
            raise SettingError("%s is one of: %s." % (label, ", ".join(CHOICES[key])))
        return value
    if kind == "text":
        text = str(value if value is not None else "")
        if len(text) > START_MAX or "\x00" in text:
            raise SettingError("%s is at most %d characters." % (label, START_MAX))
        return text
    if kind == "vec2":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise SettingError("%s is two numbers." % label)
        out = []
        for v in value:
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise SettingError("%s is two numbers." % label)
            if not math.isfinite(x) or x < lo or x > hi:
                raise SettingError("%s must be between %g and %g." % (label, lo, hi))
            out.append(x)
        return out
    if isinstance(value, bool):
        raise SettingError("%s needs a number." % label)
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise SettingError("%s needs a number." % label)
    if not math.isfinite(x) or x < lo or x > hi:
        raise SettingError("%s must be between %g and %g." % (label, lo, hi))
    return int(round(x)) if kind == "int" else x


def clean(values: dict, base: dict | None = None) -> dict:
    out = defaults()
    if base:
        out.update(base)
    for key, value in (values or {}).items():
        out[key] = clean_one(key, value)
    cross(out)
    return out


def cross(s: dict) -> None:
    if s["first_layer_height"] < s["layer_height"] * 0.5:
        raise SettingError("The first layer height must be at least half the layer height.")
    if s["layer_height"] > s["nozzle"] * 0.85:
        raise SettingError("The layer height must stay under 85 percent of the nozzle diameter.")
    if s["first_layer_height"] > s["nozzle"] * 0.9:
        raise SettingError("The first layer height must stay under 90 percent of the nozzle diameter.")
    for key in ("line_width", "outer_width", "first_layer_width"):
        if s[key] < s["nozzle"] * 0.8 or s[key] > s["nozzle"] * 2.0:
            raise SettingError("%s must be between 0.8 and 2 times the nozzle diameter." % KEYS[key][7])
    if s["layer_height"] >= s["line_width"]:
        raise SettingError("The layer height must be smaller than the line width.")


def preset(name: str) -> dict:
    if name not in PRESETS:
        raise SettingError("A preset is one of: %s." % ", ".join(PRESETS))
    return clean(PRESETS[name])
