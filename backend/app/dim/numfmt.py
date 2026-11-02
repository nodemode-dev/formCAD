import math
from decimal import ROUND_HALF_UP, Decimal

from app.cmd import units


def fixed(value: float, places: int) -> str:
    places = max(0, min(16, int(places)))
    q = Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    if s.startswith("-") and float(s) == 0.0:
        s = s[1:]
    return s


def round_to(value: float, inc: float) -> float:
    if inc is None or inc <= 0:
        return value
    steps = math.floor(abs(value) / inc + 0.5 + 1e-12)
    out = steps * inc
    return -out if value < 0 else out


def suppress(s: str, zin: int) -> str:
    neg = s.startswith("-")
    body = s[1:] if neg else s
    if "." in body:
        if zin & 8:
            body = body.rstrip("0")
            if body.endswith("."):
                body = body[:-1]
        if zin & 4 and body.startswith("0."):
            body = body[1:]
    if body == "":
        body = "0"
    return ("-" if neg else "") + body


def separator(s: str, dsep: str) -> str:
    d = str(dsep or ".")[:1]
    return s.replace(".", d) if d != "." else s


def grouped(s: str, mark: str = ",") -> str:
    neg = s.startswith("-")
    body = s[1:] if neg else s
    whole, dot, frac = body.partition(".")
    out = []
    while len(whole) > 3:
        out.insert(0, whole[-3:])
        whole = whole[:-3]
    out.insert(0, whole)
    return ("-" if neg else "") + mark.join(out) + dot + frac


