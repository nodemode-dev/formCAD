import threading
import time

from app.graph import values
from app.services import kernel

GRACE = 120.0
SWEEP_PERIOD = 5.0
SWEEP_EVERY = 200
LOCK = threading.RLock()
LEDGER: dict = {}
STATE = {"since": 0}
SOURCES: list = []


def register_source(fn) -> None:
    if fn not in SOURCES:
        SOURCES.append(fn)


def current_serial() -> int:
    try:
        return kernel.serial()
    except Exception:
        return 0


def wrap(wid: str, serial: int = 0) -> str:
    return "%d.%s" % (serial or current_serial(), wid)


def unwrap(sid: str) -> str:
    head, _, tail = str(sid).partition(".")
    return tail if tail else head


def serial_of(sid: str) -> int:
    head, _, tail = str(sid).partition(".")
    try:
        return int(head) if tail else 0
    except ValueError:
        return 0


def track(sids) -> None:
    now = time.monotonic()
    sids = list(sids)
    with LOCK:
        for sid in sids:
            LEDGER[str(sid)] = now
        STATE["since"] += len(sids)
        due = STATE["since"] >= SWEEP_EVERY
        if due:
            STATE["since"] = 0
        start = not STATE.get("timer")
        if start:
            STATE["timer"] = True
    if start:
        threading.Thread(target=sweeper, name="graph-shape-sweeper", daemon=True).start()
    if due:
        sweep()


def sweeper() -> None:
    while True:
        time.sleep(SWEEP_PERIOD)
        with LOCK:
            if not LEDGER:
                STATE["timer"] = False
                return
        try:
            sweep()
        except Exception:
            continue


def sids_of_tree(tree) -> set:
    out = set()
    if tree is None or not hasattr(tree, "items"):
        return out
    for _path, items in tree.items():
        for item in items:
            if isinstance(item, values.Shape):
                out.add(item.sid)
            elif isinstance(item, (list, tuple)):
                for sub in item:
                    if isinstance(sub, values.Shape):
                        out.add(sub.sid)
    return out


def held_by(graph) -> set:
    held = set()
    for node in list(graph.nodes.values()):
        for tree in list((node.outputs or {}).values()):
            held |= sids_of_tree(tree)
    return held


class Stale(Exception):
    pass


def checked(sid: str) -> str:
    if serial_of(sid) != current_serial():
        raise Stale("A kernel shape is from before the kernel restarted.")
    return unwrap(sid)


def session_graphs() -> list:
    try:
        from app.graph import session
    except Exception:
        return []
    return [s.graph for s in list(session.SESSIONS.values()) if s.graph is not None]


def recover(graph) -> bool:
    expired = refresh(graph) if graph is not None else []
    try:
        from app.graph import session
    except Exception:
        return False
    hit = False
    for s in list(session.SESSIONS.values()):
        if s.graph is graph:
            refresh(graph)
            s.request(0)
            hit = True
    return hit or bool(expired)


register_source(session_graphs)


def live_graphs() -> list:
    out = []
    for fn in list(SOURCES):
        try:
            out.extend(fn() or [])
        except Exception:
            continue
    return out


def free_ids(prefixed) -> None:
    serial = current_serial()
    ids = [unwrap(s) for s in prefixed if serial_of(s) == serial]
    if not ids:
        return
    try:
        kernel.call("shape_free", {"ids": ids}, 10.0)
    except Exception:
        pass


def sweep(graphs=None, force: bool = False) -> int:
    graphs = live_graphs() if graphs is None else graphs
    held = set()
    for g in graphs:
        held |= held_by(g)
    now = time.monotonic()
    serial = current_serial()
    with LOCK:
        drop = [sid for sid, born in LEDGER.items() if sid not in held and (force or now - born > GRACE)]
        for sid in drop:
            LEDGER.pop(sid, None)
        for sid in [s for s in LEDGER if serial_of(s) != serial]:
            LEDGER.pop(sid, None)
    free_ids(drop)
    return len(drop)


def release_graph(graph) -> int:
    ids = held_by(graph)
    with LOCK:
        mine = [sid for sid in ids if sid in LEDGER]
        for sid in mine:
            LEDGER.pop(sid, None)
    free_ids(mine)
    return len(mine)


def stale_nodes(graph) -> list:
    serial = current_serial()
    out = []
    for nid, node in list(graph.nodes.items()):
        sids = set()
        for tree in list((node.outputs or {}).values()):
            sids |= sids_of_tree(tree)
        if any(serial_of(s) != serial for s in sids):
            out.append(nid)
    return out


def refresh(graph) -> list:
    expired = []
    for nid in stale_nodes(graph):
        node = graph.nodes.get(nid)
        if node is not None and node.state != "blank":
            expired.extend(graph.expire(nid))
    return expired
