import json
import os
import sys
import tempfile
import threading
import time

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
CONVERT_OUT = (".pdf", ".png", ".svg", ".dxf", ".dwg", ".fcad")
HELP = """usage: formcad-engine <command> [options]

  info FILE [--compact]               print a JSON summary of a drawing
  convert IN OUT [options]            convert by the extension of OUT: pdf, png, svg, dxf, dwg, fcad
        --window X1 Y1 X2 Y2          show exactly this rectangle (image outputs)
        --view extents|current        framing for image outputs
        --layout NAME  --dpi N  --paper NAME  --dxf-version R2018  --in-place
  run [FILE...] [steps]               open files and run steps in the order typed
        --sample NAME  --new  --script TEXT  --script-file F  --lisp-file F
        --python-macro F [--grant-files DIR] [--grant-network] [--grant-subprocess]
        --command "id {json}"  --save PATH  --export PATH  --window ...  --view ...  --in-place
  commands [FILTER] [--compact]       print the command catalogue as JSON
  mcp [--connect HOST:PORT|auto] [--tools all|core]
                                      MCP server on standard input and output
  perf [N|FILE]                       time the engine on N objects or a drawing
  sample NAME OUT                     write a sample drawing: bracket or floor
  plugin seal DIR | list              hash a plugin folder into its manifest, or list plugins
  macro list                          list Python macros and their trust state

shared: --settings-dir DIR (empty means a throwaway folder), --version, --help
exit codes: 0 success, 1 a command failed, 2 usage error
"""


class Usage(Exception):
    pass


class Failed(Exception):
    pass


def err(text: str) -> None:
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def out(obj, compact: bool = False) -> None:
    text = json.dumps(obj, separators=(",", ":") if compact else None, indent=None if compact else 2, default=str)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass


def is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def parse(argv: list, spec: dict, ordered: bool = False):
    positionals, opts, seen, order = [], {}, set(), []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            positionals.extend(argv[i + 1 :])
            break
        if token.startswith("--") and len(token) > 2:
            name, eq, inline = token.partition("=")
            if name not in spec:
                raise Usage("Unknown option %s." % name)
            count, repeat = spec[name]
            if name in seen and not repeat:
                raise Usage("The option %s was given twice." % name)
            seen.add(name)
            values = []
            if count:
                if eq:
                    values = [inline] if count == 1 else inline.split(",")
                else:
                    for _ in range(count):
                        i += 1
                        if i >= len(argv):
                            raise Usage("The option %s needs %d value(s)." % (name, count))
                        if argv[i].startswith("-") and not is_number(argv[i]):
                            raise Usage("A value that begins with a dash is written %s=VALUE." % name)
                        values.append(argv[i])
                if len(values) != count:
                    raise Usage("The option %s needs %d value(s)." % (name, count))
            elif eq:
                raise Usage("The option %s takes no value." % name)
            val = values[0] if count == 1 else values if count else True
            if repeat:
                opts.setdefault(name, []).append(val)
            else:
                opts[name] = val
            order.append((name, val))
        elif token.startswith("-") and len(token) > 1 and not is_number(token):
            raise Usage("Unknown option %s." % token)
        else:
            positionals.append(token)
        i += 1
    return (positionals, opts, order) if ordered else (positionals, opts)


def settings_dir(opts: dict) -> None:
    given = opts.get("--settings-dir")
    if given is None:
        return
    if given == "":
        given = tempfile.mkdtemp(prefix="formcad-cli-")
    os.environ["FORMCAD_DATA_DIR"] = given


def headless() -> None:
    from app.doc.service import service

    service._started = True
    for name in ("FORMCAD_DESKTOP",):
        os.environ.pop(name, None)


def open_any(path: str):
    from app.doc.service import DocumentFault, service

    if not os.path.isfile(path):
        raise Failed('Cannot find the file "%s".' % path)
    try:
        return service.open(path)
    except DocumentFault as exc:
        raise Failed(exc.message)


def window_of(values) -> list | None:
    if values is None:
        return None
    try:
        box = [float(v) for v in values]
    except ValueError:
        raise Usage("A window is four numbers.")
    return box


def cmd_info(argv: list) -> int:
    pos, opts = parse(argv, {"--compact": (0, False), "--settings-dir": (1, False)})
    settings_dir(opts)
    if len(pos) != 1:
        raise Usage("info takes one drawing file.")
    headless()
    from app.automation import ops

    doc = open_any(pos[0])
    data = ops.summary(doc)
    data["file"] = os.path.realpath(pos[0])
    data["bytes"] = os.path.getsize(pos[0])
    data["header"] = {k: doc.drawing.header.get(k) for k in ("INSUNITS", "LUNITS", "LUPREC", "MEASUREMENT", "ACADVER") if k in doc.drawing.header}
    out(data, bool(opts.get("--compact")))
    return EXIT_OK


