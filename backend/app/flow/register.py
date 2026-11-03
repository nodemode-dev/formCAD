import math
import time

import numpy as np
import scipy.sparse.linalg as spla
from skfem import Basis, BilinearForm, ElementTetP0, FacetBasis, LinearForm, asm
from skfem.helpers import dot, grad

from app.flow import fill, midplane, pack, stokes, su2
from app.flow.limits import FlowError
from app.sim import fem, registry
from app.sim.fem import SimError
from app.sim.solvers import counts, field

EXIT_PERCENT = 5.0
LOCKED_DOFS = 30000


def flow_error(fn):
    def wrapped(ctx):
        try:
            return fn(ctx)
        except FlowError as err:
            raise SimError(str(err))

    return wrapped


def one_load(ctx, kind: str, label: str) -> dict:
    rows = [ld for ld in ctx.loads if ld.get("type") == kind]
    if len(rows) != 1:
        raise SimError("A flow study needs exactly one %s; this one has %d." % (label, len(rows)))
    return rows[0]


def fluid_of(ctx) -> tuple:
    fl = ctx.options.get("fluid")
    if not isinstance(fl, dict):
        raise SimError("Enter the fluid in the study options: its density and dynamic viscosity (SI). No fluid table ships with FormCAD.")
    out = []
    for key, label in (("density", "density"), ("viscosity", "dynamic viscosity")):
        try:
            v = float(fl.get(key))
        except (TypeError, ValueError):
            raise SimError("The fluid needs a %s." % label)
        if not (v > 0 and math.isfinite(v)):
            raise SimError("The fluid %s must be greater than zero." % label)
        out.append(v)
    return out[0], out[1]


def pressure_fields(pressure, velocity, label_extra=""):
    speed = np.linalg.norm(velocity, axis=1)
    fields = {"pressure": np.asarray(pressure), "velocity": np.asarray(velocity), "speed": speed}
    meta = [field("pressure", "Pa", "node", 1, label="Pressure"), field("speed", "m/s", "node", 1, label="Speed"), field("velocity", "m/s", "node", 3, label="Velocity")]
    return fields, meta


def reference_block(summary: dict, drop: float, mu: float, speed: float, length: float, area: float, perimeter: float, kind: str) -> None:
    if perimeter > 0 and abs(4.0 * math.pi * area / perimeter ** 2 - 1.0) < 0.02 and length > 0:
        diameter = math.sqrt(4.0 * area / math.pi)
        hp = 32.0 * mu * length * speed / diameter ** 2
        err = 100.0 * (drop - hp) / hp
        summary["reference"] = {"kind": "Hagen-Poiseuille", "pressure_drop": hp, "diameter": diameter, "error_percent": err, "within_exit_tolerance": abs(err) <= EXIT_PERCENT, "geometry": kind}


