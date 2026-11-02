import math
import re
from decimal import ROUND_HALF_UP, Decimal

TAU = 2 * math.pi
_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_PLAIN = re.compile("^" + _NUM + "$")
_UNSIGNED = r"\d+(?:\.\d+)?"
_FEET_INCH = re.compile(r"^(?P<neg>-)?(?:(?P<ft>" + _UNSIGNED + r")')?(?:-?\s*(?P<whole>" + _UNSIGNED + r")?(?:[\s-]+(?P<n1>\d+)/(?P<d1>\d+)|(?P<n2>\d+)/(?P<d2>\d+))?)?\"?$")
_DMS = re.compile(r"^(?P<neg>-)?(?P<d>" + _UNSIGNED + r")d(?:(?P<m>\d+(?:\.\d+)?)')?(?:(?P<s>\d+(?:\.\d+)?)\")?$", re.I)
_BEARING = re.compile(r"^(?P<ns>[ns])(?:\s*(?P<d>" + _UNSIGNED + r")d(?:(?P<m>\d+(?:\.\d+)?)')?(?:(?P<s>\d+(?:\.\d+)?)\")?)?\s*(?P<ew>[ew])$", re.I)


def round_half_away(value: float, places: int) -> Decimal:
    if not math.isfinite(value):
        return Decimal(0)
    d = Decimal(repr(float("%.15g" % value)))
    q = Decimal(1).scaleb(-places)
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    if r == 0:
        r = abs(r)
    return r


def _fixed(value: float, places: int) -> str:
    r = round_half_away(value, places)
    s = format(r, "f")
    if s.startswith("-") and Decimal(s) == 0:
        s = s[1:]
    return s


def _frac_str(frac: float, denom: int):
    n = int(round(frac * denom))
    if n >= denom:
        return None, True
    if n == 0:
        return "", False
    d = denom
    while n % 2 == 0 and d % 2 == 0:
        n //= 2
        d //= 2
    return "%d/%d" % (n, d), False


def format_distance(value: float, lunits: int = 2, luprec: int = 4) -> str:
    if not math.isfinite(value):
        return "0"
    if abs(value) > 9e18:
        lunits = 2
    neg = value < 0
    v = abs(value)
    prec = max(0, min(8, int(luprec)))
    if lunits == 1:
        if v == 0:
            exp = 0
            mant = 0.0
        else:
            exp = int(math.floor(math.log10(v)))
            mant = v / (10 ** exp)
            if float(round_half_away(mant, prec)) >= 10:
                exp += 1
                mant = v / (10 ** exp)
        sign = "-" if exp < 0 else "+"
        out = "%sE%s%02d" % (_fixed(mant, prec), sign, abs(exp))
    elif lunits == 3:
        out = _feet_inches(v, prec, False)
    elif lunits == 4:
        out = _feet_inches(v, prec, True)
    elif lunits == 5:
        denom = min(256, 2 ** prec)
        whole = int(math.floor(v + 1e-12))
        fs, carry = _frac_str(v - whole, denom)
        if carry:
            whole += 1
            fs = ""
        out = str(whole) + (" " + fs if fs else "") if (whole or not fs) else fs
    else:
        out = _fixed(v, prec)
    if neg and out.strip("0.-+E ") not in ("",):
        return "-" + out
    return out


def _feet_inches(v: float, prec: int, arch: bool) -> str:
    feet = int(math.floor(v / 12.0 + 1e-12))
    inches = v - feet * 12.0
    if arch:
        denom = min(256, 2 ** prec) if prec > 0 else 1
        whole = int(math.floor(inches + 1e-12))
        fs, carry = _frac_str(inches - whole, denom)
        if carry:
            whole += 1
            fs = ""
        if whole >= 12:
            feet += 1
            whole -= 12
        txt = str(whole) + (" " + fs if fs else "") if (whole or not fs) else fs
        return "%d'-%s\"" % (feet, txt)
    s = _fixed(inches, prec)
    if float(s) >= 12:
        feet += 1
        s = _fixed(0.0, prec)
    return "%d'-%s\"" % (feet, s)


def format_angle(rad: float, aunits: int = 0, aprec: int = 0) -> str:
    if not math.isfinite(rad):
        return "0"
    prec = max(0, min(8, int(aprec)))
    if aunits == 3:
        return _fixed(rad, prec) + "r"
    deg = math.degrees(rad)
    if aunits == 2:
        g = deg * 400.0 / 360.0
        s = _fixed(g % 400.0, prec)
        if float(s) >= 400:
            s = _fixed(0.0, prec)
        return s + "g"
    deg = deg % 360.0
    if aunits == 1:
        return _dms(deg, prec)
    if aunits == 4:
        return _bearing(deg, prec)
    s = _fixed(deg, prec)
    if float(s) >= 360:
        s = _fixed(0.0, prec)
    return s


