import math

import numpy as np

from app.flow.limits import FlowError, cap, need

LABEL = "First order fill estimate: Hele-Shaw flow on a midplane, isothermal, no frozen layer, no viscous heating, no compressibility. Pressure and fill times are indicative, not predictive."
STEP_MERGE = 0.05
CLOSING = 0.02
PICARD = 30
MAX_HISTORY = 240


def plate_formulas(length: float, width: float, gap: float, volume_flow: float, eta: float | None = None, k: float | None = None, n: float | None = None) -> dict:
    length = need(length, "The plate length", positive=True)
    width = need(width, "The plate width", positive=True)
    gap = need(gap, "The gap", positive=True)
    q = need(volume_flow, "The flow rate", positive=True)
    if eta is not None:
        dp = 12.0 * need(eta, "The viscosity", positive=True) * q * length / (width * gap ** 3)
        law = "newtonian"
    else:
        k = need(k, "The consistency K", positive=True)
        n = need(n, "The exponent n", positive=True, high=2.0)
        h = gap / 2.0
        dp = length * k * ((2.0 + 1.0 / n) * q / (2.0 * width * h ** (2.0 + 1.0 / n))) ** n
        law = "power_law"
    return {"law": law, "inlet_pressure": dp, "clamp_force": 0.5 * dp * length * width, "fill_time": length * width * gap / q}


def triangle_geometry(points: np.ndarray, tris: np.ndarray) -> tuple:
    a, b, c = points[tris[:, 0]], points[tris[:, 1]], points[tris[:, 2]]
    ab, ac = b - a, c - a
    cross = np.cross(ab, ac)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    if (area <= 1e-18).any():
        raise FlowError("The midplane has a triangle with no area.")
    lab = np.linalg.norm(ab, axis=1)
    e1 = ab / lab[:, None]
    n = cross / (2.0 * area)[:, None]
    e2 = np.cross(n, e1)
    x2, y2 = lab, np.zeros_like(lab)
    x3, y3 = (ac * e1).sum(axis=1), (ac * e2).sum(axis=1)
    bb = np.stack([y2 - y3, y3 - 0.0, 0.0 - y2], axis=1)
    cc = np.stack([x3 - x2, 0.0 - x3, x2 - 0.0], axis=1)
    grad = np.stack([bb, cc], axis=1) / (2.0 * area)[:, None, None]
    unit = area[:, None, None] * np.einsum("eki,ekj->eij", grad, grad)
    return area, unit, n


