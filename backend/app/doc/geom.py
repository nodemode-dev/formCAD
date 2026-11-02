import math

TAU = 2.0 * math.pi
EPS = 1e-9
PARALLEL_EPS = 1e-14
TINY_BULGE = 1e-12


def norm_angle(a: float) -> float:
    r = math.fmod(a, TAU)
    if r < 0:
        r += TAU
    if r >= TAU:
        r = 0.0
    return r


def ccw_sweep(a0: float, a1: float) -> float:
    s = math.fmod(a1 - a0, TAU)
    if s < 0:
        s += TAU
    if s < 1e-12:
        s = TAU
    return s


def on_sweep(a: float, a0: float, a1: float, tol: float = EPS) -> bool:
    sweep = ccw_sweep(a0, a1)
    d = math.fmod(a - a0, TAU)
    if d < 0:
        d += TAU
    return d <= sweep + tol or d >= TAU - tol


def pt(x: float, y: float, z: float = 0.0) -> list:
    return [float(x), float(y), float(z)]


def as_pt(p) -> list:
    if p is None:
        raise ValueError("point required")
    q = [float(v) for v in p]
    if len(q) == 2:
        q.append(0.0)
    if len(q) != 3 or not all(math.isfinite(v) for v in q):
        raise ValueError("invalid point")
    return q


def add(p, q) -> list:
    return [p[0] + q[0], p[1] + q[1], (p[2] if len(p) > 2 else 0.0) + (q[2] if len(q) > 2 else 0.0)]


def sub(p, q) -> list:
    return [p[0] - q[0], p[1] - q[1], (p[2] if len(p) > 2 else 0.0) - (q[2] if len(q) > 2 else 0.0)]


def scale(p, k: float) -> list:
    return [p[0] * k, p[1] * k, (p[2] if len(p) > 2 else 0.0) * k]


def dist(p, q) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def same_point(p, q, tol: float = EPS) -> bool:
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def angle_of(p, q) -> float:
    return math.atan2(q[1] - p[1], q[0] - p[0])


def polar(p, d: float, a: float) -> list:
    return [p[0] + d * math.cos(a), p[1] + d * math.sin(a), p[2] if len(p) > 2 else 0.0]


def midpoint(p, q) -> list:
    return [(p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0, ((p[2] if len(p) > 2 else 0.0) + (q[2] if len(q) > 2 else 0.0)) / 2.0]


def cross2(p, q) -> float:
    return p[0] * q[1] - p[1] * q[0]


def circle_from_3pts(a, b, c):
    ax, ay, bx, by, cx, cy = a[0], a[1], b[0], b[1], c[0], c[1]
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    scale_ref = max(abs(ax), abs(ay), abs(bx), abs(by), abs(cx), abs(cy), 1.0)
    if abs(d) <= PARALLEL_EPS * scale_ref * scale_ref:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    if not math.isfinite(r) or r <= EPS:
        return None
    return [ux, uy, 0.0], r


def arc_from_3pts(a, b, c):
    res = circle_from_3pts(a, b, c)
    if res is None:
        return None
    center, r = res
    orient = cross2(sub(b, a), sub(c, a))
    a0 = angle_of(center, a)
    a1 = angle_of(center, c)
    if orient >= 0:
        return center, r, norm_angle(a0), norm_angle(a1)
    return center, r, norm_angle(a1), norm_angle(a0)


def bulge_to_arc(p0, p1, bulge: float):
    chord = dist(p0, p1)
    if not math.isfinite(bulge) or abs(bulge) < TINY_BULGE or chord < EPS:
        return None
    theta = 4.0 * math.atan(bulge)
    if abs(theta) <= EPS:
        return None
    radius = chord / (2.0 * abs(math.sin(theta / 2.0)))
    mid = midpoint(p0, p1)
    off = abs(radius * math.cos(theta / 2.0))
    ang = angle_of(p0, p1)
    left = bulge > 0
    if abs(theta) > math.pi:
        left = not left
    side = ang + (math.pi / 2.0 if left else -math.pi / 2.0)
    center = [mid[0] + off * math.cos(side), mid[1] + off * math.sin(side), 0.0]
    a_start = angle_of(center, p0)
    a_end = angle_of(center, p1)
    ccw = bulge > 0
    if ccw:
        return center, radius, norm_angle(a_start), norm_angle(a_end), True
    return center, radius, norm_angle(a_end), norm_angle(a_start), False


def bulge_from_arc_points(p0, p1, center, ccw: bool) -> float:
    a0 = angle_of(center, p0)
    a1 = angle_of(center, p1)
    sweep = ccw_sweep(a0, a1) if ccw else ccw_sweep(a1, a0)
    b = math.tan(sweep / 4.0)
    return b if ccw else -b


def arc_bounds(center, r: float, a0: float, a1: float):
    pts = [polar(center, r, a0), polar(center, r, a1)]
    for k in range(4):
        q = k * math.pi / 2.0
        if on_sweep(q, a0, a1):
            pts.append(polar(center, r, q))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def union_bounds(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def bounds_of_points(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def boxes_overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def box_inside(inner, outer) -> bool:
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def finite_tree(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, (list, tuple)):
        return all(finite_tree(v) for v in value)
    if isinstance(value, dict):
        return all(finite_tree(v) for v in value.values())
    return True
