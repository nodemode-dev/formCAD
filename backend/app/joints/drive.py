import copy
import math

from app.mates import joint_eq

STEP_ANGLE = math.radians(4.0)
STEP_LENGTH_FRACTION = 0.04
MAX_SPLIT = 6
MAX_STEPS = 3000


class Driver:
    def __init__(self, model, check=None):
        self.model = model
        self.check = check
        self.joints = {m.id: m for m in model.mates if m.kind == "joint" and not m.suppressed}

    def measured(self, mid, key) -> float:
        m = self.joints[mid]
        w = self.model.net.worlds(m)
        prev = (m.opt.get("state") or {}).get("q")
        return joint_eq.values_of(m.opt["spec"], w[0], w[1], prev)[key]

    def commanded(self, mid, key) -> float:
        d = self.joints[mid].opt.get("drive") or {}
        return d[key] if key in d else self.measured(mid, key)

    def bounds(self, mid, key) -> tuple:
        lim = self.joints[mid].opt["spec"]["lim"].get(key)
        return (None, None) if lim is None else lim

    def clamp(self, mid, key, v) -> tuple:
        lo, hi = self.bounds(mid, key)
        out = v
        if lo is not None and out < lo:
            out = lo
        if hi is not None and out > hi:
            out = hi
        return out, out != v

    def snapshot(self) -> dict:
        return {
            "poses": self.model.net.snapshot(),
            "states": {m.id: copy.deepcopy(m.opt.get("state") or {}) for m in self.model.net.mates},
            "drives": {mid: dict(m.opt.get("drive") or {}) for mid, m in self.joints.items()},
        }

    def restore(self, snap: dict) -> None:
        self.model.net.restore(snap["poses"])
        for m in self.model.net.mates:
            if m.id in snap["states"]:
                m.opt["state"] = copy.deepcopy(snap["states"][m.id])
        for mid, d in snap["drives"].items():
            if d:
                self.joints[mid].opt["drive"] = dict(d)
            else:
                self.joints[mid].opt.pop("drive", None)

    def clear(self) -> None:
        for m in self.joints.values():
            m.opt.pop("drive", None)

    def goto(self, targets: dict, max_step: dict | None = None, retries: int = 1) -> dict:
        start = self.snapshot()
        cur = {k: self.commanded(*k) for k in targets}
        steps = 1
        for k, tv in targets.items():
            size = (max_step or {}).get(k)
            if size is None:
                size = STEP_ANGLE if k[1] in joint_eq.ANGLES else STEP_LENGTH_FRACTION * self.model.L
            need = abs(tv - cur[k]) / (abs(size) or 1e-300)
            if not math.isfinite(need) or need > MAX_STEPS:
                raise joint_eq.JointError("That move is too far for one drive; the limit is %d sub-steps. Use a nearer value." % MAX_STEPS)
            steps = max(steps, int(math.ceil(need - 1e-9)))
        acc = [0.0, 0, 0]
        prev = dict(cur)
        for i in range(1, steps + 1):
            if self.check is not None:
                self.check()
            f = i / steps
            nxt = {k: cur[k] + (targets[k] - cur[k]) * f for k in targets}
            if not self.move(prev, nxt, 0, acc, retries):
                self.restore(start)
                return {"ok": False, "ms": acc[0], "iterations": acc[1], "substeps": acc[2], "reached": (i - 1) / steps}
            prev = nxt
        return {"ok": True, "ms": acc[0], "iterations": acc[1], "substeps": acc[2], "reached": 1.0}

    def move(self, a: dict, b: dict, depth: int, acc: list, retries: int) -> bool:
        for k, v in b.items():
            self.joints[k[0]].opt.setdefault("drive", {})[k[1]] = v
        rep = self.model.net.solve(retries=retries if depth >= MAX_SPLIT else 0)
        acc[0] += rep.ms
        acc[1] += rep.iterations
        acc[2] += 1
        if rep.ok:
            return True
        if depth >= MAX_SPLIT:
            return False
        mid = {k: (a[k] + b[k]) / 2.0 for k in b}
        return self.move(a, mid, depth + 1, acc, retries) and self.move(mid, b, depth + 1, acc, retries)
