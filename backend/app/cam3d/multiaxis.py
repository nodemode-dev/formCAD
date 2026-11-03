import math

import numpy as np

from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam3d import kinematics
from app.cam3d.kinematics import Reach, TableTable
from app.cam3d.paths3d import scallop_step


def machine_of(rec_id: str):
    from app.cam3d import machines

    try:
        return TableTable(machines.get(rec_id or "mill5_table_table"))
    except KeyError as err:
        raise CamError(str(err.args[0]) if err.args else "There is no such machine.")


def rails_of(geometry: dict):
    if not geometry or geometry.get("kind") != "ruled":
        raise CamError("This operation needs a ruled surface: geometry {\"kind\": \"ruled\", \"rails\": [[[x,y,z],...], [[x,y,z],...]]} in the WCS.")
    rails = geometry.get("rails")
    if not isinstance(rails, list) or len(rails) != 2:
        raise CamError("A ruled surface takes exactly two rails.")
    out = []
    for r in rails:
        a = np.asarray(r, dtype=float)
        if a.ndim != 2 or a.shape[1] != 3 or len(a) < 2 or not np.isfinite(a).all():
            raise CamError("Each rail needs at least two points with x, y and z.")
        if len(a) > 20000:
            raise CamError("A rail has more than 20000 points.")
        out.append(a)
    return out


def resample(a, n):
    seg = np.linalg.norm(np.diff(a, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] < 1e-9:
        raise CamError("A rail has no length.")
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, a[:, i]) for i in range(3)], axis=1), s[-1]


def unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


def densify(tips, axes, max_deg: float, max_len: float):
    out_p, out_k = [tips[0]], [axes[0]]
    for i in range(1, len(tips)):
        ang = math.degrees(math.acos(min(max(float(np.dot(axes[i - 1], axes[i])), -1.0), 1.0)))
        ln = float(np.linalg.norm(tips[i] - tips[i - 1]))
        n = max(int(math.ceil(ang / max_deg)), int(math.ceil(ln / max_len)), 1)
        for s in range(1, n + 1):
            t = s / n
            p = tips[i - 1] * (1 - t) + tips[i] * t
            k = axes[i - 1] * (1 - t) + axes[i] * t
            out_p.append(p)
            out_k.append(k / np.linalg.norm(k))
    return np.array(out_p), np.array(out_k)


def swarf_pass(rails, cu_R, stl, side, step, max_deg, flute, warn, protect=True):
    A, B = rails
    L = max(np.linalg.norm(np.diff(A, axis=0), axis=1).sum(), np.linalg.norm(np.diff(B, axis=0), axis=1).sum())
    n = max(int(math.ceil(L / step)) + 1, 2)
    Ar, _ = resample(A, n)
    Br, _ = resample(B, n)
    d = Br - Ar
    ln = np.linalg.norm(d, axis=1)
    if (ln < 1e-6).any():
        raise CamError("The rails touch each other, so there is no ruling to follow.")
    k = d / ln[:, None]
    low = np.where((d[:, 2] >= 0)[:, None], Ar, Br)
    k = np.where((d[:, 2] >= 0)[:, None], k, -k)
    tang = np.gradient(low, axis=0)
    nrm = unit(np.cross(tang, k))
    if side == "negative":
        nrm = -nrm
    elif side == "up":
        nrm = np.where((nrm[:, 2] < 0)[:, None], -nrm, nrm)
    elif side == "down":
        nrm = np.where((nrm[:, 2] > 0)[:, None], -nrm, nrm)
    nrm = unit(nrm - (nrm * k).sum(axis=1, keepdims=True) * k)
    tips = low + (cu_R + stl) * nrm
    if protect:
        kz = np.maximum(k[:, 2], 1e-3)
        need = low[:, 2] + stl + cu_R * np.sqrt(np.maximum(1.0 - k[:, 2] ** 2, 0.0)) - tips[:, 2]
        tips = tips + np.maximum(need, 0.0)[:, None] / kz[:, None] * k
    if ln.max() > flute:
        warn("The ruling is %.1f mm long, more than the flute length %.1f mm; the tool cannot cut the whole wall in one pass." % (ln.max(), flute))
    dev = np.degrees(np.arccos(np.clip((k[1:] * k[:-1]).sum(axis=1), -1, 1)))
    if dev.size and dev.max() > 8.0:
        warn("The rulings turn by up to %.1f degrees between samples; the surface is probably not developable and the flank will not follow it exactly." % dev.max())
    return (*densify(tips, k, max_deg, step), nrm[0] * (2.0 * cu_R + 2.0)), ln.max()


