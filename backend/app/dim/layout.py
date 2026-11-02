import math

from app.dim import arrows as AR
from app.dim import blocks, compose, sectors
from app.dim import vec as V_
from app.dim.out import Out
from app.dim.vec import add, cross, dist, dot, mul, perp, sub, unit, xy


class Gen:
    def __init__(self, dim, V, S, measure, text_height=None):
        self.dim = dim
        self.V = V
        self.S = S
        self.measure = measure
        self.out = Out()
        self.tick = float(V.get("DIMTSZ", 0.0)) > 0.0
        self.asz = (float(V["DIMTSZ"]) if self.tick else float(V["DIMASZ"])) * S
        self.exo = float(V["DIMEXO"]) * S
        self.exe = float(V["DIMEXE"]) * S
        self.gap_raw = float(V["DIMGAP"]) * S
        self.gap = abs(self.gap_raw)
        self.ht = float(text_height) if text_height else float(V["DIMTXT"]) * S
        self.dle = float(V.get("DIMDLE", 0.0)) * S
        n1 = V.get("DIMBLK1") or V.get("DIMBLK") or ""
        n2 = V.get("DIMBLK2") or V.get("DIMBLK") or ""
        self.name1, self.name2 = n1, n2
        self.tad = int(V["DIMTAD"])
        self.just = int(V["DIMJUST"])
        self.atfit = int(V["DIMATFIT"])
        self.marks = dim.marks or {}
        self._block = None

    def block(self):
        if self._block is None:
            cont = compose.content(self.dim, self.V)
            self._block = blocks.build(cont, self.V, self.ht, self.measure, self.marks.get("inspect"), self.gap_raw < 0, self.gap)
        return self._block

    def text_rot(self, inside, line_angle):
        a = self.marks.get("text_angle")
        if a is not None:
            return float(a)
        horizontal = int(self.V["DIMTIH"]) if inside else int(self.V["DIMTOH"])
        if horizontal:
            return 0.0
        return V_.readable(line_angle)

    def support(self, rot, dirv):
        b = self.block()
        r = (math.cos(rot), math.sin(rot))
        up = (-r[1], r[0])
        return b.width / 2.0 * abs(dot(dirv, r)) + b.half_height() * abs(dot(dirv, up))

    def place(self, center, rot):
        b = self.block()
        b.center = (center[0], center[1])
        b.rot = rot
        self.out.blocks.append(b)
        self.out.text_center = b.center
        self.out.text_rot = rot

    def arrow_pair(self, name, tip, direction):
        a = AR.build(name, tip, direction, self.asz, self.tick)
        return a

    def ext_line(self, origin, onl, e, role):
        d = dot(sub(onl, origin), e)
        start = self.exo
        if int(self.V.get("DIMFXLON", 0)):
            start = max(self.exo, d - float(self.V["DIMFXL"]) * self.S)
        end = d + self.exe
        if end - start > 1e-12:
            self.out.seg(add(origin, mul(e, start)), add(origin, mul(e, end)), role)

    def leader_to_text(self, foot, center, rot):
        dv = unit(sub(center, foot))
        s = self.support(rot, dv)
        end = sub(center, mul(dv, s + self.gap * 0.5))
        if dot(sub(end, foot), dv) > 1e-9:
            self.out.seg(foot, end, "dim")
            name = self.V.get("DIMLDRBLK") or ""
            if name:
                self.out.add_arrow(AR.build(name, foot, mul(dv, -1.0), self.asz, self.tick))


def _fit(g, L, E, moved_inside=None):
    gapz = g.gap
    fw1 = AR.fit_width(g.name1, g.asz, g.tick)
    fw2 = AR.fit_width(g.name2, g.asz, g.tick)
    arrows_ok = fw1 + fw2 <= L + 1e-9
    text_ok = E + 2 * gapz <= L + 1e-9
    both_ok = E + 2 * gapz + fw1 + fw2 <= L + 1e-9
    mode = g.atfit
    if both_ok:
        res = (True, True)
    elif mode == 0:
        res = (False, False)
    elif mode == 1:
        res = (True, False) if text_ok else (False, False)
    elif mode == 2:
        res = (False, True) if arrows_ok else (False, False)
    else:
        if text_ok:
            res = (True, False)
        elif arrows_ok:
            res = (False, True)
        else:
            res = (False, False)
    text_in, arrows_in = res
    if int(g.V.get("DIMTIX", 0)):
        text_in = True
        if not both_ok:
            arrows_in = False if not (arrows_ok and mode == 2) else True
    if not (fw1 + fw2) and g.asz >= 0:
        arrows_in = True if (g.tick or AR.canonical(g.name1) in ("oblique", "architectural tick", "none", "integral")) else arrows_in
    return text_in, arrows_in, arrows_ok


