from xml.sax.saxutils import escape, quoteattr

CAPS = ("butt", "round", "square")
JOINS = ("miter", "round", "bevel")


def n(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def hexcol(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def path_d(pts, closed):
    out = []
    for i, (x, y) in enumerate(pts):
        out.append(("M" if i == 0 else "L") + n(x) + " " + n(y))
    if closed:
        out.append("Z")
    return "".join(out)


def stroke_attrs(st, min_width):
    a = ' fill="none" stroke="%s" stroke-width="%s" stroke-linecap="%s" stroke-linejoin="%s"' % (hexcol(st.rgb), n(max(st.width, min_width)), CAPS[st.cap], JOINS[st.join])
    if st.dash:
        a += ' stroke-dasharray="%s"' % " ".join(n(v) for v in st.dash[0])
        if st.dash[1]:
            a += ' stroke-dashoffset="%s"' % n(st.dash[1])
    if st.alpha < 0.999:
        a += ' stroke-opacity="%s"' % n(st.alpha)
    return a


def render(sheet, min_width=0.05, background=True):
    w, h = sheet.width, sheet.height
    x0, y0, x1, y1 = sheet.printable
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<svg xmlns="http://www.w3.org/2000/svg" width="%smm" height="%smm" viewBox="0 0 %s %s">' % (n(w), n(h), n(w), n(h))]
    out.append("<title>%s</title>" % escape(sheet.name))
    if background:
        out.append('<rect x="0" y="0" width="%s" height="%s" fill="#ffffff"/>' % (n(w), n(h)))
    out.append('<defs><clipPath id="printable"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath></defs>' % (n(x0), n(h - y1), n(x1 - x0), n(y1 - y0)))
    out.append('<g clip-path="url(#printable)"><g transform="translate(0 %s) scale(1 -1)">' % n(h))
    ops = sheet.ops
    names = {k: v[0] for k, v in sheet.layers.items()}
    cur = None
    clips = 0
    ids = 0

    def close_layer():
        nonlocal cur
        if cur is not None:
            out.append("</g>")
            cur = None

    def open_layer(key):
        nonlocal cur
        if key == cur:
            return
        close_layer()
        if key is not None and key in names:
            out.append("<g data-layer=%s>" % quoteattr(names[key]))
            cur = key

    i = 0
    total = len(ops)
    while i < total:
        op = ops[i]
        k = op[0]
        if k == "C":
            close_layer()
            ids += 1
            d = "".join(path_d(r, True) for r in op[1])
            out.append('<clipPath id="c%d"><path d=%s clip-rule="%s"/></clipPath>' % (ids, quoteattr(d), "evenodd" if op[2] else "nonzero"))
            out.append('<g clip-path="url(#c%d)">' % ids)
            clips += 1
            i += 1
        elif k == "E":
            close_layer()
            if clips:
                out.append("</g>")
                clips -= 1
            i += 1
        elif k == "S":
            st = op[3]
            open_layer(st.layer)
            j = i
            d = []
            while j < total and ops[j][0] == "S" and ops[j][3] == st:
                d.append(path_d(ops[j][1], ops[j][2]))
                j += 1
            out.append("<path d=%s%s/>" % (quoteattr("".join(d)), stroke_attrs(st, min_width)))
            i = j
        elif k == "F":
            st = op[2]
            open_layer(st.layer)
            j = i
            d = []
            if op[3]:
                d.append("".join(path_d(r, True) for r in op[1]))
                j = i + 1
            else:
                while j < total and ops[j][0] == "F" and ops[j][2] == st and not ops[j][3]:
                    d.append("".join(path_d(r, True) for r in ops[j][1]))
                    j += 1
            a = ' fill="%s" fill-rule="%s"' % (hexcol(st.rgb), "evenodd" if op[3] else "nonzero")
            if st.alpha < 0.999:
                a += ' fill-opacity="%s"' % n(st.alpha)
            out.append("<path d=%s%s/>" % (quoteattr("".join(d)), a))
            i = j
        else:
            i += 1
    close_layer()
    while clips:
        out.append("</g>")
        clips -= 1
    out.append("</g></g></svg>")
    return "\n".join(out).encode("utf-8")
