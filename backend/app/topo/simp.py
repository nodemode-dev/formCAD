import time

import numpy as np

from app.topo import hexfem, filters
from app.topo.grid import DESIGN, SOLID, VOID, Cancelled, TopoError
from app.topo.problem import Problem

EMIN_RATIO = 1e-9
MOVE = 0.2
PLATEAU = 8
PLATEAU_BAND = 0.01
DAMPING = 0.5
BIS_TOL = 1e-4


class Settings:
    def __init__(self, spec: dict):
        spec = spec or {}
        self.penal = _num(spec, "penalty", 3.0, 1.0, 6.0)
        self.radius_cells = _num(spec, "radius_cells", 1.5, 1.0, 8.0)
        self.radius = float(spec["radius"]) if spec.get("radius") else 0.0
        self.max_iter = int(_num(spec, "iterations", 100, 1, 1000))
        self.change_tol = _num(spec, "change_tol", 0.01, 1e-5, 0.5)
        self.projection = bool(spec.get("projection", True))
        self.beta_max = _num(spec, "beta_max", 8.0, 1.0, 64.0)
        self.beta_every = int(_num(spec, "beta_every", 25, 5, 200))
        self.min_iter = int(_num(spec, "min_iterations", 40, 1, 1000))
        self.symmetry = list(spec.get("symmetry") or [])
        self.extrusion = spec.get("extrusion")
        self.extra = list(spec.get("filters") or [])
        self.direct_dofs = int(_num(spec, "direct_dofs", hexfem.DIRECT_DOFS, 1000, 200000))


def _num(spec, key, default, low, high):
    try:
        v = float(spec.get(key, default))
    except (TypeError, ValueError):
        raise TopoError("%s must be a number." % key)
    if not np.isfinite(v) or v < low or v > high:
        raise TopoError("%s must be between %g and %g." % (key, low, high))
    return v


def build_chain(problem: Problem, st: Settings, bounds) -> filters.Chain:
    g = problem.grid
    stages = []
    axes = filters.plane_axes(g, st.symmetry, bounds) if st.symmetry else []
    if axes:
        bad = filters.symmetry_conflicts(g, problem.cls, axes)
        if bad:
            raise TopoError("The %s regions are not symmetric about the chosen plane%s. Make them symmetric or drop the symmetry." % (" and ".join(bad), "s" if len(axes) > 1 else ""))
        stages.append(filters.FILTERS["symmetry"](g, axes))
    if st.extrusion not in (None, "", False):
        stages.append(filters.FILTERS["extrusion"](g, st.extrusion))
    late = []
    for item in st.extra:
        name = item.get("name")
        if name not in filters.FILTERS or name in ("density", "symmetry", "extrusion"):
            raise TopoError("There is no filter called %s." % name)
        kw = {k: v for k, v in item.items() if k not in ("name", "last")}
        if item.get("last"):
            late.append(filters.FILTERS[name](g, cls=problem.cls, **kw))
            continue
        stages.append(filters.FILTERS[name](g, **kw))
    radius = st.radius if st.radius > 0 else st.radius_cells * g.h
    stages.append(filters.FILTERS["density"](g, radius))
    if st.projection:
        stages.append(filters.Projection(1.0, 0.5))
    stages.extend(late)
    stages.append(filters.Passive(problem.cls))
    return filters.Chain(stages)


class Result:
    def __init__(self):
        self.x = None
        self.xphys = None
        self.history = []
        self.iterations = 0
        self.converged = False
        self.compliance = 0.0
        self.volume = 0.0
        self.beta = 1.0
        self.seconds = 0.0


def volume_fraction(problem: Problem, xphys: np.ndarray) -> float:
    live = problem.cls != VOID
    return float(xphys[live].sum() / max(1, live.sum()))


