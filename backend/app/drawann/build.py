import math

from app.drawann import glyphs, settings

TEXT_W = 0.8


def tw(text, h) -> float:
    return TEXT_W * h * len(str(text))


def xform(prims, pos, rot):
    c, s = math.cos(rot), math.sin(rot)

    def P(x, y):
        return (pos[0] + x * c - y * s, pos[1] + x * s + y * c)

    out = []
    for p in prims:
        t = p[0]
        if t == "l":
            a, b = P(p[1], p[2]), P(p[3], p[4])
            out.append(("l", a[0], a[1], b[0], b[1]))
        elif t == "c":
            a = P(p[1], p[2])
            out.append(("c", a[0], a[1], p[3]))
        elif t == "a":
            a = P(p[1], p[2])
            out.append(("a", a[0], a[1], p[3], p[4] + rot, p[5] + rot))
        elif t == "p":
            out.append(("p", [P(x, y) for x, y in p[1]], p[2]))
        elif t == "f":
            out.append(("f", [P(x, y) for x, y in p[1]]))
        elif t == "t":
            a = P(p[1], p[2])
            out.append(("t", a[0], a[1], p[3], p[4], p[5], p[6] + rot))
    return out


def bounds_of(prims):
    xs, ys = [], []
    for p in prims:
        t = p[0]
        if t == "l":
            xs += [p[1], p[3]]
            ys += [p[2], p[4]]
        elif t in ("c", "a"):
            xs += [p[1] - p[3], p[1] + p[3]]
            ys += [p[2] - p[3], p[2] + p[3]]
        elif t in ("p", "f"):
            for x, y in p[1]:
                xs.append(x)
                ys.append(y)
        elif t == "t":
            w = tw(p[4], p[3])
            ox = {"l": 0.0, "c": -w / 2.0, "r": -w}[p[5]]
            c, s = math.cos(p[6]), math.sin(p[6])
            for dx, dy in ((ox, -p[3] / 2.0), (ox + w, p[3] / 2.0)):
                xs.append(p[1] + dx * c - dy * s)
                ys.append(p[2] + dx * s + dy * c)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def circled(letter, cx, cy, r):
    return [("c", cx, cy, r), ("t", cx, cy, r * 1.25, letter, "c", 0.0)]


def diameter_sign(cx, cy, r, sphere=False):
    d = r * 0.8
    out = [("c", cx, cy, r), ("l", cx - d * 1.25, cy - d * 1.25, cx + d * 1.25, cy + d * 1.25)]
    if sphere:
        out.append(("t", cx - r * 1.9, cy, r * 1.6, "S", "c", 0.0))
    return out


def arrow_head(tip, frm, size):
    dx, dy = tip[0] - frm[0], tip[1] - frm[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    half = size * 0.18
    return ("f", [tip, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)])


def dot_head(tip, size):
    return ("f", [(tip[0] + size * 0.4 * math.cos(k * math.pi / 6), tip[1] + size * 0.4 * math.sin(k * math.pi / 6)) for k in range(12)])


