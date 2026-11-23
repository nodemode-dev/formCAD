import math

import pytest

from tests.support import geometry

APERTURE = {"aperture": 2.0}


def last_line(doc):
    return doc.entities("line")[-1]


def line_from_snap(doc, word, click, start=None):
    if start is None:
        doc.type("LINE", word)
        doc.point(*click, snap=APERTURE)
        doc.type("90,90", "")
        return last_line(doc)["start"]
    doc.type("LINE", start, word)
    doc.point(*click, snap=APERTURE)
    doc.type("")
    return last_line(doc)["end"]


@pytest.mark.parametrize(
    "word, click, want",
    [
        ("END", (29.4, 39.3), (30.0, 40.0)),
        ("MID", (15.6, 19.5), (15.0, 20.0)),
        ("NEA", (12.0, 17.0), (0.6 * (0.6 * 12 + 0.8 * 17), 0.8 * (0.6 * 12 + 0.8 * 17))),
    ],
)
def test_endpoint_midpoint_and_nearest_snaps_land_on_the_line(doc, word, click, want):
    doc.type("LINE", "0,0", "30,40", "")
    assert geometry.same_point(line_from_snap(doc, word, click), want)


def test_intersection_snap_lands_on_the_crossing_of_two_lines(doc):
    doc.type("LINE", "0,0", "10,10", "")
    doc.type("LINE", "0,10", "10,0", "")
    assert geometry.same_point(line_from_snap(doc, "INT", (5.6, 4.5)), (5.0, 5.0))


def test_centre_snap_picked_on_the_rim_lands_on_the_centre(doc):
    doc.type("CIRCLE", "3,4", "5")
    circle = doc.only("circle")
    doc.type("LINE", "CEN")
    doc.pick(handle=circle["handle"], point=[8.0, 4.1])
    doc.type("90,90", "")
    assert geometry.same_point(doc.only("line")["start"], (3.0, 4.0))


@pytest.mark.parametrize("click, want", [((3.3, 8.6), (3.0, 9.0)), ((-1.6, 4.2), (-2.0, 4.0)), ((3.1, -0.5), (3.0, -1.0))])
def test_quadrant_snap_lands_on_the_nearest_compass_point_of_the_circle(doc, click, want):
    doc.type("CIRCLE", "3,4", "5")
    assert geometry.same_point(line_from_snap(doc, "QUA", click), want)


def test_perpendicular_snap_drops_the_foot_of_the_perpendicular(doc):
    doc.type("LINE", "0,0", "20,0", "")
    assert geometry.same_point(line_from_snap(doc, "PER", (8.0, 0.3), start="5,10"), (5.0, 0.0))


def test_tangent_snap_from_an_outside_point_touches_the_circle(doc):
    doc.type("CIRCLE", "0,0", "10")
    got = line_from_snap(doc, "TAN", (8.0, 5.5), start="0,20")
    assert geometry.same_point(got, (5.0 * math.sqrt(3.0), 5.0))


def test_tangent_to_tangent_line_between_two_equal_circles_runs_across_their_tops(doc):
    doc.type("CIRCLE", "0,0", "5")
    doc.type("CIRCLE", "20,0", "5")
    doc.type("LINE", "TAN")
    doc.point(0.5, 5.2, snap=APERTURE)
    doc.type("TAN")
    doc.point(19.5, 5.2, snap=APERTURE)
    doc.type("")
    line = doc.only("line")
    assert geometry.same_point(line["start"], (0.0, 5.0)) and geometry.same_point(line["end"], (20.0, 5.0))


def test_a_snap_with_nothing_in_reach_is_refused_and_the_prompt_stays(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("LINE", "END")
    doc.point(50.0, 50.0, snap=APERTURE)
    assert doc.error()
    assert doc.state()["active"] and len(doc.entities("line")) == 1
