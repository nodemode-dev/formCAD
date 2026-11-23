import math

import numpy as np
import pytest

from tests.meshsim import helpers as h

pytestmark = pytest.mark.kernel


def full_knots(c):
    out = []
    for k, m in zip(c["knots"], c["mults"]):
        out += [float(k)] * int(m)
    return out


def evaluate(c, t):
    p = c["degree"]
    U = full_knots(c)
    P = np.array(c["poles"], dtype=float)
    W = np.array(c["weights"] or [1.0] * len(P), dtype=float)
    n = len(P) - 1
    k = p
    while k < n and t >= U[k + 1]:
        k += 1
    d = [np.append(P[j] * W[j], W[j]) for j in range(k - p, k + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            i = j + k - p
            den = U[i + p - r + 1] - U[i]
            a = 0.0 if den == 0 else (t - U[i]) / den
            d[j] = (1 - a) * d[j - 1] + a * d[j]
    return d[p][:3] / d[p][3]


def curve(doc, handle):
    return next(c for c in doc.get("/curves", per_span=64)["curves"] if c["handle"] == handle)


def collinear(points, tol=1e-9):
    a, b = np.array(points[0]), np.array(points[1])
    u = (b - a) / np.linalg.norm(b - a)
    return all(np.linalg.norm(np.cross(np.array(q) - a, u)) <= tol for q in points[2:])


def test_a_curve_interpolated_through_points_passes_through_every_point(doc):
    h.metric(doc)
    pts = [[0, 0, 0], [10, 5, 0], [20, -3, 2], [30, 0, 0], [42, 7, -4]]
    c = curve(doc, h.handle_of(doc.command("crvinterp", points=pts)))
    lo, hi = c["domain"]
    ts = np.linspace(lo, hi, 20001)
    samples = np.array([evaluate(c, t) for t in ts])
    for q in pts:
        assert np.min(np.linalg.norm(samples - np.array(q, dtype=float), axis=1)) < 1e-3
    assert np.allclose(evaluate(c, lo), pts[0], atol=1e-9) and np.allclose(evaluate(c, hi), pts[-1], atol=1e-9)


def test_a_rational_quarter_circle_lies_on_its_circle_and_has_length_pi_r_over_two(doc):
    h.metric(doc)
    r = 10.0
    c = curve(doc, h.handle_of(doc.command("crv", points=[[r, 0, 0], [r, r, 0], [0, r, 0]], degree=2, weights=[1, math.sqrt(0.5), 1])))
    samples = np.array(c["samples"])
    assert np.allclose(np.linalg.norm(samples, axis=1), r, atol=1e-9)
    assert np.sum(np.linalg.norm(np.diff(samples, axis=0), axis=1)) == pytest.approx(math.pi * r / 2, rel=1e-4)
    mid = evaluate(c, 0.5)
    assert np.allclose(mid, [r / math.sqrt(2), r / math.sqrt(2), 0], atol=1e-9)


@pytest.mark.parametrize("continuity, held", [(1, 2), (2, 3), (3, 4)])
def test_a_curve_blend_between_two_lines_keeps_the_continuity_it_claims_at_each_join(doc, continuity, held):
    h.metric(doc)
    a = h.handle_of(doc.command("crv", points=[[0, 0, 0], [10, 0, 0]], degree=1))
    b = h.handle_of(doc.command("crv", points=[[20, 10, 0], [20, 20, 0]], degree=1))
    blend = curve(doc, h.handle_of(doc.command("crvblend", first=a, first_end="end", second=b, second_end="start", continuity=continuity)))
    poles = blend["poles"]
    assert poles[0] == pytest.approx([10, 0, 0]) and poles[-1] == pytest.approx([20, 10, 0])
    assert collinear([[0, 0, 0]] + poles[:held])
    assert collinear([[20, 20, 0]] + poles[-held:][::-1])
    assert not collinear([[0, 0, 0]] + poles[:held + 1])


def test_an_extruded_circle_has_the_lateral_area_of_a_cylinder(doc):
    h.metric(doc)
    r, height = 5.0, 7.0
    circle = h.handle_of(doc.command("circle", center=[0, 0], radius=r))
    surface = h.handle_of(doc.command("srfextrude", handles=[circle], height=height))
    props = doc.get("/solids/%d/massprops" % surface)
    assert props["area"] == pytest.approx(2 * math.pi * r * height, rel=1e-9)


def test_a_ruled_loft_between_two_circles_has_the_lateral_area_of_a_frustum(doc):
    h.metric(doc)
    r1, r2, height = 5.0, 10.0, 10.0
    low = h.handle_of(doc.command("circle", center=[0, 0, 0], radius=r1))
    high = h.handle_of(doc.command("circle", center=[0, 0, height], radius=r2))
    surface = h.handle_of(doc.command("srfloft", handles=[low, high], ruled=True))
    slant = math.hypot(r2 - r1, height)
    props = doc.get("/solids/%d/massprops" % surface)
    assert props["area"] == pytest.approx(math.pi * (r1 + r2) * slant, rel=1e-6)


def test_a_planar_surface_trimmed_by_an_inner_circle_has_the_rectangle_less_the_hole(doc):
    h.metric(doc)
    w, d, r = 40.0, 30.0, 5.0
    doc.type("RECTANG", "0,0", "%g,%g" % (w, d))
    rect = doc.entities("lwpolyline")[-1]["handle"]
    hole = h.handle_of(doc.command("circle", center=[20, 15], radius=r))
    surface = h.handle_of(doc.command("srfplanar", handles=[rect, hole]))
    props = doc.get("/solids/%d/massprops" % surface)
    assert props["area"] == pytest.approx(w * d - math.pi * r * r, rel=1e-9)


def flat_patch(doc, size=40.0, rows=5):
    sections = []
    for k in range(rows):
        y = size * k / (rows - 1)
        sections.append(h.handle_of(doc.command("crvinterp", points=[[size * i / 4, y, 0] for i in range(5)])))
    return h.handle_of(doc.command("srfloft", handles=sections))


def test_moving_one_control_point_reshapes_the_surface_only_where_that_point_has_influence(doc):
    h.metric(doc)
    size = 40.0
    surface = flat_patch(doc, size)
    net = doc.get("/surfaces/%d/net" % surface)
    nu, nv = net["count"]
    i, j = 1, nv // 2
    lift = 5.0
    reply = doc.command("srfpoints", handle=surface, points=[[i, j]], delta=[0, 0, lift])
    assert not reply.get("error"), reply.get("error")
    moved = h.handle_of(reply)
    grid = [[x, y, 0.0] for x in np.linspace(0, size, 21) for y in np.linspace(0, size, 21)]
    dist = np.array(doc.post("/analysis/points", {"points": grid, "target": moved})["distances"])
    xs = np.array([p[0] for p in grid])
    assert np.abs(dist[xs >= 0.75 * size]).max() < 1e-6
    assert 0.5 < dist[xs <= 0.25 * size].max() < lift


