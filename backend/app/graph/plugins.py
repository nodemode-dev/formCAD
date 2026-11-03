import re
import uuid

from app.graph import registry, sdk

LOCAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SPACE_RE = re.compile(r"[^a-z0-9_.-]+")


class NodePluginError(Exception):
    pass


def namespace(plugin_id: str) -> str:
    base = str(plugin_id).split(":", 1)[-1].lower()
    space = SPACE_RE.sub("-", base).strip(".-_")
    if not space:
        raise NodePluginError("The plugin id %r cannot name a node namespace." % plugin_id)
    return space


def declare(api, local: str, *, guid: str, name: str, solve=None, run=None, inputs=(), outputs=(), nick: str = "", category: str = "Plugins", group: str = "", description: str = "", version: int = 1, multi: bool = False, icon: str = "", widget: str = "", settings=None, volatile: bool = False, obsolete_by=None, exposure: str = "primary"):
    if not isinstance(local, str) or not LOCAL_RE.match(local):
        raise NodePluginError("A node name is 1 to 64 letters, digits, dot, dash or underscore, got %r." % (local,))
    try:
        uuid.UUID(str(guid))
    except ValueError:
        raise NodePluginError("The node %s needs a uuid guid that never changes." % local)
    space = namespace(api.plugin_id)
    type_id = space + "/" + local
    for existing in registry.TYPES:
        if existing == type_id and type_id not in api.nodes:
            raise NodePluginError("The node type %s already exists." % type_id)
    nt = sdk.NodeType(id=type_id, guid=str(guid), name=name, nick=nick, category=category, group=group or space, inputs=list(inputs), outputs=list(outputs), solve=solve, run=run, version=version, obsolete_by=obsolete_by, description=description, multi=multi, icon=icon, widget=widget, exposure=exposure, library=space, settings=dict(settings or {}), volatile=volatile)
    registry.register(nt)
    if type_id not in api.nodes:
        api.nodes.append(type_id)
    return nt


def withdraw(type_ids) -> int:
    count = 0
    for type_id in list(type_ids):
        if type_id in registry.TYPES:
            registry.unregister(type_id)
            count += 1
    return count


def load_trusted() -> None:
    from app.automation import plugins
    from app.cmd import registry as commands

    commands.load_modules()
    plugins.load_enabled()


def listing() -> list:
    from app.automation import plugins

    out = []
    for item in plugins.discover():
        nodes = item.get("nodes") or []
        if not nodes and not item["id"].startswith("epn:"):
            continue
        out.append({"id": item["id"], "namespace": namespace(item["id"]), "name": item.get("name", item["id"]), "state": item.get("state", ""), "nodes": nodes, "problems": item.get("problems", [])})
    return out


def missing(types) -> list:
    registry.ensure_loaded()
    found = {}
    for type_id, guid in types:
        if registry.resolve(type_id, guid or "") is None:
            lib = type_id.split("/", 1)[0] if "/" in type_id else type_id.rsplit(".", 1)[0]
            found.setdefault(type_id, lib)
    return [{"type": t, "library": lib} for t, lib in sorted(found.items())]
