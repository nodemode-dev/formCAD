import math

TOL = 1e-6


def close(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def same_point(a, b, tol: float = TOL) -> bool:
    return len(a) >= 2 and len(b) >= 2 and all(abs(float(a[i]) - float(b[i])) <= tol for i in range(2)) and abs(_z(a) - _z(b)) <= tol


def _z(p) -> float:
    return float(p[2]) if len(p) > 2 else 0.0


def dist(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (_z(a) - _z(b)) ** 2)


def path_length(points, closed: bool = False) -> float:
    pts = list(points)
    if closed and pts:
        pts.append(pts[0])
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def shoelace(points) -> float:
    pts = list(points)
    total = 0.0
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        total += a[0] * b[1] - b[0] * a[1]
    return total / 2.0


def area(points) -> float:
    return abs(shoelace(points))


def bbox(points) -> tuple:
    pts = list(points)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(points) -> tuple:
    pts = list(points)
    signed = shoelace(pts)
    cx = cy = 0.0
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        cross = a[0] * b[1] - b[0] * a[1]
        cx += (a[0] + b[0]) * cross
        cy += (a[1] + b[1]) * cross
    return cx / (6.0 * signed), cy / (6.0 * signed)


def rotate(p, about, degrees: float) -> tuple:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    x, y = p[0] - about[0], p[1] - about[1]
    return about[0] + x * c - y * s, about[1] + x * s + y * c


def mirror(p, a, b) -> tuple:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    fx, fy = a[0] + t * dx, a[1] + t * dy
    return 2 * fx - p[0], 2 * fy - p[1]


def arc_length(radius: float, start_deg: float, end_deg: float) -> float:
    sweep = (end_deg - start_deg) % 360.0
    return math.radians(sweep or 360.0) * radius


def bulge_arc(a, b, bulge: float) -> dict:
    chord = dist(a, b)
    theta = 4.0 * math.atan(bulge)
    radius = chord / (2.0 * math.sin(abs(theta) / 2.0))
    return {"radius": radius, "angle": theta, "length": abs(theta) * radius, "segment_area": radius * radius * (abs(theta) - math.sin(abs(theta))) / 2.0}


def mesh_volume(vertices, triangles) -> float:
    total = 0.0
    for i, j, k in triangles:
        a, b, c = vertices[i], vertices[j], vertices[k]
        total += a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
    return abs(total) / 6.0


def mesh_area(vertices, triangles) -> float:
    total = 0.0
    for i, j, k in triangles:
        a, b, c = vertices[i], vertices[j], vertices[k]
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        total += math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) / 2.0
    return total
