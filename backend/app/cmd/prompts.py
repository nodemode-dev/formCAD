import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.cmd import units
from app.doc import geom


class InputError(Exception):
    pass


@dataclass
class Input:
    kind: str
    value: Any = None
    from_default: bool = False
    text: str = ""

    def is_(self, kind: str, value=None) -> bool:
        return self.kind == kind and (value is None or self.value == value)


@dataclass
class Prompt:
    message: str
    accepts: tuple = ("point",)
    options: list = field(default_factory=list)
    default: Any = None
    default_text: str = ""
    base: Any = None
    free_text: bool = False
    integer: bool = False
    positive: bool = False
    nonneg: bool = False
    minimum: Any = None
    maximum: Any = None
    rect_corner: bool = False
    absolute_angle: bool = True
    select: bool = False
    pick_one: bool = False
    preselect: bool = True
    hint: str = ""

    def kind(self) -> str:
        if self.select:
            return "select"
        if self.free_text:
            return "text"
        if "point" in self.accepts:
            return "point"
        if any(a in self.accepts for a in ("number", "distance", "angle", "int")):
            return "number"
        if self.options:
            return "keyword"
        return "text"


@dataclass
class Env:
    last: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    aunits: int = 0
    angbase: float = 0.0
    angdir: int = 0
    lunits: int = 2
    luprec: int = 4
    aprec: int = 0
    cursor_angle: float = 0.0
    tracking: Any = None


def format_prompt(p: Prompt) -> str:
    msg = p.message
    if p.options:
        kw = "/".join(p.options)
        if msg.endswith("?"):
            s = "%s [%s]" % (msg, kw)
        elif not msg:
            s = "[%s]" % kw
        else:
            s = "%s or [%s]" % (msg, kw)
    else:
        s = msg
    if p.default_text:
        s += " <%s>" % p.default_text
    return s + ":"


def shortcut_of(keyword: str) -> str:
    last = -1
    for i, ch in enumerate(keyword):
        if ch.isupper() or ch.isdigit():
            last = i
    if last < 0:
        return keyword[:1].lower()
    return keyword[: last + 1].lower()


def match_keyword(options, text: str):
    t = text.strip().lower()
    if t.startswith("_"):
        t = t[1:]
    if not t:
        return None
    for kw in options:
        if t == kw.lower() or t == shortcut_of(kw):
            return kw
    for kw in options:
        sc = shortcut_of(kw)
        if len(t) > len(sc) and kw.lower().startswith(t):
            return kw
    return None


OSNAP_WORDS = ("endpoint", "midpoint", "center", "gcenter", "node", "quadrant", "intersection", "apparent", "extension", "insertion", "perpendicular", "tangent", "nearest", "parallel", "none")
FILTERS = (".xy", ".xz", ".yz", ".x", ".y", ".z")


def modifier_kind(text: str):
    t = text.strip().lower()
    if t.startswith("_"):
        t = t[1:]
    if not t:
        return None
    if t == "from":
        return "from"
    if t in ("m2p", "mtp"):
        return "m2p"
    if t == "tt":
        return "tt"
    if len(t) >= 3 and "tracking".startswith(t) or t == "tk":
        return "tk"
    if t in FILTERS:
        return t
    if t.startswith("<") and len(t) > 1 and not re.match(r"^<+\s*$", t):
        return "angle"
    if len(t) >= 3 and t.isalpha():
        for w in OSNAP_WORDS:
            if w.startswith(t):
                return "osnap:" + w
    return None


def parse_point(text: str, env: Env):
    t = text.strip()
    if not t:
        return None
    t = t.lstrip("*")
    if t.startswith("#"):
        t = t[1:]
    relative = False
    if t.startswith("@"):
        relative = True
        t = t[1:]
    t = t.lstrip("*")
    origin = env.last if relative else [0.0, 0.0, 0.0]
    if t == "":
        return list(env.last) if relative else None
    if "<" in t:
        m = re.match(r"^(.*?)(<{1,3})(.*)$", t)
        if not m:
            return None
        d = units.parse_distance(m.group(1))
        if d is None:
            return None
        marks = len(m.group(2))
        try:
            if marks == 1:
                a = units.parse_angle(m.group(3), env.aunits)
                if a is None:
                    return None
                a = units.direction_from_angle(a, env.angbase, env.angdir)
            elif marks == 2:
                a = units.parse_angle(m.group(3), 0)
            else:
                a = units.parse_angle(m.group(3), env.aunits)
        except ValueError as err:
            raise InputError(str(err))
        if a is None:
            return None
        return geom.polar(origin, d, a)
    if "," in t:
        parts = t.split(",")
        if len(parts) not in (2, 3):
            return None
        vals = [units.parse_distance(p) for p in parts]
        if any(v is None for v in vals):
            return None
        return [origin[0] + vals[0], origin[1] + vals[1], 0.0]
    return None


