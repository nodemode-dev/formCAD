import fnmatch
import threading
import weakref
from dataclasses import dataclass

from app.graph import values as V

LOCK = threading.RLock()
SUBS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
KIND_GROUPS = {
    "body": ("solidbody",),
    "curve": ("line", "circle", "arc", "lwpolyline", "polyline3d", "nurbscurve", "spline", "ellipse"),
    "point": ("point",),
}


@dataclass(frozen=True, slots=True)
class Attributed:
    geometry: object
    name: str = ""
    layer: str = ""
    colour: object = None
    props: tuple = ()

    def with_(self, **kw):
        base = {"geometry": self.geometry, "name": self.name, "layer": self.layer, "colour": self.colour, "props": self.props}
        base.update(kw)
        return Attributed(**base)

    def to_stored(self) -> dict:
        return {"$": "Attributed", "name": self.name, "layer": self.layer, "colour": self.colour.hex() if self.colour is not None else "", "props": [list(p) for p in self.props], "geometry": V.encode(self.geometry)}


def unwrap(value):
    return value.geometry if isinstance(value, Attributed) else value


def attributes_of(value) -> dict:
    if isinstance(value, Attributed):
        return {"name": value.name, "layer": value.layer, "colour": value.colour, "props": value.props}
    return {"name": "", "layer": "", "colour": None, "props": ()}


class Sub:
    __slots__ = ("drawing", "handles", "layer", "kinds", "name")

    def __init__(self, drawing, handles=(), layer=None, kinds=None, name=None):
        self.drawing = drawing
        self.handles = set(handles)
        self.layer = layer
        self.kinds = kinds
        self.name = name

    def wants(self, kind, layer) -> bool:
        if self.layer is None and not self.kinds:
            return False
        if self.kinds and kind not in self.kinds:
            return False
        if self.layer is not None and not layer_match(self.layer, layer or ""):
            return False
        return True


def layer_match(pattern: str, layer: str) -> bool:
    p = (pattern or "*").strip()
    if p in ("", "*"):
        return True
    return fnmatch.fnmatchcase(layer.lower(), p.lower()) or (p.endswith("*") and layer.lower().startswith(p[:-1].lower()))


def watch(graph, node_id: str, sub: Sub) -> None:
    with LOCK:
        SUBS.setdefault(graph, {})[node_id] = sub


def forget(graph, node_id: str) -> None:
    with LOCK:
        subs = SUBS.get(graph)
        if subs is not None:
            subs.pop(node_id, None)


def expire_hits(drawing, hit_fn) -> int:
    with LOCK:
        todo = []
        for graph, subs in list(SUBS.items()):
            for nid, sub in list(subs.items()):
                if sub.drawing is drawing and hit_fn(sub):
                    todo.append((graph, nid))
    if not todo:
        return 0
    from app.graph import session

    touched = set()
    for graph, nid in todo:
        with graph.lock:
            graph.expire(nid)
        touched.add(id(graph))
    for s in list(session.SESSIONS.values()):
        if s.graph is not None and id(s.graph) in touched:
            s.request(60)
    return len(todo)


def on_commit(doc, tx) -> None:
    if not SUBS:
        return
    changed = [k[1] for k in tx.before if k[0] == "e"]
    layers = any(k[0] == "t" and str(k[1]) == "layers" for k in tx.before)
    if not changed and not layers:
        return
    d = doc.drawing
    seen = []
    for h in changed:
        now = d.ents.get(h)
        before = tx.before.get(("e", h))
        seen.append((h, now.kind if now is not None else None, now.layer if now is not None else None, before.get("kind") if isinstance(before, dict) else None, before.get("layer") if isinstance(before, dict) else None))

    def hit(sub: Sub) -> bool:
        if layers and sub.layer is not None:
            return True
        for h, kind, layer, bkind, blayer in seen:
            if h in sub.handles:
                return True
            if kind is not None and sub.wants(kind, layer):
                return True
            if bkind is not None and sub.wants(bkind, blayer):
                return True
        return False

    expire_hits(d, hit)


def on_event(msg: dict) -> None:
    if not SUBS or msg.get("type") != "doc" or msg.get("reason") not in ("undo", "redo"):
        return
    from app.doc.service import service

    try:
        doc = service.get(str(msg.get("id")))
    except Exception:
        return
    expire_hits(doc.drawing, lambda sub: True)


def install() -> None:
    from app.doc import commit_hooks, events

    if on_commit not in [fn for _p, fn in commit_hooks.HOOKS]:
        commit_hooks.register(90, on_commit)
        events.subscribe(on_event)
