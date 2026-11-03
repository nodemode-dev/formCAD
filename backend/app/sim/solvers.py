import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from skfem import BilinearForm, FacetBasis, LinearForm, asm
from skfem.helpers import dot, grad

from app.sim import fem, registry
from app.sim.fem import SimError

MAX_MODES = 30
THERMAL_LOADS = ("heat_flux", "convection", "heat_load", "temperature_field")
THERMAL_FIXTURES = ("temperature",)
STRUCTURAL_FIXTURES = ("fixed", "roller", "symmetry", "displacement")
DEFAULT_T_REF = 293.15


def field(name, unit, location, components=1, modes=0, label=""):
    return {"name": name, "unit": unit, "location": location, "components": components, "modes": modes, "label": label or name}


def need_material(ctx, keys):
    missing = [k for k in keys if not ctx.material.get(k)]
    if missing:
        raise SimError("The material %s has no value for %s. Enter it with its source." % (ctx.material.get("name") or "", ", ".join(missing)))


def structural_fixtures(ctx):
    return [f for f in ctx.fixtures if f.get("type") in STRUCTURAL_FIXTURES]


def reactions(ctx, basis, K, f, u, fixed_groups):
    r = K @ u - f
    out = {}
    for fx in fixed_groups:
        fac = fem.facets_of(ctx.model, "fix:" + fx["id"])
        total = np.zeros(3)
        for i in range(3):
            ids = basis.get_dofs(fac, skip=[fem.COMPONENTS[j] for j in range(3) if j != i]).all()
            total[i] = r[ids].sum()
        out[fx["id"]] = [float(x) for x in total]
    return out


def total_force(basis, f):
    return np.array([f[basis.nodal_dofs[i]].sum() + f[basis.edge_dofs[i]].sum() for i in range(3)])


def counts(ctx, basis):
    return {"nodes": int(ctx.model.nodes_mm.shape[0]), "elements": int(ctx.model.tets.shape[0]), "dofs": int(basis.N)}


def run_static(ctx):
    need_material(ctx, ("E", "nu"))
    started = time.time()
    ctx.progress(0.05, "Assembling")
    basis = fem.vector_basis(ctx.model)
    size = fem.check_size(basis.N, ctx.limits, "static solve")
    K, lam, mu = fem.stiffness(ctx, basis)
    f = fem.force_vector(ctx, basis)
    if not np.any(f):
        raise SimError("The study has no load that acts on the part.")
    fixed, values = fem.fixed_dofs(ctx, basis)
    if len(fixed) < 6:
        raise SimError("The part is not held: add a fixture that removes the rigid body motion.")
    ctx.progress(0.3, "Solving")
    u, info = fem.solve_system(K, f, fixed, values, ctx)
    ctx.progress(0.8, "Recovering stress")
    st = fem.stress_fields(ctx, basis, u, lam, mu)
    nv = ctx.model.nodes_mm.shape[0]
    disp = fem.nodal_vector(basis, u, nv)
    mag = np.linalg.norm(disp, axis=1)
    react = reactions(ctx, basis, K, f, u, structural_fixtures(ctx))
    applied = total_force(basis, f)
    total_react = np.sum([r for r in react.values()], axis=0) if react else np.zeros(3)
    fields = {"u": u, "disp": disp, "disp_mag": mag, "vm": st["vm"], "s1": st["s1"], "vm_element": st["vm_element"]}
    meta_fields = [
        field("disp", "m", "node", 3, label="Displacement"),
        field("disp_mag", "m", "node", 1, label="Displacement magnitude"),
        field("vm", "Pa", "node", 1, label="Von Mises stress"),
        field("s1", "Pa", "node", 1, label="First principal stress"),
    ]
    summary = {
        "max_displacement_m": float(mag.max()),
        "max_von_mises_pa": st["vm_max_quad"],
        "max_principal_pa": st["s1_max_quad"],
        "min_principal_pa": st["s3_min_quad"],
        "reactions_n": react,
        "applied_n": [float(x) for x in applied],
        "equilibrium_error_n": float(np.linalg.norm(total_react + applied)),
        "solver": info,
        "size": size,
        "counts": counts(ctx, basis),
        "seconds": round(time.time() - started, 3),
    }
    yield_pa = ctx.material.get("sigma_y")
    if yield_pa:
        summary["safety_factor"] = float(yield_pa / max(st["vm_max_quad"], 1e-300))
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p2"})


