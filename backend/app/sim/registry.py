import copy
import time

SOLVERS: dict = {}


class Cancelled(Exception):
    pass


class Outcome:
    def __init__(self, fields=None, summary=None, meta=None, series=None):
        self.fields = fields or {}
        self.summary = summary or {}
        self.meta = meta or {}
        self.series = series or {}


class Context:
    def __init__(self, study, material, loads, fixtures, contacts, model, limits, progress=None, stop=None, deadline=None):
        self.study = study
        self.material = material
        self.loads = loads
        self.fixtures = fixtures
        self.contacts = contacts
        self.model = model
        self.limits = limits
        self.options = dict(study.get("options") or {})
        self.groups = {}
        self._progress = progress
        self._stop = stop
        self._deadline = deadline

    def progress(self, fraction: float, phase: str = "") -> None:
        self.check()
        if self._progress is not None:
            self._progress(max(0.0, min(1.0, float(fraction))), phase)

    def check(self) -> None:
        if self._stop is not None and self._stop.is_set():
            raise Cancelled("The study was cancelled.")
        if self._deadline is not None and time.time() > self._deadline:
            raise Cancelled("The study ran past its time budget and was stopped.")


class Solver:
    def __init__(self, type, label, run, needs, options, order, mesh_order=2):
        self.type = type
        self.label = label
        self.run = run
        self.needs = tuple(needs)
        self.options = dict(options or {})
        self.order = order
        self.mesh_order = mesh_order

    def view(self) -> dict:
        return {"type": self.type, "label": self.label, "needs": list(self.needs), "options": copy.deepcopy(self.options), "mesh_order": self.mesh_order}


def register(type, label, run, needs=("material", "fixtures"), options=None, order=100, mesh_order=2):
    SOLVERS[str(type)] = Solver(type, label, run, needs, options, order, mesh_order)


MODULES = ("app.sim.solvers", "app.simnl.register", "app.topo.register", "app.gen.register", "app.flow.register")
_loaded = [False]


def load() -> None:
    if _loaded[0]:
        return
    import importlib

    for name in MODULES:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as err:
            if err.name != name:
                raise
    _loaded[0] = True


def get(type):
    load()
    s = SOLVERS.get(str(type))
    if s is None:
        raise KeyError("There is no solver for the study type %s. Types: %s." % (type, ", ".join(sorted(SOLVERS))))
    return s


def listing() -> list:
    load()
    return [s.view() for s in sorted(SOLVERS.values(), key=lambda s: (s.order, s.type))]
