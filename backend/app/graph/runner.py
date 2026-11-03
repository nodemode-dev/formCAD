import copy
import hashlib
import json
import os
import re
import threading
import time

from app.graph import model, registry, sdk, solver
from app.graph import tree as T
from app.graph import values as gv

SCHEMA = "formcad.graph-io/1"
OUTPUT = "io.output"
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_NODES = model.MAX_NODES
DEFAULT_TIMEOUT = 60.0
MAX_TIMEOUT = 3600.0
AGENT_TIMEOUT = 60.0
MAX_FILE = 32 * 1024 * 1024
SLOTS = threading.BoundedSemaphore(2)
EXIT_OK, EXIT_ERRORS, EXIT_USAGE, EXIT_MISSING, EXIT_TIMEOUT, EXIT_CANCELLED = 0, 1, 2, 3, 4, 5


class RunError(Exception):
    def __init__(self, message: str, code: str = "usage", extra=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}

    @property
    def exit_code(self) -> int:
        return {"missing": EXIT_MISSING, "timeout": EXIT_TIMEOUT, "cancelled": EXIT_CANCELLED}.get(self.code, EXIT_USAGE)


def output_run(ctx, trees):
    return {"value": trees["value"]}


def register_nodes() -> None:
    sdk.register(sdk.NodeType(id=OUTPUT, guid="8d1f5b3a-6c27-4e90-b4a8-5e2d7c9a0f13", name="Graph Output", nick="Out", category="Params", group="Output", inputs=[sdk.Port("value", "any", "tree", optional=True, description="The data the headless runner returns under this node's name.")], outputs=[sdk.Port("value", "any", "tree")], run=output_run, settings={"name": ""}, description="Marks data as a named result of the graph, so the headless runner and the run route can return it."))


register_nodes()

WIDGETS = {"input.slider": ("value", "number"), "input.toggle": ("value", "boolean"), "input.panel": ("text", "any"), "input.value_list": ("", "any")}


def name_of(n) -> str:
    return str(n.nickname or "").strip()


def output_name(n) -> str:
    return str(n.settings.get("name") or n.nickname or "").strip()


def entry_of(n) -> dict:
    port, kind = WIDGETS[n.type]
    s = n.settings
    if n.type == "input.slider":
        kind = "integer" if s.get("integer") else "number"
    out = {"name": name_of(n), "node": n.id, "type": kind, "widget": n.type}
    if n.type == "input.slider":
        out.update({"min": s.get("min"), "max": s.get("max"), "step": s.get("step"), "default": stored_value(n, port)})
    elif n.type == "input.toggle":
        out["default"] = bool(stored_value(n, port))
    elif n.type == "input.value_list":
        out["choices"] = [{"name": str(e.get("name", "")), "value": e.get("value")} for e in (s.get("items") or []) if isinstance(e, dict)]
        out["default"] = s.get("selected", 0)
    else:
        out["default"] = stored_value(n, port, True)
    return out


def stored_value(n, port: str, many: bool = False):
    p = n.port(port, "in")
    tree = solver.decode_persistent(p) if p is not None else None
    if tree is None or tree.count == 0:
        return [] if many else None
    flat = tree.flat_items()
    return flat if many else (flat[0] if flat else None)


def describe(g) -> dict:
    ins, outs = [], []
    seen = {}
    for n in g.nodes.values():
        if n.type in WIDGETS and name_of(n):
            nm = name_of(n)
            if not NAME_RE.match(nm):
                raise RunError("The input name %r must start with a letter or underscore and use letters, digits and underscores." % nm, "schema")
            if nm in seen:
                raise RunError("The input name %s is used by two nodes." % nm, "schema")
            seen[nm] = n.id
            ins.append(entry_of(n))
        elif n.type == OUTPUT:
            nm = output_name(n)
            if not nm:
                continue
            if not NAME_RE.match(nm):
                raise RunError("The output name %r must start with a letter or underscore and use letters, digits and underscores." % nm, "schema")
            if any(o["name"] == nm for o in outs):
                raise RunError("The output name %s is used by two nodes." % nm, "schema")
            outs.append({"name": nm, "node": n.id})
    return {"inputs": ins, "outputs": outs}


def load_graph(defn: dict):
    if not isinstance(defn, dict):
        raise RunError("A graph is a JSON object.", "schema")
    try:
        g = model.Graph.from_definition(copy.deepcopy(defn))
    except (model.GraphError, TypeError, ValueError, OverflowError, RecursionError) as err:
        raise RunError(str(err) if isinstance(err, model.GraphError) else "The graph holds a value of the wrong type or nests too deeply.", "schema")
    g.id = g.id or "run"
    return g


