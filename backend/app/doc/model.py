import copy

from app.doc import geom
from app.doc import tables as T
from app.doc.entities import Entity, entity_from_dict
from app.sysvars.defs import drawing_defaults

MISSING = object()
FIRST_HANDLE = 0x100
MAX_ENTITIES = 5_000_000
SPACE_MODEL = "model"


def layout_space(name: str) -> str:
    return "layout:" + name


def block_space(name: str) -> str:
    return "block:" + name


class Drawing:
    def __init__(self, metric: bool = True):
        self.metric = metric
        self.header: dict = drawing_defaults(metric)
        self.tables: dict = {n: T.Table(n) for n in T.TABLE_NAMES}
        self.ents: dict = {}
        self.spaces: dict = {SPACE_MODEL: []}
        self.next_handle: int = FIRST_HANDLE
        self.foreign: dict = {}
        self.reserved3d: dict = {"parts": [], "assemblies": [], "pmi": [], "graphs": []}
        self.tolerances: dict = {"absolute": geom.EPS, "angular": geom.EPS, "parallel": geom.PARALLEL_EPS}
        self.relations: dict = {}
        self.recorder = None
        self.session_hidden: set = set()
        self.populate_defaults()

    def populate_defaults(self) -> None:
        m = self.metric
        for rec in T.standard_linetypes(m):
            self.tables["linetypes"].put(rec)
        self.tables["layers"].put(T.new_layer("0"))
        self.tables["layers"].put(T.new_layer("Defpoints", plot=False))
        self.tables["textstyles"].put(T.new_textstyle("Standard"))
        self.tables["dimstyles"].put(T.new_dimstyle("Standard"))
        if m:
            self.tables["dimstyles"].put(T.new_dimstyle("ISO-25", T.ISO25_OVERRIDES))
            self.header["DIMSTYLE"] = "ISO-25"
        self.tables["mleaderstyles"].put(T.new_mleaderstyle(m))
        self.tables["tablestyles"].put(T.new_tablestyle(m))
        self.tables["mlinestyles"].put(T.new_mlinestyle())
        self.tables["layouts"].put(T.new_layout("Layout1", 1, m))
        self.tables["layouts"].put(T.new_layout("Layout2", 2, m))
        for name in ("Layout1", "Layout2"):
            self.spaces[layout_space(name)] = []
        for rec in T.scale_records(m):
            self.tables["scales"].put(rec)
        self.tables["vports"].put({"name": "*Active", "tiles": [{"lower_left": [0.0, 0.0], "upper_right": [1.0, 1.0], "center": [210.0, 148.5] if m else [6.0, 4.5], "height": 297.0 if m else 9.0, "aspect": 1.0}]})

    def new_handle(self) -> int:
        h = self.next_handle
        self.next_handle += 1
        return h

    def _rec_entity(self, h: int) -> None:
        if self.recorder is not None:
            self.recorder.note(("e", h), lambda: self.ents[h].to_dict() if h in self.ents else None)

    def _rec_space(self, name: str) -> None:
        if self.recorder is not None:
            self.recorder.note(("s", name), lambda: list(self.spaces[name]) if name in self.spaces else None)

    def _rec_table(self, table: str, name: str) -> None:
        if self.recorder is not None:
            key = T.Table.key(name)

            def read():
                rec = self.tables[table].get(name)
                return copy.deepcopy(rec) if rec is not None else None

            self.recorder.note(("t", table, key), read)

    def _rec_header(self, name: str) -> None:
        if self.recorder is not None:
            self.recorder.note(("h", name), lambda: copy.deepcopy(self.header[name]) if name in self.header else MISSING)

    def get(self, h: int):
        return self.ents.get(h)

    def space_of(self, h: int):
        e = self.ents.get(h)
        return e.owner if e else None

    def ensure_space(self, name: str) -> list:
        if name not in self.spaces:
            self._rec_space(name)
            self.spaces[name] = []
        return self.spaces[name]

    def add_entity(self, ent: Entity, space: str = SPACE_MODEL, handle: int = 0) -> int:
        if len(self.ents) >= MAX_ENTITIES:
            raise ValueError("entity limit reached")
        if not ent.valid():
            raise ValueError("invalid geometry")
        if handle:
            if handle in self.ents:
                raise ValueError("handle in use")
            ent.handle = handle
            self.next_handle = max(self.next_handle, handle + 1)
        else:
            ent.handle = self.new_handle()
        ent.owner = space
        if not self.tables["layers"].has(ent.layer or "0"):
            self.table_set("layers", T.new_layer(ent.layer or "0"))
        elif not ent.layer:
            ent.layer = "0"
        self._rec_entity(ent.handle)
        self._rec_space(space)
        self.ensure_space(space)
        self.ents[ent.handle] = ent
        self.spaces[space].append(ent.handle)
        return ent.handle

    def erase_entity(self, h: int):
        ent = self.ents.get(h)
        if ent is None:
            return None
        self._rec_entity(h)
        self._rec_space(ent.owner)
        del self.ents[h]
        lst = self.spaces.get(ent.owner)
        if lst is not None and h in lst:
            lst.remove(h)
        return ent

    def restore_entity(self, ent: Entity) -> bool:
        if ent.handle in self.ents or ent.owner not in self.spaces:
            return False
        self._rec_entity(ent.handle)
        self._rec_space(ent.owner)
        self.ents[ent.handle] = ent
        self.spaces[ent.owner].append(ent.handle)
        return True

    def modify(self, h: int) -> Entity:
        ent = self.ents[h]
        self._rec_entity(h)
        return ent

    def set_header(self, name: str, value) -> None:
        self._rec_header(name)
        self.header[name] = value

    def get_header(self, name: str, default=None):
        return self.header.get(name, default)

    def table_set(self, table: str, record: dict) -> None:
        self._rec_table(table, record["name"])
        self.tables[table].put(record)

    def table_remove(self, table: str, name: str) -> None:
        self._rec_table(table, name)
        self.tables[table].drop(name)

    def table_get(self, table: str, name: str):
        return self.tables[table].get(name)

    def modify_record(self, table: str, name: str) -> dict:
        rec = self.tables[table].get(name)
        if rec is None:
            raise KeyError(name)
        self._rec_table(table, name)
        return rec

    def layer(self, name: str):
        return self.tables["layers"].get(name)

    def current_layer(self) -> str:
        name = self.header.get("CLAYER", "0")
        rec = self.layer(name)
        return rec["name"] if rec else "0"

    def layer_visible(self, name: str) -> bool:
        rec = self.layer(name)
        return rec is None or (rec["on"] and not rec["frozen"])

    def layer_locked(self, name: str) -> bool:
        rec = self.layer(name)
        return bool(rec and rec["locked"])

    def visible(self, ent: Entity) -> bool:
        return ent.visible and self.layer_visible(ent.layer) and ent.handle not in self.session_hidden

    def entities(self, space: str = SPACE_MODEL):
        for h in list(self.spaces.get(space, ())):
            e = self.ents.get(h)
            if e is not None:
                yield e

    def extents(self, space: str = SPACE_MODEL):
        box = None
        for e in self.entities(space):
            if not e.visible or not self.layer_visible(e.layer) or e.handle in self.session_hidden:
                continue
            box = geom.union_bounds(box, e.bounds())
        return box

    def define_block(self, name: str, base=None, description: str = "", xref: dict | None = None) -> dict:
        rec = {"name": name, "base": list(base or [0.0, 0.0, 0.0]), "description": description, "explodable": True, "insunits": self.header.get("INSUNITS", 0), "annotative": False, "anonymous": name.startswith("*"), "xref": xref}
        self.table_set("blocks", rec)
        self.ensure_space(block_space(name))
        return rec

    def define_layout(self, name: str) -> dict:
        order = len(self.tables["layouts"]) + 1
        rec = T.new_layout(name, order, self.metric)
        self.table_set("layouts", rec)
        self.ensure_space(layout_space(name))
        return rec

    def scale_value(self, name: str) -> float:
        rec = self.tables["scales"].get(name)
        if not rec or rec["paper"] == 0:
            return 1.0
        return rec["drawing"] / rec["paper"]

    def ordered_entities(self) -> list:
        out = []
        for space, handles in self.spaces.items():
            for h in handles:
                e = self.ents.get(h)
                if e is not None:
                    out.append(e)
        return out

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "header": copy.deepcopy(self.header),
            "tables": {n: t.to_list() for n, t in self.tables.items()},
            "spaces": list(self.spaces.keys()),
            "entities": [e.to_dict() for e in self.ordered_entities()],
            "next_handle": self.next_handle,
            "tolerances": dict(self.tolerances),
            "relations": copy.deepcopy(self.relations),
            "foreign": copy.deepcopy(self.foreign),
            "parts": copy.deepcopy(self.reserved3d["parts"]),
            "assemblies": copy.deepcopy(self.reserved3d["assemblies"]),
            "pmi": copy.deepcopy(self.reserved3d["pmi"]),
            "graphs": copy.deepcopy(self.reserved3d["graphs"]),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Drawing":
        d = cls(bool(data.get("metric", True)))
        d.tables = {n: T.Table(n) for n in T.TABLE_NAMES}
        for name, items in data.get("tables", {}).items():
            if name not in d.tables:
                d.tables[name] = T.Table(name)
            d.tables[name].load_list(items)
        d.header = {**d.header, **copy.deepcopy(data.get("header", {}))}
        d.spaces = {SPACE_MODEL: []}
        for s in data.get("spaces", []):
            d.spaces.setdefault(s, [])
        for rec in d.tables["layouts"].values():
            d.spaces.setdefault(layout_space(rec["name"]), [])
        for rec in d.tables["blocks"].values():
            d.spaces.setdefault(block_space(rec["name"]), [])
        top = FIRST_HANDLE
        for raw in data.get("entities", []):
            e = entity_from_dict(raw)
            if e.handle in d.ents or e.handle <= 0:
                e.handle = 0
                continue
            d.ents[e.handle] = e
            d.spaces.setdefault(e.owner, []).append(e.handle)
            top = max(top, e.handle + 1)
        d.next_handle = max(int(data.get("next_handle", FIRST_HANDLE)), top)
        d.tolerances = {**d.tolerances, **data.get("tolerances", {})}
        d.relations = copy.deepcopy(data.get("relations", {}))
        d.foreign = copy.deepcopy(data.get("foreign", {}))
        for k in ("parts", "assemblies", "pmi", "graphs"):
            d.reserved3d[k] = copy.deepcopy(data.get(k, []))
        return d

    def apply_key(self, key: tuple, value) -> None:
        kind = key[0]
        if kind == "e":
            h = key[1]
            old = self.ents.get(h)
            if value is None:
                if old is not None:
                    self.ents.pop(h, None)
            else:
                self.ents[h] = entity_from_dict(value)
        elif kind == "s":
            if value is None:
                self.spaces.pop(key[1], None)
            else:
                self.spaces[key[1]] = list(value)
        elif kind == "t":
            tbl = self.tables[key[1]]
            if value is None:
                tbl._items.pop(key[2], None)
            else:
                tbl._items[key[2]] = copy.deepcopy(value)
        elif kind == "h":
            if value is MISSING:
                self.header.pop(key[1], None)
            else:
                self.header[key[1]] = copy.deepcopy(value)

    def read_key(self, key: tuple):
        kind = key[0]
        if kind == "e":
            e = self.ents.get(key[1])
            return e.to_dict() if e is not None else None
        if kind == "s":
            lst = self.spaces.get(key[1])
            return list(lst) if lst is not None else None
        if kind == "t":
            rec = self.tables[key[1]]._items.get(key[2])
            return copy.deepcopy(rec) if rec is not None else None
        if kind == "h":
            return copy.deepcopy(self.header[key[1]]) if key[1] in self.header else MISSING
        return None
