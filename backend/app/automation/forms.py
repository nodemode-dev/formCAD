import dis
import re
import types

from app.cmd import barred, registry

POINT = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3, "description": "A point as [x, y] or [x, y, z]."}
HANDLES = {"type": "array", "items": {"type": "integer"}, "description": "Object handles; the current selection is used when omitted."}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}
STR = {"type": "string"}

CURATED = {
    "line": ({"points": {"type": "array", "items": POINT, "minItems": 2, "description": "Two or more points; each consecutive pair becomes a line."}, "closed": BOOL}, ["points"]),
    "circle": ({"center": POINT, "radius": NUM, "diameter": NUM, "points": {"type": "array", "items": POINT, "minItems": 2, "maxItems": 3, "description": "Two points (diameter ends) or three points on the circle."}}, []),
    "arc": ({"points": {"type": "array", "items": POINT, "minItems": 3, "maxItems": 3, "description": "Start, a point on the arc, and end."}}, ["points"]),
    "rectang": ({"p1": POINT, "p2": POINT, "dimensions": {"type": "array", "items": NUM, "minItems": 2, "maxItems": 2}, "rotation": NUM, "center": BOOL, "fillet": NUM}, ["p1"]),
    "pline": ({"vertices": {"type": "array", "items": {}, "minItems": 2, "description": "Points, or objects with point, bulge, startWidth, endWidth."}, "closed": BOOL, "width": NUM}, ["vertices"]),
    "polygon": ({"sides": {"type": "integer", "minimum": 3, "maximum": 1024}, "center": POINT, "radius": NUM, "inscribed": BOOL, "angle": NUM, "edge": {"type": "array", "items": POINT, "minItems": 2, "maxItems": 2}}, []),
    "move": ({"handles": HANDLES, "delta": POINT, "from": POINT, "to": POINT}, []),
    "copy": ({"handles": HANDLES, "delta": POINT, "from": POINT, "to": POINT, "count": {"type": "integer", "minimum": 1}}, []),
    "erase": ({"handles": HANDLES, "all": BOOL}, []),
    "rotate": ({"handles": HANDLES, "base": POINT, "angle": {"type": "number", "description": "Degrees, counter-clockwise."}, "copy": BOOL}, ["base"]),
    "scale": ({"handles": HANDLES, "base": POINT, "factor": NUM, "copy": BOOL}, ["base"]),
    "mirror": ({"handles": HANDLES, "p1": POINT, "p2": POINT, "erase": BOOL}, ["p1", "p2"]),
    "offset": ({"handle": {"type": "integer"}, "distance": NUM, "through": POINT, "side": POINT, "erase": BOOL, "layer": STR}, ["handle"]),
    "zoom": ({"mode": {"type": "string", "description": "extents, all, window, previous, scale"}, "p1": POINT, "p2": POINT, "factor": NUM}, []),
    "text": ({"point": POINT, "height": NUM, "rotation": NUM, "text": STR, "style": STR, "justify": STR}, ["point", "text"]),
    "mtext": ({"point": POINT, "text": STR, "contents": STR}, ["point"]),
    "setvar": ({"name": STR, "value": {}}, ["name"]),
}

READ_ONLY_NAMES = {"id", "dist", "area", "list", "measuregeom", "cal", "find", "status", "time", "dimstyle.list", "hatch.patterns", "groups.list", "blocks.list", "layer.list", "layout.list", "style.list", "viewport.list", "dynblock.read", "pan", "zoom", "regen", "regenall", "redraw", "preview", "vaultlog", "vaultdiff", "vaultwhereused", "vaultverify"}
ADDITIVE_GROUPS = {"draw", "view", "text", "inquiry", "settings", "script", "macro", "file"}
DESTRUCTIVE_NAMES = {"erase", "purge", "-purge", "wblock", "-wblock", "saveas", "export", "explode", "laydel", "layer.delete", "layer.merge", "laymrg", "break", "trim", "extend", "oops", "undo", "redo", "layout.delete", "style.delete"}


def _scan(code, names, found, seen):
    ins = list(dis.get_instructions(code))
    for i, op in enumerate(ins):
        arg = op.argval
        holds = op.opname.startswith("LOAD_FAST") and ("args" in arg if isinstance(arg, tuple) else arg == "args")
        if holds:
            nxt = ins[i + 1 : i + 4]
            if nxt and nxt[0].opname == "LOAD_CONST" and isinstance(nxt[0].argval, str):
                found.add(nxt[0].argval)
            elif nxt and nxt[0].opname in ("LOAD_ATTR", "LOAD_METHOD") and nxt[0].argval in ("get", "pop", "setdefault") and len(nxt) > 1 and nxt[1].opname == "LOAD_CONST" and isinstance(nxt[1].argval, str):
                found.add(nxt[1].argval)
        if op.opname == "LOAD_CONST" and isinstance(arg, str) and i + 2 < len(ins):
            second = ins[i + 1]
            if second.opname.startswith("LOAD_FAST") and ("args" in second.argval if isinstance(second.argval, tuple) else second.argval == "args") and ins[i + 2].opname == "CONTAINS_OP":
                found.add(arg)
        if op.opname == "LOAD_GLOBAL":
            names.add(op.argval)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            _scan(const, names, found, seen)


