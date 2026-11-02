from app.display import shapes
from app.doc import attribs as A
from app.text.model import affine


@shapes.builder("attdef")
def attdef(e, ctx):
    return shapes.text(A.display_text(e), ctx)


def add_attributes(ctx, ent, m, pp, state):
    from app.display import insert as I

    attmode = int(ctx.d.header.get("ATTMODE", 1))
    if attmode == 0:
        return
    for _att, t in A.shown_texts(ctx.d, ent, attmode, m):
        if not ctx.visible(t, pp):
            continue
        cp = ctx.props(t, pp)
        res = shapes.build(t, ctx)
        if not res:
            continue
        g, prims, _grips, bb = res
        state["count"] += 1
        tag = None
        if cp.rgb != pp.rgb or cp.c7 != pp.c7:
            tag = {"c": list(cp.rgb)}
            if cp.c7:
                tag["c7"] = True
        state["parts"].append(I.part_props(g, cp))
        state["prims"].extend(I.xf_prims(prims, affine(), tag))
        if bb:
            state["bounds"].extend([[bb[0], bb[1]], [bb[2], bb[3]]])
