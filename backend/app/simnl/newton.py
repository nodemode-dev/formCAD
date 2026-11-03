import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl


class Cancelled(Exception):
    pass


class SolveFailed(RuntimeError):
    pass


class Problem:
    def __init__(self, X0, solids, fixed, fvec, contact=None, sequence="together"):
        self.sequence = sequence
        self.X0 = np.asarray(X0, dtype=float)
        self.nn = len(self.X0)
        self.ndof = 3 * self.nn
        self.solids = solids
        dofs = np.array(sorted(fixed), dtype=np.int64)
        self.fix = dofs
        self.fix_val = np.array([fixed[int(d)] for d in dofs], dtype=float)
        self.free = np.ones(self.ndof, dtype=bool)
        self.free[dofs] = False
        self.fref = np.zeros(self.ndof) if fvec is None else np.asarray(fvec, dtype=float)
        self.contact = contact
        self.floor = max([1.0e-10 * s.mat.E * s.geo.volume() ** (2.0 / 3.0) for s in solids] + [1.0e-20])

    def fscale(self, lam):
        return min(1.0, 2.0 * lam) if self.sequence == "loads_first" else lam

    def dscale(self, lam):
        return max(0.0, 2.0 * lam - 1.0) if self.sequence == "loads_first" else lam

    def internal(self, u, need_k=True):
        f = np.zeros(self.ndof)
        K = None
        auxs = []
        for s in self.solids:
            fi, Ki, aux = s.evaluate(u, need_k)
            f += fi
            if need_k:
                K = Ki if K is None else K + Ki
            auxs.append(aux)
        return f, K, auxs

    def snapshot(self):
        return [s.snapshot() for s in self.solids], (self.contact.snapshot() if self.contact else None)

    def restore(self, snap):
        for s, sn in zip(self.solids, snap[0]):
            s.restore(sn)
        if self.contact and snap[1] is not None:
            self.contact.restore(snap[1])


def linear_solve(K, r, free, deadline=None):
    idx = np.nonzero(free)[0]
    Kff = K[idx][:, idx].tocsc()
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError("The time budget ran out.")
    lu = spl.splu(Kff, permc_spec="MMD_AT_PLUS_A")
    x = lu.solve(-r[idx])
    if not np.all(np.isfinite(x)):
        raise np.linalg.LinAlgError("The tangent stiffness is singular.")
    out = np.zeros(len(r))
    out[idx] = x
    return out


def newton_step(prob, u, lam, tol, max_iter, deadline, cancel):
    fix, free = prob.fix, prob.free
    u = u.copy()
    u[fix] = prob.dscale(lam) * prob.fix_val
    fs = prob.fscale(lam)
    norms = []
    for it in range(max_iter + 1):
        if cancel and cancel():
            raise Cancelled()
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("The time budget ran out.")
        f, K, auxs = prob.internal(u, True)
        r = f - fs * prob.fref
        if prob.contact is not None:
            fc, Kc = prob.contact.evaluate(prob.X0.ravel() + u)
            r = r - fc
            K = K + Kc
        rn = float(np.linalg.norm(r[free]))
        ref = max(float(np.linalg.norm(fs * prob.fref)), float(np.linalg.norm(f[fix])) if len(fix) else 0.0, float(np.linalg.norm(fc)) if prob.contact is not None else 0.0, 1.0e-20)
        ref = max(ref, 1.0e-300)
        norms.append(rn / ref)
        if rn <= max(tol * ref, prob.floor):
            return True, u, it, norms, auxs, f, r
        if it == max_iter:
            break
        du = linear_solve(K, r, free, deadline)
        if not np.all(np.isfinite(du)):
            return False, u, it, norms, auxs, f, r
        u = u + du
        if np.linalg.norm(du) > 1.0e30:
            return False, u, it, norms, auxs, f, r
    return False, u, max_iter, norms, auxs, f, r


def solve_static(prob, steps=10, max_iter=25, tol=1.0e-8, max_halvings=6, cancel=None, progress=None, time_limit=None, al_max=8, pen_tol=None, stop_on_failure=False):
    failed_at = None
    deadline = None if time_limit is None else time.monotonic() + float(time_limit)
    u = np.zeros(prob.ndof)
    lam = 0.0
    d0 = 1.0 / steps
    dlam = d0
    halv = 0
    history = []
    t0 = time.monotonic()
    contact = prob.contact
    last = None
    total_it = 0
    while lam < 1.0 - 1.0e-12:
        target = min(1.0, lam + dlam)
        snap = prob.snapshot()
        ok = False
        iters = 0
        norms = []
        al_rounds = 0
        try:
            ok, un, it, norms, auxs, f, r = newton_step(prob, u, target, tol, max_iter, deadline, cancel)
            iters = it
            if ok and contact is not None and contact.method == "augmented":
                while True:
                    limit = pen_tol if pen_tol is not None else 1.0e-4
                    if contact.imbalance() <= limit or al_rounds >= al_max:
                        break
                    al_rounds += 1
                    contact.advance_multipliers()
                    ok, un, it, norms, auxs, f, r = newton_step(prob, un, target, tol, max_iter, deadline, cancel)
                    iters += it
                    if not ok:
                        break
        except (np.linalg.LinAlgError, ArithmeticError, RuntimeError):
            ok = False
        if ok:
            for s, aux in zip(prob.solids, auxs):
                s.commit(aux)
            if contact is not None:
                contact.commit(prob.X0.ravel() + un)
            u = un
            lam = target
            total_it += iters
            react = np.zeros(prob.ndof)
            fc_last = contact.evaluate(prob.X0.ravel() + u, False)[0] if contact is not None else 0.0
            react[prob.fix] = (f - prob.fscale(lam) * prob.fref - fc_last)[prob.fix]
            rec = {"lambda": lam, "iterations": iters, "residuals": norms, "al_rounds": al_rounds, "reaction": react[prob.fix].copy(), "umax": float(np.abs(u).max()), "reaction_total": [float(react[c::3].sum()) for c in range(3)]}
            if contact is not None:
                rec["contact"] = dict(contact.last)
            history.append(rec)
            last = (f, auxs, react)
            if progress:
                progress(lam, "Load step %d reached %.4f of the load (%d iterations)." % (len(history), lam, iters))
            if iters <= 4 and dlam < d0:
                dlam = min(d0, dlam * 2.0)
            halv = max(0, halv - 1)
        else:
            prob.restore(snap)
            halv += 1
            dlam *= 0.5
            if halv > max_halvings or dlam < d0 / (2 ** (max_halvings + 2)):
                if stop_on_failure:
                    failed_at = lam
                    break
                raise SolveFailed("The Newton iteration did not converge at load factor %.4f after %d step halvings. Try more load steps, a softer contact stiffness, or a smaller load." % (lam, max_halvings))
            if progress:
                progress(lam, "Step did not converge, halving the load step to %.5f." % dlam)
    return {"u": u, "history": history, "iterations": total_it, "failed_at": failed_at, "reached": lam, "seconds": time.monotonic() - t0, "reaction": last[2] if last else None, "auxs": last[1] if last else None, "fint": last[0] if last else None}


def reaction_sum(prob, res, nodes, comp):
    f = res["reaction"]
    if f is None:
        return 0.0
    dof = np.asarray([3 * n + comp for n in nodes])
    return float(f[dof].sum())