def _number_for(p: Prompt, text: str, env: Env):
    if "int" in p.accepts or p.integer:
        if re.fullmatch(r"[+-]?\d+", text.strip()):
            return int(text.strip())
        v = units.parse_distance(text)
        if v is not None and v == int(v):
            return int(v)
        return None
    if "angle" in p.accepts:
        try:
            a = units.parse_angle(text, env.aunits)
        except ValueError as err:
            raise InputError(str(err))
        if a is None:
            return None
        return units.direction_from_angle(a, env.angbase, env.angdir) if p.absolute_angle else (-a if env.angdir else a)
    if "number" in p.accepts or "distance" in p.accepts:
        return units.parse_distance(text)
    return None


def check_number(p: Prompt, v):
    if not math.isfinite(v):
        raise InputError("Requires a finite number.")
    if p.positive and v <= 0:
        raise InputError("Value must be positive and nonzero.")
    if p.nonneg and v < 0:
        raise InputError("Requires a positive number.")
    if p.minimum is not None and v < p.minimum:
        raise InputError("Value must be at least %s." % p.minimum)
    if p.maximum is not None and v > p.maximum:
        raise InputError("Value must be at most %s." % p.maximum)
    return v


def default_input(p: Prompt) -> Input:
    d = p.default
    if isinstance(d, str) and p.options and match_keyword(p.options, d):
        return Input("keyword", match_keyword(p.options, d), True)
    if isinstance(d, list):
        return Input("point", list(d), True)
    if isinstance(d, (int, float)) and not isinstance(d, bool):
        return Input("number", d, True)
    return Input("text", d, True)


def resolve(p: Prompt, text: str, env: Env):
    if p.free_text:
        if text == "":
            return ("input", default_input(p) if p.default is not None else Input("enter"))
        return ("input", Input("text", text, text=text))
    t = text.strip()
    if t == "":
        if p.default is not None:
            return ("input", default_input(p))
        return ("input", Input("enter"))
    numeric = any(a in p.accepts for a in ("number", "distance", "angle", "int")) or p.integer
    if numeric:
        n = _number_for(p, t, env)
        if n is not None:
            return ("input", Input("number", check_number(p, n), text=t))
    if p.options:
        kw = match_keyword(p.options, t)
        if kw:
            return ("input", Input("keyword", kw, text=t))
    if "point" in p.accepts or "distance" in p.accepts or ("angle" in p.accepts):
        pt = parse_point(t, env)
        if pt is not None:
            return ("point", pt)
    if "point" in p.accepts:
        mod = modifier_kind(t)
        if mod:
            return ("modifier", mod if not mod.startswith("<") else "angle", t)
        b = units.parse_distance(t)
        if b is not None:
            base = p.base or env.tracking
            if base is None:
                raise InputError("Direct distance entry needs a base point.")
            if p.rect_corner:
                raise InputError("Point or option keyword required.")
            return ("point", geom.polar(base, b, env.cursor_angle))
    if "text" in p.accepts:
        return ("input", Input("text", t, text=t))
    if numeric and not p.options and "point" not in p.accepts:
        raise InputError("Requires numeric distance or a point.")
    raise InputError("Point or option keyword required." if "point" in p.accepts and p.options else ("Invalid point." if "point" in p.accepts else "Invalid option keyword." if p.options else "Invalid input."))


def point_to_input(p: Prompt, pt: list, env: Env):
    if "point" in p.accepts:
        return Input("point", pt)
    base = p.base
    if base is None:
        raise InputError("A base point is needed to pick a distance.")
    if "angle" in p.accepts:
        return Input("number", geom.angle_of(base, pt))
    return Input("number", check_number(p, geom.dist(base, pt)))
