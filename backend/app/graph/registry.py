import importlib
import pkgutil
import threading

from app.graph import sdk

_lock = threading.RLock()
TYPES: dict = {}
BY_GUID: dict = {}
LISTENERS: list = []
STATE = {"revision": 0, "loaded": False}


def register(nt: sdk.NodeType) -> sdk.NodeType:
    sdk.validate(nt)
    with _lock:
        old = TYPES.get(nt.id)
        other = BY_GUID.get(nt.guid)
        if other is not None and other.id != nt.id:
            raise ValueError("Node type %s reuses the guid of %s." % (nt.id, other.id))
        if old is not None and old.guid != nt.guid:
            raise ValueError("Node type %s changed its guid; a guid is fixed forever." % nt.id)
        TYPES[nt.id] = nt
        BY_GUID[nt.guid] = nt
        STATE["revision"] += 1
    notify()
    return nt


def unregister(type_id: str) -> None:
    with _lock:
        nt = TYPES.pop(type_id, None)
        if nt is not None:
            BY_GUID.pop(nt.guid, None)
            STATE["revision"] += 1
    notify()


def unregister_prefix(prefix: str) -> int:
    with _lock:
        ids = [i for i in TYPES if i.startswith(prefix)]
        for i in ids:
            nt = TYPES.pop(i)
            BY_GUID.pop(nt.guid, None)
        if ids:
            STATE["revision"] += 1
    if ids:
        notify()
    return len(ids)


def plugin_types(plugin_id: str) -> list:
    with _lock:
        return [nt for i, nt in TYPES.items() if i.startswith(plugin_id + "/")]


def on_change(fn) -> None:
    if fn not in LISTENERS:
        LISTENERS.append(fn)


def notify() -> None:
    for fn in list(LISTENERS):
        try:
            fn()
        except Exception:
            pass


def revision() -> int:
    return STATE["revision"]


def ensure_loaded() -> None:
    if STATE["loaded"]:
        return
    with _lock:
        if STATE["loaded"]:
            return
        STATE["loaded"] = True
        try:
            pkg = importlib.import_module("app.graph.nodes")
        except ModuleNotFoundError as err:
            if err.name not in ("app.graph.nodes",):
                raise
            return
        for info in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module("app.graph.nodes." + info.name)


def get(type_id: str):
    ensure_loaded()
    return TYPES.get(type_id)


def by_guid(guid: str):
    ensure_loaded()
    return BY_GUID.get(guid)


def resolve(type_id: str, guid: str = ""):
    nt = get(type_id)
    if nt is None and guid:
        nt = BY_GUID.get(guid)
    seen = 0
    while nt is not None and nt.obsolete_by and seen < 8:
        nxt = TYPES.get(nt.obsolete_by) or BY_GUID.get(nt.obsolete_by)
        if nxt is None:
            break
        nt = nxt
        seen += 1
    return nt


def placeholder(type_id: str, guid: str = "", name: str = "", inputs=(), outputs=()) -> sdk.NodeType:
    def missing(ctx, *args):
        raise sdk.NodeError("The node type %s is not installed. Its data and wires are kept." % type_id, "MISSING_NODE")

    lib = type_id.split("/", 1)[0] if "/" in type_id else type_id.rsplit(".", 1)[0]
    return sdk.NodeType(id=type_id, guid=guid or "00000000-0000-4000-8000-000000000000", name=name or type_id, category="Missing", group="Missing", inputs=list(inputs), outputs=list(outputs), solve=missing, run=missing, description="Missing node type %s." % type_id, exposure="hidden", library=lib, placeholder=True)


def catalogue(include_hidden: bool = False) -> list:
    ensure_loaded()
    with _lock:
        items = [nt for nt in TYPES.values() if include_hidden or nt.exposure != "hidden"]
    items.sort(key=lambda t: (t.category, t.group, t.name, t.id))
    return [nt.entry() for nt in items]
