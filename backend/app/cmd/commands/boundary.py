from app.cmd import jig
from app.cmd import hatch_support as HS
from app.cmd.commands import solids
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import loops as L
from app.doc import planar as P
from app.doc.curves2d import closed_loop_of
from app.doc import regionops as R
from app.doc.entities import LwPolyline
from app.doc.kinds.region import Region

MAX_POINTS = 256
MAX_POLYLINES = 10000
TYPE_OPTIONS = ["Polyline", "Region"]
ISLAND_OPTIONS = ["Normal", "Outer", "Ignore"]
PROPS = ("layer", "color", "linetype", "lineweight", "ltscale", "transparency")


def new_polyline(loop):
    return LwPolyline(vertices=[{"p": [v["p"][0], v["p"][1]], "bulge": v.get("bulge", 0.0) or 0.0, "sw": 0.0, "ew": 0.0} for v in loop["vertices"]], closed=True)


def new_region(loops):
    return Region(loops=[{"vertices": [dict(v) for v in lp["vertices"]], "outer": bool(lp["outer"])} for lp in loops])


def build_boundaries(ctx, point_loops, kind):
    seen = set()
    outputs = []
    for loops in point_loops:
        fresh = []
        for lp in loops:
            k = L.loop_key(lp["vertices"])
            if k in seen:
                continue
            seen.add(k)
            fresh.append(lp)
        if not fresh:
            continue
        if kind == "region":
            outputs.append(new_region(fresh))
        else:
            outputs.extend(new_polyline(lp) for lp in fresh)
    if len(outputs) > MAX_POLYLINES:
        raise CommandError("Too many boundary objects would be created.")
    return [ctx.add(o) for o in outputs]


def message(ctx, kind, count):
    ctx.say("BOUNDARY created %d %s(s)" % (count, "region" if kind == "region" else "polyline"))


@command("boundary", aliases=("bo", "bpoly"), group="draw", label="Boundary...", description="Create polylines or regions from enclosed areas.", menu="Draw > Boundary...")
def boundary_cmd(ctx):
    mem = ctx.mem
    kind = mem.get("boundary_type", "polyline")
    island = mem.get("boundary_island", int(ctx.var("HPISLAND")))
    gap = mem.get("boundary_gap", float(ctx.var("HPGAPTOL")))
    bset = mem.get("boundary_set")
    points = []
    while True:
        def show(cursor):
            try:
                found = L.detect_at(ctx.doc, cursor, island, gap, bset)
            except Exception:
                return []
            return [jig.poly(lp["vertices"], True) for lp in found]

        r = yield ctx.point("Pick internal point", ["Object type", "Island detection", "Boundary set", "Gap tolerance"], jig=show)
        if r.kind == "enter":
            break
        if r.kind == "point":
            if len(points) >= MAX_POINTS:
                ctx.say("Too many internal points.")
                continue
            try:
                found = L.detect_at(ctx.doc, r.value, island, gap, bset)
            except P.TooComplex as err:
                ctx.say(str(err))
                continue
            if not found:
                ctx.say(HS.NOT_FOUND)
                continue
            points.append(found)
            continue
        if r.kind != "keyword":
            return
        if r.value == "Object type":
            q = yield ctx.keyword("Enter type of boundary object", TYPE_OPTIONS, kind.title())
            if q.kind == "keyword":
                kind = q.value.lower()
                mem["boundary_type"] = kind
        elif r.value == "Island detection":
            q = yield ctx.keyword("Enter island detection style", ISLAND_OPTIONS, HS.STYLE_NAMES[island].title())
            if q.kind == "keyword":
                island = HS.parse_style(q.value)
                mem["boundary_island"] = island
        elif r.value == "Gap tolerance":
            q = yield ctx.number("Enter a gap tolerance from 0 to 5000", default=gap, minimum=0.0, maximum=5000.0, default_text=ctx.fd(gap))
            if q.kind == "number":
                gap = float(q.value)
                mem["boundary_gap"] = gap
        elif r.value == "Boundary set":
            q = yield ctx.select("Select objects for the boundary set (Enter uses everything visible)")
            if q.kind == "selection":
                bset = list(q.value) if q.value else None
                mem["boundary_set"] = bset
    if not points:
        return
    handles = build_boundaries(ctx, points, kind)
    message(ctx, kind, len(handles))


