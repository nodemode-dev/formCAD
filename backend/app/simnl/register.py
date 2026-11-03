import math
import time

import numpy as np
from skfem import Basis, ElementTetP2

from app.sim import fem, registry
from app.sim.fem import SimError
from app.sim.solvers import field, need_material, run_static, structural_fixtures
from app.simnl import contact as ct
from app.simnl import elements as el
from app.simnl import explicit, loads as lds, newton
from app.simnl import fatigue as ft
from app.simnl import material as mt
from app.simnl.solid import Solid

MODELS = ("elastic", "plastic", "neohookean")
METHODS = ("penalty", "augmented")
SEQUENCES = ("together", "loads_first")
MAX_PLANES = 8
MAX_HISTORY_POINTS = 20000
SWAP12 = [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]
SWAP12_P1 = [0, 2, 1, 3]

CONTACT_OPTIONS = {
    "contact_method": {"type": "choice", "choices": list(METHODS), "default": "augmented"},
    "penalty_scale": {"type": "number", "default": 10.0, "min": 0.01, "max": 1000.0},
    "rigid_planes": {"type": "list", "default": []},
    "self_contact_symmetric": {"type": "boolean", "default": True},
}
STATIC_OPTIONS = {
    "material_model": {"type": "choice", "choices": list(MODELS), "default": "plastic"},
    "hardening_modulus_pa": {"type": "number", "default": 0.0, "min": 0.0},
    "hardening_curve": {"type": "list", "default": None},
    "steps": {"type": "integer", "default": 10, "min": 1, "max": 200},
    "max_iterations": {"type": "integer", "default": 25, "min": 3, "max": 60},
    "tolerance": {"type": "number", "default": 1e-8, "min": 1e-12, "max": 1e-3},
    "load_scale": {"type": "number", "default": 1.0},
    "sequence": {"type": "choice", "choices": list(SEQUENCES), "default": "together"},
    "stop_at_collapse": {"type": "boolean", "default": False},
    **CONTACT_OPTIONS,
}
EVENT_OPTIONS = {**STATIC_OPTIONS, "sequence": {"type": "choice", "choices": list(SEQUENCES), "default": "loads_first"}}
EXPLICIT_OPTIONS = {
    "end_time_s": {"type": "number", "default": None, "min": 1e-9},
    "velocity": {"type": "vector", "default": [0.0, 0.0, 0.0]},
    "ramp_s": {"type": "number", "default": 0.0, "min": 0.0},
    "damping_alpha": {"type": "number", "default": 0.0, "min": 0.0},
    "dt_safety": {"type": "number", "default": 0.8, "min": 0.1, "max": 0.95},
    "frames": {"type": "integer", "default": 40, "min": 2, "max": 200},
    "max_steps": {"type": "integer", "default": 1000000, "min": 10, "max": 5000000},
    "penalty_scale": {"type": "number", "default": 1.0, "min": 0.001, "max": 100.0},
    "material_model": {"type": "choice", "choices": list(MODELS), "default": "elastic"},
    "hardening_modulus_pa": {"type": "number", "default": 0.0, "min": 0.0},
    "rigid_planes": {"type": "list", "default": []},
    "self_contact_symmetric": {"type": "boolean", "default": True},
}
FATIGUE_OPTIONS = {
    "sn": {"type": "object", "default": None},
    "mean_stress_correction": {"type": "choice", "choices": list(ft.CORRECTIONS), "default": "goodman"},
    "history": {"type": "list", "default": None},
    "stress_ratio": {"type": "number", "default": 0.0, "min": -1.0, "max": 0.99},
    "max_scale": {"type": "number", "default": 1.0, "min": 0.0},
}


def num(opts, key, default, lo=None, hi=None, integer=False):
    v = opts.get(key, default)
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SimError("The option %s must be a number." % key)
    if not math.isfinite(x):
        raise SimError("The option %s must be a finite number." % key)
    if lo is not None and x < lo:
        raise SimError("The option %s must be at least %g." % (key, lo))
    if hi is not None and x > hi:
        raise SimError("The option %s must be at most %g." % (key, hi))
    return int(round(x)) if integer else x


def choice(opts, key, default, allowed):
    v = opts.get(key, default)
    if v not in allowed:
        raise SimError("The option %s is one of: %s." % (key, ", ".join(allowed)))
    return v


