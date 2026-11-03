import io

import numpy as np
from skfem import MeshTet

from app.analysis import ramps
from app.sim import fem, meshio, records, study
from app.sim.fem import SimError

FIELD_UNITS = {"Pa": ("MPa", 1e-6), "m": ("mm", 1e3), "K": ("K", 1.0), "W/m2": ("W/m2", 1.0), "Hz": ("Hz", 1.0), "1": ("1", 1.0)}
SIGNED = ("s1",)
SCALAR_FIELDS = ("vm", "disp_mag", "s1", "temperature", "flux_mag")
MAX_POINTS = 64


def surface(nodes: np.ndarray, tris: np.ndarray) -> tuple:
    used = np.unique(tris)
    remap = np.full(len(nodes), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return used, remap[tris]


def disp_of(data: dict, meta: dict, mode: int):
    if "f_mode_shape" in data:
        shapes = data["f_mode_shape"]
        if not 0 <= mode < shapes.shape[0]:
            raise SimError("There is no mode %d; the result holds %d." % (mode, shapes.shape[0]))
        return shapes[mode], True
    if "f_disp" in data:
        return data["f_disp"], False
    return None, False


def pick_field(data: dict, meta: dict, field: str, mode: int, nv: int):
    if field == "mode_shape" or (field in ("disp_mag",) and "f_mode_shape" in data):
        shape, _ = disp_of(data, meta, mode)
        return np.linalg.norm(shape, axis=1), "1" if "f_mode_shape" in data else "m"
    if "f_" + field not in data:
        names = [f["name"] for f in meta["fields"]]
        raise SimError("The result has no field %s. Fields: %s." % (field, ", ".join(names)))
    arr = data["f_" + field]
    if arr.ndim == 2 and arr.shape[1] == 3:
        return np.linalg.norm(arr, axis=1), next((f["unit"] for f in meta["fields"] if f["name"] == field), "1")
    if arr.shape[0] != nv:
        raise SimError("The field %s is not a value per node and cannot be drawn." % field)
    return arr, next((f["unit"] for f in meta["fields"] if f["name"] == field), "1")


def show(doc, study_id: str, field: str = "", mode: int = 0, scale="auto", ramp: str = "") -> dict:
    d = doc.drawing
    srow = records.need(d, study_id, "study")
    if not srow.get("result"):
        raise SimError("Study %s has no result yet." % study_id)
    row, data, meta = study.load_result(d, srow["result"])
    nodes = data["nodes"]
    nv = len(nodes)
    if not field:
        field = "load_factor" if "f_load_factor" in data else ("frequency" if "f_frequency" in data else ("vm" if "f_vm" in data else ("temperature" if "f_temperature" in data else "disp_mag")))
    if field in ("frequency", "load_factor"):
        field = "mode_shape"
    vals, unit = pick_field(data, meta, field, mode, nv)
    used, idx = surface(nodes, data["tris"])
    disp, shape_mode = disp_of(data, meta, mode)
    diag = float(np.linalg.norm(nodes.max(axis=0) - nodes.min(axis=0)))
    pos = nodes[used]
    deformed = None
    used_scale = 0.0
    if disp is not None:
        mm = disp * (1.0 if shape_mode else 1e3)
        peak = float(np.linalg.norm(mm, axis=1).max())
        if scale in ("auto", None, ""):
            used_scale = (0.1 * diag / peak) if peak > 0 else 0.0
        else:
            used_scale = float(scale)
        deformed = (pos + used_scale * mm[used]).reshape(-1).tolist()
    v = np.asarray(vals, dtype=float)[used]
    full = np.asarray(vals, dtype=float)
    dunit, factor = FIELD_UNITS.get(unit, (unit, 1.0))
    base = ramp or ("diverging" if field in SIGNED else "sequential")
    rec = ramps.get(d, base)
    labels = {f["name"]: f.get("label", f["name"]) for f in meta["fields"]}
    out = {
        "study": study_id,
        "result": row["id"],
        "type": row["type"],
        "field": field,
        "label": labels.get(field, field),
        "unit": unit,
        "display_unit": dunit,
        "display_factor": factor,
        "min": float(full.min()),
        "max": float(full.max()),
        "mean": float(full.mean()),
        "location": "node",
        "positions": pos.reshape(-1).tolist(),
        "deformed": deformed,
        "scale": used_scale,
        "indices": idx.reshape(-1).tolist(),
        "values": v.tolist(),
        "ramp": rec,
        "ramp_name": base,
        "modes": row.get("modes") or [],
        "mode": mode,
        "fields": meta["fields"],
        "summary": row["summary"],
    }
    return out


def scalar_at(sb, values, cell, ref) -> float:
    return float(sum(values[sb.element_dofs[i, cell]] * sb.elem.lbasis(ref, i)[0][0] for i in range(sb.element_dofs.shape[0])))


def at_point(sb, vb, u, cell, ref) -> np.ndarray:
    out = np.zeros(3)
    for c in range(3):
        comp = np.zeros(sb.N)
        comp[sb.nodal_dofs[0]] = u[vb.nodal_dofs[c]]
        comp[sb.edge_dofs[0]] = u[vb.edge_dofs[c]]
        out[c] = scalar_at(sb, comp, cell, ref)
    return out


def probe(doc, study_id: str, points: list, mode: int = 0) -> dict:
    d = doc.drawing
    srow = records.need(d, study_id, "study")
    if not srow.get("result"):
        raise SimError("Study %s has no result yet." % study_id)
    if len(points) > MAX_POINTS:
        raise SimError("At most %d probe points at once." % MAX_POINTS)
    row, data, meta = study.load_result(d, srow["result"])
    model = study.build_model(study.get_blob(d, row["mesh_blob"]))
    sb = fem.scalar_basis(model)
    vb = fem.vector_basis(model) if meta.get("basis") == "vector_p2" else None
    corner = MeshTet(np.ascontiguousarray(model.nodes_mm.T * meshio.MM), np.ascontiguousarray(model.tets.T.astype(np.int64)))
    finder = corner.element_finder()
    out = []
    for p in points:
        x = np.array([float(v) for v in p], dtype=float) * meshio.MM
        try:
            cell = int(finder(np.array([x[0]]), np.array([x[1]]), np.array([x[2]]))[0])
            ref = corner._mapping().invF(x.reshape(3, 1, 1), np.array([cell]))[:, 0, :]
        except Exception:
            cell = -1
        item = {"point": [float(v) for v in p], "inside": cell >= 0}
        if cell >= 0:
            if vb is not None and "f_u" in data and "f_mode_shape" not in data:
                u = at_point(sb, vb, data["f_u"], cell, ref)
                item["displacement_mm"] = [float(v * 1e3) for v in u]
                item["displacement_magnitude_mm"] = float(np.linalg.norm(u) * 1e3)
            if vb is not None and "f_u_modes" in data:
                u = at_point(sb, vb, data["f_u_modes"][mode], cell, ref)
                item["mode_shape"] = [float(v) for v in u]
            if "f_vm_element" in data:
                item["von_mises_pa"] = float(data["f_vm_element"][cell])
            if "f_T" in data:
                item["temperature_k"] = float(scalar_at(sb, data["f_T"], cell, ref))
        out.append(item)
    return {"study": study_id, "result": row["id"], "probes": out}