def read_graph_file(path: str) -> dict:
    full = os.path.abspath(os.path.expanduser(str(path or "")))
    if os.path.splitext(full)[1].lower() != ".graph":
        raise RunError("A graph file ends in .graph.", "usage")
    if not os.path.isfile(full):
        raise RunError("Cannot find the graph file %s." % full, "usage")
    if os.path.getsize(full) > MAX_FILE:
        raise RunError("That graph file is larger than %d MB." % (MAX_FILE // (1024 * 1024)), "usage")
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as err:
        raise RunError("That file is not readable graph JSON: %s" % err, "schema")
    if not isinstance(data, dict) or data.get("format") != model.FORMAT:
        raise RunError("That file is not a formCAD graph file.", "schema")
    return data


def as_tree_map(value) -> dict:
    if isinstance(value, dict):
        if "tree" in value and isinstance(value["tree"], dict):
            return value["tree"]
        if value and all(isinstance(k, str) and k.startswith("{") for k in value):
            return value
        raise RunError("A tree input is an object keyed by path such as {\"{0}\": [1, 2]}.", "usage")
    if isinstance(value, (list, tuple)):
        return {"{0}": list(value)}
    return {"{0}": [value]}


def missing_types(g) -> list:
    return [{"type": n.type, "library": n.library} for n in g.nodes.values() if n.missing]


def apply_inputs(g, inputs: dict) -> None:
    info = {e["name"]: e for e in describe(g)["inputs"]}
    for name, raw in (inputs or {}).items():
        e = info.get(name)
        if e is None:
            raise RunError("The graph has no input named %s. Inputs: %s." % (name, ", ".join(sorted(info)) or "none"), "usage")
        n = g.nodes[e["node"]]
        if n.type == "input.value_list":
            n.settings["selected"] = choose(e, raw)
            continue
        port, kind = WIDGETS[n.type]
        if n.type == "input.slider" and isinstance(raw, (list, dict)) and not (isinstance(raw, list) and len(raw) == 1):
            raise RunError("The input %s is one number." % name, "usage")
        tmap = as_tree_map(raw)
        try:
            tree = T.from_map(tmap, None if n.type == "input.panel" else e["type"] if e["type"] in ("number", "integer", "boolean") else None)
        except (T.TreeError, ValueError, TypeError) as err:
            raise RunError("The input %s cannot be read: %s" % (name, err), "usage")
        if n.type == "input.toggle":
            tree = T.DataTree({p: [bool(v) for v in b] for p, b in tree.items()})
        p = n.port(port, "in")
        p.persistent = solver.encode_persistent(tree, "any" if n.type == "input.panel" else "boolean" if n.type == "input.toggle" else "number")
        g.expire(n.id)


def choose(entry: dict, raw):
    picks = raw if isinstance(raw, list) else [raw]
    out = []
    for item in picks:
        hit = None
        for i, c in enumerate(entry.get("choices") or []):
            if item == c["name"] or item == c["value"] or (isinstance(item, int) and not isinstance(item, bool) and item == i):
                hit = i
                break
        if hit is None:
            names = ", ".join(c["name"] for c in entry.get("choices") or [])
            raise RunError("The input %s has no choice %r. Choices: %s." % (entry["name"], item, names), "usage")
        out.append(hit)
    return out[0] if len(out) == 1 else out


def parse_text(entry: dict, text: str):
    s = str(text).strip()
    if s.startswith("@"):
        path = os.path.abspath(os.path.expanduser(s[1:]))
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_FILE:
            raise RunError("Cannot read the input file %s." % path, "usage")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as err:
            raise RunError("The input file %s is not JSON: %s" % (path, err), "usage")
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except ValueError as err:
            raise RunError("The value of %s is not valid JSON: %s" % (entry["name"], err), "usage")
    kind = entry["type"]
    if entry["widget"] == "input.value_list":
        parts = [p.strip() for p in s.split(",")] if "," in s and not any(s == c["name"] for c in entry.get("choices") or []) else [s]
        return [int(p) if p.lstrip("-").isdigit() and not any(p == c["name"] for c in entry.get("choices") or []) else p for p in parts]
    if entry["widget"] == "input.panel":
        parts = [p.strip() for p in s.split(",")]
        return [number_or_text(p) for p in parts]
    if kind == "boolean":
        low = s.lower()
        if low not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            raise RunError("The input %s is true or false, got %r." % (entry["name"], s), "usage")
        return low in ("true", "1", "yes", "on")
    try:
        v = float(s)
    except ValueError:
        raise RunError("The input %s is a number, got %r." % (entry["name"], s), "usage")
    return int(v) if kind == "integer" and v == int(v) else v


def number_or_text(s: str):
    try:
        v = float(s)
    except ValueError:
        return s
    return int(v) if v == int(v) and "." not in s and "e" not in s.lower() else v


def encode_item(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return gv.to_wire(v, gv.kind_of(v))


def encode_tree(tree) -> dict:
    kinds = []
    for _, items in tree.items():
        for v in items:
            k = gv.kind_of(v)
            if v is not None and k not in kinds:
                kinds.append(k)
    kind = kinds[0] if len(kinds) == 1 else ("any" if kinds else "any")
    return {"type": kind, "tree": {str(p): [encode_item(v) for v in b] for p, b in tree.items()}}


def ancestors(g, ids) -> set:
    pred = {nid: [] for nid in g.nodes}
    for w in g.wires.values():
        if w.disabled or w.src not in g.ports or w.dst not in g.ports:
            continue
        pred[g.ports[w.dst][0].id].append(g.ports[w.src][0].id)
    seen = set()
    stack = list(ids)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(pred.get(cur, ()))
    return seen


def messages_of(g) -> list:
    out = []
    for nid, n in g.nodes.items():
        for m in n.messages:
            if m["level"] in ("warning", "error"):
                out.append({"node": nid, "level": m["level"], "code": m.get("code", ""), "text": m.get("text", ""), "port": m.get("port", "")})
    return out


def solve_private(g, doc=None, inputs=None, seed=None, timeout: float = DEFAULT_TIMEOUT, cancel=None):
    from app.core import guard

    timeout = max(0.1, min(float(timeout or DEFAULT_TIMEOUT), AGENT_TIMEOUT if guard.CALLER.get() else MAX_TIMEOUT))
    end = time.monotonic() + timeout
    state = {"timed_out": False, "cancelled": False}

    def stop():
        if cancel is not None and cancel():
            state["cancelled"] = True
            return True
        if time.monotonic() > end:
            state["timed_out"] = True
            return True
        return False

    if seed is not None:
        g.settings["seed"] = int(seed)
    for n in g.nodes.values():
        if n.missing:
            raise RunError("This graph needs node types that are not installed: %s." % ", ".join(sorted({n.type for n in g.nodes.values() if n.missing})), "missing", {"missing": missing_types(g)})
    rep = solver.solve(g, doc, True, stop, None, inputs, None, True)
    if rep.aborted:
        if state["timed_out"]:
            raise RunError("The graph did not finish within %g seconds." % timeout, "timeout")
        raise RunError("The run was cancelled.", "cancelled")
    return rep


def collect(g, rep, started: float, strict: bool = False) -> dict:
    spec = describe(g)
    outputs = {}
    for o in spec["outputs"]:
        n = g.nodes[o["node"]]
        outputs[o["name"]] = encode_tree(n.outputs.get("value") or T.DataTree())
    msgs = messages_of(g)
    out_nodes = [o["node"] for o in spec["outputs"]]
    live = ancestors(g, out_nodes) if out_nodes else set(g.nodes)
    blocking = [m for m in msgs if m["level"] == "error" and m["node"] in live]
    ok = not blocking and not (strict and any(m["level"] == "warning" and m["node"] in live for m in msgs))
    canon = json.dumps(outputs, sort_keys=True, separators=(",", ":"), default=repr)
    return {"schema": SCHEMA, "ok": ok, "digest": "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest(), "outputs": outputs, "messages": msgs, "stats": {"solve_ms": round(rep.ms, 2), "nodes": len(g.nodes), "computed": len(rep.ran)}}


def run(defn: dict, inputs=None, doc=None, seed=None, timeout: float = DEFAULT_TIMEOUT, cancel=None, strict: bool = False, keep=None) -> dict:
    g = load_graph(defn)
    try:
        apply_inputs(g, inputs or {})
        t0 = time.monotonic()
        rep = solve_private(g, doc, dict(inputs or {}), seed, timeout, cancel)
        result = collect(g, rep, t0, strict)
    except RunError:
        raise
    except (T.TreeError, TypeError, ValueError, OverflowError, RecursionError) as err:
        raise RunError("The graph holds data that cannot be read: %s" % err, "schema")
    if keep is not None:
        keep.append(g)
    return result


def open_private(path: str):
    from app.doc import container
    from app.doc.document import Document
    from app.doc.service import _kind

    full = os.path.realpath(os.path.expanduser(str(path or "")))
    if os.path.splitext(full)[1].lower() != ".fcad":
        raise RunError("A document for a run is a .fcad file.", "usage")
    if not os.path.isfile(full):
        raise RunError("Cannot find the document %s." % full, "usage")
    try:
        drawing, manifest = container.load(full)
    except container.ContainerError as err:
        raise RunError(err.message, "usage")
    doc = Document(drawing, os.path.splitext(os.path.basename(full))[0], full, _kind(manifest), drawing.metric)
    doc.created = str(manifest.get("created") or doc.created)
    return doc


def new_private():
    from app.doc.document import Document
    from app.doc.model import Drawing

    drawing = Drawing(True)
    return Document(drawing, "Graph run", "", "drawing", True)


def bake_into(doc, g, options=None) -> dict:
    from app.graph import bake

    with doc.lock:
        with doc.transaction("GRAPHBAKE"):
            return bake.bake(doc, g, {"options": dict(options or {})})


def save_private(doc, path: str) -> str:
    from app.core import outputs
    from app.doc import container

    try:
        target = outputs.checked(path, (".fcad",), ".fcad")
    except outputs.OutputRefused as err:
        raise RunError(str(err), "usage")
    with doc.lock:
        doc.undo.end_group()
        return container.save(target, doc.drawing, doc.name, doc.created, False, doc.kind)


def resolve_node(g, ref: str) -> str:
    ref = str(ref or "").strip()
    if ref in g.nodes:
        return ref
    hits = [n.id for n in g.nodes.values() if ref and ref in (n.nickname, output_name(n) if n.type == OUTPUT else None)]
    if len(hits) != 1:
        raise RunError("%s names %s nodes. Use a node id or a unique nickname." % (ref or "An empty reference", "no" if not hits else "several"), "usage")
    return hits[0]


def run_files(graph_path: str, inputs=None, doc_path: str = "", bake_path: str = "", seed=None, timeout: float = DEFAULT_TIMEOUT, cancel=None, strict: bool = False, bake_options=None) -> dict:
    return run_request(read_graph_file(graph_path), inputs, doc_path, bake_path, seed, timeout, cancel, strict, bake_options)


def run_request(defn: dict, inputs=None, doc_path: str = "", bake_path: str = "", seed=None, timeout: float = DEFAULT_TIMEOUT, cancel=None, strict: bool = False, bake_options=None) -> dict:
    if bake_path:
        from app.core import outputs

        try:
            bake_path = outputs.checked(bake_path, (".fcad",), ".fcad")
        except outputs.OutputRefused as err:
            raise RunError(str(err), "usage")
    doc = None
    if doc_path or bake_path:
        doc = open_private(doc_path) if doc_path else new_private()
    g_keep: list = []
    result = run(defn, inputs, doc.drawing if doc is not None else None, seed, timeout, cancel, strict, g_keep)
    if bake_path:
        if not result["ok"]:
            raise RunError("The graph has errors, so nothing was baked.", "errors", {"result": result})
        info = bake_into(doc, g_keep[0], bake_options)
        result["bake"] = {"path": save_private(doc, bake_path), "baked": info}
    return result


def acquire() -> bool:
    return SLOTS.acquire(blocking=False)


def release() -> None:
    SLOTS.release()


def split_in(items: list) -> dict:
    out = {}
    for item in items:
        name, eq, value = str(item).partition("=")
        if not eq or not NAME_RE.match(name.strip()):
            raise RunError("An input is written name=value, got %r." % item, "usage")
        out.setdefault(name.strip(), []).append(value)
    return out


def inputs_from_text(g, pairs: dict) -> dict:
    info = {e["name"]: e for e in describe(g)["inputs"]}
    out = {}
    for name, texts in pairs.items():
        e = info.get(name)
        if e is None:
            raise RunError("The graph has no input named %s. Inputs: %s." % (name, ", ".join(sorted(info)) or "none"), "usage")
        parsed = [parse_text(e, t) for t in texts]
        if len(parsed) == 1:
            out[name] = parsed[0]
        elif all(not isinstance(p, (dict, list)) for p in parsed):
            out[name] = parsed
        else:
            raise RunError("The input %s was given more than once with structured values." % name, "usage")
    return out
