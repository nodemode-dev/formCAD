import copy

import numpy as np

from app.sim import records
from app.topo import grid as G, problem as P, selectors, surface
from app.topo.grid import DESIGN, SOLID, VOID, Grid, TopoError

CAPS = {
    "unknowns": (30000, 12000),
    "iterations": (300, 100),
    "outer": (8, 3),
    "seconds": (1800, 300),
    "cells": (12000, 3500),
    "triangles": (200000, 50000),
}
DEFAULT_CELLS = 3000
OPTION_KEYS = ("reduction", "stress_limit_mpa", "safety_factor", "cell_mm", "cells", "preserve", "obstacles", "symmetry", "penalty", "radius_cells", "radius", "iterations", "max_outer", "projection", "beta_max", "extrusion", "auto_preserve", "change_tol", "min_iterations", "filters", "direct_dofs", "seconds", "relief_passes")


class Setup:
    def __init__(self):
        self.problem = None
        self.grid = None
        self.bounds = None
        self.spec = {}
        self.info = {}
        self.faceset = None


def cap(restrict: bool, key: str):
    window, locked = CAPS[key]
    return locked if restrict else window


def tessellation(drawing, body):
    from app.param.units import mm_per_unit
    from app.solid import scene, work

    raw = work.mesh_for(drawing, body, 1.0)
    p = scene.parse(raw)
    if not p["nv"] or not p["nt"]:
        raise TopoError("The body has no triangles to build a design space from.")
    off = np.array(body.offset, dtype=np.float64) * mm_per_unit(drawing)
    return p["pos"].astype(np.float64) + off, p["idx"].astype(np.int64).reshape(-1, 3), np.asarray(p["tri_face"]).astype(np.int64)


def snapshot(doc, study_id: str) -> dict:
    d = doc.drawing
    row = records.need(d, study_id, "study")
    if row.get("type") != "topology":
        raise TopoError("Study %s is a %s study, not a topology study." % (study_id, row.get("type")))
    body = d.ents.get(row["geometry"]["body"])
    if body is None or body.kind != "solidbody":
        raise TopoError("The solid body of study %s no longer exists." % study_id)
    snap = {"study": row, "loads": [records.need(d, i, "load") for i in row.get("loads") or []], "fixtures": [records.need(d, i, "fixture") for i in row.get("fixtures") or []], "material": records.get(d, row["material"], "material") if row.get("material") else None}
    snap["mesh"] = tessellation(d, body)
    snap["regions"] = {}
    opts = row.get("options") or {}
    for key in ("preserve", "obstacles"):
        for reg in opts.get(key) or []:
            if isinstance(reg, dict) and "body" in reg and reg["body"] not in snap["regions"]:
                ent = d.ents.get(int(reg["body"]))
                if ent is None or ent.kind != "solidbody":
                    raise TopoError("The %s region names body %s, which is not a solid body." % (key[:-1] if key == "preserve" else "obstacle", reg["body"]))
                snap["regions"][reg["body"]] = tessellation(d, ent)
    return snap


def material_mm(row) -> dict:
    if row is None:
        raise TopoError("Choose a material for the study.")
    E, nu, rho, sy = row.get("E"), row.get("nu"), row.get("rho"), row.get("sigma_y")
    if not E or not nu:
        raise TopoError("The material needs a Young's modulus and a Poisson's ratio.")
    return {"E": float(E) / 1e6, "nu": float(nu), "rho": float(rho or 0.0) * 1e-9, "yield": float(sy or 0.0) / 1e6}


def pick_cell(lo, hi, opts: dict, restrict: bool) -> float:
    size = np.array(hi) - np.array(lo)
    if np.any(size <= 0):
        raise TopoError("The body has no volume.")
    if opts.get("cell_mm"):
        h = float(opts["cell_mm"])
        if not h > 0:
            raise TopoError("The cell size must be positive.")
        return h
    target = float(opts.get("cells") or DEFAULT_CELLS)
    target = min(max(target, 100.0), cap(restrict, "cells"))
    return float((float(np.prod(size)) / target) ** (1.0 / 3.0))


def clean_options(opts: dict) -> dict:
    out = {}
    for k, v in (opts or {}).items():
        if k in OPTION_KEYS:
            out[k] = copy.deepcopy(v)
    return out


