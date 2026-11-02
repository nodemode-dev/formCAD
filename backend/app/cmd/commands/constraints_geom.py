from app.cmd import constraint_flow as F
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.param import store as S

TYPES = ("Coincident", "Collinear", "Concentric", "Fix", "Parallel", "Perpendicular", "Horizontal", "Vertical", "Tangent", "Smooth", "Symmetric", "Equal")
SHORT = {"coincident": "gccoincident", "collinear": "gccollinear", "concentric": "gcconcentric", "fix": "gcfix", "parallel": "gcparallel", "perpendicular": "gcperpendicular", "horizontal": "gchorizontal", "vertical": "gcvertical", "tangent": "gctangent", "smooth": "gcsmooth", "symmetric": "gcsymmetric", "equal": "gcequal"}
TWO_OBJECTS = ("collinear", "concentric", "parallel", "perpendicular", "tangent", "smooth", "equal")


def pick(ctx, msg, mode, options=()):
    r = yield F.entity_prompt(msg, options)
    if r.kind == "enter":
        return None, None
    if r.kind == "keyword":
        return r.value, None
    return None, F.decode(ctx, r, mode)


def gather(ctx, kind):
    if kind == "coincident":
        _, a = yield from pick(ctx, "Select first point", "point")
        if a is None:
            return None
        _, b = yield from pick(ctx, "Select second point or object", "either")
        return None if b is None else [a, b]
    if kind in TWO_OBJECTS:
        _, a = yield from pick(ctx, "Select first object", "object")
        if a is None:
            return None
        _, b = yield from pick(ctx, "Select second object", "object")
        return None if b is None else [a, b]
    if kind == "fix":
        _, a = yield from pick(ctx, "Select point or object", "either")
        return None if a is None else [a]
    if kind in ("horizontal", "vertical"):
        word, a = yield from pick(ctx, "Select an object", "object", ["2Points"])
        if word == "2Points":
            _, a = yield from pick(ctx, "Select first point", "point")
            if a is None:
                return None
            _, b = yield from pick(ctx, "Select second point", "point")
            return None if b is None else [a, b]
        return None if a is None else [a]
    _, a = yield from pick(ctx, "Select first object", "either")
    if a is None:
        return None
    _, b = yield from pick(ctx, "Select second object", "either")
    if b is None:
        return None
    _, c = yield from pick(ctx, "Select symmetry line", "object")
    return None if c is None else [a, b, c]


def finish(ctx, kind, refs, **kw):
    res = F.run_add(ctx, kind, refs, **kw)
    ctx.say("%s constraint #%d applied." % (kind.title(), res["id"]))
    if res.get("report") and res["report"]["status"] == "over":
        ctx.say("The geometry is now over-constrained.")
    return res


def make(kind):
    def run(ctx):
        refs = yield from gather(ctx, kind)
        if refs is None:
            return
        finish(ctx, kind, refs)

    def exe(ctx, args):
        return finish(ctx, kind, F.refs_from_args(args), sketch=args.get("sketch"), force=bool(args.get("force")))

    name = SHORT[kind]
    command(name, group="constraints", label="%s constraint" % kind.title(), description="Add a %s relation between objects." % kind, menu="Parametric > Geometric > %s" % kind.title())(run)
    executes(name)(exe)


for _k in SHORT:
    make(_k)


@command("geomconstraint", aliases=("gcon",), group="constraints", label="Geometric constraint", description="Add a relation between objects.", menu="Parametric > Geometric Constraints")
def geomconstraint(ctx):
    r = yield ctx.keyword("Enter constraint type", list(TYPES), default="Horizontal")
    if r.kind not in ("keyword", "text"):
        return
    kind = str(r.value).lower()
    if kind not in S.GEOMETRIC_WORDS:
        raise CommandError("Unknown constraint type.")
    refs = yield from gather(ctx, kind)
    if refs is None:
        return
    finish(ctx, kind, refs)


@executes("geomconstraint")
def geomconstraint_exec(ctx, args):
    kind = str(args.get("type") or args.get("kind") or "horizontal").lower()
    if kind not in S.GEOMETRIC_WORDS:
        raise CommandError("Unknown constraint type.")
    return finish(ctx, kind, F.refs_from_args(args), sketch=args.get("sketch"), force=bool(args.get("force")))
