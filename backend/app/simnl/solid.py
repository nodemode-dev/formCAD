import numpy as np
import scipy.sparse as sp

from app.simnl import material as mt
from app.simnl.elements import Geometry

CHUNK = 3000


def build_B(dN):
    ne, nq, nen, _ = dN.shape
    B = np.zeros((ne, nq, 6, nen, 3))
    B[:, :, 0, :, 0] = dN[..., 0]
    B[:, :, 1, :, 1] = dN[..., 1]
    B[:, :, 2, :, 2] = dN[..., 2]
    B[:, :, 3, :, 0] = dN[..., 1]
    B[:, :, 3, :, 1] = dN[..., 0]
    B[:, :, 4, :, 1] = dN[..., 2]
    B[:, :, 4, :, 2] = dN[..., 1]
    B[:, :, 5, :, 0] = dN[..., 2]
    B[:, :, 5, :, 2] = dN[..., 0]
    return B.reshape(ne, nq, 6, nen * 3)


def build_G(dN):
    ne, nq, nen, _ = dN.shape
    G = np.zeros((ne, nq, 3, 3, nen, 3))
    for i in range(3):
        G[:, :, i, :, :, i] = dN.transpose(0, 1, 3, 2)
    return G.reshape(ne, nq, 9, nen * 3)


class Solid:
    def __init__(self, X0, conn, mat: mt.Material, large=False, quad=None):
        self.mat = mat
        self.large = bool(large)
        self.geo = Geometry(X0, conn, quad)
        g = self.geo
        if mat.kind == "neohookean":
            self.large = True
        self.ep = np.zeros((g.ne, g.nq, 6))
        self.alpha = np.zeros((g.ne, g.nq))
        self.sig = np.zeros((g.ne, g.nq, 6))
        self.B = None if self.large else build_B(g.dN)
        self.G = build_G(g.dN) if self.large else None
        self.pattern = None

    def reset(self):
        self.ep[:] = 0.0
        self.alpha[:] = 0.0
        self.sig[:] = 0.0

    def snapshot(self):
        return self.ep.copy(), self.alpha.copy()

    def restore(self, snap):
        self.ep[:] = snap[0]
        self.alpha[:] = snap[1]

    def evaluate(self, u, need_k=True):
        g = self.geo
        ue = u[g.dofs]
        fint = np.zeros(len(u))
        vals = [] if need_k else None
        aux = {"ep": np.empty_like(self.ep), "alpha": np.empty_like(self.alpha), "sig": np.empty_like(self.sig), "yield": np.zeros((g.ne, g.nq), dtype=bool), "J": None}
        if self.large:
            aux["J"] = np.empty((g.ne, g.nq))
        for s in range(0, g.ne, CHUNK):
            sl = slice(s, min(s + CHUNK, g.ne))
            if self.large:
                fe, ke, sig, J = self._large(g, sl, ue[sl], need_k)
                aux["J"][sl] = J
                aux["ep"][sl] = self.ep[sl]
                aux["alpha"][sl] = self.alpha[sl]
            else:
                fe, ke, sig, ep, al, yl = self._small(g, sl, ue[sl], need_k)
                aux["ep"][sl] = ep
                aux["alpha"][sl] = al
                aux["yield"][sl] = yl
            aux["sig"][sl] = sig
            fint += np.bincount(g.dofs[sl].ravel(), weights=fe.ravel(), minlength=len(u))
            if need_k:
                vals.append(ke.reshape(len(fe), -1).ravel())
        K = None
        if need_k:
            if self.pattern is None or self.pattern[0] != len(u):
                n = len(u)
                key = g.rows * n + g.cols
                uniq, inv = np.unique(key, return_inverse=True)
                ru = uniq // n
                self.pattern = (n, inv.ravel(), (uniq % n).astype(np.int32), np.searchsorted(ru, np.arange(n + 1)).astype(np.int32), len(uniq))
            n, inv, cols, indptr, nu = self.pattern
            data = np.bincount(inv, weights=np.concatenate(vals), minlength=nu)
            K = sp.csr_matrix((data, cols, indptr), shape=(n, n))
        return fint, K, aux

    def _small(self, g, sl, ue, need_k):
        B = self.B[sl]
        Bt = B.transpose(0, 1, 3, 2)
        eps = np.matmul(B, ue[:, None, :, None])[..., 0]
        sig, D, ep, al, yl = mt.small_strain(eps, self.ep[sl], self.alpha[sl], self.mat)
        dV = g.dV[sl]
        fe = np.matmul(Bt, (sig * dV[..., None])[..., None])[..., 0].sum(axis=1)
        ke = None
        if need_k:
            ke = np.matmul(Bt, np.matmul(D, B) * dV[..., None, None]).sum(axis=1)
        return fe, ke, sig, ep, al, yl

    def _large(self, g, sl, ue, need_k):
        ne = ue.shape[0]
        nen = g.nen
        G = self.G[sl]
        Gt = G.transpose(0, 1, 3, 2)
        gradu = np.matmul(G, ue[:, None, :, None])[..., 0].reshape(ne, g.nq, 3, 3)
        F = np.eye(3)[None, None] + gradu
        P, A, psi, J = mt.neo_hookean(F, self.mat)
        dV = g.dV[sl]
        fe = np.matmul(Gt, (P.reshape(ne, g.nq, 9) * dV[..., None])[..., None])[..., 0].sum(axis=1)
        ke = None
        if need_k:
            ke = np.matmul(Gt, np.matmul(A.reshape(ne, g.nq, 9, 9), G) * dV[..., None, None]).sum(axis=1)
        sig6 = self.cauchy(P, F, J)
        return fe, ke, sig6, J

    @staticmethod
    def cauchy(P, F, J):
        s = np.einsum("...iJ,...kJ->...ik", P, F) / J[..., None, None]
        return np.stack([s[..., 0, 0], s[..., 1, 1], s[..., 2, 2], s[..., 0, 1], s[..., 1, 2], s[..., 2, 0]], axis=-1)

    def commit(self, aux):
        self.ep[:] = aux["ep"]
        self.alpha[:] = aux["alpha"]
        self.sig[:] = aux["sig"]

    def mass_lumped(self, nnodes):
        g = self.geo
        m = np.zeros(nnodes)
        if g.nen == 4:
            vol = g.dV.sum(axis=1)
            np.add.at(m, g.conn.ravel(), np.repeat(self.mat.rho * vol / 4.0, 4))
        else:
            raise ValueError("Lumped mass is only built for four-node tetrahedra.")
        return m

    def element_fields(self, aux):
        sig = aux["sig"]
        vm = mt.von_mises(sig)
        return {"von_mises": vm.max(axis=1), "von_mises_mean": vm.mean(axis=1), "plastic_strain": aux["alpha"].max(axis=1), "yielded": aux["yield"].any(axis=1)}
