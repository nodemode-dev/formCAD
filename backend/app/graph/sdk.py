import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

KINDS = ("any", "number", "integer", "boolean", "text", "point", "vector", "plane", "domain", "colour", "curve", "surface", "brep", "mesh", "geometry", "transform", "docref")
ACCESS = ("item", "list", "tree")
MAX_NODE_ITEMS = 2000000
MAX_TOTAL_ITEMS = 5000000
MAX_COUNT = 1000000
MATCHING = ("longest", "shortest", "cross")
LEVELS = ("blank", "remark", "warning", "error")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$|^[a-z0-9][a-z0-9_.-]*/[A-Za-z0-9_.-]+$")


class NodeMessage(Exception):
    level = "error"

    def __init__(self, message: str = "", code: str = "", port: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.port = port


class NodeWarning(NodeMessage):
    level = "warning"

    def __init__(self, message: str = "", code: str = "", port: str = "", result: Any = None, has_result: bool = False):
        super().__init__(message, code, port)
        self.result = result
        self.has_result = has_result or result is not None


class NodeError(NodeMessage):
    level = "error"


class Aborted(BaseException):
    pass


@dataclass(frozen=True)
class Port:
    name: str
    kind: str = "any"
    access: str = "item"
    default: Any = None
    optional: bool = False
    nick: str = ""
    description: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[tuple] = None
    hidden: bool = False

    @property
    def is_optional(self) -> bool:
        return self.optional or self.default is not None

    def entry(self) -> dict:
        out = {"name": self.name, "nick": self.nick or self.name, "kind": self.kind, "access": self.access, "optional": self.is_optional, "description": self.description}
        if self.default is not None:
            out["default"] = self.default
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.choices:
            out["choices"] = list(self.choices)
        if self.hidden:
            out["hidden"] = True
        return out


@dataclass
class NodeType:
    id: str
    guid: str
    name: str
    nick: str = ""
    category: str = ""
    group: str = ""
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    solve: Optional[Callable] = None
    run: Optional[Callable] = None
    version: int = 1
    obsolete_by: Optional[str] = None
    description: str = ""
    multi: bool = False
    icon: str = ""
    widget: str = ""
    exposure: str = "primary"
    library: str = ""
    settings: dict = field(default_factory=dict)
    placeholder: bool = False
    volatile: bool = False

    def input(self, name: str) -> Optional[Port]:
        for p in self.inputs:
            if p.name == name:
                return p
        return None

    def output(self, name: str) -> Optional[Port]:
        for p in self.outputs:
            if p.name == name:
                return p
        return None

    def entry(self) -> dict:
        return {"id": self.id, "guid": self.guid, "name": self.name, "nick": self.nick or self.name, "category": self.category, "group": self.group, "description": self.description, "version": self.version, "obsolete": bool(self.obsolete_by), "obsolete_by": self.obsolete_by, "exposure": self.exposure, "icon": self.icon, "widget": self.widget, "library": self.library, "multi": self.multi, "settings": dict(self.settings), "inputs": [p.entry() for p in self.inputs], "outputs": [p.entry() for p in self.outputs]}


def validate(nt: NodeType) -> None:
    if not isinstance(nt.id, str) or not ID_RE.match(nt.id):
        raise ValueError("Node type id %r must read namespace.name, or plugin-id/name for a plugin." % (nt.id,))
    try:
        uuid.UUID(str(nt.guid))
    except ValueError:
        raise ValueError("Node type %s needs a uuid guid." % nt.id)
    if not nt.name:
        raise ValueError("Node type %s needs a name." % nt.id)
    if nt.solve is None and nt.run is None and not nt.placeholder:
        raise ValueError("Node type %s needs solve or run." % nt.id)
    for side, ports in (("input", nt.inputs), ("output", nt.outputs)):
        seen = set()
        for p in ports:
            if not isinstance(p, Port):
                raise ValueError("Node type %s: %s %r is not a Port." % (nt.id, side, p))
            if p.name in seen or not p.name:
                raise ValueError("Node type %s: duplicate or empty %s name %r." % (nt.id, side, p.name))
            seen.add(p.name)
            if p.kind not in KINDS:
                raise ValueError("Node type %s: unknown port kind %r." % (nt.id, p.kind))
            if p.access not in ACCESS:
                raise ValueError("Node type %s: unknown access %r." % (nt.id, p.access))


def register(nt: NodeType) -> NodeType:
    from app.graph import registry

    return registry.register(nt)


FALLBACKS = {("integer", "number"), ("number", "integer"), ("boolean", "number"), ("boolean", "integer")}


def coerce(kind: str, value: Any) -> Any:
    if value is None or kind in ("any", "geometry", "docref"):
        return value
    if kind == "number":
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value) if isinstance(value, int) else value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                raise TypeError("Text %r is not a number." % value)
    elif kind == "integer":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value == int(value):
                return int(value)
            return int(round(value))
        if isinstance(value, str):
            try:
                return int(round(float(value.strip())))
            except ValueError:
                raise TypeError("Text %r is not an integer." % value)
    elif kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no", "1", "0"):
            return value.strip().lower() in ("true", "yes", "1")
    elif kind == "text":
        return value if isinstance(value, str) else str(value)
    else:
        try:
            from app.graph import values
        except ImportError:
            return value
        try:
            return values.convert(value, kind)
        except ValueError as err:
            raise TypeError(str(err))
    raise TypeError("A %s value cannot be used as %s." % (type(value).__name__, kind))