def _args_of(fn, depth=0) -> set:
    found: set = set()
    code = getattr(fn, "__code__", None)
    if code is None:
        return found
    names: set = set()
    _scan(code, names, found, set())
    if "targets" in names:
        found.update(("handles", "handle"))
    if depth < 2:
        env = getattr(fn, "__globals__", {})
        for name in names:
            helper = env.get(name)
            if isinstance(helper, types.FunctionType) and helper is not fn and "args" in helper.__code__.co_varnames[: helper.__code__.co_argcount]:
                found |= _args_of(helper, depth + 1)
    return found


def _kind_of(spec) -> str:
    if spec.name in DESTRUCTIVE_NAMES:
        return "destructive"
    if spec.name in READ_ONLY_NAMES or spec.name.endswith((".list", ".read", ".measure")):
        return "read"
    if spec.group in ADDITIVE_GROUPS:
        return "additive"
    return "destructive"


def tool_name(command: str) -> str:
    return "cmd_" + re.sub(r"[^A-Za-z0-9_]", "_", command)


def old_tool_name(command: str) -> str:
    return "cmd_" + command


def command_of(tool: str) -> str:
    if not tool.startswith("cmd_"):
        return ""
    registry.load_modules()
    rest = tool[4:]
    if rest in registry.COMMANDS:
        return rest
    for name in registry.COMMANDS:
        if tool_name(name) == tool:
            return name
    return ""


def schema_for(spec) -> dict:
    curated = CURATED.get(spec.name)
    props: dict = {"document": {"type": "string", "description": "Document id; the active document when omitted."}}
    if curated is not None:
        props.update(curated[0])
        out = {"type": "object", "properties": props, "additionalProperties": False}
        if curated[1]:
            out["required"] = list(curated[1])
        return out
    for key in sorted(_args_of(spec.execute)):
        if key != "document":
            props[key] = {}
    props["inputs"] = {"type": "array", "items": {"type": ["string", "number"]}, "description": "Typed prompt answers, run in order, instead of the named parameters."}
    return {"type": "object", "properties": props, "additionalProperties": True}


def command_tools() -> list:
    registry.load_modules()
    tools = []
    for spec in sorted(registry.COMMANDS.values(), key=lambda s: s.name):
        if spec.execute is None or spec.name in barred.AGENT_BARRED:
            continue
        kind = _kind_of(spec)
        title = spec.label or spec.name.title()
        text = spec.description or title
        tools.append(
            {
                "name": tool_name(spec.name),
                "title": title,
                "description": "%s (command %s, programmatic form; no prompts or dialogs.)" % (text.rstrip("."), spec.name.upper()),
                "inputSchema": schema_for(spec),
                "annotations": {"readOnlyHint": kind == "read", "destructiveHint": kind == "destructive", "idempotentHint": kind == "read", "openWorldHint": False},
            }
        )
    return tools


def validate(value, schema, path="arguments") -> str:
    if not isinstance(schema, dict) or not schema:
        return ""
    want = schema.get("type")
    if want is not None:
        kinds = want if isinstance(want, list) else [want]
        if not any(_is(value, k) for k in kinds):
            return "%s must be %s." % (path, " or ".join(kinds))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return "%s is missing the required field %s." % (path, key)
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                bad = validate(item, props[key], path + "." + key)
                if bad:
                    return bad
            elif schema.get("additionalProperties") is False:
                return "%s has the unknown field %s." % (path, key)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return "%s needs at least %d items." % (path, schema["minItems"])
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return "%s takes at most %d items." % (path, schema["maxItems"])
        for n, item in enumerate(value):
            bad = validate(item, schema.get("items", {}), "%s[%d]" % (path, n))
            if bad:
                return bad
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return "%s must be at least %s." % (path, schema["minimum"])
        if "maximum" in schema and value > schema["maximum"]:
            return "%s must be at most %s." % (path, schema["maximum"])
    if "enum" in schema and value not in schema["enum"]:
        return "%s must be one of %s." % (path, ", ".join(map(str, schema["enum"])))
    return ""


def _is(value, kind) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool) or (isinstance(value, float) and value.is_integer())
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "null":
        return value is None
    return True
