import copy
import math
import threading
import time
import uuid

import numpy as np

from app.graph import model, solver
from app.graph import tree as T

SLIDER = "input.slider"
METHODS = ("evolution", "annealing")
DIRECTIONS = ("minimise", "maximise")
MAX_KEPT = 12
MAX_GENES = 64
HARD_BUDGET = 1000000
MAX_POPULATION = 2000
MAX_GENERATIONS = 10000
PROGRESS_GAP = 0.15
JOBS: dict = {}
ORDER: list = []
LOCK = threading.RLock()


class OptimizeError(ValueError):
    pass


class Halt(Exception):
    pass


def number_of(tree):
    for _, items in tree.items():
        for v in items:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                return float(v)
    return None


def gene_info(g, node_id: str) -> dict:
    n = g.nodes.get(node_id)
    if n is None:
        raise OptimizeError("There is no node %s." % node_id)
    if n.type != SLIDER:
        raise OptimizeError("%s is not a number slider. Only sliders can be genes." % (n.nickname or n.type_name or n.id))
    s = n.settings
    try:
        lo, hi = float(s.get("min", 0.0)), float(s.get("max", 10.0))
    except (TypeError, ValueError):
        raise OptimizeError("The slider %s has a range that is not a number." % (n.nickname or n.id))
    if not hi > lo:
        raise OptimizeError("The slider %s has no range to search (minimum %g, maximum %g)." % (n.nickname or n.id, lo, hi))
    port = n.port("value", "in")
    tree = solver.decode_persistent(port)
    cur = number_of(tree) if tree is not None else None
    return {"node": n.id, "name": n.nickname or n.type_name or n.id, "min": lo, "max": hi, "integer": bool(s.get("integer")), "step": float(s.get("step", 0.0) or 0.0), "decimals": int(s.get("decimals", 2)), "current": lo if cur is None else min(max(cur, lo), hi)}


def fitness_port(g, node_id: str, port: str) -> tuple:
    n = g.nodes.get(node_id)
    if n is None:
        raise OptimizeError("There is no fitness node %s." % node_id)
    outs = [p.name for p in n.outs]
    if not outs:
        raise OptimizeError("The fitness node has no output.")
    if not port:
        port = outs[0]
    if port not in outs:
        raise OptimizeError("The fitness node has no output %s. Outputs: %s." % (port, ", ".join(outs)))
    return n, port


def ancestor_ids(g, target: str) -> set:
    pred = {nid: [] for nid in g.nodes}
    for w in g.wires.values():
        if w.disabled or w.src not in g.ports or w.dst not in g.ports:
            continue
        pred[g.ports[w.dst][0].id].append(g.ports[w.src][0].id)
    seen = set()
    stack = [target]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(pred.get(cur, ()))
    return seen


def pruned_copy(defn: dict, keep: set) -> "model.Graph":
    small = copy.deepcopy(defn)
    small["nodes"] = [n for n in small.get("nodes") or [] if n.get("id") in keep]
    ports = {p.get("id") for n in small["nodes"] for side in ("in", "out") for p in (n.get("ports") or {}).get(side, [])}
    small["wires"] = [w for w in small.get("wires") or [] if w.get("from") in ports and w.get("to") in ports]
    small["groups"] = []
    return model.Graph.from_definition(small, "optimize")