def flowline_passes(rails, R, stl, side, scallop, lead, tilt, step, max_deg, warn, stepover=None):
    A, B = rails
    L = max(np.linalg.norm(np.diff(A, axis=0), axis=1).sum(), np.linalg.norm(np.diff(B, axis=0), axis=1).sum())
    nu = max(int(math.ceil(L / step)) + 1, 3)
    Ar, _ = resample(A, nu)
    Br, _ = resample(B, nu)
    width = float(np.linalg.norm(Br - Ar, axis=1).mean())
    ds = stepover if stepover else scallop_step(R, scallop)
    nv = max(int(math.ceil(width / ds)) + 1, 2)
    vs = np.linspace(0.0, 1.0, nv)
    out = []
    for j, v in enumerate(vs):
        S = Ar * (1 - v) + Br * v
        Su = np.gradient(S, axis=0)
        Sv = Br - Ar
        n = unit(np.cross(Su, Sv))
        if side == "negative":
            n = -n
        elif side == "up":
            n = np.where((n[:, 2] < 0)[:, None], -n, n)
        t = unit(Su)
        if j % 2 == 1:
            S, n, t = S[::-1], n[::-1], -t[::-1]
        la, ti = math.radians(lead), math.radians(tilt)
        side_v = unit(np.cross(n, t))
        k = unit(n * math.cos(la) * math.cos(ti) + t * math.sin(la) * math.cos(ti) + side_v * math.sin(ti))
        center = S + (R + stl) * n
        tips = center - R * k
        out.append(densify(tips, k, max_deg, step))
    return out, ds


def solve_pass(machine: TableTable, tips, axes, prev):
    sol = []
    for p, k in zip(tips, axes):
        try:
            s = machine.solve(p, k, prev)
        except Reach as err:
            raise CamError(str(err) + " Change the side, the lead and tilt angles or the machine limits.")
        prev = {"a": s["a"], "c": s["c"]}
        sol.append(s)
    return sol, prev


def emit(ctx, f, machine, passes, retract, approach, max_rot_jump=45.0):
    moves = common.start_moves(ctx, f)
    prev = None
    first = True
    for item in passes:
        tips, axes = item[0], item[1]
        lat = item[2] if len(item) > 2 else None
        sol, prev_new = solve_pass(machine, tips, axes, prev)
        jumps = [max(abs(sol[i]["a"] - sol[i - 1]["a"]), abs(sol[i]["c"] - sol[i - 1]["c"])) for i in range(1, len(sol))]
        if jumps and max(jumps) > max_rot_jump:
            ctx.warn("A rotary axis jumps by %.0f degrees between two samples, probably near a singularity (tool axis near vertical)." % max(jumps))
        p0, k0 = tips[0], axes[0]
        s0 = sol[0]
        opt0 = lambda kind, p=None, k=None, s=None: {"k": kind, "ax": [round(float(v), 6) for v in (k if k is not None else k0)], "abc": [round(s["a"] if s else s0["a"], 4), 0.0, round(s["c"] if s else s0["c"], 4)]}
        lat_v = np.zeros(3) if lat is None else np.asarray(lat, dtype=float)
        safe = p0 + lat_v + k0 * (retract + approach)
        near = p0 + lat_v + (k0 * approach if lat is None else 0.0)
        if prev is not None:
            pl, kl = last
            pr = pl + kl * retract
            moves.append(["rapid", float(pr[0]), float(pr[1]), float(pr[2]), opt0("retract", None, kl, prev)])
        moves.append(["rapid", float(safe[0]), float(safe[1]), float(safe[2]), opt0("approach")])
        moves.append(["rapid", float(near[0]), float(near[1]), float(near[2]), opt0("approach")])
        moves.append(["feed", float(p0[0]), float(p0[1]), float(p0[2]), f["vf_plunge"], opt0("plunge")])
        for p, k, s in zip(tips[1:], axes[1:], sol[1:]):
            moves.append(["feed", float(p[0]), float(p[1]), float(p[2]), f["vf_cut"], opt0("cut", None, k, s)])
        prev = prev_new
        last = (tips[-1], axes[-1])
    pl, kl = last
    pr = pl + kl * retract
    moves.append(["rapid", float(pr[0]), float(pr[1]), float(pr[2]), {"k": "retract", "ax": [round(float(v), 6) for v in kl], "abc": [round(prev["a"], 4), 0.0, round(prev["c"], 4)]}])
    return moves
