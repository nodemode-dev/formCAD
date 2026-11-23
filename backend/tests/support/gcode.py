import math
import re
from pathlib import Path

WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
MOTION = {0, 1, 2, 3}


def strip(line: str) -> str:
    line = re.sub(r"\([^)]*\)", "", line)
    return line.split(";", 1)[0].strip()


class Move:
    def __init__(self, kind: int, start: tuple, end: tuple, feed: float, line: int, centre: tuple | None = None, tool: int = 0, spindle: float = 0.0) -> None:
        self.kind = kind
        self.start = start
        self.end = end
        self.feed = feed
        self.line = line
        self.centre = centre
        self.tool = tool
        self.spindle = spindle

    @property
    def rapid(self) -> bool:
        return self.kind == 0

    @property
    def cutting(self) -> bool:
        return self.kind in (1, 2, 3)

    @property
    def arc(self) -> bool:
        return self.kind in (2, 3)

    @property
    def radius(self) -> float:
        if self.centre is None:
            return 0.0
        return math.hypot(self.start[0] - self.centre[0], self.start[1] - self.centre[1])

    @property
    def length(self) -> float:
        if self.arc and self.centre is not None:
            a0 = math.atan2(self.start[1] - self.centre[1], self.start[0] - self.centre[0])
            a1 = math.atan2(self.end[1] - self.centre[1], self.end[0] - self.centre[0])
            sweep = (a0 - a1) if self.kind == 2 else (a1 - a0)
            sweep %= 2 * math.pi
            if sweep < 1e-12:
                sweep = 2 * math.pi
            return math.hypot(sweep * self.radius, self.end[2] - self.start[2])
        return math.dist(self.start, self.end)


class Program:
    def __init__(self, text: str) -> None:
        self.moves: list = []
        self.units = "mm"
        self.absolute = True
        self.plane = 17
        self.offsets: list = []
        self.tools: list = []
        self.unknown: list = []
        self.spindle_on = False
        self.ended = False
        pos = [0.0, 0.0, 0.0]
        modal = None
        feed = 0.0
        speed = 0.0
        tool = 0
        for number, raw in enumerate(text.splitlines(), 1):
            line = strip(raw)
            if not line or line.startswith("%") or line[0] in "Oo":
                continue
            words = [(w.upper(), float(v)) for w, v in WORD.findall(line)]
            target = {}
            arc = {}
            motion_here = None
            for letter, value in words:
                if letter == "G":
                    g = int(round(value)) if abs(value - round(value)) < 1e-9 else value
                    if g in MOTION:
                        modal = g
                        motion_here = g
                    elif g == 20:
                        self.units = "inch"
                    elif g == 21:
                        self.units = "mm"
                    elif g == 90:
                        self.absolute = True
                    elif g == 91:
                        self.absolute = False
                    elif g in (17, 18, 19):
                        self.plane = g
                    elif isinstance(g, int) and 54 <= g <= 59:
                        self.offsets.append(g)
                    elif g == 80:
                        modal = None
                elif letter == "M":
                    m = int(round(value))
                    if m in (3, 4):
                        self.spindle_on = True
                    elif m == 5:
                        self.spindle_on = False
                    elif m in (2, 30):
                        self.ended = True
                elif letter in "XYZ":
                    target[letter] = value
                elif letter in "IJKR":
                    arc[letter] = value
                elif letter == "F":
                    feed = value
                elif letter == "S":
                    speed = value
                elif letter == "T":
                    tool = int(round(value))
                    self.tools.append(tool)
                elif letter not in "NHDPQL":
                    self.unknown.append((number, letter))
            if not target and motion_here is None:
                continue
            if modal is None:
                if target:
                    self.unknown.append((number, "motion without a mode"))
                continue
            end = list(pos)
            for i, letter in enumerate("XYZ"):
                if letter in target:
                    end[i] = target[letter] if self.absolute else pos[i] + target[letter]
            centre = None
            if modal in (2, 3):
                if "I" in arc or "J" in arc:
                    centre = (pos[0] + arc.get("I", 0.0), pos[1] + arc.get("J", 0.0))
                elif "R" in arc:
                    centre = _centre_from_radius(pos, end, arc["R"], modal)
            if end != pos or modal in (2, 3):
                self.moves.append(Move(modal, tuple(pos), tuple(end), feed, number, centre, tool, speed if self.spindle_on else 0.0))
            pos = end

    @classmethod
    def read(cls, path) -> "Program":
        return cls(Path(path).read_text(encoding="utf-8", errors="replace"))

    def cutting(self) -> list:
        return [m for m in self.moves if m.cutting]

    def rapids(self) -> list:
        return [m for m in self.moves if m.rapid]

    def lowest(self) -> float:
        return min((min(m.start[2], m.end[2]) for m in self.moves), default=0.0)

    def highest(self) -> float:
        return max((max(m.start[2], m.end[2]) for m in self.moves), default=0.0)

    def cut_length(self) -> float:
        return sum(m.length for m in self.cutting())

    def extents(self, cutting_only: bool = True) -> tuple:
        moves = self.cutting() if cutting_only else self.moves
        pts = [p for m in moves for p in (m.start, m.end)]
        return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)

    def arcs_are_consistent(self, tol: float = 1e-3) -> bool:
        for m in self.moves:
            if m.arc and m.centre is not None:
                r0 = math.hypot(m.start[0] - m.centre[0], m.start[1] - m.centre[1])
                r1 = math.hypot(m.end[0] - m.centre[0], m.end[1] - m.centre[1])
                if abs(r0 - r1) > tol:
                    return False
        return True

    def path_points(self, cutting_only: bool = True, step_deg: float = 5.0) -> list:
        out = []
        for m in self.cutting() if cutting_only else self.moves:
            if m.arc and m.centre is not None:
                a0 = math.atan2(m.start[1] - m.centre[1], m.start[0] - m.centre[0])
                a1 = math.atan2(m.end[1] - m.centre[1], m.end[0] - m.centre[0])
                sweep = (a0 - a1) if m.kind == 2 else (a1 - a0)
                sweep %= 2 * math.pi
                if sweep < 1e-12:
                    sweep = 2 * math.pi
                steps = max(2, int(math.degrees(sweep) / step_deg) + 1)
                sign = -1.0 if m.kind == 2 else 1.0
                for k in range(steps + 1):
                    a = a0 + sign * sweep * k / steps
                    z = m.start[2] + (m.end[2] - m.start[2]) * k / steps
                    out.append((m.centre[0] + m.radius * math.cos(a), m.centre[1] + m.radius * math.sin(a), z))
            else:
                out.append(m.start)
                out.append(m.end)
        return out


def _centre_from_radius(start, end, r: float, kind: int) -> tuple | None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    chord = math.hypot(dx, dy)
    if chord < 1e-12 or abs(r) < chord / 2.0 - 1e-9:
        return None
    h = math.sqrt(max(0.0, r * r - (chord / 2.0) ** 2))
    mx, my = (start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0
    side = 1.0 if (kind == 3) == (r > 0) else -1.0
    return mx - side * h * dy / chord, my + side * h * dx / chord