def frame_layout(e, st):
    th = float(e.text_height) or st["text_height"]
    H = 2.0 * th
    order = list(e.order) if e.order else list(st["gdt_order"])
    pad = 0.55 * th
    comps = []
    x = 0.0
    prims = []
    gkey = glyphs.key_of(e.char)
    datums = [d for d in (e.datums or [])[:3] if d and str(d.get("ref", "")).strip()]
    for name in order:
        if name == "characteristic":
            w = H
            prims += glyphs.glyph(gkey, 0.72 * H, x + w / 2.0, 0.0)
        elif name == "tolerance":
            parts = []
            if e.zone == "dia":
                parts.append(("dia", 1.05 * th))
            elif e.zone == "sdia":
                parts.append(("sdia", 1.9 * th))
            if str(e.tolerance) != "":
                parts.append(("val", tw(e.tolerance, th)))
            if e.modifier:
                parts.append(("mod:" + e.modifier, 1.25 * th))
            if e.projected:
                parts.append(("mod:P", 1.25 * th))
            gap = 0.3 * th
            w = 2 * pad + sum(p[1] for p in parts) + gap * max(0, len(parts) - 1)
            w = max(w, H)
            cx = x + pad
            for kind, pw in parts:
                mid = cx + pw / 2.0
                if kind == "dia":
                    prims += diameter_sign(mid, 0.0, 0.5 * th)
                elif kind == "sdia":
                    prims += diameter_sign(mid + 0.45 * th, 0.0, 0.5 * th, True)
                elif kind == "val":
                    prims.append(("t", cx, 0.0, th, str(e.tolerance), "l", 0.0))
                else:
                    prims += circled(kind[4:], mid, 0.0, 0.5 * th)
                cx += pw + gap
        else:
            idx = int(name[5:]) - 1
            if idx >= len(datums):
                continue
            d = datums[idx]
            ref = str(d.get("ref"))
            mod = glyphs.modifier_of(d.get("mod", ""))
            pw = tw(ref, th)
            w = 2 * pad + pw + (0.3 * th + 1.25 * th if mod else 0.0)
            w = max(w, H)
            cx = x + (w - (pw + (0.3 * th + 1.25 * th if mod else 0.0))) / 2.0
            prims.append(("t", cx, 0.0, th, ref, "l", 0.0))
            if mod:
                prims += circled(mod, cx + pw + 0.3 * th + 0.625 * th, 0.0, 0.5 * th)
        comps.append((name, x, x + w))
        x += w
    W = x
    prims.append(("p", [(0, -H / 2), (W, -H / 2), (W, H / 2), (0, H / 2)], True))
    for _n, _a, b in comps[:-1]:
        prims.append(("l", b, -H / 2, b, H / 2))
    if e.note_above:
        prims.append(("t", 0.0, H / 2 + 0.35 * th + th / 2, th, str(e.note_above), "l", 0.0))
    if e.note_below:
        prims.append(("t", 0.0, -H / 2 - 0.35 * th - th / 2, th, str(e.note_below), "l", 0.0))
    return prims, W, H, th


def gdt_frame(e, st):
    local, W, H, th = frame_layout(e, st)
    rot = float(e.rotation)
    pos = (float(e.position[0]), float(e.position[1]))
    prims = xform(local, pos, rot)
    info = {"width": W, "height": H}
    pts = [(float(p[0]), float(p[1])) for p in (e.leader or [])]
    c, s = math.cos(rot), math.sin(rot)
    left = (pos[0], pos[1])
    right = (pos[0] + W * c, pos[1] + W * s)
    if pts:
        tip = pts[0]
        dl = math.hypot(tip[0] - left[0], tip[1] - left[1])
        dr = math.hypot(tip[0] - right[0], tip[1] - right[1])
        side = e.leader_side if e.leader_side in ("left", "right") else ("left" if dl <= dr else "right")
        att = left if side == "left" else right
        path = pts + [att]
        for a, b in zip(path, path[1:]):
            prims.append(("l", a[0], a[1], b[0], b[1]))
        if e.arrow and len(path) >= 2:
            prims.append(arrow_head(path[0], path[1], st["arrow_size"]))
        info["attach"] = att
    return prims, info


def datum_symbol(e, st):
    th = float(e.text_height) or st["text_height"]
    S = 2.0 * th
    c = (float(e.position[0]), float(e.position[1]))
    prims = [("p", [(c[0] - S / 2, c[1] - S / 2), (c[0] + S / 2, c[1] - S / 2), (c[0] + S / 2, c[1] + S / 2), (c[0] - S / 2, c[1] + S / 2)], True), ("t", c[0], c[1], th, str(e.letter), "c", 0.0)]
    tip = e.tip if e.tip else [c[0], c[1] - S / 2 - 2.5 * th, 0.0]
    tip = (float(tip[0]), float(tip[1]))
    dx, dy = tip[0] - c[0], tip[1] - c[1]
    if abs(dx) > abs(dy):
        start = (c[0] + math.copysign(S / 2, dx), c[1])
    else:
        start = (c[0], c[1] + math.copysign(S / 2, dy))
    n = math.hypot(tip[0] - start[0], tip[1] - start[1]) or 1.0
    ux, uy = (tip[0] - start[0]) / n, (tip[1] - start[1]) / n
    h = 0.9 * th
    base = (tip[0] - ux * h * 1.2, tip[1] - uy * h * 1.2)
    left = (base[0] - uy * h * 0.5, base[1] + ux * h * 0.5)
    right = (base[0] + uy * h * 0.5, base[1] - ux * h * 0.5)
    prims.append(("l", start[0], start[1], base[0], base[1]))
    if e.filled:
        prims.append(("f", [tip, left, right]))
    else:
        prims.append(("p", [tip, left, right], True))
    return prims, {"tip": tip}


