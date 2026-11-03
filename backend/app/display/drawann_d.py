import math

from app.display import shapes
from app.display.shapes import box, grip_list, xy
from app.drawann import build, settings
from app.text import single

ARC_STEPS = 24


def _flat(pts):
    return [v for p in pts for v in (float(p[0]), float(p[1]))]


def _width(prim):
    return build.tw(prim[4], prim[3])


def render(prims, ctx, e):
    rec, fs = shapes.fontset(ctx, "Standard")
    wf = float(rec.get("width_factor", 1.0) or 1.0)
    obl = float(rec.get("oblique", 0.0) or 0.0)
    parts, out = [], []
    for p in prims:
        t = p[0]
        if t == "l":
            parts.append({"type": "line", "p1": [p[1], p[2]], "p2": [p[3], p[4]]})
        elif t == "c":
            parts.append({"type": "circle", "c": [p[1], p[2]], "r": p[3]})
        elif t == "a":
            parts.append({"type": "arc", "c": [p[1], p[2]], "r": p[3], "a0": p[4] % (2 * math.pi), "a1": p[5] % (2 * math.pi)})
        elif t == "p":
            parts.append({"type": "poly", "verts": [[x, y, 0.0, 0.0, 0.0] for x, y in p[1]], "closed": bool(p[2]), "elev": 0.0})
        elif t == "f":
            out.append({"t": "fill", "rings": [_flat(p[1])]})
        elif t == "t":
            w = _width(p)
            hal = {"l": 0, "c": 1, "r": 2}[p[5]]
            at = (p[1], p[2])
            laid = single.layout(fs, p[4], float(p[3]), wf, obl, False, False, hal, 2, at, at, p[6], bool(ctx.textfill))
            for pr in laid.prims:
                out.append(pr)
            ox = {"l": 0.0, "c": -w / 2.0, "r": -w}[p[5]]
            c, s = math.cos(p[6]), math.sin(p[6])
            corners = [(p[1] + dx * c - dy * s, p[2] + dx * s + dy * c) for dx, dy in ((ox, -p[3] / 2), (ox + w, -p[3] / 2), (ox + w, p[3] / 2), (ox, p[3] / 2))]
            parts.append({"type": "text", "insert": [p[1], p[2]], "height": float(p[3]), "rot": p[6], "box": [[x, y] for x, y in corners]})
    return parts, out


def _make(e, ctx):
    st = settings.get(ctx.d)
    prims, info = build.build(e, st)
    parts, out = render(prims, ctx, e)
    bb = build.bounds_of(prims)
    return parts, out, bb, info


def _result(e, ctx, grips):
    parts, out, bb, _info = _make(e, ctx)
    if bb is None:
        bb = box([xy(getattr(e, "position", None) or getattr(e, "center"))])
    return {"type": "compound", "parts": parts}, out, grip_list(grips), bb


@shapes.builder("gdtframe")
def gdtframe(e, ctx):
    grips = [(xy(e.position), "insert")] + [(xy(p), "vtx") for p in e.leader]
    return _result(e, ctx, grips)


@shapes.builder("datumsym")
def datumsym(e, ctx):
    grips = [(xy(e.position), "insert")] + ([(xy(e.tip), "end")] if e.tip else [])
    return _result(e, ctx, grips)


@shapes.builder("balloon")
def balloon(e, ctx):
    grips = [(xy(e.position), "insert")] + ([(xy(e.tip), "end")] if e.tip else [])
    return _result(e, ctx, grips)


@shapes.builder("finishmark")
def finishmark(e, ctx):
    return _result(e, ctx, [(xy(e.position), "insert")])


@shapes.builder("centermark")
def centermark(e, ctx):
    grips = [(xy(e.center), "cen")] if e.mode == "circle" else [(xy(e.a), "end"), (xy(e.b), "end")]
    return _result(e, ctx, grips)
