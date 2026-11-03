import os

import numpy as np

from app.interchange.errors import InterchangeError, Report
from app.interchange.fileunits import ALIASES, document_unit, unit_key
from app.meshes import core, gltf, ply, store, threemf
from app.meshes.core import Mesh, MeshError, weld
from app.param.units import LENGTH_MM, mm_per_unit
from app.solid import scene, work
from app.solid.work import SolidError

NEW_EXT = (".3mf", ".glb", ".gltf", ".ply")
UNITLESS = (".stl", ".obj", ".ply")
THREEMF_UNIT = {"mm": "millimeter", "cm": "centimeter", "m": "meter", "in": "inch", "ft": "foot", "um": "micron"}
MAX_FILE = 512 * 1024 * 1024
DEFAULT_LINEAR = 0.01
DEFAULT_ANGULAR = 0.1
TRIANGLE_CAP = 4_000_000
SUGGEST = (("mm", 1.0), ("cm", 10.0), ("m", 1000.0), ("in", 25.4), ("ft", 304.8), ("um", 0.001))


def suggest_unit(diag_raw: float, current_mm: float):
    for key, mm in SUGGEST:
        if 1.0 <= diag_raw * mm <= 2000.0:
            return key if abs(mm - current_mm) > 1e-9 else ""
    return ""


def plausibility(report: Report, name: str, diag_mm: float, chosen_key: str, diag_raw: float, current_mm: float) -> None:
    if 0.1 <= diag_mm <= 10000.0:
        return
    hint = suggest_unit(diag_raw, current_mm)
    msg = '"%s" measures %.4g mm across in %s' % (name, diag_mm, chosen_key)
    if hint:
        msg += "; if its numbers were in %s it would measure %.4g mm. Import again with unit %s if that is right." % (hint, diag_raw * LENGTH_MM[hint], hint)
    else:
        msg += ", which is outside 0.1 mm to 10 m. Check the unit."
    report.warn(msg)


def read_file_bytes(path: str) -> bytes:
    try:
        if os.path.getsize(path) > MAX_FILE:
            raise InterchangeError("The file is larger than the 512 MB limit.", "toolarge")
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as err:
        raise InterchangeError("Cannot open the file: %s" % err, "io")


def read_parts(path: str, ext: str):
    data = read_file_bytes(path)
    try:
        if ext == ".3mf":
            return threemf.read_3mf(data)
        if ext in (".glb", ".gltf"):
            return gltf.read_gltf(data, os.path.dirname(path) if ext == ".gltf" else None)
        m, info = ply.read_ply(data)
        return [{"name": os.path.splitext(os.path.basename(path))[0], "mesh": m, "rgb": info.get("rgb")}], info
    except MeshError as err:
        raise InterchangeError(str(err), "badmesh")
    except (ValueError, KeyError, IndexError, TypeError) as err:
        raise InterchangeError("The file could not be read (%s)." % err, "badmesh")