def caps(ctx):
    dofs = int(min(ctx.limits["dofs"] * 0.3, 45000))
    elems = int(min(ctx.limits["elements"] * 0.05, 20000))
    return dofs, elems


def orient(X, conn):
    p = X[conn[:, :4]]
    v = np.einsum("ei,ei->e", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), p[:, 3] - p[:, 0])
    bad = v < 0.0
    if np.any(bad):
        perm = SWAP12 if conn.shape[1] == 10 else SWAP12_P1
        conn = conn.copy()
        conn[bad] = conn[bad][:, perm]
    return conn


class Body:
    def __init__(self, ctx, order):
        model = ctx.model
        mesh = model.mesh
        self.model = model
        self.nv = int(model.nodes_mm.shape[0])
        if order == 2:
            basis = Basis(mesh, ElementTetP2())
            if not np.array_equal(basis.nodal_dofs[0], np.arange(self.nv)):
                raise SimError("The mesh vertex numbering does not match the second order basis.")
            self.X = np.ascontiguousarray(basis.doflocs.T)
            conn = np.ascontiguousarray(basis.element_dofs.T).astype(np.int64)
        else:
            self.X = np.ascontiguousarray(model.nodes_mm * 1e-3)
            conn = np.ascontiguousarray(mesh.t[:4].T).astype(np.int64)
        self.order = order
        self.conn = orient(self.X, conn)
        self.mesh = mesh
        self.ne = len(self.conn)
        self.nn = len(self.X)
        self.corner_tets = np.ascontiguousarray(mesh.t[:4])
        self._mid = None

    def faces(self, name):
        mesh = self.mesh
        fac = fem.facets_of(self.model, name)
        tri = np.ascontiguousarray(mesh.facets[:, fac].T[:, :3]).astype(np.int64)
        owner = mesh.f2t[0, fac]
        cen_e = self.X[self.conn[owner, :4]].mean(axis=1)
        p = self.X[tri]
        nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        flip = np.einsum("ij,ij->i", nrm, p.mean(axis=1) - cen_e) < 0.0
        tri[flip] = tri[flip][:, [0, 2, 1]]
        full = ct.surface_nodes(self.conn, tri) if self.order == 2 else tri
        return tri, full


def make_body(ctx, order):
    return Body(ctx, order)


def solid_material(ctx, opts, kind_default):
    m = ctx.material
    model = choice(opts, "material_model", kind_default, MODELS)
    spec = {"E": m["E"], "nu": m["nu"], "rho": m.get("rho") or 0.0}
    if model == "elastic":
        spec["kind"] = "elastic"
    elif model == "neohookean":
        spec["kind"] = "neohookean"
    else:
        spec["kind"] = "plastic"
        curve = opts.get("hardening_curve")
        if curve:
            if not isinstance(curve, list) or len(curve) > 64:
                raise SimError("The hardening curve is a list of at most 64 pairs [plastic strain, flow stress in Pa].")
            spec["curve"] = curve
        else:
            sy = m.get("sigma_y")
            if not sy:
                raise SimError("Plastic analysis needs the yield strength of the material (sigma_y) or a hardening curve.")
            spec["sy"] = sy
            spec["H"] = num(opts, "hardening_modulus_pa", 0.0, 0.0)
    try:
        return mt.Material(spec)
    except mt.MaterialError as err:
        raise SimError(str(err))


def load_vector(ctx, body, solid):
    f = np.zeros(3 * body.nn)
    rho = float(ctx.material.get("rho") or 0.0)
    for ld in ctx.loads:
        kind = ld.get("type")
        if kind not in ("force", "pressure", "traction", "gravity", "reference_load"):
            continue
        if kind == "gravity":
            d = fem.unit(ld.get("direction") or [0, 0, -1])
            g = float(ld.get("value", 9.81))
            if rho <= 0.0:
                raise SimError("Gravity needs a density in the material.")
            geo = solid.geo
            w = np.einsum("qa,eq->ea", geo.N, geo.dV) * rho * g
            for c in range(3):
                f[c::3] += np.bincount(geo.conn.ravel(), weights=(w * d[c]).ravel(), minlength=body.nn)
            continue
        tri, full = body.faces("load:" + ld["id"])
        if kind in ("force", "reference_load"):
            d = fem.unit(ld.get("direction") or [0, 0, -1])
            area = lds.total_area(body.X, full)
            f += lds.traction_forces(body.X, full, d * float(ld.get("value", 0.0)) / area, 3 * body.nn)
        elif kind == "traction":
            f += lds.traction_forces(body.X, full, [float(x) for x in (ld.get("vector") or ld.get("direction"))], 3 * body.nn)
        else:
            f += lds.traction_forces(body.X, full, None, 3 * body.nn, pressure=float(ld.get("value", 0.0)))
    return f


