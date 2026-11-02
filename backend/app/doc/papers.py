import math
import re

MAX_SIDE_MM = 5080.0
MAX_RECORD_MM = 100000.0
DEFAULT_PORTRAIT = (215.9, 279.4)
INCH = 25.4

ISO = [("A0", 841.0, 1189.0), ("A1", 594.0, 841.0), ("A2", 420.0, 594.0), ("A3", 297.0, 420.0), ("A4", 210.0, 297.0), ("A5", 148.0, 210.0), ("A6", 105.0, 148.0), ("B0", 1000.0, 1414.0), ("B1", 707.0, 1000.0), ("B2", 500.0, 707.0), ("B3", 353.0, 500.0), ("B4", 250.0, 353.0), ("B5", 176.0, 250.0)]
INCHES = [("ANSI A", 8.5, 11.0, ("letter",)), ("Legal", 8.5, 14.0, ("ansi legal",)), ("ANSI B", 11.0, 17.0, ("tabloid", "ledger")), ("ANSI C", 17.0, 22.0, ()), ("ANSI D", 22.0, 34.0, ()), ("ANSI E", 34.0, 44.0, ()), ("ARCH A", 9.0, 12.0, ()), ("ARCH B", 12.0, 18.0, ()), ("ARCH C", 18.0, 24.0, ()), ("ARCH D", 24.0, 36.0, ()), ("ARCH E1", 30.0, 42.0, ()), ("ARCH E", 36.0, 48.0, ())]


def fold(text) -> str:
    return re.sub(r"[\s_\-]+", "", str(text)).casefold()


def _canon_iso(short: str, w: float, h: float) -> str:
    return "ISO %s (%.2f x %.2f MM)" % (short, w, h)


def _canon_inch(short: str, w: float, h: float) -> str:
    return "%s (%.2f x %.2f Inches)" % (short, w, h)


def _build() -> list:
    out = []
    for short, w, h in ISO:
        out.append({"name": _canon_iso(short, w, h), "short": "ISO " + short, "width": w, "height": h, "aliases": [short, "ISO " + short]})
    for short, w, h, extra in INCHES:
        out.append({"name": _canon_inch(short, w, h), "short": short, "width": round(w * INCH, 2), "height": round(h * INCH, 2), "aliases": [short] + [e for e in extra]})
    return out


SIZES = _build()
_INDEX: dict = {}
for _rec in SIZES:
    _INDEX[fold(_rec["name"])] = _rec
    for _a in _rec["aliases"]:
        _INDEX.setdefault(fold(_a), _rec)


def custom_name(width: float, height: float) -> str:
    return "User (%.2f x %.2f MM)" % (width, height)


_CUSTOM = re.compile(r"^user\s*\(\s*([0-9.]+)\s*x\s*([0-9.]+)\s*mm\s*\)$", re.I)
_PLAIN = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*[x,*]\s*([0-9]*\.?[0-9]+)\s*(mm)?\s*$", re.I)


def lookup(text):
    t = str(text or "").strip()
    if not t:
        return None
    rec = _INDEX.get(fold(t))
    if rec is not None:
        return {"name": rec["name"], "width": rec["width"], "height": rec["height"], "custom": False}
    m = _CUSTOM.match(t) or _PLAIN.match(t)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if sane(w, h):
            return {"name": custom_name(min(w, h), max(w, h)), "width": min(w, h), "height": max(w, h), "custom": True}
    return None


def sane(width, height, limit: float = MAX_SIDE_MM) -> bool:
    try:
        w, h = float(width), float(height)
    except (TypeError, ValueError):
        return False
    return math.isfinite(w) and math.isfinite(h) and 0 < w <= limit and 0 < h <= limit


def clamp_record(width, height) -> tuple:
    try:
        w, h = float(width), float(height)
    except (TypeError, ValueError):
        return DEFAULT_PORTRAIT
    if not (math.isfinite(w) and math.isfinite(h)) or w <= 0 or h <= 0:
        return DEFAULT_PORTRAIT
    return min(w, MAX_RECORD_MM), min(h, MAX_RECORD_MM)


def name_for_size(width: float, height: float) -> str:
    lo, hi = min(width, height), max(width, height)
    for rec in SIZES:
        if abs(rec["width"] - lo) < 0.6 and abs(rec["height"] - hi) < 0.6:
            return rec["name"]
    return custom_name(lo, hi)


def listing() -> list:
    return [{"name": r["name"], "short": r["short"], "width": r["width"], "height": r["height"]} for r in SIZES]
