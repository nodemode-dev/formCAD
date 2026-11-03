import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from skfem import Basis, BilinearForm, ElementTetP2, ElementVector, FacetBasis, LinearForm, asm, condense
from skfem.helpers import div, dot, sym_grad
from skfem.models.elasticity import lame_parameters, linear_elasticity

COMPONENTS = ("u^1", "u^2", "u^3")
DIRECT_DOFS = 60000


class SimError(ValueError):
    pass


def unit(v, name="direction"):
    a = np.array([float(x) for x in v], dtype=float)
    if a.shape != (3,) or not np.isfinite(a).all() or np.linalg.norm(a) == 0:
        raise SimError("The %s needs three numbers that are not all zero." % name)
    return a / np.linalg.norm(a)


def vector_basis(model):
    return Basis(model.mesh, ElementVector(ElementTetP2()))


def scalar_basis(model):
    return Basis(model.mesh, ElementTetP2())


def facets_of(model, name):
    fac = model.mesh.boundaries.get(name)
    if fac is None or len(fac) == 0:
        raise SimError("A load or fixture selects no face of the mesh (%s)." % name)
    return fac


def facet_area(model, name):
    sb = scalar_basis(model)
    fb = FacetBasis(model.mesh, sb.elem, facets=facets_of(model, name))
    return float(asm(LinearForm(lambda v, w: v.value), fb).sum())


def traction_form(vec):
    t = [float(x) for x in vec]

    @LinearForm
    def form(v, w):
        return t[0] * v.value[0] + t[1] * v.value[1] + t[2] * v.value[2]

    return form


def pressure_form(p):
    @LinearForm
    def form(v, w):
        return -p * dot(w.n, v)

    return form


def body_form(vec):
    t = [float(x) for x in vec]

    @LinearForm
    def form(v, w):
        return t[0] * v.value[0] + t[1] * v.value[1] + t[2] * v.value[2]

    return form


def force_vector(ctx, basis, kinds=("force", "pressure", "traction", "gravity", "reference_load")):
    f = np.zeros(basis.N)
    rho = ctx.material["rho"]
    for ld in ctx.loads:
        kind = ld.get("type")
        if kind not in kinds:
            continue
        name = "load:" + ld["id"]
        if kind in ("force", "reference_load"):
            area = facet_area(ctx.model, name)
            d = unit(ld.get("direction") or [0, 0, -1])
            total = float(ld.get("value", 0.0))
            fb = FacetBasis(ctx.model.mesh, basis.elem, facets=facets_of(ctx.model, name))
            f += asm(traction_form(d * total / area), fb)
        elif kind == "traction":
            fb = FacetBasis(ctx.model.mesh, basis.elem, facets=facets_of(ctx.model, name))
            f += asm(traction_form([float(x) for x in ld.get("vector") or ld.get("direction")]), fb)
        elif kind == "pressure":
            fb = FacetBasis(ctx.model.mesh, basis.elem, facets=facets_of(ctx.model, name))
            f += asm(pressure_form(float(ld.get("value", 0.0))), fb)
        elif kind == "gravity":
            d = unit(ld.get("direction") or [0, 0, -1])
            f += asm(body_form(d * rho * float(ld.get("value", 9.81))), basis)
    return f


def fixed_dofs(ctx, basis):
    dofs = []
    values = {}
    for fx in ctx.fixtures:
        kind = fx.get("type")
        if kind not in ("fixed", "roller", "symmetry", "displacement"):
            continue
        name = "fix:" + fx["id"]
        fac = facets_of(ctx.model, name)
        if kind == "fixed":
            keep = [0, 1, 2]
        elif kind == "symmetry":
            axis = int(fx.get("axis", 0))
            keep = [axis]
        elif kind == "roller":
            free = {int(a) for a in fx.get("axes") or []}
            keep = [i for i in range(3) if i not in free]
        else:
            mask = fx.get("components") or [1, 1, 1]
            keep = [i for i in range(3) if mask[i]]
        skip = [COMPONENTS[i] for i in range(3) if i not in keep]
        ids = basis.get_dofs(fac, skip=skip or None).all()
        dofs.append(ids)
        if kind == "displacement":
            val = fx.get("value") or [0, 0, 0]
            for i in keep:
                comp = basis.get_dofs(fac, skip=[COMPONENTS[j] for j in range(3) if j != i]).all()
                for d in comp:
                    values[int(d)] = float(val[i])
    if not dofs:
        return np.zeros(0, dtype=np.int64), {}
    return np.unique(np.concatenate(dofs)), values