def _perp_offset(g, rot, nn, outside_dir):
    b = g.block()
    tad = g.tad
    r = (math.cos(rot), math.sin(rot))
    up = (-r[1], r[0])
    side = nn if dot(nn, up) >= -1e-9 else mul(nn, -1.0)
    if tad == 0:
        off = float(g.V.get("DIMTVP", 0.0)) * g.ht
        return mul(side, off), False
    clear = g.gap + b.width / 2.0 * abs(dot(side, r)) + b.half_height() * abs(dot(side, up))
    if tad == 2:
        return mul(outside_dir, clear), True
    if tad == 4:
        return mul(side, -clear), True
    return mul(side, clear), True


def _breaks(g, segs_along, lo, hi):
    out = []
    for s0, s1 in segs_along:
        if hi <= s0 or lo >= s1:
            out.append((s0, s1))
            continue
        if lo > s0:
            out.append((s0, lo))
        if hi < s1:
            out.append((hi, s1))
    return out


def gen_linear(g):
    d, V = g.dim, g.V
    a, b = xy(d.p13), xy(d.p14)
    D = xy(d.def_point)
    if d.dim_type == "aligned" and dist(a, b) > 1e-12:
        th = V_.ang_of(sub(b, a))
    else:
        th = float(d.rotation)
    u = (math.cos(th), math.sin(th))
    n = perp(u)
    ob = g.marks.get("oblique")
    v = (math.cos(ob), math.sin(ob)) if ob is not None else n
    vn = dot(v, n)
    if abs(vn) < 1e-6:
        v, vn = n, 1.0

    def onl(p):
        s = -dot(sub(p, D), n) / vn
        return add(p, mul(v, s))

    a1, b1 = onl(a), onl(b)
    e1 = unit(sub(a1, a), v)
    e2 = unit(sub(b1, b), v)
    if not int(V["DIMSE1"]):
        g.ext_line(a, a1, e1, "ext1")
    if not int(V["DIMSE2"]):
        g.ext_line(b, b1, e2, "ext2")
    L = dist(a1, b1)
    w = unit(sub(b1, a1), u)
    nn = n
    blk = g.block()
    out = g.out
    s1 = int(V["DIMSD1"])
    s2 = int(V["DIMSD2"])
    mid_o = V_.mul(add(a, b), 0.5)
    out_dir = mul(n, -1.0) if dot(sub(mid_o, D), n) >= 0 else n
    if dot(sub(mid_o, D), n) == 0:
        out_dir = n
    moved = bool(d.text_moved and d.text_point)
    rot_in = g.text_rot(True, th)
    rot_out = g.text_rot(False, th)
    E_in = g.support(rot_in, w) * 2.0 if not blk.empty else 0.0
    tmove = int(V["DIMTMOVE"])
    text_in = arrows_in = True
    along = L / 2.0
    center = None
    rot = rot_in
    off = (0.0, 0.0)
    above = False
    on_line = True
    over = g.just in (3, 4) and not moved and not blk.empty
    if blk.empty:
        _t, arrows_in, _ok = _fit(g, L, 0.0)
        text_in = True
    elif moved:
        T = xy(d.text_point)
        along_t = dot(sub(T, a1), w)
        perp_t = dot(sub(T, a1), n)
        text_in = along_t - E_in / 2.0 >= -1e-9 and along_t + E_in / 2.0 <= L + 1e-9
        collide = abs(perp_t) < blk.half_height() + g.gap * 0.5
        arrows_ok = AR.fit_width(g.name1, g.asz, g.tick) + AR.fit_width(g.name2, g.asz, g.tick) <= L + 1e-9
        both_ok = E_in + 2 * g.gap + AR.fit_width(g.name1, g.asz, g.tick) + AR.fit_width(g.name2, g.asz, g.tick) <= L + 1e-9
        arrows_in = (both_ok if collide else arrows_ok) if text_in else arrows_ok
        if not AR.fit_width(g.name1, g.asz, g.tick) and not AR.fit_width(g.name2, g.asz, g.tick):
            arrows_in = True
        center = T
        rot = rot_in if text_in else rot_out
        on_line = text_in and collide
        along = along_t
    elif over:
        _t, arrows_in, _ok = _fit(g, L, 0.0)
        text_in = False
    else:
        text_in, arrows_in, _ok = _fit(g, L, E_in)
    if center is None and not blk.empty:
        if over:
            e = e1 if g.just == 3 else e2
            piv = a1 if g.just == 3 else b1
            rot = V_.readable(V_.ang_of(e)) if g.marks.get("text_angle") is None else float(g.marks["text_angle"])
            sup = g.support(rot, e)
            center = add(piv, mul(e, g.exe + g.gap + sup))
            on_line = False
        elif text_in:
            rot = rot_in
            E = g.support(rot, w) * 2.0
            lead1 = (g.asz if arrows_in else 0.0) + g.gap
            if g.just == 1:
                along = lead1 + E / 2.0
            elif g.just == 2:
                along = L - lead1 - E / 2.0
            else:
                along = L / 2.0
            along = min(max(along, E / 2.0), max(L - E / 2.0, E / 2.0)) if L > E else L / 2.0
            base = add(a1, mul(w, along))
            offv, above = _perp_offset(g, rot, nn, out_dir)
            center = add(base, offv)
            on_line = not above and abs(float(V.get("DIMTVP", 0.0)) * g.ht) < blk.half_height()
        else:
            rot = rot_out
            E = g.support(rot, w) * 2.0
            left = g.just in (1, 3)
            K = 2 * g.asz if not arrows_in else g.asz
            start = K + g.gap
            if left:
                base = sub(a1, mul(w, start + E / 2.0))
                along = -(start + E / 2.0)
            else:
                base = add(b1, mul(w, start + E / 2.0))
                along = L + start + E / 2.0
            offv, above = _perp_offset(g, rot, nn, out_dir)
            center = add(base, offv)
            on_line = not above
    if center is not None:
        g.place(center, rot)
    E_final = g.support(rot, w) * 2.0 if center is not None else 0.0

    suppress_arrows = int(V["DIMSOXD"]) and not arrows_in
    names = (g.name1, g.name2)
    tips = ((a1, -1.0, s1), (b1, 1.0, s2))
    trims = [0.0, 0.0]
    stretch = [0.0, 0.0]
    for i, (tip, sg, sup) in enumerate(tips):
        if sup:
            continue
        nm = names[i]
        direction = mul(w, sg) if arrows_in else mul(w, -sg)
        arr = g.arrow_pair(nm, tip, direction)
        if not suppress_arrows:
            out.add_arrow(arr)
            if arrows_in:
                trims[i] = arr.trim
        kind = AR.canonical(nm)
        if (g.tick or kind in ("oblique", "architectural tick", "none")) and arrows_in:
            stretch[i] = g.dle
    t_start = -stretch[0] + trims[0]
    t_end = L + stretch[1] - trims[1]
    split = along if (center is not None and text_in and not over) else L / 2.0
    split = min(max(split, 0.0), L)
    draw_line = arrows_in or int(V["DIMTOFL"])
    line_segs = []
    if draw_line:
        if s1 and s2:
            pass
        else:
            lo_s = 0.0 if not s1 else split
            hi_s = L if not s2 else split
            lo_s = t_start if not s1 else lo_s
            hi_s = t_end if not s2 else hi_s
            if not s1 and not s2:
                line_segs = [(lo_s, hi_s)]
            elif s1:
                line_segs = [(split, hi_s)]
            else:
                line_segs = [(lo_s, split)]
        if center is not None and text_in and on_line and not over:
            lo = along - E_final / 2.0 - g.gap
            hi = along + E_final / 2.0 + g.gap
            line_segs = _breaks(g, line_segs, lo, hi)
    for s0, s1_ in line_segs:
        out.seg(add(a1, mul(w, s0)), add(a1, mul(w, s1_)), "dim")
    if not arrows_in and not suppress_arrows:
        K = 2 * g.asz
        cover0 = 0.0
        cover1 = 0.0
        if center is not None and not text_in and not over:
            ext = E_final
            if g.tad > 0 and not moved:
                if along > L:
                    cover1 = along + ext / 2.0 - L
                elif along < 0:
                    cover0 = -(along - ext / 2.0)
        if not s1:
            out.seg(a1, sub(a1, mul(w, max(K, cover0))), "dim")
        if not s2:
            out.seg(b1, add(b1, mul(w, max(K, cover1))), "dim")
    if center is not None and moved and tmove == 1:
        foot_t = min(max(along, 0.0), L)
        foot = add(a1, mul(w, foot_t))
        far = abs(dot(sub(center, foot), n)) > blk.half_height() + g.gap or not text_in
        if far:
            g.leader_to_text(foot, center, rot)
    jog = g.marks.get("jog")
    if jog:
        _apply_jog(g, a1, w, n, L, jog)
    out.notes.update({"a1": a1, "b1": b1, "w": w, "n": n, "L": L, "text_in": text_in, "arrows_in": arrows_in, "along": along})


