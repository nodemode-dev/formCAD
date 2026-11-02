from app.dim import layout as DL
from app.dim import measure as DM
from app.dim import textmeasure
from app.dim import vars as DV
from app.display.resolve import Context


def make_context(doc):
    return Context(doc, {})


def generate(doc, dim, ctx=None):
    ctx = ctx or make_context(doc)
    d = doc.drawing
    V = DV.resolve(d, dim.style, dim.overrides)
    S = DV.scale_of(d, V)
    measure, rec, _fs = textmeasure.measurer(ctx, V.get("DIMTXSTY") or "Standard")
    ht = textmeasure.text_height(rec, V, S)
    return DL.generate(dim, V, S, measure, ht), V, S


def refresh(doc, dim, ctx=None, keep_block=False):
    dim.measurement = round(DM.value_of(dim), 12)
    if not keep_block:
        dim.block = ""
    out, V, S = generate(doc, dim, ctx)
    if not dim.text_moved and out.text_center is not None:
        dim.text_point = [out.text_center[0], out.text_center[1], 0.0]
    return out


def measurement_text(doc, dim) -> str:
    from app.dim import compose

    V = DV.resolve(doc.drawing, dim.style, dim.overrides)
    return compose.measurement_text(dim, V)
