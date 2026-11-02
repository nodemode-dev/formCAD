import json

from app.display import shapes

KINDS = ("circle", "arc", "point", "lwpolyline", "ellipse")
_encode = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode


def wrap(kind):
    inner = shapes.BUILDERS.get(kind)
    if inner is None or getattr(inner, "marked", False):
        return

    def marked(e, ctx):
        res = inner(e, ctx)
        if res is None:
            return res
        mark = lookup(ctx, e)
        if mark is None:
            return res
        g, prims, grips, bb = res
        return g, list(prims) + [mark], grips, bb

    marked.marked = True
    shapes.BUILDERS[kind] = marked


def lookup(ctx, e):
    from app.param import marks

    return marks.mark_for(ctx.doc, e.handle)


def line_hook(e, ctx, entry):
    mark = lookup(ctx, e)
    if mark is not None:
        entry.js = entry.js.replace('"prims":[]', '"prims":[%s]' % _encode(mark), 1)
    return entry


for _kind in KINDS:
    wrap(_kind)

from app.display import state

if line_hook not in state.LINE_HOOKS:
    state.LINE_HOOKS.append(line_hook)
