import math
import time

import numpy as np

from app.flow.limits import FlowError, cap, need

MODEL = "Stokes creeping flow, Taylor-Hood P2 velocity and P1 pressure on curved P2 tetrahedra"
LABEL = "Own Stokes solver: no inertia and no entrance loss. Exact for the developed pressure gradient of laminar flow; use the optional CFD program for higher Reynolds numbers or entrance effects."
MAX_RE = 2300.0


def unknown_count(nverts: int, nedges: int) -> int:
    return 3 * (nverts + nedges) + nverts


def memory_estimate(unknowns: int, runner=None) -> int:
    return int(unknowns * cap("bytes_per_unknown", runner))


def plane_of(points3: np.ndarray, tris: np.ndarray, label: str) -> tuple:
    a, b, c = (points3[tris[:, i]] for i in range(3))
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    if area.sum() <= 0:
        raise FlowError("The %s face has no area." % label)
    normal = (cross * (1.0 / np.maximum(2 * area, 1e-300))[:, None] * area[:, None]).sum(axis=0)
    normal /= np.linalg.norm(normal)
    centroid = (((a + b + c) / 3.0) * area[:, None]).sum(axis=0) / area.sum()
    pts = points3[np.unique(tris)]
    spread = np.abs((pts - centroid) @ normal).max()
    extent = np.linalg.norm(pts.max(axis=0) - pts.min(axis=0))
    if spread > 1e-3 * max(extent, 1e-12):
        raise FlowError("The %s face is not flat. Choose a flat face for the %s." % (label, label))
    return normal, centroid, float(area.sum())


def axes_for(normal: np.ndarray) -> tuple:
    helper = np.array([1.0, 0, 0]) if abs(normal[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(normal, helper)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(normal, e1)


def developed_profile(points3: np.ndarray, tris: np.ndarray, normal: np.ndarray, check) -> tuple:
    from scipy.spatial import cKDTree
    from skfem import Basis, BilinearForm, ElementTriP2, LinearForm, MeshTri, condense, solve
    from skfem.helpers import dot, grad

    used, inverse = np.unique(tris, return_inverse=True)
    local = inverse.reshape(tris.shape)
    e1, e2 = axes_for(normal)
    xy = np.stack([points3[used] @ e1, points3[used] @ e2])
    mesh2 = MeshTri(xy, local.T.copy())
    basis = Basis(mesh2, ElementTriP2())
    check()
    k = BilinearForm(lambda u, v, w: dot(grad(u), grad(v))).assemble(basis)
    f = LinearForm(lambda v, w: v).assemble(basis)
    fixed = basis.get_dofs().all()
    w = solve(*condense(k, f, D=fixed))
    return cKDTree(basis.doflocs.T), w, (e1, e2), float(f @ w / f.sum())


def profile_at(tree, w, axes, points: np.ndarray) -> np.ndarray:
    e1, e2 = axes
    q = np.stack([points @ e1, points @ e2], axis=1)
    _, idx = tree.query(q)
    return w[idx]


def rim_perimeter(mesh, tris: np.ndarray) -> float:
    n = np.int64(mesh.p.shape[1] + 1)
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]).astype(np.int64), axis=1)
    keys = e[:, 0] * n + e[:, 1]
    uniq, first, count = np.unique(keys, return_index=True, return_counts=True)
    rim = e[first[count == 1]]
    table = np.sort(mesh.edges.T.astype(np.int64), axis=1)
    tkeys = table[:, 0] * n + table[:, 1]
    order = np.argsort(tkeys)
    pos = order[np.searchsorted(tkeys[order], rim[:, 0] * n + rim[:, 1])]
    mid = mesh.doflocs[:, mesh.dofs.edge_dofs[0, pos]].T
    pa, pb = mesh.p[:, rim[:, 0]].T, mesh.p[:, rim[:, 1]].T
    return float((np.linalg.norm(mid - pa, axis=1) + np.linalg.norm(pb - mid, axis=1)).sum())


def corner_count(mesh) -> int:
    return int(mesh.dofs.nodal_dofs.shape[1])


def corner_points(mesh) -> np.ndarray:
    return np.ascontiguousarray(mesh.p[:, : corner_count(mesh)].T)


def groups_of(mesh) -> dict:
    return {k: np.asarray(v, dtype=np.int64) for k, v in (mesh.boundaries or {}).items() if k != "_all"}