def stiffness(ctx, basis):
    lam, mu = lame_parameters(ctx.material["E"], ctx.material["nu"])
    return asm(linear_elasticity(lam, mu), basis), lam, mu


def mass_matrix(ctx, basis):
    rho = ctx.material["rho"]

    @BilinearForm
    def form(u, v, w):
        return rho * (u.value[0] * v.value[0] + u.value[1] * v.value[1] + u.value[2] * v.value[2])

    return asm(form, basis)


def free_of(n, fixed):
    mask = np.ones(n, dtype=bool)
    mask[fixed] = False
    return np.nonzero(mask)[0]


def memory_mb(dofs):
    return 0.0228 * dofs * (max(dofs, 57000.0) / 57000.0) ** (1.0 / 3.0)


def available_mb():
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    try:
        import os

        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1048576.0
    except (ValueError, OSError, AttributeError):
        return None


def check_size(dofs, limits, what="solve"):
    if dofs > limits["dofs"]:
        raise SimError("The study has %d unknowns, over the limit of %d for this caller. Use a larger element size." % (dofs, limits["dofs"]))
    need = memory_mb(dofs)
    have = available_mb()
    if have is not None and need > 0.7 * have:
        raise SimError("The %s needs about %.0f MB for a direct solve and only about %.0f MB is free. Use a larger element size." % (what, need, have))
    if have is None and dofs > DIRECT_DOFS:
        raise SimError("The %s has %d unknowns, over the %d that are solved when the free memory cannot be read. Use a larger element size." % (what, dofs, DIRECT_DOFS))
    return {"dofs": int(dofs), "estimated_mb": round(need, 1), "free_mb": None if have is None else round(have, 1), "method": "direct"}


def solve_system(K, f, fixed, values, ctx):
    n = K.shape[0]
    x = np.zeros(n)
    for d, v in values.items():
        x[d] = v
    free = free_of(n, fixed)
    if len(free) == 0:
        raise SimError("Every unknown is fixed.")
    Kff = K[free][:, free].tocsc()
    rhs = f[free] - K[free][:, fixed] @ x[fixed] if len(fixed) else f[free]
    info = {"dofs": int(len(free))}
    ctx.check()
    sol = spla.splu(Kff).solve(rhs)
    info["method"] = "direct"
    info["residual"] = float(np.linalg.norm(Kff @ sol - rhs) / max(np.linalg.norm(rhs), 1e-300))
    x[free] = sol
    return x, info


def strain_stress(basis, u, lam, mu, dT=None, alpha=0.0):
    uf = basis.interpolate(u)
    eps = sym_grad(uf)
    eps = np.asarray(eps)
    tr = eps[0, 0] + eps[1, 1] + eps[2, 2]
    sig = 2.0 * mu * eps
    vol = lam * tr
    if dT is not None:
        vol = vol - (3.0 * lam + 2.0 * mu) * alpha * dT
    for i in range(3):
        sig[i, i] = sig[i, i] + vol
    return sig


def von_mises(sig):
    sx, sy, sz = sig[0, 0], sig[1, 1], sig[2, 2]
    return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3.0 * (sig[0, 1] ** 2 + sig[1, 2] ** 2 + sig[0, 2] ** 2))


def principal_max(sig):
    shape = sig.shape[2:]
    flat = np.moveaxis(sig.reshape(3, 3, -1), 2, 0)
    vals = np.linalg.eigvalsh(flat)
    return vals[:, -1].reshape(shape), vals[:, 0].reshape(shape)


def element_to_nodes(mesh_tets, element_values, n_nodes):
    acc = np.zeros(n_nodes)
    cnt = np.zeros(n_nodes)
    for c in range(mesh_tets.shape[0]):
        np.add.at(acc, mesh_tets[c], element_values)
        np.add.at(cnt, mesh_tets[c], 1.0)
    return acc / np.maximum(cnt, 1.0)


def nodal_vector(basis, u, count):
    return np.stack([u[basis.nodal_dofs[i, :count]] for i in range(3)], axis=1)


def stress_fields(ctx, basis, u, lam, mu, dT=None, alpha=0.0):
    sig = strain_stress(basis, u, lam, mu, dT, alpha)
    vm = von_mises(sig)
    s1, s3 = principal_max(sig)
    nv = ctx.model.nodes_mm.shape[0]
    tets = ctx.model.mesh.t[:4]
    avg = vm.mean(axis=1)
    return {
        "vm": element_to_nodes(tets, avg, nv),
        "s1": element_to_nodes(tets, s1.mean(axis=1), nv),
        "vm_element": avg,
        "vm_max_quad": float(vm.max()),
        "s1_max_quad": float(s1.max()),
        "s3_min_quad": float(s3.min()),
    }
