import copy
import math
from dataclasses import fields

from app.cmd import hatch_support as HS
from app.cmd.commands import hatch as HC
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import curves2d
from app.doc import hatchfill as H
from app.doc import loops as L
from app.doc import patterns
from app.doc import planar as P
from app.doc.entities import Hatch

OPTIONS = ["Disassociate", "Style", "Properties", "recreate Boundary", "ASsociate", "separate Hatches", "Origin", "add Point", "add Object", "remove Boundary"]
GEOMETRY_KEYS = ("add_points", "add_handles", "remove")


def clone(h):
    return Hatch.from_dict(h.to_dict())


def assign(target, work):
    for f in fields(type(target)):
        if f.name in ("handle", "owner"):
            continue
        setattr(target, f.name, copy.deepcopy(getattr(work, f.name)))


def settings_of(work):
    st = HS.HatchSettings()
    st.pattern = work.pattern
    st.scale = work.pattern_scale
    st.angle = work.pattern_angle
    st.island = work.style
    st.gap = work.gap
    return st


def find_closed(ctx, handles):
    cands = []
    if handles:
        cands = [ctx.d.get(h) for h in handles if ctx.d.get(h) is not None]
    else:
        cands = list(ctx.visible_entities())
    out = {}
    for e in cands:
        if e.kind == "region":
            continue
        cl = curves2d.closed_loop_of(e)
        if cl is not None:
            out.setdefault(L.loop_key(cl), e.handle)
    return out


def link_loops(ctx, work, handles):
    table = find_closed(ctx, handles)
    hit = 0
    for lp in work.loops:
        h = table.get(L.loop_key(lp["vertices"]))
        if h is None:
            rev = L.loop_key(P.reverse_loop(lp["vertices"]))
            h = table.get(rev)
        if h is not None:
            lp["sources"] = [h]
            hit += 1
    if not hit:
        raise CommandError("No boundary objects matching the hatch were found.")
    work.associative = True


def regroup(ctx, work, style):
    st = settings_of(work)
    st.island = style
    seeds = work.extra.get("seeds") or []
    selected = work.extra.get("selected") or []
    if seeds or selected:
        try:
            groups = HS.groups_for(ctx, st, [tuple(p) for p in seeds], list(selected))
            merged = []
            seen = set()
            for g in groups:
                for lp in g["loops"]:
                    k = L.loop_key(lp["vertices"])
                    if k not in seen:
                        seen.add(k)
                        merged.append(lp)
            if merged:
                work.loops = merged
                work.style = style
                return
        except CommandError:
            pass
    keep = 0 if style == 2 else (1 if style == 1 else 99)
    kept = [lp for lp in work.loops if int(lp.get("depth", 0 if lp.get("outer", True) else 1)) <= keep]
    if not kept:
        raise CommandError("The island style would remove every boundary.")
    work.loops = kept
    work.style = style


def split_groups(work):
    shaped = [{"vertices": lp["vertices"]} for lp in work.loops]
    depth = L.rings_depth(shaped)
    rings = [(P.flatten_loop(lp["vertices"]), L.rep_point(lp["vertices"])) for lp in work.loops]
    areas = [abs(P.loop_area(lp["vertices"])) for lp in work.loops]
    groups = {}
    for i, d in enumerate(depth):
        if d % 2 == 0:
            groups[i] = [i]
    for i, d in enumerate(depth):
        if d % 2 == 1:
            best = None
            for j, dj in enumerate(depth):
                if dj == d - 1 and P.point_in_ring(rings[i][1][0], rings[i][1][1], rings[j][0]):
                    if best is None or areas[j] < areas[best]:
                        best = j
            if best is not None:
                groups[best].append(i)
    return [[work.loops[k] for k in idx] for idx in groups.values()]


def spec_from_args(args):
    spec = {}
    for key in ("pattern", "pattern_name", "scale", "angle", "gradient", "associative", "boundary", "add_points", "add_handles", "remove", "style", "origin", "origin_mode", "separate", "recreate"):
        if key in args and args[key] is not None:
            spec[key] = args[key]
    return spec