def su2_inputs(mesh, inlet_name: str, outlet_name: str, check=None) -> dict:
    check = check or (lambda: None)
    groups = groups_of(mesh)
    for name in (inlet_name, outlet_name):
        if name not in groups or not len(groups[name]):
            raise FlowError('The model has no face group named "%s".' % name)
    every = np.asarray(mesh.boundary_facets(), dtype=np.int64)
    walls = np.setdiff1d(every, np.concatenate([groups[inlet_name], groups[outlet_name]]))
    pts = corner_points(mesh)
    tris_in = mesh.facets[:, groups[inlet_name]].T
    n_out, c_in, a_in = plane_of(pts, tris_in, "inlet")
    if np.dot(n_out, c_in - pts.mean(axis=0)) < 0:
        n_out = -n_out
    tree, w, axes, mean = developed_profile(pts, tris_in, n_out, check)
    ids = np.unique(tris_in)
    values = profile_at(tree, w, axes, pts[ids]) / mean
    tris_out = mesh.facets[:, groups[outlet_name]].T
    _, c_out, a_out = plane_of(pts, tris_out, "outlet")
    return {
        "points": pts,
        "tets": mesh.t[:4].T,
        "markers": {"inlet": tris_in, "outlet": tris_out, "wall": mesh.facets[:, walls].T},
        "profile": (pts[ids], values, -n_out),
        "direction": -n_out,
        "inlet_ids": ids,
        "inlet_area": a_in,
        "outlet_ids": np.unique(tris_out),
        "length": float(np.dot(c_out - c_in, -n_out)),
        "perimeter": rim_perimeter(mesh, tris_in),
        "tris_in": tris_in,
        "tris_out": tris_out,
    }


