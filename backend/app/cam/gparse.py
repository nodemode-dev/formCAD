import math
import re

from app.cam import toolpath as T
from app.cam.limits import CamError

WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
MAX_LINES = 5000000


def strip(line: str) -> str:
    line = re.sub(r"\([^)]*\)", "", line)
    line = line.split(";", 1)[0]
    return line.strip()


def parse(text: str, units_default: str = "mm") -> T.Toolpath:
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise CamError("The program has too many lines.")
    scale = 1.0 if units_default == "mm" else 25.4
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    absolute = True
    plane = "xy"
    feed = 0.0
    rpm = 0.0
    motion = None
    cycle = None
    r_plane = 0.0
    moves = []
    for raw in lines:
        s = strip(raw)
        if not s or s.startswith("%"):
            continue
        s = re.sub(r"^N\d+\s*", "", s)
        words = [(m.group(1).upper(), float(m.group(2))) for m in WORD.finditer(s)]
        gs = [w[1] for w in words if w[0] == "G"]
        ms = [int(w[1]) for w in words if w[0] == "M"]
        vals = {}
        for k, v in words:
            if k not in "GM":
                vals[k] = v
        for g in gs:
            if abs(g - 21) < 1e-9:
                scale = 1.0
            elif abs(g - 20) < 1e-9:
                scale = 25.4
            elif abs(g - 90) < 1e-9:
                absolute = True
            elif abs(g - 91) < 1e-9:
                absolute = False
            elif abs(g - 17) < 1e-9:
                plane = "xy"
            elif abs(g - 18) < 1e-9:
                plane = "zx"
            elif abs(g - 19) < 1e-9:
                plane = "yz"
            elif abs(g - 80) < 1e-9:
                cycle = None
                motion = None
            elif abs(g - 98) < 1e-9 or abs(g - 99) < 1e-9:
                pass
            elif abs(g) < 1e-9 or abs(g - 1) < 1e-9 or abs(g - 2) < 1e-9 or abs(g - 3) < 1e-9:
                motion = int(round(g))
                cycle = None
            elif abs(g - 4) < 1e-9:
                moves.append(["dwell", vals.get("P", 0.0)])
            elif abs(g - 81) < 1e-9 or abs(g - 82) < 1e-9 or abs(g - 83) < 1e-9 or abs(g - 73) < 1e-9:
                cycle = {81: "drill", 82: "dwell", 83: "peck", 73: "chip"}[int(round(g))]
        if "F" in vals:
            feed = vals["F"] * scale
        if "S" in vals:
            rpm = vals["S"]
        for m in ms:
            if m in (3, 4):
                moves.append(["spindle", rpm, "cw" if m == 3 else "ccw"])
            elif m == 5:
                moves.append(["spindle", 0.0, "off"])
            elif m == 6 and "T" in vals:
                moves.append(["tool", int(vals["T"]), rpm, ""])
        if cycle is not None and any(k in vals for k in "XYZR"):
            x = (vals["X"] * scale) if "X" in vals else pos["X"]
            y = (vals["Y"] * scale) if "Y" in vals else pos["Y"]
            if "R" in vals:
                r_plane = vals["R"] * scale
            z = (vals["Z"] * scale) if "Z" in vals else pos["Z"]
            moves.append(["cycle", cycle, x, y, z, r_plane, (vals.get("Q", 0.0) * scale), vals.get("P", 0.0), feed])
            pos["X"], pos["Y"], pos["Z"] = x, y, r_plane
            continue
        if motion is None or not any(k in vals for k in "XYZ"):
            continue
        new = dict(pos)
        for k in "XYZ":
            if k in vals:
                new[k] = (vals[k] * scale) if absolute else pos[k] + vals[k] * scale
        if motion == 0:
            moves.append(["rapid", new["X"], new["Y"], new["Z"]])
        elif motion == 1:
            moves.append(["feed", new["X"], new["Y"], new["Z"], feed])
        else:
            off = {k: vals.get(k, 0.0) * scale for k in "IJK"}
            cx, cy, cz = pos["X"] + off["I"], pos["Y"] + off["J"], pos["Z"] + off["K"]
            moves.append(["arc", "cw" if motion == 2 else "ccw", new["X"], new["Y"], new["Z"], cx, cy, cz, feed, plane])
        pos = new
    return T.Toolpath(moves)
