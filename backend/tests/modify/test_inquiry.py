import math

import pytest

from tests.modify.draw import circle, newest, pline, tag
from tests.support import geometry


def area_of(doc, handle):
    doc.type("MEASUREGEOM", "AR", "O", tag(handle))
    return float(doc.var("AREA")), float(doc.var("PERIMETER"))


def test_dist_reports_the_distance_and_the_deltas_between_two_points(doc):
    answer = doc.type("DIST", "1,2", "4,6")
    text = " ".join(answer["output"])
    assert "Distance = 5.0000" in text
    assert "Delta X = 3.0000" in text and "Delta Y = 4.0000" in text


def test_measured_distance_is_kept_in_the_distance_variable(doc):
    doc.type("MEASUREGEOM", "D", "-2,1", "10,6")
    assert geometry.close(float(doc.var("DISTANCE")), 13.0)


def test_area_by_points_gives_the_shoelace_area_and_the_closed_perimeter(doc):
    pts = [(0, 0), (7, 0), (9, 4), (3, 6), (-1, 3)]
    answer = doc.type("MEASUREGEOM", "AR", *("%g,%g" % p for p in pts), "")
    assert geometry.close(float(doc.var("AREA")), geometry.area(pts))
    assert geometry.close(float(doc.var("PERIMETER")), geometry.path_length(pts, closed=True))
    assert "Area = %.4f" % geometry.area(pts) in " ".join(answer["output"])


def test_area_of_a_polyline_with_an_arc_segment_includes_the_exact_circular_segment(doc):
    doc.type("PLINE", "20,0", "30,0", "A", "30,10", "L", "20,10", "C")
    area, perimeter = area_of(doc, newest(doc))
    assert geometry.close(area, 100 + math.pi * 25 / 2)
    assert geometry.close(perimeter, 30 + math.pi * 5)


def test_area_of_a_region_with_an_island_subtracts_the_island_and_counts_both_boundaries(doc):
    outer = pline(doc, "0,0", "10,0", "10,10", "0,10")
    inner = pline(doc, "6,6", "8,6", "8,8", "6,8")
    doc.type("REGION", "ALL", "")
    regions = sorted(e["handle"] for e in doc.entities("region"))
    doc.type("SUBTRACT", tag(regions[0]), "", tag(regions[1]), "")
    region = doc.only("region")
    area, perimeter = area_of(doc, region["handle"])
    assert geometry.close(area, 100 - 4) and geometry.close(perimeter, 40 + 8)
    assert outer not in doc.handles() and inner not in doc.handles()


@pytest.mark.xfail(strict=True, reason="DEFECT: the area of a region bounded by arcs is measured on a 64-chord-per-arc polygon (12.5613 for a radius 2 circle) instead of the exact pi r squared (12.5664) that the same command gives for a circle or a bulged polyline; source: mathematics")
def test_area_of_a_region_made_from_a_circle_is_pi_r_squared(doc):
    circle(doc, "5,5", 2)
    doc.type("REGION", "ALL", "")
    area, perimeter = area_of(doc, doc.only("region")["handle"])
    assert geometry.close(area, math.pi * 4)
    assert geometry.close(perimeter, math.pi * 4)


def test_list_of_a_circle_shows_its_circumference_and_area(doc):
    c = circle(doc, "0,0", 5)
    answer = doc.type("LIST", tag(c), "")
    text = " ".join(answer["output"])
    assert "circumference %.4f" % (10 * math.pi) in text
    assert "area %.4f" % (25 * math.pi) in text


def test_shape_analysis_gives_the_centroid_area_and_perimeter_of_a_concave_polygon(doc):
    pts = [(0, 0), (20, 0), (20, 20), (10, 20), (10, 10), (0, 10)]
    p = pline(doc, *("%g,%g" % q for q in pts))
    shapes = doc.command("analyzeshapes")["result"]["shapes"]
    shape = next(s for s in shapes if s["handle"] == p)
    cx, cy = geometry.centroid(pts)
    assert geometry.same_point(shape["centroid"], (cx, cy), 1e-6)
    assert geometry.close(shape["area"], geometry.area(pts)) and geometry.close(shape["perimeter"], 80.0)
