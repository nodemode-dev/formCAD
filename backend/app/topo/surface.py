import numpy as np

from app.topo.grid import Grid, TopoError

TETS = np.array([[0, 1, 3, 7], [0, 1, 5, 7], [0, 2, 3, 7], [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 6, 7]])
MAX_LATTICE = 30_000_000


def lattice(grid: Grid, field: np.ndarray) -> np.ndarray:
    f = np.zeros((grid.nz + 2, grid.ny + 2, grid.nx + 2))
    f[1:-1, 1:-1, 1:-1] = field.reshape(grid.shape())
    return f


def marching_tets(f: np.ndarray, level: float, spacing: float, origin: np.ndarray):
    nz, ny, nx = f.shape
    if f.size > MAX_LATTICE:
        raise TopoError("The grid is too large to extract a surface.")
    inside = f > level
    corners = [inside[a:nz - 1 + a, b:ny - 1 + b, c:nx - 1 + c] for c in (0, 1) for b in (0, 1) for a in (0, 1)]
    any_in = np.zeros_like(corners[0])
    all_in = np.ones_like(corners[0])
    for m in corners:
        any_in |= m
        all_in &= m
    cubes = np.argwhere(any_in & ~all_in)
    empty = (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    if not len(cubes):
        return empty
    sxy = nx * ny
    base = cubes[:, 2] + nx * cubes[:, 1] + sxy * cubes[:, 0]
    offs = np.array([a + nx * b + sxy * c for c in (0, 1) for b in (0, 1) for a in (0, 1)])
    tet_nodes = (base[:, None] + offs[None, :])[:, TETS].reshape(-1, 4)
    flat = f.ravel()
    ins = flat[tet_nodes] > level
    count = ins.sum(axis=1)
    keep = (count > 0) & (count < 4)
    tet_nodes, ins, count = tet_nodes[keep], ins[keep], count[keep]

    def xyz(n):
        return np.stack([n % nx, (n // nx) % ny, n // sxy], axis=-1).astype(float)

    edges_lo, edges_hi, dirs = [], [], []

    def emit(tn, pairs, i_idx, o_idx):
        lo = np.stack([np.minimum(tn[np.arange(len(tn)), a], tn[np.arange(len(tn)), b]) for a, b in pairs], axis=1)
        hi = np.stack([np.maximum(tn[np.arange(len(tn)), a], tn[np.arange(len(tn)), b]) for a, b in pairs], axis=1)
        pin = np.mean([xyz(tn[np.arange(len(tn)), q]) for q in i_idx], axis=0)
        pout = np.mean([xyz(tn[np.arange(len(tn)), q]) for q in o_idx], axis=0)
        edges_lo.append(lo)
        edges_hi.append(hi)
        dirs.append(pout - pin)

    for k in (1, 2, 3):
        sel = np.flatnonzero(count == k)
        if not len(sel):
            continue
        order = np.argsort(~ins[sel], axis=1, kind="stable")
        ni = [order[:, q] for q in range(k)]
        no = [order[:, q] for q in range(k, 4)]
        tn = tet_nodes[sel]
        if k == 1:
            emit(tn, [(ni[0], no[0]), (ni[0], no[1]), (ni[0], no[2])], ni, no)
        elif k == 3:
            emit(tn, [(ni[0], no[0]), (ni[1], no[0]), (ni[2], no[0])], ni, no)
        else:
            a, b, c, d = ni[0], ni[1], no[0], no[1]
            emit(tn, [(a, c), (a, d), (b, d)], ni, no)
            emit(tn, [(a, c), (b, d), (b, c)], ni, no)
    lo = np.concatenate(edges_lo, axis=0)
    hi = np.concatenate(edges_hi, axis=0)
    dirn = np.concatenate(dirs, axis=0)
    key = lo.astype(np.int64) * f.size + hi
    uniq, inv = np.unique(key.ravel(), return_inverse=True)
    ulo, uhi = uniq // f.size, uniq % f.size
    vlo, vhi = flat[ulo], flat[uhi]
    t = (level - vlo) / (vhi - vlo)
    p = xyz(ulo) * (1.0 - t)[:, None] + xyz(uhi) * t[:, None]
    verts = origin + (p - 0.5) * spacing
    faces = inv.reshape(-1, 3).astype(np.int64)
    n = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    flip = np.einsum("ij,ij->i", n, dirn) < 0
    faces[flip] = faces[flip][:, ::-1]
    good = (np.linalg.norm(n, axis=1) > 1e-12 * spacing * spacing) & (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return verts, faces[good]


def compact(v: np.ndarray, t: np.ndarray):
    used = np.unique(t)
    remap = np.full(len(v), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[t]


def taubin(v: np.ndarray, t: np.ndarray, iterations: int = 10, lam: float = 0.5, mu: float = -0.53, limit: float = 0.0):
    import scipy.sparse as sp

    n = len(v)
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=0)
    e = np.concatenate([e, e[:, ::-1]], axis=0)
    A = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
    A.data[:] = 1.0
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg[deg == 0] = 1.0
    L = sp.diags(1.0 / deg) @ A - sp.eye(n)
    p = v.copy()
    for _ in range(iterations):
        p = p + lam * (L @ p)
        p = p + mu * (L @ p)
    if limit > 0:
        d = p - v
        r = np.linalg.norm(d, axis=1)
        over = r > limit
        if over.any():
            p[over] = v[over] + d[over] * (limit / r[over])[:, None]
    return p


def volume(v: np.ndarray, t: np.ndarray) -> float:
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return float(np.einsum("ij,ij->", a, np.cross(b, c)) / 6.0)
