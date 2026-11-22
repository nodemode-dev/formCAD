import json
import threading

from app import __version__
from app.automation import forms, ops

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SUPPORTED = (MODERN,) + LEGACY
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
META_INFO = "io.modelcontextprotocol/serverInfo"
MAX_TEXT = 60000
SERVER_INFO = {"name": "formcad", "title": "FormCAD", "version": __version__}
INSTRUCTIONS = (
    "FormCAD is a CAD studio: 2D drafting, parametric parts with a feature tree, assemblies, drawings with views, NURBS surfaces, "
    "a node graph, CAM toolpaths and simulation studies, all in one .fcad document. Start with formcad_status: it says whether the "
    "3D kernel and the mesher are installed and which folders you may read and write. 2D drafting, meshes and the graph's non-solid "
    "nodes work without the kernel; parts, surfaces, assemblies, drawing views, STEP, IGES and 3DM need it, and a study needs the "
    "mesher. If one is missing, tell the person to use Install kernel in the status bar or Install mesher in the Studies panel; "
    "you cannot install them. "
    "To work: open or create a document, then run commands. formcad_list_commands finds a command by word; formcad_execute runs "
    "any of them by id with a JSON parameter object and no prompts, and formcad_command_line types a line as a person would. "
    "The cmd_* tools in this list are the same commands for the most common drafting steps; every other command is reached "
    "through formcad_execute, and a cmd_* name built from any command id (dots and dashes written as underscores) can also be called. "
    "Look before and after: formcad_inspect, formcad_query_entities and formcad_render. Edits are undoable with formcad_undo. "
    "Long work runs as a job: formcad_sim_start or formcad_cam_start returns a job id at once; poll formcad_job_status until its "
    "state is done, failed or cancelled, and read the result there. formcad_graph_run solves a node graph without the window. "
    "Files: a path you pass must lie inside a granted folder (formcad_status lists them and names the settings file where a person grants more); anything else is refused with the reason. "
    "Every document is addressed by its id; omit it to use the active one."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603
UNSUPPORTED_VERSION = -32022


class RpcError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


DOC = {"type": "string", "description": "Drawing id; the active drawing when omitted."}
POINT = forms.POINT


def _obj(props: dict, required=()) -> dict:
    out = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = list(required)
    return out


def _ann(read=False, destructive=False, idem=False):
    return {"readOnlyHint": read, "destructiveHint": destructive, "idempotentHint": idem or read, "openWorldHint": False}


def _text(data) -> str:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + '..."truncated"'
    return text


def _result(data, error: bool = False, extra=None) -> dict:
    out = {"content": [{"type": "text", "text": _text(data)}] + list(extra or [])}
    if isinstance(data, dict):
        out["structuredContent"] = data
    else:
        out["structuredContent"] = {"value": data}
    if error:
        out["isError"] = True
    return out


def _doc(args: dict):
    return ops.document(str(args.get("document") or ""))


def t_command_line(a):
    r = ops.type_line(_doc(a), a["text"])
    return _result(r, not r["ok"])


def t_script(a):
    r = ops.run_script_text(_doc(a), a["text"])
    return _result(r, not r["ok"])


def t_execute(a):
    r = ops.execute(_doc(a), a["command"], a.get("args") or {})
    return _result(r, not r["ok"])


def t_list_commands(a):
    items = ops.catalogue(a.get("filter", ""))
    if a.get("programmatic_only"):
        items = [i for i in items if i["programmatic"]]
    return _result({"total": len(items), "commands": [{"id": i["id"], "label": i["label"], "menu": i["menu"], "aliases": i["aliases"], "programmatic": i["programmatic"], "tool": forms.tool_name(i["id"]) if i["programmatic"] else ""} for i in items]})


def t_list_documents(a):
    from app.doc.service import service

    return _result({"documents": service.summaries(), "active": service.active_id})


def t_new_document(a):
    return _result(ops.new_doc(a.get("name", ""), a.get("template", "")))


def t_open_document(a):
    return _result(ops.open_path(a["path"]))


def t_save_document(a):
    return _result(ops.save_doc(_doc(a), a.get("path", "")))


def t_close_document(a):
    return _result(ops.close_doc(_doc(a), bool(a.get("force"))))


def t_inspect(a):
    return _result(ops.summary(_doc(a)))


def t_query(a):
    return _result(ops.query_entities(_doc(a), a.get("kind", ""), a.get("layer", ""), bool(a.get("selected")), a.get("window"), a.get("crossing", True), a.get("offset", 0), a.get("limit", 200), a.get("handle"), a.get("geometry", True)))


def t_find_text(a):
    return _result(ops.find_text(_doc(a), a.get("contains", ""), a.get("layer", ""), a.get("limit", 200)))


def t_render(a):
    shot = ops.render_b64(_doc(a), a.get("window"), a.get("size", 1200))
    info = {"mime": shot["mime"], "bytes": shot["bytes"], "window": a.get("window")}
    return _result(info, False, [{"type": "image", "data": shot["data"], "mimeType": shot["mime"]}])


def t_selection(a):
    return _result({"selection": ops.selection(_doc(a))})


def t_select(a):
    return _result({"selection": ops.select(_doc(a), a.get("handles", []), a.get("mode", "set"))})


def t_cancel(a):
    r = ops.press(_doc(a), "escape")
    return _result(r)


def t_undo(a):
    from app.routers import docs

    doc = _doc(a)
    return _result(docs._history(doc, "undo", max(1, int(a.get("steps", 1)))))


def t_redo(a):
    from app.routers import docs

    doc = _doc(a)
    return _result(docs._history(doc, "redo", max(1, int(a.get("steps", 1)))))


def t_export(a):
    return _result(ops.export(_doc(a), a["path"], a.get("version", ""), a.get("window"), "", a.get("layout", "Model"), a.get("dpi"), a.get("paper", "")))


def t_display(a):
    payload = ops.display_list(_doc(a), a.get("space", "model"))
    data = json.loads(payload)
    counts = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in data.items()} if isinstance(data, dict) else {"items": len(data)}
    out = {"bytes": len(payload), "counts": counts}
    if a.get("include"):
        out["display"] = payload[: min(int(a.get("max_chars", 20000)), MAX_TEXT // 2)]
    return _result(out)


def t_get_variable(a):
    return _result({"name": a["name"].upper(), "value": ops.variable(_doc(a), a["name"])})


def t_set_variable(a):
    return _result({"name": a["name"].upper(), "value": ops.set_variable(_doc(a), a["name"], a["value"])})


def t_graph_run(a):
    from types import SimpleNamespace

    from app.cmd import barred
    from app.graph import plugins as graph_plugins
    from app.graph import runner

    why = barred.args_refusal(None, SimpleNamespace(name="graphrun"), {k: v for k, v in a.items() if k in ("graph_path", "doc_path", "bake_path")})
    if why:
        return _result({"ok": False, "error": why}, True)
    if not runner.acquire():
        return _result({"ok": False, "error": "Too many graph runs are going. Try again shortly."}, True)
    try:
        graph_plugins.load_trusted()
        if a.get("graph") is not None:
            defn = a["graph"]
        elif a.get("graph_path"):
            defn = runner.read_graph_file(a["graph_path"])
        else:
            raise runner.RunError("Give graph (a definition) or graph_path (a .graph file).")
        result = runner.run_request(defn, a.get("inputs") or {}, a.get("doc_path", ""), a.get("bake_path", ""), a.get("seed"), float(a.get("timeout_s") or runner.DEFAULT_TIMEOUT), None, bool(a.get("strict")))
        return _result(result, not result["ok"])
    except runner.RunError as err:
        return _result({"ok": False, "error": err.message, "code": err.code}, True)
    finally:
        runner.release()


def t_status(a):
    from app.cmd import barred
    from app.services import kernel, mesher

    def part(s: dict, where: str) -> dict:
        state = "installed" if s.get("available") else "installing" if s.get("installing") else "not installed"
        out = {"state": state, "version": s.get("version"), "message": s.get("message") or ""}
        if state == "installing":
            out["progress"] = s.get("progress")
        if state == "not installed":
            out["how"] = where
        return out

    from app.doc.service import service

    seen = mesher.status()
    if not seen.get("available") and not seen.get("installing"):
        mesher.probe()
    return _result({
        "version": __version__,
        "kernel": part(kernel.status(), "A person installs it with Install kernel in the status bar of the FormCAD window."),
        "mesher": part(mesher.status(), "A person installs it with Install mesher in the Studies panel of the FormCAD window."),
        "granted_folders": barred._granted(None, "agent"),
        "folder_rule": "A path you pass must lie inside a granted folder. A person grants a folder by adding it to the agentFolders list in the settings file named here.",
        "settings_file": str(_settings_file()),
        "documents": len(service.docs),
        "active_document": service.active_id,
    })


def _settings_file():
    from app.automation import macros

    return macros.settings_path()


def _job_view(kind: str, view: dict) -> dict:
    state = view.get("state", "")
    out = {"job": view.get("job") or view.get("id"), "kind": kind, "state": state, "finished": state in ("done", "failed", "cancelled"), "message": view.get("message", "")}
    progress = view.get("progress")
    out["progress"] = progress.get("fraction", 0.0) if isinstance(progress, dict) else progress
    if kind == "sim":
        out.update({"study": view.get("study"), "phase": view.get("phase", ""), "result": view.get("result")})
    else:
        out.update({"operations": view.get("ops", []), "detail": progress if isinstance(progress, dict) else {}, "results": view.get("results", {})})
    return out


def t_sim_start(a):
    from app.sim import jobs, records, study
    from app.sim.fem import SimError

    doc = _doc(a)
    try:
        with doc.lock:
            records.need(doc.drawing, a["study"], "study")
        return _result(_job_view("sim", jobs.start(doc, a["study"], a.get("mode", "run"), True)))
    except (SimError, ValueError) as err:
        return _result({"ok": False, "error": str(err)}, True)


def t_cam_start(a):
    from app.cam import jobs
    from app.cam.limits import CamError

    doc = _doc(a)
    try:
        with doc.lock:
            ids = jobs.ops_for(doc, a.get("setup"), a.get("operations"))
        return _result(_job_view("cam", jobs.start(doc, ids, False).view()))
    except (CamError, ValueError) as err:
        return _result({"ok": False, "error": str(err)}, True)


def _find_job(job_id: str):
    from app.cam import jobs as cam_jobs
    from app.sim import jobs as sim_jobs

    with sim_jobs.LOCK:
        found = sim_jobs.JOBS.get(job_id)
    if found is not None:
        return "sim", found
    found = cam_jobs.get(job_id)
    if found is not None:
        return "cam", found
    raise ops.OpError("There is no job %s. Jobs are kept only while the engine runs." % job_id)


def t_job_status(a):
    kind, job = _find_job(a["job"])
    return _result(_job_view(kind, job.view()))


def t_job_cancel(a):
    from app.cam import jobs as cam_jobs
    from app.sim import jobs as sim_jobs

    kind, job = _find_job(a["job"])
    if kind == "sim":
        sim_jobs.cancel(job.id)
    else:
        cam_jobs.cancel(job.id)
    return _result(_job_view(kind, job.view()))


FIXED = [
    ("formcad_status", "Read what this FormCAD can do right now: its version, whether the 3D kernel and the mesher are installed (state is installed, installing or not installed, with how a person installs a missing one), the folders you may read and write, and how many documents are open. Call it first. Returns {version, kernel:{state,version,message}, mesher:{state,version,message}, granted_folders:[paths], folder_rule, settings_file, documents, active_document}.", _obj({}), _ann(read=True), t_status),
    ("formcad_sim_start", "Start a simulation study as a background job and return at once. mode run meshes and solves; mode mesh only meshes. Needs the mesher (see formcad_status). Returns {job, kind:'sim', state, finished, progress, phase, message, study, result}; poll formcad_job_status with the job id until finished is true. Example: {study:'S1'}.", _obj({"study": {"type": "string", "description": "The study id, as the sim commands and formcad_inspect list it."}, "mode": {"type": "string", "enum": ["run", "mesh"]}, "document": DOC}, ["study"]), _ann(), t_sim_start),
    ("formcad_cam_start", "Generate toolpaths as a background job and return at once: every operation of a setup, the listed operations, or all of them when neither is given. Returns {job, kind:'cam', state, finished, progress, message, operations, detail, results}; poll formcad_job_status with the job id until finished is true. Example: {setup:'Setup1'}.", _obj({"setup": {"type": "string"}, "operations": {"type": "array", "items": {"type": "string"}}, "document": DOC}), _ann(), t_cam_start),
    ("formcad_job_status", "Read one job started by formcad_sim_start or formcad_cam_start. state is queued, running, done, failed or cancelled; finished is true for the last three; progress runs from 0 to 1. A finished study carries its result summary in result; finished toolpaths carry one entry per operation in results. Does not block: call it again after a short wait while finished is false.", _obj({"job": {"type": "string"}}, ["job"]), _ann(read=True), t_job_status),
    ("formcad_job_cancel", "Stop a running job by its id. Returns the job as formcad_job_status does; a job that already finished is returned unchanged.", _obj({"job": {"type": "string"}}, ["job"]), _ann(idem=True), t_job_cancel),
    ("formcad_command_line", "Type one line at the command prompt exactly as a person would: command names or aliases, points such as 10,20 or @5<45, distances, keywords. Spaces act as Enter, so a whole command with its answers fits one call. Returns the new prompt, output lines and an error field when the line was refused.", _obj({"text": {"type": "string"}, "document": DOC}, ["text"]), _ann(destructive=True), t_command_line),
    ("formcad_script", "Run a multi-line script in the .scr style: one input per line, a blank line is Enter.", _obj({"text": {"type": "string"}, "document": DOC}, ["text"]), _ann(destructive=True), t_script),
    ("formcad_execute", "Run any command by id with a JSON parameter object and no prompts or dialogs, for example command line with args {points:[[0,0],[10,5]]}. Use formcad_list_commands to find ids.", _obj({"command": {"type": "string"}, "args": {"type": "object"}, "document": DOC}, ["command"]), _ann(destructive=True), t_execute),
    ("formcad_list_commands", "List the command catalogue: id, label, menu path, aliases and whether a programmatic form exists, with an optional substring filter.", _obj({"filter": {"type": "string"}, "programmatic_only": {"type": "boolean"}}), _ann(read=True), t_list_commands),
    ("formcad_list_documents", "List the open drawings and which one is active.", _obj({}), _ann(read=True), t_list_documents),
    ("formcad_new_document", "Create a new empty drawing and make it active.", _obj({"name": {"type": "string"}, "template": {"type": "string"}}), _ann(), t_new_document),
    ("formcad_open_document", "Open a file by path: .fcad, .dxf, .dwg, .dwt, .svg, or a model or mesh file (.step, .stp, .iges, .igs, .3dm, .stl, .obj, .3mf, .glb, .gltf, .ply; these need the kernel and come back with import notes).", _obj({"path": {"type": "string"}}, ["path"]), _ann(), t_open_document),
    ("formcad_save_document", "Save a drawing. Without a path it saves in place; a .dxf or .fcad path saves as.", _obj({"path": {"type": "string"}, "document": DOC}), _ann(destructive=True), t_save_document),
    ("formcad_close_document", "Close a drawing; refused when it has unsaved changes unless force is true.", _obj({"force": {"type": "boolean"}, "document": DOC}), _ann(destructive=True), t_close_document),
    ("formcad_inspect", "Summarise a drawing: object counts by kind, layers, blocks, layouts, extents, selection.", _obj({"document": DOC}), _ann(read=True), t_inspect),
    ("formcad_query_entities", "Query objects with handles and geometry, filtered by kind, layer, selection and a window (crossing by default). Does not change the drawing or selection.", _obj({"kind": {"type": "string", "description": "One kind or a comma list, such as line,circle."}, "layer": {"type": "string"}, "selected": {"type": "boolean"}, "window": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, "crossing": {"type": "boolean"}, "handle": {"type": "integer"}, "geometry": {"type": "boolean"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 5000}, "document": DOC}), _ann(read=True), t_query),
    ("formcad_find_text", "Read text and multiline text with position, height, rotation, style and layer; filter by substring and layer.", _obj({"contains": {"type": "string"}, "layer": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}, "document": DOC}), _ann(read=True), t_find_text),
    ("formcad_render", "Render the drawing (or a model-space window) to a PNG image.", _obj({"window": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, "size": {"type": "integer", "minimum": 200, "maximum": 4000}, "document": DOC}), _ann(read=True), t_render),
    ("formcad_get_selection", "Return the handles of the current selection.", _obj({"document": DOC}), _ann(read=True), t_selection),
    ("formcad_select", "Set, add to or remove from the selection by handles.", _obj({"handles": {"type": "array", "items": {"type": "integer"}}, "mode": {"type": "string", "enum": ["set", "add", "remove"]}, "document": DOC}, ["handles"]), _ann(idem=True), t_select),
    ("formcad_cancel", "Press Escape: cancel the running command or clear the selection.", _obj({"document": DOC}), _ann(idem=True), t_cancel),
    ("formcad_undo", "Undo the last edits of a document, one step per command that changed it (kernel features included). Returns {rev, label, labels, state}: the document's new revision number, the names of the commands taken back (labels, newest first; label is the last of them) and the command line state. Example: {steps:2} takes back the last two commands.",_obj({"steps": {"type": "integer", "minimum": 1}, "document": DOC}), _ann(destructive=True), t_undo),
    ("formcad_redo", "Redo edits that formcad_undo took back, one step each. A new edit after an undo empties what can be redone. Returns {rev, label, labels, state} as formcad_undo does, naming the commands put back. Example: {steps:1}.",_obj({"steps": {"type": "integer", "minimum": 1}, "document": DOC}), _ann(), t_redo),
    ("formcad_export", "Export to a file chosen by its extension: .pdf, .png, .svg, .dxf (optionally a DXF version such as R2018), .dwg, or a model or mesh file (.step with version ap203, ap214 or ap242, .iges, .3dm, .stl, .obj, .3mf, .glb, .ply; these need the kernel and return export notes).", _obj({"path": {"type": "string"}, "version": {"type": "string"}, "window": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, "layout": {"type": "string"}, "dpi": {"type": "number"}, "paper": {"type": "string"}, "document": DOC}, ["path"]), _ann(destructive=True), t_export),
    ("formcad_display_list", "Summarise the display list the canvas draws (counts, size); include=true embeds a bounded slice of the JSON.", _obj({"space": {"type": "string"}, "include": {"type": "boolean"}, "max_chars": {"type": "integer"}, "document": DOC}), _ann(read=True), t_display),
    ("formcad_get_variable", "Read one system variable of a document, for example LTSCALE, CLAYER, OSMODE or MEASUREMENT. The name is not case sensitive. Returns {name, value}, the name in upper case and the value as a number or text. Example: {name:'CLAYER'} returns {name:'CLAYER', value:'0'}.",_obj({"name": {"type": "string"}, "document": DOC}, ["name"]), _ann(read=True), t_get_variable),
    ("formcad_set_variable", "Set one system variable of a document. A read-only variable or a value outside its range is refused with the reason. Returns {name, value} with the value as it now stands, which may differ from what was sent when the variable rounds or clamps. Example: {name:'LTSCALE', value:2} returns {name:'LTSCALE', value:2.0}.",_obj({"name": {"type": "string"}, "value": {}, "document": DOC}, ["name", "value"]), _ann(destructive=True), t_set_variable),
    ("formcad_graph_run", "Solve a node graph without the interface: a .graph file path or an inline definition, named inputs (graph widgets with a nickname) and the named outputs it returns as data trees. With bake_path the geometry is baked into the base document (doc_path, or a new one) and saved as .fcad.", _obj({"graph_path": {"type": "string"}, "graph": {"type": "object"}, "inputs": {"type": "object"}, "doc_path": {"type": "string"}, "bake_path": {"type": "string"}, "seed": {"type": "integer"}, "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 3600}, "strict": {"type": "boolean"}}), _ann(destructive=True), t_graph_run),
]

_tools_cache: list | None = None
_lock = threading.Lock()


def reset_tools() -> None:
    global _tools_cache
    with _lock:
        _tools_cache = None


def tool_list(mode: str = "core") -> list:
    global _tools_cache
    with _lock:
        if _tools_cache is None:
            fixed = [{"name": n, "title": n.replace("formcad_", "").replace("_", " ").capitalize(), "description": d, "inputSchema": s, "annotations": a} for n, d, s, a, _ in FIXED]
            _tools_cache = sorted(fixed, key=lambda t: t["name"]) + forms.command_tools()
        tools = _tools_cache
    if mode == "core":
        return [t for t in tools if not t["name"].startswith("cmd_") or t["name"][4:] in forms.CURATED]
    return tools


RESOURCES = [
    {"uri": "formcad://drawing/summary", "name": "drawing-summary", "title": "Active drawing summary", "mimeType": "application/json"},
    {"uri": "formcad://commands", "name": "commands", "title": "Command catalogue", "mimeType": "application/json"},
]


class Server:
    def __init__(self, mode: str = "core"):
        self.mode = mode
        self.legacy = False
        self.handlers = {n: h for n, _, _, _, h in FIXED}

    def capabilities(self) -> dict:
        return {"tools": {"listChanged": False}, "resources": {"listChanged": False, "subscribe": False}}

    def meta_check(self, params: dict, era_hint: str) -> str:
        meta = params.get("_meta") if isinstance(params, dict) else None
        version = meta.get(META_VERSION) if isinstance(meta, dict) else None
        if version is None:
            if self.legacy or era_hint in LEGACY:
                return "legacy"
            raise RpcError(INVALID_PARAMS, "Missing _meta %s. Send server/discover first, or initialize for the earlier lifecycle." % META_VERSION)
        if version not in SUPPORTED:
            raise RpcError(UNSUPPORTED_VERSION, "Unsupported protocol version.", {"supported": list(SUPPORTED), "requested": version})
        if META_CAPS not in meta and version == MODERN:
            raise RpcError(INVALID_PARAMS, "Missing _meta %s." % META_CAPS)
        return "modern" if version == MODERN else "legacy"

    def initialize(self, params: dict) -> dict:
        wanted = (params or {}).get("protocolVersion")
        version = wanted if wanted in LEGACY else LEGACY[0]
        self.legacy = True
        return {"protocolVersion": version, "capabilities": self.capabilities(), "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}

    def discover(self) -> dict:
        return {"resultType": "complete", "supportedVersions": list(SUPPORTED[:1]) + list(LEGACY), "capabilities": self.capabilities(), "_meta": {META_INFO: SERVER_INFO}, "instructions": INSTRUCTIONS, "ttlMs": 60000, "cacheScope": "public"}

    def call_tool(self, params: dict) -> dict:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise RpcError(INVALID_PARAMS, "tools/call needs a tool name.")
        name = params["name"]
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "Tool arguments must be an object.")
        tool = next((t for t in tool_list("all") if t["name"] == name), None)
        if tool is None and forms.command_of(name):
            name = forms.tool_name(forms.command_of(name))
            tool = next((t for t in tool_list("all") if t["name"] == name), None)
        if tool is None:
            raise RpcError(INVALID_PARAMS, "Unknown tool: %s. formcad_list_commands finds commands by word; formcad_execute runs any of them by id." % name)
        bad = forms.validate(args, tool["inputSchema"])
        if bad:
            raise RpcError(INVALID_PARAMS, bad)
        try:
            handler = self.handlers.get(name)
            if handler is not None:
                return handler(args)
            command = forms.command_of(name)
            doc = _doc(args)
            rest = {k: v for k, v in args.items() if k != "document"}
            r = ops.execute(doc, command, rest)
            return _result(r, not r["ok"])
        except ops.OpError as err:
            return _result({"ok": False, "error": str(err)}, True)
        except RpcError:
            raise
        except Exception as err:
            return _result({"ok": False, "error": "%s: %s" % (type(err).__name__, err)}, True)

    def read_resource(self, params: dict) -> dict:
        uri = (params or {}).get("uri")
        try:
            if uri == "formcad://drawing/summary":
                body = ops.summary(ops.document(""))
            elif uri == "formcad://commands":
                body = {"commands": [{k: i[k] for k in ("id", "label", "menu", "aliases", "programmatic")} for i in ops.catalogue("")]}
            else:
                raise RpcError(INVALID_PARAMS, "Unknown resource: %s." % uri)
        except ops.OpError as err:
            raise RpcError(INVALID_PARAMS, str(err))
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(body, separators=(",", ":"))}]}

    def dispatch(self, method: str, params: dict, era: str) -> dict:
        if method == "tools/list":
            out = {"tools": tool_list(self.mode)}
            if era == "modern":
                out.update({"ttlMs": 60000, "cacheScope": "public"})
            return out
        if method == "tools/call":
            return self.call_tool(params)
        if method == "resources/list":
            out = {"resources": RESOURCES}
            if era == "modern":
                out.update({"ttlMs": 60000, "cacheScope": "private"})
            return out
        if method == "resources/templates/list":
            out = {"resourceTemplates": []}
            if era == "modern":
                out.update({"ttlMs": 60000, "cacheScope": "public"})
            return out
        if method == "resources/read":
            return self.read_resource(params)
        if method == "prompts/list":
            out = {"prompts": []}
            if era == "modern":
                out.update({"ttlMs": 60000, "cacheScope": "public"})
            return out
        raise RpcError(METHOD_NOT_FOUND, "Method not found: %s." % method)

    def handle(self, msg, era_hint: str = "") -> dict | None:
        from app.core import guard

        mark = guard.CALLER.set("agent")
        try:
            return self.handle_as_agent(msg, era_hint)
        finally:
            guard.CALLER.reset(mark)

    def handle_as_agent(self, msg, era_hint: str = "") -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Not a JSON-RPC 2.0 message."}}
        method = msg.get("method")
        has_id = "id" in msg and msg["id"] is not None
        if not isinstance(method, str):
            return None if "result" in msg or "error" in msg else {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": INVALID_REQUEST, "message": "A request needs a method."}}
        if not has_id:
            if method == "notifications/cancelled" or method.startswith("notifications/"):
                return None
            return None
        rid = msg["id"]
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                result = self.initialize(params)
            elif method == "server/discover":
                meta = params.get("_meta") if isinstance(params, dict) else None
                if isinstance(meta, dict) and META_VERSION in meta and meta[META_VERSION] not in SUPPORTED:
                    raise RpcError(UNSUPPORTED_VERSION, "Unsupported protocol version.", {"supported": list(SUPPORTED), "requested": meta[META_VERSION]})
                result = self.discover()
            elif method == "ping":
                result = {}
            else:
                era = self.meta_check(params, era_hint)
                result = self.dispatch(method, params, era)
                if era == "modern":
                    result.setdefault("resultType", "complete")
                    result.setdefault("_meta", {})[META_INFO] = SERVER_INFO
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except RpcError as err:
            error = {"code": err.code, "message": err.message}
            if err.data is not None:
                error["data"] = err.data
            return {"jsonrpc": "2.0", "id": rid, "error": error}
        except Exception as err:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": INTERNAL, "message": "%s: %s" % (type(err).__name__, err)}}

    def handle_text(self, text: str, era_hint: str = "") -> str | None:
        try:
            msg = json.loads(text)
        except ValueError:
            return json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error."}})
        if isinstance(msg, list):
            out = [r for r in (self.handle(m, era_hint) for m in msg) if r is not None]
            return json.dumps(out) if out else None
        reply = self.handle(msg, era_hint)
        return json.dumps(reply, separators=(",", ":")) if reply is not None else None
