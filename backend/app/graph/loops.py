import time
import uuid

from app.graph import modifiers, sdk, solver
from app.graph import tree as T

BEGIN = "flow.loop_begin"
END = "flow.loop_end"
SLOTS = ("a", "b", "c")
CEILING = 100000
DEFAULT_MAX = 100


def scope_of(n) -> str:
    return str(n.settings.get("scope") or "")


def adjacency(g, extra_wire=None) -> tuple:
    succ = {nid: [] for nid in g.nodes}
    pred = {nid: [] for nid in g.nodes}
    wires = [w for w in g.wires.values() if not w.disabled]
    if extra_wire is not None:
        wires.append(extra_wire)
    for w in wires:
        if w.src not in g.ports or w.dst not in g.ports:
            continue
        a, b = g.ports[w.src][0].id, g.ports[w.dst][0].id
        if b not in succ[a]:
            succ[a].append(b)
        if a not in pred[b]:
            pred[b].append(a)
    return succ, pred


def reach(start: str, adj: dict) -> set:
    seen = set()
    stack = list(adj.get(start, ()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()))
    return seen


def pairs(g, extra_wire=None) -> dict:
    succ, pred = adjacency(g, extra_wire)
    begins = [n for n in g.nodes.values() if n.type == BEGIN]
    out = {}
    for end in g.nodes.values():
        if end.type != END:
            continue
        up = reach(end.id, pred)
        best = None
        for b in begins:
            if b.id in up and scope_of(b) == scope_of(end):
                size = len(reach(b.id, succ))
                if best is None or size < best[0]:
                    best = (size, b.id)
        if best is not None:
            out[end.id] = best[1]
    return out


def members_of(g, begin_id: str, end_id: str, extra_wire=None) -> set:
    succ, pred = adjacency(g, extra_wire)
    return (reach(begin_id, succ) & reach(end_id, pred)) - {begin_id, end_id}


def plan(g, order: list) -> tuple:
    if not any(n.type == END for n in g.nodes.values()):
        return set(), order
    held = set()
    ends = set()
    for end_id, begin_id in pairs(g).items():
        held |= members_of(g, begin_id, end_id)
        ends.add(end_id)
    if not held:
        return held, order
    succ, _ = adjacency(g)
    for end_id in ends:
        succ[end_id] = []
    tail = set()
    for nid in held:
        tail |= reach(nid, succ)
    tail -= held
    tail -= ends
    if not tail:
        return held, order
    return held, [nid for nid in order if nid not in tail] + [nid for nid in order if nid in tail]


def scopes(g) -> list:
    out = []
    for end_id, begin_id in pairs(g).items():
        mem = members_of(g, begin_id, end_id)
        out.append({"scope": scope_of(g.nodes[end_id]), "begin": begin_id, "end": end_id, "members": [nid for nid in g.order() if nid in mem]})
    return out


def new_scope_id() -> str:
    return "loop_" + uuid.uuid4().hex[:6]


def first_item(tree, default=None):
    for _, items in tree.items():
        if items:
            return items[0]
    return default


def truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value) if value is not None else False


def pass_seed(base: int, iteration: int) -> int:
    return (int(base) * 1000003 + int(iteration) * 7919 + 1) & 0x7FFFFFFF


def begin_run(ctx, trees):
    out = {slot: trees[slot] for slot in SLOTS}
    out["iteration"] = T.DataTree.from_item(0)
    out["first"] = T.DataTree.from_item(True)
    return out


def read_inputs(ctx, end) -> dict:
    got = {}
    for decl in end.ntype.inputs:
        port = end.port(decl.name, "in")
        raw = solver.gather(ctx.graph, end, decl)
        tr = modifiers.apply(T.DataTree.coerce(raw), dict(port.mods), ctx.seed)
        if tr.count == 0 and decl.is_optional:
            tr = T.DataTree.from_item(decl.default)
        got[decl.name] = solver.coerce_tree(tr, decl.kind, decl.name)
    return got


def run_member(ctx, m) -> None:
    if not m.enabled:
        m.state, m.outputs, m.messages = "skipped", {}, []
        return
    m.epoch += 1
    m.state = "computing"
    t1 = time.monotonic()
    failure = None
    outs, msgs = {}, []
    try:
        if m.missing:
            raise sdk.NodeError("The node type %s is not installed. Its data and wires are kept." % m.type, "MISSING_NODE")
        outs, msgs = solver.run_node(ctx, m)
    except sdk.Aborted:
        m.state = "blank"
        raise
    except sdk.NodeMessage as err:
        failure = {"level": "error", "text": err.message, "code": err.code or "ERROR", "port": err.port}
    except T.TreeError as err:
        failure = {"level": "error", "text": str(err), "code": getattr(err, "code", "TREE") or "TREE", "port": ""}
    except Exception as err:
        failure = {"level": "error", "text": "%s: %s" % (type(err).__name__, err), "code": "EXCEPTION", "port": ""}
    m.ms = (time.monotonic() - t1) * 1000.0
    m.runs += 1
    if failure is not None:
        m.state, m.outputs, m.messages = "failed", {}, [failure]
        raise sdk.NodeError("%s inside the loop failed: %s" % (m.nickname or m.type_name or m.id, failure["text"]), "LOOP_MEMBER_FAILED")
    m.state, m.outputs, m.messages = "computed", outs, msgs