def region_voxels(grid: Grid, reg: dict, snap: dict) -> np.ndarray:
    if "body" in reg:
        pos, idx, _ = snap["regions"][reg["body"]]
        return G.voxelize_mesh(grid, pos, idx)
    spec = dict(reg)
    if "min" not in spec and "box" in spec:
        spec = {"kind": "box", "min": reg["box"][0], "max": reg["box"][1]}
    return G.region_mask_elements(grid, spec)


def selector_nodes(grid: Grid, fs: selectors.FaceSet, sel: dict, live_nodes: np.ndarray, what: str):
    faces = selectors.faces_for(sel, fs)
    if not faces:
        raise TopoError("%s selects no face of the body." % what)
    w, area, nsum = selectors.node_weights(grid, fs, faces, live_nodes)
    if not np.any(w > 0):
        raise TopoError("%s selects faces that do not touch the design grid." % what)
    return w, area, nsum


def resolve(snap: dict, restrict: bool, overrides: dict = None) -> Setup:
    opts = clean_options(snap["study"].get("options"))
    opts.update(clean_options(overrides or {}))
    mat = material_mm(snap["material"])
    pos, idx, tri_face = snap["mesh"]
    fs = selectors.FaceSet(pos, idx, tri_face)
    h = pick_cell(fs.lo, fs.hi, opts, restrict)
    grid = Grid.fit(fs.lo, fs.hi, h)
    if grid.ne > cap(restrict, "cells") * 4 or grid.ndof > cap(restrict, "unknowns"):
        raise TopoError("The grid would hold %d cells and %d unknowns; the limit is %d unknowns%s. Use a larger cell size." % (grid.ne, grid.ndof, cap(restrict, "unknowns"), " for a macro or an outside agent" if restrict else ""))
    from app.sim import fem
    from app.topo import hexfem

    need_mb = hexfem.estimate_bytes(grid.ndof) / 1048576.0
    free_mb = fem.available_mb()
    if free_mb is not None and need_mb > 0.7 * free_mb:
        raise TopoError("The optimisation needs about %.0f MB and only about %.0f MB is free. Use a larger cell size." % (need_mb, free_mb))
    design = G.voxelize_mesh(grid, pos, idx, int(cap(restrict, "triangles")))
    if design.sum() < 8:
        raise TopoError("The body holds fewer than 8 cells at this cell size. Use a smaller cell size.")
    preserve = [r for r in opts.get("preserve") or []]
    obstacles = [r for r in opts.get("obstacles") or []]
    pre_masks = [region_voxels(grid, r, snap) for r in preserve]
    obs_masks = [region_voxels(grid, r, snap) for r in obstacles]
    pre_specs = [{"kind": "mask", "mask": m} for m in pre_masks]
    obs_specs = [{"kind": "mask", "mask": m} for m in obs_masks]
    live_nodes = np.zeros(grid.nn, dtype=bool)
    cls0 = np.full(grid.ne, DESIGN, dtype=np.int8)
    cls0[~design] = VOID
    for m in obs_masks:
        cls0[m] = VOID
    live_nodes[grid.element_nodes()[cls0 != VOID].ravel()] = True
    loads, supports = [], []
    gravity = np.zeros(grid.ndof)
    for ld in snap["loads"]:
        t = ld["type"]
        if t in ("force", "pressure", "traction"):
            w, area, nsum = selector_nodes(grid, fs, ld["select"], live_nodes, "Load %s" % ld["id"])
            if t == "force":
                d = np.array(ld["direction"], dtype=float)
                n = np.linalg.norm(d)
                if n == 0:
                    raise TopoError("Load %s has a zero direction." % ld["id"])
                vec = d / n * float(ld["value"])
            elif t == "pressure":
                vec = -float(ld["value"]) * 1e-6 * nsum
            else:
                vec = np.array(ld["vector"], dtype=float) * 1e-6 * area
            loads.append((w, vec))
        elif t == "gravity":
            if mat["rho"] <= 0:
                raise TopoError("Gravity needs a material density.")
            d = np.array(ld["direction"], dtype=float)
            d = d / np.linalg.norm(d)
            per = mat["rho"] * grid.h ** 3 * float(ld["value"]) / 8.0
            en = grid.element_nodes()[cls0 != VOID]
            for c in range(3):
                np.add.at(gravity, 3 * en.ravel() + c, per * d[c])
        else:
            raise TopoError("Load %s is a %s load; a topology study takes force, pressure, traction and gravity loads." % (ld["id"], t))
    for fx in snap["fixtures"]:
        t = fx["type"]
        w, _a, _n = selector_nodes(grid, fs, fx["select"], live_nodes, "Fixture %s" % fx["id"])
        if t == "fixed":
            flags = [True, True, True]
        elif t == "roller":
            flags = [c not in fx["axes"] for c in range(3)]
        elif t == "symmetry":
            flags = [c == fx["axis"] for c in range(3)]
        elif t == "displacement":
            if any(abs(v) > 0 for v in fx["value"]):
                raise TopoError("Fixture %s prescribes a displacement; a topology study only takes zero displacements." % fx["id"])
            flags = [bool(c) for c in fx["components"]]
        else:
            raise TopoError("Fixture %s is a %s fixture; a topology study takes fixed, roller, symmetry and zero displacement fixtures." % (fx["id"], t))
        supports.append((w > 0, flags))
    prob = build_problem(grid, design, mat, pre_specs, obs_specs, loads, supports, gravity, bool(opts.get("auto_preserve", True)))
    st = Setup()
    st.problem = prob
    st.grid = grid
    st.bounds = (grid.origin.copy(), grid.origin + np.array([grid.nx, grid.ny, grid.nz]) * grid.h)
    st.faceset = fs
    spec = {k: v for k, v in opts.items() if k not in ("preserve", "obstacles", "cell_mm", "cells", "auto_preserve")}
    spec["iterations"] = min(int(spec.get("iterations", 100)), int(cap(restrict, "iterations")))
    spec["max_outer"] = min(int(spec.get("max_outer", 6)), int(cap(restrict, "outer")))
    if "safety_factor" not in spec and "stress_limit_mpa" not in spec and mat["yield"] > 0:
        spec["safety_factor"] = 1.5
        prob.notes.append("No stress limit was given: the yield strength over a safety factor of 1.5 is used.")
    if "symmetry" in spec:
        spec["symmetry"] = [s for s in spec["symmetry"]]
    st.spec = spec
    st.info = {"grid": grid.dims(), "cells_design": int((prob.cls == DESIGN).sum()), "cells_preserved": int((prob.cls == SOLID).sum()), "cells_void": int((prob.cls == VOID).sum()), "loaded_nodes": int(sum(int((w > 0).sum()) for w, _ in loads)), "fixed_dofs": int(prob.fixed.sum()), "body_volume_mm3": abs(surface.volume(pos, idx)), "material": {"E_mpa": mat["E"], "nu": mat["nu"], "rho_kg_mm3": mat["rho"], "yield_mpa": mat["yield"]}, "notes": list(prob.notes), "limits": {"unknowns": cap(restrict, "unknowns")}}
    return st