def image_request(opts: dict, ext: str, doc, out_path: str) -> dict:
    from app.automation import ops

    layout = opts.get("--layout") or "Model"
    window = window_of(opts.get("--window"))
    view = opts.get("--view") or ""
    if window and view:
        raise Usage("--window and --view cannot be used together.")
    if view and view not in ("extents", "current"):
        raise Usage("--view is extents or current.")
    raw = ops.plot_request(layout, window, view, float(opts["--dpi"]) if opts.get("--dpi") else None, opts.get("--paper") or "")
    if view == "current":
        v = doc.view
        if v and v.get("height"):
            raw["view"] = {"center": list(v.get("center", [0, 0]))[:2], "height": float(v["height"])}
            raw.pop("area", None)
    if ext == ".png" and not opts.get("--dpi") and not opts.get("--paper"):
        raw.update({"width": 304.8, "height": 203.2, "landscape": True, "dpi": 200.0, "margins": [0, 0, 0, 0], "fit": True})
    elif ext == ".pdf" and not opts.get("--paper") and str(layout).lower() == "model":
        box = doc.drawing.extents(doc.current_space)
        if box and (box[2] - box[0]) > (box[3] - box[1]):
            raw["landscape"] = True
    raw["path"] = out_path
    return raw


def do_convert(doc, out_path: str, opts: dict) -> dict:
    from app.automation import ops
    from app.interchange import files
    from app.interchange.errors import InterchangeError
    from app.output import plot
    from app.output import request as R

    ext = os.path.splitext(out_path)[1].lower()
    if ext not in CONVERT_OUT:
        raise Usage("The output type %s is not supported. Use one of %s." % (ext or "(none)", ", ".join(CONVERT_OUT)))
    if (opts.get("--window") or opts.get("--view")) and ext not in (".png", ".svg", ".pdf"):
        raise Usage("--window and --view need an image or PDF output.")
    folder = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(folder):
        raise Failed("The folder %s does not exist." % folder)
    try:
        if ext in (".dxf", ".dwg"):
            report = files.write_any(doc.drawing, out_path, opts.get("--dxf-version") or "", False)
            return {"path": os.path.abspath(out_path), "format": ext[1:], "notes": report.summary()}
        if ext == ".fcad":
            from app.doc.service import service

            saved = service.save(doc, os.path.abspath(out_path))
            return {"path": saved.path, "format": "fcad"}
        raw = image_request(opts, ext, doc, os.path.abspath(out_path))
        res = plot.export_svg(doc, raw) if ext == ".svg" else plot.run(doc, raw, ext[1:])
        return {"path": res.get("path", out_path), "format": ext[1:], "size": res["size"], "pages": res["pages"]}
    except InterchangeError as exc:
        raise Failed(str(exc))
    except R.PlotError as exc:
        raise Failed(str(exc))
    except ops.OpError as exc:
        raise Failed(str(exc))


def cmd_convert(argv: list) -> int:
    spec = {"--window": (4, False), "--view": (1, False), "--layout": (1, False), "--dpi": (1, False), "--paper": (1, False), "--dxf-version": (1, False), "--in-place": (0, False), "--settings-dir": (1, False)}
    pos, opts = parse(argv, spec)
    settings_dir(opts)
    if len(pos) != 2:
        raise Usage("convert takes an input file and an output file.")
    src, dst = pos
    if os.path.exists(dst) and os.path.exists(src) and os.path.samefile(src, dst) and not opts.get("--in-place"):
        raise Usage("The output is the input file; add --in-place to overwrite it.")
    ext = os.path.splitext(dst)[1].lower()
    if ext not in CONVERT_OUT:
        raise Usage("The output type %s is not supported. Use one of %s." % (ext or "(none)", ", ".join(CONVERT_OUT)))
    if opts.get("--window") and opts.get("--view"):
        raise Usage("--window and --view cannot be used together.")
    headless()
    doc = open_any(src)
    result = do_convert(doc, dst, opts)
    err("wrote %s" % result["path"])
    out(result, True)
    return EXIT_OK