@flow_error
def run_flow(ctx):
    started = time.time()
    rho, mu = fluid_of(ctx)
    inlet = one_load(ctx, "flow_inlet", "flow inlet")
    outlet = one_load(ctx, "flow_outlet", "flow outlet")
    mesh = ctx.model.mesh
    which = str(ctx.options.get("solver", "own"))
    if which not in ("own", "su2"):
        raise SimError("The flow solver is own or su2.")
    names = ("load:" + inlet["id"], "load:" + outlet["id"])
    ctx.progress(0.05, "Preparing")
    if which == "own":
        params = {"viscosity": mu, "density": rho, "inlet": names[0], "outlet": names[1], "speed": inlet.get("speed"), "flow": inlet.get("flow"), "curved": bool(ctx.model.curved), "max_unknowns": ctx.limits["dofs"]}
        out = stokes.solve_flow(mesh, params, check=ctx.check)
        summary = out["summary"]
        summary["solver"] = "own"
        summary["counts"] = {"nodes": int(ctx.model.nodes_mm.shape[0]), "elements": int(ctx.model.tets.shape[0]), "dofs": summary["unknowns"]}
        fields, meta = pressure_fields(out["fields"]["pressure"], out["fields"]["velocity"])
        return registry.Outcome(fields, summary, {"fields": meta, "basis": "scalar_p1"})
    inp = stokes.su2_inputs(mesh, names[0], names[1], ctx.check)
    area_flat = float(np.linalg.norm(np.cross(inp["points"][inp["tris_in"][:, 1]] - inp["points"][inp["tris_in"][:, 0]], inp["points"][inp["tris_in"][:, 2]] - inp["points"][inp["tris_in"][:, 0]]), axis=1).sum() / 2.0)
    speed = float(inlet["speed"]) if inlet.get("speed") else float(inlet["flow"]) / area_flat
    values = inp["profile"][1] * speed
    ctx.progress(0.1, "Running SU2")
    res = su2.solve(inp["points"], inp["tets"], inp["markers"], "inlet", "outlet", ["wall"], rho, mu, speed, inp["direction"], profile=(inp["profile"][0], values, inp["direction"]), check=ctx.check, runner=None, extra=ctx.options.get("su2_options"))
    f = res["fields"]
    pressure = f["Pressure"]
    vel = np.stack([f["Velocity_x"], f["Velocity_y"], f["Velocity_z"]], axis=1)
    pts = inp["points"]

    def face_mean(tris):
        a = np.linalg.norm(np.cross(pts[tris[:, 1]] - pts[tris[:, 0]], pts[tris[:, 2]] - pts[tris[:, 0]]), axis=1) / 2.0
        return float((pressure[tris].mean(axis=1) * a).sum() / a.sum())

    p_in, p_out = face_mean(inp["tris_in"]), face_mean(inp["tris_out"])
    drop = p_in - p_out
    summary = {
        "solver": "su2",
        "model": "SU2 incompressible laminar Navier-Stokes, straight-sided linear tetrahedra, prescribed developed inlet profile",
        "label": su2.LABEL,
        "pressure_drop": drop,
        "inlet_pressure": p_in,
        "outlet_pressure": p_out,
        "mean_speed": speed,
        "flow_rate": speed * area_flat,
        "inlet_area": area_flat,
        "length": inp["length"],
        "reynolds": rho * speed * (4.0 * area_flat / inp["perimeter"]) / mu if inp["perimeter"] > 0 else None,
        "iterations": res["iterations"],
        "final_residual": res["residual"],
        "tets": int(inp["tets"].shape[0]),
        "seconds": round(time.time() - started, 3),
        "warnings": ["SU2 sees straight-sided cells: on a curved wall the result carries the faceted-wall bias and needs a fine mesh. Compare with the own solver before trusting it."],
        "counts": {"nodes": int(len(pts)), "elements": int(inp["tets"].shape[0])},
    }
    reference_block(summary, drop, mu, speed, inp["length"], area_flat, inp["perimeter"], "straight-sided")
    fields, meta = pressure_fields(pressure, vel)
    return registry.Outcome(fields, summary, {"fields": meta, "basis": "scalar_p1"})


def element_volumes(basis, mesh):
    b0 = Basis(mesh, ElementTetP0(), quadrature=basis.quadrature)
    return asm(LinearForm(lambda v, w: v.value), b0), b0


