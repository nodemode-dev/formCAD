import os

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc.service import DocumentFault, service
from app.interchange import files
from app.interchange.errors import InterchangeError

HINT = {"open": ".dxf, .dwg, .dwt, .svg, .svgz or .fcad", "saveas": ".fcad, .dxf, .dwg or .dwt", "export": ".dxf, .dwg, .dwt, .svg, .png or .pdf", "import": ".dxf, .dwg, .svg or .svgz"}


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
    ext = files.ext_of(path)
    try:
        if ext in (".dxf", ".dwg", ".dwt"):
            service.save_foreign(ctx.doc, path, version, binary)
        elif ext in (".svg", ".png", ".pdf"):
            raise CommandError("Use EXPORT to write %s files." % ext[1:].upper())
        else:
            service.save(ctx.doc, path)
    except DocumentFault as err:
        raise CommandError(err.message)
    ctx.say("Saved %s." % path)
    return {"path": path}


def do_export(ctx, path, version="", binary=False):
    ext = files.ext_of(path)
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


def do_import(ctx, path, recover=False):
    try:
        out = files.merge_into(ctx.doc, path, "IMPORT", recover)
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
    return do_export(ctx, str(args.get("path", "")), str(args.get("version", "") or ""), bool(args.get("binary", False)))


@command("import", group="file", label="Import", description="Bring a DXF, DWG or SVG file into the current drawing.", menu="File > Import...", undoable=True, repeatable=False)
def import_cmd(ctx):
    path = yield from ask(ctx, "import", None)
    if path:
        do_import(ctx, path)


@executes("import")
def import_exec(ctx, args):
    return do_import(ctx, str(args.get("path", "")), bool(args.get("recover", False)))
