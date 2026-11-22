import math

from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.param import adapt, marks, ops, sketch
from app.param import store as S

POINT_PARTS = {
    "line": ("start", "end", "mid"),
    "arc": ("start", "end", "mid", "center"),
    "circle": ("center",),
    "ellipse": ("center",),
    "point": ("whole",),
}
DEFAULT_PART = {"line": "start", "arc": "start", "circle": "center", "ellipse": "center", "point": "whole", "lwpolyline": "v0"}


def fail(ctx, err) -> None:
    if isinstance(err, ops.Refused):
        if err.explanation is not None:
            ctx.runner.result = {"refused": True, "explanation": err.explanation}
        raise CommandError(err.message)
    raise CommandError(str(err))


def entity_prompt(msg, options=()):
    return Prompt(msg, ("entity", "text"), list(options))


def aperture(ctx) -> float:
    return float(ctx.doc.view.get("height", 100.0)) * 0.02


def near_part(ent, pt, limit):
    best = None
    if ent.kind == "lwpolyline":
        for i, v in enumerate(ent.vertices):
            dd = math.hypot(v["p"][0] - pt[0], v["p"][1] - pt[1])
            if best is None or dd < best[0]:
                best = (dd, "v%d" % i)
        return best[1] if best and best[0] <= limit else None
    for part in POINT_PARTS.get(ent.kind, ()):
        p = marks.point_of(ent, part)
        if p is None:
            continue
        dd = math.hypot(p[0] - pt[0], p[1] - pt[1])
        if best is None or dd < best[0]:
            best = (dd, part)
    return best[1] if best and best[0] <= limit else None


def nearest_part(ent, pt):
    if ent.kind == "lwpolyline":
        return near_part(ent, pt, float("inf"))
    return near_part(ent, pt, float("inf")) or DEFAULT_PART.get(ent.kind, "whole")


def segment_at(ent, pt) -> str:
    best = (float("inf"), "s0")
    n = len(ent.vertices)
    count = n if ent.closed else n - 1
    for i in range(max(count, 0)):
        a, b = ent.vertices[i]["p"], ent.vertices[(i + 1) % n]["p"]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ll = dx * dx + dy * dy
        t = 0.0 if ll < 1e-18 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / ll))
        dd = math.hypot(a[0] + t * dx - pt[0], a[1] + t * dy - pt[1])
        if dd < best[0]:
            best = (dd, "s%d" % i)
    return best[1]


def parse_handle(text: str):
    h, _, part = str(text).strip().lstrip("#").partition(":")
    try:
        return int(h, 0), (part or None)
    except ValueError:
        try:
            return int(h, 16), (part or None)
        except ValueError:
            return None, None


def decode(ctx, r, mode: str):
    if r.kind == "entity":
        h = int(r.value["handle"])
        pt = r.value.get("point") or [0.0, 0.0]
        explicit = None
    elif r.kind == "text":
        h, explicit = parse_handle(r.value)
        pt = None
        if h is None:
            raise CommandError("*Invalid selection*")
    else:
        raise CommandError("*Invalid selection*")
    ent = ctx.d.get(h)
    if ent is None:
        raise CommandError("*Invalid selection*")
    if not adapt.constrainable(ent):
        raise CommandError(adapt.refuse_text(ent))
    if explicit:
        return [h, explicit]
    if mode == "point":
        return [h, nearest_part(ent, pt) if pt else DEFAULT_PART.get(ent.kind, "whole")]
    if ent.kind == "lwpolyline":
        if mode == "either" and pt:
            part = near_part(ent, pt, aperture(ctx))
            if part:
                return [h, part]
        return [h, segment_at(ent, pt) if pt else "s0"]
    if mode == "either" and pt:
        part = near_part(ent, pt, aperture(ctx))
        if part:
            return [h, part]
    return [h, "whole"]


def selection_handles(ctx, r) -> list:
    if r.kind != "selection":
        return []
    return [int(h) for h in r.value]


def keyword_of(r):
    return r.value if r.kind == "keyword" else None


def refs_from_args(args) -> list:
    if args.get("refs") is not None:
        return ops.norm_refs(args["refs"])
    if args.get("handles") is not None:
        return ops.norm_refs(list(args["handles"]))
    return []


def guard_call(ctx, fn, *a, **k):
    try:
        return fn(ctx.d, *a, **k)
    except (S.ParamError, ValueError) as err:
        fail(ctx, err)


def run_add(ctx, kind, refs, **kw):
    try:
        sketch.adopt(ctx.d)
        res = ops.add_constraint(ctx.d, kind, refs, **kw)
    except (S.ParamError, ValueError) as err:
        fail(ctx, err)
    return res