def eigen_modes(Kff, Mff, count, sigma):
    vals, vecs = spla.eigsh(Kff, k=count, M=Mff, sigma=sigma, which="LM")
    order = np.argsort(vals)
    return vals[order], vecs[:, order]


def run_modal(ctx):
    need_material(ctx, ("E", "nu", "rho"))
    started = time.time()
    count = max(1, min(int(ctx.options.get("modes", 6)), MAX_MODES))
    ctx.progress(0.05, "Assembling")
    basis = fem.vector_basis(ctx.model)
    size = fem.check_size(basis.N, ctx.limits, "modal solve")
    K, _lam, _mu = fem.stiffness(ctx, basis)
    M = fem.mass_matrix(ctx, basis)
    fixed, _values = fem.fixed_dofs(ctx, basis)
    free = fem.free_of(basis.N, fixed)
    if len(free) <= count + 2:
        raise SimError("The mesh is too coarse for %d modes; use a smaller element size." % count)
    Kff = K[free][:, free].tocsc()
    Mff = M[free][:, free].tocsc()
    ctx.progress(0.3, "Finding modes")
    free_free = len(fixed) == 0
    vals, vecs = eigen_modes(Kff, Mff, count, -1.0 if free_free else 0.0)
    ctx.progress(0.8, "Collecting modes")
    nv = ctx.model.nodes_mm.shape[0]
    freqs = np.sqrt(np.maximum(vals, 0.0)) / (2.0 * np.pi)
    shapes = np.zeros((count, nv, 3))
    full = np.zeros((count, basis.N))
    for j in range(count):
        x = np.zeros(basis.N)
        x[free] = vecs[:, j]
        shape = fem.nodal_vector(basis, x, nv)
        peak = np.abs(shape).max()
        scale = 1.0 / peak if peak > 0 else 1.0
        shapes[j] = shape * scale
        full[j] = x * scale
    rigid = int(np.sum(freqs < 1e-3 * max(freqs.max(), 1.0))) if free_free else 0
    fields = {"mode_shape": shapes, "frequency": freqs, "u_modes": full}
    meta_fields = [field("mode_shape", "1", "node", 3, count, "Mode shape"), field("frequency", "Hz", "scalar", 1, count, "Frequency")]
    summary = {
        "frequencies_hz": [float(x) for x in freqs],
        "rigid_modes": rigid,
        "mass_kg": float(M.sum() / 3.0),
        "solver": {"method": "shift-invert eigsh", "shift": -1.0 if free_free else 0.0},
        "size": size,
        "counts": counts(ctx, basis),
        "seconds": round(time.time() - started, 3),
    }
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p2", "modes": [{"index": j, "frequency_hz": float(freqs[j])} for j in range(count)]})