def _fraction(frac: float, denom: int):
    num = int(round(frac * denom))
    if num >= denom:
        return None, True
    if num == 0:
        return "", False
    g = math.gcd(num, denom)
    return (num // g, denom // g), False


def _frac_pieces(whole: str, fr, mode: int, tail: str = "", head: str = ""):
    if fr is None or fr == "":
        return [("t", head + whole + tail)]
    n, d = fr
    if mode == 2:
        text = ("%s %d/%d" % (whole, n, d)) if whole else "%d/%d" % (n, d)
        return [("t", head + text + tail)]
    out = []
    if whole:
        out.append(("t", head + whole + (" " if mode == 2 else "")))
    elif head:
        out.append(("t", head))
    out.append(("f", str(n), str(d), mode == 1))
    if tail:
        out.append(("t", tail))
    return out


def decimal_text(value: float, dec: int, zin: int, dsep: str, grouping: bool = False) -> str:
    s = fixed(value, dec)
    s = suppress(s, zin)
    if not grouping:
        return separator(s, dsep)
    d = str(dsep or ".")[:1]
    neg = s.startswith("-")
    body = s[1:] if neg else s
    whole, dot, frac = body.partition(".")
    return ("-" if neg else "") + grouped(whole, "." if d == "," else ",") + (d + frac if dot else "")


def scientific_text(value: float, dec: int, zin: int, dsep: str) -> str:
    neg = value < 0
    v = abs(value)
    if v == 0:
        exp = 0
        mant = 0.0
    else:
        exp = int(math.floor(math.log10(v)))
        mant = v / (10 ** exp)
        if float(fixed(mant, dec)) >= 10:
            exp += 1
            mant = v / (10 ** exp)
    m = suppress(fixed(mant, dec), zin)
    m = separator(m, dsep)
    out = "%sE%s%02d" % (m, "-" if exp < 0 else "+", abs(exp))
    return ("-" if neg else "") + out


def feet_inches(value: float, arch: bool, dec: int, zin: int, dsep: str, frac_mode: int):
    neg = value < 0
    v = abs(value)
    feet = int(math.floor(v / 12.0 + 1e-12))
    inches = v - feet * 12.0
    fr = None
    whole = ""
    if arch:
        denom = max(1, min(256, 2 ** max(0, int(dec))))
        w = int(math.floor(inches + 1e-12))
        fr, carry = _fraction(inches - w, denom)
        if carry:
            w += 1
            fr = ""
        if w >= 12:
            feet += 1
            w -= 12
        whole = str(w)
        in_zero = w == 0 and not fr
        in_text = None
    else:
        s = fixed(inches, dec)
        if float(s) >= 12:
            feet += 1
            s = fixed(0.0, dec)
        in_zero = float(s) == 0.0
        in_text = separator(suppress(s, zin & 12), dsep)
    z = zin & 3
    show_feet = feet != 0 or z in (1, 2)
    show_in = (not in_zero) or z in (1, 3)
    if feet == 0 and z in (0, 2) and not show_in and in_zero:
        show_feet = False
    pieces = []
    prefix = "-" if neg else ""
    if arch:
        if show_in:
            if fr and whole == "0":
                body = _frac_pieces("", fr, frac_mode)
            else:
                body = _frac_pieces(whole, fr, frac_mode)
            body = body + [("t", "\"")]
        else:
            body = []
        head = prefix + ("%d'" % feet if show_feet else "")
        if show_feet and show_in:
            head += "-"
        if not show_feet and not show_in:
            return [("t", prefix + "0")]
        if body and body[0][0] == "t":
            body[0] = ("t", head + body[0][1])
        else:
            body.insert(0, ("t", head))
        return body
    parts = prefix + ("%d'" % feet if show_feet else "")
    if show_in:
        parts += ("-" if show_feet else "") + in_text + "\""
    if not show_feet and not show_in:
        parts = prefix + "0"
    return [("t", parts)]


def linear(value: float, lunit: int, dec: int, zin: int, dsep: str, frac_mode: int):
    if lunit == 1:
        return [("t", scientific_text(value, dec, zin, dsep))]
    if lunit in (3, 4):
        return feet_inches(value, lunit == 4, dec, zin, dsep, frac_mode)
    if lunit == 5:
        neg = value < 0
        v = abs(value)
        denom = max(1, min(256, 2 ** max(0, int(dec))))
        w = int(math.floor(v + 1e-12))
        fr, carry = _fraction(v - w, denom)
        if carry:
            w += 1
            fr = ""
        whole = str(w) if (w or not fr) else ""
        return _frac_pieces(whole, fr, frac_mode, head="-" if neg else "")
    return [("t", decimal_text(value, dec, zin, dsep, lunit == 6))]


def plain(pieces) -> str:
    out = []
    for p in pieces:
        if p[0] == "t":
            out.append(p[1])
        else:
            out.append("%s/%s" % (p[1], p[2]))
    return "".join(out)


def affix(pieces, template: str):
    if not template:
        return list(pieces)
    if "<>" in template:
        pre, _, post = template.partition("<>")
    else:
        pre, post = "", template
    out = []
    if pre:
        out.append(("t", pre))
    out.extend(pieces)
    if post:
        out.append(("t", post))
    return out


def prefix_pieces(pieces, symbol: str):
    if not pieces:
        return [("t", symbol)]
    first = pieces[0]
    if first[0] == "t":
        neg = first[1].startswith("-")
        body = first[1][1:] if neg else first[1]
        return [("t", ("-" if neg else "") + symbol + body)] + list(pieces[1:])
    return [("t", symbol)] + list(pieces)


def angular(rad: float, aunit: int, adec: int, azin: int) -> str:
    adec = max(0, min(8, int(adec)))
    deg = math.degrees(rad)
    if aunit == 3:
        s = fixed(rad, adec)
        return _angle_zero(s, azin) + "r"
    if aunit == 2:
        g = deg * 400.0 / 360.0
        s = fixed(g, adec)
        return _angle_zero(s, azin) + "g"
    if aunit == 1:
        return _dms_text(deg, adec, azin)
    if aunit == 4:
        txt = units.format_angle(rad, 4, adec)
        return txt.replace("d", "°")
    s = fixed(deg, adec)
    return _angle_zero(s, azin) + "°"


def _angle_zero(s: str, azin: int) -> str:
    z = 0
    if azin & 1:
        z |= 4
    if azin & 2:
        z |= 8
    return suppress(s, z)


def _dms_text(deg: float, adec: int, azin: int) -> str:
    total = abs(deg)
    d = int(math.floor(total + 1e-12))
    rem = (total - d) * 60.0
    if adec <= 0:
        mm = 0
        d = int(math.floor(total + 0.5))
        out = "%d°" % d
        return ("-" if deg < 0 else "") + out
    if adec <= 2:
        m = int(math.floor(rem + 0.5 + 1e-12))
        if m >= 60:
            d += 1
            m = 0
        out = "%d°" % d
        if m or not azin & 2:
            out += "%d'" % m
        return ("-" if deg < 0 else "") + out
    sec = (rem - math.floor(rem + 1e-12)) * 60.0
    m = int(math.floor(rem + 1e-12))
    places = max(0, adec - 4)
    s = fixed(sec, places)
    if float(s) >= 60.0:
        s = fixed(0.0, places)
        m += 1
        if m >= 60:
            m = 0
            d += 1
    if azin & 2:
        s = suppress(s, 8)
    out = "%d°%d'%s\"" % (d, m, s)
    return ("-" if deg < 0 else "") + out