def optimise(problem: Problem, vf: float, st: Settings, bounds, progress=None, cancel=None, x0=None, label: str = "") -> Result:
    g = problem.grid
    if not (0.02 <= vf <= 1.0):
        raise TopoError("The volume fraction must be between 0.02 and 1.")
    chain = build_chain(problem, st, bounds)
    live = problem.cls != VOID
    members = np.flatnonzero(live)
    free = np.repeat(problem.nodes_used(live), 3) & ~problem.fixed
    asm = hexfem.Assembler(g, free, members)
    ke = hexfem.unit_stiffness(g.h, problem.nu)
    E0 = problem.E
    Emin = E0 * EMIN_RATIO
    f = problem.force[free]
    nlive = float(live.sum())
    dv_raw = chain.backward(chain.trace(np.full(g.ne, vf)), np.where(live, 1.0, 0.0))
    x = np.full(g.ne, vf) if x0 is None else np.clip(np.asarray(x0, dtype=float), 0.0, 1.0)
    x[problem.cls == SOLID] = 1.0
    x[problem.cls == VOID] = 0.0
    res = Result()
    t0 = time.monotonic()
    beta = 1.0
    proj = chain.find("projection")
    edof = g.edofs()
    u = np.zeros(g.ndof)
    solver = hexfem.Solver(st.direct_dofs)
    for it in range(1, st.max_iter + 1):
        if cancel is not None and cancel():
            raise Cancelled("The optimisation was cancelled.")
        used = beta
        if proj is not None:
            proj.beta = beta
        seen = chain.trace(x)
        xp = seen[-1]
        stiff = Emin + xp ** st.penal * (E0 - Emin)
        K = asm.matrix(ke, stiff[members])
        u[free] = solver.solve(K, f, u[free])
        ue = u[edof[members]]
        ce = np.zeros(g.ne)
        ce[members] = np.einsum("ei,ij,ej->e", ue, ke, ue)
        c = float((stiff * ce).sum())
        dc_xp = -st.penal * xp ** (st.penal - 1.0) * (E0 - Emin) * ce
        dc = chain.backward(seen, dc_xp)
        dv = dv_raw
        scale = max(1e-300, float(np.max(np.abs(dc))))
        dcn = dc / scale
        l1, l2 = 0.0, 1e9
        move = MOVE / max(1.0, used / 2.0)
        xnew = x
        for _ in range(100):
            if (l2 - l1) / (l1 + l2 + 1e-300) <= BIS_TOL:
                break
            mid = 0.5 * (l1 + l2)
            ratio = np.maximum(-dcn, 0.0) / np.maximum(dv, 1e-12) / mid
            cand = np.clip(x * ratio ** DAMPING, np.maximum(0.0, x - move), np.minimum(1.0, x + move))
            cand[problem.cls == SOLID] = 1.0
            cand[problem.cls == VOID] = 0.0
            xph = chain.forward(cand)
            if volume_fraction(problem, xph) > vf:
                l1 = mid
            else:
                l2 = mid
            xnew = cand
        change = float(np.max(np.abs(xnew - x)))
        x = xnew
        xpn = chain.forward(x)
        vol = volume_fraction(problem, xpn)
        res.history.append({"iteration": it, "compliance": c, "volume": vol, "change": change, "beta": beta})
        if progress is not None:
            progress(label, it / st.max_iter, {"iteration": it, "compliance": c, "volume": vol, "change": change})
        done = change < st.change_tol and it >= st.min_iter
        tail = [h["compliance"] for h in res.history[-PLATEAU:] if h["beta"] == used]
        if not done and len(tail) >= PLATEAU and (proj is None or used >= st.beta_max) and (max(tail) - min(tail)) / max(1e-300, float(np.mean(tail))) < PLATEAU_BAND:
            done = True
        if proj is not None and beta < st.beta_max:
            if it % st.beta_every == 0 or change < st.change_tol:
                beta = min(st.beta_max, beta * 2.0)
                done = False
        if done:
            res.converged = True
            break
    if proj is not None:
        proj.beta = used
    res.iterations = it
    res.x = x
    res.xphys = chain.forward(x)
    res.compliance = c
    res.volume = volume_fraction(problem, res.xphys)
    res.beta = used
    res.seconds = time.monotonic() - t0
    res.chain = chain
    return res


def grey_share(problem: Problem, xphys: np.ndarray) -> float:
    m = problem.cls == DESIGN
    if not m.any():
        return 0.0
    return float(((xphys[m] > 0.1) & (xphys[m] < 0.9)).mean())