def thermal_solve(ctx, basis, started=None):
    need_material(ctx, ("k",))
    from skfem import condense

    k = float(ctx.material["k"])
    K = asm(BilinearForm(lambda u, v, w: k * dot(grad(u), grad(v))), basis)
    f = np.zeros(basis.N)
    volume = None
    fixed_ids = []
    fixed_vals = []
    for ld in ctx.loads:
        kind = ld.get("type")
        if kind not in ("heat_flux", "convection", "heat_load"):
            continue
        if kind == "heat_load" and not ld.get("select"):
            volume = volume or float(asm(LinearForm(lambda v, w: v.value), basis).sum())
            f += asm(LinearForm(lambda v, w, q=float(ld.get("value", 0.0)) / volume: q * v.value), basis)
            continue
        fac = fem.facets_of(ctx.model, "load:" + ld["id"])
        fb = FacetBasis(ctx.model.mesh, basis.elem, facets=fac)
        if kind == "heat_flux":
            q = float(ld.get("value", 0.0))
            f += asm(LinearForm(lambda v, w, q=q: q * v.value), fb)
        elif kind == "convection":
            h = float(ld.get("h", 0.0))
            tinf = float(ld.get("t_inf", 293.15))
            if not h > 0:
                raise SimError("A convection load needs a positive film coefficient h.")
            K = K + asm(BilinearForm(lambda u, v, w, h=h: h * u.value * v.value), fb)
            f += asm(LinearForm(lambda v, w, h=h, t=tinf: h * t * v.value), fb)
        elif kind == "heat_load":
            q = float(ld.get("value", 0.0))
            area = fem.facet_area(ctx.model, "load:" + ld["id"])
            f += asm(LinearForm(lambda v, w, q=q / area: q * v.value), fb)
    ref_T = None
    for fx in ctx.fixtures:
        if fx.get("type") != "temperature":
            continue
        fac = fem.facets_of(ctx.model, "fix:" + fx["id"])
        ids = basis.get_dofs(fac).all()
        fixed_ids.append(ids)
        fixed_vals.append(np.full(len(ids), float(fx.get("value", 293.15))))
    has_conv = any(ld.get("type") == "convection" for ld in ctx.loads)
    if not fixed_ids and not has_conv:
        raise SimError("A thermal study needs a temperature fixture or a convection load, otherwise the temperature is not determined.")
    T = np.zeros(basis.N)
    D = np.zeros(0, dtype=np.int64)
    if fixed_ids:
        D = np.concatenate(fixed_ids)
        T[D] = np.concatenate(fixed_vals)
    free = fem.free_of(basis.N, D)
    ctx.check()
    Kc = K.tocsr()
    rhs = f[free] - Kc[free][:, D] @ T[D] if len(D) else f[free]
    T[free] = spla.splu(Kc[free][:, free].tocsc()).solve(rhs)
    residual = Kc @ T - f
    flows = {}
    for fx in ctx.fixtures:
        if fx.get("type") == "temperature":
            ids = basis.get_dofs(fem.facets_of(ctx.model, "fix:" + fx["id"])).all()
            flows[fx["id"]] = float(residual[ids].sum())
    return T, K, f, flows


def run_thermal(ctx):
    started = time.time()
    ctx.progress(0.05, "Assembling")
    basis = fem.scalar_basis(ctx.model)
    size = fem.check_size(basis.N, ctx.limits, "thermal solve")
    ctx.progress(0.2, "Solving")
    T, K, f, flows = thermal_solve(ctx, basis)
    k = float(ctx.material["k"])
    nv = ctx.model.nodes_mm.shape[0]
    gT = basis.interpolate(T).grad
    flux = k * np.sqrt(gT[0] ** 2 + gT[1] ** 2 + gT[2] ** 2)
    flux_nodal = fem.element_to_nodes(ctx.model.mesh.t[:4], flux.mean(axis=1), nv)
    Tn = T[basis.nodal_dofs[0, :nv]]
    fields = {"T": T, "temperature": Tn, "flux_mag": flux_nodal}
    meta_fields = [field("temperature", "K", "node", 1, label="Temperature"), field("flux_mag", "W/m2", "node", 1, label="Heat flux magnitude")]
    summary = {
        "min_temperature_k": float(T.min()),
        "max_temperature_k": float(T.max()),
        "max_flux_w_m2": float(flux.max()),
        "heat_flow_w": flows,
        "size": size,
        "counts": counts(ctx, basis),
        "seconds": round(time.time() - started, 3),
    }
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "scalar_p2"})