class Run:
    def __init__(self, defn: dict, doc, spec: dict, cancel=None, progress=None):
        probe = model.Graph.from_definition(copy.deepcopy(defn), "probe")
        if probe.readonly:
            raise OptimizeError("This graph was written by a newer version of formCAD and cannot be run here.")
        ids = [str(i) for i in spec.get("genes") or []]
        if not ids:
            raise OptimizeError("Choose at least one slider as a gene.")
        if len(ids) > MAX_GENES or len(set(ids)) != len(ids):
            raise OptimizeError("Choose between 1 and %d different sliders." % MAX_GENES)
        self.genes = [gene_info(probe, i) for i in ids]
        fnode, fport = fitness_port(probe, str(spec.get("fitness_node") or spec.get("fitness") or ""), str(spec.get("fitness_port") or ""))
        self.fitness_node, self.fitness_port = fnode.id, fport
        direction = str(spec.get("direction") or "minimise")
        if direction not in DIRECTIONS:
            raise OptimizeError("The direction is minimise or maximise.")
        self.sign = 1.0 if direction == "minimise" else -1.0
        self.direction = direction
        method = str(spec.get("method") or "evolution")
        if method not in METHODS:
            raise OptimizeError("The method is evolution or annealing.")
        self.method = method
        n = len(self.genes)
        self.population = max(min(int(spec.get("population") or 15 * n), MAX_POPULATION), 5)
        self.generations = max(1, min(int(spec.get("generations") or 100), MAX_GENERATIONS))
        self.budget = max(1, min(int(spec.get("budget") or HARD_BUDGET), HARD_BUDGET))
        self.seed = int(spec.get("seed") or 0)
        self.time_limit = float(spec.get("time_limit") or 0.0)
        self.stagnation = max(0, int(spec.get("stagnation") or 0))
        keep = ancestor_ids(probe, fnode.id)
        for gene in self.genes:
            if gene["node"] not in keep:
                raise OptimizeError("The slider %s does not feed the fitness output, so changing it cannot change the result." % gene["name"])
        self.work = pruned_copy(defn, keep)
        self.doc = doc
        self.cancel = cancel
        self.progress = progress
        self.evals = 0
        self.failures = 0
        self.best_f = math.inf
        self.best_x = None
        self.halt = ""
        self.history: list = []
        self.started = 0.0
        self.last_report = 0.0
        self.generation = 0
        self.flat = 0

    def clip(self, x):
        out = []
        for v, gene in zip(x, self.genes):
            v = min(max(float(v), gene["min"]), gene["max"])
            if gene["integer"]:
                v = float(min(max(int(math.floor(v + 0.5)), math.ceil(gene["min"])), math.floor(gene["max"])))
            out.append(v)
        return out

    def stopping(self) -> str:
        if self.halt:
            return self.halt
        if self.cancel is not None and self.cancel():
            self.halt = "cancelled"
        elif self.evals >= self.budget:
            self.halt = "budget"
        elif self.time_limit > 0 and time.monotonic() - self.started > self.time_limit:
            self.halt = "time"
        return self.halt

    def score(self, x) -> float:
        if self.stopping():
            return math.inf
        vec = self.clip(x)
        for gene, v in zip(self.genes, vec):
            n = self.work.nodes[gene["node"]]
            n.port("value", "in").persistent = solver.encode_persistent(T.DataTree.from_item(v), "number")
            self.work.expire(n.id)
        self.evals += 1
        value = math.inf
        try:
            solver.solve(self.work, self.doc, False, self.cancel, None, None, None, True)
            f = self.work.nodes[self.fitness_node]
            if f.state == "computed":
                got = number_of(f.outputs.get(self.fitness_port) or T.DataTree())
                if got is not None:
                    value = self.sign * got
        except Exception:
            value = math.inf
        if not math.isfinite(value):
            self.failures += 1
            return math.inf
        if value < self.best_f:
            self.best_f = value
            self.best_x = vec
            self.flat = 0
            if self.method == "annealing":
                self.note("improved")
        self.report(False)
        return value

    def note(self, why: str) -> None:
        self.history.append({"generation": self.generation, "evaluations": self.evals, "best": None if self.best_x is None else self.sign * self.best_f})

    def report(self, force: bool) -> None:
        now = time.monotonic()
        if self.progress is None or (not force and now - self.last_report < PROGRESS_GAP):
            return
        self.last_report = now
        self.progress({"generation": self.generation, "evaluations": self.evals, "failures": self.failures, "best": None if self.best_x is None else self.sign * self.best_f, "elapsed": round(now - self.started, 2)})

    def on_generation(self, xk=None, convergence=None):
        self.generation += 1
        before = self.history[-1]["best"] if self.history else None
        self.note("generation")
        now_best = self.history[-1]["best"]
        if before is not None and now_best is not None and abs(now_best - before) <= 1e-12 * max(1.0, abs(before)):
            self.flat += 1
        else:
            self.flat = 0
        self.report(True)
        if self.stagnation and self.flat >= self.stagnation:
            self.halt = "stagnation"
        return bool(self.stopping())

    def execute(self) -> dict:
        from scipy import optimize as so

        self.started = time.monotonic()
        bounds = [(gene["min"], gene["max"]) for gene in self.genes]
        x0 = np.array([gene["current"] for gene in self.genes], dtype=float)
        n = len(self.genes)
        try:
            if self.method == "evolution":
                popsize = max(int(math.ceil(self.population / n)), int(math.ceil(5 / n)), 1)

                def batch(X):
                    X = np.asarray(X, dtype=float)
                    return np.array([self.score(X[:, j]) for j in range(X.shape[1])], dtype=float)

                so.differential_evolution(batch, bounds, maxiter=self.generations, popsize=popsize, tol=0.0, atol=0.0, polish=False, rng=self.seed, updating="deferred", vectorized=True, callback=self.on_generation, integrality=[g["integer"] for g in self.genes], x0=x0, init="latinhypercube")
            else:
                def single(x):
                    if self.stopping():
                        raise Halt()
                    value = self.score(x)
                    if self.stopping():
                        raise Halt()
                    return value if math.isfinite(value) else 1e300

                try:
                    so.dual_annealing(single, bounds, maxiter=self.generations, maxfun=self.budget, rng=self.seed, no_local_search=True, x0=x0)
                except Halt:
                    pass
        except OptimizeError:
            raise
        if not self.halt:
            self.halt = "done"
        self.report(True)
        return self.result()

    def result(self) -> dict:
        names = {g["node"]: g for g in self.genes}
        best = None
        if self.best_x is not None:
            best = [{"node": g["node"], "name": g["name"], "value": v} for g, v in zip(self.genes, self.best_x)]
        start = [{"node": g["node"], "name": g["name"], "value": g["current"]} for g in self.genes]
        return {"direction": self.direction, "method": self.method, "seed": self.seed, "stopped": self.halt, "evaluations": self.evals, "failures": self.failures, "generations": self.generation, "best_value": None if self.best_x is None else self.sign * self.best_f, "best": best, "start": start, "history": self.history, "fitness": {"node": self.fitness_node, "port": self.fitness_port}, "seconds": round(time.monotonic() - self.started, 3), "genes": [dict(g) for g in names.values()]}


