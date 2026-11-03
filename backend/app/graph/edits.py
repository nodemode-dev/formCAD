import copy

from app.graph import model, sdk, solver
from app.graph import tree as T


class EditError(ValueError):
    pass


def port_of(g, ref, side: str = ""):
    if isinstance(ref, str) and ref in g.ports:
        found = g.ports[ref]
    elif isinstance(ref, str) and ":" in ref:
        nid, name = ref.split(":", 1)
        n = g.nodes.get(nid)
        p = n.port(name, side) if n is not None else None
        if p is None:
            raise EditError("There is no port %s." % ref)
        found = (n, p.side, p)
    elif isinstance(ref, dict) and ref.get("node"):
        n = g.nodes.get(ref["node"])
        p = n.port(str(ref.get("port")), side) if n is not None else None
        if p is None:
            raise EditError("There is no port %s." % ref)
        found = (n, p.side, p)
    else:
        raise EditError("There is no port %s." % (ref,))
    if side and found[1] != side:
        raise EditError("%s is not an %s port." % (ref, "input" if side == "in" else "output"))
    return found


def node_of(g, nid):
    n = g.nodes.get(str(nid))
    if n is None:
        raise EditError("There is no node %s." % nid)
    return n


def persistent_from(op: dict, kind: str):
    if op.get("clear"):
        return None
    if "tree" in op:
        return {"type": op.get("type") or kind, "tree": copy.deepcopy(op["tree"])}
    if "value" in op:
        return solver.encode_persistent(T.DataTree.coerce(op["value"]), op.get("type") or kind)
    raise EditError("Give value, tree or clear for persistent data.")


def op_add_node(g, op):
    n = g.add_node(str(op.get("type") or ""), float(op.get("x", 0.0) or 0.0), float(op.get("y", 0.0) or 0.0), str(op.get("id") or ""), op.get("settings"))
    for key in ("nickname", "enabled", "preview", "matching"):
        if key in op:
            setattr(n, key, op[key])
    for item in op.get("persistent") or []:
        p = n.port(str(item.get("port")), "in")
        if p is None:
            raise EditError("Node %s has no input %s." % (n.type, item.get("port")))
        p.persistent = persistent_from(item, "any")
    return {"id": n.id, "ports": {"in": {p.name: p.id for p in n.ins}, "out": {p.name: p.id for p in n.outs}}}


def op_remove_node(g, op):
    ids = op.get("ids") or [op.get("id")]
    for nid in ids:
        node_of(g, nid)
        g.remove_node(str(nid))
    return {"removed": [str(i) for i in ids]}


def op_move(g, op):
    items = op.get("nodes") or [{"id": op.get("id"), "x": op.get("x"), "y": op.get("y")}]
    for it in items:
        n = node_of(g, it.get("id"))
        if it.get("x") is not None:
            n.x = float(it["x"])
        if it.get("y") is not None:
            n.y = float(it["y"])
    return {}


def op_set(g, op):
    n = node_of(g, op.get("id"))
    changed = False
    for key in ("nickname", "preview"):
        if key in op:
            setattr(n, key, op[key] if key == "nickname" else bool(op[key]))
    if "enabled" in op and bool(op["enabled"]) != n.enabled:
        n.enabled = bool(op["enabled"])
        changed = True
    if "matching" in op:
        if op["matching"] not in sdk.MATCHING:
            raise EditError("Matching is one of %s." % ", ".join(sdk.MATCHING))
        if op["matching"] != n.matching:
            n.matching = op["matching"]
            changed = True
    if isinstance(op.get("settings"), dict):
        n.settings.update(copy.deepcopy(op["settings"]))
        changed = True
    if isinstance(op.get("persistent"), dict):
        spec = op["persistent"]
        p = n.port(str(spec.get("port") or (n.ins[0].name if n.ins else "")), "in")
        if p is None:
            raise EditError("Node %s has no input %s." % (n.id, spec.get("port")))
        decl = n.ntype.input(p.name)
        p.persistent = persistent_from(spec, decl.kind if decl is not None else "any")
        changed = True
    if isinstance(op.get("mods"), dict):
        spec = op["mods"]
        side = "out" if spec.get("side") == "out" else "in"
        p = n.port(str(spec.get("port")), side)
        if p is None:
            raise EditError("Node %s has no port %s." % (n.id, spec.get("port")))
        if "access" in spec:
            if spec["access"] not in sdk.ACCESS:
                raise EditError("Access is one of %s." % ", ".join(sdk.ACCESS))
            p.access = spec["access"]
        merged = dict(p.mods)
        merged.update({k: v for k, v in (spec.get("mods") or {}).items()})
        p.mods = model.clean_mods(merged)
        changed = True
    if changed:
        g.expire(n.id)
    return {}


def op_connect(g, op):
    s = port_of(g, op.get("from"), "out")[2]
    d = port_of(g, op.get("to"), "in")[2]
    w = g.connect(s.id, d.id, str(op.get("mode") or "replace"), str(op.get("id") or ""))
    return {"id": w.id}


def op_disconnect(g, op):
    if op.get("id"):
        g.disconnect(str(op["id"]))
        return {}
    s = port_of(g, op.get("from"), "out")[2]
    d = port_of(g, op.get("to"), "in")[2]
    hit = [w.id for w in g.wires.values() if w.src == s.id and w.dst == d.id]
    if not hit:
        raise EditError("Those ports are not joined.")
    for wid in hit:
        g.disconnect(wid)
    return {}


def op_group(g, op):
    gid = str(op.get("id") or "")
    members = [str(m) for m in (op.get("members") or []) if str(m) in g.nodes]
    grp = g.groups.get(gid) if gid else None
    if grp is None:
        grp = model.Group(gid or model.new_id("g"), str(op.get("name") or ""), str(op.get("colour") or "#8a8f98"), members)
        g.groups[grp.id] = grp
    else:
        if "name" in op:
            grp.name = str(op["name"])
        if "colour" in op:
            grp.colour = str(op["colour"])
        if "members" in op:
            grp.members = members
    return {"id": grp.id}


def op_ungroup(g, op):
    if str(op.get("id")) not in g.groups:
        raise EditError("There is no group %s." % op.get("id"))
    del g.groups[str(op["id"])]
    return {}


def op_graph(g, op):
    if "name" in op:
        g.name = str(op["name"])
        g.meta["name"] = g.name
    if isinstance(op.get("settings"), dict):
        g.settings.update(copy.deepcopy(op["settings"]))
        if any(k in op["settings"] for k in ("seed", "tolerance", "units")):
            g.expire_all()
    if isinstance(op.get("view"), dict):
        g.view = copy.deepcopy(op["view"])
    if isinstance(op.get("notes"), list):
        g.notes = copy.deepcopy(op["notes"])
    return {}


OPS = {"add_node": op_add_node, "remove_node": op_remove_node, "move": op_move, "set": op_set, "connect": op_connect, "disconnect": op_disconnect, "group": op_group, "ungroup": op_ungroup, "graph": op_graph}


def apply(g, ops: list) -> list:
    out = []
    for op in ops:
        fn = OPS.get(str(op.get("op")))
        if fn is None:
            raise EditError("Unknown graph edit %r. Use one of %s." % (op.get("op"), ", ".join(OPS)))
        out.append(fn(g, op))
    return out