def _zigzag(c, u, n, h, ang):
    tn = math.tan(max(math.radians(1.0), min(math.radians(89.0), ang)))
    c_ = h / tn
    return [sub(c, mul(u, c_)), add(sub(c, mul(u, c_ / 2.0)), mul(n, h / 2.0)), sub(add(c, mul(u, c_ / 2.0)), mul(n, h / 2.0)), add(c, mul(u, c_))], c_


def _apply_jog(g, a1, w, n, L, jog):
    p = xy(jog)
    t = dot(sub(p, a1), w)
    t = min(max(t, 0.0), L)
    h = 1.5 * (g.asz if g.asz > 0 else g.ht * 0.5)
    ang = math.radians(float(g.V.get("DIMJOGANG", 45.0)) or 45.0)
    c = add(a1, mul(w, t))
    zz, c_ = _zigzag(c, w, n, h, ang)
    out = g.out
    kept = []
    for p0, p1, role in out.segs:
        if role != "dim":
            kept.append((p0, p1, role))
            continue
        t0 = dot(sub(p0, a1), w)
        t1 = dot(sub(p1, a1), w)
        if abs(cross(sub(p1, p0), w)) > 1e-9 or t0 > t1:
            kept.append((p0, p1, role))
            continue
        lo, hi = t - c_, t + c_
        if t1 <= lo or t0 >= hi:
            kept.append((p0, p1, role))
            continue
        if t0 < lo:
            kept.append((p0, add(a1, mul(w, lo)), role))
        if t1 > hi:
            kept.append((add(a1, mul(w, hi)), p1, role))
    out.segs = kept
    out.polys.append(([zz[0]] + zz[1:3] + [zz[3]], False, "dim"))
    out.notes["jog_at"] = c


