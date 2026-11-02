import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from app.cmd.context import CommandError
from app.doc import hatchfill as H
from app.doc import loops as L
from app.doc import patterns
from app.doc.entities import Hatch, LwPolyline
from app.sysvars import registry as sv

STYLE_NAMES = ("normal", "outer", "ignore")
STYLE_WORDS = {"normal": 0, "outer": 1, "ignore": 2}
ORIGIN_WORDS = {"current": 0, "use current": 0, "bottom left": 1, "bottom right": 2, "top right": 3, "top left": 4, "center": 5, "centre": 5}
MAX_HATCH_LOOPS = 1000
MAX_PICKS = 256
NOT_FOUND = "Valid hatch boundary not found."
NO_OBJECTS = "No closed boundary objects selected."
NO_INPUT = "Give internal points or boundary handles."


@dataclass
class HatchSettings:
    pattern: str = "ANSI31"
    scale: float = 1.0
    angle: float = 0.0
    associative: bool = True
    separate: bool = False
    origin: list = field(default_factory=lambda: [0.0, 0.0])
    origin_mode: int = 0
    island: int = 0
    gap: float = 0.0
    draw_order: int = 3
    transparency: Any = "ByLayer"
    annotative: bool = False
    retain: int = 0
    gradient: Optional[dict] = None
    boundary: Optional[list] = None


def color_value(value):
    try:
        return sv.parse_color(value)
    except sv.SysvarError:
        raise CommandError("Invalid colour %s." % value)


def default_gradient(ctx) -> dict:
    c1 = ctx.var("GRADCOLOR1")
    c2 = ctx.var("GRADCOLOR2")
    tint = float(ctx.var("GRADTINT"))
    return {"name": str(ctx.var("GRADNAME")).upper(), "color1": c1, "color2": c2, "tint": tint if tint else 1.0, "one": tint != 0.0, "angle": math.radians(float(ctx.var("GRADANGLE"))), "centered": bool(ctx.var("GRADCENTERED"))}


def read_settings(ctx) -> HatchSettings:
    st = HatchSettings()
    st.pattern = str(ctx.var("HPNAME")).upper()
    st.scale = float(ctx.var("HPSCALE"))
    st.angle = math.radians(float(ctx.var("HPANG")))
    st.associative = bool(ctx.var("HPASSOC"))
    st.separate = bool(ctx.var("HPSEPARATE"))
    o = ctx.var("HPORIGIN")
    st.origin = [float(o[0]), float(o[1])]
    st.origin_mode = int(ctx.var("HPORIGINMODE"))
    st.island = int(ctx.var("HPISLAND"))
    st.gap = float(ctx.var("HPGAPTOL"))
    st.draw_order = int(ctx.var("HPDRAWORDER"))
    st.transparency = ctx.var("HPTRANSP")
    st.annotative = bool(ctx.var("HPANNOTATIVE"))
    st.retain = int(ctx.var("HPBOUND"))
    return st


def store_settings(ctx, st: HatchSettings) -> None:
    ctx.setvar("HPNAME", st.pattern)
    ctx.setvar("HPSCALE", st.scale)
    ctx.setvar("HPANG", math.degrees(st.angle))
    ctx.setvar("HPASSOC", 1 if st.associative else 0)
    ctx.setvar("HPSEPARATE", 1 if st.separate else 0)
    ctx.setvar("HPORIGIN", list(st.origin))
    ctx.setvar("HPORIGINMODE", st.origin_mode)
    ctx.setvar("HPISLAND", st.island)
    ctx.setvar("HPGAPTOL", st.gap)
    ctx.setvar("HPDRAWORDER", st.draw_order)
    ctx.setvar("HPTRANSP", str(st.transparency))
    ctx.setvar("HPANNOTATIVE", 1 if st.annotative else 0)
    ctx.setvar("HPBOUND", st.retain)


def store_gradient(ctx, g: dict) -> None:
    ctx.setvar("GRADNAME", g["name"])
    ctx.setvar("GRADCOLOR1", g["color1"])
    if g.get("color2") is not None:
        ctx.setvar("GRADCOLOR2", g["color2"])
    ctx.setvar("GRADANGLE", math.degrees(g["angle"]))
    ctx.setvar("GRADCENTERED", 1 if g["centered"] else 0)
    ctx.setvar("GRADTINT", float(g["tint"]) if g.get("one") else 0.0)


