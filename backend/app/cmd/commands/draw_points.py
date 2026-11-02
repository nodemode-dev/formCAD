import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import outline, pick_entity, pick_point, point_shape, rect_corners, with_jig
from app.cmd.registry import command, executes
from app.doc import curvepath, geom
from app.doc.entities import Insert, Point

MAX_MARKERS = 20000
MAX_SEGMENTS = 32767
SWATCHES = (0, 1, 2, 3, 4, 32, 33, 34, 35, 36, 64, 65, 66, 67, 68, 96, 97, 98, 99, 100)


def _echo_style(ctx) -> None:
    ctx.say("Current point modes: PDMODE=%s PDSIZE=%s" % (ctx.var("PDMODE"), ctx.fd(ctx.var("PDSIZE"))))


def _pt(v):
    return geom.as_pt(v)


def _point_jig(ctx):
    return lambda p: [point_shape(ctx, p)]


@command("point", aliases=("po",), group="draw", label="Point", description="Places one point object (point style applies).", menu="Draw > Point > Single Point")
def point_cmd(ctx):
    _echo_style(ctx)
    r = yield ctx.point("Specify a point", jig=_point_jig(ctx))
    if r.kind == "point":
        ctx.add(Point(position=list(r.value)))


@command("point.multiple", group="draw", label="Multiple Point", description="Places points repeatedly until Enter.", menu="Draw > Point > Multiple Point")
def point_multiple(ctx):
    _echo_style(ctx)
    while True:
        r = yield ctx.point("Specify a point", jig=_point_jig(ctx))
        if r.kind != "point":
            return
        ctx.add(Point(position=list(r.value)))


@executes("point", "point.multiple")
def point_exec(ctx, args):
    pts = args.get("points") or ([args["point"]] if "point" in args else [])
    if not pts:
        raise CommandError("A point is required.")
    return {"handles": [ctx.add(Point(position=_pt(p))) for p in pts]}


def style_data(ctx) -> dict:
    mode = int(ctx.var("PDMODE"))
    size = float(ctx.var("PDSIZE"))
    return {"swatches": list(SWATCHES), "mode": mode, "size": size, "relative": size <= 0, "unit": "%" if size <= 0 else "units", "percent": 5.0 if size == 0 else abs(size) if size < 0 else None}