def solve_flow(mesh, params: dict, check=None, runner=None) -> dict:
    t0 = time.time()
    check = check or (lambda: None)
    mu = need(params.get("viscosity"), "The viscosity", positive=True)
    rho = need(params.get("density", 1000.0), "The density", positive=True)
    inlet_name, outlet_name = str(params.get("inlet", "inlet")), str(params.get("outlet", "outlet"))
    speed, flow = params.get("speed"), params.get("flow")
    if (speed is None) == (flow is None):
        raise FlowError("Give either the mean inlet speed or the volume flow rate.")
    groups = {k: np.asarray(v, dtype=np.int64) for k, v in (mesh.boundaries or {}).items() if k != "_all"}
    for name in (inlet_name, outlet_name):
        if name not in groups or not len(groups[name]):
            raise FlowError('The model has no face group named "%s". Groups: %s.' % (name, ", ".join(sorted(groups)) or "none"))
    if inlet_name == outlet_name:
        raise FlowError("The inlet and outlet must be different faces.")
    if np.intersect1d(groups[inlet_name], groups[outlet_name]).size:
        raise FlowError("The inlet and outlet share a face.")
    every = np.asarray(mesh.boundary_facets(), dtype=np.int64)
    wall_facets = np.setdiff1d(every, np.concatenate([groups[inlet_name], groups[outlet_name]]))
    if not len(wall_facets):
        raise FlowError("The flow needs wall faces.")
    from skfem import Basis, BilinearForm, ElementTetP1, ElementTetP2, ElementVector, FacetBasis, LinearForm
    from skfem.helpers import div, ddot, dot, grad
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl

    m2 = mesh
    facets = {inlet_name: groups[inlet_name], outlet_name: groups[outlet_name], "_walls": wall_facets}
    wall_names = ["_walls"]
    nverts, nedges = corner_count(m2), m2.edges.shape[1]
    unknowns = unknown_count(nverts, nedges)
    limit = min(cap("unknowns", runner), int(params.get("max_unknowns", 1 << 60)))
    if unknowns > limit:
        raise FlowError("The flow problem has %d unknowns, above the limit of %d. Use a coarser mesh." % (unknowns, limit))
    memory = memory_estimate(unknowns, runner)
    from app.sim import fem

    free_mb = fem.available_mb()
    if free_mb is not None and memory / 1048576.0 > 0.7 * free_mb:
        raise FlowError("The flow solve needs about %.0f MB for a direct solve and only about %.0f MB is free. Use a coarser mesh." % (memory / 1048576.0, free_mb))
    warnings = []
    if not params.get("curved", True):
        warnings.append("The mesh has no mid-edge nodes, so the walls are faceted and the pressure drop of narrow passages reads high.")
    check()
    pts = corner_points(m2)
    tris_in, tris_out = m2.facets[:, groups[inlet_name]].T, m2.facets[:, groups[outlet_name]].T
    n_in_out, c_in, a_in = plane_of(pts, tris_in, "inlet")
    n_out_out, c_out, a_out = plane_of(pts, tris_out, "outlet")
    centre = pts.mean(axis=0)
    if np.dot(n_in_out, c_in - centre) < 0:
        n_in_out = -n_in_out
    direction = -n_in_out
    perimeter = rim_perimeter(m2, tris_in)
    tree, wprof, axes, _mean = developed_profile(pts, tris_in, n_in_out, check)

    elem = ElementVector(ElementTetP2())
    bu = Basis(m2, elem, intorder=6)
    bp = bu.with_element(ElementTetP1())
    a_form = BilinearForm(lambda u, v, w: mu * ddot(grad(u), grad(v)))
    b_form = BilinearForm(lambda u, v, w: -div(u) * v)
    check()
    amat = a_form.assemble(bu)
    bmat = b_form.assemble(bu, bp)
    nu = amat.shape[0]
    np_ = bmat.shape[0]
    kmat = sp.bmat([[amat, bmat.T], [bmat, None]], format="csc")
    check()

    inlet_dofs = bu.get_dofs(facets[inlet_name]).all()
    wall_dofs = np.unique(np.concatenate([bu.get_dofs(facets[n]).all() for n in wall_names]))
    loc = bu.doflocs[:, inlet_dofs].T
    owner = np.zeros(nu, dtype=int)
    for c in range(3):
        owner[bu.nodal_dofs[c]] = c
        owner[bu.edge_dofs[c]] = c
    comp = owner[inlet_dofs]
    prof = profile_at(tree, wprof, axes, loc)
    u0 = np.zeros(nu)
    u0[inlet_dofs] = prof * direction[comp]
    u0[wall_dofs] = 0.0
    fb_in = FacetBasis(m2, elem, facets=facets[inlet_name], intorder=6)
    flux_vec = LinearForm(lambda v, w: dot(w.n, v)).assemble(fb_in)
    raw = float(flux_vec @ u0)
    if raw >= 0 or not math.isfinite(raw):
        raise FlowError("The inlet profile does not flow into the model.")
    fb_p_in = FacetBasis(m2, ElementTetP1(), facets=facets[inlet_name], intorder=6)
    fb_p_out = FacetBasis(m2, ElementTetP1(), facets=facets[outlet_name], intorder=6)
    g_in = LinearForm(lambda v, w: v).assemble(fb_p_in)
    g_out = LinearForm(lambda v, w: v).assemble(fb_p_out)
    area = float(g_in.sum())
    target = float(flow) if flow is not None else float(speed) * area
    target = need(target, "The flow rate", positive=True)
    u0 *= target / -raw
    mean_speed = target / area
    d_h = 4.0 * area / perimeter if perimeter > 0 else float("nan")
    re = rho * mean_speed * d_h / mu
    if re > MAX_RE:
        warnings.append("Reynolds number %.0f is above %.0f: the flow is probably turbulent, and the creeping-flow solution is not valid." % (re, MAX_RE))
    elif re > 100:
        warnings.append("Reynolds number %.0f: inertia matters near bends and entrances, which this solver leaves out." % re)

    fixed = np.unique(np.concatenate([inlet_dofs, wall_dofs]))
    free_u = np.setdiff1d(np.arange(nu), fixed)
    free = np.concatenate([free_u, nu + np.arange(np_)])
    xfull = np.zeros(nu + np_)
    xfull[:nu] = u0
    rhs = -(kmat[:, :nu] @ u0)
    kff = kmat[free][:, free]
    check()
    x = spl.spsolve(kff, rhs[free])
    if not np.isfinite(x).all():
        raise FlowError("The solver returned non finite values; the mesh may be degenerate.")
    xfull[free] = x
    check()
    u = xfull[:nu]
    p = xfull[nu:]

    p_in = float(g_in @ p / g_in.sum())
    p_out = float(g_out @ p / g_out.sum())
    drop = p_in - p_out
    axis_len = float(np.dot(c_out - c_in, direction))
    result = {
        "model": MODEL,
        "label": LABEL,
        "pressure_drop": drop,
        "inlet_pressure": p_in,
        "outlet_pressure": p_out,
        "flow_rate": target,
        "mean_speed": mean_speed,
        "inlet_area": area,
        "outlet_area": float(g_out.sum()),
        "hydraulic_diameter": d_h,
        "reynolds": re,
        "length": axis_len,
        "unknowns": int(unknowns),
        "tets": int(m2.t.shape[1]),
        "memory_estimate": memory,
        "curved_geometry": bool(params.get("curved", True)),
        "seconds": round(time.time() - t0, 3),
        "warnings": warnings,
    }
    pv = p
    along = (pts - c_in) @ direction
    mid = (along > 0.25 * axis_len) & (along < 0.75 * axis_len)
    if mid.sum() >= 8:
        slope = np.polyfit(along[mid], pv[mid], 1)[0]
        result["developed_gradient"] = float(-slope)
    if perimeter > 0 and abs(4.0 * math.pi * area / perimeter ** 2 - 1.0) < 0.02 and axis_len > 0:
        diameter = math.sqrt(4.0 * area / math.pi)
        hp = 32.0 * mu * axis_len * mean_speed / diameter ** 2
        result["reference"] = {"kind": "Hagen-Poiseuille", "pressure_drop": hp, "gradient": hp / axis_len, "error_percent": 100.0 * (drop - hp) / hp, "diameter": diameter, "within_exit_tolerance": abs(drop - hp) <= 0.05 * hp}
        if "developed_gradient" in result:
            result["reference"]["gradient_error_percent"] = 100.0 * (result["developed_gradient"] - hp / axis_len) / (hp / axis_len)
    velocity = np.stack([u[bu.nodal_dofs[c]] for c in range(3)], axis=1)
    return {"summary": result, "fields": {"pressure": pv, "velocity": velocity, "speed": np.linalg.norm(velocity, axis=1)}}
