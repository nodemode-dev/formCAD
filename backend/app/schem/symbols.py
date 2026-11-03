import math

from app.schem.errors import SchemError

GRID = 5.0
LABEL = "Device symbols are FormCAD's own simple outlines drawn from rectangles, circles and lines, on a 5 unit grid. They follow no published symbol standard."


def box(x0, y0, x1, y1):
    return [("line", (x0, y0), (x1, y0)), ("line", (x1, y0), (x1, y1)), ("line", (x1, y1), (x0, y1)), ("line", (x0, y1), (x0, y0))]


def stub(p, q):
    return ("line", p, q)


def two_pin(names, half=10.0):
    return [{"id": names[0], "dx": -half, "dy": 0.0}, {"id": names[1], "dx": half, "dy": 0.0}]


def resistor(_n):
    return two_pin(("1", "2")), box(-5, -2, 5, 2) + [stub((-10, 0), (-5, 0)), stub((5, 0), (10, 0))]


def capacitor(_n):
    return two_pin(("1", "2")), [stub((-10, 0), (-1.5, 0)), stub((1.5, 0), (10, 0)), stub((-1.5, -4), (-1.5, 4)), stub((1.5, -4), (1.5, 4))]


def coil(_n):
    return two_pin(("A1", "A2")), box(-5, -3, 5, 3) + [stub((-10, 0), (-5, 0)), stub((5, 0), (10, 0))]


def contact_no(_n):
    return two_pin(("13", "14")), [stub((-10, 0), (-3, 0)), stub((3, 0), (10, 0)), stub((-3, 0), (3, 4))]


def contact_nc(_n):
    return two_pin(("11", "12")), [stub((-10, 0), (-3, 0)), stub((3, 0), (10, 0)), stub((-3, 0), (3, 4)), stub((3, -3), (3, 3))]


def switch(_n):
    return two_pin(("1", "2")), [stub((-10, 0), (-3, 0)), stub((3, 0), (10, 0)), stub((-3, 0), (3, 4))]


def push_button(_n):
    return two_pin(("1", "2")), [stub((-10, 0), (-3, 0)), stub((3, 0), (10, 0)), stub((-3, 0), (3, 3)), stub((0, 5), (0, 8)), stub((-3, 8), (3, 8))]


def fuse(_n):
    return two_pin(("1", "2")), box(-5, -2, 5, 2) + [stub((-10, 0), (-5, 0)), stub((5, 0), (10, 0)), stub((-5, 0), (5, 0))]


def lamp(_n):
    return two_pin(("X1", "X2")), [("circle", (0, 0), 5), stub((-10, 0), (-5, 0)), stub((5, 0), (10, 0)), stub((-3.5, -3.5), (3.5, 3.5)), stub((-3.5, 3.5), (3.5, -3.5))]


def motor(_n):
    pins = [{"id": "U", "dx": -5.0, "dy": 10.0}, {"id": "V", "dx": 0.0, "dy": 10.0}, {"id": "W", "dx": 5.0, "dy": 10.0}]
    return pins, [("circle", (0, 0), 8), stub((-5, 10), (-5, 6.4)), stub((0, 10), (0, 8)), stub((5, 10), (5, 6.4)), ("text", (-2, -2), "M", 4.0)]


def terminal(_n):
    return two_pin(("1", "2"), 5.0), [("circle", (0, 0), 1.5), stub((-5, 0), (-1.5, 0)), stub((1.5, 0), (5, 0))]


def source(_n):
    return [{"id": "+", "dx": 0.0, "dy": 10.0}, {"id": "-", "dx": 0.0, "dy": -10.0}], [("circle", (0, 0), 6), stub((0, 10), (0, 6)), stub((0, -6), (0, -10)), stub((-2, 2.5), (2, 2.5)), stub((0, 0.5), (0, 4.5)), stub((-2, -2.5), (2, -2.5))]


def ground(_n):
    return [{"id": "1", "dx": 0.0, "dy": 0.0}], [stub((0, 0), (0, -3)), stub((-4, -3), (4, -3)), stub((-2.5, -5), (2.5, -5)), stub((-1, -7), (1, -7))]


def junction(_n):
    return [{"id": "1", "dx": 0.0, "dy": 0.0}], [("circle", (0, 0), 0.8)]


def connector(n):
    n = max(int(n or 4), 1)
    h = GRID * (n + 1)
    pins = []
    draw = box(-5, -h / 2, 5, h / 2)
    for i in range(n):
        y = h / 2 - GRID * (i + 1)
        pins.append({"id": str(i + 1), "dx": -10.0, "dy": y})
        draw.append(stub((-10, y), (-5, y)))
        draw.append(("text", (-4.5, y - 1.2), str(i + 1), 2.0))
    return pins, draw


def block(_n):
    return [], box(-10, -10, 10, 10)


KINDS = {"resistor": resistor, "capacitor": capacitor, "coil": coil, "contact_no": contact_no, "contact_nc": contact_nc, "switch": switch, "push_button": push_button, "fuse": fuse, "lamp": lamp, "motor": motor, "terminal": terminal, "source": source, "ground": ground, "junction": junction, "connector": connector, "block": block}
PREFIX = {"resistor": "R", "capacitor": "C", "coil": "K", "contact_no": "K", "contact_nc": "K", "switch": "S", "push_button": "S", "fuse": "F", "lamp": "H", "motor": "M", "terminal": "X", "source": "G", "ground": "PE", "junction": "J", "connector": "J", "block": "U"}


def build(kind: str, pin_count=None):
    fn = KINDS.get(kind)
    if fn is None:
        raise SchemError("A device kind is one of %s." % ", ".join(KINDS))
    return fn(pin_count)


def rotate(x: float, y: float, rot: int):
    a = math.radians(rot)
    c, s = round(math.cos(a), 12), round(math.sin(a), 12)
    return x * c - y * s, x * s + y * c


def pin_world(dev: dict, pin: dict):
    rx, ry = rotate(pin["dx"], pin["dy"], int(dev.get("rotation", 0)))
    return dev["x"] + rx, dev["y"] + ry
