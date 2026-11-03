import math

import numpy as np

KINDS = ("elastic", "plastic", "neohookean")
SQ23 = math.sqrt(2.0 / 3.0)
M6 = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
W6 = np.array([1.0, 1.0, 1.0, 2.0, 2.0, 2.0])


class MaterialError(ValueError):
    pass


class Material:
    def __init__(self, spec: dict):
        self.kind = str(spec.get("kind", "elastic"))
        if self.kind not in KINDS:
            raise MaterialError("Material kind must be one of %s." % ", ".join(KINDS))
        try:
            self.E = float(spec["E"])
            self.nu = float(spec["nu"])
        except (KeyError, TypeError, ValueError):
            raise MaterialError("A material needs a Young's modulus E and a Poisson ratio nu.")
        self.rho = float(spec.get("rho", 0.0) or 0.0)
        if not (self.E > 0.0 and math.isfinite(self.E)):
            raise MaterialError("Young's modulus must be positive.")
        if not (-1.0 < self.nu < 0.5):
            raise MaterialError("Poisson ratio must lie between -1 and 0.5 (exclusive).")
        self.G = self.E / (2.0 * (1.0 + self.nu))
        self.lam = self.E * self.nu / ((1.0 + self.nu) * (1.0 - 2.0 * self.nu))
        self.K = self.lam + 2.0 * self.G / 3.0
        self.sy = None
        self.curve = None
        if self.kind == "plastic":
            curve = spec.get("curve")
            if curve:
                pts = sorted((float(a), float(b)) for a, b in curve)
                if pts[0][0] != 0.0:
                    raise MaterialError("A hardening curve starts at equivalent plastic strain 0.")
                if any(pts[i + 1][0] <= pts[i][0] for i in range(len(pts) - 1)):
                    raise MaterialError("Hardening curve strains must increase.")
                if pts[0][1] <= 0.0 or any(b < 0.0 for _, b in pts):
                    raise MaterialError("Hardening curve stresses must be positive.")
                self.curve = np.array(pts)
                self.sy = float(pts[0][1])
            else:
                try:
                    self.sy = float(spec["sy"])
                except (KeyError, TypeError, ValueError):
                    raise MaterialError("A plastic material needs a yield stress sy or a hardening curve.")
                self.H = float(spec.get("H", 0.0))
                if self.sy <= 0.0:
                    raise MaterialError("Yield stress must be positive.")
                if self.H < 0.0:
                    raise MaterialError("Hardening modulus must not be negative.")
                self.curve = np.array([[0.0, self.sy], [1.0e3, self.sy + self.H * 1.0e3]])
        De = np.zeros((6, 6))
        De[:3, :3] = self.lam
        De[0, 0] = De[1, 1] = De[2, 2] = self.lam + 2.0 * self.G
        De[3, 3] = De[4, 4] = De[5, 5] = self.G
        self.De = De

    def flow(self, alpha):
        c = self.curve
        a = np.clip(alpha, 0.0, c[-1, 0])
        idx = np.clip(np.searchsorted(c[:, 0], a, side="right") - 1, 0, len(c) - 2)
        slope = (c[idx + 1, 1] - c[idx, 1]) / (c[idx + 1, 0] - c[idx, 0])
        beyond = np.maximum(alpha - c[-1, 0], 0.0)
        s = c[idx, 1] + slope * (a - c[idx, 0]) + slope * beyond
        return s, slope


def dev_norm(s):
    return np.sqrt(np.einsum("...i,i,...i->...", s, W6, s))


def small_strain(eps, ep, alpha, mat: Material):
    if mat.kind == "elastic":
        sig = eps @ mat.De.T
        D = np.broadcast_to(mat.De, eps.shape[:-1] + (6, 6))
        return sig, D, ep, alpha, np.zeros(eps.shape[:-1], dtype=bool)
    ee = eps - ep
    sig_tr = ee @ mat.De.T
    p = sig_tr[..., :3].sum(axis=-1) / 3.0
    s = sig_tr - p[..., None] * M6
    sn = dev_norm(s)
    sy_n, _ = mat.flow(alpha)
    f = sn - SQ23 * sy_n
    yielding = f > 1.0e-12 * mat.sy
    G = mat.G
    sig = sig_tr.copy()
    D = np.broadcast_to(mat.De, eps.shape[:-1] + (6, 6)).copy()
    ep_new = ep.copy()
    a_new = alpha.copy()
    if np.any(yielding):
        i = np.nonzero(yielding)
        s_y = s[i]
        sn_y = sn[i]
        a0 = alpha[i]
        dg = f[i] / (2.0 * G)
        for _ in range(40):
            sy_new, h = mat.flow(a0 + SQ23 * dg)
            phi = sn_y - 2.0 * G * dg - SQ23 * sy_new
            dphi = -2.0 * G - (2.0 / 3.0) * h
            step = phi / dphi
            dg = dg - step
            if np.max(np.abs(step)) < 1.0e-14 * (1.0 + np.max(np.abs(dg))):
                break
        dg = np.maximum(dg, 0.0)
        a1 = a0 + SQ23 * dg
        _, h1 = mat.flow(a1)
        n = s_y / sn_y[:, None]
        s_new = s_y - 2.0 * G * dg[:, None] * n
        sig[i] = s_new + p[i][:, None] * M6
        ep_new[i] = ep[i] + dg[:, None] * n * W6
        a_new[i] = a1
        theta = 1.0 - 2.0 * G * dg / sn_y
        thetabar = 1.0 / (1.0 + h1 / (3.0 * G)) - (1.0 - theta)
        Id = np.diag([1.0, 1.0, 1.0, 0.5, 0.5, 0.5]) - np.outer(M6, M6) / 3.0
        Dy = mat.K * np.outer(M6, M6)[None] + 2.0 * G * theta[:, None, None] * Id[None] - 2.0 * G * thetabar[:, None, None] * np.einsum("ni,nj->nij", n, n)
        D[i] = Dy
    return sig, D, ep_new, a_new, yielding


def von_mises(sig):
    p = sig[..., :3].sum(axis=-1) / 3.0
    s = sig - p[..., None] * M6
    return math.sqrt(1.5) * dev_norm(s)


def neo_hookean(F, mat: Material):
    mu, lam = mat.G, mat.lam
    Fi = np.linalg.inv(F)
    J = np.linalg.det(F)
    if np.any(J <= 0.0):
        raise ArithmeticError("An element inverted (the Jacobian of the deformation became non-positive).")
    lnJ = np.log(J)
    FiT = np.swapaxes(Fi, -1, -2)
    P = mu * (F - FiT) + (lam * lnJ)[..., None, None] * FiT
    A = (
        mu * np.einsum("ik,JL->iJkL", np.eye(3), np.eye(3))[None]
        + (mu - lam * lnJ)[..., None, None, None, None] * np.einsum("...Jk,...Li->...iJkL", Fi, Fi)
        + lam * np.einsum("...iJ,...kL->...iJkL", FiT, FiT)
    )
    I1 = np.einsum("...ij,...ij->...", F, F)
    psi = 0.5 * mu * (I1 - 3.0) - mu * lnJ + 0.5 * lam * lnJ**2
    return P, A, psi, J
