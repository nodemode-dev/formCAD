import os

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.core import outputs
from app.doc.service import DocumentFault, service
from app.interchange import files
from app.interchange.errors import InterchangeError

HINT = {"open": ".dxf, .dwg, .dwt, .svg, .svgz, .step, .iges, .3dm, .stl, .obj or .fcad", "saveas": ".fcad, .dxf, .dwg, .dwt or .3dm", "export": ".dxf, .dwg, .dwt, .svg, .png, .pdf, .step, .3dm, .stl or .obj", "import": ".dxf, .dwg, .svg, .svgz, .step, .iges, .3dm, .stl or .obj"}


def stem(ctx) -> str:
    return os.path.splitext(os.path.basename(ctx.doc.path))[0] if ctx.doc.path else str(ctx.doc.name or "Drawing")


def ask(ctx, what, default):
    r = yield ctx.text("Enter file name (%s)" % HINT[what], default)
    if r.kind == "enter":
        return default or None
    if r.kind != "text":
        return None
    return str(r.value).strip() or None


def notes_line(report) -> str:
    d = report if isinstance(report, dict) else report.to_dict()
    n = d.get("notes") or d.get("lost") or []
    return "%d note%s." % (len(n), "" if len(n) == 1 else "s") if n else ""


def do_open(ctx, path):
    full = os.path.realpath(os.path.expanduser(path))
    try:
        doc = service.open(full)
    except DocumentFault as err:
        raise CommandError(err.message)
    ctx.say("Opened %s." % full)
    return {"path": full, "doc": doc.id}


def do_saveas(ctx, path, version="", binary=False):
    try:
        path = outputs.checked(path, (".fcad", ".dxf", ".dwg", ".dwt") + files.THREEDM_EXT, ".fcad")
    except outputs.OutputRefused as err:
        raise CommandError(str(err))
    ext = files.ext_of(path)
    if ext in files.THREEDM_EXT:
        return do_export(ctx, path, version)
    try:
        if ext in (".dxf", ".dwg", ".dwt"):
            service.save_foreign(ctx.doc, path, version, binary)
        elif ext in (".svg", ".png", ".pdf", ".step", ".stp", ".iges", ".igs"):
            raise CommandError("Use EXPORT to write %s files." % ext[1:].upper())
        else:
            service.save(ctx.doc, path)
    except DocumentFault as err:
        raise CommandError(err.message)
    ctx.doc.save_version = version
    ctx.doc.save_binary = bool(binary)
    ctx.say("Saved %s." % path)
    return {"path": path}


def do_export(ctx, path, version="", binary=False, unit=""):
    try:
        path = outputs.checked(path, (".dxf", ".dwg", ".dwt", ".svg", ".png", ".pdf") + tuple(files.MODEL_EXT) + files.THREEDM_EXT + files.MESH_EXT, ".dxf")
    except outputs.OutputRefused as err:
        raise CommandError(str(err))
    ext = files.ext_of(path)
    if ext in files.THREEDM_EXT or ext in files.MESH_EXT:
        return export_threedm_mesh(ctx, path, ext, version, binary, unit)
    if ext in files.MODEL_EXT:
        from app.cmd.commands import solids

        return solids.export_model(ctx, path, ext)
    if ext in files.PLOT_EXT:
        from app.cmd.commands import plot as P

        raw = {"layout": P.current_name(ctx), "path": path}
        res = P.run_plot(ctx, raw, None if ext != ".png" else "png", svg=ext == ".svg") if ext != ".pdf" else P.run_plot(ctx, raw, "pdf")
        P.echo(ctx, res)
        return P.pack(res)
    try:
        report = files.write_any(ctx.doc.drawing, path, version, binary)
    except InterchangeError as err:
        raise CommandError(str(err))
    ctx.say("Exported %s." % path)
    return {"path": path, "notes": report.to_dict()}


def export_threedm_mesh(ctx, path, ext, version, binary, unit):
    from app.interchange.errors import Report

    d = ctx.doc.drawing
    report = Report()
    chosen = [e for e in (d.get(h) for h in ctx.doc.selection) if e is not None]
    try:
        if ext in files.THREEDM_EXT:
            from app.interchange import threedm

            try:
                number = int(version) if version else 0
            except ValueError:
                raise CommandError('The 3DM archive version "%s" is not a number. Use 0 for the latest or a number from 2 up.' % version)
            threedm.write(d, path, report, number, unit, chosen or None)
        else:
            from app.meshes import files as mesh_files

            bodies = [e for e in (chosen or d.entities("model")) if e.kind in ("meshbody", "solidbody")]
            res = mesh_files.write_file(d, path, bodies, str(version).lower() != "ascii", unit)
            report.note("%d triangles written as %s." % (res["triangles"], res["form"]))
            report.extra["mesh"] = res
    except InterchangeError as err:
        raise CommandError(str(err))
    ctx.say("Exported %s." % path)
    for w in report.warnings[:6]:
        ctx.say(w)
    return {"path": path, "notes": report.to_dict()}


def do_import(ctx, path, recover=False, unit=""):
    try:
        out = files.merge_into(ctx.doc, path, "IMPORT", recover, unit)
    except InterchangeError as err:
        raise CommandError(str(err))
    ctx.say("Imported %s." % path)
    return out


@command("open", group="file", label="Open", description="Open a drawing file.", menu="File > Open...", undoable=False, repeatable=False)
def open_cmd(ctx):
    path = yield from ask(ctx, "open", None)
    if path:
        do_open(ctx, path)


@executes("open")
def open_exec(ctx, args):
    return do_open(ctx, str(args.get("path", "")))


@command("saveas", group="file", label="Save As", description="Save the drawing under a new name, in the format its extension names.", menu="File > Save As...", undoable=False, repeatable=False)
def saveas_cmd(ctx):
    path = yield from ask(ctx, "saveas", os.path.join(os.path.dirname(os.path.abspath(ctx.doc.path)) if ctx.doc.path else os.path.expanduser("~"), stem(ctx) + ".fcad"))
    if path:
        do_saveas(ctx, path)


@executes("saveas")
def saveas_exec(ctx, args):
    return do_saveas(ctx, str(args.get("path", "")), str(args.get("version", "") or ""), bool(args.get("binary", False)))


@command("export", group="file", label="Export", description="Write the drawing as DXF, DWG, SVG, PNG or PDF, by the file name's extension.", menu="File > Export...", undoable=False, repeatable=False)
def export_cmd(ctx):
    path = yield from ask(ctx, "export", os.path.join(os.path.dirname(os.path.abspath(ctx.doc.path)) if ctx.doc.path else os.path.expanduser("~"), stem(ctx) + ".dxf"))
    if path:
        do_export(ctx, path)


@executes("export")
def export_exec(ctx, args):
    return do_export(ctx, str(args.get("path", "")), str(args.get("version", "") or ""), bool(args.get("binary", False)), str(args.get("unit", "") or ""))


@command("import", group="file", label="Import", description="Bring a DXF, DWG or SVG file into the current drawing.", menu="File > Import...", undoable=True, repeatable=False)
def import_cmd(ctx):
    path = yield from ask(ctx, "import", None)
    if path:
        do_import(ctx, path)


@executes("import")
def import_exec(ctx, args):
    return do_import(ctx, str(args.get("path", "")), bool(args.get("recover", False)), str(args.get("unit", "") or ""))