@executes("boundary")
def boundary_exec(ctx, args):
    pts = args.get("points") or []
    if not pts:
        raise CommandError(HS.NO_INPUT)
    if len(pts) > MAX_POINTS:
        raise CommandError("Too many internal points.")
    island = HS.parse_style(args.get("style", ctx.var("HPISLAND")))
    gap = float(args.get("gap", ctx.var("HPGAPTOL")))
    if not 0.0 <= gap <= 5000.0:
        raise CommandError("Gap tolerance is between 0 and 5000.")
    kind = str(args.get("type", "polyline")).lower()
    if kind not in ("polyline", "region"):
        raise CommandError("Boundary type is polyline or region.")
    bset = [int(h) for h in args["boundary_set"]] if args.get("boundary_set") is not None else None
    found = []
    for p in pts:
        try:
            lp = L.detect_at(ctx.doc, [float(p[0]), float(p[1])], island, gap, bset)
        except P.TooComplex as err:
            raise CommandError(str(err))
        if not lp:
            raise CommandError(HS.NOT_FOUND)
        found.append(lp)
    handles = build_boundaries(ctx, found, kind)
    message(ctx, kind, len(handles))
    return {"handles": handles, "count": len(handles)}


def copy_props(src, dst):
    for name in PROPS:
        setattr(dst, name, getattr(src, name))


def regions_from(ctx, ents):
    made = []
    erase = []
    open_ents = []
    for e in ents:
        if e.kind == "region":
            continue
        cl = closed_loop_of(e)
        if cl is not None:
            loop = L.make_loop(cl, [e.handle], 0)
            rg = new_region([loop])
            if rg.valid():
                copy_props(e, rg)
                made.append((rg, [e.handle]))
                erase.append(e.handle)
        elif e.kind in ("line", "arc", "lwpolyline", "polyline3d", "ellipse", "spline"):
            open_ents.append(e)
    if open_ents:
        for lp in L.loops_from_objects(open_ents, 0, ctx.var("HPGAPTOL")):
            lone = {"vertices": L.orient(lp["vertices"], True), "outer": True}
            rg = new_region([lone])
            if not rg.valid():
                continue
            first = ctx.d.get(lp["sources"][0]) if lp["sources"] else open_ents[0]
            copy_props(first, rg)
            made.append((rg, list(lp["sources"])))
            for s in lp["sources"]:
                if s not in erase:
                    erase.append(s)
    return made, erase


def apply_regions(ctx, ents):
    made, erase = regions_from(ctx, ents)
    if len(made) > MAX_POLYLINES:
        raise CommandError("Too many loops.")
    out = []
    for rg, _src in made:
        out.append(ctx.d.add_entity(rg, ctx.doc.current_space))
    for h in erase:
        ctx.d.erase_entity(h)
    ctx.say("%d Region(s) created." % len(out))
    return out


@command("region", aliases=("reg",), group="draw", label="Region", description="Convert closed objects into region objects.", menu="Draw > Region")
def region_cmd(ctx):
    r = yield ctx.select("Select objects")
    if r.kind != "selection" or not r.value:
        return
    ents = ctx.editable(r.value)
    if not ents:
        ctx.say("0 Region(s) created.")
        return
    apply_regions(ctx, ents)


@executes("region")
def region_exec(ctx, args):
    handles = [int(h) for h in args.get("handles") or []]
    if not handles:
        raise CommandError("Give the handles of the objects to convert.")
    ents = ctx.editable(handles)
    return {"handles": apply_regions(ctx, ents)}


def region_ents(ctx, handles):
    regs = []
    skipped = 0
    for h in handles:
        e = ctx.d.get(h)
        if e is not None and e.kind == "region" and not ctx.locked(e):
            regs.append(e)
        else:
            skipped += 1
    if skipped:
        ctx.say("%d object(s) are not regions and are ignored." % skipped)
    return regs


def finish_boolean(ctx, op, first, rest, result):
    if not result:
        ctx.say("The result has no area.")
        return None
    if len(result) > R.MAX_LOOPS:
        raise CommandError("Too many loops.")
    probe = Region(loops=result)
    if not probe.valid():
        ctx.say("The result has no area.")
        return None
    ent = ctx.d.modify(first.handle)
    ent.loops = result
    for r in rest:
        ctx.d.erase_entity(r.handle)
    return first.handle