def balloon(e, st):
    D = float(e.diameter) or st["balloon_diameter"]
    r = D / 2.0
    c = (float(e.position[0]), float(e.position[1]))
    text = str(e.text)
    h = min(0.5 * D, 0.82 * D / max(TEXT_W * len(text), 1.0))
    prims = [("c", c[0], c[1], r), ("t", c[0], c[1], h, text, "c", 0.0)]
    if e.tip:
        tip = (float(e.tip[0]), float(e.tip[1]))
        dx, dy = tip[0] - c[0], tip[1] - c[1]
        n = math.hypot(dx, dy)
        if n > r + 1e-9:
            ux, uy = dx / n, dy / n
            start = (c[0] + ux * r, c[1] + uy * r)
            prims.append(("l", start[0], start[1], tip[0], tip[1]))
            end = e.end or st["balloon_end"]
            prims.append(dot_head(tip, st["arrow_size"]) if end == "dot" else arrow_head(tip, start, st["arrow_size"]))
    return prims, {"diameter": D, "text_height": h}


def finish_mark(e, st):
    h = float(e.height) or st["finish_height"]
    w = tw(e.value, h) + 0.4 * h
    local = [("l", -0.6 * h, 0.6 * h, 0.0, 0.0), ("l", 0.0, 0.0, 1.2 * h, 2.4 * h), ("l", 1.2 * h, 2.4 * h, 1.2 * h + w, 2.4 * h), ("t", 1.35 * h, 2.4 * h + 0.2 * h + h / 2.0, h, str(e.value), "l", 0.0)]
    pos = (float(e.position[0]), float(e.position[1]))
    return xform(local, pos, float(e.rotation)), {}


def chain_line(p0, p1, long_, short, gap):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return []
    ux, uy = dx / L, dy / L
    mid = L / 2.0
    spans = [(mid - short / 2.0, mid + short / 2.0)]
    lo = mid - short / 2.0 - gap
    hi = mid + short / 2.0 + gap
    use_long = True
    while lo > 1e-9:
        seg = long_ if use_long else short
        spans.append((max(0.0, lo - seg), lo))
        spans.append((hi, min(L, hi + seg)))
        lo = lo - seg - gap
        hi = hi + seg + gap
        use_long = not use_long
    out = []
    for a, b in spans:
        if b - a > 1e-6:
            out.append(("l", p0[0] + ux * a, p0[1] + uy * a, p0[0] + ux * b, p0[1] + uy * b))
    return out


def center_mark(e, st):
    ext, gap, lg, sh = st["center_extension"], st["center_gap"], st["center_long"], st["center_short"]
    if e.mode == "axis":
        a = (float(e.a[0]), float(e.a[1]))
        b = (float(e.b[0]), float(e.b[1]))
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-9:
            return [], {}
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        p0 = (a[0] - ux * ext, a[1] - uy * ext)
        p1 = (b[0] + ux * ext, b[1] + uy * ext)
        if L + 2 * ext < 4 * lg:
            return [("l", p0[0], p0[1], p1[0], p1[1])], {}
        return chain_line(p0, p1, lg, sh, gap), {}
    c = (float(e.center[0]), float(e.center[1]))
    r = float(e.radius)
    reach = r + ext
    prims = []
    if 2 * reach < 4 * lg:
        for ang in (0.0, math.pi / 2):
            ca, sa = math.cos(ang), math.sin(ang)
            prims.append(("l", c[0] - reach * ca, c[1] - reach * sa, c[0] + reach * ca, c[1] + reach * sa))
        return prims, {}
    for ang in (0.0, math.pi / 2):
        ca, sa = math.cos(ang), math.sin(ang)
        prims += chain_line((c[0] - reach * ca, c[1] - reach * sa), (c[0] + reach * ca, c[1] + reach * sa), lg, sh, gap)
    return prims, {}


def build(e, st=None, d=None):
    st = st or (settings.get(d) if d is not None else dict(settings.DEFAULTS))
    fn = {"gdtframe": gdt_frame, "datumsym": datum_symbol, "balloon": balloon, "finishmark": finish_mark, "centermark": center_mark}[e.kind]
    return fn(e, st)
