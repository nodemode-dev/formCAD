from app.cmd import jig
from app.cmd.prompts import Prompt
from app.doc import geom


def with_jig(prompt: Prompt, fn) -> Prompt:
    prompt.jig = fn
    return prompt


def point_shape(ctx, p) -> dict:
    mode = int(ctx.d.header.get("PDMODE", 0))
    size = float(ctx.d.header.get("PDSIZE", 0.0))
    g = {"type": "point", "p": [float(p[0]), float(p[1])], "mode": mode, "size": size if size > 0 else 0.0}
    g["rel"] = 0.0 if size > 0 else (abs(size) if size < 0 else 5.0)
    return g


def pick_entity(ctx, value):
    if not isinstance(value, dict):
        return None
    try:
        return ctx.d.get(int(value.get("handle")))
    except (TypeError, ValueError):
        return None


def pick_point(value) -> list:
    pt = value.get("point") if isinstance(value, dict) else None
    return [float(pt[0]), float(pt[1]), 0.0] if pt else [0.0, 0.0, 0.0]


def outline(ctx, ent) -> list:
    g = jig.entity_geom(ent, ctx.d)
    return [g] if g else []


def inherit(src, dst) -> None:
    for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "plot_style"):
        setattr(dst, name, getattr(src, name))


def add_props(ctx, ent, **props) -> int:
    h = ctx.add(ent)
    rec = ctx.d.modify(h)
    for k, v in props.items():
        setattr(rec, k, v)
    return h


def add_like(ctx, ent, src) -> int:
    h = ctx.add(ent)
    inherit(src, ctx.d.modify(h))
    return h


def ensure_linetype(ctx, name: str) -> str:
    from app.doc import tables as T

    rec = ctx.d.table_get("linetypes", name)
    if rec is not None:
        return rec["name"]
    for std in T.standard_linetypes(ctx.d.metric):
        if std["name"].lower() == name.lower():
            ctx.d.table_set("linetypes", std)
            return std["name"]
    return "Continuous"


def rect_corners(a, b) -> list:
    return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]


def signed_area(pts) -> float:
    s = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s += a[0] * b[1] - b[0] * a[1]
    return s / 2.0


def same(ctx, a, b) -> bool:
    return geom.same_point(a, b, ctx.d.tolerances["absolute"])
