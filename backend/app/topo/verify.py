import numpy as np

from app.topo import hexfem
from app.topo.grid import DESIGN, SOLID, VOID, TopoError
from app.topo.problem import Problem, reachable


class Check:
    def __init__(self):
        self.solid = None
        self.u = None
        self.vm = None
        self.peak = 0.0
        self.peak_all = 0.0
        self.p99 = 0.0
        self.peak_cell = -1
        self.volume_fraction = 0.0
        self.mass = 0.0
        self.compliance = 0.0
        self.dropped = 0
        self.max_disp = 0.0
        self.failure = ""

    def view(self) -> dict:
        return {"peak_stress": self.peak, "peak_stress_all": self.peak_all, "stress_p99": self.p99, "volume_fraction": self.volume_fraction, "mass": self.mass, "compliance": self.compliance, "disconnected_cells_removed": self.dropped, "max_displacement": self.max_disp}


def solve_design(problem: Problem, solid: np.ndarray, direct_dofs: int = hexfem.DIRECT_DOFS) -> Check:
    g = problem.grid
    solid = solid & (problem.cls != VOID)
    keep = reachable(problem, solid)
    out = Check()
    out.dropped = int(solid.sum() - keep.sum())
    solid = keep
    out.solid = solid
    used = problem.nodes_used(solid)
    dof_used = np.repeat(used, 3)
    free = dof_used & ~problem.fixed
    loaded = np.flatnonzero(problem.force != 0)
    if not np.all(dof_used[loaded]):
        raise TopoError("The thresholded design no longer connects a load to the supports (members thinner than the filter radius were cut). Ask for less mass reduction, use a finer grid (more cells), or add a preserve region along the load path.")
    if not np.any(dof_used & problem.fixed):
        raise TopoError("No support touches the remaining material: the design was cut away from the supports. Ask for less mass reduction or add a preserve region at the support.")
    elements = np.flatnonzero(solid)
    asm = hexfem.Assembler(g, free, elements)
    ke = hexfem.unit_stiffness(g.h, problem.nu)
    K = asm.matrix(ke, np.full(len(elements), problem.E))
    u = np.zeros(g.ndof)
    u[free] = hexfem.Solver(direct_dofs).solve(K, problem.force[free])
    out.u = u
    s = hexfem.element_stress(g, u, problem.E, problem.nu, elements)
    vm = np.zeros(g.ne)
    vm[elements] = hexfem.von_mises(s)
    out.vm = vm
    scored = solid & (problem.cls == DESIGN)
    if not scored.any():
        scored = solid
    vals = vm[scored]
    ids = np.flatnonzero(scored)
    out.peak = float(vals.max())
    out.peak_cell = int(ids[int(np.argmax(vals))])
    out.p99 = float(np.percentile(vals, 99))
    out.peak_all = float(vm[solid].max())
    live = problem.cls != VOID
    out.volume_fraction = float(solid.sum() / max(1, live.sum()))
    out.mass = float(solid.sum()) * g.h ** 3 * problem.rho
    ue = u[g.edofs()[elements]]
    out.compliance = float(np.einsum("ei,ij,ej->", ue, ke, ue) * problem.E)
    out.max_disp = float(np.abs(u).max())
    return out


def try_design(problem: Problem, solid: np.ndarray, direct_dofs: int = hexfem.DIRECT_DOFS) -> Check:
    try:
        return solve_design(problem, solid, direct_dofs)
    except TopoError as err:
        out = Check()
        out.solid = solid & (problem.cls != VOID)
        out.vm = np.zeros(problem.grid.ne)
        out.peak = out.peak_all = out.p99 = float("inf")
        out.volume_fraction = float(out.solid.sum() / max(1, (problem.cls != VOID).sum()))
        out.failure = str(err)
        return out


def threshold(problem: Problem, xphys: np.ndarray, level: float = 0.5) -> np.ndarray:
    solid = (xphys >= level) & (problem.cls != VOID)
    solid |= problem.cls == SOLID
    return solid


def match_volume(problem: Problem, xphys: np.ndarray, vf: float) -> float:
    live = problem.cls != VOID
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        frac = float(threshold(problem, xphys, mid)[live].mean() if live.any() else 0.0)
        if frac > vf:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
