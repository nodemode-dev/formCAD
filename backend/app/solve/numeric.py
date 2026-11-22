import heapq
import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

RANK_TOL = 1e-7
FWD_STEP = 1e-7
CTR_STEP = 1e-6
SPARSE_ROWS = 48


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


def assemble_sparse(cons, x, cmap, n, central=False):
    m = sum(c.rows for c in cons)
    F = np.empty(m)
    ri, ci, vv = [], [], []
    r = 0
    for c in cons:
        f, Jl = local_jacobian(c, x, central)
        F[r:r + c.rows] = f
        cols = [cmap[i] for i in c.vars]
        k = len(cols)
        for j in range(c.rows):
            ri.extend([r + j] * k)
            ci.extend(cols)
            vv.extend(Jl[j].tolist())
        r += c.rows
    J = sp.csr_matrix((vv, (ri, ci)), shape=(m, n))
    J.eliminate_zeros()
    return F, J


def echelon(J, tol=RANK_TOL):
    J = J.tocsr()
    m, n = J.shape
    ip, ix, dv = J.indptr, J.indices, J.data
    piv = {}
    rank_of = {}
    rows = []
    dependent = []
    for r in range(m):
        a, b = ip[r], ip[r + 1]
        row = {int(c): float(v) for c, v in zip(ix[a:b], dv[a:b]) if v != 0.0}
        nr = math.sqrt(sum(v * v for v in row.values()))
        if nr <= 1e-12:
            dependent.append(r)
            continue
        for c in row:
            row[c] /= nr
        heap = [rank_of[c] for c in row if c in rank_of]
        heapq.heapify(heap)
        while heap:
            k = heapq.heappop(heap)
            pc, prow = rows[k]
            v = row.pop(pc, 0.0)
            if v == 0.0:
                continue
            for cc, pv in prow.items():
                if cc == pc:
                    continue
                old = row.get(cc)
                if old is None:
                    row[cc] = -v * pv
                    q = rank_of.get(cc)
                    if q is not None:
                        heapq.heappush(heap, q)
                else:
                    row[cc] = old - v * pv
        best, bc = 0.0, -1
        for c, v in row.items():
            if abs(v) > best:
                best, bc = abs(v), c
        if best <= tol:
            dependent.append(r)
            continue
        inv = 1.0 / row[bc]
        prow = {c: v * inv for c, v in row.items() if abs(v) > 1e-15 * best}
        prow[bc] = 1.0
        rank_of[bc] = len(rows)
        piv[bc] = prow
        rows.append((bc, prow))
    free = [c for c in range(n) if c not in piv]
    Z = np.zeros((n, len(free)))
    for k, f in enumerate(free):
        Z[f, k] = 1.0
    if free:
        for pc, prow in reversed(rows):
            acc = np.zeros(len(free))
            for cc, pv in prow.items():
                if cc != pc:
                    acc -= pv * Z[cc]
            Z[pc] = acc
        Z, _ = np.linalg.qr(Z)
    return len(rows), Z, dependent


def dependent_sparse(J, dependent, owners):
    J = J.tocsr()
    nr = np.sqrt(np.asarray(J.multiply(J).sum(axis=1)).ravel())
    live = nr > 1e-12
    Jn = sp.diags(np.where(live, 1.0 / np.where(live, nr, 1.0), 0.0)) @ J
    dep = set(dependent)
    out = {}
    for r in sorted(dependent):
        if not live[r]:
            out.setdefault(owners[r], []).append([])
            continue
        kept = [i for i in range(r) if i not in dep]
        if not kept:
            out.setdefault(owners[r], []).append([])
            continue
        B = Jn[kept].T.tocsc()
        coef = spl.lsqr(B, Jn[r].toarray().ravel(), atol=1e-14, btol=1e-14, iter_lim=20 * len(kept))[0]
        names = sorted({owners[kept[i]] for i in range(len(kept)) if abs(coef[i]) > 1e-6})
        out.setdefault(owners[r], []).append(names)
    return out


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
    sparse = m > SPARSE_ROWS
    build = assemble_sparse if sparse else assemble
    F, J = build(cons, x, cmap, n)
    nf = float(np.max(np.abs(F)))
    lam = 1e-8
    it = 0
    stall = 0
    eye = sp.identity(m, format="csc") if sparse else np.eye(m)
    while it < max_it and nf > tol:
        it += 1
        A = (J @ sp.diags(winv) @ J.T).tocsc() if sparse else (J * winv) @ J.T
        f2 = float(F @ F)
        accepted = False
        while lam < 1e12:
            try:
                y = spl.splu(A + lam * eye).solve(F) if sparse else np.linalg.solve(A + lam * eye, F)
            except (np.linalg.LinAlgError, RuntimeError):
                lam *= 10.0
                continue
            if not np.all(np.isfinite(y)):
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
        F, J = build(cons, x, cmap, n)
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
