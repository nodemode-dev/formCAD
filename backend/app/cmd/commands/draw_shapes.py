import math

from app.cmd import jig
from app.cmd.commands.draw import _pt, dnum
from app.cmd.context import CommandError
from app.cmd.prompts import Input
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc.entities import LwPolyline, Solid

SIDES_MESSAGE = "Requires an integer between 3 and 1024."
INSCRIBED = "Inscribed in circle"
CIRCUMSCRIBED = "Circumscribed about circle"


def polygon_points(n, center, radius, inscribed, angle=None):
    step = geom.TAU / n
    if inscribed:
        first = angle if angle is not None else -math.pi / 2.0 + math.pi / n
        rad = radius
    else:
        mid = angle if angle is not None else -math.pi / 2.0
        first = mid + math.pi / n
        rad = radius / math.cos(math.pi / n)
    return [[center[0] + rad * math.cos(first + k * step), center[1] + rad * math.sin(first + k * step), 0.0] for k in range(n)]


def edge_polygon(n, p1, p2):
    side = geom.dist(p1, p2)
    if side < geom.EPS:
        return None
    apothem = side / (2.0 * math.tan(math.pi / n))
    ux, uy = (p2[0] - p1[0]) / side, (p2[1] - p1[1]) / side
    mid = geom.midpoint(p1, p2)
    center = [mid[0] - uy * apothem, mid[1] + ux * apothem, 0.0]
    first = geom.angle_of(center, p1)
    rad = math.hypot(p1[0] - center[0], p1[1] - center[1])
    return [[center[0] + rad * math.cos(first + k * geom.TAU / n), center[1] + rad * math.sin(first + k * geom.TAU / n), 0.0] for k in range(n)]


def _ring(pts):
    return jig.poly([[p[0], p[1], 0.0] for p in pts], True)


def _add_polygon(ctx, pts):
    return ctx.add(LwPolyline.from_points([[p[0], p[1]] for p in pts], closed=True))


def _ask_sides(ctx):
    last = int(ctx.d.header.get("POLYSIDES", 4))
    while True:
        r = yield ctx.number("Enter number of sides", default=last)
        if r.kind != "number":
            return None
        v = r.value
        if v != int(v) or not 3 <= int(v) <= 1024:
            ctx.say(SIDES_MESSAGE)
            continue
        ctx.d.set_header("POLYSIDES", int(v))
        return int(v)


@command("polygon", aliases=("pol",), group="draw", label="Polygon", description="Regular polygon 3 to 1024 sides, inscribed, circumscribed or by edge.", menu="Draw > Polygon")
def polygon(ctx):
    n = yield from _ask_sides(ctx)
    if n is None:
        return
    c = yield ctx.point("Specify center of polygon", ["Edge"])
    if c.kind == "keyword":
        a = yield ctx.point("Specify first endpoint of edge")
        if a.kind != "point":
            return
        def show_edge(p):
            pts = edge_polygon(n, a.value, p)
            return [_ring(pts)] + jig.rubber(a.value, p) if pts else jig.rubber(a.value, p)

        while True:
            b = yield ctx.point("Specify second endpoint of edge", base=a.value, jig=show_edge)
            if b.kind != "point":
                return
            pts = edge_polygon(n, a.value, b.value)
            if pts is None:
                ctx.say("Edge endpoints must differ.")
                continue
            _add_polygon(ctx, pts)
            return
    if c.kind != "point":
        return
    center = c.value
    last = ctx.mem.get("polygon_mode", INSCRIBED)
    ask = ctx.keyword("Enter an option", [INSCRIBED, CIRCUMSCRIBED], last)
    ask.hint = "bare"
    ask.default_text = "I" if last == INSCRIBED else "C"
    mode = yield ask
    if mode.kind != "keyword":
        return
    inscribed = mode.value == INSCRIBED
    ctx.mem["polygon_mode"] = mode.value
    tol = ctx.d.tolerances["absolute"]

    def build(inp):
        if inp.kind == "number":
            return polygon_points(n, center, inp.value, inscribed) if inp.value > tol else None
        rad = geom.dist(center, inp.value)
        if rad <= tol:
            return None
        return polygon_points(n, center, rad, inscribed, geom.angle_of(center, inp.value))

    def show(p):
        pts = build(Input("point", p))
        return [_ring(pts)] + jig.rubber(center, p) if pts else jig.rubber(center, p)

    while True:
        r = yield ctx.distance("Specify radius of circle", base=center, positive=True, jig=show)
        if r.kind not in ("number", "point"):
            return
        pts = build(r)
        if pts is None:
            ctx.say("Value must be positive and nonzero.")
            continue
        _add_polygon(ctx, pts)
        return


@executes("polygon")
def polygon_exec(ctx, args):
    n = int(args.get("sides", 4))
    if n != args.get("sides", 4) or not 3 <= n <= 1024:
        raise CommandError(SIDES_MESSAGE)
    if "edge" in args:
        p1, p2 = (_pt(p) for p in args["edge"])
        pts = edge_polygon(n, p1, p2)
        if pts is None:
            raise CommandError("Edge endpoints must differ.")
        return {"handle": _add_polygon(ctx, pts)}
    c = _pt(args["center"])
    r = float(args.get("radius", 0.0))
    if r <= ctx.d.tolerances["absolute"]:
        raise CommandError("Value must be positive and nonzero.")
    ang = math.radians(float(args["angle"])) if args.get("angle") is not None else None
    return {"handle": _add_polygon(ctx, polygon_points(n, c, r, bool(args.get("inscribed", True)), ang))}


