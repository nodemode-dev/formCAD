from app.graph import tree as T
from app.graph.sdk import NodeError, NodeType, NodeWarning, Port, register


def P(name, kind="any", access="item", default=None, nick="", description="", optional=False):
    return Port(name, kind, access, default, optional, nick or name, description)


def add(type_id, guid, name, nick, category, group, inputs, outputs, solve=None, run=None, description="", multi=False, settings=None, widget=""):
    return register(NodeType(id=type_id, guid=guid, name=name, nick=nick, category=category, group=group, inputs=list(inputs), outputs=list(outputs), solve=solve, run=run, description=description, multi=multi, settings=dict(settings or {}), widget=widget))


def absent(lst) -> bool:
    return not lst or (len(lst) == 1 and lst[0] is None)


def tree_absent(tree) -> bool:
    if tree is None or tree.count == 0:
        return True
    if tree.count == 1:
        row = tree.items()[0][1]
        return len(row) == 1 and row[0] is None
    return False


def head(lst, default=None):
    if lst and lst[0] is not None:
        return lst[0]
    return default


def first_item(tree, default=None):
    for _, row in tree.items():
        for v in row:
            if v is not None:
                return v
    return default


def single(value, path=None):
    return T.DataTree.from_items([value], path or T.Path((0,)))


def listing(items, path=None):
    return T.DataTree.from_items(list(items), path or T.Path((0,)))


def sort_rank(v):
    if v is None:
        return (0, 0, "")
    if isinstance(v, bool):
        return (1, int(v), "")
    if isinstance(v, (int, float)):
        return (2, v, "")
    if isinstance(v, str):
        return (3, 0, v)
    return (4, 0, repr(v))


__all__ = ["NodeError", "NodeWarning", "P", "add", "absent", "tree_absent", "head", "first_item", "single", "listing", "sort_rank", "T"]
