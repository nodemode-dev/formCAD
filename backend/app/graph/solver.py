import copy
import hashlib
import json
import time

from app.graph import match, modifiers, registry, sdk
from app.graph import tree as T

NODE_BUDGET = 60.0


class Report:
    def __init__(self):
        self.order: list = []
        self.ran: list = []
        self.skipped: list = []
        self.failed: list = []
        self.kept: list = []
        self.aborted = False
        self.disabled = False
        self.ms = 0.0
        self.digest = ""

    def to_dict(self) -> dict:
        return {"order": self.order, "ran": self.ran, "kept": self.kept, "skipped": self.skipped, "failed": self.failed, "aborted": self.aborted, "disabled": self.disabled, "ms": round(self.ms, 2), "digest": self.digest}


class SolveContext:
    def __init__(self, graph, doc=None, cancel=None, kernel=None, inputs=None, scratch=None):
        self.graph = graph
        self.doc = doc
        self.node = None
        self.inputs = inputs if inputs is not None else {}
        self.scratch = scratch if scratch is not None else {}
        self.call_index = 0
        self.deadline = None
        self._cancel = cancel
        self._kernel = kernel
        self.messages: list = []
        self.tol = float(graph.settings.get("tolerance", 0.001) or 0.001)
        self.seed = int(graph.settings.get("seed", 0) or 0)
        self.settings: dict = {}

    def cancelled(self) -> bool:
        if self.graph.abort.is_set():
            return True
        if self._cancel is not None and self._cancel():
            return True
        return self.deadline is not None and time.monotonic() > self.deadline

    def kernel(self, method: str, params: dict = None, timeout: float = 30.0):
        self.check()
        if self._kernel is not None:
            return self._kernel(method, params or {}, timeout)
        from app.services import kernel

        return kernel.call(method, params or {}, timeout)

    def check(self) -> None:
        if self.graph.abort.is_set() or (self._cancel is not None and self._cancel()):
            raise sdk.Aborted()
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise sdk.NodeError("The node used its whole time budget.", "TIMEOUT")

    def persistent(self, port: str):
        n = self.node
        if n is None:
            return None
        p = n.port(port, "in")
        return decode_persistent(p) if p is not None else None

    def warn(self, text: str, code: str = "", port: str = "") -> None:
        self.messages.append({"level": "warning", "text": str(text), "code": code, "port": port})

    def remark(self, text: str, code: str = "", port: str = "") -> None:
        self.messages.append({"level": "remark", "text": str(text), "code": code, "port": port})

    def error(self, text: str, code: str = "", port: str = "") -> None:
        raise sdk.NodeError(text, code, port)


def decode_persistent(p):
    raw = p.persistent
    if not isinstance(raw, dict) or "tree" not in raw:
        return None
    kind = raw.get("type")
    return T.from_map(raw["tree"], kind if kind in sdk.KINDS and kind != "any" else None)


def encode_persistent(tree: T.DataTree, kind: str = "any") -> dict:
    return {"type": kind, "tree": T.to_map(tree, kind if kind != "any" else None)}


def merge_trees(trees: list) -> T.DataTree:
    if len(trees) == 1:
        return trees[0]
    out = T.DataTree()
    for t in trees:
        for path, items in t.items():
            out.extend(path, items)
    return out


def gather(g, n, decl) -> T.DataTree:
    p = n.port(decl.name, "in")
    srcs = g.sources_of(p.id)
    if srcs:
        trees = []
        for sid in srcs:
            sn, _, sp = g.ports[sid]
            trees.append(sn.outputs.get(sp.name) or T.DataTree())
        return merge_trees(trees)
    stored = decode_persistent(p)
    if stored is not None:
        return stored
    return T.DataTree()


def coerce_tree(tree: T.DataTree, kind: str, port: str) -> T.DataTree:
    if kind in ("any", "geometry", "docref"):
        return tree
    out = T.DataTree()
    for path, items in tree.items():
        row = []
        for v in items:
            try:
                row.append(sdk.coerce(kind, v))
            except TypeError as err:
                raise sdk.NodeError("Input %s: %s" % (port, err), "TYPE_MISMATCH", port)
        out.set_branch(path, row)
    return out


