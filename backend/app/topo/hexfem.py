import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

from app.topo.grid import Grid, TopoError

GAUSS = 1.0 / np.sqrt(3.0)
CORNERS = [(a, b, c) for c in (0, 1) for b in (0, 1) for a in (0, 1)]


def constitutive(E: float, nu: float) -> np.ndarray:
    if not (-1.0 < nu < 0.5):
        raise TopoError("Poisson's ratio must be between -1 and 0.5.")
    f = E / ((1 + nu) * (1 - 2 * nu))
    D = np.zeros((6, 6))
    D[:3, :3] = f * nu
    for k in range(3):
        D[k, k] = f * (1 - nu)
        D[3 + k, 3 + k] = f * (1 - 2 * nu) / 2.0
    return D


def strain_matrices(h: float) -> np.ndarray:
    out = []
    for gx in (-GAUSS, GAUSS):
        for gy in (-GAUSS, GAUSS):
            for gz in (-GAUSS, GAUSS):
                dN = np.zeros((3, 8))
                for n, (a, b, c) in enumerate(CORNERS):
                    sx, sy, sz = 2 * a - 1, 2 * b - 1, 2 * c - 1
                    dN[0, n] = sx * (1 + sy * gy) * (1 + sz * gz) / 8.0
                    dN[1, n] = sy * (1 + sx * gx) * (1 + sz * gz) / 8.0
                    dN[2, n] = sz * (1 + sx * gx) * (1 + sy * gy) / 8.0
                dN *= 2.0 / h
                B = np.zeros((6, 24))
                for n in range(8):
                    B[0, 3 * n] = dN[0, n]
                    B[1, 3 * n + 1] = dN[1, n]
                    B[2, 3 * n + 2] = dN[2, n]
                    B[3, 3 * n] = dN[1, n]
                    B[3, 3 * n + 1] = dN[0, n]
                    B[4, 3 * n + 1] = dN[2, n]
                    B[4, 3 * n + 2] = dN[1, n]
                    B[5, 3 * n] = dN[2, n]
                    B[5, 3 * n + 2] = dN[0, n]
                out.append(B)
    return np.array(out)


def unit_stiffness(h: float, nu: float) -> np.ndarray:
    D = constitutive(1.0, nu)
    Bs = strain_matrices(h)
    w = (h / 2.0) ** 3
    K = np.zeros((24, 24))
    for B in Bs:
        K += w * B.T @ D @ B
    return 0.5 * (K + K.T)


def estimate_bytes(ndof: int) -> int:
    return int(2400.0 * float(ndof) ** 1.18) + 200 * int(ndof)


class Assembler:
    def __init__(self, grid: Grid, free: np.ndarray, elements: np.ndarray = None):
        self.grid = grid
        self.free = free
        self.elements = np.arange(grid.ne) if elements is None else elements
        edof = grid.edofs()[self.elements]
        index = np.cumsum(free) - 1
        index = np.where(free, index, -1)
        self.index = index
        self.nfree = int(free.sum())
        rows = np.repeat(edof, 24, axis=1)
        cols = np.tile(edof, (1, 24))
        r = index[rows]
        c = index[cols]
        keep = (r >= 0) & (c >= 0)
        self.keep = keep
        kr, kc = r[keep], c[keep]
        key = kc.astype(np.int64) * self.nfree + kr
        order = np.argsort(key, kind="stable")
        skey = key[order]
        first = np.ones(len(skey), dtype=bool)
        first[1:] = skey[1:] != skey[:-1]
        self.order = order
        self.starts = np.flatnonzero(first)
        ukey = skey[self.starts]
        self.indices = (ukey % self.nfree).astype(np.int32)
        cnt = np.bincount((ukey // self.nfree).astype(np.int64), minlength=self.nfree)
        self.indptr = np.concatenate([[0], np.cumsum(cnt)]).astype(np.int32)

    def matrix(self, ke: np.ndarray, scale: np.ndarray) -> sp.csc_matrix:
        vals = (scale[:, None, None] * ke[None, :, :]).reshape(len(self.elements), 576)
        data = np.add.reduceat(vals[self.keep.reshape(len(self.elements), 576)][self.order], self.starts)
        return sp.csc_matrix((data, self.indices, self.indptr), shape=(self.nfree, self.nfree))


class Factor:
    def __init__(self, K: sp.csc_matrix):
        try:
            self.lu = spl.splu(K, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options={"SymmetricMode": True})
        except RuntimeError:
            raise TopoError("The stiffness matrix is singular: the supports do not hold the design, or part of it is not connected to them.")

    def solve(self, b: np.ndarray) -> np.ndarray:
        x = self.lu.solve(b)
        if not np.all(np.isfinite(x)):
            raise TopoError("The stiffness matrix is singular: the supports do not hold the design, or part of it is not connected to them.")
        return x


DIRECT_DOFS = 14000


class Solver:
    def __init__(self, direct_dofs: int = DIRECT_DOFS, refresh: int = 8):
        self.direct_dofs = direct_dofs
        self.refresh = refresh
        self.ilu = None
        self.age = 0
        self.last_iterations = 0
        self.mode = "direct"

    def solve(self, K: sp.csc_matrix, b: np.ndarray, x0: np.ndarray = None) -> np.ndarray:
        if K.shape[0] <= self.direct_dofs:
            self.mode = "direct"
            return Factor(K).solve(b)
        self.mode = "iterative"
        if self.ilu is None or self.age >= self.refresh:
            try:
                self.ilu = spl.spilu(K, drop_tol=1e-4, fill_factor=10, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0)
            except RuntimeError:
                raise TopoError("The stiffness matrix is singular: the supports do not hold the design, or part of it is not connected to them.")
            self.age = 0
        self.age += 1
        count = [0]

        def tick(_):
            count[0] += 1

        M = spl.LinearOperator(K.shape, self.ilu.solve)
        x, info = spl.cg(K, b, x0=x0, M=M, rtol=1e-8, atol=0.0, maxiter=400, callback=tick)
        if info != 0 and self.age > 1:
            self.ilu = None
            return self.solve(K, b, x0)
        if info != 0 or not np.all(np.isfinite(x)):
            raise TopoError("The iterative solver did not converge: the design is too weakly held. Check the supports.")
        self.last_iterations = count[0]
        return x


def element_displacements(grid: Grid, u: np.ndarray) -> np.ndarray:
    return u[grid.edofs()]


def element_stress(grid: Grid, u: np.ndarray, E: float, nu: float, elements=None) -> np.ndarray:
    D = constitutive(E, nu)
    Bs = strain_matrices(grid.h)
    mean = D @ Bs.mean(axis=0)
    ue = u[grid.edofs() if elements is None else grid.edofs()[elements]]
    return ue @ mean.T


def von_mises(s: np.ndarray) -> np.ndarray:
    sx, sy, sz, txy, tyz, tzx = (s[:, k] for k in range(6))
    return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3.0 * (txy ** 2 + tyz ** 2 + tzx ** 2))
