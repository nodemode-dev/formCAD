import pytest

from tests.modify.draw import circle, corners, ent, ends, line, newest, pick, pline
from tests.support import geometry

L_SHAPE = ("0,0", "20,0", "20,20", "10,20", "10,10", "0,10")


def offset(doc, distance, handle, at, side):
    doc.type("OFFSET", str(distance))
    pick(doc, handle, *at)
    doc.type(side, "")


def test_offset_of_a_line_is_parallel_at_the_given_distance_on_the_picked_side(doc):
    a = line(doc, "0,0", "30,40")
    offset(doc, 5, a, (15, 20), "0,10")
    made = [e for e in doc.entities("line") if e["handle"] != a]
    assert len(made) == 1
    s, t = ends(made[0])
    assert geometry.same_point(s, (-4, 3)) and geometry.same_point(t, (26, 43))


def test_offset_of_a_circle_outwards_adds_the_distance_to_the_radius(doc):
    c = circle(doc, "50,50", 5)
    offset(doc, 3, c, (50, 55), "50,70")
    made = [e for e in doc.entities("circle") if e["handle"] != c]
    assert len(made) == 1
    assert geometry.close(made[0]["radius"], 8.0) and geometry.same_point(made[0]["center"], (50, 50))


def test_offset_of_a_circle_inwards_past_its_centre_is_refused(doc):
    c = circle(doc, "0,0", 5)
    offset(doc, 6, c, (0, 5), "1,0")
    assert len(doc.entities("circle")) == 1


@pytest.mark.parametrize("d", [1.0, 2.5])
def test_offset_of_a_closed_rectangle_grows_its_area_and_perimeter_by_the_closed_form_amount(doc, d):
    r = pline(doc, "0,0", "12,0", "12,7", "0,7")
    offset(doc, d, r, (6, 0), "6,-20")
    made = ent(doc, newest(doc))
    pts = corners(made)
    assert made["closed"]
    assert geometry.close(geometry.area(pts), 84 + 38 * d + 4 * d * d)
    assert geometry.close(geometry.path_length(pts, closed=True), 38 + 8 * d)


def test_offset_of_a_concave_l_shape_outwards_mitres_five_convex_corners_and_one_reflex(doc):
    p = pline(doc, *L_SHAPE)
    offset(doc, 1, p, (5, 0), "5,-5")
    pts = corners(ent(doc, newest(doc)))
    assert geometry.close(geometry.area(pts), 300 + 80 * 1 + (5 - 1) * 1)
    assert sorted(pts) == sorted([(-1, -1), (21, -1), (21, 21), (9, 21), (9, 11), (-1, 11)])


def test_offset_of_a_concave_l_shape_inwards_shrinks_by_the_closed_form_amount(doc):
    p = pline(doc, *L_SHAPE)
    offset(doc, 4, p, (5, 0), "5,5")
    pts = corners(ent(doc, newest(doc)))
    assert geometry.close(geometry.area(pts), 300 - 80 * 4 + (5 - 1) * 16)


def test_offset_inwards_beyond_the_collapse_of_the_shape_is_refused_and_adds_nothing(doc):
    p = pline(doc, *L_SHAPE)
    doc.type("OFFSET", "6")
    pick(doc, p, 5, 0)
    answer = doc.type("15,5")
    assert any("Cannot offset" in line for line in answer["output"])
    doc.type("")
    assert [e["handle"] for e in doc.entities()] == [p]
