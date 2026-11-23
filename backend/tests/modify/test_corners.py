import math

from tests.modify.draw import ends, line, pick
from tests.support import geometry


def corner(doc):
    a = line(doc, "0,0", "10,0")
    b = line(doc, "10,0", "10,10")
    return a, b


def test_fillet_puts_a_tangent_arc_of_the_radius_between_two_lines_and_trims_them(doc):
    a, b = corner(doc)
    doc.type("FILLET", "R", "2")
    pick(doc, a, 5, 0)
    pick(doc, b, 10, 5)
    arc = doc.only("arc")
    assert geometry.close(arc["radius"], 2.0)
    assert geometry.same_point(arc["center"], (8, 2))
    tips = sorted((arc["center"][0] + 2 * math.cos(t), arc["center"][1] + 2 * math.sin(t)) for t in (arc["start_angle"], arc["end_angle"]))
    assert geometry.same_point(tips[0], (8, 0)) and geometry.same_point(tips[1], (10, 2))
    lines = {e["handle"]: ends(e) for e in doc.entities("line")}
    assert geometry.same_point(lines[a][1], (8, 0)) and geometry.same_point(lines[b][0], (10, 2))


def test_fillet_with_radius_zero_joins_two_gapped_lines_at_a_sharp_corner(doc):
    a = line(doc, "0,0", "7,0")
    b = line(doc, "10,3", "10,10")
    doc.type("FILLET", "R", "0")
    pick(doc, a, 3, 0)
    pick(doc, b, 10, 8)
    assert doc.entities("arc") == []
    got = {e["handle"]: ends(e) for e in doc.entities("line")}
    assert geometry.same_point(got[a][1], (10, 0)) and geometry.same_point(got[b][0], (10, 0))


def test_fillet_with_a_radius_too_large_for_the_lines_is_refused_and_changes_nothing(doc):
    a, b = corner(doc)
    doc.type("FILLET", "R", "20")
    pick(doc, a, 5, 0)
    answer = pick(doc, b, 10, 5)
    assert any("too large" in s.lower() for s in answer["output"])
    assert doc.entities("arc") == []
    got = {e["handle"]: ends(e) for e in doc.entities("line")}
    assert geometry.same_point(got[a][1], (10, 0)) and geometry.same_point(got[b][0], (10, 0))


def test_chamfer_by_two_distances_cuts_each_line_back_by_its_distance(doc):
    a, b = corner(doc)
    doc.type("CHAMFER", "D", "2", "3")
    pick(doc, a, 5, 0)
    pick(doc, b, 10, 5)
    got = {e["handle"]: e for e in doc.entities("line")}
    assert geometry.same_point(ends(got[a])[1], (8, 0)) and geometry.same_point(ends(got[b])[0], (10, 3))
    bevel = [e for h, e in got.items() if h not in (a, b)]
    assert len(bevel) == 1
    s, t = ends(bevel[0])
    assert geometry.close(geometry.dist(s, t), math.sqrt(13))
