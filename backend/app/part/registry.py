from dataclasses import dataclass, field
from typing import Callable, Optional

TYPES: dict = {}
PLANE_SOURCES: dict = {}
KINDS = ("length", "angle", "int", "bool", "enum", "text", "vector", "json")
REF_KINDS = ("face", "edge", "vertex", "sketch", "plane", "feature")


class PartError(ValueError):
    pass


class RefLost(PartError):
    def __init__(self, message, slot="", key=""):
        super().__init__(message)
        self.slot = slot
        self.key = key


@dataclass
class Param:
    name: str
    kind: str = "length"
    default: object = None
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list] = None
    label: str = ""
    unit: str = ""

    def schema(self) -> dict:
        return {"name": self.name, "kind": self.kind, "default": self.default, "min": self.min, "max": self.max, "choices": self.choices, "label": self.label or self.name, "unit": self.unit}


@dataclass
class RefSlot:
    name: str
    kind: str = "face"
    multi: bool = False
    required: bool = True
    label: str = ""

    def schema(self) -> dict:
        return {"name": self.name, "kind": self.kind, "multi": self.multi, "required": self.required, "label": self.label or self.name}


@dataclass
class FeatureType:
    type: str
    label: str
    group: str = ""
    needs_body: bool = True
    sketch: bool = False
    params: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    roles: tuple = ()
    plan: Optional[Callable] = None
    finish: Optional[Callable] = None
    fixed: dict = field(default_factory=dict)

    def param(self, name):
        for p in self.params:
            if p.name == name:
                return p
        return None

    def slot(self, name):
        for s in self.refs:
            if s.name == name:
                return s
        return None

    def schema(self) -> dict:
        return {"type": self.type, "label": self.label, "group": self.group, "needs_body": self.needs_body, "sketch": self.sketch, "params": [p.schema() for p in self.params], "refs": [s.schema() for s in self.refs], "roles": list(self.roles)}


def register(ft: FeatureType) -> FeatureType:
    for p in ft.params:
        if p.kind not in KINDS:
            raise ValueError("Unknown parameter kind %s." % p.kind)
    for s in ft.refs:
        if s.kind not in REF_KINDS:
            raise ValueError("Unknown reference kind %s." % s.kind)
    TYPES[ft.type] = ft
    return ft


def get(type_name: str) -> FeatureType:
    ft = TYPES.get(str(type_name))
    if ft is None:
        raise PartError("Unknown feature type %s." % type_name)
    return ft


def register_plane_source(kind: str, fn) -> None:
    PLANE_SOURCES[kind] = fn


def listing() -> list:
    return [t.schema() for t in TYPES.values()]
