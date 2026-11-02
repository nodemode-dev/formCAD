import math

from app.dim import vec as V


def two_lines(dim):
    p13, p14, p15, p16 = (V.xy(dim.p13), V.xy(dim.p14), V.xy(dim.p15), V.xy(dim.p16))
    d1 = V.sub(p14, p13)
    d2 = V.sub(p16, p15)
    vertex = V.line_hit(p13, d1, p15, d2)
    if vertex is None:
        return None
    t1 = V.ang_of(d1)
    t2 = V.ang_of(d2)
    rays = sorted([(V.norm_pos(t1), 0, 1), (V.norm_pos(t1 + math.pi), 0, -1), (V.norm_pos(t2), 1, 1), (V.norm_pos(t2 + math.pi), 1, -1)])
    pick = V.xy(dim.marks.get("sector_pt") or dim.def_point)
    phi = V.norm_pos(V.ang_of(V.sub(pick, vertex)))
    chosen = None
    for i in range(4):
        r0 = rays[i]
        r1 = rays[(i + 1) % 4]
        span = V.ccw(r0[0], r1[0])
        if span < 1e-12:
            span = 2 * math.pi
        if V.ccw(r0[0], phi) <= span + 1e-12:
            chosen = (r0, r1, span)
            break
    if chosen is None:
        r0, r1 = rays[0], rays[1]
        chosen = (r0, r1, V.ccw(r0[0], r1[0]))
    r0, r1, span = chosen
    return {"vertex": vertex, "a0": r0[0], "sweep": span, "ray0": (r0[1], r0[2]), "ray1": (r1[1], r1[2]), "pts": ((p13, p14), (p15, p16))}


def three_points(dim):
    v = V.xy(dim.p15)
    a1 = V.ang_of(V.sub(V.xy(dim.p13), v))
    a2 = V.ang_of(V.sub(V.xy(dim.p14), v))
    ccw_flag = dim.marks.get("ccw")
    if ccw_flag is None:
        phi = V.ang_of(V.sub(V.xy(dim.def_point), v))
        ccw_flag = V.ccw(a1, phi) <= V.ccw(a1, a2) + 1e-12
    if ccw_flag:
        a0, sweep = V.norm_pos(a1), V.ccw(a1, a2)
    else:
        a0, sweep = V.norm_pos(a2), V.ccw(a2, a1)
    if sweep < 1e-12:
        sweep = 2 * math.pi
    return {"vertex": v, "a0": a0, "sweep": sweep}


def arc_points(dim):
    c = V.xy(dim.p15)
    a0 = V.ang_of(V.sub(V.xy(dim.p13), c))
    a1 = V.ang_of(V.sub(V.xy(dim.p14), c))
    sweep = V.ccw(a0, a1)
    if sweep < 1e-12:
        sweep = 2 * math.pi
    if dim.marks.get("arc_cw"):
        a0, sweep = V.norm_pos(a1), V.ccw(a1, a0)
    return {"vertex": c, "a0": V.norm_pos(a0), "sweep": sweep, "r": V.dist(V.xy(dim.p13), c)}