def fixed_values(ctx, body, scale):
    fixed = {}
    for fx in structural_fixtures(ctx):
        kind = fx.get("type")
        _tri, full = body.faces("fix:" + fx["id"])
        nodes = np.unique(full.ravel())
        if kind == "fixed":
            keep = [0, 1, 2]
            val = [0.0, 0.0, 0.0]
        elif kind == "symmetry":
            keep = [int(fx.get("axis", 0))]
            val = [0.0, 0.0, 0.0]
        elif kind == "roller":
            free = {int(a) for a in fx.get("axes") or []}
            keep = [i for i in range(3) if i not in free]
            val = [0.0, 0.0, 0.0]
        else:
            mask = fx.get("components") or [1, 1, 1]
            keep = [i for i in range(3) if mask[i]]
            val = [float(x) * scale for x in (fx.get("value") or [0, 0, 0])]
        for c in keep:
            for n in nodes:
                fixed[3 * int(n) + c] = val[c]
    return fixed


def face_size(X, full):
    p = X[full[:, :3]]
    e = np.concatenate([np.linalg.norm(p[:, 1] - p[:, 0], axis=1), np.linalg.norm(p[:, 2] - p[:, 1], axis=1), np.linalg.norm(p[:, 0] - p[:, 2], axis=1)])
    return float(e.mean())


def build_contact(ctx, body, solid, opts, method, eps_scale, notes, stable_dt=None):
    contacts = [c for c in ctx.contacts if c.get("type") in ("frictionless", "frictional")]
    for c in ctx.contacts:
        if c.get("type") == "bonded":
            notes.append("Contact %s is bonded; a bonded contact inside one part has no effect and was ignored." % c["id"])
    planes = opts.get("rigid_planes") or []
    if not isinstance(planes, list) or len(planes) > MAX_PLANES:
        raise SimError("rigid_planes is a list of at most %d planes." % MAX_PLANES)
    if not contacts and not planes:
        return None, {}
    by_id = {c["id"]: c for c in contacts}
    hs = []
    work = []
    for c in contacts:
        trA, fullA = body.faces("contact:%s:a" % c["id"])
        trB, fullB = body.faces("contact:%s:b" % c["id"])
        work.append((c, trA, fullA, trB, fullB))
        hs.append(face_size(body.X, fullA))
    for pl in planes:
        c = by_id.get(str(pl.get("contact")))
        if c is None:
            raise SimError("A rigid plane names the contact %s, which is not part of this study." % pl.get("contact"))
    h_c = min(hs) if hs else face_size(body.X, body.faces("contact:%s:a" % contacts[0]["id"])[1])
    E = float(ctx.material["E"])
    eps_n = eps_scale * E / h_c
    if stable_dt is not None:
        eps_n = min(eps_n, stable_dt)
    cn = ct.Contact(body.nn, eps_n, method=method)
    used_planes = {str(p.get("contact")) for p in planes}
    for c, trA, fullA, trB, fullB in work:
        mu = float(c.get("friction", 0.0)) if c.get("type") == "frictional" else 0.0
        nodesA, areaA = ct.tributary(body.X, trA, fullA)
        if c["id"] in used_planes:
            for pl in planes:
                if str(pl.get("contact")) != c["id"]:
                    continue
                pt = np.array([float(v) for v in pl.get("point_mm", [0, 0, 0])]) * 1e-3
                nm = np.array([float(v) for v in pl.get("normal", [0, 0, 1])])
                cn.add_plane(nodesA, areaA, pt, nm, mu=mu)
        else:
            if mu > 0.0:
                notes.append("Friction between two deformable faces is not modelled; contact %s is solved frictionless." % c["id"])
            radius = 4.0 * h_c
            cn.add_surface(nodesA, areaA, trB, radius)
            if opts.get("self_contact_symmetric", True):
                nodesB, areaB = ct.tributary(body.X, trB, fullB)
                cn.add_surface(nodesB, areaB, trA, radius)
    return cn, {"h_contact_m": h_c, "eps_n": eps_n, "pairs": len(cn.pairs)}