def run_boolean(ctx, op, first, rest):
    try:
        res = R.combine(op, [dict(lp) for lp in first.loops], [[dict(lp) for lp in r.loops] for r in rest])
    except R.TooComplexToCombine as err:
        raise CommandError(str(err))
    except P.TooComplex as err:
        raise CommandError(str(err))
    return finish_boolean(ctx, op, first, rest, res)


@command("union", aliases=("uni",), group="modify", label="Union", description="Union of regions.", menu="Modify > Solid Editing > Union")
def union_cmd(ctx):
    r = yield ctx.select("Select regions")
    if r.kind != "selection":
        return
    if solids.any_solid(ctx, r.value):
        solids.boolean_pick(ctx, "fuse", r.value)
        return
    regs = region_ents(ctx, r.value)
    if len(regs) < 2:
        ctx.say("Select at least two regions.")
        return
    run_boolean(ctx, R.UNION, regs[0], regs[1:])


@command("intersect", aliases=("in",), group="modify", label="Intersect", description="Intersection of regions.", menu="Modify > Solid Editing > Intersect")
def intersect_cmd(ctx):
    r = yield ctx.select("Select regions")
    if r.kind != "selection":
        return
    if solids.any_solid(ctx, r.value):
        solids.boolean_pick(ctx, "common", r.value)
        return
    regs = region_ents(ctx, r.value)
    if len(regs) < 2:
        ctx.say("Select at least two regions.")
        return
    run_boolean(ctx, R.INTERSECT, regs[0], regs[1:])


@command("subtract", aliases=("su",), group="modify", label="Subtract", description="Subtract regions.", menu="Modify > Solid Editing > Subtract")
def subtract_cmd(ctx):
    ctx.say("Select regions to subtract from ..")
    a = yield ctx.select("Select regions to subtract from")
    if a.kind != "selection":
        return
    if solids.any_solid(ctx, a.value):
        ctx.say("Select solids to subtract ..")
        b = yield ctx.select("Select solids to subtract")
        if b.kind == "selection":
            solids.boolean_run(ctx, "cut", a.value, b.value)
        return
    base = region_ents(ctx, a.value)
    if not base:
        ctx.say("Select at least one region.")
        return
    ctx.say("Select regions to subtract ..")
    b = yield ctx.select("Select regions to subtract")
    if b.kind != "selection":
        return
    cut =[r for r in region_ents(ctx, b.value) if r.handle != base[0].handle]
    if not cut:
        ctx.say("Select at least one region to subtract.")
        return
    run_boolean(ctx, R.SUBTRACT, base[0], cut)


def two_handles(args):
    handles = [int(h) for h in args.get("handles") or []]
    return handles


@executes("union")
def union_exec(ctx, args):
    if solids.any_solid(ctx, two_handles(args)):
        return solids.boolean_exec(ctx, "fuse", two_handles(args)[:1], two_handles(args)[1:])
    regs = region_ents(ctx, two_handles(args))
    if len(regs) < 2:
        raise CommandError("Give at least two region handles.")
    return {"handle": run_boolean(ctx, R.UNION, regs[0], regs[1:])}


@executes("intersect")
def intersect_exec(ctx, args):
    if solids.any_solid(ctx, two_handles(args)):
        return solids.boolean_exec(ctx, "common", two_handles(args)[:1], two_handles(args)[1:])
    regs = region_ents(ctx, two_handles(args))
    if len(regs) < 2:
        raise CommandError("Give at least two region handles.")
    return {"handle": run_boolean(ctx, R.INTERSECT, regs[0], regs[1:])}


@executes("subtract")
def subtract_exec(ctx, args):
    if solids.any_solid(ctx, [int(h) for h in args.get("from") or []]):
        return solids.boolean_exec(ctx, "cut", [int(h) for h in args.get("from") or []], [int(h) for h in args.get("subtract") or []])
    base = region_ents(ctx, [int(h) for h in args.get("from") or []])
    cut = region_ents(ctx, [int(h) for h in args.get("subtract") or []])
    if not base or not cut:
        raise CommandError("Give region handles to subtract from and to subtract.")
    return {"handle": run_boolean(ctx, R.SUBTRACT, base[0], [r for r in cut if r.handle != base[0].handle])}
