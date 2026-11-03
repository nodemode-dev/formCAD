import math

import numpy as np

KINDS = ("flat", "ball", "bull", "cone")
BIG = 1e9


class Cutter:
    def __init__(self, kind: str, diameter: float, corner: float = 0.0, half_angle: float = 0.0, tip_diameter: float = 0.0, flute: float = 1e6):
        if kind not in KINDS:
            raise ValueError("The cutter kind %s is not one of %s." % (kind, ", ".join(KINDS)))
        if not diameter > 0:
            raise ValueError("The cutter diameter must be above zero.")
        self.kind = kind
        self.R = diameter / 2.0
        self.flute = float(flute)
        if kind == "flat":
            self.r = 0.0
        elif kind == "ball":
            self.r = self.R
        elif kind == "bull":
            self.r = min(max(float(corner), 0.0), self.R)
        else:
            self.r = 0.0
        self.Rc = self.R - self.r
        self.tan = 0.0
        self.rt = 0.0
        self.hc = 0.0
        if kind == "cone":
            if not 0.0 < half_angle < 89.0:
                raise ValueError("The cone half angle must be between 0 and 89 degrees.")
            self.tan = math.tan(math.radians(half_angle))
            self.rt = min(max(tip_diameter / 2.0, 0.0), self.R * 0.999)
            self.hc = (self.R - self.rt) / self.tan

    @classmethod
    def from_tool(cls, tool) -> "Cutter":
        kind = str(getattr(tool, "kind", "flat"))
        d = float(getattr(tool, "diameter", 6.0))
        flute = float(getattr(tool, "flute_length", 0) or 1e6)
        if kind == "ball":
            return cls("ball", d, flute=flute)
        if kind == "bull":
            return cls("bull", d, float(getattr(tool, "corner_radius", 0) or 0), flute=flute)
        if kind in ("chamfer", "engraver"):
            ang = float(getattr(tool, "tip_angle", 90) or 90)
            return cls("cone", d, half_angle=min(max(ang / 2.0, 1.0), 88.0), tip_diameter=float(getattr(tool, "tip_diameter", 0) or 0), flute=flute)
        if kind == "drill":
            ang = float(getattr(tool, "tip_angle", 118) or 118)
            return cls("cone", d, half_angle=min(max(ang / 2.0, 1.0), 88.0), flute=flute)
        if kind == "tapered_ball":
            return cls("ball", d, flute=flute)
        return cls("flat", d, flute=flute)

    def under(self, rho):
        rho = np.asarray(rho, dtype=float)
        k = self.kind
        if k == "flat":
            out = np.zeros_like(rho)
        elif k == "cone":
            out = np.where(rho <= self.rt, 0.0, (rho - self.rt) / self.tan)
            out = np.where(rho <= self.R, out, BIG)
            return out
        else:
            q = np.clip(rho - self.Rc, 0.0, self.r)
            if self.r > 0:
                out = np.where(rho <= self.Rc, 0.0, self.r - np.sqrt(np.maximum(self.r * self.r - q * q, 0.0)))
            else:
                out = np.zeros_like(rho)
        return np.where(rho <= self.R + 1e-12, out, BIG)

    def radius_at(self, h):
        h = np.asarray(h, dtype=float)
        k = self.kind
        if k == "flat":
            out = np.full_like(h, self.R)
        elif k == "cone":
            out = np.minimum(self.R, self.rt + np.maximum(h, 0.0) * self.tan)
        elif self.r <= 0:
            out = np.full_like(h, self.R)
        else:
            hh = np.clip(h, 0.0, self.r)
            out = np.where(h >= self.r, self.R, self.Rc + np.sqrt(np.maximum(self.r * self.r - (self.r - hh) ** 2, 0.0)))
        return np.where(h < 0, -1.0, out)

    def support(self, nxy, nz):
        nxy = np.asarray(nxy, dtype=float)
        nz = np.asarray(nz, dtype=float)
        k = self.kind
        if k == "flat":
            return np.full_like(nxy, self.R), np.zeros_like(nxy)
        if k == "cone":
            a_rho, a_h = self.rt, 0.0
            b_rho, b_h = self.R, self.hc
            fa = -a_rho * nxy + nz * a_h
            fb = -b_rho * nxy + nz * b_h
            take_a = fa <= fb
            return np.where(take_a, a_rho, b_rho), np.where(take_a, a_h, b_h)
        if self.r <= 0:
            return np.full_like(nxy, self.R), np.zeros_like(nxy)
        phi = np.arctan2(nxy, np.maximum(nz, 0.0))
        return self.Rc + self.r * np.sin(phi), self.r * (1.0 - np.cos(phi))

    def profile(self, points: int = 24) -> list:
        out = [[0.0, 0.0]]
        if self.kind == "flat":
            out = [[0.0, 0.0], [self.R, 0.0]]
        elif self.kind == "cone":
            out = [[0.0, 0.0]] + ([[self.rt, 0.0]] if self.rt > 0 else []) + [[self.R, self.hc]]
        else:
            out = [[0.0, 0.0]] + ([[self.Rc, 0.0]] if self.Rc > 0 else [])
            for i in range(1, points + 1):
                phi = (math.pi / 2.0) * i / points
                out.append([self.Rc + self.r * math.sin(phi), self.r * (1.0 - math.cos(phi))])
        top = min(self.flute, 1e5)
        out.append([self.R, top])
        return out

    def key(self) -> tuple:
        return (self.kind, round(self.R, 6), round(self.r, 6), round(self.tan, 6), round(self.rt, 6))