def digest_of(g, ids) -> str:
    h = hashlib.sha256()
    for nid in ids:
        n = g.nodes.get(nid)
        if n is None:
            continue
        h.update(nid.encode())
        for name in sorted(n.outputs):
            h.update(name.encode())
            h.update(json.dumps(T.to_json(n.outputs[name]), sort_keys=True, default=repr).encode())
    return h.hexdigest()


def run_node(ctx, n) -> tuple:
    nt = n.ntype
    ins = []
    for decl in nt.inputs:
        raw = gather(ctx.graph, n, decl)
        ins.append((decl, raw))
    ctx.node = n
    ctx.settings = copy.deepcopy(n.settings)
    ctx.messages = []
    ctx.call_index = 0
    ctx.deadline = time.monotonic() + float(ctx.graph.settings.get("time_budget", NODE_BUDGET) or NODE_BUDGET)
    out_mods = [dict(p.mods) for p in n.outs]
    if nt.run is not None and not nt.placeholder:
        trees = {}
        for decl, raw in ins:
            mods = dict(n.port(decl.name, "in").mods)
            tr = modifiers.apply(T.DataTree.coerce(raw), mods, ctx.seed)
            if tr.count == 0 and decl.is_optional:
                tr = T.DataTree.from_item(decl.default)
            elif tr.count == 0:
                return ({o.name: T.DataTree() for o in nt.outputs}, ctx.messages + [{"level": "warning", "text": "input %s has no data" % decl.name, "code": "NO_DATA", "port": decl.name}])
            trees[decl.name] = coerce_tree(tr, decl.kind, decl.name)
        res = nt.run(ctx, trees)
        outs = {}
        for i, o in enumerate(nt.outputs):
            v = (res or {}).get(o.name)
            tr = T.DataTree.coerce(v) if v is not None else T.DataTree()
            if out_mods[i]:
                tr = modifiers.apply(tr, out_mods[i], ctx.seed)
            outs[o.name] = tr
        return outs, ctx.messages
    mi = []
    for decl, raw in ins:
        p = n.port(decl.name, "in")
        mi.append(match.MatchInput(decl.name, coerce_tree(T.DataTree.coerce(raw), decl.kind, decl.name) if decl.access != "tree" else raw, p.access, decl.is_optional, decl.default, dict(p.mods)))
    nouts = len(nt.outputs)
    call_msgs: list = []

    def fn(*args):
        ctx.check()
        ctx.call_index += 1
        try:
            out = nt.solve(ctx, *args)
        except sdk.NodeWarning as w:
            call_msgs.append({"level": "warning", "text": w.message, "code": w.code or "WARNING", "port": w.port})
            if w.has_result:
                return out_shape(w.result, nouts)
            return match.NULLED
        return out_shape(out, nouts)

    try:
        res = match.run(mi, fn, nouts, n.matching, None, bool(nt.multi), out_mods, ctx.seed, ctx.cancelled)
    except match.MatchCancelled:
        ctx.check()
        raise sdk.Aborted()
    except T.TreeError as err:
        raise sdk.NodeError(str(err), getattr(err, "code", "TREE") or "TREE")
    msgs = list(ctx.messages) + call_msgs
    seen = set()
    for m in res.messages:
        key = (m.code, m.port, m.text)
        if m.code == "NULL_INPUT":
            key = ("NULL_INPUT",)
        if key in seen:
            continue
        seen.add(key)
        msgs.append({"level": m.level, "text": m.text, "code": m.code, "port": m.port or ""})
    outs = {}
    for o, tr in zip(nt.outputs, res.trees):
        outs[o.name] = tr
    return outs, msgs


def out_shape(value, nouts: int):
    if nouts == 0:
        return ()
    if nouts == 1:
        return value
    if not isinstance(value, (tuple, list)) or len(value) != nouts:
        raise sdk.NodeError("The node returned %s where %d outputs were expected." % ("a value" if not isinstance(value, (tuple, list)) else "%d values" % len(value), nouts), "BAD_RETURN")
    return value


