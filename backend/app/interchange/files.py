import copy
import os

from app.interchange import dwg, dxfcommon
from app.interchange.errors import InterchangeError, Report

MODEL_EXT = (".step", ".stp", ".iges", ".igs")
THREEDM_EXT = (".3dm",)
NEW_MESH_EXT = (".3mf", ".glb", ".gltf", ".ply")
MESH_EXT = (".stl", ".obj") + NEW_MESH_EXT
READ_EXT = (".dxf", ".dwg", ".dwt", ".svg", ".svgz") + MODEL_EXT + THREEDM_EXT + MESH_EXT
WRITE_EXT = (".dxf", ".dwg", ".dwt", ".svg", ".png", ".pdf") + MODEL_EXT + THREEDM_EXT + MESH_EXT
PLOT_EXT = (".svg", ".png", ".pdf")
NATIVE = ".fcad"
MERGED = ("layers", "linetypes", "textstyles", "dimstyles", "mleaderstyles", "tablestyles", "mlinestyles", "scales")


def ext_of(path: str) -> str:
    return os.path.splitext(str(path).strip())[1].lower()


def sniff(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
    except OSError as err:
        raise InterchangeError("Cannot open the file: %s" % err, "io")
    if head.startswith(b"AC10") or head.startswith(b"AC1."):
        return ".dwg"
    if head.startswith(b"AutoCAD Binary DXF"):
        return ".dxf"
    if head[:2] == b"\x1f\x8b":
        return ".svgz"
    if head.lstrip()[:5] == b"<?xml" or b"<svg" in head:
        return ".svg"
    return ""


def detect(path: str) -> str:
    e = ext_of(path)
    if e in READ_EXT or e == NATIVE:
        return e
    if e == "":
        return ".dxf"
    guess = sniff(path) if os.path.isfile(path) else ""
    if guess:
        return guess
    raise InterchangeError('Files of type "%s" are not supported.' % e, "unsupported")


MODEL_OPTIONS = {
    "step": ["schema", "unit", "pmi", "bodies"],
    "iges": ["unit", "bodies"],
    "3mf": ["unit", "linear", "angular", "bodies"],
    "glb": ["linear", "angular", "bodies"],
    "ply": ["unit", "binary", "linear", "angular", "bodies"],
}


def formats() -> dict:
    read = [(".dxf", "DXF", "drawing"), (".dwg", "DWG (needs a converter)", "drawing"), (".dwt", "Drawing template", "drawing"), (".svg", "SVG", "drawing"), (".svgz", "SVGZ", "drawing"), (".step", "STEP (needs the kernel)", "step"), (".stp", "STEP (needs the kernel)", "step"), (".iges", "IGES (needs the kernel)", "iges"), (".igs", "IGES (needs the kernel)", "iges"), (".3dm", "3DM (needs the kernel)", "3dm"), (".stl", "STL mesh", "mesh"), (".obj", "OBJ mesh", "mesh"), (".3mf", "3MF mesh", "3mf"), (".glb", "glTF binary", "glb"), (".gltf", "glTF", "glb"), (".ply", "PLY mesh", "ply")]
    write = [(".dxf", "DXF", "drawing"), (".dwg", "DWG (needs a converter)", "drawing"), (".dwt", "Drawing template", "drawing"), (".svg", "SVG", "drawing"), (".png", "PNG", "drawing"), (".pdf", "PDF", "drawing"), (".step", "STEP (needs the kernel)", "step"), (".stp", "STEP (needs the kernel)", "step"), (".iges", "IGES (needs the kernel)", "iges"), (".igs", "IGES (needs the kernel)", "iges"), (".3dm", "3DM (needs the kernel)", "3dm"), (".stl", "STL mesh", "mesh"), (".obj", "OBJ mesh", "mesh"), (".3mf", "3MF mesh", "3mf"), (".glb", "glTF binary", "glb"), (".ply", "PLY mesh", "ply")]
    return {
        "read": [{"ext": e, "name": n, "kind": k, "options": MODEL_OPTIONS.get(k, [])} for e, n, k in read],
        "write": [{"ext": e, "name": n, "kind": k, "options": MODEL_OPTIONS.get(k, [])} for e, n, k in write],
        "versions": list(dxfcommon.VERSION_ORDER),
        "schemas": [{"id": "ap203", "name": "AP203"}, {"id": "ap214", "name": "AP214 (default)"}, {"id": "ap242", "name": "AP242 (DIS schema, carries PMI)"}],
        "units": ["mm", "cm", "m", "in", "ft", "um"],
    }


def svg_drawing(path: str, report: Report):
    from app.doc.model import Drawing
    from app.interchange import svg_import
    from app.doc import tables as T

    ents, layers, page, rep = svg_import.import_svg(path, report)
    d = Drawing(True)
    for name in layers:
        d.table_set("layers", T.new_layer(name))
    for e in ents:
        d.add_entity(e, "model")
    return d


def model_drawing(path: str, kind: str, report: Report, target=None, options=None):
    from app.interchange import stepio

    return stepio.read_into(path, kind, report, target, options)


def read_any(path: str, recover: bool = False, report: Report | None = None, unit: str = "", target=None, options=None):
    report = report or Report()
    unit = str(unit or (options or {}).get("unit") or "")
    from app.interchange.fileunits import ALIASES

    unit = ALIASES.get(unit.strip().lower(), unit)
    full =os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(full):
        raise InterchangeError('Cannot find the file "%s".' % path, "missing")
    kind = detect(full)
    from app.interchange import dxf_read

    if kind in (".dxf", ".dwt"):
        d, _ = dxf_read.read_file(full, recover, report)
    elif kind == ".dwg":
        produced, work = dwg.dwg_to_dxf(full)
        try:
            d, _ = dxf_read.read_file(produced, recover, report)
        finally:
            import shutil

            shutil.rmtree(work, ignore_errors=True)
    elif kind in (".svg", ".svgz"):
        d = svg_drawing(full, report)
    elif kind in MODEL_EXT:
        d = model_drawing(full, kind, report, target, options)
    elif kind in THREEDM_EXT:
        from app.interchange import threedm

        d = threedm.read_drawing(full, report, target)
    elif kind in NEW_MESH_EXT:
        from app.meshes import exchange

        d = exchange.mesh_drawing_new(full, report, unit, target, options)
    elif kind in MESH_EXT:
        from app.meshes import files as mesh_files

        d = mesh_files.mesh_drawing(full, report, unit, target)
    else:
        raise InterchangeError("Files of this type are not read here.", "unsupported")
    from app.doc.kinds import blockcache

    blockcache.refresh_all(d)
    return d, report, kind


def write_any(drawing, path: str, version: str = "", binary: bool = False, precision: int = 16, options=None, doc=None) -> Report:
    report = Report()
    kind = ext_of(path)
    from app.interchange import dxf_write

    ver = dxfcommon.parse_version(version) if version else ""
    if kind in MODEL_EXT:
        from app.interchange import stepio

        opts = dict(options or {})
        if version and not opts.get("schema"):
            opts["schema"] = str(version).lower()
        stepio.write_file(drawing, path, report, opts, doc)
        return report
    if kind in NEW_MESH_EXT:
        from app.meshes import exchange

        opts = dict(options or {})
        opts.setdefault("binary", bool(binary) or str(version).lower() != "ascii")
        chosen = opts.get("bodies")
        ents = [e for e in drawing.entities("model") if e.kind in ("meshbody", "solidbody") and (not chosen or e.handle in {int(h) for h in chosen})]
        res = exchange.write_new(drawing, path, ents, opts, report)
        report.note("%d triangles written as %s." % (res["triangles"], res["form"]))
        report.extra["mesh"] = res
        return report
    if version and not ver and kind not in THREEDM_EXT + MESH_EXT:
        raise InterchangeError('Unknown DXF version "%s". Use one of %s.' % (version, ", ".join(dxfcommon.VERSION_ORDER)), "badversion")
    if kind in (".dxf", ".dwt"):
        return dxf_write.write_file(drawing, path, ver, report, precision, binary)
    if kind == ".dwg":
        import tempfile

        with tempfile.TemporaryDirectory(prefix="fcdwgw_") as tmp:
            mid = os.path.join(tmp, "tmp.dxf")
            dxf_write.write_file(drawing, mid, ver or "R2018", report, precision)
            for n in dwg.dxf_to_dwg(mid, path, ver or "R2018"):
                report.note(n)
        return report
    if kind in THREEDM_EXT:
        from app.interchange import threedm

        try:
            number = int(version) if version else 0
        except ValueError:
            raise InterchangeError('The 3DM archive version "%s" is not a number. Use 0 for the latest or a number from 2 up.' % version, "badversion")
        threedm.write(drawing, path, report, number)
        return report
    if kind in MESH_EXT:
        from app.meshes import files as mesh_files

        bodies = [e for e in drawing.entities("model") if e.kind in ("meshbody", "solidbody")]
        res = mesh_files.write_file(drawing, path, bodies, str(version).lower() != "ascii")
        report.note("%d triangles written as %s." % (res["triangles"], res["form"]))
        return report
    raise InterchangeError('Files of type "%s" cannot be written here.' % (kind or "this"), "unsupported")


def merge_into(doc, path: str, label: str = "IMPORT", recover: bool = False, unit: str = "", options=None) -> dict:
    src, report, kind = read_any(path, recover, None, unit, doc.drawing, options)
    d = doc.drawing
    added = {"objects": 0, "layers": 0, "blocks": 0}
    handle_map, pid_map = {}, {}
    from app.doc import blockdefs
    from app.doc.entities import entity_from_dict
    from app.doc.model import SPACE_MODEL, block_space

    with doc.transaction(label):
        if kind in (".svg", ".svgz"):
            for rec in src.tables["layers"].values():
                if not d.tables["layers"].has(rec["name"]):
                    d.table_set("layers", copy.deepcopy(rec))
                    added["layers"] += 1
        else:
            for t in MERGED:
                for rec in src.tables[t].values():
                    if not d.tables[t].has(rec["name"]):
                        d.table_set(t, copy.deepcopy(rec))
                        if t == "layers":
                            added["layers"] += 1
        remap = {}
        taken = set()
        for rec in list(src.tables["blocks"].values()):
            if rec.get("xref"):
                continue
            nm = rec["name"]
            if d.tables["blocks"].has(nm):
                if nm.startswith("*"):
                    n = 1
                    while d.tables["blocks"].has("*U%d" % n) or ("*U%d" % n) in taken:
                        n += 1
                    remap[nm.casefold()] = "*U%d" % n
                    taken.add("*U%d" % n)
                continue
            remap[nm.casefold()] = nm
        for rec in list(src.tables["blocks"].values()):
            target = remap.get(rec["name"].casefold())
            if not target or d.tables["blocks"].has(target) or rec.get("xref"):
                continue
            nr = d.define_block(target, rec.get("base"), rec.get("description", ""))
            nr["explodable"] = bool(rec.get("explodable", True))
            nr["annotative"] = bool(rec.get("annotative", False))
            d.table_set("blocks", nr)
            for e in src.entities(block_space(rec["name"])):
                c = entity_from_dict(e.to_dict())
                c.handle = 0
                c.reactors = []
                if getattr(c, "block", None) and c.block.casefold() in remap:
                    c.block = remap[c.block.casefold()]
                d.add_entity(c, block_space(target))
            added["blocks"] += 1
        for e in src.entities(SPACE_MODEL):
            c = entity_from_dict(e.to_dict())
            c.handle = 0
            c.reactors = []
            if getattr(c, "block", None) and c.block.casefold() in remap:
                c.block = remap[c.block.casefold()]
            if c.kind == "dimension":
                c.associativity = {}
            if c.kind == "solidbody":
                from app.solid import ids

                for path, data in src.blobs.items():
                    d.blobs.setdefault(path, data)
                old_faces, old_edges = list(c.face_ids), list(c.edge_ids)
                c.face_ids, c.edge_ids = ids.fresh(d, len(c.face_ids), len(c.edge_ids))
                for a, b in zip(old_faces, c.face_ids):
                    pid_map[(e.handle, "face", a)] = b
                for a, b in zip(old_edges, c.edge_ids):
                    pid_map[(e.handle, "edge", a)] = b
                c.lineage = {}
            if c.kind == "meshbody":
                from app.solid import ids

                for path, data in src.blobs.items():
                    d.blobs.setdefault(path, data)
                c.face_ids, c.edge_ids = ids.fresh(d, len(c.face_ids), len(c.edge_ids))
                c.lineage = {}
            handle_map[e.handle] = d.add_entity(c, SPACE_MODEL)
            added["objects"] += 1
        if handle_map and isinstance(src.header.get("PMI"), dict):
            from app.pmi import store as pmi_store

            added["pmi"] = pmi_store.merge(d, src, handle_map, pid_map)
    from app.doc.kinds import blockcache

    blockcache.refresh_all(d)
    return {"added": added, "report": report.to_dict(), "summary": report.summary()}


def save_document(doc, path: str, version: str = "", binary: bool = False) -> Report:
    ext = ext_of(path)
    if ext in PLOT_EXT:
        raise InterchangeError("Use the plot export for %s files." % ext[1:].upper(), "plot")
    target = os.path.realpath(os.path.expanduser(path))
    fx = (doc.drawing.foreign or {}).get("dxf", {}) if hasattr(doc.drawing, "foreign") else {}
    if not version and fx.get("acadver"):
        version = dxfcommon.default_version(fx["acadver"])
    rep = write_any(doc.drawing, target, version, binary)
    return rep
