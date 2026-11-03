import math

import numpy as np

from app.probing import expr as E

STEP = 0.02
MAX_STEPS = 20000


class SimError(ValueError):
    pass


class Solid:
    def __init__(self, kind, z0, z1, **kw):
        self.kind = kind
        self.z0 = z0
        self.z1 = z1
        self.kw = kw

    def sdf(self, P):
        if self.kind == "circle":
            c = np.asarray(self.kw["c"], float)
            return np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]) - self.kw["r"]
        poly = np.asarray(self.kw["pts"], float)
        d = seg_distance(P, poly)
        ins = inside(P, poly)
        out = np.where(ins, -d, d)
        for h in self.kw.get("holes", []):
            hc = np.asarray(h["c"], float)
            out = np.maximum(out, h["r"] - np.hypot(P[:, 0] - hc[0], P[:, 1] - hc[1]))
        return out


def seg_distance(P, poly):
    A = poly
    B = np.roll(poly, -1, axis=0)
    d = B - A
    L = (d ** 2).sum(axis=1)
    L[L == 0] = 1e-18
    diff = P[:, None, :] - A[None, :, :]
    t = np.clip((diff * d[None, :, :]).sum(axis=2) / L[None, :], 0.0, 1.0)
    proj = A[None, :, :] + t[:, :, None] * d[None, :, :]
    return np.sqrt(((P[:, None, :] - proj) ** 2).sum(axis=2)).min(axis=1)


def inside(P, poly):
    x, y = P[:, 0][:, None], P[:, 1][:, None]
    xi, yi = poly[:, 0][None, :], poly[:, 1][None, :]
    xj, yj = np.roll(poly[:, 0], 1)[None, :], np.roll(poly[:, 1], 1)[None, :]
    cond = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / np.where(yj - yi == 0, 1e-18, yj - yi) + xi)
    return cond.sum(axis=1) % 2 == 1


def reff(zc, z0, z1, r):
    out = np.full(zc.shape, -1e9)
    mid = (zc >= z0) & (zc <= z1)
    out = np.where(mid, r, out)
    up = (zc > z1) & (zc < z1 + r)
    out = np.where(up, np.sqrt(np.maximum(r * r - (zc - z1) ** 2, 0.0)), out)
    dn = (zc < z0) & (zc > z0 - r)
    out = np.where(dn, np.sqrt(np.maximum(r * r - (z0 - zc) ** 2, 0.0)), out)
    return out


class World:
    def __init__(self, solids, origin, radius):
        self.solids = solids
        self.origin = list(origin)
        self.r = radius
        self.crashes = []
        self.pos = None
        self.env = {}
        self.rot = 0.0
        self.log = []

    def gap(self, P3):
        P = np.asarray(P3, float)
        g = np.full(len(P), 1e9)
        for s in self.solids:
            rr = reff(P[:, 2], s.z0, s.z1, self.r)
            ok = rr > -1e8
            val = s.sdf(P[:, :2]) - rr
            g = np.where(ok, np.minimum(g, val), g)
        return g

    def sweep(self, a, b, step=STEP, thresh=0.0):
        a = np.asarray(a, float)
        b = np.asarray(b, float)
        L = float(np.linalg.norm(b - a))
        n = max(2, min(MAX_STEPS, int(L / step) + 1))
        ts = np.linspace(0.0, 1.0, n)
        P = a[None, :] + ts[:, None] * (b - a)[None, :]
        g = self.gap(P)
        hit = np.nonzero(g <= thresh)[0]
        if len(hit) == 0:
            return None
        i = int(hit[0])
        if i == 0:
            return 0.0
        lo, hi = ts[i - 1], ts[i]
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.gap((a + mid * (b - a))[None, :])[0] <= thresh:
                hi = mid
            else:
                lo = mid
        return hi


def machine(world, p):
    return (world.origin[0] + p[0], world.origin[1] + p[1], world.origin[2] + p[2])


def target_of(world, m, env):
    ex = (m[-1] or {}).get("expr") if isinstance(m[-1], dict) else None
    x, y, z = float(m[1]), float(m[2]), float(m[3])
    if ex:
        if "x" in ex:
            x = E.evaluate(ex["x"], env)
        if "y" in ex:
            y = E.evaluate(ex["y"], env)
        if "z" in ex:
            z = E.evaluate(ex["z"], env)
    return (x, y, z)


def run(moves, world, start):
    world.pos = tuple(start)
    env = world.env
    for slot in range(1, 10):
        base = 5221 + 20 * (slot - 1)
        for i, ax in enumerate("xyz"):
            env["p%d" % (base + i)] = world.origin["xyz".index(ax)] if slot == 1 else 0.0
        env["p%d" % (base + 9)] = 0.0
    probes = 0
    for m in moves:
        k = m[0]
        o = m[-1] if isinstance(m[-1], dict) else {}
        if k in ("rapid", "feed"):
            tgt = target_of(world, m, env)
            a = machine(world, world.pos)
            b = machine(world, tgt)
            hit = world.sweep(a, b, STEP, 0.0 if o.get("probe") else -0.01)
            if o.get("probe"):
                probes += 1
                if hit is None:
                    if o["probe"] in ("g38.2", "g38.4"):
                        raise SimError("Probe move %d reached its end without contact." % probes)
                    world.pos = tgt
                    continue
                pt = tuple(np.asarray(a) + hit * (np.asarray(b) - np.asarray(a)))
                loc = (pt[0] - world.origin[0], pt[1] - world.origin[1], pt[2] - world.origin[2])
                name = o["store"]
                for ax, v in zip("xyz", loc):
                    env["%s_%s" % (name, ax)] = v
                world.pos = loc
                world.log.append(("contact", name, loc))
            else:
                if hit is not None and hit < 1.0 and k == "rapid":
                    world.crashes.append((world.pos, tgt))
                world.pos = tgt
        elif k == "param":
            env[m[1]] = E.evaluate(m[2], env)
        elif k == "wcs_set":
            slot = int(m[1])
            base = 5221 + 20 * (slot - 1)
            for ax, ex in m[2].items():
                v = E.evaluate(ex, env)
                if ax == "r":
                    env["p%d" % (base + 9)] = v
                    world.rot = v
                else:
                    i = "xyz".index(ax)
                    env["p%d" % (base + i)] = v
                    world.origin[i] = v
    return {"env": env, "origin": list(world.origin), "crashes": world.crashes, "probes": probes, "rot": world.rot}
