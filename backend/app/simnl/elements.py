import numpy as np

EDGES = ((0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3))
FACES = ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1))

A4 = 0.5854101966249685
B4 = 0.1381966011250105
QP4 = np.array([[B4, B4, B4], [A4, B4, B4], [B4, A4, B4], [B4, B4, A4]])
QW4 = np.full(4, 1.0 / 24.0)
QP1 = np.array([[0.25, 0.25, 0.25]])
QW1 = np.array([1.0 / 6.0])


def tet4_shape(qp):
    L = np.column_stack([1.0 - qp.sum(axis=1), qp])
    N = L
    dL = np.array([[-1.0, -1.0, -1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    dN = np.broadcast_to(dL, (len(qp), 4, 3)).copy()
    return N, dN


def tet10_shape(qp):
    L = np.column_stack([1.0 - qp.sum(axis=1), qp])
    dL = np.array([[-1.0, -1.0, -1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    nq = len(qp)
    N = np.zeros((nq, 10))
    dN = np.zeros((nq, 10, 3))
    for i in range(4):
        N[:, i] = L[:, i] * (2.0 * L[:, i] - 1.0)
        dN[:, i, :] = (4.0 * L[:, i] - 1.0)[:, None] * dL[i][None, :]
    for k, (i, j) in enumerate(EDGES):
        N[:, 4 + k] = 4.0 * L[:, i] * L[:, j]
        dN[:, 4 + k, :] = 4.0 * (L[:, i][:, None] * dL[j][None, :] + L[:, j][:, None] * dL[i][None, :])
    return N, dN


class Geometry:
    def __init__(self, X, conn, quad=None):
        self.conn = np.asarray(conn, dtype=np.int64)
        self.nen = self.conn.shape[1]
        if self.nen == 10:
            qp, qw = (QP4, QW4) if quad is None else quad
            N, dNr = tet10_shape(qp)
        elif self.nen == 4:
            qp, qw = (QP1, QW1) if quad is None else quad
            N, dNr = tet4_shape(qp)
        else:
            raise ValueError("Elements must have 4 or 10 nodes.")
        self.N = N
        self.qw = qw
        xe = X[self.conn]
        J = np.einsum("ean,qar->eqnr", xe, dNr)
        det = np.linalg.det(J)
        if np.any(det <= 0.0):
            bad = int(np.sum(det <= 0.0))
            raise ValueError("%d element quadrature points have a non-positive Jacobian (inverted or flat elements)." % bad)
        inv = np.linalg.inv(J)
        self.dN = np.einsum("eqar,eqrn->eqan", dNr[None, :, :, :].repeat(len(self.conn), axis=0), inv)
        self.dV = det * qw[None, :]
        self.nq = len(qp)
        self.ne = len(self.conn)
        self.xq = np.einsum("qa,ean->eqn", N, xe)
        dofs = (self.conn[:, :, None] * 3 + np.arange(3)[None, None, :]).reshape(self.ne, -1)
        self.dofs = dofs
        self.rows = np.repeat(dofs, dofs.shape[1], axis=1).ravel()
        self.cols = np.tile(dofs, (1, dofs.shape[1])).ravel()

    def volume(self):
        return float(self.dV.sum())


def corner_to_p2(X, tets):
    tets = np.asarray(tets, dtype=np.int64)
    pairs = np.stack([tets[:, list(e)] for e in EDGES], axis=1)
    pairs.sort(axis=2)
    flat = pairs.reshape(-1, 2)
    key = flat[:, 0] * (len(X) + 1) + flat[:, 1]
    uniq, inverse = np.unique(key, return_inverse=True)
    first = np.zeros(len(uniq), dtype=np.int64)
    first[inverse[::-1]] = np.arange(len(flat))[::-1]
    mid = 0.5 * (X[flat[first, 0]] + X[flat[first, 1]])
    Xn = np.vstack([X, mid])
    mids = (len(X) + inverse).reshape(len(tets), 6)
    return Xn, np.hstack([tets, mids])


def box_tets(lx, ly, lz, nx, ny, nz, origin=(0.0, 0.0, 0.0)):
    xs = np.linspace(0.0, lx, nx + 1) + origin[0]
    ys = np.linspace(0.0, ly, ny + 1) + origin[1]
    zs = np.linspace(0.0, lz, nz + 1) + origin[2]
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    X = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])

    def nid(i, j, k):
        return (i * (ny + 1) + j) * (nz + 1) + k

    I, Jj, K = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    I, Jj, K = I.ravel(), Jj.ravel(), K.ravel()
    c = [nid(I + a, Jj + b, K + d) for a, b, d in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))]
    paths = ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6))
    tets = np.vstack([np.column_stack([c[a], c[b], c[d], c[e]]) for a, b, d, e in paths])
    p = X[tets]
    v = np.einsum("ei,ei->e", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), p[:, 3] - p[:, 0])
    flip = v < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    return X, tets


def boundary_faces(conn):
    conn = np.asarray(conn)
    tri = np.concatenate([conn[:, list(f)] for f in FACES], axis=0)
    owner = np.tile(np.arange(len(conn)), len(FACES))
    key = np.sort(tri, axis=1)
    _, first, inverse, counts = np.unique(key, axis=0, return_index=True, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    once = counts[inverse] == 1
    return tri[once], owner[once]