def build_problem(grid, design, mat, pre_specs, obs_specs, loads, supports, gravity, auto_preserve) -> P.Problem:
    cls = np.full(grid.ne, DESIGN, dtype=np.int8)
    cls[~design] = VOID
    notes = []
    for spec in obs_specs:
        m = G.region_mask_elements(grid, spec)
        if not m.any():
            notes.append("An obstacle region holds no cell of the grid.")
        cls[m] = VOID
    for spec in pre_specs:
        m = G.region_mask_elements(grid, spec) & design & (cls != VOID)
        if not m.any():
            notes.append("A preserve region holds no cell of the design space.")
        cls[m] = SOLID
    force = gravity.copy()
    fixed = np.zeros(grid.ndof, dtype=bool)
    touched = np.zeros(grid.nn, dtype=bool)
    for w, vec in loads:
        share = w / w.sum()
        for c in range(3):
            force[3 * np.arange(grid.nn) + c] += share * vec[c]
        touched |= w > 0
    for nodes, flags in supports:
        for c in range(3):
            if flags[c]:
                fixed[3 * np.flatnonzero(nodes) + c] = True
        touched |= nodes
    if not fixed.any():
        raise TopoError("Add at least one fixture: nothing holds the design.")
    if not np.any(force != 0):
        raise TopoError("Add at least one load: with no load there is nothing to optimise for.")
    if auto_preserve:
        near = touched[grid.element_nodes()].any(axis=1) & (cls == DESIGN)
        cls[near] = SOLID
        if near.any():
            notes.append("%d cells next to loads and fixtures were kept solid." % int(near.sum()))
    p = P.Problem(grid, cls, force, fixed, mat["E"], mat["nu"], mat["rho"], mat["yield"])
    p.notes = notes
    return p
