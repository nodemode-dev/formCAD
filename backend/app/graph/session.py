import copy
import threading
import time

from app.doc import events
from app.graph import model, solver, store

SESSIONS: dict = {}
LOCK = threading.RLock()
STATE = {"installed": False}


def install() -> None:
    with LOCK:
        if STATE["installed"]:
            return
        STATE["installed"] = True
    events.subscribe(on_event)


def on_event(msg: dict) -> None:
    if msg.get("type") == "docs" and msg.get("reason") == "close":
        drop_doc(str(msg.get("id")))
        return
    if msg.get("type") != "doc" or msg.get("reason") not in ("undo", "redo"):
        return
    for sess in list(SESSIONS.values()):
        if sess.doc_id == msg.get("id"):
            sess.refresh()


def drop_doc(doc_id: str) -> None:
    with LOCK:
        gone = [k for k in SESSIONS if k[0] == doc_id]
        sessions = [SESSIONS.pop(k) for k in gone]
    for s in sessions:
        s.stop()


def of(doc, gid: str) -> "Session":
    install()
    rec = store.get(doc.drawing, gid)
    if rec is None:
        raise store.StoreError("There is no graph %s." % gid)
    key = (doc.id, rec["id"])
    with LOCK:
        sess = SESSIONS.get(key)
        if sess is None or sess.doc is not doc:
            sess = Session(doc, rec["id"])
            SESSIONS[key] = sess
    sess.sync()
    return sess


class Session:
    def __init__(self, doc, gid: str):
        self.doc = doc
        self.doc_id = doc.id
        self.gid = gid
        self.graph = None
        self.hash = ""
        self.cond = threading.Condition()
        self.pending = False
        self.running = False
        self.deadline = 0.0
        self.want_all = False
        self.thread = None
        self.solves = 0
        self.last = None
        self.error = ""
        self.changed: set = set()

    def sync(self) -> list:
        rec = store.get(self.doc.drawing, self.gid)
        if rec is None:
            if self.graph is not None:
                self.graph.abort.set()
            return []
        defn = rec["definition"]
        digest = store.digest(defn)
        if self.graph is None:
            self.graph = model.Graph.from_definition(copy.deepcopy(defn), self.gid)
            self.hash = digest
            return []
        if digest == self.hash:
            return []
        with self.graph.lock:
            try:
                expired = self.graph.apply_definition(copy.deepcopy(defn))
            except model.GraphRefused:
                self.graph = model.Graph.from_definition(copy.deepcopy(defn), self.gid)
                expired = list(self.graph.nodes)
            self.hash = digest
        return expired

    def refresh(self) -> None:
        expired = self.sync()
        publish(self, "definition", {"expired": expired})
        if expired and self.graph is not None:
            self.request(0)

    def request(self, delay_ms: float = 0.0, expire_all: bool = False) -> None:
        if self.graph is None:
            return
        with self.cond:
            at = time.monotonic() + max(0.0, float(delay_ms)) / 1000.0
            if self.pending:
                self.deadline = min(self.deadline, at)
            else:
                self.pending = True
                self.deadline = at
            self.want_all = self.want_all or expire_all
            if self.running:
                self.graph.abort.set()
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.loop, name="graph-%s" % self.gid, daemon=True)
                self.thread.start()
            self.cond.notify_all()

    def cancel(self) -> None:
        with self.cond:
            self.pending = False
            self.want_all = False
            if self.graph is not None and self.running:
                self.graph.abort.set()
            self.cond.notify_all()

    def stop(self) -> None:
        self.cancel()

    def loop(self) -> None:
        while True:
            with self.cond:
                while True:
                    if not self.pending:
                        self.thread = None
                        self.cond.notify_all()
                        return
                    wait = self.deadline - time.monotonic()
                    if wait <= 0:
                        break
                    self.cond.wait(wait)
                self.pending = False
                every = self.want_all
                self.want_all = False
                self.running = True
                self.graph.abort.clear()
            try:
                self.run_once(every)
            except Exception as err:
                self.error = "%s: %s" % (type(err).__name__, err)
                publish(self, "error", {"message": self.error})
            with self.cond:
                self.running = False
                self.cond.notify_all()

    def run_once(self, every: bool) -> None:
        g = self.graph
        self.error = ""
        self.changed = set()

        def on_node(n, phase):
            if phase != "computing":
                self.changed.add(n.id)
            publish(self, "node", {"node": n.id, "state": n.state, "level": n.level(), "phase": phase})

        publish(self, "start", {})
        rep = solver.solve(g, self.doc.drawing, every, None, on_node)
        self.solves += 1
        self.last = rep
        publish(self, "solved", {"changed": sorted(self.changed), "ms": round(rep.ms, 2), "aborted": rep.aborted, "ran": len(rep.ran), "failed": len(rep.failed), "digest": rep.digest})

    def wait(self, timeout: float = 600.0) -> bool:
        end = time.monotonic() + timeout
        with self.cond:
            while self.pending or self.running:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self.cond.wait(min(left, 0.2))
        return True

    def busy(self) -> bool:
        return self.pending or self.running

    def state(self, first: int = 6) -> dict:
        g = self.graph
        with g.lock:
            nodes = {}
            for nid, n in g.nodes.items():
                outs = {name: solver.summarise(tree, first) for name, tree in n.outputs.items()}
                nodes[nid] = {"state": n.state, "level": n.level(), "messages": copy.deepcopy(n.messages), "runs": n.runs, "ms": round(n.ms, 2), "missing": n.missing, "outputs": outs}
            return {"graph": self.gid, "busy": self.busy(), "solving": self.running, "pending": self.pending, "rev": g.rev, "solves": self.solves, "error": self.error, "report": self.last.to_dict() if self.last is not None else None, "problems": list(g.problems), "readonly": g.readonly, "nodes": nodes}


def publish(sess: Session, reason: str, extra: dict) -> None:
    msg = {"type": "graph", "id": sess.doc_id, "graph": sess.gid, "reason": reason}
    msg.update(extra)
    events.publish(msg)
