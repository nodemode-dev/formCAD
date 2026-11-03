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
    "FormCAD is a 2D drafting application. Open or create a drawing, then either type a command line as a person would "
    "(formcad_command_line), run one command by name with parameters (formcad_execute or a cmd_* tool), or run a multi-line "
    "script. Inspect with formcad_inspect and formcad_query_entities, look at the result with formcad_render, and export with "
    "formcad_export. Every drawing is addressed by its id; omit it to use the active drawing. Edits are undoable (formcad_undo)."
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


FIXED = [
    ("formcad_command_line", "Type one line at the command prompt exactly as a person would: command names or aliases, points such as 10,20 or @5<45, distances, keywords. Spaces act as Enter, so a whole command with its answers fits one call. Returns the new prompt, output lines and an error field when the line was refused.", _obj({"text": {"type": "string"}, "document": DOC}, ["text"]), _ann(destructive=True), t_command_line),
    ("formcad_script", "Run a multi-line script in the .scr style: one input per line, a blank line is Enter.", _obj({"text": {"type": "string"}, "document": DOC}, ["text"]), _ann(destructive=True), t_script),
    ("formcad_execute", "Run any command by id with a JSON parameter object and no prompts or dialogs, for example command line with args {points:[[0,0],[10,5]]}. Use formcad_list_commands to find ids.", _obj({"command": {"type": "string"}, "args": {"type": "object"}, "document": DOC}, ["command"]), _ann(destructive=True), t_execute),
    ("formcad_list_commands", "List the command catalogue: id, label, menu path, aliases and whether a programmatic form exists, with an optional substring filter.", _obj({"filter": {"type": "string"}, "programmatic_only": {"type": "boolean"}}), _ann(read=True), t_list_commands),
    ("formcad_list_documents", "List the open drawings and which one is active.", _obj({}), _ann(read=True), t_list_documents),
    ("formcad_new_document", "Create a new empty drawing and make it active.", _obj({"name": {"type": "string"}, "template": {"type": "string"}}), _ann(), t_new_document),
    ("formcad_open_document", "Open a .fcad, .dxf, .dwg, .dwt or .svg file by path.", _obj({"path": {"type": "string"}}, ["path"]), _ann(), t_open_document),
    ("formcad_save_document", "Save a drawing. Without a path it saves in place; a .dxf or .fcad path saves as.", _obj({"path": {"type": "string"}, "document": DOC}), _ann(destructive=True), t_save_document),
    ("formcad_close_document", "Close a drawing; refused when it has unsaved changes unless force is true.", _obj({"force": {"type": "boolean"}, "document": DOC}), _ann(destructive=True), t_close_document),
    ("formcad_inspect", "Summarise a drawing: object counts by kind, layers, blocks, layouts, extents, selection.", _obj({"document": DOC}), _ann(read=True), t_inspect),
    ("formcad_query_entities", "Query objects with handles and geometry, filtered by kind, layer, selection and a window (crossing by default). Does not change the drawing or selection.", _obj({"kind": {"type": "string", "description": "One kind or a comma list, such as line,circle."}, "layer": {"type": "string"}, "selected": {"type": "boolean"}, "window": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, "crossing": {"type": "boolean"}, "handle": {"type": "integer"}, "geometry": {"type": "boolean"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 5000}, "document": DOC}), _ann(read=True), t_query),
    ("formcad_find_text", "Read text and multiline text with position, height, rotation, style and layer; filter by substring and layer.", _obj({"contains": {"type": "string"}, "layer": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}, "document": DOC}), _ann(read=True), t_find_text),
    ("formcad_render", "Render the drawing (or a model-space window) to a PNG image.", _obj({"window": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, "size": {"type": "integer", "minimum": 200, "maximum": 4000}, "document": DOC}), _ann(read=True), t_render),
    ("formcad_get_selection", "Return the handles of the current selection.", _obj({"document": DOC}), _ann(read=True), t_selection),
    ("formcad_select", "Set, add to or remove from the selection by handles.", _obj({"handles": {"type": "array", "items": {"type": "integer"}}, "mode": {"type": "string", "enum": ["set", "add", "remove"]}, "document": DOC}, ["handles"]), _ann(idem=True), t_select),
    ("formcad_cancel", "Press Escape: cancel the running command or clear the selection.", _obj({"document": DOC}), _ann(idem=True), t_cancel),
    ("formcad_undo", "Undo steps.", _obj({"steps": {"type": "integer", "minimum": 1}, "document": DOC}), _ann(destructive=True), t_undo),
    ("formcad_redo", "Redo steps.", _obj({"steps": {"type": "integer", "minimum": 1}, "document": DOC}), _ann(), t_redo),
    ("formcad_export", "Export to a file chosen by its extension: .pdf, .png, .svg, .dxf (optionally a DXF version such as R2018) or .dwg.", _obj({"path": {"type": "string"}, "version": {"type": "string"}, "window": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, "layout": {"type": "string"}, "dpi": {"type": "number"}, "paper": {"type": "string"}, "document": DOC}, ["path"]), _ann(destructive=True), t_export),
    ("formcad_display_list", "Summarise the display list the canvas draws (counts, size); include=true embeds a bounded slice of the JSON.", _obj({"space": {"type": "string"}, "include": {"type": "boolean"}, "max_chars": {"type": "integer"}, "document": DOC}), _ann(read=True), t_display),
    ("formcad_get_variable", "Read a system variable.", _obj({"name": {"type": "string"}, "document": DOC}, ["name"]), _ann(read=True), t_get_variable),
    ("formcad_set_variable", "Set a system variable.", _obj({"name": {"type": "string"}, "value": {}, "document": DOC}, ["name", "value"]), _ann(destructive=True), t_set_variable),
    ("formcad_graph_run", "Solve a node graph without the interface: a .graph file path or an inline definition, named inputs (graph widgets with a nickname) and the named outputs it returns as data trees. With bake_path the geometry is baked into the base document (doc_path, or a new one) and saved as .fcad.", _obj({"graph_path": {"type": "string"}, "graph": {"type": "object"}, "inputs": {"type": "object"}, "doc_path": {"type": "string"}, "bake_path": {"type": "string"}, "seed": {"type": "integer"}, "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 3600}, "strict": {"type": "boolean"}}), _ann(destructive=True), t_graph_run),
]

_tools_cache: list | None = None
_lock = threading.Lock()


def reset_tools() -> None:
    global _tools_cache
    with _lock:
        _tools_cache = None


def tool_list(mode: str = "all") -> list:
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
    def __init__(self, mode: str = "all"):
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
        tool = next((t for t in tool_list(self.mode) if t["name"] == name), None)
        if tool is None:
            raise RpcError(INVALID_PARAMS, "Unknown tool: %s." % name)
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
