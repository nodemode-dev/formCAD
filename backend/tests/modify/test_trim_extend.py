from tests.modify.draw import corners, ent, ends, line, lines_matching, pick, pline, tag
from tests.support import geometry


def test_trim_with_every_object_as_a_cutting_edge_removes_the_picked_span_between_crossings(doc):
    a = line(doc, "0,0", "20,0")
    line(doc, "5,-5", "5,5")
    line(doc, "15,-5", "15,5")
    doc.type("TRIM")
    pick(doc, a, 10, 0)
    doc.type("")
    assert lines_matching(doc, [((0, 0), (5, 0)), ((15, 0), (20, 0)), ((5, -5), (5, 5)), ((15, -5), (15, 5))])


def test_trim_against_several_chosen_edges_cuts_only_at_those_edges(doc):
    a = line(doc, "0,0", "30,0")
    e1 = line(doc, "5,-5", "5,5")
    line(doc, "10,-5", "10,5")
    e3 = line(doc, "20,-5", "20,5")
    doc.type("TRIM", "T", "%s,%s" % (tag(e1), tag(e3)), "")
    pick(doc, a, 12, 0)
    doc.type("")
    assert lines_matching(doc, [((0, 0), (5, 0)), ((20, 0), (30, 0)), ((5, -5), (5, 5)), ((10, -5), (10, 5)), ((20, -5), (20, 5))])


def test_extend_to_one_boundary_moves_the_picked_end_onto_it(doc):
    edge = line(doc, "25,-10", "25,40")
    a = line(doc, "0,10", "3,13")
    doc.type("EXTEND", tag(edge), "")
    pick(doc, a, 2.5, 12.5)
    doc.type("")
    s, t = ends(ent(doc, a))
    assert geometry.same_point(s, (0, 10)) and geometry.same_point(t, (25, 35))


def test_extend_with_several_boundaries_reaches_the_nearest_then_the_next(doc):
    near = line(doc, "5,-10", "5,20")
    far = line(doc, "25,-10", "25,20")
    a = line(doc, "0,10", "3,10")
    doc.type("EXTEND", "%s,%s" % (tag(near), tag(far)), "")
    pick(doc, a, 2.5, 10)
    assert geometry.same_point(ends(ent(doc, a))[1], (5, 10))
    pick(doc, a, 4.5, 10)
    doc.type("")
    assert geometry.same_point(ends(ent(doc, a))[1], (25, 10))


def test_break_between_two_points_removes_exactly_that_span(doc):
    a = line(doc, "0,0", "20,0")
    doc.type("BREAK")
    pick(doc, a, 5, 0)
    doc.type("F", "5,0", "8,0")
    assert lines_matching(doc, [((0, 0), (5, 0)), ((8, 0), (20, 0))])


def test_join_of_two_collinear_touching_lines_makes_one_line_over_both(doc):
    line(doc, "0,0", "7,0")
    line(doc, "7,0", "20,0")
    doc.type("JOIN", "ALL", "")
    assert lines_matching(doc, [((0, 0), (20, 0))])


def test_lengthen_by_a_delta_adds_that_length_at_the_picked_end(doc):
    a = line(doc, "0,0", "6,8")
    doc.type("LENGTHEN", "DE", "5")
    pick(doc, a, 5.4, 7.2)
    doc.type("")
    s, t = ends(ent(doc, a))
    assert geometry.same_point(s, (0, 0)) and geometry.same_point(t, (9, 12))


def test_lengthen_to_a_total_sets_the_exact_length(doc):
    a = line(doc, "0,0", "6,8")
    doc.type("LENGTHEN", "T", "25")
    pick(doc, a, 5.4, 7.2)
    doc.type("")
    s, t = ends(ent(doc, a))
    assert geometry.close(geometry.dist(s, t), 25.0) and geometry.same_point(t, (15, 20))


def test_stretch_with_a_crossing_window_moves_only_the_vertices_inside_it(doc):
    r = pline(doc, "0,0", "10,0", "10,10", "0,10")
    doc.type("STRETCH", "C", "8,-1", "12,12", "", "0,0", "5,0")
    assert sorted(corners(ent(doc, r))) == sorted([(0, 0), (15, 0), (15, 10), (0, 10)])
