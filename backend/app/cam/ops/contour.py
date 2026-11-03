import math

import numpy as np

from app.cam import geom, limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam.registry import Field, OpType, register


def start_on_longest(ring):
    pts = [tuple(p) for p in ring]
    n = len(pts)
    best, bi = -1.0, 0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = math.dist(a, b)
        if d > best:
            best, bi = d, i
    a, b = pts[bi], pts[(bi + 1) % n]
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    return [mid] + pts[bi + 1 :] + pts[: bi + 1]


def lead_geometry(P0, t, n_dir_left: bool, radius: float):
    tx, ty = t
    nx, ny = (-ty, tx) if n_dir_left else (ty, -tx)
    cx, cy = P0[0] + nx * radius, P0[1] + ny * radius
    S = (cx - tx * radius, cy - ty * radius)
    E = (cx + tx * radius, cy + ty * radius)
    return (cx, cy), S, E


def arc_samples(c, r, a0, a1, ccw, n=8):
    out = []
    sw = a1 - a0
    if ccw:
        while sw <= 0:
            sw += 2 * math.pi
    else:
        while sw >= 0:
            sw -= 2 * math.pi
    for k in range(n + 1):
        a = a0 + sw * k / n
        out.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
    return out


def lead_ok(points, forbid_rings, keep_rings) -> bool:
    for pt in points:
        if forbid_rings is not None and geom.inside(pt, forbid_rings):
            return False
        if keep_rings is not None and not geom.inside(pt, keep_rings):
            return False
    return True


def generate(ctx):
    p = ctx.p
    t = ctx.tool
    h = ctx.h
    region = ctx.region()
    side = p["side"]
    stl = p["stock_to_leave_xy"]
    n_pass = p["radial_passes"]
    rstep = p["radial_step"] if p["radial_step"] is not None else 0.5 * t.diameter
    control = p["compensation"] == "control"
    bottom = ctx.bottom() + p["stock_to_leave_z"]
    zs = common.levels(h.top, bottom, p["stepdown"] if p["stepdown"] is not None else 0.5 * t.diameter)
    f = ctx.feed_for(0.0, 0.0)
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    sign = 1.0 if side in ("outside", "on") else -1.0
    forbid = region.offset(t.radius - 0.001).rings if side == "outside" else None
    keep = region.offset(-(t.radius - 0.001)).rings if side == "inside" else None
    if side == "inside" and not keep:
        raise CamError("The tool is too large for this region.")
    passes = []
    for k in range(n_pass):
        extra = stl + (n_pass - 1 - k) * rstep
        if side == "on":
            rings = region.rings
        elif control:
            rings = geom.offset(region.rings, sign * extra) if extra > 1e-9 else region.rings
        else:
            rings = geom.offset(region.rings, sign * (t.radius + extra))
        if not rings:
            raise CamError("The offset removed the whole contour; the tool does not fit.")
        passes.append(rings)
    limits.need(len(passes) * len(zs), "passes", "Contour passes")
    lead_r = p["lead_radius"] if p["lead_radius"] is not None else max(0.5 * t.radius, 1.0)
    if control:
        lead_r = max(lead_r, t.radius * 1.05)
    climb = p["direction"] == "climb"
    prepared = []
    for rings in passes:
        pr = []
        for ring in rings:
            is_outer = geom.is_ccw(ring)
            material_inside = is_outer if side in ("outside", "on") else not is_outer
            want_ccw = is_outer
            reverse = climb if side in ("outside", "on") else not climb
            if reverse:
                want_ccw = not want_ccw
            r2 = list(ring) if geom.is_ccw(ring) == want_ccw else geom.reverse(ring)
            r2 = start_on_longest(r2)
            travel_ccw = geom.is_ccw(r2)
            material_left = (material_inside and travel_ccw) or (not material_inside and not travel_ccw)
            pr.append((r2, material_left))
        prepared.append(pr)
    total = sum(len(pr) for pr in prepared) * len(zs)
    done = 0
    dnum = t.diameter_offset
    for li, z in enumerate(zs):
        for pr in prepared:
            for ring, material_left in pr:
                ctx.check()
                P0 = ring[0]
                nxt = next((q for q in ring[1:] if math.dist(q, P0) > 1e-6), ring[1])
                dx, dy = nxt[0] - P0[0], nxt[1] - P0[1]
                ln = math.hypot(dx, dy)
                tdir = (dx / ln, dy / ln)
                n_left = not material_left
                lead_in = None
                if p["lead_in"] != "none":
                    rr = lead_r
                    for _ in range(4):
                        C, S, E = lead_geometry(P0, tdir, n_left, rr)
                        ang_s = math.atan2(S[1] - C[1], S[0] - C[0])
                        ang_p = math.atan2(P0[1] - C[1], P0[0] - C[0])
                        smp = arc_samples(C, rr, ang_s, ang_p, n_left)
                        if p["lead_in"] == "line":
                            smp = [S, P0]
                        if lead_ok(smp, forbid, keep):
                            lead_in = (C, S, E, rr)
                            break
                        rr *= 0.6
                    if lead_in is None:
                        ctx.warn("A lead-in did not fit on a contour; it starts on the path.")
                if lead_in is None:
                    start_pt = P0
                else:
                    start_pt = lead_in[1]
                if li == 0 or pen.pos is None:
                    pen.over(start_pt[0], start_pt[1], h.retract)
                    if h.feed < h.retract - 1e-9:
                        pen.rapid(start_pt[0], start_pt[1], h.feed, k="approach")
                else:
                    pen.over(start_pt[0], start_pt[1], h.retract)
                    pen.rapid(start_pt[0], start_pt[1], zs[li - 1] + 0.5, k="approach")
                pen.feed(start_pt[0], start_pt[1], z, f["vf_plunge"], "plunge")
                if control:
                    moves.append(["comp", "right" if material_left else "left", dnum])
                if lead_in is not None:
                    C, S, E, rr = lead_in
                    if p["lead_in"] == "line":
                        pen.feed(P0[0], P0[1], z, f["vf_cut"], "lead")
                    else:
                        pen.arc("ccw" if n_left else "cw", P0[0], P0[1], z, C[0], C[1], z, f["vf_cut"], "lead")
                common.cut_polyline(pen, [P0] + list(ring[1:]) + [P0], z, f["vf_cut"], "cut", p["arc_tolerance"])
                if math.dist(pen.pos[:2], P0) > 1e-9:
                    pen.feed(P0[0], P0[1], z, f["vf_cut"], "cut")
                ov = p["lead_overlap"]
                tail, tail_t = P0, tdir
                if ov > 0:
                    walked = 0.0
                    prev = P0
                    for q in ring[1:]:
                        seg = math.dist(prev, q)
                        if seg < 1e-9:
                            continue
                        if walked + seg >= ov:
                            fr = (ov - walked) / seg
                            tail = (prev[0] + (q[0] - prev[0]) * fr, prev[1] + (q[1] - prev[1]) * fr)
                            tail_t = ((q[0] - prev[0]) / seg, (q[1] - prev[1]) / seg)
                            pen.feed(tail[0], tail[1], z, f["vf_cut"], "cut")
                            break
                        pen.feed(q[0], q[1], z, f["vf_cut"], "cut")
                        walked += seg
                        prev = q
                if p["lead_out"] != "none" and lead_in is not None:
                    rr = lead_in[3]
                    C2, S2, E2 = lead_geometry(tail, tail_t, n_left, rr)
                    ang_t = math.atan2(tail[1] - C2[1], tail[0] - C2[0])
                    ang_e = math.atan2(E2[1] - C2[1], E2[0] - C2[0])
                    pts_out = [tail, E2] if p["lead_out"] == "line" else arc_samples(C2, rr, ang_t, ang_e, n_left)
                    if lead_ok(pts_out, forbid, keep):
                        if p["lead_out"] == "line":
                            pen.feed(E2[0], E2[1], z, f["vf_cut"], "lead")
                        else:
                            pen.arc("ccw" if n_left else "cw", E2[0], E2[1], z, C2[0], C2[1], z, f["vf_cut"], "lead")
                if control:
                    moves.append(["comp", "off", 0])
                done += 1
                ctx.progress(done / max(total, 1))
    pen.finish()
    ctx.meta = {"levels": len(zs), "radial_passes": n_pass, "lead_radius": lead_r}
    return T.Toolpath(moves, ctx.meta)


