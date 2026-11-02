LENGTH_MM = {
    "um": 0.001, "mil": 0.0254, "thou": 0.0254, "mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0, "km": 1e6,
    "in": 25.4, "ft": 304.8, "yd": 914.4, "mi": 1609344.0,
}
ANGLE_DEG = {"deg": 1.0, "rad": 57.29577951308232, "grad": 0.9, "turn": 360.0}
INSUNITS_MM = {1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0, 6: 1000.0, 7: 1e6, 9: 0.0254, 10: 914.4, 14: 100.0}


def unit_names() -> set:
    return set(LENGTH_MM) | set(ANGLE_DEG)


def mm_per_unit(d) -> float:
    code = int(d.header.get("INSUNITS", 0) or 0)
    if code in INSUNITS_MM:
        return INSUNITS_MM[code]
    return 1.0 if d.metric else 25.4


def factor(d, unit: str) -> float:
    u = unit.lower()
    if u in LENGTH_MM:
        return LENGTH_MM[u] / mm_per_unit(d)
    if u in ANGLE_DEG:
        return ANGLE_DEG[u]
    raise KeyError(unit)


def is_unit(unit: str) -> bool:
    return unit.lower() in LENGTH_MM or unit.lower() in ANGLE_DEG


def to_base(d, value: float, unit: str) -> float:
    return value * factor(d, unit) if unit else value


def from_base(d, value: float, unit: str) -> float:
    return value / factor(d, unit) if unit else value


def format_value(v: float, places: int = 6) -> str:
    text = ("%." + str(places) + "f") % v
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
