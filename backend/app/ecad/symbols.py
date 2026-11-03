import re

from app.ecad.store import ETYPES, MAX_PINS, EcadError

PITCH = 2.54
LEN = 2.54


def _pin(number, name, etype, pos, orient, length=LEN, unit=1, hidden=False):
    return {"number": str(number), "name": str(name), "etype": etype, "pos": [round(pos[0], 4), round(pos[1], 4)], "orient": orient, "length": length, "unit": unit, "hidden": hidden}


def _sym(sid, name, prefix, graphics, pins, footprint="", power=False, units=1, desc="", keywords=()):
    return {"id": sid, "name": name, "description": desc, "prefix": prefix, "power": power, "units": units, "default_footprint": footprint, "keywords": list(keywords), "graphics": graphics, "pins": pins, "source": "builtin"}


def _poly(pts, unit=0):
    return {"t": "line", "pts": [[round(a, 4), round(b, 4)] for a, b in pts], "unit": unit}


def _rect(x0, y0, x1, y1, unit=0):
    return {"t": "rect", "x0": x0, "y0": y0, "x1": x1, "y1": y1, "unit": unit}


def two_pin(sid, name, prefix, body, footprint, desc, keywords=(), etype="passive", names=("~", "~"), numbers=("1", "2")):
    pins = [_pin(numbers[0], names[0], etype, (0, 3.81), "U", 2.54), _pin(numbers[1], names[1], etype, (0, -3.81), "D", 2.54)]
    return _sym(sid, name, prefix, body, pins, footprint, desc=desc, keywords=keywords)


def resistor():
    return two_pin("R", "Resistor", "R", [_rect(-1.016, -1.27, 1.016, 1.27)], "CHIP-0603", "Fixed resistor", ("resistor",))


def capacitor():
    return two_pin("C", "Capacitor", "C", [_poly([(-2.032, 0.508), (2.032, 0.508)]), _poly([(-2.032, -0.508), (2.032, -0.508)]), _poly([(0, 1.27), (0, 0.508)]), _poly([(0, -0.508), (0, -1.27)])], "CHIP-0603", "Capacitor", ("capacitor",))


def polarized():
    s = two_pin("CP", "Polarized capacitor", "C", [_poly([(-2.032, 0.508), (2.032, 0.508)]), {"t": "line", "pts": [[-2.032, -0.508], [-1.0, -0.8], [1.0, -0.8], [2.032, -0.508]], "unit": 0}, _poly([(0, 1.27), (0, 0.508)]), _poly([(0, -0.8), (0, -1.27)]), {"t": "text", "text": "+", "pos": [-1.6, 1.4], "h": 1.27, "unit": 0}], "RADIAL-D5_P2.5", "Polarized capacitor, pin 1 positive", ("capacitor", "electrolytic"))
    return s


def inductor():
    arcs = [{"t": "line", "pts": [[0, 1.27 - 0.635 * i], [0.6, 1.27 - 0.635 * i - 0.3175], [0, 1.27 - 0.635 * i - 0.635]], "unit": 0} for i in range(4)]
    return two_pin("L", "Inductor", "L", arcs, "CHIP-0805", "Inductor", ("inductor",))


def diode():
    return two_pin("D", "Diode", "D", [_poly([(-1.27, 1.27), (1.27, 1.27), (0, -1.27), (-1.27, 1.27)]), _poly([(-1.27, -1.27), (1.27, -1.27)])], "CHIP-0805", "Diode, pin 1 cathode, pin 2 anode", ("diode",), names=("K", "A"))


def led():
    return two_pin("LED", "LED", "D", [_poly([(-1.27, 1.27), (1.27, 1.27), (0, -1.27), (-1.27, 1.27)]), _poly([(-1.27, -1.27), (1.27, -1.27)]), _poly([(1.5, 0.5), (2.5, 1.5)]), _poly([(1.9, -0.2), (2.9, 0.8)])], "CHIP-0805", "Light emitting diode, pin 1 cathode, pin 2 anode", ("led",), names=("K", "A"))


def bjt(sid, name, npn):
    body = [_poly([(-0.508, 1.905), (-0.508, -1.905)]), _poly([(-2.54, 0), (-0.508, 0)]), _poly([(-0.508, 0.635), (2.54, 2.54)]), _poly([(-0.508, -0.635), (2.54, -2.54)])]
    pins = [_pin(1, "B", "input", (-5.08, 0), "L"), _pin(2, "C", "passive", (2.54, 5.08), "U", 2.54), _pin(3, "E", "passive", (2.54, -5.08), "D", 2.54)]
    pins[0]["length"] = 2.54
    return _sym(sid, name, "Q", body, pins, "SOT23-3", desc=name, keywords=("transistor",))


