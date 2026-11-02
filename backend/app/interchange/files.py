import copy
import os

from app.interchange import dwg, dxfcommon
from app.interchange.errors import InterchangeError, Report

READ_EXT = (".dxf", ".dwg", ".dwt", ".svg", ".svgz")
WRITE_EXT = (".dxf", ".dwg", ".dwt", ".svg", ".png", ".pdf")
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


def formats() -> dict:
    return {
        "read": [{"ext": e, "name": n} for e, n in ((".dxf", "DXF"), (".dwg", "DWG (needs a converter)"), (".dwt", "Drawing template"), (".svg", "SVG"), (".svgz", "SVGZ"))],
        "write": [{"ext": e, "name": n} for e, n in ((".dxf", "DXF"), (".dwg", "DWG (needs a converter)"), (".dwt", "Drawing template"), (".svg", "SVG"), (".png", "PNG"), (".pdf", "PDF"))],
        "versions": list(dxfcommon.VERSION_ORDER),
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


def read_any(path: str, recover: bool = False, report: Report | None = None):
    report = report or Report()
    full = os.path.realpath(os.path.expanduser(path))
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
    else:
        raise InterchangeError("Files of this type are not read here.", "unsupported")
    from app.doc.kinds import blockcache

    blockcache.refresh_all(d)
    return d, report, kind


def write_any(drawing, path: str, version: str = "", binary: bool = False, precision: int = 16) -> Report:
    report = Report()
    kind = ext_of(path)
    from app.interchange import dxf_write

    ver = dxfcommon.parse_version(version) if version else ""
    if version and not ver:
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
    raise InterchangeError('Files of type "%s" cannot be written here.' % (kind or "this"), "unsupported")


def merge_into(doc, path: str, label: str = "IMPORT", recover: bool = False) -> dict:
    src, report, kind = read_any(path, recover)
    d = doc.drawing
    added = {"objects": 0, "layers": 0, "blocks": 0}
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
            d.add_entity(c, SPACE_MODEL)
            added["objects"] += 1
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