def mesh_drawing_new(path: str, report: Report, unit: str = "", target=None, options=None):
    from app.doc.model import Drawing

    options = options or {}
    ext = os.path.splitext(path)[1].lower()
    d = Drawing(True if target is None else target.metric)
    d.header["INSUNITS"] = target.header.get("INSUNITS", 4) if target is not None else 4
    doc_key, doc_mm = document_unit(d)
    parts, info = read_parts(path, ext)
    stem = os.path.splitext(os.path.basename(path))[0]
    choice = str(options.get("unit_choice") or "convert").lower()
    if ext == ".ply":
        file_key = info.get("unit") and ALIASES.get(info["unit"])
        if unit:
            use_key = unit_key(unit)
            scale = LENGTH_MM[use_key]
        elif file_key:
            use_key, scale = file_key, LENGTH_MM[file_key]
            report.note("The file states its unit in a comment: %s." % file_key)
        else:
            use_key, scale = doc_key, doc_mm
            report.warn("PLY carries no unit; its numbers are read as %s." % doc_key)
        unitless = not file_key
    else:
        file_mm = info["unit_mm"]
        file_key = next((k for k, v in LENGTH_MM.items() if abs(v - file_mm) < 1e-9 and k in ("mm", "cm", "m", "in", "ft", "um")), "mm")
        if abs(file_mm - doc_mm) > 1e-9 * max(doc_mm, 1.0) and ext == ".3mf":
            if choice == "keep":
                scale, use_key = doc_mm, doc_key
                report.warn("The file is in %s and the document in %s; the numbers were kept as they are." % (file_key, doc_key))
            else:
                scale, use_key = file_mm, file_key
                report.warn("The file is in %s and the document in %s; the numbers were converted (scale %g)." % (file_key, doc_key, file_mm / doc_mm))
        else:
            scale, use_key = file_mm, file_key
        unitless = False
    base = info.get("unit_mm") if ext != ".ply" else None
    for n in info.get("notes", []):
        report.note(n)
    for w in info.get("warnings", []):
        report.warn(w)
    for i, p in enumerate(parts):
        m = p["mesh"]
        if ext == ".ply":
            raw_diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0)))
            mm_mesh = Mesh(m.v * scale, m.t)
        elif ext == ".3mf":
            raw_diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0))) / max(base, 1e-12)
            factor = scale / base
            mm_mesh = Mesh(m.v * factor, m.t)
        else:
            raw_diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0))) / 1000.0
            mm_mesh = m
        diag_mm = float(np.linalg.norm(mm_mesh.v.max(axis=0) - mm_mesh.v.min(axis=0)))
        name = p.get("name") or "%s %d" % (stem, i + 1)
        body = store.new_body(d, mm_mesh, name, {"op": "import", "format": ext[1:], "file": stem}, mm_per_unit(d), rgb=p.get("rgb"))
        d.add_entity(body, "model")
        s = body.summary
        if s["naked_edges"]:
            report.warn('"%s" has %d naked edges in %d loops.' % (name, s["naked_edges"], s["naked_loops"]))
        if s["nonmanifold_edges"]:
            report.warn('"%s" has %d non-manifold edges.' % (name, s["nonmanifold_edges"]))
        if ext == ".3mf" and s.get("inconsistent_edges"):
            report.warn('"%s" has %d edges where neighbouring triangles disagree on orientation; 3MF requires consistent orientation.' % (name, s["inconsistent_edges"]))
        if unitless or ext in (".glb", ".gltf", ".3mf"):
            plausibility(report, name, diag_mm, use_key, raw_diag, scale)
        report.count("meshes")
    report.note("%d mesh object%s read from the %s file, in %s." % (len(parts), "" if len(parts) == 1 else "s", ext[1:].upper(), use_key))
    report.extra["mesh"] = {"format": ext[1:], "objects": len(parts), "unit": use_key, "unit_mm": scale, "unit_declared": not unitless}
    return d


def tess_mesh(d, body, linear: float, angular: float) -> Mesh:
    import tempfile

    for _attempt in range(4):
        wid = work.worker_id(d, body)
        with tempfile.TemporaryDirectory(prefix="fcxmesh_") as tmp:
            out = os.path.join(tmp, "body.mesh")
            work.kcall("tessellate", {"id": wid, "linear": linear, "angular": angular, "path": out}, work.LONG)
            with open(out, "rb") as fh:
                raw = fh.read()
        p = scene.parse(raw)
        if p["nt"] <= TRIANGLE_CAP or _attempt == 3:
            break
        linear *= 4.0
    if not p["nv"] or not p["nt"]:
        raise MeshError("The solid has no triangles.")
    m = Mesh(p["pos"].astype(np.float64), p["idx"].astype(np.int64).reshape(-1, 3))
    diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0)))
    out_mesh, _ = weld(m, max(1e-7, diag * 2e-6))
    return out_mesh