def cmd_commands(argv: list) -> int:
    pos, opts = parse(argv, {"--compact": (0, False), "--settings-dir": (1, False)})
    settings_dir(opts)
    if len(pos) > 1:
        raise Usage("commands takes at most one filter.")
    from app.automation import ops

    items = ops.catalogue(pos[0] if pos else "")
    from app.automation import forms

    rows = []
    for item in items:
        row = {"id": item["id"], "label": item["label"], "menu": item["menu"], "aliases": item["aliases"], "programmatic": item["programmatic"]}
        if item["programmatic"]:
            from app.cmd import registry

            row["parameters"] = sorted(k for k in forms.schema_for(registry.COMMANDS[item["id"]])["properties"] if k != "document")
        rows.append(row)
    out({"commands": rows}, bool(opts.get("--compact")))
    return EXIT_OK


def serve_local() -> str:
    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, name="formcad-local", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started and server.servers:
            break
        time.sleep(0.05)
    else:
        raise Failed("The local engine did not start.")
    port = server.servers[0].sockets[0].getsockname()[1]
    return "http://127.0.0.1:%d" % port


def substitute(value, handle):
    if isinstance(value, str) and value == "last handle":
        if handle is None:
            raise Failed('"last handle" was used before any step returned a handle.')
        return handle
    if isinstance(value, list):
        return [substitute(v, handle) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, handle) for k, v in value.items()}
    return value


def last_handle_of(result):
    if isinstance(result, dict):
        if isinstance(result.get("handle"), int):
            return result["handle"]
        if isinstance(result.get("handles"), list) and result["handles"]:
            return result["handles"][-1]
        for v in result.values():
            found = last_handle_of(v)
            if found is not None:
                return found
    return None


def build_sample(doc, name: str) -> None:
    from app.automation import ops

    def go(cmd, **args):
        r = ops.execute(doc, cmd, args)
        if not r["ok"]:
            raise Failed(r["error"])
        return r

    if name == "bracket":
        go("pline", vertices=[[0, 0], [100, 0], [100, 20], [30, 20], [30, 60], [0, 60]], closed=True)
        go("circle", center=[15, 40], radius=6)
        go("circle", center=[65, 10], radius=4)
        go("line", points=[[-10, 30], [110, 30]])
    elif name in ("floor", "floorplan"):
        go("rectang", p1=[0, 0], p2=[8000, 5000])
        go("line", points=[[4000, 0], [4000, 5000]])
        go("line", points=[[4000, 2500], [8000, 2500]])
        go("text", point=[1500, 2500], height=250, text="LIVING")
        go("text", point=[5500, 3600], height=250, text="KITCHEN")
        go("text", point=[5500, 1200], height=250, text="BATH")
    else:
        raise Usage("The sample names are bracket and floor.")


def cmd_sample(argv: list) -> int:
    pos, opts = parse(argv, {"--settings-dir": (1, False)})
    settings_dir(opts)
    if len(pos) != 2:
        raise Usage("sample takes a name and an output file.")
    headless()
    from app.doc.service import service

    doc = service.new("sample", "metric")
    build_sample(doc, pos[0].lower())
    dst = pos[1]
    ext = os.path.splitext(dst)[1].lower()
    if ext in (".dxf", ".dwg", ".fcad", ""):
        saved = service.save(doc, os.path.abspath(dst))
        err("wrote %s" % saved.path)
        out({"path": saved.path})
    else:
        result = do_convert(doc, dst, {})
        err("wrote %s" % result["path"])
        out(result, True)
    return EXIT_OK


def run_python(path: str, doc, opts_list: list, grants: dict) -> dict:
    from app.automation import macros

    try:
        url = serve_local()
        return macros.run(path, url, doc.id if doc else "", None, None, grants)
    except macros.MacroError as exc:
        raise Failed(str(exc))


def run_lisp(doc, path: str) -> dict:
    from app.automation import ops

    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise Failed('Cannot find the LISP file "%s".' % path)
    from app.cmd import registry

    registry.load_modules()
    for name in ("appload", "load"):
        if name in registry.COMMANDS and registry.COMMANDS[name].execute is not None:
            r = ops.execute(doc, name, {"path": full, "file": full})
            if not r["ok"]:
                raise Failed(r["error"])
            return r
    raise Failed("The LISP engine is not part of this build.")


