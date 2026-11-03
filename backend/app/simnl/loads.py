import numpy as np

TP = np.array([[1.0 / 6.0, 1.0 / 6.0], [2.0 / 3.0, 1.0 / 6.0], [1.0 / 6.0, 2.0 / 3.0]])
TW = np.full(3, 1.0 / 6.0)


def tri_shape(nodes_per_face):
    L = np.column_stack([1.0 - TP.sum(axis=1), TP])
    dL = np.array([[-1.0, -1.0], [1.0, 0.0], [0.0, 1.0]])
    if nodes_per_face == 3:
        return L, np.broadcast_to(dL, (3, 3, 2)).copy()
    N = np.zeros((3, 6))
    dN = np.zeros((3, 6, 2))
    for i in range(3):
        N[:, i] = L[:, i] * (2.0 * L[:, i] - 1.0)
        dN[:, i, :] = (4.0 * L[:, i] - 1.0)[:, None] * dL[i][None, :]
    for k, (i, j) in enumerate(((0, 1), (1, 2), (2, 0))):
        N[:, 3 + k] = 4.0 * L[:, i] * L[:, j]
        dN[:, 3 + k, :] = 4.0 * (L[:, i][:, None] * dL[j][None, :] + L[:, j][:, None] * dL[i][None, :])
    return N, dN


def face_areas(X, faces):
    N, dN = tri_shape(faces.shape[1])
    xe = X[faces]
    t = np.einsum("fan,qar->fqnr", xe, dN)
    nrm = np.cross(t[..., 0], t[..., 1])
    jac = np.linalg.norm(nrm, axis=-1)
    return jac, N, nrm


def traction_forces(X, faces, vec, ndof, pressure=None):
    jac, N, nrm = face_areas(X, faces)
    f = np.zeros(ndof)
    w = jac * TW[None, :]
    for q in range(3):
        for a in range(faces.shape[1]):
            if pressure is not None:
                u = nrm[:, q, :] / np.maximum(jac[:, q], 1e-300)[:, None]
                val = -pressure * u
            else:
                val = np.broadcast_to(np.asarray(vec, dtype=float), (len(faces), 3))
            contrib = (N[q, a] * w[:, q])[:, None] * val
            for c in range(3):
                f[:] += np.bincount(3 * faces[:, a] + c, weights=contrib[:, c], minlength=ndof)
    return f


def total_area(X, faces):
    jac, _, _ = face_areas(X, faces)
    return float((jac * TW[None, :]).sum())
