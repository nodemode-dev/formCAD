import math

from tests.drawing import _shapes
from tests.support import geometry

PLATE = 100.0 * 60.0
HOLE = math.pi * 10.0**2


def plate_with_hole(doc):
    doc.type("RECTANG", "0,0", "100,60")
    doc.type("CIRCLE", "50,30", "10")


def test_hatch_picked_between_a_plate_and_its_hole_covers_the_plate_minus_the_hole(doc):
    plate_with_hole(doc)
    doc.type("HATCH", "50,5", "")
    hatch = doc.only("hatch")
    loops = hatch["loops"]
    assert len(loops) == 2
    areas = sorted(_shapes.loop_area(lp["vertices"]) for lp in loops)
    assert geometry.close(areas[0], HOLE) and geometry.close(areas[1], PLATE)
    measured = _shapes.area_of(doc, hatch["handle"])
    assert abs(measured - (PLATE - HOLE)) <= 1e-4 * (PLATE - HOLE)


def test_region_from_closed_objects_keeps_each_outline_area(doc):
    plate_with_hole(doc)
    doc.type("REGION", "ALL", "")
    regions = doc.entities("region")
    assert len(regions) == 2
    areas = sorted(_shapes.loop_area(r["loops"][0]["vertices"]) for r in regions)
    assert geometry.close(areas[0], HOLE) and geometry.close(areas[1], PLATE)


def test_boundary_picked_between_plate_and_hole_traces_both_loops_as_new_polylines(doc):
    plate_with_hole(doc)
    before = {e["handle"] for e in doc.entities()}
    doc.type("BOUNDARY", "50,5", "")
    made = [e for e in doc.entities("lwpolyline") if e["handle"] not in before]
    assert len(made) == 2 and all(p["closed"] for p in made)
    areas = sorted(_shapes.loop_area(p["vertices"]) for p in made)
    assert geometry.close(areas[0], HOLE) and geometry.close(areas[1], PLATE)
    assert before <= {e["handle"] for e in doc.entities()}