def center_mark(g, c, r, role="dim"):
    size = float(g.V["DIMCEN"]) * g.S
    if size == 0:
        return
    m = abs(size)
    for dv in ((1.0, 0.0), (0.0, 1.0)):
        if size > 0:
            g.out.seg(sub(c, mul(dv, m)), add(c, mul(dv, m)), role)
        else:
            for sg in (1.0, -1.0):
                g.out.seg(add(c, mul(dv, sg * m * 0.5)), add(c, mul(dv, sg * (r + m))), role)


def gen_center(g):
    d = g.dim
    c = xy(d.p15)
    r = float(g.marks.get("radius", 0.0))
    center_mark(g, c, r)


def gen_radius(g):
    d, V = g.dim, g.V
    C, P = xy(d.def_point), xy(d.p15)
    r = dist(C, P)
    out = g.out
    if r < 1e-12:
        return
    u = unit(sub(P, C))
    blk = g.block()
    T = xy(d.text_point) if d.text_point else add(C, mul(u, r * 0.5))
    inside = dist(T, C) <= r
    g_dir = unit(sub(T, C), u)
    rot_ang = V_.ang_of(u)
    if inside:
        rot = g.text_rot(True, rot_ang)
        arr = g.arrow_pair(g.name2 or g.name1, P, u)
        out.add_arrow(arr)
        if not blk.empty:
            g.place(T, rot)
            E = g.support(rot, u) * 2.0
            tc = dot(sub(T, C), u)
            on = abs(dot(sub(T, C), perp(u))) < blk.half_height()
            if g.tad == 0 and on:
                s_lo = tc - E / 2.0 - g.gap
                s_hi = tc + E / 2.0 + g.gap
                segs = _breaks(g, [(0.0, r - arr.trim)], s_lo, s_hi)
            else:
                segs = [(0.0, r - arr.trim)]
        else:
            segs = [(0.0, r - arr.trim)]
        for s0, s1 in segs:
            out.seg(add(C, mul(u, s0)), add(C, mul(u, s1)), "dim")
    else:
        rot = g.text_rot(False, rot_ang)
        arr = g.arrow_pair(g.name2 or g.name1, P, mul(u, -1.0))
        out.add_arrow(arr)
        lead = unit(sub(T, P), u)
        horiz = int(V["DIMTOH"]) and g.marks.get("text_angle") is None
        land = g.asz if horiz else 0.0
        if not blk.empty:
            g.place(T, rot)
            sgn = 1.0 if (T[0] - P[0]) >= 0 else -1.0
            if horiz and land > 0:
                sup = g.support(rot, (sgn, 0.0))
                end_text = (T[0] - sgn * (sup + g.gap), T[1])
                elbow = (end_text[0] - sgn * land, end_text[1])
                out.seg(P, elbow, "dim")
                out.seg(elbow, end_text, "dim")
            else:
                sup = g.support(rot, lead)
                out.seg(P, sub(T, mul(lead, sup + g.gap)), "dim")
        else:
            out.seg(P, T, "dim")
        center_mark(g, C, r)
        out.notes["outside"] = True


