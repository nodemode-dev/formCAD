import math
import re
from dataclasses import dataclass, field
from pathlib import Path

INCH = 25.4


@dataclass
class Flash:
    x: float
    y: float
    aperture: int
    attrs: dict


@dataclass
class Draw:
    start: tuple
    end: tuple
    aperture: int
    mode: str
    center: tuple | None
    attrs: dict


@dataclass
class Region:
    contours: list
    polarity: str
    attrs: dict


@dataclass
class Aperture:
    code: int
    template: str
    params: list
    attrs: dict


class Expr:
    TOKEN = re.compile(r"\s*(\$\d+|\d*\.\d+|\d+|[-+x/()])")

    def __init__(self, text: str, env: dict) -> None:
        self.toks = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = self.TOKEN.match(text, pos)
            if not m:
                raise ValueError("bad macro expression %r" % text)
            self.toks.append(m.group(1))
            pos = m.end()
        self.i = 0
        self.env = env

    def value(self) -> float:
        v = self.sum()
        if self.i != len(self.toks):
            raise ValueError("trailing tokens in macro expression")
        return v

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def sum(self):
        v = self.prod()
        while self.peek() in ("+", "-"):
            op = self.take()
            r = self.prod()
            v = v + r if op == "+" else v - r
        return v

    def prod(self):
        v = self.unary()
        while self.peek() in ("x", "/"):
            op = self.take()
            r = self.unary()
            v = v * r if op == "x" else v / r
        return v

    def unary(self):
        t = self.peek()
        if t in ("+", "-"):
            self.take()
            v = self.unary()
            return v if t == "+" else -v
        if t == "(":
            self.take()
            v = self.sum()
            if self.take() != ")":
                raise ValueError("unbalanced parenthesis")
            return v
        t = self.take()
        if t.startswith("$"):
            return float(self.env.get(int(t[1:]), 0.0))
        return float(t)