def with_genome(defn: dict, best: list) -> dict:
    out = copy.deepcopy(defn)
    values = {b["node"]: b["value"] for b in best or []}
    for node in out.get("nodes") or []:
        if node.get("id") in values:
            for p in (node.get("ports") or {}).get("in", []):
                if p.get("name") == "value":
                    p["persistent"] = solver.encode_persistent(T.DataTree.from_item(values[node["id"]]), "number")
    return out


class Job:
    def __init__(self, doc_id: str, gid: str, spec: dict):
        self.id = uuid.uuid4().hex[:12]
        self.doc_id = doc_id
        self.gid = gid
        self.spec = spec
        self.state = "queued"
        self.message = ""
        self.progress: dict = {}
        self.result = None
        self.committed = False
        self.created = time.time()
        self.finished = None
        self.stop = threading.Event()
        self.thread = None

    def view(self) -> dict:
        out = {"id": self.id, "doc": self.doc_id, "graph": self.gid, "state": self.state, "message": self.message, "progress": dict(self.progress), "committed": self.committed, "created": self.created, "finished": self.finished}
        if self.result is not None:
            out["result"] = self.result
        return out


def publish(job: Job, reason: str) -> None:
    from app.doc import events

    events.publish({"type": "graph", "id": job.doc_id, "graph": job.gid, "reason": "optimize", "job": job.id, "state": job.state, "phase": reason, "progress": dict(job.progress)})


def evict() -> None:
    while len(ORDER) > MAX_KEPT:
        old = ORDER.pop(0)
        job = JOBS.get(old)
        if job is not None and job.state in ("running", "queued"):
            ORDER.append(old)
            break
        JOBS.pop(old, None)


def start(doc, gid: str, spec: dict, commit: bool = True) -> Job:
    from app.graph import session

    sess = session.of(doc, gid)
    with sess.graph.lock:
        defn = sess.graph.to_definition()
    with LOCK:
        for j in JOBS.values():
            if j.doc_id == doc.id and j.gid == sess.gid and j.state in ("queued", "running"):
                raise OptimizeError("An optimizer run is already going on this graph. Stop it first.")
    Run(defn, doc.drawing, spec)
    job = Job(doc.id, sess.gid, copy.deepcopy(spec))
    job.progress = {"generation": 0, "evaluations": 0, "failures": 0, "best": None, "elapsed": 0.0}
    with LOCK:
        JOBS[job.id] = job
        ORDER.append(job.id)
        evict()

    def progress(p):
        job.progress = p
        publish(job, "progress")

    def work():
        job.state = "running"
        publish(job, "start")
        try:
            run = Run(defn, doc.drawing, spec, job.stop.is_set, progress)
            job.result = run.execute()
            job.state = "cancelled" if job.result["stopped"] == "cancelled" else "done"
            job.message = "Best value %s after %d evaluations." % (job.result["best_value"], job.result["evaluations"])
            if commit and job.result["best"] is not None:
                try:
                    write_back(doc, job)
                except Exception as err:
                    job.message += " The best values could not be written to the sliders: %s" % err
        except Exception as err:
            job.state = "failed"
            job.message = str(err) if isinstance(err, OptimizeError) else "%s: %s" % (type(err).__name__, err)
        job.finished = time.time()
        publish(job, "end")

    job.thread = threading.Thread(target=work, name="optimize-%s" % job.id, daemon=True)
    job.thread.start()
    return job


def write_back(doc, job: Job) -> None:
    from app.graph import store
    from app.routers import graph as routes

    best = job.result["best"]

    def apply(d):
        rec = store.need(d.drawing, job.gid)
        new = with_genome(rec["definition"], best)
        return store.update(d.drawing, job.gid, new)

    routes._edit(doc.id, "GRAPHOPTIMIZE", apply)
    routes._after(doc, job.gid, True, 0.0, False)
    job.committed = True


def get(job_id: str):
    return JOBS.get(job_id)


def cancel(job_id: str) -> bool:
    job = JOBS.get(job_id)
    if job is None:
        return False
    job.stop.set()
    return True


def listing(doc_id=None, gid=None) -> list:
    return [j.view() for j in JOBS.values() if (doc_id is None or j.doc_id == doc_id) and (gid is None or j.gid == gid)]


def run_blocking(defn: dict, spec: dict, doc=None, cancel=None, progress=None) -> dict:
    return Run(defn, doc, spec, cancel, progress).execute()
