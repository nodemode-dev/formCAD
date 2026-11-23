import math

from tests.support import geometry

TAU = 2.0 * math.pi


def loop_area(vertices) -> float:
    pts = [v["p"] for v in vertices]
    signed = geometry.shoelace(pts)
    n = len(vertices)
    for i, v in enumerate(vertices):
        b = v.get("bulge", 0.0) or 0.0
        if abs(b) > 1e-12:
            seg = geometry.bulge_arc(v["p"], vertices[(i + 1) % n]["p"], b)["segment_area"]
            signed += math.copysign(seg, b)
    return abs(signed)


def loop_length(vertices, closed: bool = True) -> float:
    n = len(vertices)
    total = 0.0
    for i in range(n if closed else n - 1):
        a, b = vertices[i]["p"], vertices[(i + 1) % n]["p"]
        bulge = vertices[i].get("bulge", 0.0) or 0.0
        total += geometry.bulge_arc(a, b, bulge)["length"] if abs(bulge) > 1e-12 else geometry.dist(a, b)
    return total


def same_angle(a: float, b: float, tol: float = 1e-6) -> bool:
    d = (a - b) % TAU
    return min(d, TAU - d) <= tol


def _basis_point(degree, knots, ctrl, u):
    n = len(ctrl) - 1
    if u >= knots[n + 1]:
        k = n
    else:
        k = degree
        while k < n and not (knots[k] <= u < knots[k + 1]):
            k += 1
    d = [list(ctrl[j + k - degree][:2]) for j in range(degree + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            i = j + k - degree
            den = knots[i + degree - r + 1] - knots[i]
            a = 0.0 if den == 0 else (u - knots[i]) / den
            d[j] = [(1 - a) * d[j - 1][0] + a * d[j][0], (1 - a) * d[j - 1][1] + a * d[j][1]]
    return d[degree]


def spline_distance_to(spline, target, samples: int = 4000) -> float:
    degree, knots, ctrl = spline["degree"], spline["knots"], spline["control_points"]
    lo, hi = knots[degree], knots[len(ctrl)]

    def gap(u):
        return geometry.dist(_basis_point(degree, knots, ctrl, u), target)

    step = (hi - lo) / samples
    best = min(range(samples + 1), key=lambda i: gap(lo + i * step))
    a, b = max(lo, lo + (best - 1) * step), min(hi, lo + (best + 1) * step)
    for _ in range(200):
        m1, m2 = a + (b - a) / 3.0, b - (b - a) / 3.0
        if gap(m1) < gap(m2):
            b = m2
        else:
            a = m1
    return gap((a + b) / 2.0)


def area_of(doc, handle) -> float:
    return doc.command("measuregeom", mode="area", handles=[handle])["result"]["area"]