register(OpType(
    kind="contour", label="Contour", group="2d", generate=generate, tool_kinds=("flat", "bull", "ball", "chamfer", "engraver"), geometry=("polygons", "rect", "entities", "section"),
    description="Follow the outline of a region on the outside or inside with a tangent arc lead-in and lead-out, in even depth steps, with optional radial passes and control compensation.",
    fields=[
        Field("side", "choice", "outside", "Tool side", choices=("outside", "inside", "on"), group="Path"),
        Field("direction", "choice", "climb", "Cut direction", choices=("climb", "conventional"), group="Path"),
        Field("stepdown", "number", None, "Maximum stepdown", 0.001, 1000.0, "mm", group="Passes", nullable=True),
        Field("stock_to_leave_xy", "number", 0.0, "Stock to leave on the wall", 0.0, 50.0, "mm", group="Passes"),
        Field("stock_to_leave_z", "number", 0.0, "Stock to leave on the floor", 0.0, 50.0, "mm", group="Passes"),
        Field("radial_passes", "int", 1, "Radial passes", 1, 20, group="Passes"),
        Field("radial_step", "number", None, "Radial step", 0.001, 100.0, "mm", group="Passes", nullable=True),
        Field("compensation", "choice", "computer", "Compensation", choices=("computer", "control"), group="Path"),
        Field("lead_in", "choice", "arc", "Lead-in", choices=("arc", "line", "none"), group="Linking"),
        Field("lead_out", "choice", "arc", "Lead-out", choices=("arc", "line", "none"), group="Linking"),
        Field("lead_radius", "number", None, "Lead radius", 0.01, 500.0, "mm", group="Linking", nullable=True),
        Field("lead_overlap", "number", 0.0, "Overlap past the start", 0.0, 50.0, "mm", group="Linking"),
        Field("arc_tolerance", "number", 0.01, "Arc fitting tolerance (0 keeps line segments)", 0.0, 1.0, "mm", group="Passes"),
    ],
))