def cmd_run(argv: list) -> int:
    spec = {"--sample": (1, True), "--new": (0, True), "--script": (1, True), "--script-file": (1, True), "--lisp-file": (1, True), "--python-macro": (1, True), "--command": (1, True), "--save": (1, False), "--export": (1, False), "--window": (4, False), "--view": (1, False), "--in-place": (0, False), "--grant-files": (1, True), "--grant-network": (0, False), "--grant-subprocess": (0, False), "--settings-dir": (1, False), "--layout": (1, False), "--dxf-version": (1, False)}
    pos, opts, order = parse(argv, spec, True)
    settings_dir(opts)
    if opts.get("--window") and opts.get("--view"):
        raise Usage("--window and --view cannot be used together.")
    if (opts.get("--window") or opts.get("--view")) and not opts.get("--export"):
        raise Usage("--window and --view need --export.")
    if opts.get("--in-place") and not opts.get("--save"):
        pass
    for p in pos:
        if opts.get("--save") and os.path.exists(p) and os.path.exists(opts["--save"]) and os.path.samefile(p, opts["--save"]) and not opts.get("--in-place"):
            raise Usage("--save names an input file; add --in-place to overwrite it.")
    headless()
    from app.automation import ops
    from app.doc.service import service

    doc = None
    handle = None
    failed = False
    for p in pos:
        doc = open_any(p)
    grants = {"network": bool(opts.get("--grant-network")), "subprocess": bool(opts.get("--grant-subprocess")), "native": False, "files": [os.path.realpath(d) for d in opts.get("--grant-files", [])]}
    for name, value in order:
        try:
            if name == "--sample":
                doc = service.new("sample", "metric")
                build_sample(doc, value.lower())
            elif name == "--new":
                doc = service.new("", "metric")
            elif name in ("--script", "--script-file", "--lisp-file", "--python-macro", "--command"):
                if doc is None:
                    doc = service.active() or service.new("", "")
                if name == "--script":
                    r = ops.run_script_text(doc, value.replace("\\n", "\n"))
                elif name == "--script-file":
                    if not os.path.isfile(value):
                        raise Failed('Cannot find the script file "%s".' % value)
                    with open(value, "rb") as fh:
                        r = ops.run_script_text(doc, fh.read().decode("utf-8-sig", "replace"))
                elif name == "--lisp-file":
                    r = run_lisp(doc, value)
                elif name == "--python-macro":
                    res = run_python(value, doc, [], grants)
                    if res["stdout"]:
                        sys.stdout.write(res["stdout"])
                    if res["stderr"]:
                        err(res["stderr"].rstrip("\n"))
                    if not res["ok"]:
                        raise Failed("The macro %s ended with exit status %s%s." % (os.path.basename(value), res["exit"], " (timed out)" if res["timedOut"] else ""))
                    r = {"ok": True}
                else:
                    cid, brace, rest = value.partition("{")
                    cid = cid.strip()
                    if not cid:
                        raise Usage('A command step is "id {json}".')
                    try:
                        args = json.loads("{" + rest) if brace else {}
                    except ValueError:
                        raise Usage("The parameters of %s are not valid JSON." % cid)
                    r = ops.execute(doc, cid, substitute(args, handle))
                    if r["ok"]:
                        sys.stdout.write(json.dumps(r.get("result", {}), separators=(",", ":")) + "\n") if r.get("result") is not None else None
                        found = last_handle_of(r.get("result"))
                        if found is not None:
                            handle = found
                if not r.get("ok", True):
                    raise Failed(r.get("error") or "The step failed.")
        except Failed as exc:
            err("step %s failed: %s" % (name, exc))
            failed = True
            break
    if doc is None:
        raise Usage("run needs a drawing: give a file, --sample or --new.")
    if not failed and opts.get("--save"):
        try:
            result = do_convert(doc, opts["--save"], {})
            err("wrote %s" % result["path"])
        except (Failed, Usage) as exc:
            err(str(exc))
            failed = True
    if not failed and opts.get("--export"):
        try:
            result = do_convert(doc, opts["--export"], opts)
            err("wrote %s" % result["path"])
        except (Failed, Usage) as exc:
            err(str(exc))
            failed = True
    return EXIT_FAILED if failed else EXIT_OK


def cmd_mcp(argv: list) -> int:
    pos, opts = parse(argv, {"--connect": (1, False), "--lazy": (0, False), "--launch": (0, False), "--tools": (1, False), "--settings-dir": (1, False)})
    settings_dir(opts)
    if pos:
        raise Usage("mcp takes no positional arguments.")
    if opts.get("--launch"):
        raise Usage("--launch is not supported; start FormCAD, then connect.")
    tools = opts.get("--tools", "all")
    if tools not in ("all", "core"):
        raise Usage("--tools is all or core.")
    from app.automation import stdio

    if "--connect" in opts:
        if not opts["--connect"]:
            raise Usage("--connect needs HOST:PORT or auto; it never falls back to a headless drawing.")
        if opts["--connect"] != "auto":
            import urllib.parse

            given = opts["--connect"]
            host = (urllib.parse.urlsplit(given if "://" in given else "//" + given).hostname or "").lower()
            if host not in ("127.0.0.1", "localhost", "::1"):
                raise Usage("--connect accepts only 127.0.0.1, localhost or ::1; the session token is never sent to another computer.")
        return stdio.serve_bridge(opts["--connect"])
    headless()
    return stdio.serve_headless(tools)


