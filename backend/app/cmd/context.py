import math

from app.cmd import units
from app.cmd.prompts import Prompt
from app.doc import geom
from app.doc.entities import Arc, Circle, Entity, Line, LwPolyline, Point
from app.sysvars import registry as sv

THICK_KINDS = (Line, Arc, Circle, Point, LwPolyline)


class CommandError(Exception):
    pass


class CommandCancel(Exception):
    pass


class Context:
    def __init__(self, runner, doc):
        self.runner = runner
        self.doc = doc
        self.d = doc.drawing
        self.mem = runner.memory

    def say(self, msg: str) -> None:
        self.runner.log(msg)

    def var(self, name: str):
        return sv.get_var(self.doc, name)

    def setvar(self, name: str, value):
        return sv.set_var(self.doc, name, value)

    def lunits(self) -> int:
        return int(self.d.header.get("LUNITS", 2))

    def luprec(self) -> int:
        return int(self.d.header.get("LUPREC", 4))

    def fd(self, v: float) -> str:
        return units.format_distance(v, self.lunits(), self.luprec())

    def fa(self, rad: float) -> str:
        h = self.d.header
        return units.format_angle(units.angle_for_display(rad, h.get("ANGBASE", 0.0), h.get("ANGDIR", 0)), int(h.get("AUNITS", 0)), int(h.get("AUPREC", 0)))

    def fp(self, p) -> str:
        return "%s,%s" % (self.fd(p[0]), self.fd(p[1]))

    def point(self, msg, options=(), default=None, base=None, rect=False, default_text="", jig=None):
        dt = default_text or (self.fp(default) if default is not None else "")
        return Prompt(msg, ("point",), list(options), default, dt, base, rect_corner=rect, jig=jig)

    def distance(self, msg, options=(), default=None, base=None, positive=False, nonneg=False, jig=None):
        dt = self.fd(default) if isinstance(default, (int, float)) else ""
        return Prompt(msg, ("distance", "point"), list(options), default, dt, base, positive=positive, nonneg=nonneg, jig=jig)

    def entity(self, msg, options=()):
        return Prompt(msg, ("entity",), list(options))

    def number(self, msg, options=(), default=None, integer=False, positive=False, minimum=None, maximum=None, default_text=""):
        dt = default_text or (str(default) if default is not None else "")
        return Prompt(msg, ("int",) if integer else ("number",), list(options), default, dt, integer=integer, positive=positive, minimum=minimum, maximum=maximum)

    def angle(self, msg, options=(), default=None, base=None, absolute=True, jig=None):
        dt = self.fa(default) if isinstance(default, (int, float)) and absolute else ("%g" % math.degrees(default) if isinstance(default, (int, float)) else "")
        pts = ("angle", "point") if base is not None else ("angle",)
        return Prompt(msg, pts, list(options), default, dt, base, absolute_angle=absolute, jig=jig)

    def keyword(self, msg, options, default=None):
        return Prompt(msg, ("keyword",), list(options), default, default or "")

    def yesno(self, msg, default="No"):
        return Prompt(msg, ("keyword",), ["Yes", "No"], default, default)

    def text(self, msg, default=None):
        return Prompt(msg, ("text",), [], default, default or "", free_text=True)

    def word(self, msg, options=(), default=None):
        return Prompt(msg, ("text",), list(options), default, default or "")

    def select(self, msg="Select objects", pick_one=False):
        return Prompt(msg, ("select",), select=True, pick_one=pick_one)

    def stamp(self, ent: Entity) -> Entity:
        h = self.d.header
        ent.layer = self.d.current_layer()
        ent.color = h.get("CECOLOR", 256)
        lt = self.d.table_get("linetypes", str(h.get("CELTYPE", "ByLayer")))
        ent.linetype = lt["name"] if lt else "ByLayer"
        ent.lineweight = h.get("CELWEIGHT", -1)
        ent.ltscale = h.get("CELTSCALE", 1.0)
        if isinstance(ent, THICK_KINDS):
            ent.thickness = float(h.get("THICKNESS", 0.0))
        return ent

    def add(self, ent: Entity) -> int:
        self.stamp(ent)
        try:
            return self.d.add_entity(ent, self.doc.current_space)
        except ValueError as err:
            raise CommandError(str(err))

    def locked(self, ent: Entity) -> bool:
        return self.d.layer_locked(ent.layer)

    def editable(self, handles) -> list:
        out = []
        for h in handles:
            e = self.d.get(h)
            if e is not None and not self.locked(e):
                out.append(e)
        return out

    def visible_entities(self):
        space = self.doc.current_space
        for e in self.d.entities(space):
            if self.d.visible(e):
                yield e

    def last_point(self) -> list:
        return list(self.doc.lastpoint)

    def set_last(self, p) -> None:
        self.doc.lastpoint = [p[0], p[1], 0.0]

    def direction(self, typed: float) -> float:
        return typed

    def ensure_finite(self, *vals) -> None:
        for v in vals:
            if not math.isfinite(v):
                raise CommandError("Invalid value.")
        return None

    def same(self, p, q) -> bool:
        return geom.same_point(p, q, self.d.tolerances["absolute"])