def gen_diameter(g):
    d, V = g.dim, g.V
    F, N = xy(d.def_point), xy(d.p15)
    r2 = dist(F, N)
    if r2 < 1e-12:
        return
    C = V_.mul(add(F, N), 0.5)
    r = r2 / 2.0
    u = unit(sub(N, F))
    out = g.out
    blk = g.block()
    T = xy(d.text_point) if d.text_point else C
    inside = dist(T, C) <= r + 1e-9
    rot_ang = V_.ang_of(u)
    a_far = g.arrow_pair(g.name1, F, mul(u, -1.0))
    if inside:
        rot = g.text_rot(True, rot_ang)
        a_near = g.arrow_pair(g.name2 or g.name1, N, u)
        out.add_arrow(a_far)
        out.add_arrow(a_near)
        lo, hi = a_far.trim, r2 - a_near.trim
        segs = [(lo, hi)]
        if not blk.empty:
            g.place(T, rot)
            E = g.support(rot, u) * 2.0
            tc = dot(sub(T, F), u)
            on = abs(dot(sub(T, F), perp(u))) < blk.half_height()
            if g.tad == 0 and on:
                segs = _breaks(g, segs, tc - E / 2.0 - g.gap, tc + E / 2.0 + g.gap)
        for s0, s1 in segs:
            out.seg(add(F, mul(u, s0)), add(F, mul(u, s1)), "dim")
    else:
        rot = g.text_rot(False, rot_ang)
        side = 1.0 if dot(sub(T, C), u) >= 0 else -1.0
        near = N if side > 0 else F
        far = F if side > 0 else N
        dn = mul(u, side)
        a_near = g.arrow_pair(g.name1, near, mul(dn, -1.0))
        a_far2 = g.arrow_pair(g.name2 or g.name1, far, mul(dn, -1.0))
        out.add_arrow(a_near)
        out.add_arrow(a_far2)
        out.seg(add(far, mul(dn, a_far2.trim)), near, "dim")
        horiz = int(V["DIMTOH"]) and g.marks.get("text_angle") is None
        if not blk.empty:
            g.place(T, rot)
            sgn = 1.0 if (T[0] - near[0]) >= 0 else -1.0
            if horiz and g.asz > 0:
                sup = g.support(rot, (sgn, 0.0))
                end_text = (T[0] - sgn * (sup + g.gap), T[1])
                elbow = (end_text[0] - sgn * g.asz, end_text[1])
                out.seg(near, elbow, "dim")
                out.seg(elbow, end_text, "dim")
            else:
                lead = unit(sub(T, near), dn)
                sup = g.support(rot, lead)
                out.seg(near, sub(T, mul(lead, sup + g.gap)), "dim")
        else:
            out.seg(near, T, "dim")
        center_mark(g, C, r)
        out.notes["outside"] = True