def run_thermal_stress(ctx):
    need_material(ctx, ("E", "nu", "alpha"))
    started = time.time()
    ctx.progress(0.05, "Thermal solve")
    sb = fem.scalar_basis(ctx.model)
    t_ref = float(ctx.options.get("t_ref", DEFAULT_T_REF))
    uniform = [ld for ld in ctx.loads if ld.get("type") == "temperature_field"]
    thermal_ready = any(ld.get("type") in ("heat_flux", "convection", "heat_load") for ld in ctx.loads) or any(f.get("type") == "temperature" for f in ctx.fixtures)
    if thermal_ready:
        T, _K, _f, flows = thermal_solve(ctx, sb)
    elif uniform:
        T = np.full(sb.N, float(uniform[0].get("value", t_ref)))
        flows = {}
    else:
        raise SimError("A thermal stress study needs thermal loads or fixtures, or a uniform temperature load.")
    ctx.progress(0.35, "Structural solve")
    vb = fem.vector_basis(ctx.model)
    size = fem.check_size(vb.N, ctx.limits, "thermal stress solve")
    K, lam, mu = fem.stiffness(ctx, vb)
    alpha = float(ctx.material["alpha"])
    T_interp = sb.interpolate(T)
    dT = np.asarray(T_interp.value) - t_ref
    coef = (3.0 * lam + 2.0 * mu) * alpha

    @LinearForm
    def thermal_load(v, w):
        from skfem.helpers import div

        return coef * w["dT"] * div(v)

    f = asm(thermal_load, vb, dT=dT)
    f += fem.force_vector(ctx, vb)
    fixed, values = fem.fixed_dofs(ctx, vb)
    if len(fixed) < 6:
        raise SimError("The part is not held: add a structural fixture, otherwise the free thermal expansion is not determined.")
    u, info = fem.solve_system(K, f, fixed, values, ctx)
    st = fem.stress_fields(ctx, vb, u, lam, mu, dT, alpha)
    nv = ctx.model.nodes_mm.shape[0]
    disp = fem.nodal_vector(vb, u, nv)
    mag = np.linalg.norm(disp, axis=1)
    Tn = T[sb.nodal_dofs[0, :nv]]
    fields = {"u": u, "T": T, "disp": disp, "disp_mag": mag, "vm": st["vm"], "s1": st["s1"], "temperature": Tn, "vm_element": st["vm_element"]}
    meta_fields = [
        field("disp", "m", "node", 3, label="Displacement"),
        field("disp_mag", "m", "node", 1, label="Displacement magnitude"),
        field("vm", "Pa", "node", 1, label="Von Mises stress"),
        field("s1", "Pa", "node", 1, label="First principal stress"),
        field("temperature", "K", "node", 1, label="Temperature"),
    ]
    summary = {
        "max_displacement_m": float(mag.max()),
        "max_von_mises_pa": st["vm_max_quad"],
        "max_principal_pa": st["s1_max_quad"],
        "min_principal_pa": st["s3_min_quad"],
        "min_temperature_k": float(T.min()),
        "max_temperature_k": float(T.max()),
        "t_ref_k": t_ref,
        "heat_flow_w": flows,
        "solver": info,
        "size": size,
        "counts": counts(ctx, vb),
        "seconds": round(time.time() - started, 3),
    }
    yield_pa = ctx.material.get("sigma_y")
    if yield_pa:
        summary["safety_factor"] = float(yield_pa / max(st["vm_max_quad"], 1e-300))
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p2"})


def geometric_stiffness(vb, u0, lam, mu):
    sig = fem.strain_stress(vb, u0, lam, mu)
    kw = {"s%d%d" % (i, j): sig[i, j] for i in range(3) for j in range(3)}

    @BilinearForm
    def form(u, v, w):
        out = 0.0
        for k in range(3):
            for i in range(3):
                for j in range(3):
                    out = out + w["s%d%d" % (i, j)] * u.grad[k][i] * v.grad[k][j]
        return out

    return asm(form, vb, **kw)


