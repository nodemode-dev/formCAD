import math

import pytest

from tests.modify.draw import circle, close_rows, corners, ent, ends, geometry_rows, line, pline, tag
from tests.support import geometry


def test_move_by_two_points_shifts_every_vertex_by_the_vector(doc):
    a = line(doc, "1,2", "4,6")
    r = pline(doc, "0,0", "5,0", "5,3")
    doc.type("MOVE", "ALL", "", "2,3", "12,-4")
    s, t = ends(ent(doc, a))
    assert geometry.same_point(s, (11, -5)) and geometry.same_point(t, (14, -1))
    assert all(geometry.same_point(p, q) for p, q in zip(corners(ent(doc, r)), [(10, -7), (15, -7), (15, -4)]))


def test_copy_with_several_second_points_leaves_the_original_and_places_each_copy(doc):
    c = circle(doc, "0,0", 2)
    doc.type("COPY", tag(c), "", "0,0", "10,0", "0,10", "")
    centres = sorted(tuple(round(v, 9) for v in e["center"][:2]) for e in doc.entities("circle"))
    assert centres == [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0)]
    assert all(geometry.close(e["radius"], 2.0) for e in doc.entities("circle"))


def test_rotate_by_an_angle_turns_points_about_the_base(doc):
    a = line(doc, "3,1", "8,1")
    doc.type("ROTATE", tag(a), "", "1,1", "60")
    s, t = ends(ent(doc, a))
    assert geometry.same_point(s, geometry.rotate((3, 1), (1, 1), 60))
    assert geometry.same_point(t, geometry.rotate((8, 1), (1, 1), 60))


def test_rotate_with_a_reference_angle_turns_by_the_difference_of_the_two_angles(doc):
    a = line(doc, "0,0", "10,0")
    doc.type("ROTATE", tag(a), "", "0,0", "R", "30", "75")
    _, t = ends(ent(doc, a))
    assert geometry.same_point(t, (10 * math.cos(math.radians(45)), 10 * math.sin(math.radians(45))))


def test_scale_about_a_base_point_scales_distances_from_that_point(doc):
    c = circle(doc, "5,5", 2)
    doc.type("SCALE", tag(c), "", "1,1", "2.5")
    e = ent(doc, c)
    assert geometry.close(e["radius"], 5.0)
    assert geometry.same_point(e["center"], (11.0, 11.0))


def test_mirror_keeping_the_source_adds_the_reflection_across_the_line(doc):
    a = line(doc, "1,1", "4,2")
    doc.type("MIRROR", tag(a), "", "0,0", "1,1", "N")
    lines = doc.entities("line")
    assert len(lines) == 2
    copy = next(e for e in lines if e["handle"] != a)
    s, t = ends(copy)
    assert geometry.same_point(s, geometry.mirror((1, 1), (0, 0), (1, 1)))
    assert geometry.same_point(t, geometry.mirror((4, 2), (0, 0), (1, 1)))


def test_mirror_erasing_the_source_leaves_only_the_reflection(doc):
    a = line(doc, "1,1", "4,2")
    doc.type("MIRROR", tag(a), "", "0,5", "10,5", "Y")
    lines = doc.entities("line")
    assert len(lines) == 1
    s, t = ends(lines[0])
    assert geometry.same_point(s, (1, 9)) and geometry.same_point(t, (4, 8))


def test_align_with_two_point_pairs_and_scaling_maps_source_onto_destination(doc):
    a = line(doc, "0,0", "10,0")
    c = circle(doc, "5,0", 1)
    doc.type("ALIGN", "ALL", "", "0,0", "20,20", "10,0", "20,40", "", "Y")
    s, t = ends(ent(doc, a))
    assert geometry.same_point(s, (20, 20)) and geometry.same_point(t, (20, 40))
    e = ent(doc, c)
    assert geometry.same_point(e["center"], (20, 30)) and geometry.close(e["radius"], 2.0)


def test_move_by_a_vector_then_by_its_negative_restores_every_coordinate(doc):
    line(doc, "1.25,2.5", "7.75,-3")
    circle(doc, "4,4", 1.5)
    pline(doc, "0,0", "6,0", "6,2", "0,5")
    before = geometry_rows(doc)
    doc.type("MOVE", "ALL", "", "0,0", "13.7,-8.3")
    assert not close_rows(geometry_rows(doc), before)
    doc.type("MOVE", "ALL", "", "13.7,-8.3", "0,0")
    assert close_rows(geometry_rows(doc), before)


def test_rotating_twelve_times_by_thirty_degrees_returns_home(doc):
    line(doc, "2,1", "9,4")
    pline(doc, "3,3", "8,3", "8,6")
    before = geometry_rows(doc)
    for _ in range(12):
        doc.type("ROTATE", "ALL", "", "1,-2", "30")
    assert close_rows(geometry_rows(doc), before, tol=1e-9)


def test_mirroring_twice_across_the_same_line_restores_the_shape(doc):
    a = line(doc, "2,1", "9,4")
    before = ends(ent(doc, a))
    doc.type("MIRROR", tag(a), "", "0,0", "3,7", "Y")
    once = doc.entities("line")[0]
    assert not geometry.same_point(ends(once)[0], before[0])
    doc.type("MIRROR", tag(once["handle"]), "", "0,0", "3,7", "Y")
    back = doc.entities("line")[0]
    assert geometry.same_point(ends(back)[0], before[0], 1e-9) and geometry.same_point(ends(back)[1], before[1], 1e-9)
