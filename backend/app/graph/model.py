import copy
import threading
import uuid
from datetime import datetime, timezone
from graphlib import TopologicalSorter

from app.graph import registry, sdk

FORMAT = "formcad.graph"
VERSION = "1.0.0"
MIN_READER = "1.0.0"
MOD_KEYS = ("reverse", "flatten", "graft", "simplify", "invert", "principal")
STATES = ("blank", "collecting", "computing", "computed", "failed", "skipped")
LEVEL_RANK = {"blank": 0, "remark": 1, "warning": 2, "error": 3}
DEFAULT_SETTINGS = {"seed": 0, "tolerance": 0.001, "units": "mm", "time_budget": 60.0, "enabled": True}
MAX_NODES = 5000
MAX_WIRES = 20000


class GraphError(ValueError):
    pass


class GraphRefused(GraphError):
    def __init__(self, message: str, code: str = "refused", path=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.path = path or []


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:8])


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def version_tuple(text) -> tuple:
    out = []
    for part in str(text or "0").split(".")[:3]:
        try:
            out.append(int("".join(c for c in part if c.isdigit()) or 0))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def clean_mods(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if key in MOD_KEYS:
            if value:
                out[key] = True
        elif key == "expression":
            if isinstance(value, str) and value.strip():
                out[key] = value
        elif value not in (None, False, "", {}, []):
            out[key] = copy.deepcopy(value)
    return out


class PortState:
    def __init__(self, pid: str, name: str, side: str, access: str = "item", mods=None, persistent=None, extra=None):
        self.id = pid
        self.name = name
        self.side = side
        self.access = access
        self.mods = clean_mods(mods)
        self.persistent = copy.deepcopy(persistent)
        self.extra = extra or {}

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update({"id": self.id, "name": self.name, "access": self.access})
        if self.mods:
            out["mods"] = copy.deepcopy(self.mods)
        if self.side == "in" and self.persistent is not None:
            out["persistent"] = copy.deepcopy(self.persistent)
        return out


class Node:
    def __init__(self, nid: str, type_id: str):
        self.id = nid
        self.type = type_id
        self.guid = ""
        self.type_name = ""
        self.library = ""
        self.node_version = 1
        self.nickname = ""
        self.enabled = True
        self.preview = True
        self.matching = "longest"
        self.x = 0.0
        self.y = 0.0
        self.settings: dict = {}
        self.ins: list = []
        self.outs: list = []
        self.extra: dict = {}
        self.ntype = None
        self.state = "blank"
        self.messages: list = []
        self.outputs: dict = {}
        self.runs = 0
        self.ms = 0.0
        self.epoch = 0
        self.missing = False

    def port(self, pid_or_name: str, side: str = ""):
        for p in (self.ins if side != "out" else []) + (self.outs if side != "in" else []):
            if p.id == pid_or_name or p.name == pid_or_name:
                return p
        return None

    def level(self) -> str:
        best = "blank"
        for m in self.messages:
            if LEVEL_RANK[m["level"]] > LEVEL_RANK[best]:
                best = m["level"]
        return best

    def config_signature(self) -> str:
        import json

        ports = [(p.name, p.access, sorted(p.mods.items()), p.persistent) for p in self.ins]
        outs = [(p.name, sorted(p.mods.items())) for p in self.outs]
        return json.dumps([self.type, self.guid, self.enabled, self.matching, self.settings, ports, outs], sort_keys=True, default=str)

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update({"id": self.id, "type": self.type, "guid": self.guid, "type_name": self.type_name, "library": self.library, "node_version": self.node_version, "nickname": self.nickname, "enabled": self.enabled, "preview": self.preview, "matching": self.matching, "x": self.x, "y": self.y, "ports": {"in": [p.to_dict() for p in self.ins], "out": [p.to_dict() for p in self.outs]}, "settings": copy.deepcopy(self.settings)})
        return out

    def bind_type(self) -> None:
        nt = registry.resolve(self.type, self.guid)
        if nt is None:
            nt = registry.placeholder(self.type, self.guid, self.type_name, [sdk.Port(p.name, "any", p.access, optional=True) for p in self.ins], [sdk.Port(p.name, "any", "item") for p in self.outs])
            self.missing = True
        else:
            self.missing = False
        self.ntype = nt


class Wire:
    def __init__(self, wid: str, src: str, dst: str, order: int = 0, extra=None):
        self.id = wid
        self.src = src
        self.dst = dst
        self.order = order
        self.extra = extra or {}
        self.disabled = False

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update({"id": self.id, "from": self.src, "to": self.dst, "order": self.order})
        return out


class Group:
    def __init__(self, gid: str, name: str = "", colour: str = "#8a8f98", members=None, extra=None):
        self.id = gid
        self.name = name
        self.colour = colour
        self.members = list(members or [])
        self.extra = extra or {}

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update({"id": self.id, "name": self.name, "colour": self.colour, "members": list(self.members)})
        return out


def walk(adj: dict, start: str, goal: str):
    parent = {start: None}
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur == goal:
            path = []
            while cur is not None:
                path.append(cur)
                cur = parent[cur]
            return path[::-1]
        for nxt in adj.get(cur, ()):
            if nxt not in parent:
                parent[nxt] = cur
                stack.append(nxt)
    return None


def reconcile_ports(node: Node, saved: dict, problems: list) -> None:
    nt = node.ntype
    saved_in = {p.get("name"): p for p in (saved.get("in") or []) if isinstance(p, dict)}
    saved_out = {p.get("name"): p for p in (saved.get("out") or []) if isinstance(p, dict)}
    node.ins = []
    node.outs = []
    if node.missing:
        for side, src, dest in (("in", saved.get("in") or [], node.ins), ("out", saved.get("out") or [], node.outs)):
            for p in src:
                if isinstance(p, dict) and p.get("name"):
                    dest.append(make_port(p, side, str(p.get("access") or "item"), p))
        return
    for decl in nt.inputs:
        raw = saved_in.get(decl.name)
        node.ins.append(make_port(raw or {}, "in", decl.access, raw, decl.name))
    for decl in nt.outputs:
        raw = saved_out.get(decl.name)
        node.outs.append(make_port(raw or {}, "out", decl.access, raw, decl.name))
    gone = [n for n in list(saved_in) + list(saved_out) if n not in {d.name for d in nt.inputs} | {d.name for d in nt.outputs}]
    for name in gone:
        problems.append("Node %s no longer has a port named %s; it was dropped." % (node.id, name))


def make_port(raw: dict, side: str, default_access: str, full=None, name: str = "") -> PortState:
    raw = raw or {}
    known = {"id", "name", "access", "mods", "persistent"}
    extra = {k: v for k, v in raw.items() if k not in known}
    access = raw.get("access") if raw.get("access") in sdk.ACCESS else default_access
    return PortState(str(raw.get("id") or new_id("p")), name or str(raw.get("name")), side, access, raw.get("mods"), raw.get("persistent"), extra)


NODE_KNOWN = {"id", "type", "guid", "type_name", "library", "node_version", "nickname", "enabled", "preview", "matching", "x", "y", "ports", "settings"}


def node_from_dict(raw: dict, problems: list) -> Node:
    if not isinstance(raw, dict) or not raw.get("type"):
        raise GraphError("A node needs a type.")
    n = Node(str(raw.get("id") or new_id("n")), str(raw["type"]))
    n.guid = str(raw.get("guid") or "")
    n.type_name = str(raw.get("type_name") or "")
    n.library = str(raw.get("library") or "")
    n.node_version = raw.get("node_version", 1)
    n.nickname = str(raw.get("nickname") or "")
    n.enabled = bool(raw.get("enabled", True))
    n.preview = bool(raw.get("preview", True))
    n.matching = raw.get("matching") if raw.get("matching") in sdk.MATCHING else "longest"
    n.x = float(raw.get("x", 0.0) or 0.0)
    n.y = float(raw.get("y", 0.0) or 0.0)
    if not (abs(n.x) < 1e12 and abs(n.y) < 1e12):
        raise GraphError("A node position is not a usable number.")
    n.settings = copy.deepcopy(raw.get("settings")) if isinstance(raw.get("settings"), dict) else {}
    n.extra = {k: copy.deepcopy(v) for k, v in raw.items() if k not in NODE_KNOWN}
    n.bind_type()
    if not n.type_name:
        n.type_name = n.ntype.name
    if not n.guid or not n.missing:
        n.guid = n.ntype.guid if not n.missing else n.guid
    if not n.library:
        n.library = n.ntype.library
    if not n.missing:
        n.node_version = n.ntype.version
        for key, value in n.ntype.settings.items():
            n.settings.setdefault(key, copy.deepcopy(value))
    ports = raw.get("ports") if isinstance(raw.get("ports"), dict) else {}
    reconcile_ports(n, ports, problems)
    return n


class Graph:
    def __init__(self, gid: str = "", name: str = ""):
        self.id = gid
        self.name = name
        self.meta: dict = {"name": name, "description": "", "author": "", "license": ""}
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.nodes: dict = {}
        self.wires: dict = {}
        self.groups: dict = {}
        self.notes: list = []
        self.view: dict = {"zoom": 1.0, "origin": [0, 0]}
        self.extensions: dict = {}
        self.libraries: list = []
        self.created = now_iso()
        self.extra: dict = {}
        self.version = VERSION
        self.min_reader = MIN_READER
        self.readonly = False
        self.raw = None
        self.problems: list = []
        self.rev = 0
        self.lock = threading.RLock()
        self.abort = threading.Event()
        self.ports: dict = {}
        self.solving = False

    @classmethod
    def from_definition(cls, defn: dict, gid: str = "") -> "Graph":
        if not isinstance(defn, dict):
            raise GraphError("A graph definition is a JSON object.")
        fmt = defn.get("format", FORMAT)
        if fmt != FORMAT:
            raise GraphError("This is not a formCAD graph (format %r)." % (fmt,))
        for key, cap, what in (("nodes", MAX_NODES, "nodes"), ("wires", MAX_WIRES, "wires")):
            rows = defn.get(key)
            if rows is not None and not isinstance(rows, list):
                raise GraphError("The %s of a graph are a list." % what)
            if rows is not None and len(rows) > cap:
                raise GraphError("The graph has %d %s; the limit is %d." % (len(rows), what, cap))
        g = cls(gid or str(defn.get("id") or ""), str(defn.get("name") or ""))
        try:
            g.load(defn)
        except GraphError:
            raise
        except (TypeError, ValueError, AttributeError, KeyError, OverflowError, RecursionError):
            raise GraphError("A field of the graph has a value of the wrong type.")
        return g

    def load(self, defn: dict) -> None:
        self.version = str(defn.get("version") or VERSION)
        self.min_reader = str(defn.get("min_reader") or MIN_READER)
        mine = version_tuple(VERSION)
        theirs = version_tuple(self.version)
        self.readonly = theirs[0] > mine[0] or version_tuple(self.min_reader) > mine
        self.raw = copy.deepcopy(defn) if self.readonly else None
        self.name = str(defn.get("name") or self.name or "")
        self.created = str(defn.get("created") or self.created)
        meta = defn.get("meta") if isinstance(defn.get("meta"), dict) else {}
        self.meta = {"name": self.name, "description": "", "author": "", "license": ""}
        self.meta.update(copy.deepcopy(meta))
        self.settings = dict(DEFAULT_SETTINGS)
        if isinstance(defn.get("settings"), dict):
            self.settings.update(copy.deepcopy(defn["settings"]))
        self.view = copy.deepcopy(defn["view"]) if isinstance(defn.get("view"), dict) else {"zoom": 1.0, "origin": [0, 0]}
        self.notes = copy.deepcopy(defn["notes"]) if isinstance(defn.get("notes"), list) else []
        self.extensions = copy.deepcopy(defn["extensions"]) if isinstance(defn.get("extensions"), dict) else {}
        self.libraries = copy.deepcopy(defn["libraries"]) if isinstance(defn.get("libraries"), list) else []
        known = {"format", "version", "min_reader", "created", "app", "meta", "libraries", "settings", "nodes", "wires", "groups", "notes", "view", "extensions", "id", "name"}
        self.extra = {k: copy.deepcopy(v) for k, v in defn.items() if k not in known}
        self.problems = []
        self.nodes = {}
        self.wires = {}
        self.groups = {}
        for raw in defn.get("nodes") or []:
            try:
                n = node_from_dict(raw, self.problems)
            except GraphError as err:
                self.problems.append(str(err))
                continue
            if n.id in self.nodes:
                n.id = new_id("n")
            self.nodes[n.id] = n
        self.reindex()
        for raw in sorted([w for w in (defn.get("wires") or []) if isinstance(w, dict)], key=lambda w: (int(w.get("order", 0) or 0))):
            src, dst = raw.get("from"), raw.get("to")
            if src not in self.ports or dst not in self.ports or self.ports[src][1] != "out" or self.ports[dst][1] != "in":
                self.problems.append("Wire %s joins ports that do not exist and was dropped." % raw.get("id"))
                continue
            w = Wire(str(raw.get("id") or new_id("w")), src, dst, int(raw.get("order", 0) or 0), {k: copy.deepcopy(v) for k, v in raw.items() if k not in ("id", "from", "to", "order")})
            if w.id in self.wires:
                w.id = new_id("w")
            self.wires[w.id] = w
        self.settle_loops()
        for raw in defn.get("groups") or []:
            if isinstance(raw, dict):
                g = Group(str(raw.get("id") or new_id("g")), str(raw.get("name") or ""), str(raw.get("colour") or "#8a8f98"), [m for m in raw.get("members") or [] if m in self.nodes], {k: copy.deepcopy(v) for k, v in raw.items() if k not in ("id", "name", "colour", "members")})
                self.groups[g.id] = g

    def close_wire(self, w: Wire) -> None:
        w.disabled = True
        self.problems.append("Wire %s would close a loop and is disabled." % w.id)
        for nid in {self.ports[w.src][0].id, self.ports[w.dst][0].id}:
            self.nodes[nid].messages = [{"level": "error", "text": "A wire into this node closes a loop and is disabled.", "code": "CYCLE", "port": ""}]

    def settle_loops(self) -> None:
        pairs, indeg, live = {}, {nid: 0 for nid in self.nodes}, []
        for w in self.wires.values():
            a, b = self.ports[w.src][0].id, self.ports[w.dst][0].id
            if a == b:
                self.close_wire(w)
                continue
            live.append((w, a, b))
            if b not in pairs.setdefault(a, set()):
                pairs[a].add(b)
                indeg[b] += 1
        ready = [nid for nid, d in indeg.items() if d == 0]
        seen = 0
        while ready:
            nid = ready.pop()
            seen += 1
            for b in pairs.get(nid, ()):
                indeg[b] -= 1
                if indeg[b] == 0:
                    ready.append(b)
        if seen == len(self.nodes):
            return
        stuck = {nid for nid, d in indeg.items() if d > 0}
        accepted = {}
        for w, a, b in live:
            if a in stuck and b in stuck:
                if walk(accepted, b, a) is not None:
                    self.close_wire(w)
                else:
                    accepted.setdefault(a, set()).add(b)

    def rebind_types(self) -> list:
        changed = []
        for n in self.nodes.values():
            nt = registry.resolve(n.type, n.guid)
            if (nt is None) == n.missing and (nt is None or nt is n.ntype):
                continue
            saved = n.to_dict()["ports"]
            n.bind_type()
            reconcile_ports(n, saved, self.problems)
            if not n.missing:
                n.type_name = n.ntype.name
                n.node_version = n.ntype.version
                for key, value in n.ntype.settings.items():
                    n.settings.setdefault(key, copy.deepcopy(value))
            changed.append(n.id)
        if changed:
            self.reindex()
            for wid in [w.id for w in self.wires.values() if w.src not in self.ports or w.dst not in self.ports]:
                del self.wires[wid]
        return changed

    def reindex(self) -> None:
        self.ports = {}
        for n in self.nodes.values():
            for p in n.ins:
                self.ports[p.id] = (n, "in", p)
            for p in n.outs:
                self.ports[p.id] = (n, "out", p)

    def to_definition(self, with_format: bool = True) -> dict:
        if self.readonly and self.raw is not None:
            return copy.deepcopy(self.raw)
        out = copy.deepcopy(self.extra)
        if with_format:
            out["format"] = FORMAT
        out.update({"version": self.version if self.readonly else VERSION, "min_reader": MIN_READER, "id": self.id, "name": self.name, "created": self.created, "app": {"name": "formCAD"}, "meta": copy.deepcopy(self.meta), "libraries": copy.deepcopy(self.libraries), "settings": copy.deepcopy(self.settings), "nodes": [n.to_dict() for n in self.nodes.values()], "wires": [w.to_dict() for w in sorted(self.wires.values(), key=lambda w: w.order)], "groups": [g.to_dict() for g in self.groups.values()], "notes": copy.deepcopy(self.notes), "view": copy.deepcopy(self.view), "extensions": copy.deepcopy(self.extensions)})
        out["meta"]["name"] = self.name
        return out

    def edges(self) -> dict:
        preds = {nid: {} for nid in self.nodes}
        for w in self.wires.values():
            if w.disabled:
                continue
            preds[self.ports[w.dst][0].id][self.ports[w.src][0].id] = True
        return preds

    def successors(self) -> dict:
        succ = {}
        for w in self.wires.values():
            if not w.disabled:
                succ.setdefault(self.ports[w.src][0].id, {})[self.ports[w.dst][0].id] = True
        return succ

    def cycle_through(self, src_node: str, dst_node: str):
        return walk(self.successors(), dst_node, src_node)

    def order(self) -> list:
        sorter = TopologicalSorter(self.edges())
        sorter.prepare()
        pos = {nid: i for i, nid in enumerate(self.nodes)}
        out = []
        while sorter.is_active():
            ready = sorted(sorter.get_ready(), key=pos.__getitem__)
            for nid in ready:
                out.append(nid)
                sorter.done(nid)
        return out

    def sources_of(self, port_id: str) -> list:
        ws = [w for w in self.wires.values() if w.dst == port_id and not w.disabled]
        ws.sort(key=lambda w: w.order)
        return [w.src for w in ws]

    def downstream(self, node_id: str, succ=None) -> list:
        succ = self.successors() if succ is None else succ
        pos = {nid: i for i, nid in enumerate(self.nodes)}
        seen = {}
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for nxt in sorted(succ.get(cur, ()), key=pos.__getitem__):
                if nxt not in seen and nxt != node_id:
                    seen[nxt] = True
                    stack.append(nxt)
        return list(seen)

    def expire(self, node_id: str) -> list:
        out = []
        stack = [node_id]
        succ = {}
        for w in self.wires.values():
            if not w.disabled:
                succ.setdefault(self.ports[w.src][0].id, []).append(self.ports[w.dst][0].id)
        while stack:
            nid = stack.pop()
            n = self.nodes.get(nid)
            if n is None:
                continue
            n.epoch += 1
            if n.state == "blank" and nid != node_id and not n.messages:
                continue
            if n.state != "blank" or n.outputs or n.messages:
                out.append(nid)
            n.state = "blank"
            n.outputs = {}
            n.messages = []
            stack.extend(succ.get(nid, []))
        self.rev += 1
        return out

    def expire_all(self) -> None:
        for nid in list(self.nodes):
            n = self.nodes[nid]
            n.epoch += 1
            n.state = "blank"
            n.outputs = {}
            n.messages = []
        self.rev += 1

    def explain_cycle(self, cycle: list) -> str:
        names = [self.nodes[c].nickname or self.nodes[c].type_name or c for c in cycle if c in self.nodes]
        return " -> ".join(names)

    def connect(self, src: str, dst: str, mode: str = "replace", wid: str = "") -> Wire:
        if src not in self.ports or dst not in self.ports:
            raise GraphRefused("That port does not exist.", "noport")
        sn, sside, _ = self.ports[src]
        dn, dside, _ = self.ports[dst]
        if sside != "out" or dside != "in":
            raise GraphRefused("A wire runs from an output port to an input port.", "direction")
        if sn.id == dn.id:
            raise GraphRefused("A node cannot feed itself.", "selfloop", [sn.id, sn.id])
        for w in self.wires.values():
            if w.src == src and w.dst == dst:
                raise GraphRefused("Those two ports are already joined.", "duplicate")
        if len(self.wires) >= MAX_WIRES:
            raise GraphRefused("A graph holds at most %d wires." % MAX_WIRES, "limit")
        w = Wire(wid or new_id("w"), src, dst, 0)
        cycle = self.cycle_through(sn.id, dn.id)
        if cycle:
            raise GraphRefused("That wire would make a loop: %s." % self.explain_cycle(cycle), "cycle", cycle)
        existing = [x for x in self.wires.values() if x.dst == dst]
        if mode == "replace":
            for x in existing:
                self.disconnect(x.id)
            w.order = 0
        else:
            w.order = max([x.order for x in existing], default=-1) + 1
        self.wires[w.id] = w
        self.expire(dn.id)
        return w

    def disconnect(self, wid: str) -> None:
        w = self.wires.pop(wid, None)
        if w is None:
            raise GraphRefused("There is no wire %s." % wid, "nowire")
        self.expire(self.ports[w.dst][0].id)

    def add_node(self, type_id: str, x: float = 0.0, y: float = 0.0, nid: str = "", settings=None) -> Node:
        nt = registry.get(type_id)
        if nt is None:
            raise GraphRefused("There is no node type %s." % type_id, "notype")
        if len(self.nodes) >= MAX_NODES:
            raise GraphRefused("A graph holds at most %d nodes." % MAX_NODES, "limit")
        raw = {"id": nid or new_id("n"), "type": nt.id, "guid": nt.guid, "x": x, "y": y}
        if settings:
            raw["settings"] = settings
        n = node_from_dict(raw, self.problems)
        if n.id in self.nodes:
            raise GraphRefused("There is already a node %s." % n.id, "dupnode")
        self.nodes[n.id] = n
        self.reindex()
        self.rev += 1
        return n

    def remove_node(self, nid: str) -> list:
        n = self.nodes.get(nid)
        if n is None:
            raise GraphRefused("There is no node %s." % nid, "nonode")
        ports = {p.id for p in n.ins + n.outs}
        hit = []
        for w in list(self.wires.values()):
            if w.src in ports or w.dst in ports:
                other = self.ports[w.dst][0].id if w.src in ports else None
                if other:
                    hit.append(other)
                del self.wires[w.id]
        for other in hit:
            self.expire(other)
        for g in self.groups.values():
            g.members = [m for m in g.members if m != nid]
        del self.nodes[nid]
        self.reindex()
        self.rev += 1
        return hit

    def apply_definition(self, defn: dict) -> list:
        fresh = Graph.from_definition(defn, self.id)
        if fresh.readonly:
            raise GraphRefused("This graph was written by a newer version of formCAD and cannot be changed here.", "newer")
        expired = []
        old_sig = {nid: n.config_signature() for nid, n in self.nodes.items()}
        old_wires = self.wire_signature()
        keep = {}
        for nid, n in fresh.nodes.items():
            prev = self.nodes.get(nid)
            if prev is not None and old_sig[nid] == n.config_signature():
                n.state, n.messages, n.outputs, n.runs, n.ms, n.epoch = prev.state, prev.messages, prev.outputs, prev.runs, prev.ms, prev.epoch
                keep[nid] = True
        self.nodes = fresh.nodes
        self.wires = fresh.wires
        self.groups = fresh.groups
        self.ports = fresh.ports
        self.name, self.meta, self.settings, self.view, self.notes = fresh.name, fresh.meta, fresh.settings, fresh.view, fresh.notes
        self.extensions, self.libraries, self.extra, self.created = fresh.extensions, fresh.libraries, fresh.extra, fresh.created
        self.version, self.min_reader, self.readonly, self.raw, self.problems = fresh.version, fresh.min_reader, False, None, fresh.problems
        new_wires = self.wire_signature()
        for nid, n in self.nodes.items():
            if nid not in keep or old_wires.get(nid) != new_wires.get(nid):
                n.epoch += 1
                n.state, n.messages, n.outputs = "blank", [], {}
                expired.append(nid)
        seen = set(expired)
        succ = self.successors()
        stack = list(expired)
        while stack:
            cur = stack.pop()
            for d in succ.get(cur, ()):
                if d not in seen:
                    seen.add(d)
                    dn = self.nodes[d]
                    dn.epoch += 1
                    dn.state, dn.messages, dn.outputs = "blank", [], {}
                    expired.append(d)
                    stack.append(d)
        for nid, n in self.nodes.items():
            if nid in keep and n.state == "blank":
                n.state = "blank"
        self.rev += 1
        return expired

    def wire_signature(self) -> dict:
        sig = {}
        for w in self.wires.values():
            if w.disabled:
                continue
            dn, _, dp = self.ports[w.dst]
            sn, _, sp = self.ports[w.src]
            sig.setdefault(dn.id, []).append((dp.name, sn.id, sp.name, w.order))
        return {k: sorted(v) for k, v in sig.items()}