@flow_error
def run_cooling(ctx):
    from skfem import condense  # noqa: F401

    started = time.time()
    k0 = ctx.material.get("k")
    if not k0:
        raise SimError("The material has no thermal conductivity k. Enter it with its source.")
    mesh = ctx.model.mesh
    opts = ctx.options
    basis = fem.scalar_basis(ctx.model)
    size = fem.check_size(basis.N, ctx.limits, "cooling solve")
    ctx.progress(0.1, "Assembling")
    vols, b0 = element_volumes(basis, mesh)
    centres = ctx.model.nodes_mm[mesh.t[:4]].mean(axis=0)
    sources = opts.get("sources") or []
    if not isinstance(sources, list) or len(sources) > 64:
        raise SimError("Heat sources are a list of at most 64 regions.")
    kel = np.full(len(vols), float(k0))
    qel = np.zeros(len(vols))
    member = np.full(len(vols), -1, dtype=int)
    rows = []
    for i, src in enumerate(sources):
        try:
            box = np.asarray(src["box"], dtype=float)
            power = float(src.get("power_w", 0.0))
            ok = box.shape == (2, 3) and np.isfinite(box).all() and math.isfinite(power) and power >= 0
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            raise SimError("Heat source %d needs a box of two corners in mm and a power in watts of at least zero." % (i + 1))
        lo, hi = np.minimum(box[0], box[1]), np.maximum(box[0], box[1])
        inside = ((centres >= lo) & (centres <= hi)).all(axis=1) & (member < 0)
        if not inside.any():
            raise SimError("Heat source %d (%s) contains no element." % (i + 1, src.get("name", "")))
        member[inside] = i
        vol = float(vols[inside].sum())
        qel[inside] = power / vol
        if src.get("k") not in (None, ""):
            kel[inside] = float(src["k"])
        rows.append({"name": str(src.get("name", "source %d" % (i + 1))), "power_w": power, "volume_m3": vol, "elements": int(inside.sum())})
    body_power = 0.0
    for ld in ctx.loads:
        if ld.get("type") == "heat_load" and not ld.get("select"):
            body_power += float(ld.get("value", 0.0))
    kf = b0.interpolate(kel)
    qf = b0.interpolate(qel)
    K = asm(BilinearForm(lambda u, v, w: w["k"] * dot(grad(u), grad(v))), basis, k=kf)
    f = asm(LinearForm(lambda v, w: w["q"] * v.value), basis, q=qf)
    if body_power:
        total_vol = float(vols.sum())
        f = f + asm(LinearForm(lambda v, w, q=body_power / total_vol: q * v.value), basis)
    films = []
    flux_in = 0.0
    for ld in ctx.loads:
        if ld.get("type") == "convection":
            films.append((fem.facets_of(ctx.model, "load:" + ld["id"]), float(ld["h"]), float(ld.get("t_inf", 293.15))))
        elif ld.get("type") == "heat_flux":
            fb = FacetBasis(mesh, basis.elem, facets=fem.facets_of(ctx.model, "load:" + ld["id"]))
            part = asm(LinearForm(lambda v, w, q=float(ld.get("value", 0.0)): q * v.value), fb)
            flux_in += float(part.sum())
            f = f + part
    if not films and opts.get("h") not in (None, ""):
        h = float(opts["h"])
        if not (h > 0 and math.isfinite(h)):
            raise SimError("The film coefficient h must be greater than zero.")
        every = mesh.boundaries.get("_all") if mesh.boundaries else None
        every = np.asarray(every if every is not None else mesh.boundary_facets(), dtype=np.int64)
        for fx in ctx.fixtures:
            if fx.get("type") == "temperature":
                every = np.setdiff1d(every, fem.facets_of(ctx.model, "fix:" + fx["id"]))
        films.append((every, h, float(opts.get("t_amb", 293.15))))
    for fac, h, tinf in films:
        fb = FacetBasis(mesh, basis.elem, facets=fac)
        K = K + asm(BilinearForm(lambda u, v, w, h=h: h * u.value * v.value), fb)
        f = f + asm(LinearForm(lambda v, w, h=h, t=tinf: h * t * v.value), fb)
    ids, vals = [], []
    for fx in ctx.fixtures:
        if fx.get("type") == "temperature":
            d = basis.get_dofs(fem.facets_of(ctx.model, "fix:" + fx["id"])).all()
            ids.append(d)
            vals.append(np.full(len(d), float(fx.get("value", 293.15))))
    if not films and not ids:
        raise SimError("Give the cooling study a film coefficient (a convection load or the option h) or a temperature fixture.")
    total_power = float(sum(r["power_w"] for r in rows)) + body_power
    if not np.any(f) and not ids:
        raise SimError("The cooling study has no heat input.")
    T = np.zeros(basis.N)
    D = np.zeros(0, dtype=np.int64)
    if ids:
        D = np.concatenate(ids)
        T[D] = np.concatenate(vals)
    free = fem.free_of(basis.N, D)
    ctx.progress(0.4, "Solving")
    Kc = K.tocsr()
    rhs = f[free] - Kc[free][:, D] @ T[D] if len(D) else f[free]
    T[free] = spla.splu(Kc[free][:, free].tocsc()).solve(rhs)
    ctx.progress(0.8, "Post processing")
    nv = ctx.model.nodes_mm.shape[0]
    Tn = T[basis.nodal_dofs[0, :nv]]
    gT = basis.interpolate(T).grad
    flux = np.sqrt(gT[0] ** 2 + gT[1] ** 2 + gT[2] ** 2) * kel[:, None]
    flux_nodal = fem.element_to_nodes(mesh.t[:4], flux.mean(axis=1), nv)
    convected = 0.0
    for fac, h, tinf in films:
        fb = FacetBasis(mesh, basis.elem, facets=fac)
        convected += float(asm(LinearForm(lambda v, w, h=h, t=tinf: h * (w["T"] - t) * v.value), fb, T=fb.interpolate(T)).sum())
    residual = Kc @ T - f
    fixed_flow = float(residual[D].sum()) if len(D) else 0.0
    corner = mesh.t[:4]
    for i, r in enumerate(rows):
        sel = np.unique(corner[:, member == i])
        r["mean_temperature_k"] = float(Tn[sel].mean())
        r["max_temperature_k"] = float(Tn[sel].max())
    hot = int(np.argmax(Tn))
    amb = films[0][2] if films else None
    summary = {
        "model": "Steady conduction in the solid with a film coefficient on the exposed faces (first version, no airflow model)",
        "label": "Conduction with a convective boundary. The film coefficient is yours; it is not computed from airflow.",
        "max_temperature_k": float(Tn.max()),
        "max_temperature_at_mm": [float(x) for x in ctx.model.nodes_mm[hot]],
        "min_temperature_k": float(Tn.min()),
        "total_power_w": total_power,
        "convected_w": convected,
        "fixed_temperature_flow_w": fixed_flow,
        "heat_input_w": total_power + flux_in,
        "energy_balance_error_w": convected - fixed_flow - total_power - flux_in,
        "sources": rows,
        "size": size,
        "counts": counts(ctx, basis),
        "seconds": round(time.time() - started, 3),
        "warnings": [],
    }
    if amb is not None and total_power > 0:
        summary["ambient_k"] = amb
        summary["thermal_resistance_k_per_w"] = (float(Tn.max()) - amb) / total_power
    fields = {"T": T, "temperature": Tn, "flux_mag": flux_nodal}
    meta = [field("temperature", "K", "node", 1, label="Temperature"), field("flux_mag", "W/m2", "node", 1, label="Heat flux magnitude")]
    return registry.Outcome(fields, summary, {"fields": meta, "basis": "scalar_p2"})