def solve(g, doc=None, expire_all: bool = False, cancel=None, on_node=None, inputs=None, kernel=None, force: bool = False) -> Report:
    registry.ensure_loaded()
    rep = Report()
    t0 = time.monotonic()
    if not g.settings.get("enabled", True) and not force:
        rep.disabled = True
        return rep
    with g.lock:
        for n in g.nodes.values():
            if n.state == "failed":
                g.expire(n.id)
            elif n.state in ("collecting", "computing"):
                n.state = "blank"
                n.epoch += 1
        if expire_all:
            g.expire_all()
        for nid in g.rebind_types():
            g.expire(nid)
        order = g.order()
        from app.graph import loops

        held, order = loops.plan(g, order)
    rep.order = list(order)
    ctx = SolveContext(g, doc, cancel, kernel, inputs)
    g.solving = True
    try:
        for nid in order:
            if g.abort.is_set() or (cancel is not None and cancel()):
                rep.aborted = True
                break
            if nid in held:
                continue
            with g.lock:
                n = g.nodes.get(nid)
                if n is None:
                    continue
                if n.state in ("computed", "skipped") or (n.state == "failed"):
                    rep.kept.append(nid)
                    continue
                epoch = n.epoch
                if not n.enabled:
                    n.state, n.outputs, n.messages = "skipped", {}, []
                    rep.skipped.append(nid)
                    emit(on_node, n, "skipped")
                    continue
                n.state = "computing"
            emit(on_node, n, "computing")
            t1 = time.monotonic()
            outs, msgs, failure = {}, [], None
            try:
                if n.missing:
                    raise sdk.NodeError("The node type %s is not installed. Its data and wires are kept." % n.type, "MISSING_NODE")
                outs, msgs = run_node(ctx, n)
            except sdk.Aborted:
                with g.lock:
                    if n.epoch == epoch:
                        n.state = "blank"
                rep.aborted = True
                break
            except sdk.NodeMessage as err:
                failure = {"level": "error", "text": err.message, "code": err.code or "ERROR", "port": err.port}
            except T.TreeError as err:
                failure = {"level": "error", "text": str(err), "code": getattr(err, "code", "TREE") or "TREE", "port": ""}
            except Exception as err:
                failure = {"level": "error", "text": "%s: %s" % (type(err).__name__, err), "code": "EXCEPTION", "port": ""}
            if failure is None and (g.abort.is_set() or (cancel is not None and cancel())):
                with g.lock:
                    if n.epoch == epoch:
                        n.state = "blank"
                rep.aborted = True
                break
            with g.lock:
                if g.nodes.get(nid) is not n or n.epoch != epoch:
                    continue
                n.ms = (time.monotonic() - t1) * 1000.0
                n.runs += 1
                if failure is not None:
                    n.state, n.outputs, n.messages = "failed", {}, [failure]
                    rep.failed.append(nid)
                else:
                    n.state, n.outputs, n.messages = "computed", outs, msgs + loop_messages(g, n)
                    rep.ran.append(nid)
            emit(on_node, n, n.state)
    finally:
        g.solving = False
    rep.ms = (time.monotonic() - t0) * 1000.0
    if not rep.aborted:
        with g.lock:
            rep.digest = digest_of(g, order)
    return rep


def loop_messages(g, n) -> list:
    mine = {p.id for p in n.ins + n.outs}
    if any(w.disabled and (w.src in mine or w.dst in mine) for w in g.wires.values()):
        return [{"level": "error", "text": "A wire at this node closes a loop and is disabled.", "code": "CYCLE", "port": ""}]
    return []


def emit(fn, n, phase) -> None:
    if fn is None:
        return
    try:
        fn(n, phase)
    except Exception:
        pass


def summarise(tree: T.DataTree, first: int = 6) -> dict:
    items = []
    for _, branch in tree.items():
        for v in branch:
            if len(items) >= first:
                break
            items.append(T.format_item(v))
    return {"branches": tree.count, "items": tree.item_count, "first": items}