def nodal(body, elem_values):
    return fem.element_to_nodes(body.corner_tets, np.asarray(elem_values, dtype=float), body.nv)


def run_nonlinear(ctx, default_sequence="together"):
    started = time.time()
    need_material(ctx, ("E", "nu"))
    opts = ctx.options
    cap_dofs, cap_elems = caps(ctx)
    body = make_body(ctx, 2)
    if body.ne > cap_elems:
        raise SimError("The nonlinear study has %d elements, over the limit of %d for this caller. Use a larger element size." % (body.ne, cap_elems))
    size = fem.check_size(3 * body.nn, {"dofs": cap_dofs}, "nonlinear solve")
    steps = num(opts, "steps", 10, 1, 200, True)
    max_iter = num(opts, "max_iterations", 25, 3, 60, True)
    tol = num(opts, "tolerance", 1e-8, 1e-12, 1e-3)
    scale = num(opts, "load_scale", 1.0)
    sequence = choice(opts, "sequence", default_sequence, SEQUENCES)
    method = choice(opts, "contact_method", "augmented", METHODS)
    eps_scale = num(opts, "penalty_scale", 10.0, 0.01, 1000.0)
    stop_collapse = bool(opts.get("stop_at_collapse", False))
    kind_default = "plastic" if ctx.material.get("sigma_y") else "elastic"
    mat = solid_material(ctx, opts, kind_default)
    ctx.progress(0.03, "Building elements")
    solid = Solid(body.X, body.conn, mat, mat.kind == "neohookean")
    f = load_vector(ctx, body, solid) * scale
    fixed = fixed_values(ctx, body, scale)
    if len(fixed) < 6 and not np.any(f):
        raise SimError("The study has no load and no prescribed displacement.")
    notes = []
    cn, cinfo = build_contact(ctx, body, solid, opts, method, eps_scale, notes)
    prob = newton.Problem(body.X, [solid], fixed, f, cn, sequence)

    def cancel():
        ctx.check()
        return False

    def progress(lam, msg):
        ctx.progress(0.1 + 0.8 * lam, msg)

    pen_tol = 1e-4
    ctx.progress(0.1, "Load stepping")
    try:
        res = newton.solve_static(prob, steps=steps, max_iter=max_iter, tol=tol, max_halvings=8 if stop_collapse else 6, cancel=cancel, progress=progress, time_limit=None, pen_tol=pen_tol, al_max=12, stop_on_failure=stop_collapse)
    except newton.SolveFailed as err:
        raise SimError(str(err))
    except TimeoutError as err:
        raise registry.Cancelled(str(err))
    except newton.Cancelled:
        raise registry.Cancelled("The study was cancelled.")
    if not res["history"]:
        raise SimError("The first load step did not converge. Use more steps or a smaller load.")
    ctx.progress(0.93, "Collecting results")
    u = res["u"]
    nv = body.nv
    disp = u.reshape(-1, 3)[:nv]
    mag = np.linalg.norm(disp, axis=1)
    ef = solid.element_fields(res["auxs"][0])
    vm_n = nodal(body, ef["von_mises"])
    pe_n = nodal(body, ef["plastic_strain"])
    fields = {"disp": disp, "disp_mag": mag, "vm": vm_n, "plastic_strain": pe_n}
    meta_fields = [
        field("disp", "m", "node", 3, label="Displacement"),
        field("disp_mag", "m", "node", 1, label="Displacement magnitude"),
        field("vm", "Pa", "node", 1, label="Von Mises stress"),
        field("plastic_strain", "1", "node", 1, label="Equivalent plastic strain"),
    ]
    contact_summary = None
    if cn is not None:
        fc, _ = cn.evaluate(body.X.ravel() + u, False)
        cf = np.linalg.norm(fc.reshape(-1, 3), axis=1)[:nv]
        fields["contact_force"] = cf
        meta_fields.append(field("contact_force", "N", "node", 1, label="Contact force"))
        contact_summary = {**cinfo, "method": method, "penetration_m": float(cn.last.get("penetration", 0.0)), "active_nodes": int(cn.last.get("active", 0)), "normal_force_n": float(cn.last.get("normal_force", 0.0))}
    hist = res["history"]
    keep = hist if len(hist) <= 200 else hist[:: int(math.ceil(len(hist) / 200))]
    rows = []
    for h in keep:
        row = {"load_factor": h["lambda"], "iterations": h["iterations"], "final_residual": h["residuals"][-1], "umax_m": h["umax"], "reaction_n": h["reaction_total"]}
        if "contact" in h:
            row["contact"] = {"penetration_m": float(h["contact"].get("penetration", 0.0)), "active": int(h["contact"].get("active", 0)), "normal_force_n": float(h["contact"].get("normal_force", 0.0))}
        rows.append(row)
    summary = {
        "model": mat.kind,
        "max_displacement_m": float(mag.max()),
        "max_von_mises_pa": float(ef["von_mises"].max()),
        "max_plastic_strain": float(ef["plastic_strain"].max()),
        "yielded_fraction": float(ef["yielded"].mean()),
        "reached_load_factor": float(res["reached"]),
        "limit_load_factor": res["reached"] if res["failed_at"] is not None else None,
        "converged_to_full_load": res["failed_at"] is None,
        "newton_iterations": int(res["iterations"]),
        "reactions_n": [float(x) for x in hist[-1]["reaction_total"]],
        "steps": rows,
        "contact": contact_summary,
        "notes": notes,
        "size": size,
        "counts": {"nodes": nv, "elements": body.ne, "dofs": 3 * body.nn},
        "seconds": round(time.time() - started, 3),
    }
    yield_pa = ctx.material.get("sigma_y")
    if yield_pa and mat.kind != "neohookean":
        summary["safety_factor_vs_yield"] = float(yield_pa / max(float(ef["von_mises"].max()), 1e-300))
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p2"})


