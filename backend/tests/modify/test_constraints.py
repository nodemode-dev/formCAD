import math

import pytest

from tests.modify.draw import circle, ent, ends, geometry_rows, line
from tests.support import geometry
from tests.support.engine import Refused

TOL = 1e-9


def con(doc, kind, *refs, **extra):
    return doc.post("/constraints", {"kind": kind, "refs": [list(r) if isinstance(r, tuple) else r for r in refs], **extra})


def vec(e):
    s, t = ends(e)
    return t[0] - s[0], t[1] - s[1]


def length(e):
    return math.hypot(*vec(e))


def cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def dot(u, v):
    return u[0] * v[0] + u[1] * v[1]


def l_corner(doc):
    a = line(doc, "0,0", "10,1")
    b = line(doc, "10.5,0.5", "11,8")
    con(doc, "coincident", (a, "end"), (b, "start"))
    con(doc, "horizontal", a)
    con(doc, "perpendicular", a, b)
    anchor = ends(ent(doc, a))[0]
    con(doc, "fix", (a, "start"))
    con(doc, "distance", (a, "start"), (a, "end"), value=12)
    return a, b, anchor


def assert_l_corner_holds(doc, a, b, anchor, size):
    ea, eb = ent(doc, a), ent(doc, b)
    assert geometry.same_point(ends(ea)[1], ends(eb)[0], TOL)
    assert abs(vec(ea)[1]) <= TOL
    assert abs(dot(vec(ea), vec(eb))) <= TOL * length(ea) * length(eb)
    assert geometry.same_point(ends(ea)[0], anchor, TOL)
    assert geometry.close(length(ea), size, TOL)


def test_a_solved_sketch_meets_coincident_horizontal_perpendicular_fix_and_distance(doc):
    a, b, anchor = l_corner(doc)
    assert_l_corner_holds(doc, a, b, anchor, 12.0)


def test_changing_a_driving_dimension_moves_the_geometry_to_the_new_exact_size(doc):
    a, b, anchor = l_corner(doc)
    doc.put("/parameters/d1", {"expr": "25"})
    assert_l_corner_holds(doc, a, b, anchor, 25.0)


def test_a_conflicting_constraint_is_refused_with_the_conflict_named_and_the_drawing_unchanged(doc):
    a, b, anchor = l_corner(doc)
    before = geometry_rows(doc)
    count = len(doc.get("/constraints")["constraints"])
    with pytest.raises(Refused) as err:
        con(doc, "vertical", a)
    assert err.value.status == 409
    assert "horizontal" in err.value.body and "vertical" in err.value.body
    assert geometry_rows(doc) == before
    assert len(doc.get("/constraints")["constraints"]) == count


def test_a_second_dimension_that_over_defines_a_length_is_refused(doc):
    a, b, anchor = l_corner(doc)
    before = geometry_rows(doc)
    with pytest.raises(Refused) as err:
        con(doc, "distance", (a, "start"), (a, "end"), value=20)
    assert err.value.status == 409 and "d1" in err.value.body
    assert geometry_rows(doc) == before


def test_parallel_and_equal_make_two_lines_parallel_and_the_same_length(doc):
    a = line(doc, "0,0", "10,0")
    b = line(doc, "0,5", "7,9")
    con(doc, "parallel", a, b)
    con(doc, "equal", a, b)
    ea, eb = ent(doc, a), ent(doc, b)
    assert abs(cross(vec(ea), vec(eb))) <= 1e-8 * length(ea) * length(eb)
    assert geometry.close(length(ea), length(eb), TOL)



def test_tangent_puts_a_line_at_one_radius_from_the_circle_centre(doc):
    c = circle(doc, "0,0", 3)
    a = line(doc, "-10,4", "10,5")
    con(doc, "tangent", a, c)
    ec, ea = ent(doc, c), ent(doc, a)
    s, _ = ends(ea)
    u = vec(ea)
    gap = abs(cross(u, (ec["center"][0] - s[0], ec["center"][1] - s[1]))) / length(ea)
    assert geometry.close(gap, ec["radius"], 1e-8)


def test_a_radius_dimension_sets_the_circle_radius(doc):
    c = circle(doc, "4,4", 3)
    con(doc, "radius", c, value=7.25)
    assert geometry.close(ent(doc, c)["radius"], 7.25, TOL)


def test_a_dimension_driven_by_a_parameter_follows_the_parameter(doc):
    a = line(doc, "0,0", "10,0")
    con(doc, "fix", (a, "start"))
    con(doc, "horizontal", a)
    doc.post("/parameters", {"name": "w", "expr": "10"})
    con(doc, "distance", (a, "start"), (a, "end"), expr="w*2")
    assert geometry.close(length(ent(doc, a)), 20.0, TOL)
    doc.put("/parameters/w", {"expr": "15"})
    assert geometry.close(length(ent(doc, a)), 30.0, TOL)
    assert geometry.same_point(ends(ent(doc, a))[0], (0, 0), TOL)


def test_adding_a_constraint_is_one_undo_step(doc):
    a = line(doc, "0,0", "10,3")
    before = geometry_rows(doc)
    con(doc, "horizontal", a)
    assert abs(vec(ent(doc, a))[1]) <= TOL
    doc.undo()
    assert geometry_rows(doc) == before
    assert doc.get("/constraints")["constraints"] == []
