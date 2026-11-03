import math

import numpy as np

from app.cam import limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.ops import common
from app.cam3d import paths3d
from app.cam3d.cutters import Cutter
from app.cam3d.surface import Surface


def model_surface(ctx):
    tris = ctx.triangles()
    limits.need(len(tris), "triangles", "Model")
    return Surface(tris)


def cutter_of(ctx) -> Cutter:
    try:
        return Cutter.from_tool(ctx.tool)
    except ValueError as err:
        raise CamError(str(err))


def region_rings(ctx):
    g = ctx.op.get("geometry") or {}
    if not g:
        return None
    return ctx.region().rings


def model_bounds(surf, margin: float):
    return (float(surf.bmin[0] - margin), float(surf.bmin[1] - margin), float(surf.bmax[0] + margin), float(surf.bmax[1] + margin))


def clamp_bottom(ctx, surf):
    b = ctx.h.bottom
    return float(surf.bmin[2]) if b is None else float(b)


def cancel_of(ctx):
    return ctx.check


def link_paths(surf, cu, stl, passes, bottom, max_gap, spacing):
    n = len(passes)
    samples = []
    spans = []
    for k in range(n - 1):
        a = passes[k][-1]
        b = passes[k + 1][0]
        d = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        if d > max_gap:
            spans.append(None)
            continue
        m = max(int(math.ceil(d / spacing)), 2)
        t = np.linspace(0.0, 1.0, m + 1)
        xy = np.stack([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], axis=1)
        spans.append((len(samples), m + 1))
        samples.append(xy)
    if not samples:
        return [None] * max(n - 1, 0)
    xy = np.concatenate(samples)
    z = paths3d.drop_points(surf, cu, stl, xy)
    out = []
    pos = 0
    for k, sp in enumerate(spans):
        if sp is None:
            out.append(None)
            continue
        cnt = sp[1]
        zz = z[pos:pos + cnt]
        pts = xy[pos:pos + cnt]
        pos += cnt
        if not np.isfinite(zz).all():
            out.append(None)
            continue
        zz = np.maximum(zz, bottom)
        out.append(np.column_stack([pts, zz]))
    return out


def emit_passes(ctx, f, passes, surf, cu, stl, bottom, link_gap, spacing, closed=None):
    h = ctx.h
    moves = common.start_moves(ctx, f)
    pen = common.Pen(ctx, moves)
    links = link_paths(surf, cu, stl, passes, bottom, link_gap, spacing)
    for k, p in enumerate(passes):
        ctx.check()
        a = p[0]
        lk = links[k - 1] if k > 0 else None
        if lk is not None and pen.pos is not None:
            for q in lk[1:]:
                pen.feed(float(q[0]), float(q[1]), float(q[2]), f["vf_cut"], "link")
        else:
            pen.over(float(a[0]), float(a[1]), max(h.retract, float(a[2]) + 1.0))
            if abs(pen.pos[2] - a[2]) > 1e-9:
                pen.feed(float(a[0]), float(a[1]), float(a[2]), f["vf_plunge"], "plunge")
        for q in p[1:]:
            pen.feed(float(q[0]), float(q[1]), float(q[2]), f["vf_cut"], "cut")
        if k % 20 == 0:
            ctx.progress((k + 1) / len(passes))
    pen.finish()
    return moves


def order_nearest(items, key_pts, start=None):
    left = list(range(len(items)))
    out = []
    cur = start
    while left:
        if cur is None:
            i = left[0]
        else:
            best, i = 1e30, left[0]
            for j in left:
                p = key_pts(items[j])
                d = (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2
                if d < best:
                    best, i = d, j
        left.remove(i)
        out.append(items[i])
        cur = key_pts(items[i], True)
    return out
