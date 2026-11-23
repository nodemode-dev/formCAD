import math

import pytest

from tests.drawing import _shapes
from tests.support import geometry


def test_ellipse_by_axis_endpoints_has_the_midpoint_centre_and_axis_ratio(doc):
    doc.type("ELLIPSE", "0,0", "10,0", "3")
    e = doc.only("ellipse")
    assert geometry.same_point(e["center"], (5, 0))
    assert geometry.close(math.hypot(e["major"][0], e["major"][1]), 5.0)
    assert geometry.close(e["ratio"], 0.6)
    measured = _shapes.area_of(doc, e["handle"])
    assert geometry.close(measured, math.pi * 5.0 * 3.0)


@pytest.mark.parametrize(
    "inputs, sides, vertex_radius",
    [
        (("6", "0,0", "I", "10"), 6, 10.0),
        (("6", "0,0", "C", "10"), 6, 10.0 / math.cos(math.pi / 6.0)),
        (("8", "0,0", "I", "5"), 8, 5.0),
    ],
)
def test_polygon_inscribed_and_circumscribed_have_the_closed_form_vertex_radius_and_area(doc, inputs, sides, vertex_radius):
    doc.type("POLYGON", *inputs)
    pl = doc.only("lwpolyline")
    verts = pl["vertices"]
    assert pl["closed"] and len(verts) == sides
    assert all(geometry.close(geometry.dist(v["p"], (0, 0)), vertex_radius) for v in verts)
    want = 0.5 * sides * vertex_radius**2 * math.sin(2 * math.pi / sides)
    assert geometry.close(_shapes.loop_area(verts), want)


def test_polygon_by_edge_has_equal_sides_of_the_edge_length(doc):
    doc.type("POLYGON", "5", "E", "0,0", "10,0")
    verts = [v["p"] for v in doc.only("lwpolyline")["vertices"]]
    assert len(verts) == 5
    assert all(geometry.close(geometry.dist(verts[i], verts[(i + 1) % 5]), 10.0) for i in range(5))
    assert any(geometry.same_point(p, (0, 0)) for p in verts) and any(geometry.same_point(p, (10, 0)) for p in verts)
    assert geometry.close(geometry.area(verts), 5 * 10.0**2 / (4.0 * math.tan(math.pi / 5.0)))


@pytest.mark.parametrize(
    "inputs, base, direction",
    [
        (("0,0", "10,10", ""), (0, 0), (1, 1)),
        (("H", "0,5", ""), (0, 5), (1, 0)),
        (("V", "7,0", ""), (7, 0), (0, 1)),
        (("A", "30", "1,1", ""), (1, 1), (math.cos(math.radians(30)), math.sin(math.radians(30)))),
    ],
)
def test_construction_line_passes_through_the_point_in_the_given_direction(doc, inputs, base, direction):
    doc.type("XLINE", *inputs)
    x = doc.only("xline")
    norm = math.hypot(*direction)
    unit = (direction[0] / norm, direction[1] / norm)
    cross = (x["base"][0] - base[0]) * unit[1] - (x["base"][1] - base[1]) * unit[0]
    assert abs(cross) < 1e-9
    assert geometry.same_point(x["direction"], unit) or geometry.same_point(x["direction"], (-unit[0], -unit[1]))


def test_ray_starts_at_its_start_point_and_heads_through_the_second(doc):
    doc.type("RAY", "2,1", "5,5", "")
    r = doc.only("ray")
    assert geometry.same_point(r["base"], (2, 1))
    assert geometry.same_point(r["direction"], (0.6, 0.8))


def test_spline_through_fit_points_passes_through_every_one(doc):
    fit = [(0, 0), (5, 5), (10, 0), (17, 3), (20, -4)]
    doc.type("SPLINE", *["%g,%g" % p for p in fit], "")
    s = doc.only("spline")
    for p in fit:
        assert _shapes.spline_distance_to(s, p) < 1e-6
