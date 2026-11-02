import numpy as np

RANK_TOL = 1e-7
FWD_STEP = 1e-7
CTR_STEP = 1e-6


class Cons:
    __slots__ = ("id", "kind", "group", "refs", "value", "name", "rows", "vars", "fn", "ctx", "ents")

    def __init__(self, cid, kind, group, refs, value, name, rows, vars_, fn, ctx, ents):
        self.id = cid
        self.kind = kind
        self.group = group
        self.refs = refs
        self.value = value
        self.name = name
        self.rows = rows
        self.vars = vars_
        self.fn = fn
        self.ctx = ctx
        self.ents = ents


def local_jacobian(c, x, central):
    f0 = c.fn(x)
    idx = c.vars
    J = np.empty((f0.size, len(idx)))
    h0 = CTR_STEP if central else FWD_STEP
    for k, i in enumerate(idx):
        xi = x[i]
        h = h0 * max(1.0, abs(xi))
        x[i] = xi + h
        fp = c.fn(x)
        if central:
            x[i] = xi - h
            fm = c.fn(x)
            J[:, k] = (fp - fm) / (2.0 * h)
        else:
            J[:, k] = (fp - f0) / h
        x[i] = xi
    return f0, J


def assemble(cons, x, cmap, n, central=False):
    m = sum(c.rows for c in cons)
    F = np.empty(m)
    J = np.zeros((m, n))
    r = 0
    for c in cons:
        f, Jl = local_jacobian(c, x, central)
        F[r:r + c.rows] = f
        cols = [cmap[i] for i in c.vars]
        J[r:r + c.rows, cols] = Jl
        r += c.rows
    return F, J


def residual(cons, x):
    if not cons:
        return np.zeros(0)
    return np.concatenate([c.fn(x) for c in cons])


def solve_system(cons, x0, weights, tol_rel=1e-10, max_it=200):
    cols = sorted({int(i) for c in cons for i in c.vars})
    cmap = {c: k for k, c in enumerate(cols)}
    n = len(cols)
    x = x0.copy()
    m = sum(c.rows for c in cons)
    if m == 0:
        return True, x, 0, 0.0
    scale = max(1.0, float(np.max(np.abs(x[cols]))))
    tol = tol_rel * scale
    winv = 1.0 / weights[cols]
    F, J = assemble(cons, x, cmap, n)
    nf = float(np.max(np.abs(F)))
    lam = 1e-8
    it = 0
    stall = 0
    eye = np.eye(m)
    while it < max_it and nf > tol:
        it += 1
        A = (J * winv) @ J.T
        f2 = float(F @ F)
        accepted = False
        while lam < 1e12:
            try:
                y = np.linalg.solve(A + lam * eye, F)
            except np.linalg.LinAlgError:
                lam *= 10.0
                continue
            xt = x.copy()
            xt[cols] -= winv * (J.T @ y)
            Ft = residual(cons, xt)
            if float(Ft @ Ft) < f2:
                x = xt
                lam = max(lam * 0.1, 1e-12)
                accepted = True
                break
            lam *= 10.0
        if not accepted:
            break
        F, J = assemble(cons, x, cmap, n)
        nn = float(np.max(np.abs(F)))
        stall = stall + 1 if nn > 0.999 * nf else 0
        nf = nn
        if stall >= 8:
            break
    return nf <= tol * 10.0, x, it, nf


def normalize_rows(J):
    nr = np.linalg.norm(J, axis=1)
    out = J.copy()
    live = nr > 1e-12
    out[live] /= nr[live][:, None]
    return out, live


def numeric_rank(J):
    if J.size == 0:
        return 0
    s = np.linalg.svd(J, compute_uv=False)
    if s.size == 0 or s[0] <= 1e-12:
        return 0
    return int(np.sum(s > RANK_TOL * s[0]))


def null_basis(J, n):
    if J.shape[0] == 0:
        return np.eye(n)
    _, s, Vt = np.linalg.svd(J, full_matrices=True)
    rank = int(np.sum(s > RANK_TOL * s[0])) if s.size and s[0] > 1e-12 else 0
    return Vt[rank:].T


def dependent_rows(Jn, live, owners):
    basis = []
    kept = []
    kept_owner = []
    out = {}
    for r in range(Jn.shape[0]):
        row = Jn[r]
        if not live[r]:
            out.setdefault(owners[r], []).append([])
            continue
        v = row.copy()
        for _ in range(2):
            for b in basis:
                v -= (v @ b) * b
        if np.linalg.norm(v) > RANK_TOL:
            basis.append(v / np.linalg.norm(v))
            kept.append(row)
            kept_owner.append(owners[r])
        else:
            B = np.array(kept)
            coef = np.linalg.lstsq(B.T, row, rcond=None)[0] if len(kept) else np.zeros(0)
            names = sorted({kept_owner[i] for i in range(len(kept)) if abs(coef[i]) > 1e-6})
            out.setdefault(owners[r], []).append(names)
    return out