def _rot(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


class Gerber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.units = None
        self.format = None
        self.zero = None
        self.notation = None
        self.file_attrs: dict = {}
        self.apertures: dict = {}
        self.macros: dict = {}
        self.flashes: list = []
        self.draws: list = []
        self.regions: list = []
        self.ended = False
        self._ap_attrs: dict = {}
        self._obj_attrs: dict = {}
        self._cur = None
        self._pt = (0.0, 0.0)
        self._mode = "G01"
        self._region = None
        self._contour = None
        self._polarity = "D"
        self._parse()

    @classmethod
    def read(cls, path) -> "Gerber":
        return cls(Path(path).read_text(encoding="ascii"))

    def _parse(self) -> None:
        text = self.text
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch in " \r\n\t":
                i += 1
                continue
            if ch == "%":
                j = text.index("%", i + 1)
                self._extended(text[i + 1:j])
                i = j + 1
                continue
            j = text.index("*", i)
            self._word(text[i:j].strip())
            i = j + 1
        if not self.ended:
            raise ValueError("the file does not end with M02")

    def _extended(self, block: str) -> None:
        block = block.strip()
        if block.startswith("AM"):
            parts = [p.strip() for p in block.split("*")]
            name = parts[0][2:]
            self.macros[name] = [p for p in parts[1:] if p and not p.startswith("0 ")]
            return
        for cmd in [c.strip() for c in block.split("*") if c.strip()]:
            self._ext_command(cmd)

    def _ext_command(self, cmd: str) -> None:
        if cmd.startswith("MO"):
            self.units = {"MM": "mm", "IN": "in"}[cmd[2:]]
        elif cmd.startswith("FS"):
            m = re.fullmatch(r"FS([LT])([AI])X(\d)(\d)Y(\d)(\d)", cmd)
            if not m:
                raise ValueError("bad format statement %r" % cmd)
            if (m.group(3), m.group(4)) != (m.group(5), m.group(6)):
                raise ValueError("X and Y formats differ")
            self.zero, self.notation = m.group(1), m.group(2)
            self.format = (int(m.group(3)), int(m.group(4)))
        elif cmd.startswith("AD"):
            if self.units is None or self.format is None:
                raise ValueError("aperture defined before MO and FS")
            m = re.fullmatch(r"ADD(\d+)([A-Za-z_.$][A-Za-z0-9_.$]*)(?:,(.*))?", cmd)
            if not m:
                raise ValueError("bad aperture definition %r" % cmd)
            code = int(m.group(1))
            if code < 10:
                raise ValueError("aperture codes start at D10")
            params = [float(v) for v in m.group(3).split("X")] if m.group(3) else []
            self.apertures[code] = Aperture(code, m.group(2), params, dict(self._ap_attrs))
        elif cmd.startswith("TF"):
            bits = cmd[2:].split(",")
            self.file_attrs[bits[0]] = bits[1:]
        elif cmd.startswith("TA"):
            bits = cmd[2:].split(",")
            self._ap_attrs[bits[0]] = bits[1:]
        elif cmd.startswith("TO"):
            bits = cmd[2:].split(",")
            self._obj_attrs[bits[0]] = bits[1:]
        elif cmd.startswith("TD"):
            name = cmd[2:]
            if name:
                self._ap_attrs.pop(name, None)
                self._obj_attrs.pop(name, None)
            else:
                self._ap_attrs.clear()
                self._obj_attrs.clear()
        elif cmd.startswith("LP"):
            self._polarity = cmd[2:]
        elif cmd.startswith(("LM", "LR", "LS", "SR", "AB", "IP", "OF", "IN", "LN")):
            pass
        else:
            raise ValueError("unknown extended command %r" % cmd)

    def _number(self, digits: str) -> float:
        if self.format is None:
            raise ValueError("coordinate before the format statement")
        whole, frac = self.format
        sign = -1.0 if digits.startswith("-") else 1.0
        body = digits.lstrip("+-")
        if "." in body:
            raise ValueError("decimal point in a coordinate")
        if len(body) > whole + frac:
            raise ValueError("coordinate %s has more digits than the format allows" % digits)
        if self.zero == "T":
            body = body.ljust(whole + frac, "0")
        value = sign * int(body) / 10 ** frac
        return value * (INCH if self.units == "in" else 1.0)

    def _word(self, word: str) -> None:
        if not word:
            return
        if word.startswith("G04"):
            return
        if word == "M02":
            self.ended = True
            return
        for g in re.findall(r"G0*(\d+)", word):
            code = int(g)
            if code in (1, 2, 3):
                self._mode = "G0%d" % code
            elif code == 36:
                self._region = Region([], self._polarity, dict(self._obj_attrs))
                self._contour = None
            elif code == 37:
                if self._contour:
                    self._region.contours.append(self._contour)
                self.regions.append(self._region)
                self._region = None
                self._contour = None
            elif code in (74, 75, 70, 71, 90, 91, 54, 55):
                pass
            else:
                raise ValueError("unknown G code %r" % word)
        word = re.sub(r"G0*\d+", "", word)
        if not word:
            return
        m = re.fullmatch(r"(?:X([+-]?\d+))?(?:Y([+-]?\d+))?(?:I([+-]?\d+))?(?:J([+-]?\d+))?(?:D0*(\d+))?", word)
        if not m:
            raise ValueError("unknown word %r" % word)
        x = self._number(m.group(1)) if m.group(1) else self._pt[0]
        y = self._number(m.group(2)) if m.group(2) else self._pt[1]
        i = self._number(m.group(3)) if m.group(3) else 0.0
        j = self._number(m.group(4)) if m.group(4) else 0.0
        d = int(m.group(5)) if m.group(5) else None
        if d is None:
            if any(m.group(k) for k in (1, 2, 3, 4)):
                raise ValueError("coordinates without an operation code")
            return
        if d >= 10:
            if d not in self.apertures:
                raise ValueError("aperture D%d is used before it is defined" % d)
            self._cur = d
            return
        if d == 1:
            if self._region is not None:
                if self._contour is None:
                    self._contour = [self._pt]
                self._contour.append((x, y))
            else:
                if self._cur is None:
                    raise ValueError("draw with no current aperture")
                center = (self._pt[0] + i, self._pt[1] + j) if self._mode != "G01" else None
                self.draws.append(Draw(self._pt, (x, y), self._cur, self._mode, center, dict(self._obj_attrs)))
        elif d == 2:
            if self._region is not None:
                if self._contour:
                    self._region.contours.append(self._contour)
                self._contour = [(x, y)]
        elif d == 3:
            if self._region is not None:
                raise ValueError("flash inside a region")
            if self._cur is None:
                raise ValueError("flash with no current aperture")
            self.flashes.append(Flash(x, y, self._cur, dict(self._obj_attrs)))
        else:
            raise ValueError("unknown operation D%02d" % d)
        self._pt = (x, y)

    def function(self) -> str:
        return ",".join(self.file_attrs.get(".FileFunction", []))

    def polarity(self) -> str:
        return ",".join(self.file_attrs.get(".FilePolarity", []))

    def scale(self) -> float:
        return INCH if self.units == "in" else 1.0

    def extent(self, code: int) -> tuple:
        ap = self.apertures[code]
        s = self.scale()
        p = ap.params
        t = ap.template
        if t == "C":
            return (p[0] * s, p[0] * s)
        if t in ("R", "O"):
            return (p[0] * s, p[1] * s)
        if t == "P":
            return (p[0] * s, p[0] * s)
        if t not in self.macros:
            raise ValueError("aperture template %s is not defined" % t)
        xs, ys = [], []
        for x, y in self.macro_points(t, p):
            xs.append(x)
            ys.append(y)
        return (round((max(xs) - min(xs)) * s, 9), round((max(ys) - min(ys)) * s, 9))

    def macro_points(self, name: str, params: list) -> list:
        env = {k + 1: v for k, v in enumerate(params)}
        pts = []
        for prim in self.macros[name]:
            m = re.fullmatch(r"\$(\d+)=(.*)", prim)
            if m:
                env[int(m.group(1))] = Expr(m.group(2), env).value()
                continue
            args = [Expr(a, env).value() for a in prim.split(",")]
            kind = int(args[0])
            if kind == 1:
                dia, cx, cy = args[2], args[3], args[4]
                rot = args[5] if len(args) > 5 else 0.0
                cx, cy = _rot(cx, cy, rot)
                r = dia / 2.0
                pts += [(cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r)]
            elif kind == 20:
                w, x1, y1, x2, y2, rot = args[2:8]
                ang = math.atan2(y2 - y1, x2 - x1)
                nx, ny = -math.sin(ang) * w / 2, math.cos(ang) * w / 2
                for qx, qy in ((x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny)):
                    pts.append(_rot(qx, qy, rot))
            elif kind == 21:
                w, h, cx, cy, rot = args[2:7]
                for qx, qy in ((cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)):
                    pts.append(_rot(qx, qy, rot))
            elif kind == 4:
                count = int(args[2])
                coords = args[3:3 + 2 * (count + 1)]
                rot = args[3 + 2 * (count + 1)]
                for k in range(0, len(coords), 2):
                    pts.append(_rot(coords[k], coords[k + 1], rot))
            elif kind == 5:
                count, cx, cy, dia, rot = int(args[2]), args[3], args[4], args[5], args[6]
                for k in range(count):
                    a = 2 * math.pi * k / count
                    pts.append(_rot(cx + dia / 2 * math.cos(a), cy + dia / 2 * math.sin(a), rot))
            else:
                raise ValueError("macro primitive %d is not supported" % kind)
        return pts

    def flashes_with(self, attr: str, *values) -> list:
        return [f for f in self.flashes if f.attrs.get(attr, [])[: len(values)] == list(values)]

    def pad_flashes(self) -> dict:
        out = {}
        for f in self.flashes:
            pin = f.attrs.get(".P")
            if pin:
                out[(pin[0], pin[1])] = f
        return out


def contour_area(pts) -> float:
    s = 0.0
    for k in range(len(pts)):
        x0, y0 = pts[k]
        x1, y1 = pts[(k + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return s / 2.0
