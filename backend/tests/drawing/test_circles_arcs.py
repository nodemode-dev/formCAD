import math

import pytest

from tests.drawing import _shapes
from tests.support import geometry

HALF = math.pi / 2.0


@pytest.mark.parametrize(
    "inputs, center, radius",
    [
        (("4,-3", "D", "20"), (4, -3), 10.0),
        (("2P", "0,0", "10,0"), (5, 0), 5.0),
        (("3P", "0,0", "10,0", "0,10"), (5, 5), math.sqrt(50.0)),
        (("3P", "1,1", "4,5", "@-7,0"), (0.5, 4.5), math.sqrt(12.5)),
    ],
)
def test_circle_by_each_method_has_the_closed_form_centre_and_radius(doc, inputs, center, radius):
    doc.type("CIRCLE", *inputs)
    circle = doc.only("circle")
    assert geometry.same_point(circle["center"], center)
    assert geometry.close(circle["radius"], radius)


def test_circle_tangent_tangent_radius_sits_in_the_corner_of_two_lines(doc):
    doc.type("LINE", "0,0", "100,0", "")
    doc.type("LINE", "0,0", "0,100", "")
    first, second = doc.entities("line")
    doc.type("CIRCLE", "T")
    doc.pick(handle=first["handle"], point=[20.0, 0.0])
    doc.pick(handle=second["handle"], point=[0.0, 20.0])
    doc.type("7")
    circle = doc.only("circle")
    assert geometry.same_point(circle["center"], (7.0, 7.0)) and geometry.close(circle["radius"], 7.0)


@pytest.mark.parametrize(
    "inputs, start, end",
    [
        (("10,0", "0,10", "-10,0"), 0.0, math.pi),
        (("10,0", "C", "0,0", "0,10"), 0.0, HALF),
        (("10,0", "C", "0,0", "A", "90"), 0.0, HALF),
        (("10,0", "C", "0,0", "A", "-90"), -HALF, 0.0),
        (("10,0", "C", "0,0", "L", "%.15f" % (10 * math.sqrt(2.0))), 0.0, HALF),
        (("10,0", "E", "0,10", "R", "10"), 0.0, HALF),
        (("10,0", "E", "0,10", "A", "90"), 0.0, HALF),
        (("10,0", "E", "0,10", "D", "90"), 0.0, HALF),
        (("10,0", "E", "0,10", "0,0"), 0.0, HALF),
        (("C", "0,0", "10,0", "-10,0"), 0.0, math.pi),
    ],
)
def test_arc_by_each_method_is_on_the_radius_ten_circle_about_the_origin(doc, inputs, start, end):
    doc.type("ARC", *inputs)
    arc = doc.only("arc")
    assert geometry.same_point(arc["center"], (0, 0)) and geometry.close(arc["radius"], 10.0)
    assert _shapes.same_angle(arc["start_angle"], start) and _shapes.same_angle(arc["end_angle"], end)


def test_arc_continued_from_a_line_leaves_tangent_to_it(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("ARC", "", "10,10")
    arc = doc.only("arc")
    assert geometry.same_point(arc["center"], (10.0, 5.0)) and geometry.close(arc["radius"], 5.0)
    assert _shapes.same_angle(arc["start_angle"], -HALF) and _shapes.same_angle(arc["end_angle"], HALF)
