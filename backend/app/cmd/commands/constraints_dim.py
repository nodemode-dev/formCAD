from app.cmd import constraint_flow as F
from app.cmd.context import CommandError
from app.cmd.commands.constraints_geom import pick
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.param import adapt, marks, ops
from app.param import store as S
from app.param import units as U
from app.solve.errors import SolverFault

TYPES = ("Linear", "ALigned", "Horizontal", "Vertical", "Angular", "Radius", "Diameter")
KIND_OF = {"linear": "linear", "aligned": "distance", "horizontal": "hdistance", "vertical": "vdistance", "angular": "angle", "radius": "radius", "diameter": "diameter"}
SHORT = {"linear": "dclinear", "aligned": "dcaligned", "horizontal": "dchorizontal", "vertical": "dcvertical", "angular": "dcangular", "radius": "dcradius", "diameter": "dcdiameter"}


def end_points(d, refs):
    pts = []
    for h, part in refs:
        ent = d.get(h)
        if ent is None:
            return None
        if part in ("whole",) or part.startswith("s"):
            if ent.kind == "line":
                pts.extend([marks.point_of(ent, "start"), marks.point_of(ent, "end")])
            elif ent.kind == "lwpolyline" and part.startswith("s") and part[1:].isdigit():
                i = int(part[1:])
                n = len(ent.vertices)
                pts.extend([ent.vertices[i]["p"][:2], ent.vertices[(i + 1) % n]["p"][:2]])
            else:
                return None
        else:
            pts.append(marks.point_of(ent, part))
    return pts


def resolve_kind(d, word, refs):
    kind = KIND_OF[word]
    if kind != "linear":
        return kind
    pts = end_points(d, refs)
    if not pts or len(pts) < 2:
        raise CommandError("Linear needs two points or a line.")
    return "hdistance" if abs(pts[-1][0] - pts[0][0]) >= abs(pts[-1][1] - pts[0][1]) else "vdistance"


def expand_object(ctx, ref):
    ent = ctx.d.get(ref[0])
    part = ref[1]
    if ent.kind == "arc" and part == "whole":
        return [[ref[0], "start"], [ref[0], "end"]]
    if ent.kind == "line" or (ent.kind == "lwpolyline" and part.startswith("s")):
        return [ref]
    if part == "whole":
        raise CommandError("*Invalid selection*")
    return [ref]


def gather(ctx, word):
    if word in ("linear", "aligned", "horizontal", "vertical"):
        w, a = yield from pick(ctx, "Select object", "object", ["Points"])
        if w == "Points":
            _, a = yield from pick(ctx, "Specify first constraint point", "point")
            if a is None:
                return None
            _, b = yield from pick(ctx, "Specify second constraint point", "either" if word == "aligned" else "point")
            return None if b is None else [a, b]
        return None if a is None else expand_object(ctx, a)
    if word == "angular":
        _, a = yield from pick(ctx, "Select first line or arc", "object")
        if a is None:
            return None
        if ctx.d.get(a[0]).kind == "arc":
            return [[a[0], "whole"]]
        _, b = yield from pick(ctx, "Select second line", "object")
        return None if b is None else [a, b]
    _, a = yield from pick(ctx, "Select arc or circle", "object")
    return None if a is None else [[a[0], "whole"]]


def measured(ctx, kind, refs):
    net = adapt.load(ctx.d, seeds=[h for h, _ in refs])
    try:
        return net.sk.measure(kind, net.refs(refs))
    except (SolverFault, S.ParamError) as err:
        raise CommandError(str(err))


def split_entry(text):
    if "=" in text:
        name, _, e = text.partition("=")
        return name.strip() or None, e.strip()
    return None, text.strip()


def finish(ctx, kind, refs, text=None, driving=True, name=None, sketch=None, value=None, force=False):
    label, expr = split_entry(text) if text else (None, "")
    res = F.run_add(ctx, kind, refs, expr=expr or None, value=value, driving=driving, label=name or label, sketch=sketch, force=force)
    shown = res.get("expr") or U.format_value(res.get("value") or 0.0)
    ctx.say("%s = %s" % (res["label"], shown))
    return res


def make(word):
    def run(ctx):
        refs = yield from gather(ctx, word)
        if refs is None:
            return
        kind = resolve_kind(ctx.d, word, refs)
        meas = measured(ctx, kind, refs)
        shown = U.format_value(meas, 4)
        r = yield Prompt("Enter dimension value or name=expression (Reference for a driven dimension)", ("text",), [], shown, shown, free_text=True)
        if r.kind not in ("text", "number"):
            return
        text = str(r.value)
        if text.strip().lower() in ("r", "reference"):
            finish(ctx, kind, refs, driving=False)
            return
        if r.from_default:
            finish(ctx, kind, refs, value=float(U.format_value(meas)))
            return
        finish(ctx, kind, refs, text=text)

    return run


def make_exec(word):
    def exe(ctx, args):
        refs = F.refs_from_args(args)
        if not refs:
            raise CommandError("Name the objects to dimension in refs.")
        w = str(args.get("type") or word).lower()
        if w not in KIND_OF:
            raise CommandError("Unknown dimension type.")
        kind = resolve_kind(ctx.d, w, refs)
        text = args.get("expr")
        value = args.get("value")
        return finish(ctx, kind, refs, text=str(text) if text not in (None, "") else None, driving=bool(args.get("driving", True)), name=args.get("name"), sketch=args.get("sketch"), value=value, force=bool(args.get("force")))

    return exe


for _w, _n in SHORT.items():
    command(_n, group="constraints", label="%s dimension constraint" % _w.title(), description="Add a %s dimension that drives the geometry." % _w, menu="Parametric > Dimensional > %s" % _w.title())(make(_w))
    executes(_n)(make_exec(_w))


@command("dimconstraint", aliases=("dcon",), group="constraints", label="Dimensional constraint", description="Add a dimension that drives the geometry.", menu="Parametric > Dimensional Constraints")
def dimconstraint(ctx):
    r = yield ctx.keyword("Select a dimension constraint type", list(TYPES), default="ALigned")
    if r.kind not in ("keyword", "text"):
        return
    word = str(r.value).lower()
    if word not in KIND_OF:
        raise CommandError("Unknown dimension type.")
    yield from make(word)(ctx)


@executes("dimconstraint")
def dimconstraint_exec(ctx, args):
    return make_exec(str(args.get("type") or "aligned").lower())(ctx, args)
