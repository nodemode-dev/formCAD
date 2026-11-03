import numpy as np

from app.topo import grid as G
from app.topo.grid import DESIGN, SOLID, VOID, Grid, TopoError

MAX_REGIONS = 64
MAX_LOADS = 32


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


def build(grid: Grid, design: np.ndarray, material: dict, preserve=(), obstacles=(), loads=(), supports=(), auto_preserve: bool = True, start=None) -> Problem:
    if len(preserve) + len(obstacles) > MAX_REGIONS or len(loads) + len(supports) > MAX_LOADS:
        raise TopoError("Too many regions, loads or supports.")
    E = float(material.get("E", 0.0))
    nu = float(material.get("nu", 0.3))
    if not E > 0:
        raise TopoError("The material needs a Young's modulus.")
    cls = np.full(grid.ne, DESIGN, dtype=np.int8)
    cls[~design] = VOID
    notes = []
    for spec in obstacles:
        m = G.region_mask_elements(grid, spec)
        if not m.any():
            notes.append("An obstacle region holds no cell of the grid.")
        cls[m] = VOID
    for spec in preserve:
        m = G.region_mask_elements(grid, spec) & design
        if not m.any():
            notes.append("A preserve region holds no cell of the design space.")
        cls[m] = SOLID
    force = np.zeros(grid.ndof)
    fixed = np.zeros(grid.ndof, dtype=bool)
    touched = np.zeros(grid.nn, dtype=bool)
    live_nodes = np.zeros(grid.nn, dtype=bool)
    live_nodes[grid.element_nodes()[cls != VOID].ravel()] = True
    for spec in supports:
        reg = spec.get("region") or spec
        nodes = G.region_mask_nodes(grid, reg) & live_nodes
        if not nodes.any():
            raise TopoError("A support holds no node of the design; move it onto the material.")
        flags = spec.get("fix", [True, True, True])
        if len(flags) != 3:
            raise TopoError("A support fixes x, y and z: give three flags.")
        for c in range(3):
            if flags[c]:
                fixed[3 * np.flatnonzero(nodes) + c] = True
        touched |= nodes
    for spec in loads:
        reg = spec.get("region") or spec
        nodes = G.region_mask_nodes(grid, reg) & live_nodes
        if not nodes.any():
            raise TopoError("A load holds no node of the design; move it onto the material.")
        vec = G.vec3(spec.get("force"), "A load force")
        share = vec / float(nodes.sum())
        idx = np.flatnonzero(nodes)
        for c in range(3):
            force[3 * idx + c] += share[c]
        touched |= nodes
    if not fixed.any():
        raise TopoError("Add at least one support: nothing holds the design.")
    if not np.any(force != 0):
        raise TopoError("Add at least one load: with no load there is nothing to optimise for.")
    if auto_preserve:
        en = grid.element_nodes()
        near = touched[en].any(axis=1) & (cls == DESIGN)
        cls[near] = SOLID
        if near.any():
            notes.append("%d cells next to loads and supports were kept solid." % int(near.sum()))
    p = Problem(grid, cls, force, fixed, E, nu, float(material.get("rho", 0.0)), float(material.get("yield", 0.0)))
    p.notes = notes
    p.start = start
    return p


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