def gen_jogged(g):
    d, V = g.dim, g.V
    C, P = xy(d.def_point), xy(d.p15)
    O = xy(g.marks.get("jog_center") or d.def_point)
    J = xy(g.marks["jog_point"]) if g.marks.get("jog_point") else V_.mul(add(O, P), 0.5)
    out = g.out
    blk = g.block()
    u = unit(sub(P, O))
    T = xy(d.text_point) if d.text_point else add(P, mul(u, g.ht * 2))
    arr = g.arrow_pair(g.name2 or g.name1, P, mul(u, -1.0) if dot(sub(T, P), u) >= 0 else u)
    out.add_arrow(arr)
    n = perp(u)
    t = min(max(dot(sub(J, O), u), 0.0), dist(O, P))
    h = 1.5 * (g.asz if g.asz > 0 else g.ht * 0.5)
    ang = math.radians(float(V.get("DIMJOGANG", 45.0)) or 45.0)
    c = add(O, mul(u, t))
    zz, c_ = _zigzag(c, u, n, h, ang)
    first_end = zz[0]
    last_start = zz[3]
    out.seg(O, first_end, "dim")
    out.poly(zz, False, "dim")
    out.seg(last_start, P, "dim")
    rot = g.text_rot(False, V_.ang_of(u))
    if not blk.empty:
        g.place(T, rot)
        lead = unit(sub(T, P), u)
        sup = g.support(rot, lead)
        out.seg(P, sub(T, mul(lead, sup + g.gap)), "dim")
    out.notes["jog_at"] = c


def _arc_text(g, c, R, a0, sweep):
    out = g.out
    blk = g.block()
    mid = a0 + sweep / 2.0
    rr = (math.cos(mid), math.sin(mid))
    tg = perp(rr)
    L = R * sweep
    p_start = V_.polar(c, R, a0)
    p_end = V_.polar(c, R, a0 + sweep)
    t_start = (math.sin(a0), -math.cos(a0))
    t_end = (-math.sin(a0 + sweep), math.cos(a0 + sweep))
    moved = bool(g.dim.text_moved and g.dim.text_point)
    rot_in = g.text_rot(True, V_.ang_of(tg))
    rot_out = g.text_rot(False, V_.ang_of(tg))
    E_in = g.support(rot_in, tg) * 2.0 if not blk.empty else 0.0
    center = None
    rot = rot_in
    text_in = True
    on_line = True
    brk = None
    if blk.empty:
        _t, arrows_in, _ok = _fit(g, L, 0.0)
    elif moved:
        T = xy(g.dim.text_point)
        rho = dist(T, c)
        ang_t = V_.ang_of(sub(T, c))
        off_a = V_.ccw(a0, ang_t)
        text_in = off_a <= sweep and rho > 0
        fw = AR.fit_width(g.name1, g.asz, g.tick) + AR.fit_width(g.name2, g.asz, g.tick)
        collide = abs(rho - R) < blk.half_height() + g.gap * 0.5
        both = E_in + 2 * g.gap + fw <= L + 1e-9
        arrows_in = both if (text_in and collide) else fw <= L + 1e-9
        center = T
        rot = rot_in if text_in else rot_out
        on_line = text_in and collide
        brk = (V_.ccw(a0, ang_t) if off_a <= sweep else None)
    else:
        text_in, arrows_in, _ok = _fit(g, L, E_in)
        if text_in:
            rot = rot_in
            r_off, above = 0.0, False
            if g.tad == 0:
                r_off = float(g.V.get("DIMTVP", 0.0)) * g.ht
            else:
                sup = g.support(rot, rr)
                clear = g.gap + sup
                r_off = -clear if g.tad == 4 else clear
                above = True
            center = V_.polar(c, R + r_off, mid)
            on_line = not above
            brk = sweep / 2.0
        else:
            rot = rot_out
            E = g.support(rot, t_end) * 2.0
            K = 2 * g.asz if not arrows_in else g.asz
            center = add(p_end, mul(t_end, K + g.gap + E / 2.0))
            on_line = False
    if center is not None:
        g.place(center, rot)
    segs = [(0.0, sweep)]
    if center is not None and text_in and on_line and g.tad == 0 and brk is not None:
        Ex = g.support(rot, perp(unit(sub(center, c)))) * 2.0
        da = (Ex / 2.0 + g.gap) / max(R, 1e-12)
        segs = _breaks(g, segs, brk - da, brk + da)
    return segs, arrows_in, text_in, (p_start, p_end, t_start, t_end)