def _valid_mode(mode) -> bool:
    return isinstance(mode, int) and (mode % 32) in (0, 1, 2, 3, 4) and (mode // 32) in (0, 1, 2, 3) and mode >= 0 and mode <= 100 and (mode in SWATCHES)


def _set_style(ctx, mode, size) -> None:
    if mode is not None:
        if not _valid_mode(int(mode)):
            raise CommandError("invalid value for PDMODE (0 to 4, plus 32 for a circle, plus 64 for a square)")
        ctx.setvar("PDMODE", int(mode))
    if size is not None:
        if not math.isfinite(float(size)):
            raise CommandError("invalid value for PDSIZE")
        ctx.setvar("PDSIZE", float(size))


@command("ddptype", aliases=("ptype",), group="format", label="Point Style...", description="Set point display mode and size.", menu="Format > Point Style...")
def ddptype(ctx):
    cur = int(ctx.var("PDMODE"))
    ctx.say("Point display modes: %s" % ", ".join(str(m) for m in SWATCHES))
    m = yield ctx.number("Enter point display mode (0 to 4, plus 32 circle, plus 64 square)", default=cur, integer=True, minimum=0, maximum=100)
    if m.kind not in ("number", "enter"):
        return
    mode = cur if m.kind == "enter" else m.value
    if not _valid_mode(int(mode)):
        raise CommandError("invalid value for PDMODE (0 to 4, plus 32 for a circle, plus 64 for a square)")
    size = float(ctx.var("PDSIZE"))
    s = yield ctx.number("Enter point size (negative for percent of the view height, zero for 5 percent)", default=size)
    if s.kind not in ("number", "enter"):
        return
    _set_style(ctx, mode, size if s.kind == "enter" else s.value)
    ctx.say("PDMODE=%s PDSIZE=%s" % (ctx.var("PDMODE"), ctx.fd(ctx.var("PDSIZE"))))


@executes("ddptype")
def ddptype_exec(ctx, args):
    mode = args.get("mode")
    size = args.get("size")
    if size is not None and "relative" in args:
        size = -abs(float(size)) if args["relative"] else abs(float(size))
    if mode is not None or size is not None:
        _set_style(ctx, mode, size)
    return style_data(ctx)


def _path(ctx, ent, verb):
    if ent is None or ent.kind not in curvepath.KINDS:
        return None
    p = curvepath.build(ent)
    if p is None or p.length <= ctx.d.tolerances["absolute"]:
        return None
    return p


def _block_exists(ctx, name) -> bool:
    return bool(name) and ctx.d.table_get("blocks", name) is not None


def _make_marker(ctx, pos, ang, block, align) -> int:
    if block:
        return ctx.add(Insert(block=block, position=[pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0], rotation=ang if align else 0.0))
    return ctx.add(Point(position=[pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0]))


def _divide_positions(path, n) -> list:
    L = path.length
    ks = range(0, n) if path.closed else range(1, n)
    return [L * k / n for k in ks]


def _measure_positions(path, length, from_end) -> list:
    L = path.length
    if length <= 0 or not math.isfinite(length):
        raise CommandError("Value must be positive and nonzero.")
    if L / length > MAX_MARKERS:
        raise CommandError("The segment length is too small: more than %d markers." % MAX_MARKERS)
    eps = 1e-9 * max(1.0, L)
    out = []
    k = 1
    while k * length < L - eps:
        out.append(L - k * length if from_end else k * length)
        k += 1
    return out


def _place(ctx, path, positions, block, align) -> list:
    handles = []
    for s in positions:
        p, ang = path.at(s)
        handles.append(_make_marker(ctx, p, ang, block, align))
    return handles


def _preview_markers(ctx, path, positions, limit=400) -> list:
    if len(positions) > limit:
        positions = positions[:: max(1, len(positions) // limit)]
    return [point_shape(ctx, path.at(s)[0]) for s in positions]


def _pick_object(ctx, verb):
    while True:
        r = yield ctx.entity("Select object to %s" % verb)
        if r.kind != "entity":
            return None
        ent = pick_entity(ctx, r.value)
        path = _path(ctx, ent, verb)
        if path is None:
            ctx.say("Cannot %s that object." % verb)
            continue
        return ent, path, pick_point(r.value)


def _ask_block(ctx):
    while True:
        b = yield ctx.word("Enter name of block to insert")
        if b.kind != "text":
            return None
        name = str(b.value).strip()
        if _block_exists(ctx, name):
            break
        ctx.say("Block %s not found." % name)
    a = yield ctx.yesno("Align block with object?", "Yes")
    align = not (a.kind == "keyword" and a.value == "No")
    return name, align


@command("divide", aliases=("div",), group="draw", label="Divide", description="Place points or blocks dividing an object into equal segments.", menu="Draw > Point > Divide")
def divide(ctx):
    got = yield from _pick_object(ctx, "divide")
    if got is None:
        return
    ent, path, pk = got
    block, align = None, True
    while True:
        prompt = ctx.number("Enter the number of segments", ["Block"], integer=True, minimum=2, maximum=MAX_SEGMENTS)
        with_jig(prompt, lambda p: outline(ctx, ent))
        r = yield prompt
        if r.kind == "keyword" and r.value == "Block":
            res = yield from _ask_block(ctx)
            if res is None:
                return
            block, align = res
            continue
        if r.kind != "number":
            return
        _place(ctx, path, _divide_positions(path, int(r.value)), block, align)
        return


@executes("divide")
def divide_exec(ctx, args):
    ent = ctx.d.get(int(args.get("handle", 0)))
    path = _path(ctx, ent, "divide")
    if path is None:
        raise CommandError("Cannot divide that object.")
    n = int(args.get("segments", 0))
    if n < 2 or n > MAX_SEGMENTS:
        raise CommandError("The number of segments must be from 2 to %d." % MAX_SEGMENTS)
    block = args.get("block") or None
    if block and not _block_exists(ctx, block):
        raise CommandError("Block %s not found." % block)
    handles = _place(ctx, path, _divide_positions(path, n), block, bool(args.get("align", True)))
    return {"handles": handles, "count": len(handles)}


@command("measure", aliases=("me",), group="draw", label="Measure", description="Place points or blocks at fixed lengths along an object.", menu="Draw > Point > Measure")
def measure(ctx):
    got = yield from _pick_object(ctx, "measure")
    if got is None:
        return
    ent, path, pk = got
    from_end = (not path.closed) and path.locate(pk) > path.length / 2.0
    block, align = None, True

    def shape(p):
        d = geom.dist(pk, p)
        if d <= 0 or path.length / d > MAX_MARKERS:
            return [jig.line(pk, p)]
        return [jig.line(pk, p)] + _preview_markers(ctx, path, _measure_positions(path, d, from_end))

    while True:
        r = yield ctx.distance("Specify length of segment", ["Block"], base=pk, positive=True, jig=shape)
        if r.kind == "keyword" and r.value == "Block":
            res = yield from _ask_block(ctx)
            if res is None:
                return
            block, align = res
            continue
        if r.kind != "number":
            return
        _place(ctx, path, _measure_positions(path, r.value, from_end), block, align)
        return


@executes("measure")
def measure_exec(ctx, args):
    ent = ctx.d.get(int(args.get("handle", 0)))
    path = _path(ctx, ent, "measure")
    if path is None:
        raise CommandError("Cannot measure that object.")
    length = float(args.get("length", 0.0))
    block = args.get("block") or None
    if block and not _block_exists(ctx, block):
        raise CommandError("Block %s not found." % block)
    start = args.get("from")
    from_end = bool(start) and not path.closed and path.locate(_pt(start)) > path.length / 2.0
    handles = _place(ctx, path, _measure_positions(path, length, from_end), block, bool(args.get("align", True)))
    return {"handles": handles, "count": len(handles), "fromEnd": from_end}


@command("limits", group="format", label="Drawing Limits", description="Set drawing limits.", menu="Format > Drawing Limits")
def limits(ctx):
    lo = [float(v) for v in ctx.var("LIMMIN")]
    hi = [float(v) for v in ctx.var("LIMMAX")]
    r = yield ctx.point("Specify lower left corner", ["ON", "OFF"], default=[lo[0], lo[1], 0.0])
    if r.kind == "keyword":
        ctx.setvar("LIMCHECK", 1 if r.value == "ON" else 0)
        ctx.say("Limits checking is %s." % r.value)
        return
    if r.kind not in ("point", "enter"):
        return
    corner = list(r.value) if r.kind == "point" else [lo[0], lo[1], 0.0]
    u = yield ctx.point("Specify upper right corner", default=[hi[0], hi[1], 0.0], base=corner, rect=True, jig=lambda p: [jig.poly(rect_corners(corner, p), True)])
    if u.kind not in ("point", "enter"):
        return
    top = list(u.value) if u.kind == "point" else [hi[0], hi[1], 0.0]
    _apply_limits(ctx, corner, top)


def _apply_limits(ctx, lo, hi) -> None:
    if not (hi[0] > lo[0] and hi[1] > lo[1]):
        raise CommandError("Invalid limits: the upper right corner must be above and right of the lower left corner.")
    ctx.setvar("LIMMIN", [float(lo[0]), float(lo[1])])
    ctx.setvar("LIMMAX", [float(hi[0]), float(hi[1])])
    ctx.say("Limits set: %s to %s" % (ctx.fp(lo), ctx.fp(hi)))


@executes("limits")
def limits_exec(ctx, args):
    if "check" in args:
        ctx.setvar("LIMCHECK", 1 if args["check"] else 0)
    if "min" in args or "max" in args:
        lo = _pt(args.get("min", list(ctx.var("LIMMIN"))))
        hi = _pt(args.get("max", list(ctx.var("LIMMAX"))))
        _apply_limits(ctx, lo, hi)
    return {"min": list(ctx.var("LIMMIN")), "max": list(ctx.var("LIMMAX")), "check": int(ctx.var("LIMCHECK"))}
