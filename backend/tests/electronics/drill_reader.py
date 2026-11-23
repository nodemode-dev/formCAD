import re
from dataclasses import dataclass
from pathlib import Path

INCH = 25.4


@dataclass
class Hit:
    x: float
    y: float
    tool: int
    diameter: float
    end: tuple | None = None


class Drill:
    def __init__(self, text: str) -> None:
        self.text = text
        self.units = None
        self.zeros = None
        self.digits = None
        self.tools: dict = {}
        self.hits: list = []
        self.attrs: dict = {}
        self.ended = False
        self._tool = None
        self._pt = (0.0, 0.0)
        self._parse()

    @classmethod
    def read(cls, path) -> "Drill":
        return cls(Path(path).read_text(encoding="ascii"))

    def scale(self) -> float:
        return INCH if self.units == "in" else 1.0

    def _number(self, raw: str) -> float:
        if "." in raw:
            return float(raw) * self.scale()
        sign = -1.0 if raw.startswith("-") else 1.0
        body = raw.lstrip("+-")
        whole, frac = self.digits or ((3, 3) if self.units == "mm" else (2, 4))
        if self.zeros == "LZ":
            body = body.ljust(whole + frac, "0")
        return sign * int(body) / 10 ** frac * self.scale()

    def _parse(self) -> None:
        lines = [ln.strip() for ln in self.text.splitlines()]
        if not lines or lines[0] != "M48":
            raise ValueError("a drill file starts with M48")
        k = 1
        while k < len(lines):
            ln = lines[k]
            k += 1
            if ln in ("%", "M95"):
                break
            if ln.startswith(";"):
                m = re.match(r";\s*#@!\s*(T\w+\.\w+),(.*)", ln)
                if m:
                    self.attrs[m.group(1)] = m.group(2).split(",")
                continue
            m = re.fullmatch(r"(METRIC|INCH)(?:,(LZ|TZ))?(?:,(0+)\.(0+))?", ln)
            if m:
                self.units = "mm" if m.group(1) == "METRIC" else "in"
                self.zeros = m.group(2)
                if m.group(3):
                    self.digits = (len(m.group(3)), len(m.group(4)))
                continue
            m = re.fullmatch(r"T(\d+)(?:[FS][\d.]+)*C([\d.]+)(?:[FS][\d.]+)*", ln)
            if m:
                if self.units is None:
                    raise ValueError("a tool is defined before the units")
                self.tools[int(m.group(1))] = float(m.group(2)) * self.scale()
                continue
            if ln.startswith(("FMAT", "VER", "ICI", "ATC")) or not ln:
                continue
            raise ValueError("unknown header line %r" % ln)
        else:
            raise ValueError("the header never ends")
        for ln in lines[k:]:
            if not ln or ln.startswith(";"):
                continue
            if ln == "M30":
                self.ended = True
                break
            if re.fullmatch(r"G(05|90|00|01)", ln) or ln in ("M71", "M72"):
                if ln == "M72":
                    raise ValueError("inch mode switch in the body is not supported")
                continue
            m = re.fullmatch(r"T(\d+)", ln)
            if m:
                t = int(m.group(1))
                if t != 0 and t not in self.tools:
                    raise ValueError("tool T%d is used but not defined" % t)
                self._tool = t
                continue
            m = re.fullmatch(r"(?:X([+-]?[\d.]+))?(?:Y([+-]?[\d.]+))?(?:G85(?:X([+-]?[\d.]+))?(?:Y([+-]?[\d.]+))?)?", ln)
            if m and (m.group(1) or m.group(2)):
                if not self._tool:
                    raise ValueError("a hole before any tool is selected")
                x = self._number(m.group(1)) if m.group(1) else self._pt[0]
                y = self._number(m.group(2)) if m.group(2) else self._pt[1]
                end = None
                if "G85" in ln:
                    end = (self._number(m.group(3)) if m.group(3) else x, self._number(m.group(4)) if m.group(4) else y)
                self.hits.append(Hit(x, y, self._tool, self.tools[self._tool], end))
                self._pt = end or (x, y)
                continue
            raise ValueError("unknown body line %r" % ln)
        if not self.ended:
            raise ValueError("the drill file does not end with M30")

    def function(self) -> str:
        return ",".join(self.attrs.get("TF.FileFunction", []))