def run_quasistatic(ctx):
    return run_nonlinear(ctx, "loads_first")


def run_explicit_event(ctx):
    started = time.time()
    need_material(ctx, ("E", "nu", "rho"))
    opts = ctx.options
    cap_dofs, cap_elems = caps(ctx)
    body = make_body(ctx, 1)
    if body.ne > cap_elems:
        raise SimError("The dynamic study has %d elements, over the limit of %d for this caller. Use a larger element size." % (body.ne, cap_elems))
    size = fem.check_size(3 * body.nn, {"dofs": cap_dofs}, "explicit run")
    t_end = num(opts, "end_time_s", None, 1e-9)
    if t_end is None:
        raise SimError("An explicit event needs end_time_s, the time to simulate in seconds.")
    safety = num(opts, "dt_safety", 0.8, 0.1, 0.95)
    ramp = num(opts, "ramp_s", 0.0, 0.0)
    alpha_m = num(opts, "damping_alpha", 0.0, 0.0)
    frames = num(opts, "frames", 40, 2, 200, True)
    max_steps = num(opts, "max_steps", 1000000, 10, 5000000, True)
    eps_scale = num(opts, "penalty_scale", 1.0, 0.001, 100.0)
    vel = opts.get("velocity") or [0.0, 0.0, 0.0]
    if not isinstance(vel, (list, tuple)) or len(vel) != 3:
        raise SimError("velocity is three numbers in metres per second.")
    vel = [float(x) for x in vel]
    mat = solid_material(ctx, opts, "elastic")
    solid = Solid(body.X, body.conn, mat, mat.kind == "neohookean")
    f = load_vector(ctx, body, solid)
    fixed = fixed_values(ctx, body, 1.0)
    fixed = {d: 0.0 for d in fixed}
    notes = []
    dt, c, hmin = explicit.stable_dt(body.X, solid, safety)
    mass = solid.mass_lumped(body.nn)
    stable = None
    cn = None
    cinfo = {}
    planes = opts.get("rigid_planes") or []
    contacts_present = any(c_.get("type") in ("frictionless", "frictional") for c_ in ctx.contacts)
    if contacts_present or planes:
        probe, _ = build_contact(ctx, body, solid, opts, "penalty", eps_scale, notes)
        if probe is not None:
            lim = np.inf
            for pr in probe.pairs:
                lim = min(lim, float(np.min(mass[pr["nodes"]] / np.maximum(pr["area"], 1e-300))) / dt**2)
            stable = lim
            cn, cinfo = build_contact(ctx, body, solid, opts, "penalty", eps_scale, notes, stable_dt=stable)
    prob = newton.Problem(body.X, [solid], fixed, f, cn)
    v0 = np.zeros(3 * body.nn)
    for k in range(3):
        v0[k::3] = vel[k]
    ctx.progress(0.1, "Stepping")

    def cancel():
        ctx.check()
        return False

    def progress(frac, msg):
        ctx.progress(0.1 + 0.8 * frac, msg)

    remaining = max(30.0, (ctx._deadline - time.time()) if getattr(ctx, "_deadline", None) else 600.0)
    try:
        res = explicit.run_explicit(prob, v0, t_end, safety, ramp, alpha_m, frames, 0, max_steps, remaining, cancel, progress)
    except explicit.ExplicitError as err:
        raise SimError(str(err))
    except TimeoutError as err:
        raise registry.Cancelled(str(err))
    except newton.Cancelled:
        raise registry.Cancelled("The study was cancelled.")
    ctx.progress(0.93, "Collecting results")
    nv = body.nv
    u = res["u"]
    disp = u.reshape(-1, 3)[:nv]
    mag = np.linalg.norm(disp, axis=1)
    ef = solid.element_fields(res["auxs"][0])
    fields = {
        "disp": disp,
        "disp_mag": mag,
        "vm": nodal(body, ef["von_mises"]),
        "plastic_strain": nodal(body, ef["plastic_strain"]),
        "disp_frames": res["frames"][:, :nv, :],
        "frame_time": res["frame_time"],
        "history_time": res["time"],
        "history_kinetic_j": res["kinetic"],
        "history_internal_work_j": res["internal_work"],
        "history_external_work_j": res["external_work"],
        "history_contact_force_n": res["contact_force"],
    }
    meta_fields = [
        field("disp", "m", "node", 3, label="Displacement at the end"),
        field("disp_mag", "m", "node", 1, label="Displacement magnitude"),
        field("vm", "Pa", "node", 1, label="Von Mises stress"),
        field("plastic_strain", "1", "node", 1, label="Equivalent plastic strain"),
        field("disp_frames", "m", "frames", 3, len(res["frame_time"]), "Displacement frames"),
        field("frame_time", "s", "series", 1, label="Frame time"),
        field("history_time", "s", "series", 1, label="History time"),
        field("history_kinetic_j", "J", "series", 1, label="Kinetic energy"),
        field("history_internal_work_j", "J", "series", 1, label="Internal work"),
        field("history_external_work_j", "J", "series", 1, label="External work"),
        field("history_contact_force_n", "N", "series", 1, label="Contact normal force"),
    ]
    force = res["contact_force"]
    impulse = float(np.trapezoid(force, res["time"])) if len(force) > 1 else 0.0
    summary = {
        "time_step_s": res["dt"],
        "steps": res["steps"],
        "wave_speed_m_s": res["wave_speed"],
        "smallest_element_m": res["h_min"],
        "end_time_s": t_end,
        "max_displacement_m": float(mag.max()),
        "max_von_mises_pa": float(ef["von_mises"].max()),
        "max_plastic_strain": float(ef["plastic_strain"].max()),
        "peak_contact_force_n": float(force.max()) if len(force) else 0.0,
        "contact_impulse_ns": impulse,
        "final_kinetic_j": float(res["kinetic"][-1]) if len(res["kinetic"]) else 0.0,
        "contact": ({**cinfo, "stable_stiffness_limit": stable} if cn is not None else None),
        "notes": notes + ["The explicit run uses four-node tetrahedra on the corner nodes of the mesh and small strain; shear and bending response is stiffer than with second-order elements."],
        "size": size,
        "counts": {"nodes": nv, "elements": body.ne, "dofs": 3 * body.nn},
        "seconds": round(time.time() - started, 3),
    }
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p1"})


