import math

import pytest

from tests.support import geometry


def ends(doc):
    return [(line["start"], line["end"]) for line in doc.entities("line")]


def test_absolute_relative_and_polar_entry_chain_from_the_last_point(doc):
    doc.type("LINE", "10,20", "@30,0", "@0,40", "@50<180", "")
    got = ends(doc)
    want = [((10, 20), (40, 20)), ((40, 20), (40, 60)), ((40, 60), (-10, 60))]
    assert len(got) == 3
    for (s, e), (ws, we) in zip(got, want):
        assert geometry.same_point(s, ws) and geometry.same_point(e, we)


@pytest.mark.parametrize(
    "angle, degrees",
    [
        ("30", 30.0),
        ("45d30'", 45.5),
        ("100g", 90.0),
        ("%.15fr" % (math.pi / 3.0), 60.0),
        ("N45dE", 45.0),
        ("S30dW", 240.0),
        ("-90", 270.0),
    ],
)
def test_polar_angles_accept_degree_dms_grad_radian_and_bearing_forms(doc, angle, degrees):
    doc.type("LINE", "0,0", "@10<" + angle, "")
    end = doc.only("line")["end"]
    want = (10 * math.cos(math.radians(degrees)), 10 * math.sin(math.radians(degrees)))
    assert geometry.same_point(end, want)


@pytest.mark.parametrize(
    "radius, value",
    [("7.25", 7.25), ("1.5e1", 15.0), ("3/4", 0.75), ("1-1/2", 1.5), ("1'6\"", 18.0), ("2'", 24.0)],
)
def test_distances_accept_decimal_scientific_fraction_and_feet_inch_forms(doc, radius, value):
    doc.type("CIRCLE", "0,0", radius)
    assert geometry.close(doc.only("circle")["radius"], value)


def test_clockwise_angle_direction_setting_turns_polar_angles_clockwise(doc):
    doc.set_var("ANGDIR", 1)
    doc.type("LINE", "0,0", "@10<90", "")
    assert geometry.same_point(doc.only("line")["end"], (0.0, -10.0))


def test_grad_angle_units_read_a_bare_angle_as_grads(doc):
    doc.set_var("AUNITS", 2)
    doc.type("LINE", "0,0", "@10<50", "")
    want = (10 * math.cos(math.radians(45)), 10 * math.sin(math.radians(45)))
    assert geometry.same_point(doc.only("line")["end"], want)


def test_angle_override_then_a_bare_distance_places_the_point_along_that_angle(doc):
    doc.type("LINE", "5,5", "<30", "10", "")
    want = (5 + 10 * math.cos(math.radians(30)), 5 + 10 * math.sin(math.radians(30)))
    assert geometry.same_point(doc.only("line")["end"], want)


@pytest.mark.xfail(strict=True, reason="DEFECT: after FROM, a relative offset @5,-2 is taken from the previous point and then added to the base again (100,100 start gives 115,108); the <Offset> prompt means base plus offset, 15,8.")
def test_from_modifier_offsets_the_point_from_a_base(doc):
    doc.type("LINE", "100,100", "FROM", "10,10", "@5,-2", "")
    assert geometry.same_point(doc.only("line")["end"], (15.0, 8.0))