def cmd_perf(argv: list) -> int:
    pos, opts = parse(argv, {"--settings-dir": (1, False)})
    settings_dir(opts)
    if len(pos) > 1:
        raise Usage("perf takes a count or a file.")
    headless()
    from app import display
    from app.doc.entities import Line
    from app.doc.service import service

    rows = []
    t0 = time.perf_counter()
    if pos and not pos[0].isdigit():
        doc = open_any(pos[0])
        label = os.path.basename(pos[0])
    else:
        n = max(1, min(int(pos[0]) if pos else 200000, 20000000))
        doc = service.new("perf", "")
        for k in range(n):
            doc.drawing.add_entity(Line(start=[k % 1000, k // 1000, 0.0], end=[k % 1000 + 0.5, k // 1000 + 0.5, 0.0]), "model")
        label = "%d synthetic lines" % n
    rows.append(("build", time.perf_counter() - t0))
    t0 = time.perf_counter()
    payload = display.build(doc, None, "model")
    rows.append(("display list (%d bytes)" % len(payload), time.perf_counter() - t0))
    t0 = time.perf_counter()
    doc.drawing.extents("model")
    rows.append(("extents", time.perf_counter() - t0))
    sys.stdout.write("%s\n" % label)
    for name, secs in rows:
        sys.stdout.write("%-34s %9.3f s\n" % (name, secs))
    return EXIT_OK


def cmd_plugin(argv: list) -> int:
    from app.automation import plugins

    if not argv or argv[0] not in ("seal", "list"):
        raise Usage("plugin takes seal DIR or list.")
    if argv[0] == "list":
        parse(argv[1:], {"--settings-dir": (1, False)})
        out({"plugins": [{k: v for k, v in i.items() if k in ("id", "name", "version", "state", "tier", "problems", "commands")} for i in plugins.discover()]})
        return EXIT_OK
    if len(argv) != 2:
        raise Usage("plugin seal takes one folder.")
    try:
        data = plugins.seal(argv[1])
    except plugins.PluginError as exc:
        raise Failed(str(exc))
    out({"id": data.get("id"), "files": data["files"]})
    return EXIT_OK


def cmd_macro(argv: list) -> int:
    if argv and argv[0] == "--host":
        return host_macro(argv[1:])
    if argv and argv[0] == "list":
        from app.automation import macros

        out({"macros": macros.listing()})
        return EXIT_OK
    raise Usage("macro takes list.")


def host_macro(argv: list) -> int:
    import runpy

    base = getattr(sys, "_MEIPASS", None)
    sdk = os.path.join(base, "app", "data", "sdk") if base else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sdk")
    sys.argv = [os.path.join(sdk, "_host.py")] + argv
    sys.path.insert(0, sdk)
    ns = runpy.run_path(os.path.join(sdk, "_host.py"), run_name="formcad_host")
    return int(ns["main"]() or 0)


COMMANDS = {"info": cmd_info, "convert": cmd_convert, "run": cmd_run, "commands": cmd_commands, "mcp": cmd_mcp, "perf": cmd_perf, "sample": cmd_sample, "plugin": cmd_plugin, "macro": cmd_macro}


def main(argv: list) -> int:
    if not argv or argv[0] in ("--help", "-h", "help"):
        sys.stdout.write(HELP)
        return EXIT_OK if argv else EXIT_USAGE
    handler = COMMANDS.get(argv[0])
    if handler is None:
        err("Unknown command %s. Run formcad-engine --help." % argv[0])
        return EXIT_USAGE
    try:
        if argv[0] != "mcp":
            os.environ.setdefault("FORMCAD_HEADLESS", "1")
        return handler(argv[1:])
    except Usage as exc:
        err("formcad-engine %s: %s" % (argv[0], exc))
        return EXIT_USAGE
    except Failed as exc:
        err("formcad-engine %s: %s" % (argv[0], exc))
        return EXIT_FAILED
    except KeyboardInterrupt:
        return 130