def history_points(opts):
    hist = opts.get("history")
    if hist:
        if not isinstance(hist, list) or len(hist) < 2 or len(hist) > MAX_HISTORY_POINTS:
            raise SimError("history is a list of 2 to %d load multipliers at the turning points of one repeat." % MAX_HISTORY_POINTS)
        try:
            return [float(x) for x in hist]
        except (TypeError, ValueError):
            raise SimError("history holds numbers only.")
    top = num(opts, "max_scale", 1.0, 0.0)
    ratio = num(opts, "stress_ratio", 0.0, -1.0, 0.99)
    return [top, ratio * top]


def run_fatigue(ctx):
    started = time.time()
    need_material(ctx, ("E", "nu"))
    opts = ctx.options
    try:
        sn = ft.SN(opts.get("sn"))
    except ft.FatigueError as err:
        raise SimError(str(err))
    method = choice(opts, "mean_stress_correction", "goodman", ft.CORRECTIONS)
    sigma_u = ctx.material.get("sigma_u")
    sigma_y = ctx.material.get("sigma_y")
    pts = history_points(opts)
    try:
        cycles = ft.merge_cycles(ft.rainflow_repeating(pts))
        blocks = [(rng / 2.0, mean, cnt) for rng, mean, cnt in cycles if rng > 0.0]
        if not blocks:
            raise SimError("The load history has no cycles (every point is the same).")
        ft.equivalent_amplitude(1.0, 0.0, method, sigma_u, sigma_y)
    except ft.FatigueError as err:
        raise SimError(str(err))
    base = run_static(ctx)
    ctx.progress(0.9, "Counting damage")
    vm_n = np.asarray(base.fields["vm"], dtype=float)
    dn = ft.damage(sn, blocks, sigma_u, sigma_y, method, vm_n)
    vm_q = float(base.summary["max_von_mises_pa"])
    dq = float(ft.damage(sn, blocks, sigma_u, sigma_y, method, vm_q))
    with np.errstate(divide="ignore"):
        life_n = np.where(dn > 0.0, 1.0 / np.maximum(dn, 1e-300), ft.LIFE_CAP)
        life_q = (1.0 / dq) if dq > 0.0 else ft.LIFE_CAP
    per_repeat = float(sum(cnt for _, _, cnt in blocks))
    fields = dict(base.fields)
    fields["damage"] = dn
    fields["life_repeats"] = np.minimum(life_n, ft.LIFE_CAP)
    fields["log10_life_cycles"] = np.log10(np.minimum(life_n * per_repeat, ft.LIFE_CAP))
    meta_fields = list(base.meta.get("fields", [])) + [
        field("damage", "1", "node", 1, label="Damage per repeat"),
        field("life_repeats", "1", "node", 1, label="Life in repeats of the history"),
        field("log10_life_cycles", "1", "node", 1, label="Log10 of life in cycles"),
    ]
    worst = int(np.argmin(life_n))
    summary = dict(base.summary)
    summary.update(
        {
            "min_life_repeats": float(min(life_q, ft.LIFE_CAP)),
            "min_life_cycles": float(min(life_q * per_repeat, ft.LIFE_CAP)),
            "worst_node_position_mm": [float(x) for x in ctx.model.nodes_mm[worst]],
            "cycles_per_repeat": per_repeat,
            "cycle_table": [{"range": r, "mean": m, "count": c} for r, m, c in cycles],
            "mean_stress_correction": method,
            "sn": {"C_pa": sn.C, "b": sn.b, "endurance_limit_pa": sn.limit},
            "stress_basis": "von Mises of the linear static stress at the reference load, scaled by the load multipliers; mean stress sign follows the multiplier; the minimum life uses the largest quadrature point stress, the life map uses smoothed nodal stress and is for display",
        }
    )
    summary["seconds"] = round(time.time() - started, 3)
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p2"})


registry.register("nonlinear_static", "Nonlinear static", run_nonlinear, needs=("material", "fixtures"), options=STATIC_OPTIONS, order=40)
registry.register("event_quasistatic", "Quasistatic event", run_quasistatic, needs=("material", "fixtures"), options=EVENT_OPTIONS, order=41)
registry.register("event_explicit", "Explicit dynamic event", run_explicit_event, needs=("material",), options=EXPLICIT_OPTIONS, order=42)
registry.register("fatigue", "Fatigue life", run_fatigue, needs=("material", "fixtures", "loads"), options=FATIGUE_OPTIONS, order=43)
