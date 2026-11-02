from app.text import bidi, scripts, shaping


def annotate(ctx, para):
    items = para.items
    chars = []
    fss = []
    for it in items:
        if it[0] == "c":
            chars.append(it[1])
            fss.append(ctx.fs(it[2]))
        elif it[0] == "tab":
            chars.append("\t")
            fss.append(None)
        elif it[0] == "br":
            chars.append(" ")
            fss.append(None)
        else:
            chars.append("￼")
            fss.append(None)
    clusters, levels, base = shaping.shape(None, chars, fss)
    para.base = base
    para.rtl = base % 2 == 1
    para.mixed = any(v % 2 for v in levels)
    for k, it in enumerate(items):
        if it[0] == "c":
            items[k] = it + ((clusters[k], levels[k]),)


def reorder_line(ln):
    para = ln.para
    if not getattr(para, "mixed", False):
        return
    text = []
    levels = []
    for it, _x, _w in ln.cells:
        if it[0] == "c":
            text.append(it[1])
            levels.append(it[4][1])
        elif it[0] == "tab":
            text.append("\t")
            levels.append(para.base)
        elif it[0] == "br":
            text.append(" ")
            levels.append(para.base)
        else:
            text.append("￼")
            levels.append(para.base)
    if not any(v % 2 for v in levels):
        return
    ll = bidi.line_levels("".join(text), levels, para.base)
    order = bidi.visual_order(ll)
    x = ln.x0
    out = []
    ink = x
    for k in order:
        it, _x, w = ln.cells[k]
        out.append((it, x, w))
        if it[0] == "c" and it[1] == " " and not it[3]:
            pass
        elif it[0] == "c":
            ink = max(ink, x + w - it[4][0].trail * it[2].h * it[2].wf)
        else:
            ink = max(ink, x + w)
        x += w
    ln.cells = out
    ln.x1 = ink


def thai_pieces(tok):
    if len(tok) < 2 or any(it[0] != "c" for it in tok):
        return [tok]
    text = "".join(it[1] for it in tok)
    if not any(scripts.is_thai(c) for c in text):
        return [tok]
    return [tok[a:b] for a, b in scripts.thai_pieces(text)]