def donut_vertices(center, inside, outside):
    rc = (inside + outside) / 4.0
    w = (outside - inside) / 2.0
    verts = [
        {"p": [center[0] - rc, center[1]], "bulge": 1.0, "sw": w, "ew": w},
        {"p": [center[0] + rc, center[1]], "bulge": 1.0, "sw": w, "ew": w},
    ]
    return verts, w


def _add_donut(ctx, center, inside, outside):
    verts, w = donut_vertices(center, inside, outside)
    return ctx.add(LwPolyline(vertices=verts, closed=True, const_width=w))


def _length(ctx, r):
    if r.kind == "number":
        return r.value
    if r.kind == "point":
        p2 = yield ctx.point("Specify second point", base=r.value, jig=lambda p: jig.rubber(r.value, p))
        if p2.kind == "point":
            return geom.dist(r.value, p2.value)
    return None


@command("donut", aliases=("do", "doughnut"), group="draw", label="Donut", description="Filled ring as a wide two-arc polyline.", menu="Draw > Donut")
def donut(ctx):
    tol = ctx.d.tolerances["absolute"]
    inside = float(ctx.d.header.get("DONUTID", 0.5))
    outside = float(ctx.d.header.get("DONUTOD", 1.0))
    while True:
        a = yield ctx.distance("Specify inside diameter of donut", default=inside, nonneg=True)
        iv = yield from _length(ctx, a)
        if iv is None:
            return
        if iv < 0:
            ctx.say("Requires a positive number.")
            continue
        b = yield ctx.distance("Specify outside diameter of donut", default=outside, positive=True)
        ov = yield from _length(ctx, b)
        if ov is None:
            return
        if ov <= tol:
            ctx.say("Value must be positive and nonzero.")
            continue
        if iv > ov:
            ctx.say("Inside diameter cannot exceed the outside diameter.")
            continue
        break
    ctx.d.set_header("DONUTID", float(iv))
    ctx.d.set_header("DONUTOD", float(ov))

    def preview(p):
        out = [jig.circle(p, ov / 2.0)]
        if iv > tol:
            out.append(jig.circle(p, iv / 2.0))
        return out

    while True:
        c = yield ctx.point("Specify center of donut or <exit>", jig=preview)
        if c.kind != "point":
            return
        _add_donut(ctx, c.value, iv, ov)


@executes("donut")
def donut_exec(ctx, args):
    inside = float(args.get("inside", ctx.d.header.get("DONUTID", 0.5)))
    outside = float(args.get("outside", ctx.d.header.get("DONUTOD", 1.0)))
    if inside < 0 or outside <= ctx.d.tolerances["absolute"]:
        raise CommandError("Value must be positive and nonzero.")
    if inside > outside:
        raise CommandError("Inside diameter cannot exceed the outside diameter.")
    centers = args.get("centers") or ([args["center"]] if "center" in args else [])
    if not centers:
        raise CommandError("A centre is required.")
    ctx.d.set_header("DONUTID", inside)
    ctx.d.set_header("DONUTOD", outside)
    return {"handles": [_add_donut(ctx, _pt(c), inside, outside) for c in centers]}


def _solid_ring(pts):
    order = [0, 1, 3, 2] if len(pts) == 4 else list(range(len(pts)))
    return jig.poly([[pts[i][0], pts[i][1], 0.0] for i in order], True)


def _add_solid(ctx, pts):
    return ctx.add(Solid(corners=[[p[0], p[1], 0.0] for p in pts]))


@command("solid", aliases=("so",), group="draw", label="2D Solid", description="Filled triangle or quadrilateral, chaining on the last two corners.", menu="Draw > 2D Solid")
def solid(ctx):
    a = yield ctx.point("Specify first point")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify second point", base=a.value, jig=lambda p: jig.rubber(a.value, p))
    if b.kind != "point":
        return
    p1, p2 = a.value, b.value
    while True:
        c = yield ctx.point("Specify third point", base=p2, jig=lambda p: [_solid_ring([p1, p2, p])])
        if c.kind != "point":
            return
        d = yield ctx.point("Specify fourth point or <exit>", base=c.value, jig=lambda p: [_solid_ring([p1, p2, c.value, p])])
        if d.kind == "point":
            _add_solid(ctx, [p1, p2, c.value, d.value])
            p1, p2 = c.value, d.value
        elif d.kind == "enter":
            _add_solid(ctx, [p1, p2, c.value])
            p1, p2 = p2, c.value
        else:
            return


@executes("solid")
def solid_exec(ctx, args):
    pts = [_pt(p) for p in args.get("points", [])]
    n = len(pts)
    if n >= 4 and (n - 4) % 2 == 0:
        first = 4
    elif n >= 3 and (n - 3) % 2 == 0:
        first = 3
    else:
        raise CommandError("Give three or four points, then two more for each chained solid.")
    made = [_add_solid(ctx, pts[:first])]
    prev = pts[:first]
    rest = pts[first:]
    for i in range(0, len(rest), 2):
        quad = [prev[-2], prev[-1], rest[i], rest[i + 1]]
        made.append(_add_solid(ctx, quad))
        prev = quad
    return {"handles": made}