def parse_transparency(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = float(value)
    else:
        s = str(value).strip().lower().rstrip("%")
        if s in ("bylayer", "by layer"):
            return "ByLayer"
        if s in ("byblock", "by block"):
            return "ByBlock"
        try:
            n = float(s)
        except ValueError:
            raise CommandError("Transparency is ByLayer, ByBlock or a number from 0 to 90.")
    if not 0.0 <= n <= 90.0:
        raise CommandError("Transparency is ByLayer, ByBlock or a number from 0 to 90.")
    return int(n) if n == int(n) else n


def parse_style(value) -> int:
    if isinstance(value, int) and value in (0, 1, 2):
        return value
    key = str(value).strip().lower()
    if key in STYLE_WORDS:
        return STYLE_WORDS[key]
    raise CommandError("Island detection is normal, outer or ignore.")


def parse_origin_mode(value) -> int:
    if isinstance(value, int) and 0 <= value <= 5:
        return value
    key = str(value).strip().lower()
    if key in ORIGIN_WORDS:
        return ORIGIN_WORDS[key]
    raise CommandError("Origin is current, bottom left, bottom right, top right, top left or center.")


def gradient_from(args: dict, base: Optional[dict] = None) -> dict:
    g = dict(base) if base else {"name": "LINEAR", "color1": 5, "color2": 7, "tint": 1.0, "one": False, "angle": 0.0, "centered": True}
    if "name" in args:
        name = str(args["name"]).strip().upper()
        if name not in H.GRADIENT_NAMES:
            raise CommandError("Gradient name is one of %s." % ", ".join(H.GRADIENT_NAMES))
        g["name"] = name
    for key, field_name in (("color1", "color1"), ("color", "color1"), ("color2", "color2")):
        if key in args and args[key] is not None:
            g[field_name] = color_value(args[key])
            if field_name == "color2":
                g["one"] = False
    if "tint" in args and args["tint"] is not None:
        t = float(args["tint"])
        if not -1.0 <= t <= 1.0:
            raise CommandError("Tint is between -1 and 1.")
        g["tint"] = t
        g["one"] = True
    if "angle" in args and args["angle"] is not None:
        g["angle"] = math.radians(float(args["angle"]))
    if "centered" in args and args["centered"] is not None:
        g["centered"] = bool(args["centered"])
    return g


def resolve_pattern(name_or_source, pattern_name=None) -> str:
    if name_or_source is None:
        return "ANSI31"
    text = str(name_or_source)
    looks_inline = "\n" in text or text.lstrip().startswith("*")
    if looks_inline or (os.sep in text or text.lower().endswith(".pat")) and os.path.isfile(text):
        try:
            res = patterns.load(text)
        except patterns.PatternError as err:
            raise CommandError(str(err))
        if pattern_name:
            want = str(pattern_name).upper()
        elif res["added"]:
            want = res["added"][0]
        else:
            want = None
        if want is None or not patterns.known(want):
            raise CommandError("Hatch pattern %s was not found in the pattern text." % (want or ""))
        return want
    n = text.strip().upper()
    if not patterns.known(n):
        raise CommandError('Hatch pattern "%s" is not built in and not loaded.' % text.strip())
    return n


def groups_for(ctx, st: HatchSettings, points, handles):
    doc = ctx.doc
    d = ctx.d
    groups = []
    for p in points:
        found = L.detect_at(doc, p, st.island, st.gap, st.boundary)
        if not found:
            raise CommandError(NOT_FOUND)
        groups.append({"loops": found, "seeds": [[p[0], p[1]]], "selected": []})
    if handles:
        ents = []
        for h in handles:
            e = d.get(h)
            if e is None:
                raise CommandError("Object %s was not found." % h)
            ents.append(e)
        if st.separate:
            for e in ents:
                found = L.loops_from_objects([e], st.island, st.gap)
                if found:
                    groups.append({"loops": found, "seeds": [], "selected": [e.handle]})
        else:
            found = L.loops_from_objects(ents, st.island, st.gap)
            if found:
                groups.append({"loops": found, "seeds": [], "selected": [e.handle for e in ents]})
        if not any(g["selected"] for g in groups):
            raise CommandError(NO_OBJECTS)
    if not st.separate and len(groups) > 1:
        loops, seeds, selected, seen = [], [], [], set()
        for g in groups:
            for lp in g["loops"]:
                k = L.loop_key(lp["vertices"])
                if k in seen:
                    continue
                seen.add(k)
                loops.append(lp)
            seeds.extend(g["seeds"])
            selected.extend(g["selected"])
        groups = [{"loops": loops, "seeds": seeds, "selected": selected}]
    for g in groups:
        if len(g["loops"]) > MAX_HATCH_LOOPS:
            raise CommandError("Too many boundary loops.")
    return groups


def retain_boundaries(ctx, loops, kind) -> list:
    handles = []
    if kind == 2:
        from app.doc.kinds.region import Region

        rg = Region(loops=[{"vertices": [dict(v) for v in lp["vertices"]], "outer": lp["outer"]} for lp in loops])
        handles.append(ctx.add(rg))
        return handles
    for lp in loops:
        pl = LwPolyline(vertices=[{"p": [v["p"][0], v["p"][1]], "bulge": v.get("bulge", 0.0) or 0.0, "sw": 0.0, "ew": 0.0} for v in lp["vertices"]], closed=True)
        handles.append(ctx.add(pl))
    return handles


def place(ctx, handle, sources, order):
    d = ctx.d
    ent = d.get(handle)
    space = ent.owner
    lst = d.spaces[space]
    if order not in (1, 2, 3, 4) or handle not in lst:
        return
    d._rec_space(space)
    lst.remove(handle)
    idx = [lst.index(s) for s in sources if s in lst]
    if order == 1:
        lst.insert(0, handle)
    elif order == 2:
        lst.append(handle)
    elif order == 3:
        lst.insert(min(idx) if idx else 0, handle)
    else:
        lst.insert(max(idx) + 1 if idx else len(lst), handle)


def make_hatch(ctx, st: HatchSettings, group, retain_override=None) -> int:
    d = ctx.d
    loops = [dict(lp) for lp in group["loops"]]
    name = st.pattern
    solid = patterns.is_solid(name) and not st.gradient
    kept = st.retain if retain_override is None else retain_override
    retained = []
    sources_all = []
    if kept in (1, 2):
        retained = retain_boundaries(ctx, loops, kept)
        if st.associative and kept == 1:
            for lp, h in zip(loops, retained):
                lp["sources"] = [h]
        elif st.associative and kept == 2:
            for lp in loops:
                lp["sources"] = [retained[0]]
    hatch = Hatch()
    hatch.pattern = "SOLID" if (solid or st.gradient) else name
    hatch.solid = bool(solid)
    hatch.loops = [{"vertices": [dict(v) for v in lp["vertices"]], "sources": list(lp.get("sources", [])), "outer": lp["outer"], "depth": lp.get("depth", 0)} for lp in loops]
    hatch.pattern_scale = st.scale
    hatch.pattern_angle = st.angle
    hatch.style = st.island
    hatch.origin = list(st.origin)
    hatch.origin_mode = H.ORIGIN_MODES[st.origin_mode]
    hatch.gap = st.gap
    hatch.annotative = st.annotative
    hatch.gradient = dict(st.gradient) if st.gradient else None
    hatch.associative = bool(st.associative and any(lp["sources"] for lp in hatch.loops))
    if st.annotative:
        hatch.annotation_scales = [str(ctx.d.header.get("CANNOSCALE", "1:1"))]
    if not st.gradient and not solid:
        n, fams = patterns.lookup(name)
        if n in patterns.USER:
            hatch.pattern_lines = [dict(f) for f in fams]
    ctx.stamp(hatch)
    hatch.transparency = parse_transparency(st.transparency)
    hatch.extra = {"seeds": group.get("seeds", []), "selected": group.get("selected", [])}
    if hatch.associative:
        hatch.extra["assoc_fresh"] = True
    h = ctx.add(hatch)
    for lp in hatch.loops:
        for s in lp["sources"]:
            if s not in sources_all:
                sources_all.append(s)
    if hatch.associative:
        for s in sources_all:
            src = d.get(s)
            if src is not None:
                d.modify(s)
                src.reactors = list(src.reactors) + [{"hatch": h}]
    order_sources = sources_all or list(group.get("selected", []))
    place(ctx, h, order_sources, st.draw_order)
    return h


def create_all(ctx, st: HatchSettings, groups) -> list:
    return [make_hatch(ctx, st, g) for g in groups]


def hatch_entities(ctx, handles):
    out = []
    for h in handles:
        e = ctx.d.get(h)
        if e is not None and e.kind == "hatch":
            out.append(e)
    return out


def current_line(ctx, st: HatchSettings, gradient: bool) -> str:
    if gradient and st.gradient:
        g = st.gradient
        return "Current gradient: %s Angle: %s Centered: %s" % (g["name"], ctx.fa(g["angle"]), "on" if g["centered"] else "off")
    return "Current hatch pattern: %s Scale: %s Angle: %s" % (st.pattern, ctx.fd(st.scale), ctx.fa(st.angle))
