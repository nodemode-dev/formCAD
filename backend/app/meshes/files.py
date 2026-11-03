import os

import numpy as np

from app.interchange.errors import InterchangeError, Report
from app.meshes import formats, store
from app.meshes.core import Mesh, MeshError, weld
from app.param.units import LENGTH_MM, mm_per_unit
from app.solid import scene, work
from app.solid.work import SolidError

MESH_EXT = (".stl", ".obj")
WELD_EXACT = 1e-7


def unit_mm(d, unit: str = "") -> float:
    if unit:
        key = unit.lower()
        if key not in LENGTH_MM:
            raise InterchangeError('Unknown unit "%s". Use one of %s.' % (unit, ", ".join(sorted(LENGTH_MM))), "badunit")
        return LENGTH_MM[key]
    return mm_per_unit(d)


def read_file(path: str, scale_mm: float) -> tuple:
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as fh:
            data = fh.read(formats.MAX_FILE + 1)
    except OSError as err:
        raise InterchangeError("Cannot open the file: %s" % err, "io")
    try:
        m, info = formats.read_stl(data) if ext == ".stl" else formats.read_obj(data)
    except MeshError as err:
        raise InterchangeError(str(err), "badmesh")
    except ValueError as err:
        raise InterchangeError("The file holds a number that cannot be read (%s)." % err, "badmesh")
    return Mesh(m.v * scale_mm, m.t), info


def mesh_drawing(path: str, report: Report, unit: str = "", target=None):
    from app.doc.model import Drawing

    d = Drawing(True if target is None else target.metric)
    if target is not None:
        d.header["INSUNITS"] = target.header.get("INSUNITS", 4)
    else:
        d.header["INSUNITS"] = 4
    scale = unit_mm(d, unit)
    m, info = read_file(path, scale)
    stem = os.path.splitext(os.path.basename(path))[0]
    body = store.new_body(d, m, stem, {"op": "import", "format": os.path.splitext(path)[1][1:].lower(), "form": info.get("form")}, mm_per_unit(d))
    d.add_entity(body, "model")
    s = body.summary
    report.note("%d triangles and %d vertices read (%s)." % (s["triangles"], s["vertices"], info.get("form")))
    if not unit:
        report.note("The file carries no unit; its numbers are read as %s." % ("millimetres" if scale == 1.0 else "drawing units"))
    if s["naked_edges"]:
        report.warn("The mesh has %d naked edges in %d loops." % (s["naked_edges"], s["naked_loops"]))
    if s["nonmanifold_edges"]:
        report.warn("The mesh has %d non-manifold edges." % s["nonmanifold_edges"])
    for n in info.get("notes") or []:
        report.note(n)
    report.count("meshes")
    return d


def solid_mesh(d, body, detail: float = 1.0) -> Mesh:
    raw = work.mesh_for(d, body, detail)
    p = scene.parse(raw)
    if not p["nv"] or not p["nt"]:
        raise MeshError("The solid has no triangles.")
    m = Mesh(p["pos"].astype(np.float64), p["idx"].astype(np.int64).reshape(-1, 3))
    diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0)))
    out, _ = weld(m, max(WELD_EXACT, diag * 2e-6))
    off = np.array(body.offset, dtype=np.float64) * mm_per_unit(d)
    return Mesh(out.v + off, out.t)


def body_mesh(d, ent, detail: float = 1.0) -> Mesh:
    if ent.kind == "meshbody":
        m = store.load(d, ent)
        return Mesh(m.v + np.array(ent.offset, dtype=np.float64) * mm_per_unit(d), m.t)
    return solid_mesh(d, ent, detail)


def write_file(d, path: str, entities: list, binary: bool = True, unit: str = "", detail: float = 1.0) -> dict:
    ext = os.path.splitext(path)[1].lower()
    scale = unit_mm(d, unit)
    parts = []
    for e in entities:
        if e.kind == "meshbody" and e.points_only:
            continue
        if e.kind in ("meshbody", "solidbody"):
            try:
                m = body_mesh(d, e, detail)
            except (SolidError, MeshError) as err:
                raise InterchangeError("%s: %s" % (e.name or "A body", err), "kernel")
            parts.append((e.name or "mesh", Mesh(m.v / scale, m.t)))
    if not parts:
        raise InterchangeError("There are no meshes or solids to write.", "empty")
    try:
        if ext == ".stl":
            data = formats.write_stl(formats.merged([m for _n, m in parts]), binary, parts[0][0])
        else:
            data = formats.write_obj(parts)
    except MeshError as err:
        raise InterchangeError(str(err), "badmesh")
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    tri = sum(len(m.t) for _n, m in parts)
    return {"path": path, "objects": len(parts), "triangles": tri, "bytes": len(data), "form": "binary" if binary and ext == ".stl" else ("ascii" if ext == ".stl" else "obj"), "unit_mm": scale}