def _dms(deg: float, prec: int) -> str:
    if prec == 0:
        d = int(round_half_away(deg, 0))
        return "%dd" % (d % 360)
    if prec <= 2:
        total_min = int(round_half_away(deg * 60.0, 0))
        d, m = divmod(total_min, 60)
        return "%dd%d'" % (d % 360, m)
    dec = prec - 4 if prec > 4 else 0
    scale = 10 ** dec
    total = int(round_half_away(deg * 3600.0 * scale, 0))
    secs_units = total
    d, rem = divmod(secs_units, 3600 * scale)
    m, srem = divmod(rem, 60 * scale)
    sec = srem / scale
    sec_txt = ("%.*f" % (dec, sec)) if dec else "%d" % sec
    return "%dd%d'%s\"" % (d % 360, m, sec_txt)


def _bearing(deg: float, prec: int) -> str:
    if abs(deg - 90) < 1e-9 and prec > 0:
        return "N"
    if abs(deg - 270) < 1e-9 and prec > 0:
        return "S"
    if abs(deg) < 1e-9 and prec > 0:
        return "E"
    if abs(deg - 180) < 1e-9 and prec > 0:
        return "W"
    if 0 <= deg <= 180:
        ns = "N"
        from_ns = abs(90 - deg)
        ew = "E" if deg <= 90 else "W"
    else:
        ns = "S"
        from_ns = abs(270 - deg)
        ew = "E" if deg >= 270 else "W"
    return "%s %s %s" % (ns, _dms(from_ns, prec), ew)


def _frac(n: str, d: str):
    nn, dd = int(n), int(d)
    if dd == 0:
        return None
    return nn / dd


def parse_distance(text: str):
    s = text.strip()
    if not s:
        return None
    if _PLAIN.match(s):
        v = float(s)
        return v if math.isfinite(v) else None
    m = _FEET_INCH.match(s)
    if not m or not any((m.group("ft"), m.group("whole"), m.group("n1"), m.group("n2"))):
        return None
    if m.group("ft") is None and "'" in s:
        return None
    total = 0.0
    if m.group("ft"):
        total += float(m.group("ft")) * 12.0
    if m.group("whole"):
        total += float(m.group("whole"))
    if m.group("n1"):
        f = _frac(m.group("n1"), m.group("d1"))
        if f is None:
            return None
        total += f
    if m.group("n2"):
        f = _frac(m.group("n2"), m.group("d2"))
        if f is None:
            return None
        total += f
    if m.group("neg"):
        total = -total
    return total if math.isfinite(total) else None


def _dms_value(m) -> float:
    deg = float(m.group("d"))
    mi = float(m.group("m") or 0)
    se = float(m.group("s") or 0)
    if mi > 60 or se > 60:
        raise ValueError("minutes and seconds run 0 to 60")
    return deg + mi / 60.0 + se / 3600.0


def parse_angle(text: str, aunits: int = 0):
    s = text.strip()
    if not s:
        return None
    neg = False
    if s.startswith("-"):
        neg = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    val = None
    low = s.lower()
    if _PLAIN.match(s):
        n = float(s)
        if aunits == 3:
            val = n
        elif aunits == 2:
            val = math.radians(n * 360.0 / 400.0)
        else:
            val = math.radians(n)
    elif low.endswith("r") and _PLAIN.match(low[:-1]):
        val = float(low[:-1])
    elif low.endswith("g") and _PLAIN.match(low[:-1]):
        val = math.radians(float(low[:-1]) * 360.0 / 400.0)
    else:
        m = _BEARING.match(s)
        if m:
            ns = m.group("ns").upper()
            ew = m.group("ew").upper()
            if m.group("d") is None:
                return None
            a = _dms_value(m)
            if a > 90:
                raise ValueError("a bearing runs 0 to 90 within a quadrant")
            base = 90.0 if ns == "N" else 270.0
            toward = a if (ns == "N" and ew == "W") or (ns == "S" and ew == "E") else -a
            val = math.radians((base + toward) % 360.0)
        else:
            m = _DMS.match(s)
            if m:
                val = math.radians(_dms_value(m))
                if m.group("neg"):
                    neg = not neg
            elif low in ("n", "e", "s", "w"):
                val = math.radians({"n": 90.0, "e": 0.0, "s": 270.0, "w": 180.0}[low])
    if val is None:
        return None
    return -val if neg else val


def direction_from_angle(angle: float, angbase: float, angdir: int) -> float:
    return angbase + (-angle if angdir else angle)


def angle_for_display(direction: float, angbase: float, angdir: int) -> float:
    a = direction - angbase
    if angdir:
        a = -a
    return a % TAU