def plan(ctx, hatch, spec):
    work = clone(hatch)
    post = {}
    if "pattern" in spec and "gradient" in spec:
        raise CommandError("Give a pattern or a gradient, not both.")
    if "pattern" in spec:
        name = HS.resolve_pattern(spec["pattern"], spec.get("pattern_name"))
        work.pattern = name
        work.solid = patterns.is_solid(name)
        work.gradient = None
        n, fams = patterns.lookup(name)
        work.pattern_lines = [dict(f) for f in fams] if n in patterns.USER else []
    if "gradient" in spec:
        if not isinstance(spec["gradient"], dict):
            raise CommandError("The gradient is an object with a name, colours, angle and centred flag.")
        work.gradient = HS.gradient_from(spec["gradient"], work.gradient)
        work.pattern = "SOLID"
        work.solid = False
        work.pattern_lines = []
    if "scale" in spec:
        v = float(spec["scale"])
        if not v > 0 or not math.isfinite(v):
            raise CommandError("Value must be positive and nonzero.")
        work.pattern_scale = v
    if "angle" in spec:
        work.pattern_angle = math.radians(float(spec["angle"]))
    if "style" in spec:
        regroup(ctx, work, HS.parse_style(spec["style"]))
    if "origin" in spec:
        o = spec["origin"]
        work.origin = [float(o[0]), float(o[1])]
        work.origin_mode = "current"
    if "origin_mode" in spec:
        work.origin_mode = H.ORIGIN_MODES[HS.parse_origin_mode(spec["origin_mode"])]
    for p in spec.get("add_points") or []:
        found = L.detect_at(ctx.doc, [float(p[0]), float(p[1])], work.style, work.gap)
        if not found:
            raise CommandError(HS.NOT_FOUND)
        seen = {L.loop_key(lp["vertices"]) for lp in work.loops}
        for lp in found:
            if L.loop_key(lp["vertices"]) not in seen:
                work.loops.append(lp)
        work.extra["seeds"] = list(work.extra.get("seeds", [])) + [[float(p[0]), float(p[1])]]
    if spec.get("add_handles"):
        ents = []
        for h in spec["add_handles"]:
            e = ctx.d.get(int(h))
            if e is None:
                raise CommandError("Object %s was not found." % h)
            ents.append(e)
        found = L.loops_from_objects(ents, work.style, work.gap)
        if not found:
            raise CommandError(HS.NO_OBJECTS)
        seen = {L.loop_key(lp["vertices"]) for lp in work.loops}
        for lp in found:
            if L.loop_key(lp["vertices"]) not in seen:
                work.loops.append(lp)
        work.extra["selected"] = list(work.extra.get("selected", [])) + [e.handle for e in ents]
    if spec.get("remove") is not None:
        idx = sorted({int(i) for i in spec["remove"]})
        if any(i < 0 or i >= len(work.loops) for i in idx):
            raise CommandError("Boundary loop numbers start at zero and must exist.")
        if len(idx) >= len(work.loops):
            raise CommandError("A hatch must keep at least one boundary loop.")
        work.loops = [lp for k, lp in enumerate(work.loops) if k not in idx]
    if len(work.loops) > HS.MAX_HATCH_LOOPS:
        raise CommandError("Too many boundary loops.")
    if "boundary" in spec:
        link_loops(ctx, work, [int(h) for h in spec["boundary"]])
    if "associative" in spec:
        if spec["associative"]:
            if not any(lp.get("sources") for lp in work.loops):
                link_loops(ctx, work, None)
            work.associative = True
        else:
            work.associative = False
    if spec.get("separate"):
        groups = split_groups(work)
        if len(groups) < 2:
            raise CommandError("The hatch has only one area to separate.")
        post["separate"] = groups
    rec = spec.get("recreate")
    if rec:
        kind = str(rec.get("type", "polyline")).lower() if isinstance(rec, dict) else "polyline"
        if kind not in ("polyline", "region"):
            raise CommandError("Boundary type is polyline or region.")
        post["recreate"] = {"type": kind, "associate": bool(rec.get("associate", False)) if isinstance(rec, dict) else False}
    return work, post


def add_reactors(ctx, handle, work):
    for lp in work.loops:
        for s in lp.get("sources", ()):
            src = ctx.d.get(s)
            if src is not None and not any(isinstance(r, dict) and r.get("hatch") == handle for r in src.reactors):
                ctx.d.modify(s)
                src.reactors = list(src.reactors) + [{"hatch": handle}]


def commit_plan(ctx, hatch, work, post, out):
    if "recreate" in post:
        kind = 2 if post["recreate"]["type"] == "region" else 1
        made = HS.retain_boundaries(ctx, work.loops, kind)
        out["boundaries"].extend(made)
        if post["recreate"]["associate"]:
            for k, lp in enumerate(work.loops):
                lp["sources"] = [made[0] if kind == 2 else made[k]]
            work.associative = True
    if "separate" in post:
        for g in post["separate"]:
            piece = clone(work)
            piece.handle = 0
            piece.loops = [dict(lp, outer=(i == 0), depth=(0 if i == 0 else 1)) for i, lp in enumerate(g)]
            h = ctx.d.add_entity(piece, hatch.owner)
            out["created"].append(h)
            if piece.associative:
                add_reactors(ctx, h, piece)
        ctx.d.erase_entity(hatch.handle)
        return
    ctx.d.modify(hatch.handle)
    assign(hatch, work)
    if work.associative:
        hatch.extra["assoc_fresh"] = True
        add_reactors(ctx, hatch.handle, work)
    out["handles"].append(hatch.handle)