def end_run(ctx, trees):
    g, end = ctx.graph, ctx.node
    settings = dict(ctx.settings)
    pair = pairs(g).get(end.id)
    if pair is None:
        raise sdk.NodeError("This loop end finds no loop begin with the same scope upstream of it.", "LOOP_UNPAIRED")
    begin = g.nodes[pair]
    mem = members_of(g, pair, end.id)
    order = [nid for nid in g.order() if nid in mem]
    initial = dict(begin.outputs)
    if not all(slot in initial for slot in SLOTS):
        raise sdk.NodeError("The loop begin has no data yet.", "LOOP_NO_BEGIN")
    first = read_inputs(ctx, end)
    limit = int(first_item(first["max_iterations"], DEFAULT_MAX) or DEFAULT_MAX)
    limit = max(1, min(limit, CEILING))
    exit_wired = bool(g.sources_of(end.port("exit", "in").id)) or end.port("exit", "in").persistent is not None
    collect = bool(settings.get("collect"))
    deadline = ctx.deadline
    base_seed = ctx.seed
    state = {slot: initial[slot] for slot in SLOTS}
    history = T.DataTree()
    msgs = []
    count = 0
    reason = "max"
    try:
        for it in range(limit):
            ctx.check()
            if deadline is not None and time.monotonic() > deadline:
                reason = "time"
                break
            outs = dict(state)
            outs["iteration"] = T.DataTree.from_item(it)
            outs["first"] = T.DataTree.from_item(it == 0)
            begin.outputs = outs
            ctx.seed = pass_seed(base_seed, it)
            for nid in order:
                run_member(ctx, g.nodes[nid])
            ctx.seed = base_seed
            ctx.node, ctx.settings = end, settings
            nxt = read_inputs(ctx, end)
            state = {slot: nxt[slot] for slot in SLOTS}
            count = it + 1
            if collect:
                history.set_branch(T.Path((it,)), [v for _, items in state["a"].items() for v in items])
            if truthy(first_item(nxt["exit"], False)):
                reason = "exit"
                break
    finally:
        ctx.seed = base_seed
        ctx.node, ctx.settings = end, settings
        begin.outputs = initial
    if reason == "max" and exit_wired:
        msgs.append({"level": "warning", "text": "The loop reached its limit of %d passes before the exit test was true." % limit, "code": "LOOP_MAX", "port": "max_iterations"})
    elif reason == "time":
        msgs.append({"level": "warning", "text": "The loop stopped after %d passes because the node used its time budget." % count, "code": "LOOP_TIMEOUT", "port": ""})
    else:
        msgs.append({"level": "remark", "text": "The loop ran %d pass%s (%s)." % (count, "" if count == 1 else "es", "exit test true" if reason == "exit" else "limit reached"), "code": "LOOP_DONE", "port": ""})
    ctx.messages = msgs
    ctx.deadline = deadline
    out = {slot: state[slot] for slot in SLOTS}
    out["count"] = T.DataTree.from_item(count)
    out["history"] = history
    return out


def register_nodes() -> None:
    state_in = [sdk.Port(slot, "any", "tree", optional=True, description="Data carried into the loop and from pass to pass.") for slot in SLOTS]
    sdk.register(sdk.NodeType(id=BEGIN, guid="b5c9f3d0-7a41-4e0c-9d2e-3f6a1c8e5b10", name="Loop Begin", nick="Loop in", category="Flow", group="Loops", inputs=state_in, outputs=[sdk.Port(slot, "any", "tree") for slot in SLOTS] + [sdk.Port("iteration", "integer", "tree", description="Zero based pass number."), sdk.Port("first", "boolean", "tree", description="True on the first pass only.")], run=begin_run, settings={"scope": ""}, description="Opens a loop. The data on a, b and c enters the first pass, and later passes receive what the loop end collected."))
    end_in = [sdk.Port(slot, "any", "tree", optional=True, description="Result of this pass, carried into the next one.") for slot in SLOTS]
    end_in.append(sdk.Port("exit", "boolean", "tree", default=False, description="When true after a pass, the loop stops."))
    end_in.append(sdk.Port("max_iterations", "integer", "tree", default=DEFAULT_MAX, min=1, max=CEILING, description="Most passes the loop may run."))
    sdk.register(sdk.NodeType(id=END, guid="2e8d4a67-91b3-4c5f-8a7d-0c3b6e9f1a24", name="Loop End", nick="Loop out", category="Flow", group="Loops", inputs=end_in, outputs=[sdk.Port(slot, "any", "tree") for slot in SLOTS] + [sdk.Port("count", "integer", "tree", description="Passes that ran."), sdk.Port("history", "any", "tree", description="The a data of every pass, one branch per pass, when collecting is on.")], run=end_run, settings={"scope": "", "collect": False}, description="Closes a loop. Everything between the loop begin and this node runs again for each pass until the exit input is true or the limit is reached."))


register_nodes()