def mosfet(sid, name):
    body = [_poly([(-0.508, 1.905), (-0.508, -1.905)]), _poly([(0.254, 2.54), (0.254, 1.27)]), _poly([(0.254, 0.5), (0.254, -0.5)]), _poly([(0.254, -1.27), (0.254, -2.54)]), _poly([(0.254, 1.905), (2.54, 1.905)]), _poly([(0.254, -1.905), (2.54, -1.905)])]
    pins = [_pin(1, "G", "input", (-5.08, 0), "L"), _pin(2, "D", "passive", (2.54, 5.08), "U"), _pin(3, "S", "passive", (2.54, -5.08), "D")]
    return _sym(sid, name, "Q", body, pins, "SOT23-3", desc=name, keywords=("transistor", "mosfet"))


def opamp():
    body = [_poly([(-5.08, 5.08), (-5.08, -5.08), (5.08, 0), (-5.08, 5.08)])]
    pins = [_pin(3, "+", "input", (-7.62, 2.54), "L"), _pin(2, "-", "input", (-7.62, -2.54), "L"), _pin(1, "OUT", "output", (7.62, 0), "R"), _pin(5, "V+", "power_in", (0, 7.62), "U"), _pin(4, "V-", "power_in", (0, -7.62), "D")]
    return _sym("OPAMP", "Operational amplifier", "U", body, pins, "SOT23-5", desc="Single op-amp", keywords=("opamp",))


def power_symbol(name: str, sid: str | None = None):
    sid = sid or name
    gnd = name.upper().startswith("GND") or name.upper() in ("VSS", "0V")
    if gnd:
        body = [_poly([(0, 0), (0, -1.27)]), _poly([(-1.27, -1.27), (1.27, -1.27), (0, -2.54), (-1.27, -1.27)])]
    else:
        body = [_poly([(0, 0), (0, 1.27)]), _poly([(-1.27, 1.27), (1.27, 1.27)]), {"t": "text", "text": "%V", "pos": [0, 2.0], "h": 1.27, "unit": 0}]
    pin = _pin(1, name, "power_out", (0, 0), "U", 0.0)
    s = _sym(sid, "Power " + name, "#PWR", body, [pin], power=True, desc="Power symbol; the net is the part value", keywords=("power",))
    s["default_value"] = name
    return s


def ic(sid: str, name: str, left: list, right: list, top: list | None = None, bottom: list | None = None, prefix="U", footprint="", desc=""):
    top, bottom = top or [], bottom or []
    rows = max(len(left), len(right))
    cols = max(len(top), len(bottom))
    longest = max([len(str(p.get("name", ""))) for p in left + right] + [3])
    half_w = max(3.81, longest * 0.9 + 1.27, (cols + 1) * 1.27 if cols else 0)
    half_w = round(half_w / 1.27 + 0.499) * 1.27
    half_h = (max(rows, 1) * 2.54) / 2 + 1.27
    half_h = round(half_h / 1.27 + 0.499) * 1.27
    pins = []

    def side(items, orient, fixed):
        n = len(items)
        for i, it in enumerate(items):
            if orient in ("L", "R"):
                y = (n - 1) / 2 * PITCH - i * PITCH
                y = round(y / 1.27) * 1.27
                pos = (fixed, y)
            else:
                x = -(n - 1) / 2 * PITCH + i * PITCH
                x = round(x / 1.27) * 1.27
                pos = (x, fixed)
            et = it.get("etype", "passive")
            if et not in ETYPES:
                raise EcadError("Unknown pin type %s." % et)
            pins.append(_pin(it["number"], it.get("name", ""), et, pos, orient, LEN, it.get("unit", 1), bool(it.get("hidden"))))

    side(left, "L", -half_w - LEN)
    side(right, "R", half_w + LEN)
    side(top, "U", half_h + LEN)
    side(bottom, "D", -half_h - LEN)
    if len(pins) > MAX_PINS:
        raise EcadError("That symbol has too many pins.")
    return _sym(sid, name, prefix, [_rect(-half_w, -half_h, half_w, half_h)], pins, footprint, desc=desc, keywords=("ic",))


def parse_pins(spec) -> list:
    out = []
    if isinstance(spec, str):
        for tok in re.split(r"[;\n]+", spec):
            tok = tok.strip()
            if not tok:
                continue
            bits = [b.strip() for b in tok.split(":")]
            if len(bits) < 2:
                raise EcadError("A pin is number:name[:type].")
            out.append({"number": bits[0], "name": bits[1], "etype": bits[2] if len(bits) > 2 and bits[2] else "passive"})
        return out
    for it in spec or []:
        out.append({"number": str(it["number"]), "name": str(it.get("name", "")), "etype": it.get("etype", "passive"), **({"hidden": True} if it.get("hidden") else {})})
    return out


def generic_ic(sid, name, pins: list, prefix="U", footprint="", desc="", split=None):
    n = len(pins)
    k = split if split is not None else (n + 1) // 2
    return ic(sid, name, pins[:k], pins[k:], prefix=prefix, footprint=footprint, desc=desc)


