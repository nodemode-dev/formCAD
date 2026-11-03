import math

import numpy as np

EPS = 1e-9


def rot(x: float, y: float, deg: float):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


def seg_seg(a, b, c, d) -> float:
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    ux, uy = bx - ax, by - ay
    vx, vy = dx - cx, dy - cy
    wx, wy = ax - cx, ay - cy
    den = ux * vy - uy * vx
    if abs(den) > EPS:
        s = (vx * wy - vy * wx) / den
        t = (ux * wy - uy * wx) / den
        if 0.0 <= s <= 1.0 and 0.0 <= t <= 1.0:
            return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


def pt_seg(p, a, b) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < EPS:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def pt_in_poly(p, poly) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def poly_edges(poly):
    n = len(poly)
    return [(poly[i], poly[(i + 1) % n]) for i in range(n)]


def poly_poly(p, q) -> float:
    if pt_in_poly(p[0], q) or pt_in_poly(q[0], p):
        return 0.0
    best = 1e18
    for a, b in poly_edges(p):
        for c, d in poly_edges(q):
            v = seg_seg(a, b, c, d)
            if v < best:
                best = v
                if best <= 0.0:
                    return 0.0
    return best


def seg_poly(a, b, poly) -> float:
    if pt_in_poly(a, poly) or pt_in_poly(b, poly):
        return 0.0
    best = 1e18
    for c, d in poly_edges(poly):
        v = seg_seg(a, b, c, d)
        if v < best:
            best = v
    return best


def area(poly) -> float:
    s = 0.0
    for (x0, y0), (x1, y1) in poly_edges(poly):
        s += x0 * y1 - x1 * y0
    return s / 2.0


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def rect_poly(cx, cy, w, h, deg=0.0):
    out = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        x, y = rot(dx, dy, deg)
        out.append((cx + x, cy + y))
    return out


def circle_poly(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def self_intersects(poly) -> bool:
    e = poly_edges(poly)
    n = len(e)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if seg_seg(e[i][0], e[i][1], e[j][0], e[j][1]) <= 0.0:
                a, b = e[i]
                c, d = e[j]
                if not (a == c or a == d or b == c or b == d):
                    return True
    return False


def seg_dist_field(xs, ys, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < EPS:
        return np.hypot(xs - ax, ys - ay)
    t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / l2, 0.0, 1.0)
    return np.hypot(xs - ax - t * dx, ys - ay - t * dy)


def poly_inside_field(xs, ys, poly):
    inside = np.zeros(xs.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if yi != yj:
            cond = ((yi > ys) != (yj > ys)) & (xs < (xj - xi) * (ys - yi) / (yj - yi) + xi)
            inside ^= cond
        j = i
    return inside


def poly_dist_field(xs, ys, poly):
    d = None
    for a, b in poly_edges(poly):
        f = seg_dist_field(xs, ys, a, b)
        d = f if d is None else np.minimum(d, f)
    inside = poly_inside_field(xs, ys, poly)
    return np.where(inside, 0.0, d)
