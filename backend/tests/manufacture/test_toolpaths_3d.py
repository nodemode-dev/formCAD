import math

import pytest

from tests.manufacture.helpers import Mill, box_triangles, dist_to_polygon, inside, open_mesh, prism_triangles, rapids_into_uncut_stock, rect, sample_points

SLOPE = math.radians(20.0)
LENGTH = 60.0
BALL = 3.0


def slope_part(docs, tmp_path):
    h = LENGTH * math.tan(SLOPE)
    profile = [(0.0, -10.0), (LENGTH, -10.0), (LENGTH, h), (0.0, 0.0)]
    doc = open_mesh(docs, tmp_path, prism_triangles(profile, 0.0, 40.0), "ramp")
    m = Mill(doc, stock={"kind": "from_model", "offsets": {"zmax": 1.0}})
    m.tool(2, "ball", 2 * BALL)
    return m


def test_parallel_finishing_over_a_known_slope_rests_the_ball_on_the_plane_within_tolerance(docs, tmp_path):
    m = slope_part(docs, tmp_path)
    m.op("parallel", 2, None, {"stepover": 2.0, "tolerance": 0.01})
    program, _ = m.post()
    lift = BALL * (1.0 / math.cos(SLOPE) - 1.0)
    pts = [p for p in sample_points(program.cutting(), seg=1.0) if 6.0 <= p[0] <= 50.0 and 6.0 <= p[1] <= 34.0]
    assert len(pts) > 200
    worst = max(abs(p[2] - (p[0] * math.tan(SLOPE) + lift)) for p in pts)
    assert worst <= 0.02


def test_parallel_finishing_with_stock_to_leave_rides_that_far_above_the_slope(docs, tmp_path):
    m = slope_part(docs, tmp_path)
    m.op("parallel", 2, None, {"stepover": 3.0, "tolerance": 0.01, "stock_to_leave": 0.4})
    program, _ = m.post()
    lift = (BALL + 0.4) / math.cos(SLOPE) - BALL
    pts = [p for p in sample_points(program.cutting(), seg=1.0) if 6.0 <= p[0] <= 50.0 and 6.0 <= p[1] <= 34.0]
    assert len(pts) > 100
    assert max(abs(p[2] - (p[0] * math.tan(SLOPE) + lift)) for p in pts) <= 0.02


def test_parallel_finishing_over_a_flat_top_stays_on_the_flat_and_never_below_it(docs, tmp_path):
    doc = open_mesh(docs, tmp_path, box_triangles((0, 0, -15), (50, 30, 0)), "plate")
    m = Mill(doc, stock={"kind": "from_model", "offsets": {"zmax": 1.0}})
    m.tool(2, "ball", 2 * BALL)
    m.op("parallel", 2, None, {"stepover": 2.5, "tolerance": 0.01, "angle": 90.0})
    program, _ = m.post()
    pts = [p for p in sample_points(program.cutting(), seg=1.0) if 4.0 <= p[0] <= 46.0 and 4.0 <= p[1] <= 26.0]
    assert len(pts) > 100
    assert max(abs(p[2]) for p in pts) <= 0.01
    assert program.lowest() >= -15.0 - 0.01


PART = rect(20.0, 20.0, 80.0, 60.0)
FLAT = 3.0


@pytest.fixture()
def boss(docs, tmp_path):
    doc = open_mesh(docs, tmp_path, box_triangles((20, 20, -20), (80, 60, 0)), "boss")
    m = Mill(doc, stock={"kind": "from_model", "offsets": {"xmin": 8, "xmax": 8, "ymin": 8, "ymax": 8, "zmax": 3}})
    m.tool(1, "flat", 2 * FLAT)
    return m


def clearance_of_flat_tool(p):
    d = 0.0 if inside(p, PART) else dist_to_polygon(p, PART)
    side, up = d - FLAT, p[2]
    if side <= 0.0:
        return up
    if up <= 0.0:
        return side
    return math.hypot(side, up)


def gouges(points, stock, tol):
    return [p for p in points if clearance_of_flat_tool(p) < stock - tol]


@pytest.mark.parametrize("stock", [0.5, 1.5])
@pytest.mark.xfail(strict=True, reason="DEFECT: 3D adaptive roughing of a closed box enters a lower level with a helix or plunge at about (40, 40), inside the box footprint 20..80 by 20..60, cutting up to 15 mm into the part; roughing must leave the stated stock on the model everywhere (op description: keeps the tool out of the model)")
def test_3d_roughing_leaves_at_least_the_stated_stock_on_every_side_and_the_top_of_a_box(boss, stock):
    boss.op("adaptive3d", 1, None, {"stepdown": 5.0, "stock_to_leave": stock, "optimal_load": 2.0})
    program, _ = boss.post()
    pts = sample_points(program.cutting(), seg=0.5)
    assert len(pts) > 200
    assert gouges(pts, stock, 0.05) == []
    near = [dist_to_polygon(p, PART) - FLAT for p in pts if p[2] < -1.0 and not inside(p, PART)]
    assert min(near) == pytest.approx(stock, abs=0.1)


def test_3d_roughing_never_cuts_below_the_lowest_point_of_the_part_and_never_rapids_into_stock(boss):
    boss.op("adaptive3d", 1, None, {"stepdown": 5.0, "stock_to_leave": 0.5, "optimal_load": 2.0})
    program, _ = boss.post()
    assert program.lowest() >= -20.0 - 0.01
    assert rapids_into_uncut_stock(program, 3.0) == []


@pytest.mark.parametrize("stock", [0.0, 0.6])
@pytest.mark.xfail(strict=True, reason="DEFECT: waterline finishing of a closed box mesh also runs loops and links inside the solid (tool centre up to 3.6 mm inside the walls at z -12), gouging the part; a finishing pass must keep the tool one radius plus the stock outside the model")
def test_waterline_finishing_of_a_box_keeps_the_tool_one_radius_plus_stock_outside_its_walls(boss, stock):
    boss.op("waterline", 1, None, {"stepdown": 4.0, "stock_to_leave": stock, "tolerance": 0.01})
    program, _ = boss.post()
    walls = [p for p in sample_points(program.cutting(), seg=0.5) if p[2] < -0.5]
    assert len(walls) > 100
    assert [p for p in walls if inside(p, PART) or dist_to_polygon(p, PART) < FLAT + stock - 0.02] == []