def run_buckling(ctx):
    need_material(ctx, ("E", "nu"))
    started = time.time()
    count = max(1, min(int(ctx.options.get("modes", 3)), 10))
    ctx.progress(0.05, "Assembling")
    vb = fem.vector_basis(ctx.model)
    size = fem.check_size(vb.N, ctx.limits, "buckling solve")
    K, lam, mu = fem.stiffness(ctx, vb)
    f = fem.force_vector(ctx, vb, ("force", "pressure", "traction", "gravity", "reference_load"))
    if not np.any(f):
        raise SimError("A buckling study needs a reference load.")
    fixed, values = fem.fixed_dofs(ctx, vb)
    if len(fixed) < 6:
        raise SimError("The part is not held: add a fixture that removes the rigid body motion.")
    ctx.progress(0.25, "Pre-stress solve")
    u0, info = fem.solve_system(K, f, fixed, {}, ctx)
    ctx.progress(0.5, "Geometric stiffness")
    Kg = geometric_stiffness(vb, u0, lam, mu)
    free = fem.free_of(vb.N, fixed)
    Kff = K[free][:, free].tocsc()
    Gff = (-Kg[free][:, free]).tocsc()
    ctx.progress(0.65, "Finding buckling modes")
    mu_vals, vecs = spla.eigsh(Gff, k=count, M=Kff, which="LA")
    order = np.argsort(-mu_vals)
    mu_vals, vecs = mu_vals[order], vecs[:, order]
    good = mu_vals > 1e-12
    if not good.any():
        raise SimError("No positive load factor was found: the reference load does not compress the part.")
    factors = 1.0 / mu_vals[good]
    vecs = vecs[:, good]
    nv = ctx.model.nodes_mm.shape[0]
    n = len(factors)
    shapes = np.zeros((n, nv, 3))
    full = np.zeros((n, vb.N))
    for j in range(n):
        x = np.zeros(vb.N)
        x[free] = vecs[:, j]
        sh = fem.nodal_vector(vb, x, nv)
        peak = np.abs(sh).max()
        scale = 1.0 / peak if peak > 0 else 1.0
        shapes[j] = sh * scale
        full[j] = x * scale
    reference = float(np.linalg.norm(total_force(vb, f)))
    fields = {"mode_shape": shapes, "load_factor": factors, "u_modes": full, "u": u0}
    meta_fields = [field("mode_shape", "1", "node", 3, n, "Buckling mode shape"), field("load_factor", "1", "scalar", 1, n, "Load factor")]
    summary = {
        "load_factors": [float(x) for x in factors],
        "reference_load_n": reference,
        "critical_load_n": float(factors[0] * reference),
        "solver": info,
        "size": size,
        "counts": counts(ctx, vb),
        "seconds": round(time.time() - started, 3),
    }
    return registry.Outcome(fields, summary, {"fields": meta_fields, "basis": "vector_p2", "modes": [{"index": j, "load_factor": float(factors[j])} for j in range(n)]})


registry.register("static", "Linear static", run_static, needs=("material", "loads", "fixtures"), options={}, order=10)
registry.register("modal", "Modal frequencies", run_modal, needs=("material",), options={"modes": {"default": 6, "min": 1, "max": MAX_MODES}}, order=20)
registry.register("thermal", "Steady thermal", run_thermal, needs=("material",), options={}, order=30)
registry.register("thermal_stress", "Thermal stress", run_thermal_stress, needs=("material", "fixtures"), options={"t_ref": {"default": DEFAULT_T_REF, "unit": "K"}}, order=40)
registry.register("buckling", "Linear buckling", run_buckling, needs=("material", "loads", "fixtures"), options={"modes": {"default": 3, "min": 1, "max": 10}}, order=50)