def gen_angular_common(g, c, a0, sweep, R):
    out = g.out
    V = g.V
    segs, arrows_in, text_in, (p0, p1, t0, t1) = _arc_text(g, c, R, a0, sweep)
    s1, s2 = int(V["DIMSD1"]), int(V["DIMSD2"])
    suppress = int(V["DIMSOXD"]) and not arrows_in
    for i, (tip, tdir) in enumerate(((p0, t0), (p1, t1))):
        if (s1 if i == 0 else s2):
            continue
        nm = g.name1 if i == 0 else g.name2
        direction = tdir if arrows_in else mul(tdir, -1.0)
        arr = g.arrow_pair(nm, tip, direction)
        if not suppress:
            out.add_arrow(arr)
    if arrows_in or int(V["DIMTOFL"]):
        for s_lo, s_hi in segs:
            if s1 and s_hi <= sweep / 2.0 + 1e-12 and s_lo < sweep / 2.0:
                s_lo = max(s_lo, sweep / 2.0)
            if s2 and s_lo >= sweep / 2.0 - 1e-12 and s_hi > sweep / 2.0:
                s_hi = min(s_hi, sweep / 2.0)
            if s_hi > s_lo:
                out.arc(c, R, a0 + s_lo, s_hi - s_lo, "dim")
    elif not suppress:
        K = 2 * g.asz
        if not s1:
            out.seg(p0, sub(p0, mul(t0, K)), "dim")
        if not s2:
            out.seg(p1, sub(p1, mul(t1, K)), "dim")
    out.notes.update({"arrows_in": arrows_in, "text_in": text_in})


def _ext_for_ray(g, c, ang, R, near_pts, role):
    r = (math.cos(ang), math.sin(ang))
    ts = sorted(dot(sub(p, c), r) for p in near_pts)
    lo, hi = ts[0], ts[-1]
    if R > hi:
        s = max(hi, 0.0) + g.exo
        e = R + g.exe
        if e > s:
            g.out.seg(add(c, mul(r, s)), add(c, mul(r, e)), role)
    elif R < lo:
        s = lo - g.exo
        e = R - g.exe
        if s > e:
            g.out.seg(add(c, mul(r, s)), add(c, mul(r, e)), role)


def gen_angular(g):
    d = g.dim
    s = sectors.two_lines(d)
    if s is None:
        return
    c = s["vertex"]
    R = dist(c, xy(d.def_point))
    if R < 1e-9:
        return
    a0, sweep = s["a0"], s["sweep"]
    ends = (a0, a0 + sweep)
    rays = (s["ray0"], s["ray1"])
    for k in range(2):
        line_idx, _sg = rays[k]
        if k == 0 and not int(g.V["DIMSE1"]):
            _ext_for_ray(g, c, ends[k], R, s["pts"][line_idx], "ext1")
        elif k == 1 and not int(g.V["DIMSE2"]):
            _ext_for_ray(g, c, ends[k], R, s["pts"][line_idx], "ext2")
    gen_angular_common(g, c, a0, sweep, R)


def gen_angular3(g):
    d = g.dim
    s = sectors.three_points(d)
    c = s["vertex"]
    R = dist(c, xy(d.def_point))
    if R < 1e-9:
        return
    a0, sweep = s["a0"], s["sweep"]
    p13, p14 = xy(d.p13), xy(d.p14)
    ends = (a0, a0 + sweep)
    for k in range(2):
        a = ends[k]
        role = "ext1" if k == 0 else "ext2"
        if (k == 0 and int(g.V["DIMSE1"])) or (k == 1 and int(g.V["DIMSE2"])):
            continue
        pts = [p13] if abs(V_.ccw(V_.ang_of(sub(p13, c)), a)) < 1e-6 or abs(V_.ccw(a, V_.ang_of(sub(p13, c)))) < 1e-6 else [p14]
        _ext_for_ray(g, c, a, R, pts, role)
    gen_angular_common(g, c, a0, sweep, R)


