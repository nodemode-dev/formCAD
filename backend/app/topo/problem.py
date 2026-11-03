import numpy as np

from app.topo.grid import VOID, Grid


class Problem:
    def __init__(self, grid: Grid, cls: np.ndarray, force: np.ndarray, fixed: np.ndarray, E: float, nu: float, rho: float, yield_mpa: float = 0.0):
        self.grid = grid
        self.cls = cls
        self.force = force
        self.fixed = fixed
        self.E = float(E)
        self.nu = float(nu)
        self.rho = float(rho)
        self.yield_mpa = float(yield_mpa)
        self.notes: list = []

    def live_elements(self) -> np.ndarray:
        return self.cls != VOID

    def nodes_used(self, mask: np.ndarray) -> np.ndarray:
        used = np.zeros(self.grid.nn, dtype=bool)
        used[self.grid.element_nodes()[mask].ravel()] = True
        return used


def reachable(problem: Problem, solid: np.ndarray) -> np.ndarray:
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    g = problem.grid
    en = g.element_nodes()[solid]
    ne = len(en)
    rows = np.repeat(np.arange(ne), 8)
    cols = en.ravel()
    inc = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(ne, g.nn))
    adj = (inc @ inc.T).tocsr()
    _, label = connected_components(adj, directed=False)
    fixed_nodes = np.unique(np.flatnonzero(problem.fixed) // 3)
    anchored = np.zeros(g.nn, dtype=bool)
    anchored[fixed_nodes] = True
    comp_ok = np.zeros(label.max() + 1 if ne else 0, dtype=bool)
    touch = anchored[en].any(axis=1)
    comp_ok[np.unique(label[touch])] = True
    keep = np.zeros(g.ne, dtype=bool)
    ids = np.flatnonzero(solid)
    keep[ids[comp_ok[label]]] = True
    return keep