def gather(d, entities, options, report: Report) -> list:
    linear = float(options.get("linear", DEFAULT_LINEAR))
    angular = float(options.get("angular", DEFAULT_ANGULAR))
    if not (0.0005 <= linear <= 100.0) or not (0.01 <= angular <= 1.0):
        raise InterchangeError("The tessellation deflection is 0.0005 to 100 mm and the angle 0.01 to 1 radian.", "badoption")
    parts = []
    for e in entities:
        if e.kind == "meshbody" and e.points_only:
            continue
        if e.kind not in ("meshbody", "solidbody"):
            continue
        try:
            if e.kind == "meshbody":
                m = store.load(d, e)
                m = Mesh(m.v + np.array(e.offset, dtype=np.float64) * mm_per_unit(d), m.t)
            else:
                m = tess_mesh(d, e, linear, angular)
                m = Mesh(m.v + np.array(e.offset, dtype=np.float64) * mm_per_unit(d), m.t)
        except (SolidError, MeshError) as err:
            raise InterchangeError("%s: %s" % (e.name or "A body", err), "kernel")
        parts.append({"name": e.name or "Body %d" % e.handle, "mesh": m, "rgb": list(e.rgb) if len(e.rgb or []) == 3 else None, "material": getattr(e, "material", "") or "", "solid": e.kind == "solidbody", "handle": e.handle})
    if not parts:
        raise InterchangeError("There are no meshes or solids to write.", "empty")
    return parts


def checks(parts, report: Report) -> None:
    for p in parts:
        r = core.report(p["mesh"])
        p["report"] = r
        if not r["closed"]:
            report.warn('"%s" is not a closed manifold mesh (%d naked edges, %d non-manifold); 3MF printers expect closed bodies.' % (p["name"], r["naked_edges"], r["nonmanifold_edges"]))
        elif r["inconsistent_edges"]:
            report.warn('"%s" has inconsistent triangle orientation.' % p["name"])


def write_new(d, path: str, entities, options, report: Report) -> dict:
    ext = os.path.splitext(path)[1].lower()
    options = options or {}
    parts = gather(d, entities, options, report)
    unit = str(options.get("unit") or "mm").lower()
    key = unit_key(unit)
    tri = sum(len(p["mesh"].t) for p in parts)
    if ext == ".3mf":
        if key not in THREEMF_UNIT:
            raise InterchangeError("A 3MF file takes mm, cm, m, in, ft or um.", "badunit")
        checks(parts, report)
        data = threemf.write_3mf(parts, THREEMF_UNIT[key])
        form = "3mf"
        report.note("3MF written in %s with %d object%s." % (THREEMF_UNIT[key], len(parts), "" if len(parts) == 1 else "s"))
    elif ext in (".glb", ".gltf"):
        data = gltf.write_glb(parts)
        form = "glb"
        report.note("glTF written in metres, Y up, with a metallic-roughness material per body.")
        if ext == ".gltf":
            report.note("A .gltf name was given; the file written is the binary GLB form, which is a valid glTF 2.0 asset.")
    elif ext == ".ply":
        binary = bool(options.get("binary", True))
        data = ply.write_ply([(Mesh(p["mesh"].v / LENGTH_MM[key], p["mesh"].t), p["rgb"]) for p in parts], binary, key)
        form = "binary" if binary else "ascii"
        report.note("PLY has no unit field; the unit %s is stated in a comment line." % key)
        report.warn("PLY is a unitless format; the numbers are in %s." % key)
    else:
        raise InterchangeError("Files of type %s are not written here." % ext, "unsupported")
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return {"path": path, "objects": len(parts), "triangles": tri, "bytes": len(data), "form": form, "unit": key, "parts": [{"name": p["name"], "closed": bool(p.get("report", {}).get("closed")), "volume": p.get("report", {}).get("volume")} for p in parts]}