def run_edit(ctx, hatches, spec):
    if not hatches:
        raise CommandError("No hatch objects were selected.")
    if len(hatches) > 1 and any(k in spec for k in GEOMETRY_KEYS):
        raise CommandError("Adding or removing boundaries works on one hatch at a time.")
    planned = [(h, *plan(ctx, h, spec)) for h in hatches]
    out = {"handles": [], "created": [], "boundaries": []}
    for h, work, post in planned:
        commit_plan(ctx, h, work, post, out)
    return out


@command("hatchedit", aliases=("he", "-hatchedit"), group="modify", label="Hatch Edit", description="Edit hatch pattern, scale, angle, style, origin, association, boundaries.", menu="Modify > Object > Hatch...")
def hatchedit_cmd(ctx):
    r = yield ctx.select("Select hatch objects")
    if r.kind != "selection":
        return
    hatches = HS.hatch_entities(ctx, r.value)
    hatches = [h for h in hatches if not ctx.locked(h)]
    if not hatches:
        ctx.say("No hatch objects were selected.")
        return
    q = yield ctx.keyword("Enter a hatch option", OPTIONS)
    if q.kind != "keyword":
        return
    k = q.value
    spec = {}
    if k == "Disassociate":
        spec["associative"] = False
    elif k == "Style":
        s = yield ctx.keyword("Enter new island detection style", ["Ignore", "Outer", "Normal"], HS.STYLE_NAMES[hatches[0].style].title())
        if s.kind != "keyword":
            return
        spec["style"] = s.value.lower()
    elif k == "Properties":
        st = settings_of(hatches[0])
        ok = yield from HC.ask_pattern(ctx, st)
        if not ok:
            return
        ok = yield from HC.ask_scale_angle(ctx, st)
        if not ok:
            return
        if st.pattern != hatches[0].pattern or hatches[0].gradient:
            spec["pattern"] = st.pattern
        spec["scale"] = st.scale
        spec["angle"] = math.degrees(st.angle)
    elif k == "recreate Boundary":
        t = yield ctx.keyword("Enter type of boundary object", ["Region", "Polyline"], "Polyline")
        if t.kind != "keyword":
            return
        a = yield ctx.yesno("Associate the hatch with the new boundary objects?", "No")
        if a.kind != "keyword":
            return
        spec["recreate"] = {"type": t.value.lower(), "associate": a.value == "Yes"}
    elif k == "ASsociate":
        s = yield ctx.select("Select boundary objects (Enter finds them)")
        if s.kind != "selection":
            return
        spec["boundary"] = list(s.value)
        if not s.value:
            spec = {"associative": True}
    elif k == "separate Hatches":
        spec["separate"] = True
    elif k == "Origin":
        st = settings_of(hatches[0])
        ok = yield from HC.ask_origin(ctx, st)
        if not ok:
            return
        if st.origin_mode == 0 and st.origin != hatches[0].origin:
            spec["origin"] = st.origin
        else:
            spec["origin_mode"] = st.origin_mode
    elif k == "add Point":
        pts = []
        while True:
            p = yield ctx.point("Pick an internal point for the new boundary")
            if p.kind != "point":
                break
            pts.append([p.value[0], p.value[1]])
        if not pts:
            return
        spec["add_points"] = pts
    elif k == "add Object":
        s = yield ctx.select("Select closed boundary objects to add")
        if s.kind != "selection" or not s.value:
            return
        spec["add_handles"] = list(s.value)
    else:
        n = yield ctx.number("Enter a boundary loop number to remove (starting at 1)", integer=True, minimum=1)
        if n.kind != "number":
            return
        spec["remove"] = [n.value - 1]
    run_edit(ctx, hatches, spec)


@executes("hatchedit")
def hatchedit_exec(ctx, args):
    handles = [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") is not None else [])]
    hatches = []
    for h in handles:
        e = ctx.d.get(h)
        if e is None or e.kind != "hatch":
            raise CommandError("Object %s is not a hatch." % h)
        if ctx.locked(e):
            raise CommandError("Object %s is on a locked layer." % h)
        hatches.append(e)
    return run_edit(ctx, hatches, spec_from_args(args))