def run(points, tris, thickness, gates, volume_flow=None, fill_time=None, eta=None, k=None, n=None, pressure_limit=None, check=None, runner=None, pull=None) -> dict:
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl

    check = check or (lambda: None)
    points = np.ascontiguousarray(points, dtype=np.float64)
    tris = np.ascontiguousarray(tris, dtype=np.int64)
    nn = len(points)
    if len(tris) > cap("midplane_triangles", runner):
        raise FlowError("The midplane has %d triangles, above the limit of %d." % (len(tris), cap("midplane_triangles", runner)))
    if not len(tris) or tris.min() < 0 or tris.max() >= nn:
        raise FlowError("The midplane triangles do not fit its points.")
    thick = np.asarray(thickness, dtype=np.float64)
    if thick.ndim == 0:
        thick = np.full(nn, float(thick))
    if thick.shape != (nn,) or not np.isfinite(thick).all() or (thick <= 0).any():
        raise FlowError("Every midplane node needs a positive thickness.")
    newtonian = eta is not None
    if newtonian:
        eta = need(eta, "The viscosity", positive=True)
    else:
        k = need(k, "The consistency K", positive=True)
        n = need(n, "The exponent n", positive=True, high=2.0)
    gates = np.unique(np.asarray(gates, dtype=np.int64))
    if not len(gates) or gates.min() < 0 or gates.max() >= nn:
        raise FlowError("The fill needs at least one gate node.")
    area, unit, normal = triangle_geometry(points, tris)
    h_tri = thick[tris].mean(axis=1)
    cell = np.zeros(nn)
    for i in range(3):
        np.add.at(cell, tris[:, i], area * h_tri / 3.0)
    total_volume = float(cell.sum())
    if volume_flow is None:
        ft = need(fill_time, "The fill time", positive=True)
        q_target = total_volume / ft
    else:
        q_target = need(volume_flow, "The flow rate", positive=True)
    if newtonian:
        coef = h_tri ** 3 / (12.0 * eta)
    else:
        coef0 = (2.0 * n / (2.0 * n + 1.0)) * (h_tri / 2.0) ** (2.0 + 1.0 / n) * k ** (-1.0 / n)
    adj = sp.coo_matrix((np.ones(3 * len(tris)), (np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]]), np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]]))), shape=(nn, nn)).tocsr()
    adj = adj + adj.T
    status = np.zeros(nn, dtype=np.int8)
    frac = np.zeros(nn)
    status[gates] = 2
    frac[gates] = 1.0
    arrival = np.full(nn, np.nan)
    arrival[gates] = 0.0

    def promote():
        full = status == 2
        reach = (adj @ full.astype(np.float64)) > 0
        status[(status == 0) & reach] = 1

    promote()
    t = float(cell[gates].sum()) / q_target
    history = []
    peak = 0.0
    closing = 0.0
    snap = None
    steps = 0
    gscale = np.ones(len(tris))
    seen = np.zeros(len(tris), dtype=bool)
    max_steps = cap("fill_steps", runner)
    last_p = None
    last_scale = 1.0
    filled_volume = float(cell[gates].sum())
    while (status != 2).any():
        steps += 1
        if steps > max_steps:
            raise FlowError("The fill needed more than %d steps. Use a coarser midplane." % max_steps)
        check()
        active = (status[tris] > 0).all(axis=1)
        if not active.any():
            raise FlowError("The melt cannot reach part of the cavity; it is not connected to the gate.")
        tri_a = tris[active]
        picard = 1 if newtonian else PICARD
        p = None
        if not newtonian:
            fresh = active & ~seen
            if fresh.any() and seen.any():
                gscale[fresh] = np.median(gscale[active & seen])
            seen |= active
        for it in range(picard):
            s_e = coef[active] if newtonian else coef0[active] * np.maximum(gscale[active], 1e-30) ** (1.0 / n - 1.0)
            ke = s_e[:, None, None] * unit[active]
            rows = np.repeat(tri_a[:, :, None], 3, axis=2).ravel()
            cols = np.repeat(tri_a[:, None, :], 3, axis=1).ravel()
            kmat = sp.coo_matrix((ke.ravel(), (rows, cols)), shape=(nn, nn)).tocsr()
            pv = np.zeros(nn)
            pv[gates] = 1.0
            unknown = np.nonzero((status == 2) & ~np.isin(np.arange(nn), gates))[0]
            if len(unknown):
                rhs = -(kmat[unknown][:, gates] @ pv[gates])
                sub = kmat[unknown][:, unknown].tocsc()
                pv[unknown] = spl.spsolve(sub, rhs)
            if not np.isfinite(pv).all():
                raise FlowError("The fill solve failed; the midplane may be degenerate.")
            p = pv
            if not newtonian:
                new = np.maximum(unit_grad(points, tri_a, p), 1e-30)
                old = gscale[active]
                change = float(np.max(np.abs(np.log(new / old))))
                gscale[active] = np.sqrt(new * old) if it < PICARD - 1 else new
                if change < 5e-3:
                    break
        flux = -(kmat @ p)
        front = np.nonzero(status == 1)[0]
        q_front = flux[front]
        q_total = float(q_front[q_front > 0].sum())
        if q_total <= 0:
            raise FlowError("The fill stalled: no melt reaches the front.")
        ratio = q_target / q_total
        scale = ratio ** (n if not newtonian else 1.0)
        closing = max(closing, scale)
        if filled_volume < (1.0 - CLOSING) * total_volume:
            peak = max(peak, scale)
            snap = p * scale
        q_real = q_front * ratio
        remain = cell[front] * (1.0 - frac[front])
        with np.errstate(divide="ignore", invalid="ignore"):
            dt_i = np.where(q_real > 0, remain / q_real, np.inf)
        dt = float(dt_i.min())
        if not math.isfinite(dt):
            raise FlowError("The fill stalled: no front node receives melt.")
        done = dt_i <= dt * (1.0 + STEP_MERGE)
        dt = float(dt_i[done].max()) if done.any() else dt
        gain = np.minimum(q_real * dt / cell[front], 1.0 - frac[front])
        gain[q_real <= 0] = 0.0
        frac[front] = frac[front] + gain
        t += dt
        filled_volume += float((gain * cell[front]).sum())
        became = front[frac[front] >= 1.0 - 1e-9]
        frac[became] = 1.0
        status[became] = 2
        arrival[became] = t
        last_p, last_scale = p, scale
        if len(history) < MAX_HISTORY or steps % max(1, steps // MAX_HISTORY) == 0:
            history.append({"time": t, "fraction": min(1.0, filled_volume / total_volume), "pressure": scale})
        promote()
    pressure = snap if snap is not None else last_p * last_scale
    p_elem = pressure[tris].mean(axis=1)
    if pull is not None:
        d = np.asarray(pull, dtype=float)
        d = d / np.linalg.norm(d)
        proj = area * np.abs(normal @ d)
    else:
        proj = area
    clamp = float((p_elem * proj).sum())
    notes = []
    warnings = []
    limit_hit = False
    if pressure_limit is not None:
        limit = need(pressure_limit, "The pressure limit", positive=True)
        if peak > limit:
            limit_hit = True
            warnings.append("The estimated injection pressure %.3g Pa is above the machine limit %.3g Pa." % (peak, limit))
    notes.append("Constant flow rate; the inlet pressure follows the filling area. Frozen layer, heating and compressibility are left out, which makes real pressures higher.")
    last_nodes = np.argsort(np.nan_to_num(arrival, nan=-1.0))[-3:][::-1]
    return {
        "label": LABEL,
        "fill_time": float(t),
        "flow_rate": q_target,
        "volume": total_volume,
        "peak_pressure": float(peak),
        "closing_pressure": float(closing),
        "end_pressure": float(pressure.max()),
        "clamp_force": clamp,
        "steps": steps,
        "arrival": arrival,
        "pressure": pressure,
        "history": history,
        "last_filled": [int(i) for i in last_nodes],
        "limit_exceeded": limit_hit,
        "warnings": warnings,
        "notes": notes,
    }


def unit_grad(points: np.ndarray, tris: np.ndarray, p: np.ndarray) -> np.ndarray:
    a, b, c = points[tris[:, 0]], points[tris[:, 1]], points[tris[:, 2]]
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    twice = np.linalg.norm(n, axis=1)
    n = n / twice[:, None]
    g = (np.cross(n, ac) * (p[tris[:, 1]] - p[tris[:, 0]])[:, None] + np.cross(ab, n) * (p[tris[:, 2]] - p[tris[:, 0]])[:, None]) / twice[:, None]
    return np.linalg.norm(g, axis=1)
