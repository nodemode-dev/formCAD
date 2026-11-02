from dataclasses import dataclass, field
from typing import ClassVar

from app.doc import geom
from app.doc.entities import Entity, entity_kind

MAX_POLES = 50000
MAX_DEGREE = 25


@entity_kind
@dataclass
class NurbsCurve(Entity):
    kind: ClassVar[str] = "nurbscurve"
    POINT_LISTS: ClassVar[tuple] = ("poles",)
    name: str = ""
    degree: int = 3
    poles: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    knots: list = field(default_factory=list)
    mults: list = field(default_factory=list)
    periodic: bool = False
    source: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)

    def bounds(self):
        return geom.bounds_of_points(self.poles)

    def snap_points(self):
        from app.nurbs3d.form import FormError, NurbsForm

        try:
            form = NurbsForm.from_entity(self)
        except FormError:
            return []
        lo, hi = form.domain()
        return [form.point(lo), form.point(hi)]

    def record(self) -> dict:
        return {"degree": self.degree, "poles": [list(q) for q in self.poles], "weights": list(self.weights), "knots": list(self.knots), "mults": list(self.mults), "periodic": self.periodic}

    def set_record(self, rec: dict) -> None:
        self.degree = int(rec["degree"])
        self.poles = [[float(c) for c in q] for q in rec["poles"]]
        self.weights = [float(w) for w in rec.get("weights") or []]
        self.knots = [float(k) for k in rec["knots"]]
        self.mults = [int(m) for m in rec["mults"]]
        self.periodic = bool(rec.get("periodic", False))

    def apply_transform(self, xf) -> None:
        self.poles = [xf.pt(q) for q in self.poles]

    def valid(self):
        if not super().valid():
            return False
        if not (1 <= self.degree <= MAX_DEGREE) or not (2 <= len(self.poles) <= MAX_POLES):
            return False
        if len(self.knots) != len(self.mults) or len(self.knots) < 2:
            return False
        if self.weights and len(self.weights) != len(self.poles):
            return False
        total = sum(self.mults)
        return total - self.mults[0] == len(self.poles) if self.periodic else total == len(self.poles) + self.degree + 1
