import copy
import math
import time

import numpy as np

from app.mates import eqs, rig

RANK_TOL = 1e-6
FWD = 1e-7
CTR = 1e-6
DRAG_W = 1e-3


class Body:
    __slots__ = ("id", "R", "t", "fixed", "weight", "size")

    def __init__(self, bid, matrix=None, fixed=False, weight=1.0, size=100.0):
        self.id = bid
        m = np.eye(4) if matrix is None else np.asarray(matrix, dtype=float).reshape(4, 4)
        self.R, self.t = rig.split(m)
        self.fixed = bool(fixed)
        self.weight = float(weight)
        self.size = float(size)

    def matrix(self) -> np.ndarray:
        return rig.matrix(self.R, self.t)


class Report:
    def __init__(self):
        self.ok = True
        self.iterations = 0
        self.residual = 0.0
        self.ms = 0.0
        self.message = ""


GROUND = (np.eye(3), np.zeros(3))


class Network:
    def __init__(self, bodies: list, mates: list, scale: float | None = None):
        self.bodies = {b.id: b for b in bodies}
        self.mates = list(mates)
        sizes = [b.size for b in bodies] or [100.0]
        self.L = float(scale) if scale else max(1.0, float(np.mean(sizes)))
        self.tol = 1e-10 * max(1.0, self.L)
        self.rng = np.random.default_rng(11)

    def pose(self, cid, over=None):
        if cid is None:
            return GROUND
        if over is not None and cid in over:
            return over[cid]
        b = self.bodies.get(cid)
        if b is None:
            raise eqs.MateError("The component %s is not in the assembly." % cid)
        return (b.R, b.t)

    def active(self, mates=None):
        return [m for m in (self.mates if mates is None else mates) if not m.suppressed]

    def worlds(self, m, over=None):
        return [eqs.world(s, self.pose(s.comp, over)) for s in m.sides]

    def mate_res(self, m, over=None):
        return eqs.residual(m, self.worlds(m, over))

    def free_ids(self, mates):
        seen = []
        for m in mates:
            for c in m.comps():
                b = self.bodies.get(c)
                if b is not None and not b.fixed and c not in seen:
                    seen.append(c)
        return seen

    def jac_mate(self, m, f0, central, scale_rot=True):
        cols = {}
        for c in dict.fromkeys(m.comps()):
            b = self.bodies[c]
            if b.fixed:
                continue
            block = np.zeros((f0.size, 6))
            for j in range(6):
                if central:
                    fp = self.mate_res(m, {c: self.bump(b, j, CTR)})
                    fm = self.mate_res(m, {c: self.bump(b, j, -CTR)})
                    col = (fp - fm) / (2 * CTR)
                else:
                    fp = self.mate_res(m, {c: self.bump(b, j, FWD)})
                    col = (fp - f0) / FWD
                block[:, j] = col
            if scale_rot:
                block[:, 3:] /= self.L
            cols[c] = block
        return cols

    @staticmethod
    def bump(b, j, h):
        if j < 3:
            t = b.t.copy()
            t[j] += h
            return (b.R, t)
        w = np.zeros(3)
        w[j - 3] = h
        return (rig.expm(w) @ b.R, b.t)

    def system(self, mates, extra=None, central=False):
        free = self.free_ids(mates)
        col = {c: 6 * i for i, c in enumerate(free)}
        fs, rows = [], []
        for m in mates:
            f0 = self.mate_res(m)
            fs.append(f0)
            rows.append((m, f0.size))
        n = 6 * len(free)
        total = sum(r for _, r in rows) + (3 * len(extra) if extra else 0)
        F = np.zeros(total)
        J = np.zeros((total, n))
        r = 0
        for m, f0 in zip(mates, fs):
            F[r:r + f0.size] = f0
            for c, block in self.jac_mate(m, f0, central).items():
                J[r:r + f0.size, col[c]:col[c] + 6] = block
            r += f0.size
        if extra:
            for e in extra:
                c, lp, target, w = e
                b = self.bodies[c]
                pos = b.R @ lp + b.t
                F[r:r + 3] = w * (pos - target)
                if c in col:
                    J[r:r + 3, col[c]:col[c] + 3] = w * np.eye(3)
                    J[r:r + 3, col[c] + 3:col[c] + 6] = -w * rig.skew(b.R @ lp) / self.L
                r += 3
        return free, F, J

    def extra_res(self, extra):
        out = []
        for c, lp, target, w in extra or []:
            b = self.bodies[c]
            out.append(w * (b.R @ lp + b.t - target))
        return np.concatenate(out) if out else np.zeros(0)

    def residual(self, mates, extra=None):
        parts = [self.mate_res(m) for m in mates]
        if extra:
            parts.append(self.extra_res(extra))
        return np.concatenate(parts) if parts else np.zeros(0)

    def snapshot(self):
        return {k: (b.R.copy(), b.t.copy()) for k, b in self.bodies.items()}

    def restore(self, snap):
        for k, (r, t) in snap.items():
            self.bodies[k].R, self.bodies[k].t = r.copy(), t.copy()

    def step(self, free, dx):
        for i, c in enumerate(free):
            b = self.bodies[c]
            y = dx[6 * i:6 * i + 6]
            b.t = b.t + y[:3]
            b.R = rig.orthonormal(rig.expm(y[3:] / self.L) @ b.R)

    def lm(self, mates, extra=None, max_it=120, tol=None, lam0=1e-6):
        tol = self.tol if tol is None else tol
        free = self.free_ids(mates)
        if extra:
            for c, *_ in extra:
                if c not in free and not self.bodies[c].fixed:
                    free.append(c)
        n = 6 * len(free)
        winv = np.ones(n)
        for i, c in enumerate(free):
            winv[6 * i:6 * i + 6] = 1.0 / max(self.bodies[c].weight, 1e-12)
        lam = lam0
        F = self.residual(mates, extra)
        if F.size == 0:
            return True, 0, 0.0
        it = 0
        best = float(np.max(np.abs(F)))
        stall = 0
        limit = 0.25 * self.L
        while it < max_it:
            if best < tol:
                break
            _, F, J = self.system_for(free, mates, extra)
            JW = J * winv
            A = JW @ J.T
            nf = float(F @ F)
            improved = False
            for _try in range(12):
                try:
                    z = np.linalg.solve(A + lam * np.eye(A.shape[0]) * max(1.0, float(np.trace(A)) / max(A.shape[0], 1)), -F)
                except np.linalg.LinAlgError:
                    lam *= 10
                    continue
                dx = JW.T @ z
                big = float(np.max(np.abs(dx))) if dx.size else 0.0
                if big > limit:
                    dx = dx * (limit / big)
                snap = self.snapshot()
                self.step(free, dx)
                Fn = self.residual(mates, extra)
                if float(Fn @ Fn) < nf:
                    lam = max(lam * 0.2, 1e-14)
                    F = Fn
                    improved = True
                    break
                self.restore(snap)
                lam = min(lam * 8.0, 1e8)
            it += 1
            cur = float(np.max(np.abs(F)))
            if not improved:
                break
            if cur > best * 0.999999 and cur >= tol:
                stall += 1
                if stall > 6:
                    best = cur
                    break
            else:
                stall = 0
            best = cur
        final = self.residual(mates, extra)
        return float(np.max(np.abs(final))) < tol * 1.0 or best < tol, it, float(np.max(np.abs(final))) if final.size else 0.0

    def system_for(self, free, mates, extra):
        col = {c: 6 * i for i, c in enumerate(free)}
        n = 6 * len(free)
        total = sum(self.mate_res(m).size for m in mates) + (3 * len(extra) if extra else 0)
        F = np.zeros(total)
        J = np.zeros((total, n))
        r = 0
        for m in mates:
            f0 = self.mate_res(m)
            F[r:r + f0.size] = f0
            for c, block in self.jac_mate(m, f0, False).items():
                if c in col:
                    J[r:r + f0.size, col[c]:col[c] + 6] = block
            r += f0.size
        for c, lp, target, w in extra or []:
            b = self.bodies[c]
            F[r:r + 3] = w * (b.R @ lp + b.t - target)
            if c in col:
                J[r:r + 3, col[c]:col[c] + 3] = w * np.eye(3)
                J[r:r + 3, col[c] + 3:col[c] + 6] = -w * rig.skew(b.R @ lp) / self.L
            r += 3
        return free, F, J

    def solve(self, mates=None, extra=None, retries=2, **kw):
        mates = self.active(mates)
        t0 = time.perf_counter()
        start = self.snapshot()
        ok, it, res = self.lm(mates, extra, **kw)
        tries = 0
        while not ok and tries < retries and mates:
            tries += 1
            self.restore(start)
            for c in self.free_ids(mates):
                b = self.bodies[c]
                b.t = b.t + self.rng.normal(0.0, 0.01 * self.L, 3)
                b.R = rig.orthonormal(rig.expm(self.rng.normal(0.0, 0.02, 3)) @ b.R)
            ok, it2, res = self.lm(mates, extra, **kw)
            it += it2
        rep = Report()
        rep.ok, rep.iterations, rep.residual = ok, it, res
        if not ok:
            self.restore(start)
            rep.message = "The mates cannot all be satisfied."
        else:
            for m in mates:
                eqs.update_state(m, self.worlds(m))
        rep.ms = (time.perf_counter() - t0) * 1000.0
        return rep

    def feasible(self, mates, start):
        snap = self.snapshot()
        self.restore(start)
        rep = self.solve(mates, retries=1, max_it=40)
        self.restore(snap)
        return rep.ok

    def prepare(self, m):
        eqs.resolve(m, self.worlds_with_frames(m))
        return m

    def worlds_with_frames(self, m):
        return self.worlds(m)

    def drag(self, cid, local_point, target, weight=DRAG_W, polish=True):
        t0 = time.perf_counter()
        b = self.bodies[cid]
        if b.fixed:
            raise eqs.MateError("A fixed component cannot be dragged.")
        mates = self.active()
        start = self.snapshot()
        lp = np.asarray(local_point, dtype=float)
        tg = np.asarray(target, dtype=float)
        extra = [(cid, lp, tg, weight)]
        gap0 = float(np.linalg.norm(b.R @ lp + b.t - tg))
        self.descend(mates, extra, b, lp, tg, gap0, polish)
        rep = Report()
        if polish:
            rep2 = self.solve(mates, retries=0, max_it=60)
            rep.ok, rep.iterations, rep.residual = rep2.ok, rep2.iterations, rep2.residual
            if not rep2.ok:
                self.restore(start)
                rep.message = "The drag leaves the mates unsatisfied; the component stays."
            elif gap0 - float(np.linalg.norm(b.R @ lp + b.t - tg)) < 1e-9 * self.L and gap0 > 1e-6 * self.L:
                best = (self.snapshot(), gap0)
                for scale in (1e-3, 1e-2, 5e-2):
                    self.restore(start)
                    for c in self.free_ids(mates):
                        fb = self.bodies[c]
                        fb.t = fb.t + self.rng.normal(0.0, scale * self.L, 3)
                        fb.R = rig.orthonormal(rig.expm(self.rng.normal(0.0, scale, 3)) @ fb.R)
                    if not self.solve(mates, retries=0, max_it=60).ok:
                        continue
                    self.descend(mates, extra, b, lp, tg, float(np.linalg.norm(b.R @ lp + b.t - tg)), polish)
                    if not self.solve(mates, retries=0, max_it=60).ok:
                        continue
                    gap = float(np.linalg.norm(b.R @ lp + b.t - tg))
                    if gap < best[1] - 1e-6 * self.L:
                        best = (self.snapshot(), gap)
                        break
                self.restore(best[0] if best[1] < gap0 else start)
                rep.ok = True
        rep.ms = (time.perf_counter() - t0) * 1000.0
        return rep

    def descend(self, mates, extra, b, lp, tg, prev, polish=True):
        gap = prev
        for _ in range(80):
            moved = False
            for frac in (1.0, 0.5, 0.25, 0.1):
                keep = self.snapshot()
                if not self.tangent_step(mates, extra, frac):
                    break
                if polish:
                    self.solve(mates, retries=0, max_it=20)
                gap = float(np.linalg.norm(b.R @ lp + b.t - tg))
                if gap < prev - 1e-9 * self.L:
                    moved = True
                    break
                self.restore(keep)
            if not moved or prev - gap < 1e-7 * self.L:
                break
            prev = gap
        return gap

    def tangent_step(self, mates, extra, frac=1.0):
        free = self.free_ids(mates)
        for c, *_ in extra:
            if c not in free and not self.bodies[c].fixed:
                free.append(c)
        w = extra[0][3]
        _, F, J = self.system_for(free, mates, extra)
        k = len(extra) * 3
        Js, rs = J[-k:] / w, F[-k:] / w
        sides = self.one_sided(mates)
        eq = [i for i in range(J.shape[0] - k) if i not in sides]
        dx = self.null_step(J[eq], Js, rs)
        if dx is None:
            return False
        if sides:
            snap = self.snapshot()
            before = self.residual(mates)
            self.step(free, dx * frac)
            after = self.residual(mates)
            self.restore(snap)
            hit = [i for i in sides if abs(after[i]) > abs(before[i]) + 1e-9 * self.L]
            if hit:
                dx = self.null_step(np.vstack([J[eq], self.side_rows(free, mates, hit)]), Js, rs)
                if dx is None:
                    return False
        self.step(free, dx * frac)
        return True

    def null_step(self, Jh, Js, rs):
        if Jh.shape[0]:
            _, s, Vt = np.linalg.svd(Jh, full_matrices=True)
            rank = int(np.sum(s > 1e-7 * max(s[0], 1e-30)))
            N = Vt[rank:].T
        else:
            N = np.eye(Js.shape[1])
        if N.shape[1] == 0:
            return None
        dx = N @ np.linalg.lstsq(Js @ N, -rs, rcond=1e-6)[0]
        big = float(np.max(np.abs(dx))) if dx.size else 0.0
        if big < 1e-12 * self.L:
            return None
        limit = 0.25 * self.L
        return dx * (limit / big) if big > limit else dx

    def one_sided(self, mates):
        out, r = [], 0
        for m in mates:
            n = self.mate_res(m).size
            if m.kind in ("limitdistance", "limitangle") or (m.kind == "slot" and m.opt.get("position", "free") not in ("centre", "center")):
                out.append(r + n - 1)
            r += n
        return out

    def side_rows(self, free, mates, rows):
        col = {c: 6 * i for i, c in enumerate(free)}
        out = np.zeros((len(rows), 6 * len(free)))
        r = 0
        for m in mates:
            f0 = self.mate_res(m)
            for j, row in enumerate(rows):
                if r <= row < r + f0.size:
                    for c, block in self.jac_mate(m, f0, True).items():
                        if c in col:
                            out[j, col[c]:col[c] + 6] = block[row - r]
            r += f0.size
        return out

    def lm_soft(self, mates, extra, max_it=40):
        free = self.free_ids(mates)
        for c, *_ in extra:
            if c not in free and not self.bodies[c].fixed:
                free.append(c)
        n = 6 * len(free)
        winv = np.ones(n)
        lam = 1e-9
        limit = 0.25 * self.L
        for _ in range(max_it):
            if float(np.max(np.abs(self.extra_res(extra)))) < 1e-9 * self.L * extra[0][3]:
                break
            _, F, J = self.system_for(free, mates, extra)
            nf = float(F @ F)
            JW = J * winv
            A = JW @ J.T
            dx = None
            for _try in range(10):
                z = np.linalg.solve(A + lam * np.eye(A.shape[0]) * max(1e-12, float(np.trace(A)) / max(A.shape[0], 1)), -F)
                dx = JW.T @ z
                big = float(np.max(np.abs(dx))) if dx.size else 0.0
                if big > limit:
                    dx = dx * (limit / big)
                snap = self.snapshot()
                self.step(free, dx)
                Fn = self.residual(mates, extra)
                if float(Fn @ Fn) < nf:
                    lam = max(lam * 0.3, 1e-14)
                    break
                self.restore(snap)
                lam = min(lam * 6.0, 1e8)
                dx = None
            if dx is None or float(np.max(np.abs(dx))) < 1e-12 * self.L:
                break
            if (nf - float(Fn @ Fn)) < 1e-12 * max(nf, 1e-30):
                break

    def analyse(self, mates=None):
        mates = self.active(mates)
        free = self.free_ids(mates)
        unmated = [c for c, b in self.bodies.items() if not b.fixed and c not in free]
        if mates:
            _, F, J = self.system(mates, None, central=True)
        else:
            F, J = np.zeros(0), np.zeros((0, 6 * len(free)))
        rows = []
        r = 0
        for m in mates:
            k = self.mate_res(m).size
            rows.append((m, r, r + k))
            r += k
        norms = np.linalg.norm(J, axis=1) if J.size else np.zeros(0)
        live = norms > 1e-9
        Jn = J.copy()
        if J.size:
            Jn[live] = J[live] / norms[live][:, None]
        out = {"rank": 0, "nullity": 6 * len(free), "mates": [], "components": {}, "groups": [], "dof": 0, "residual": float(np.max(np.abs(F))) if F.size else 0.0}
        cum = np.zeros((0, J.shape[1]))
        rank_c = 0
        inactive = []
        for m, a, b in rows:
            blk = Jn[a:b][live[a:b]]
            own = int(np.linalg.matrix_rank(blk, tol=RANK_TOL)) if blk.size else 0
            if blk.size == 0:
                inactive.append(m.id)
                out["mates"].append({"id": m.id, "rows": b - a, "removes": 0, "added": 0, "state": "inactive" if m.kind.startswith("limit") else "empty", "redundant": False})
                continue
            test = np.vstack([cum, blk])
            nr = int(np.linalg.matrix_rank(test, tol=RANK_TOL)) if test.size else 0
            added = nr - rank_c
            cum, rank_c = test, nr
            out["mates"].append({"id": m.id, "rows": b - a, "removes": own, "added": added, "state": "active", "redundant": added == 0 and own > 0, "overlap": own - added})
        out["rank"] = rank_c
        groups = self.groups(mates)
        total = 0
        for g in groups:
            gi = [c for c in g["bodies"] if c in free]
            cols = []
            for c in gi:
                i = free.index(c)
                cols += list(range(6 * i, 6 * i + 6))
            gm = [(m, a, b) for m, a, b in rows if any(c in g["bodies"] for c in m.comps())]
            ridx = [i for m, a, b in gm for i in range(a, b) if live[i]]
            sub = Jn[np.ix_(ridx, cols)] if (ridx and cols) else np.zeros((0, len(cols)))
            k = len(cols)
            if k == 0:
                g.update(nullity=0, internal=0)
                continue
            if sub.shape[0]:
                _, s, vt = np.linalg.svd(sub, full_matrices=True)
            else:
                s, vt = np.zeros(0), np.eye(k)
            rk = int(np.sum(s > RANK_TOL))
            N = vt[rk:].T
            g["nullity"] = k - rk
            if not g["grounded"]:
                R6 = self.rigid_modes(gi)
                N = self.complement(N, R6)
                g["internal"] = N.shape[1]
            else:
                g["internal"] = N.shape[1]
            total += g["internal"]
            g["null"] = (gi, N)
        for c in unmated:
            total += 6
            groups.append({"bodies": [c], "grounded": False, "internal": 6, "nullity": 6, "free": True, "null": None})
        out["dof"] = total
        for g in groups:
            nb = g.get("null")
            for c in g["bodies"]:
                b = self.bodies[c]
                if b.fixed:
                    out["components"][c] = {"dof": 0, "state": "fixed", "modes": []}
                    continue
                if nb is None:
                    out["components"][c] = {"dof": 6, "state": "free", "modes": self.free_modes(b)}
                    continue
                gi, N = nb
                i = gi.index(c)
                blk = N[6 * i:6 * i + 6, :]
                if blk.size:
                    u, s, _ = np.linalg.svd(blk, full_matrices=False)
                    d = int(np.sum(s > 1e-7))
                    modes = [self.twist(b, u[:, j] * 1.0) for j in range(d)]
                else:
                    d, modes = 0, []
                out["components"][c] = {"dof": d, "state": "fully" if d == 0 else "under", "modes": modes}
        for g in groups:
            g.pop("null", None)
        out["groups"] = groups
        return out

    def free_modes(self, b):
        eye = np.eye(3)
        return [{"type": "translation", "dir": eye[i].tolist()} for i in range(3)] + [{"type": "rotation", "dir": eye[i].tolist(), "point": b.t.tolist()} for i in range(3)]

    def twist(self, b, y):
        v = np.asarray(y[:3], dtype=float)
        w = np.asarray(y[3:], dtype=float) / self.L
        nv, nw = float(np.linalg.norm(v)), float(np.linalg.norm(w))
        tn = nv + nw * self.L
        if tn < 1e-12:
            return {"type": "none"}
        v, w = v / tn, w / tn
        if nw * self.L < 1e-6 * tn:
            return {"type": "translation", "dir": rig.unit(v).tolist()}
        nw = float(np.linalg.norm(w))
        k = w / nw
        pt = b.t + np.cross(w, v) / (nw * nw)
        pitch = float(w @ v) / (nw * nw)
        if abs(pitch) < 1e-6 * self.L:
            return {"type": "rotation", "dir": k.tolist(), "point": pt.tolist()}
        return {"type": "screw", "dir": k.tolist(), "point": pt.tolist(), "pitch": pitch * 2.0 * math.pi}

    def groups(self, mates):
        parent = {}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for c in self.bodies:
            parent[c] = c
        grounded = set()
        for m in mates:
            cs = [c for c in m.comps() if c in self.bodies]
            if len(cs) < len(m.sides):
                grounded.update(cs)
            for a in cs[1:]:
                parent[find(a)] = find(cs[0])
        for c, b in self.bodies.items():
            if b.fixed:
                grounded.add(c)
        gmap = {}
        for c in self.bodies:
            gmap.setdefault(find(c), []).append(c)
        gset = {find(c) for c in grounded}
        used = set()
        for m in mates:
            for c in m.comps():
                used.add(c)
        out = []
        for root, members in gmap.items():
            if not any(c in used for c in members) and not any(self.bodies[c].fixed for c in members):
                continue
            out.append({"bodies": members, "grounded": root in gset})
        return out

    def rigid_modes(self, ids):
        centre = np.mean([self.bodies[c].t for c in ids], axis=0)
        cols = []
        for k in range(3):
            v = np.zeros(6 * len(ids))
            for i in range(len(ids)):
                v[6 * i + k] = 1.0
            cols.append(v)
        for k in range(3):
            e = np.zeros(3)
            e[k] = 1.0
            v = np.zeros(6 * len(ids))
            for i, c in enumerate(ids):
                v[6 * i:6 * i + 3] = np.cross(e, self.bodies[c].t - centre)
                v[6 * i + 3:6 * i + 6] = e * self.L
            cols.append(v)
        return np.array(cols).T

    @staticmethod
    def complement(N, R6):
        if N.shape[1] == 0:
            return N
        q, _ = np.linalg.qr(R6)
        P = N - q @ (q.T @ N)
        u, s, _ = np.linalg.svd(P, full_matrices=False)
        return u[:, s > 1e-7]

    def status(self, mates=None):
        mates = self.active(mates)
        an = self.analyse(mates)
        F = self.residual(mates)
        res = float(np.max(np.abs(F))) if F.size else 0.0
        redundant = [m["id"] for m in an["mates"] if m["redundant"]]
        if res > max(self.tol * 100, 1e-7):
            state = "conflict"
        elif redundant:
            state = "over"
        elif an["dof"] == 0 and mates:
            state = "fully"
        elif not mates:
            state = "none"
        else:
            state = "under"
        an["state"] = state
        an["redundant"] = redundant
        an["residual"] = res
        return an

    def clone_for(self, mates):
        return mates

    def conflict_set(self, mates, start, budget=8.0):
        mates = list(mates)
        t0 = time.perf_counter()
        exact = True
        cand = list(mates)
        for m in list(mates):
            if time.perf_counter() - t0 > budget:
                exact = False
                break
            rest = [k for k in cand if k.id != m.id]
            if not rest:
                continue
            if not self.feasible(rest, start):
                cand = rest
        return cand, exact

    def fixes(self, mates, start, within):
        out = []
        for m in within:
            rest = [k for k in mates if k.id != m.id]
            if self.feasible(rest, start):
                out.append(m)
        return out

    def redundant_set(self, mates, target):
        mates = self.active(mates)
        idx = [m.id for m in mates].index(target.id)
        before = mates[:idx]
        _, F, J = self.system(before + [target], None, central=True)
        r = 0
        spans = {}
        for m in before + [target]:
            k = self.mate_res(m).size
            spans[m.id] = (r, r + k)
            r += k
        norms = np.linalg.norm(J, axis=1)
        Jn = J / np.where(norms > 1e-9, norms, 1.0)[:, None]

        def dependent(ids):
            others = [i for mid in ids if mid != target.id for i in range(*spans[mid]) if norms[i] > 1e-9]
            mine = [i for i in range(*spans[target.id]) if norms[i] > 1e-9]
            own = np.linalg.matrix_rank(Jn[mine], tol=RANK_TOL) if mine else 0
            ro = np.linalg.matrix_rank(Jn[others], tol=RANK_TOL) if others else 0
            ra = np.linalg.matrix_rank(Jn[others + mine], tol=RANK_TOL) if (others or mine) else 0
            return ra - ro < own

        cand = [m.id for m in before]
        for mid in list(cand):
            rest = [i for i in cand if i != mid]
            if dependent(rest + [target.id]):
                cand = rest
        return cand + [target.id]
