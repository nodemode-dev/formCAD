import math

import numpy as np

CORRECTIONS = ("none", "goodman", "gerber", "soderberg")
MAX_BLOCKS = 4096
MAX_HISTORY = 200000
LIFE_CAP = 1.0e15


class FatigueError(ValueError):
    pass


class SN:
    def __init__(self, spec: dict):
        if not isinstance(spec, dict):
            raise FatigueError("The S-N curve is missing. Give C and b, or two points [cycles, stress amplitude].")
        if "C" in spec and "b" in spec:
            self.C = float(spec["C"])
            self.b = float(spec["b"])
        elif "points" in spec:
            pts = spec["points"]
            if not isinstance(pts, list) or len(pts) != 2:
                raise FatigueError("Two S-N points are needed: [[cycles, amplitude], [cycles, amplitude]].")
            (n1, s1), (n2, s2) = [(float(a), float(b)) for a, b in pts]
            if not (n1 > 0 and n2 > 0 and s1 > 0 and s2 > 0) or n1 == n2:
                raise FatigueError("S-N points need positive values at two different cycle counts.")
            self.b = math.log(s2 / s1) / math.log(n2 / n1)
            self.C = s1 / n1 ** self.b
        elif "reference" in spec:
            ref = spec["reference"]
            n_e, s_e, b = float(ref["cycles"]), float(ref["amplitude"]), float(ref["b"])
            self.b = b
            self.C = s_e / n_e ** b
        else:
            raise FatigueError("The S-N curve needs C and b, two points, or a reference point with a slope b.")
        if not (self.C > 0.0 and math.isfinite(self.C)):
            raise FatigueError("The S-N coefficient C must be positive.")
        if not (-1.0 < self.b < 0.0):
            raise FatigueError("The Basquin exponent b must be negative (between -1 and 0).")
        self.limit = float(spec["endurance_limit"]) if spec.get("endurance_limit") not in (None, "") else None

    def amplitude_at(self, n):
        return self.C * np.power(np.asarray(n, dtype=float), self.b)

    def life(self, sigma_ar):
        s = np.asarray(sigma_ar, dtype=float)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            n = np.power(np.maximum(s, 1.0e-300) / self.C, 1.0 / self.b)
        n = np.minimum(n, LIFE_CAP)
        if self.limit is not None:
            n = np.where(s <= self.limit, LIFE_CAP, n)
        return np.where(s <= 0.0, LIFE_CAP, n)


def equivalent_amplitude(sig_a, sig_m, method, sigma_u=None, sigma_y=None):
    sa = np.asarray(sig_a, dtype=float)
    sm = np.asarray(sig_m, dtype=float)
    if method not in CORRECTIONS:
        raise FatigueError("The mean stress correction is one of: %s." % ", ".join(CORRECTIONS))
    if method == "none":
        return sa
    pos = np.maximum(sm, 0.0)
    if method == "goodman":
        if not sigma_u:
            raise FatigueError("The Goodman correction needs the ultimate strength of the material.")
        den = 1.0 - pos / sigma_u
    elif method == "gerber":
        if not sigma_u:
            raise FatigueError("The Gerber correction needs the ultimate strength of the material.")
        den = 1.0 - (pos / sigma_u) ** 2
    else:
        if not sigma_y:
            raise FatigueError("The Soderberg correction needs the yield strength of the material.")
        den = 1.0 - pos / sigma_y
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den > 1.0e-9, sa / np.maximum(den, 1.0e-9), np.inf)
    return out


def allowable_amplitude(sn_amp, sig_m, method, sigma_u=None, sigma_y=None):
    sm = max(float(sig_m), 0.0)
    if method == "none":
        return sn_amp
    if method == "goodman":
        return sn_amp * (1.0 - sm / sigma_u)
    if method == "gerber":
        return sn_amp * (1.0 - (sm / sigma_u) ** 2)
    return sn_amp * (1.0 - sm / sigma_y)


def rainflow(points):
    pts = [float(p) for p in points]
    if len(pts) > MAX_HISTORY:
        raise FatigueError("The load history has %d points, over the limit of %d." % (len(pts), MAX_HISTORY))
    red = []
    for p in pts:
        if red and p == red[-1]:
            continue
        if len(red) >= 2 and (red[-1] - red[-2]) * (p - red[-1]) > 0:
            red[-1] = p
        else:
            red.append(p)
    stack = []
    cycles = []
    for p in red:
        stack.append(p)
        while len(stack) >= 3:
            a, b, c = stack[-3], stack[-2], stack[-1]
            x = abs(c - b)
            y = abs(b - a)
            if x < y:
                break
            if len(stack) == 3:
                cycles.append((y, 0.5 * (a + b), 0.5))
                stack.pop(-3)
            else:
                cycles.append((y, 0.5 * (a + b), 1.0))
                del stack[-3:-1]
    for i in range(len(stack) - 1):
        cycles.append((abs(stack[i + 1] - stack[i]), 0.5 * (stack[i] + stack[i + 1]), 0.5))
    return cycles


def rainflow_repeating(points):
    pts = [float(p) for p in points]
    if len(pts) < 2:
        raise FatigueError("A load history needs at least two points.")
    if pts[0] == pts[-1] and len(pts) > 2:
        pts = pts[:-1]
    i = int(np.argmax(np.abs(pts)))
    pts = pts[i:] + pts[:i] + [pts[i]]
    return rainflow(pts)


def merge_cycles(cycles):
    acc = {}
    for rng, mean, cnt in cycles:
        key = (round(rng, 9), round(mean, 9))
        acc[key] = acc.get(key, 0.0) + cnt
    return sorted(((k[0], k[1], v) for k, v in acc.items()), key=lambda t: (t[0], t[1]))


def damage(sn: SN, blocks, sigma_u=None, sigma_y=None, method="goodman", scale=1.0):
    total = np.zeros_like(np.asarray(scale, dtype=float)) if np.ndim(scale) else 0.0
    for amp, mean, count in blocks:
        eq = equivalent_amplitude(amp * scale, mean * scale, method, sigma_u, sigma_y)
        n = sn.life(eq)
        total = total + count / n
    return total


def miner_life(sn: SN, spectrum, sigma_u=None, sigma_y=None, method="goodman"):
    if not isinstance(spectrum, list) or not spectrum or len(spectrum) > MAX_BLOCKS:
        raise FatigueError("The load spectrum is a list of 1 to %d blocks." % MAX_BLOCKS)
    rows = []
    dsum = 0.0
    for blk in spectrum:
        try:
            amp = float(blk["amplitude"])
            mean = float(blk.get("mean", 0.0))
            frac = float(blk.get("cycles", blk.get("fraction", 1.0)))
        except (KeyError, TypeError, ValueError):
            raise FatigueError("A spectrum block needs amplitude, mean and cycles (or fraction).")
        if amp < 0.0 or frac < 0.0:
            raise FatigueError("A spectrum block has a negative amplitude or count.")
        eq = float(equivalent_amplitude(amp, mean, method, sigma_u, sigma_y))
        n = float(sn.life(eq)) if math.isfinite(eq) else 0.0
        n = max(n, 1.0e-300)
        d = frac / n
        dsum += d
        rows.append({"amplitude": amp, "mean": mean, "cycles": frac, "equivalent_amplitude": eq, "life_cycles": n, "damage": d})
    return {"damage_per_block": dsum, "repeats_to_failure": (1.0 / dsum) if dsum > 0.0 else math.inf, "blocks": rows}