@flow_error
def run_fill(ctx):
    started = time.time()
    gate = [ld for ld in ctx.loads if ld.get("type") == "injection_gate"]
    if not gate:
        raise SimError("A fill study needs an injection gate: pick the face where the melt enters.")
    opts = ctx.options
    poly = opts.get("polymer")
    if not isinstance(poly, dict):
        raise SimError("Enter the polymer in the study options: a Newtonian viscosity eta (Pa s) or a power law K (Pa s^n) and n. No polymer table ships with FormCAD.")
    mesh = ctx.model.mesh
    facets = np.unique(np.concatenate([fem.facets_of(ctx.model, "load:" + g["id"]) for g in gate]))
    ctx.progress(0.05, "Building the midplane")
    locked = bool(ctx.limits.get("dofs", 1 << 30) <= LOCKED_DOFS)
    plane = midplane.extract(mesh, facets, opts.get("pull"), runner=locked, check=ctx.check)
    ctx.progress(0.3, "Filling")
    law = {"eta": poly.get("eta")} if poly.get("eta") not in (None, "") else {"k": poly.get("k"), "n": poly.get("n")}
    result = fill.run(plane["points"], plane["tris"], plane["thickness"], plane["gates"], volume_flow=opts.get("flow"), fill_time=opts.get("fill_time"), pressure_limit=opts.get("pressure_limit"), check=ctx.check, pull=plane["pull"], runner=locked, **law)
    nodes_m = stokes.corner_points(mesh)
    arrival = midplane.spread_to_nodes(nodes_m, plane, np.nan_to_num(result["arrival"], nan=0.0), plane["pull"])
    pressure = midplane.spread_to_nodes(nodes_m, plane, result["pressure"], plane["pull"])
    thick = midplane.spread_to_nodes(nodes_m, plane, plane["thickness"], plane["pull"])
    thin = plane["thickness"]
    summary = {
        "model": "Hele-Shaw midplane fill, isothermal, constant flow rate",
        "label": fill.LABEL,
        "fill_time_s": result["fill_time"],
        "flow_rate_m3_s": result["flow_rate"],
        "midplane_volume_m3": result["volume"],
        "peak_pressure_pa": result["peak_pressure"],
        "closing_pressure_pa": result["closing_pressure"],
        "clamp_force_n": result["clamp_force"],
        "steps": result["steps"],
        "thickness_min_m": float(thin.min()),
        "thickness_max_m": float(thin.max()),
        "thickness_mean_m": float(thin.mean()),
        "midplane_nodes": int(len(plane["points"])),
        "midplane_triangles": int(len(plane["tris"])),
        "gate_nodes": int(len(plane["gates"])),
        "last_filled_mm": [[float(x * 1000.0) for x in plane["skin_points"][i]] for i in result["last_filled"]],
        "history": result["history"],
        "warnings": list(result["warnings"]),
        "notes": list(result["notes"]),
        "counts": {"nodes": int(ctx.model.nodes_mm.shape[0]), "elements": int(ctx.model.tets.shape[0])},
        "seconds": round(time.time() - started, 3),
    }
    if isinstance(opts.get("pack"), dict):
        spec = dict(opts["pack"])
        spec.setdefault("thickness", float(thin.max()))
        spec.setdefault("gate_thickness", float(thin.min()))
        summary["pack"] = pack.pack(spec)
    if isinstance(opts.get("warp"), dict):
        spec = dict(opts["warp"])
        spec.setdefault("thickness", float(thin.mean()))
        spec.setdefault("length", float(np.ptp(plane["points"], axis=0).max()))
        summary["warp"] = pack.warp(spec)
    fields = {"arrival_time": arrival, "fill_pressure": pressure, "thickness": thick}
    meta = [field("arrival_time", "s", "node", 1, label="Fill time"), field("fill_pressure", "Pa", "node", 1, label="Pressure at 98 percent fill"), field("thickness", "m", "node", 1, label="Wall thickness")]
    return registry.Outcome(fields, summary, {"fields": meta, "basis": "scalar_p1"})


registry.register("flow", "Laminar pipe flow", run_flow, needs=("loads",), options={"solver": {"default": "own", "choices": ["own", "su2"]}, "fluid": {"density": None, "viscosity": None}, "su2_options": {}}, order=60, mesh_order=2)
registry.register("cooling", "Electronics cooling", run_cooling, needs=("material",), options={"h": {"unit": "W/m2K"}, "t_amb": {"default": 293.15, "unit": "K"}, "sources": []}, order=70)
registry.register("fill", "Injection fill estimate", run_fill, needs=("loads",), options={"polymer": {"eta": None, "k": None, "n": None}, "fill_time": {"unit": "s"}, "flow": {"unit": "m3/s"}, "pressure_limit": {"unit": "Pa"}, "pack": {}, "warp": {}}, order=80)
