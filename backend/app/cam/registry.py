import importlib
import pkgutil
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from app.cam.limits import CamError

TYPES: dict = {}
_lock = threading.Lock()
_loaded = False


@dataclass
class Field:
    name: str
    type: str
    default: Any = None
    label: str = ""
    min: float | None = None
    max: float | None = None
    unit: str = ""
    choices: tuple = ()
    group: str = ""
    nullable: bool = False

    def view(self) -> dict:
        return {"name": self.name, "type": self.type, "default": self.default, "label": self.label or self.name.replace("_", " ").capitalize(), "min": self.min, "max": self.max, "unit": self.unit, "choices": list(self.choices), "group": self.group, "nullable": self.nullable}

    def clean(self, value):
        if value is None:
            if self.nullable or self.default is None:
                return None
            return self.default
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            raise CamError("%s must be true or false." % self.name)
        if self.type == "choice":
            if value not in self.choices:
                raise CamError("%s must be one of %s." % (self.name, ", ".join(str(c) for c in self.choices)))
            return value
        if self.type == "text":
            return str(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CamError("%s needs a number." % self.name)
        v = float(value)
        if v != v or v in (float("inf"), float("-inf")):
            raise CamError("%s needs a finite number." % self.name)
        if self.min is not None and v < self.min or self.max is not None and v > self.max:
            raise CamError("%s must be between %g and %g." % (self.name, self.min if self.min is not None else float("-inf"), self.max if self.max is not None else float("inf")))
        return int(round(v)) if self.type == "int" else v


@dataclass
class OpType:
    kind: str
    label: str
    group: str
    generate: Callable
    fields: list = field(default_factory=list)
    tool_kinds: tuple = ()
    geometry: tuple = ()
    description: str = ""
    needs_feeds: bool = True
    needs_model: bool = False
    default_geometry: dict | None = None

    def defaults(self) -> dict:
        return {f.name: f.default for f in self.fields}

    def clean(self, params: dict) -> dict:
        params = params or {}
        by_name = {f.name: f for f in self.fields}
        for key in params:
            if key not in by_name:
                raise CamError("%s has no parameter called %s." % (self.label, key))
        return {f.name: f.clean(params.get(f.name)) for f in self.fields}

    def view(self) -> dict:
        return {"kind": self.kind, "label": self.label, "group": self.group, "tool_kinds": list(self.tool_kinds), "geometry": list(self.geometry), "description": self.description, "fields": [f.view() for f in self.fields]}


def register(op: OpType) -> OpType:
    TYPES[op.kind] = op
    return op


def load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        from app.cam import ops

        for info in pkgutil.iter_modules(ops.__path__):
            importlib.import_module("app.cam.ops." + info.name)


def get(kind: str) -> OpType:
    load()
    if kind not in TYPES:
        raise CamError("There is no operation type called %s." % kind)
    return TYPES[kind]


def listing() -> list:
    load()
    return [t.view() for t in TYPES.values()]
