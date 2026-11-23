import math

import pytest

from tests.manufacture.helpers import Mill, at_depth, box_triangles, dist_to_polygon, inside, open_mesh, rapids_into_uncut_stock, rect, sample_points
from tests.support import geometry

R = 3.0
RECT = rect(20.0, 20.0, 60.0, 50.0)
FEEDS = {"rpm": 10000, "vf_cut": 800, "vf_plunge": 200}


@pytest.fixture()
def mill(docs, tmp_path):
    doc = open_mesh(docs, tmp_path, box_triangles((0, 0, -20), (100, 100, 0)), "block")
    m = Mill(doc)
    m.tool(1, "flat", 2 * R)
    return m


def contour(mill, geometry, side="outside", **params):
    base = {"side": side, "stepdown": 2.0, "lead_in": "none", "lead_out": "none"}
    base.update(params)
    return mill.op("contour", 1, geometry, base, FEEDS, {"bottom": -5.0})


def circle_geometry(mill):
    mill.doc.type("CIRCLE", "50,50", "15")
    return {"kind": "entities", "handles": [mill.doc.only("circle")["handle"]]}


@pytest.mark.parametrize("side,sign", [("outside", 1.0), ("inside", -1.0)])
def test_a_rectangle_profile_keeps_the_tool_centre_exactly_one_radius_from_the_edge_on_the_chosen_side(mill, side, sign):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, side)
    program, _ = mill.post()
    pts = sample_points(at_depth(program, -5.0))
    assert len(pts) > 20
    for p in pts:
        assert abs(dist_to_polygon(p, RECT) - R) < 1e-3
        assert inside(p, RECT) == (sign < 0)


@pytest.mark.parametrize("side,expected", [("outside", 15.0 + R), ("inside", 15.0 - R)])
def test_a_circle_profile_runs_at_the_circle_radius_plus_or_minus_the_tool_radius(mill, side, expected):
    contour(mill, circle_geometry(mill), side)
    program, _ = mill.post()
    pts = sample_points(at_depth(program, -5.0))
    assert len(pts) > 20
    for p in pts:
        assert abs(math.hypot(p[0] - 50.0, p[1] - 50.0) - expected) < 0.015


def test_stock_to_leave_on_the_wall_moves_the_profile_out_by_that_amount(mill):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, "outside", stock_to_leave_xy=0.7)
    program, _ = mill.post()
    for p in sample_points(at_depth(program, -5.0)):
        assert abs(dist_to_polygon(p, RECT) - (R + 0.7)) < 1e-3


@pytest.mark.parametrize("side,direction,clockwise", [("outside", "climb", True), ("outside", "conventional", False), ("inside", "climb", False), ("inside", "conventional", True)])
def test_climb_milling_with_a_clockwise_spindle_keeps_the_material_on_the_right_of_the_tool(mill, side, direction, clockwise):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, side, direction=direction)
    program, text = mill.post()
    assert "M3" in text and "M4" not in text
    loop = [p[:2] for p in sample_points(at_depth(program, -5.0))]
    area = geometry.shoelace(loop)
    assert abs(area) > 500.0
    assert (area < 0) == clockwise


@pytest.mark.parametrize("stepdown,levels", [(2.0, 3), (1.25, 4), (5.0, 1)])
def test_a_profile_reaches_the_final_depth_in_equal_steps_no_larger_than_the_step_down(mill, stepdown, levels):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, stepdown=stepdown)
    program, _ = mill.post()
    depths = sorted({round(m.end[2], 6) for m in program.cutting() if abs(m.start[2] - m.end[2]) < 1e-9}, reverse=True)
    assert len(depths) == levels
    steps = [0.0 - depths[0]] + [depths[i] - depths[i + 1] for i in range(len(depths) - 1)]
    assert all(s <= stepdown + 1e-6 for s in steps)
    assert abs(depths[-1] + 5.0) < 1e-6
    assert abs(program.lowest() + 5.0) < 1e-6


def test_a_profile_never_rapids_sideways_below_the_stock_or_down_into_uncut_material(mill):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, lead_in="arc", lead_out="arc", stepdown=1.0)
    program, _ = mill.post()
    assert rapids_into_uncut_stock(program, 0.0) == []
    sideways = [m for m in program.rapids()[1:] if math.dist(m.start[:2], m.end[:2]) > 1e-6]
    assert sideways and all(min(m.start[2], m.end[2]) >= 5.0 - 1e-6 for m in sideways)


def test_a_profile_cuts_at_the_set_feeds_and_spindle_speed_and_ends_with_spindle_off_and_program_end(mill):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]})
    program, text = mill.post()
    cuts = program.cutting()
    plunges = [m for m in cuts if math.dist(m.start[:2], m.end[:2]) < 1e-9 and m.end[2] < m.start[2]]
    sideways = [m for m in cuts if math.dist(m.start[:2], m.end[:2]) > 1e-9]
    assert plunges and all(m.feed == 200.0 for m in plunges)
    assert sideways and all(m.feed == 800.0 for m in sideways)
    assert all(m.spindle == 10000.0 for m in cuts)
    lines = [ln.strip() for ln in text.splitlines()]
    last_cut = max(m.line for m in cuts)
    off = [i + 1 for i, ln in enumerate(lines) if ln.split() and ln.split()[0] == "M5"]
    end = [i + 1 for i, ln in enumerate(lines) if ln in ("M30", "M2")]
    assert off and end and last_cut < off[-1] < end[-1]
    assert program.ended and not program.spindle_on and program.unknown == []


def test_an_arc_lead_in_and_lead_out_meet_the_profile_tangentially_and_stay_clear_of_the_part(mill):
    contour(mill, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, lead_in="arc", lead_out="arc", lead_radius=2.0, stepdown=5.0)
    program, _ = mill.post()
    cuts = at_depth(program, -5.0)
    leads = [i for i, m in enumerate(cuts) if m.arc and abs(m.radius - 2.0) < 1e-3]
    assert len(leads) == 2
    first, last = leads

    def tangent_at(m, point):
        rx, ry = point[0] - m.centre[0], point[1] - m.centre[1]
        t = (ry, -rx) if m.kind == 2 else (-ry, rx)
        n = math.hypot(*t)
        return t[0] / n, t[1] / n

    def chord_dir(m):
        dx, dy = m.end[0] - m.start[0], m.end[1] - m.start[1]
        n = math.hypot(dx, dy)
        return dx / n, dy / n

    t_in = tangent_at(cuts[first], cuts[first].end)
    d_next = chord_dir(cuts[first + 1])
    assert t_in[0] * d_next[0] + t_in[1] * d_next[1] > 1 - 1e-6
    t_out = tangent_at(cuts[last], cuts[last].start)
    d_prev = chord_dir(cuts[last - 1])
    assert t_out[0] * d_prev[0] + t_out[1] * d_prev[1] > 1 - 1e-6
    for p in sample_points([cuts[first], cuts[last]]):
        assert dist_to_polygon(p, RECT) >= R - 1e-3 and not inside(p, RECT)