def connector(rows: int, cols: int, sid: str | None = None):
    n = rows * cols
    if rows not in (1, 2) or cols < 1 or n > 80:
        raise EcadError("Connectors are 1 or 2 rows with up to 80 pins.")
    sid = sid or ("CONN_%dx%02d" % (rows, cols))
    h = cols * PITCH
    left, right = [], []
    for c in range(cols):
        y = (cols - 1) / 2 * PITCH - c * PITCH
        y = round(y / 1.27) * 1.27
        if rows == 1:
            right.append((c * 1 + 1, y))
        else:
            left.append((2 * c + 1, y))
            right.append((2 * c + 2, y))
    top = round((h / 2) / 1.27 + 0.499) * 1.27
    if rows == 1:
        body = [_rect(0, -top, 3.81, top)]
        pins = [_pin(num, str(num), "passive", (3.81 + 2.54, y), "R") for num, y in right]
    else:
        pins = [_pin(num, str(num), "passive", (-2.54 - 2.54, y), "L") for num, y in left] + [_pin(num, str(num), "passive", (2.54 + 2.54, y), "R") for num, y in right]
        body = [_rect(-2.54, -top, 2.54, top)]
    fp = "HDR-%dx%02d" % (rows, cols)
    return _sym(sid, "Connector %dx%d" % (rows, cols), "J", body, pins, fp, desc="Pin header connector", keywords=("connector", "header"))


def builtins() -> dict:
    out = {}
    for s in (resistor(), capacitor(), polarized(), inductor(), diode(), led(), bjt("Q_NPN", "NPN transistor", True), bjt("Q_PNP", "PNP transistor", False), mosfet("Q_NMOS", "N-channel MOSFET"), mosfet("Q_PMOS", "P-channel MOSFET"), opamp()):
        out[s["id"]] = s
    for n in ("GND", "VCC", "VDD", "VSS", "+3V3", "+5V", "+12V", "-12V"):
        out["PWR_" + n] = power_symbol(n, "PWR_" + n)
    for cols in (1, 2, 3, 4, 5, 6, 8, 10):
        c = connector(1, cols)
        out[c["id"]] = c
    for cols in (2, 3, 4, 5, 8):
        c = connector(2, cols)
        out[c["id"]] = c
    timer = [
        {"number": "1", "name": "GND", "etype": "power_in"}, {"number": "2", "name": "TRIG", "etype": "input"}, {"number": "3", "name": "OUT", "etype": "output"}, {"number": "4", "name": "RESET", "etype": "input"},
        {"number": "8", "name": "VCC", "etype": "power_in"}, {"number": "7", "name": "DIS", "etype": "open_collector"}, {"number": "6", "name": "THR", "etype": "input"}, {"number": "5", "name": "CTRL", "etype": "input"},
    ]
    out["TIMER_8"] = ic("TIMER_8", "Timer, 8 pin", timer[:4], timer[4:], prefix="U", footprint="SOIC-8", desc="Generic 8-pin timer: left pins 1 to 4, right pins 8 to 5")
    return out


BUILTIN = builtins()


def validate(sym: dict) -> dict:
    for k in ("id", "pins"):
        if k not in sym:
            raise EcadError("A symbol needs %s." % k)
    sid = str(sym["id"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_+\-.:]{1,64}", sid):
        raise EcadError("A symbol id is 1 to 64 letters, digits or _+-.:")
    pins = []
    for p in sym["pins"]:
        et = p.get("etype", "passive")
        if et not in ETYPES:
            raise EcadError("Unknown pin type %s." % et)
        if p.get("orient", "L") not in ("U", "D", "L", "R"):
            raise EcadError("A pin orientation is U, D, L or R.")
        pins.append({"number": str(p["number"]), "name": str(p.get("name", "")), "etype": et, "pos": [float(p["pos"][0]), float(p["pos"][1])], "orient": p.get("orient", "L"), "length": float(p.get("length", LEN)), "unit": int(p.get("unit", 1)), "hidden": bool(p.get("hidden", False))})
    if not pins or len(pins) > MAX_PINS:
        raise EcadError("A symbol has 1 to %d pins." % MAX_PINS)
    graphics = []
    for g in sym.get("graphics", [])[:500]:
        if g.get("t") not in ("rect", "line", "circle", "text"):
            raise EcadError("Unknown graphic %s." % g.get("t"))
        graphics.append(g)
    return {
        "id": sid, "name": str(sym.get("name", sid))[:120], "description": str(sym.get("description", ""))[:400], "prefix": str(sym.get("prefix", "U"))[:8], "power": bool(sym.get("power", False)),
        "units": max(1, int(sym.get("units", 1))), "default_footprint": str(sym.get("default_footprint", "")), "keywords": [str(k) for k in sym.get("keywords", [])][:20], "graphics": graphics, "pins": pins, "source": "user",
    }
