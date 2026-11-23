import math

from tests.drawing import _shapes
from tests.support import geometry


def test_chained_line_with_close_makes_one_line_per_segment_ending_at_the_start(doc):
    doc.type("LINE", "0,0", "40,0", "40,30", "C")
    lines = doc.entities("line")
    assert len(lines) == 3
    assert geometry.close(sum(geometry.dist(l["start"], l["end"]) for l in lines), 120.0)
    assert geometry.same_point(lines[-1]["start"], (40, 30)) and geometry.same_point(lines[-1]["end"], (0, 0))
    for a, b in zip(lines, lines[1:]):
        assert geometry.same_point(a["end"], b["start"])


def test_line_undo_option_takes_back_the_last_segment_only(doc):
    doc.type("LINE", "0,0", "10,0", "20,5", "U", "10,10", "")
    segs = [(l["start"], l["end"]) for l in doc.entities("line")]
    assert len(segs) == 2
    assert geometry.same_point(segs[1][0], (10, 0)) and geometry.same_point(segs[1][1], (10, 10))


def test_polyline_with_a_tangent_arc_has_the_bulge_area_and_length(doc):
    doc.type("PLINE", "0,0", "10,0", "A", "10,10", "L", "0,10", "C")
    pl = doc.only("lwpolyline")
    assert pl["closed"] and len(pl["vertices"]) == 4
    want_area = 100.0 + math.pi * 25.0 / 2.0
    want_length = 30.0 + 5.0 * math.pi
    assert geometry.close(pl["vertices"][1]["bulge"], 1.0)
    assert geometry.close(_shapes.loop_area(pl["vertices"]), want_area)
    assert geometry.close(_shapes.loop_length(pl["vertices"]), want_length)
    measured = doc.command("measuregeom", mode="area", handles=[pl["handle"]])["result"]
    assert geometry.close(measured["area"], want_area) and geometry.close(measured["perimeter"], want_length)


def test_polyline_arc_by_centre_and_included_angle_lands_on_the_circle(doc):
    doc.type("PLINE", "10,0", "A", "CE", "0,0", "A", "90", "")
    pl = doc.only("lwpolyline")
    assert geometry.same_point(pl["vertices"][1]["p"], (0.0, 10.0))
    assert geometry.close(pl["vertices"][0]["bulge"], math.tan(math.pi / 8.0))
    assert geometry.close(_shapes.loop_length(pl["vertices"], closed=False), 5.0 * math.pi)


def test_rectangle_by_two_corners_has_the_four_corners(doc):
    doc.type("RECTANG", "10,20", "@100,60")
    pl = doc.only("lwpolyline")
    corners = sorted((round(v["p"][0], 9), round(v["p"][1], 9)) for v in pl["vertices"])
    assert pl["closed"] and corners == [(10, 20), (10, 80), (110, 20), (110, 80)]
    assert geometry.close(_shapes.loop_area(pl["vertices"]), 6000.0)


def test_filleted_rectangle_loses_the_corner_squares_minus_quarter_circles(doc):
    doc.type("RECTANG", "F", "5", "0,0", "100,60")
    pl = doc.only("lwpolyline")
    assert len(pl["vertices"]) == 8
    assert geometry.close(_shapes.loop_area(pl["vertices"]), 6000.0 - (4.0 - math.pi) * 25.0)
    assert geometry.close(_shapes.loop_length(pl["vertices"]), 320.0 - 40.0 + 10.0 * math.pi)


def test_chamfered_rectangle_loses_four_corner_triangles(doc):
    doc.type("RECTANG", "C", "5", "10", "0,0", "100,60")
    pl = doc.only("lwpolyline")
    assert len(pl["vertices"]) == 8
    assert geometry.close(_shapes.loop_area(pl["vertices"]), 6000.0 - 4 * 25.0)
    assert geometry.close(_shapes.loop_length(pl["vertices"]), 320.0 - 60.0 + 4 * math.sqrt(125.0))