def gen_arc(g):
    d = g.dim
    s = sectors.arc_points(d)
    c = s["vertex"]
    R = dist(c, xy(d.def_point))
    r = s["r"]
    if R < 1e-9:
        return
    a0, sweep = s["a0"], s["sweep"]
    ends = (a0, a0 + sweep)
    for k in range(2):
        if (k == 0 and int(g.V["DIMSE1"])) or (k == 1 and int(g.V["DIMSE2"])):
            continue
        _ext_for_ray(g, c, ends[k], R, [V_.polar(c, r, ends[k])], "ext1" if k == 0 else "ext2")
    gen_angular_common(g, c, a0, sweep, R)


def gen_ordinate(g):
    d = g.dim
    F, E, O = xy(d.p13), xy(d.p14), xy(d.def_point)
    kind = g.marks.get("ordinate", "x")
    out = g.out
    ax = 1 if kind == "x" else 0
    along = (0.0, 1.0) if ax == 1 else (1.0, 0.0)
    across = (1.0, 0.0) if ax == 1 else (0.0, 1.0)
    dv = dot(sub(E, F), along)
    sgn = 1.0 if dv >= 0 else -1.0
    start = add(F, mul(along, sgn * g.exo))
    shift = dot(sub(E, F), across)
    reach = abs(dv) - g.exo
    if reach <= 1e-12:
        out.seg(F, E, "dim")
    elif abs(shift) < 1e-9:
        out.seg(start, E, "dim")
    elif abs(shift) >= reach:
        out.seg(start, E, "dim")
    else:
        p_a = add(F, mul(along, sgn * (abs(dv) - abs(shift))))
        out.seg(start, p_a, "dim")
        out.seg(p_a, E, "dim")
    blk = g.block()
    if not blk.empty:
        lead = mul(along, sgn)
        if g.marks.get("text_angle") is not None:
            rot = float(g.marks["text_angle"])
        elif int(g.V["DIMTIH"]):
            rot = 0.0
        else:
            rot = V_.readable(V_.ang_of(along))
        sup = g.support(rot, lead)
        center = add(E, mul(lead, sup + g.gap))
        if d.text_moved and d.text_point:
            center = xy(d.text_point)
        g.place(center, rot)


def generate(dim, V, S, measure, text_height=None) -> Out:
    g = Gen(dim, V, S, measure, text_height)
    t = dim.dim_type
    fn = {"linear": gen_linear, "aligned": gen_linear, "radius": gen_radius, "diameter": gen_diameter, "jogged": gen_jogged, "angular": gen_angular, "angular3": gen_angular3, "arc": gen_arc, "ordinate": gen_ordinate, "center": gen_center}.get(t)
    if fn is not None:
        try:
            fn(g)
        except (ZeroDivisionError, ValueError):
            g.out.notes["error"] = True
    apply_breaks(g)
    return g.out


def apply_breaks(g):
    brks = g.marks.get("breaks") or []
    if not brks:
        return
    out = g.out
    segs = out.segs
    for b in brks:
        p = xy(b["p"])
        size = float(b.get("size", g.asz if g.asz > 0 else g.ht * 0.5))
        which = b.get("on")
        nxt = []
        for p0, p1, role in segs:
            if role not in ("dim", "ext1", "ext2") or (which and role != which):
                nxt.append((p0, p1, role))
                continue
            dv = sub(p1, p0)
            ln = V_.length(dv)
            if ln < 1e-12:
                nxt.append((p0, p1, role))
                continue
            uu = mul(dv, 1.0 / ln)
            off = abs(cross(sub(p, p0), uu))
            t = dot(sub(p, p0), uu)
            tol = max(g.ht * 0.5, size)
            if off > tol or t < -size or t > ln + size:
                nxt.append((p0, p1, role))
                continue
            lo, hi = t - size / 2.0, t + size / 2.0
            if lo > 1e-12:
                nxt.append((p0, add(p0, mul(uu, min(lo, ln))), role))
            if hi < ln - 1e-12:
                nxt.append((add(p0, mul(uu, max(hi, 0.0))), p1, role))
        segs = nxt
    out.segs = segs
