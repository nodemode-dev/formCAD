import math

TABLE = {
    "length": {"um": 1e-6, "mm": 1e-3, "cm": 1e-2, "dm": 1e-1, "m": 1.0, "km": 1000.0, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344, "nmi": 1852.0},
    "area": {"mm2": 1e-6, "cm2": 1e-4, "m2": 1.0, "ha": 1e4, "km2": 1e6, "in2": 0.00064516, "ft2": 0.09290304, "yd2": 0.83612736, "acre": 4046.8564224, "mi2": 2589988.110336},
    "volume": {"mm3": 1e-9, "cm3": 1e-6, "ml": 1e-6, "l": 1e-3, "m3": 1.0, "in3": 1.6387064e-5, "ft3": 0.028316846592, "yd3": 0.764554857984, "us gallon": 0.003785411784, "uk gallon": 0.00454609},
    "angle": {"deg": math.pi / 180.0, "rad": 1.0, "grad": math.pi / 200.0, "rev": 2.0 * math.pi},
}
ALIASES = {"usgallon": "us gallon", "us_gallon": "us gallon", "usgal": "us gallon", "ukgallon": "uk gallon", "uk_gallon": "uk gallon", "ukgal": "uk gallon", "degree": "deg", "degrees": "deg", "radian": "rad", "radians": "rad", "inch": "in", "feet": "ft", "foot": "ft", "meter": "m", "metre": "m", "litre": "l", "liter": "l"}


class UnitError(Exception):
    pass


def canonical(name: str) -> str:
    s = " ".join(str(name).strip().lower().split())
    return ALIASES.get(s, s)


def kind_of(name: str):
    n = canonical(name)
    for kind, table in TABLE.items():
        if n in table:
            return kind
    return None


def significant(v: float, digits: int = 14) -> float:
    if v == 0 or not math.isfinite(v):
        return v
    return float("%.*e" % (digits - 1, v))


def convert(value: float, src: str, dst: str, kind: str | None = None) -> float:
    a, b = canonical(src), canonical(dst)
    if kind:
        table = TABLE.get(canonical(kind))
        if table is None:
            raise UnitError("unknown unit type %s" % kind)
        kinds = [canonical(kind)]
    else:
        ka, kb = kind_of(a), kind_of(b)
        if ka is None:
            raise UnitError("unknown unit %s" % src)
        if kb is None:
            raise UnitError("unknown unit %s" % dst)
        if ka != kb:
            raise UnitError("cannot convert %s to %s" % (src, dst))
        kinds = [ka]
    table = TABLE[kinds[0]]
    if a not in table:
        raise UnitError("unknown %s unit %s" % (kinds[0], src))
    if b not in table:
        raise UnitError("unknown %s unit %s" % (kinds[0], dst))
    return significant(value * table[a] / table[b])


def listing(kind: str | None = None) -> dict:
    if kind:
        t = TABLE.get(canonical(kind))
        if t is None:
            raise UnitError("unknown unit type %s" % kind)
        return {canonical(kind): list(t)}
    return {k: list(v) for k, v in TABLE.items()}
