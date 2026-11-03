import math

import numpy as np


class Reach(ValueError):
    pass


def rx(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def rz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


DEFAULT = {
    "id": "mill5_table_table", "name": "5-axis table-table (A about X under C about Z)", "kind": "table_table", "version": 1,
    "a": {"min": -120.0, "max": 30.0}, "c": {"min": -100000.0, "max": 100000.0},
    "pivot": [0.0, 0.0, 0.0], "offset": {"dy": 0.0, "dz": 0.0},
    "travel": {"x": [-300.0, 300.0], "y": [-250.0, 250.0], "z": [-250.0, 100.0]},
    "table": {"radius": 150.0, "thickness": 40.0},
    "head": {"radius": 60.0, "length": 120.0},
    "rapid": 12000.0, "accel": 1500.0, "tool_change_s": 6.0, "rotary_feed_max": 7200.0,
}


class TableTable:
    def __init__(self, rec: dict):
        r = dict(DEFAULT)
        r.update({k: v for k, v in (rec or {}).items() if v is not None})
        self.rec = r
        self.a_lim = (float(r["a"]["min"]), float(r["a"]["max"]))
        self.c_lim = (float(r["c"]["min"]), float(r["c"]["max"]))
        self.origin = np.array(r["pivot"], dtype=float)
        self.arm = np.array([0.0, float(r["offset"].get("dy", 0.0)), float(r["offset"].get("dz", 0.0))])
        self.tx = tuple(float(v) for v in r["travel"]["x"])
        self.ty = tuple(float(v) for v in r["travel"]["y"])
        self.tz = tuple(float(v) for v in r["travel"]["z"])

    def rot(self, a_deg: float, c_deg: float) -> np.ndarray:
        return rx(math.radians(a_deg)) @ rz(math.radians(c_deg))

    def machine_point(self, p, a_deg, c_deg):
        R = self.rot(a_deg, c_deg)
        pa = np.asarray(p, dtype=float)
        return self.origin - self.arm + rx(math.radians(a_deg)) @ (self.arm + rz(math.radians(c_deg)) @ pa)

    def part_point(self, m, a_deg, c_deg):
        ma = np.asarray(m, dtype=float)
        inner = rx(-math.radians(a_deg)) @ (ma - self.origin + self.arm) - self.arm
        return rz(-math.radians(c_deg)) @ inner

    def axis_in_part(self, a_deg, c_deg):
        return rz(-math.radians(c_deg)) @ rx(-math.radians(a_deg)) @ np.array([0.0, 0.0, 1.0])

    def frame_in_part(self, a_deg, c_deg):
        return rz(-math.radians(c_deg)) @ rx(-math.radians(a_deg))

    def candidates(self, k):
        k = np.asarray(k, dtype=float)
        n = np.linalg.norm(k)
        if n < 1e-12:
            raise Reach("The tool axis has no length.")
        i, j, l = k / n
        rho = math.hypot(i, j)
        a1 = math.degrees(math.atan2(rho, l))
        if rho < 1e-9:
            return [(0.0, None)] if l > 0 else [(180.0, None), (-180.0, None)]
        c1 = math.degrees(math.atan2(i, j))
        c2 = c1 + 180.0
        return [(a1, c1), (-a1, c2)]

    def solve_axis(self, k, previous=None):
        prev = previous or {"a": 0.0, "c": 0.0}
        best = None
        for a, c in self.candidates(k):
            if c is None:
                c = prev["c"]
            if c is not None:
                c = c + 360.0 * round((prev["c"] - c) / 360.0)
            ok = self.a_lim[0] - 1e-9 <= a <= self.a_lim[1] + 1e-9
            if ok and not (self.c_lim[0] <= c <= self.c_lim[1]):
                for t in (c - 360.0, c + 360.0):
                    if self.c_lim[0] <= t <= self.c_lim[1]:
                        c = t
                        break
                else:
                    ok = False
            cost = abs(a - prev["a"]) + abs(c - prev["c"])
            row = (not ok, cost, a, c)
            if best is None or row < best:
                best = row
        bad, _, a, c = best
        if bad:
            raise Reach("The tool axis cannot be reached: A would be %.2f degrees (limits %g to %g)." % (a, self.a_lim[0], self.a_lim[1]))
        return a, c

    def solve(self, p, k, previous=None):
        a, c = self.solve_axis(k, previous)
        m = self.machine_point(p, a, c)
        return {"x": float(m[0]), "y": float(m[1]), "z": float(m[2]), "a": a, "c": c}

    def forward(self, x, y, z, a, c):
        p = self.part_point([x, y, z], a, c)
        return p, self.axis_in_part(a, c)

    def in_travel(self, m) -> list:
        out = []
        for name, v, lim in (("x", m[0], self.tx), ("y", m[1], self.ty), ("z", m[2], self.tz)):
            if v < lim[0] - 1e-6 or v > lim[1] + 1e-6:
                out.append(name)
        return out

    def solve_path(self, pts, axes, subdivide_deg: float = 0.0, chord_tol: float = 0.01):
        prev = None
        out = []
        for p, k in zip(pts, axes):
            s = self.solve(p, k, prev)
            prev = {"a": s["a"], "c": s["c"]}
            out.append(s)
        return out
