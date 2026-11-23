from tests.modify.draw import corners, ent, line, lines_matching, newest, pick, pline
from tests.support import geometry


def test_explode_of_a_closed_polyline_gives_one_line_per_edge_including_the_closing_edge(doc):
    pline(doc, "0,0", "10,0", "10,10", "0,10")
    answer = doc.type("EXPLODE", "ALL", "")
    assert doc.entities("lwpolyline") == []
    assert lines_matching(doc, [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0))])
    assert any("4 objects created" in s for s in answer["output"])


def test_pedit_turns_a_line_into_a_polyline_and_joins_the_touching_lines(doc):
    a = line(doc, "0,0", "10,0")
    line(doc, "10,0", "10,6")
    line(doc, "10,6", "0,6")
    doc.type("PEDIT")
    pick(doc, a, 5, 0)
    doc.type("Y", "J", "ALL", "", "")
    assert doc.entities("line") == []
    poly = doc.only("lwpolyline")
    assert corners(poly) == [(0, 0), (10, 0), (10, 6), (0, 6)]
    assert not poly["closed"]


def test_pedit_close_adds_the_closing_edge_to_an_open_polyline(doc):
    p = pline(doc, "0,0", "10,0", "10,6", "0,6", closed=False)
    doc.type("PEDIT")
    pick(doc, p, 5, 0)
    doc.type("C", "")
    poly = ent(doc, p)
    assert poly["closed"]
    doc.type("MEASUREGEOM", "AR", "O", "#%x" % p)
    assert geometry.close(float(doc.var("AREA")), 60.0) and geometry.close(float(doc.var("PERIMETER")), 32.0)


def test_pedit_width_sets_the_same_width_on_every_segment(doc):
    p = pline(doc, "0,0", "10,0", "10,6")
    doc.type("PEDIT")
    pick(doc, p, 5, 0)
    doc.type("W", "2.5", "")
    poly = ent(doc, p)
    assert all(v["sw"] == 2.5 and v["ew"] == 2.5 for v in poly["vertices"])
