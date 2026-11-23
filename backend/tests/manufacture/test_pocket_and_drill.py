import math
import re

import numpy as np
import pytest

from tests.manufacture.helpers import Mill, at_depth, box_triangles, dist_to_polygon, inside, min_dist_to_segments, open_mesh, rapids_into_uncut_stock, rect, sample_points, segments_xy

R = 3.0
POCKET = rect(20.0, 20.0, 70.0, 50.0)
HOLES = [(15.0, 15.0), (80.0, 15.0), (80.0, 70.0), (40.0, 60.0)]


@pytest.fixture()
def mill(docs, tmp_path):
    doc = open_mesh(docs, tmp_path, box_triangles((0, 0, -20), (100, 100, 0)), "block")
    m = Mill(doc)
    m.tool(1, "flat", 2 * R)
    m.tool(3, "drill", 6.0, tip_angle=118.0)
    return m


def pocket(mill, **params):
    base = {"stepover": 2.5, "stepdown": 2.0}
    base.update(params)
    return mill.op("pocket", 1, {"kind": "rect", "min": [20, 20], "max": [70, 50]}, base, heights={"bottom": -6.0})


def test_a_pocket_toolpath_never_comes_closer_to_the_wall_than_the_tool_radius(mill):
    pocket(mill, entry="helix")
    program, _ = mill.post()
    pts = sample_points(program.cutting())
    assert len(pts) > 100
    for p in pts:
        assert inside(p, POCKET) and dist_to_polygon(p, POCKET) >= R - 1e-3


@pytest.mark.parametrize("stepover", [1.5, 2.5, 4.0, pytest.param(5.5, marks=pytest.mark.xfail(strict=True, reason="DEFECT: a pocket accepts any stepover below 0.99 of the tool diameter but its nested offsets leave uncut cusps in the floor corners once the stepover exceeds the tool radius times the square root of two (5.5 mm with a 6 mm tool leaves points 3.18 mm from any tool centre); the pocket is described as clearing the region, so it should add corner passes or refuse the stepover"))])
def test_a_pocket_clears_every_point_of_the_floor_a_round_tool_can_reach(mill, stepover):
    pocket(mill, stepover=stepover, stepdown=6.0, entry="plunge")
    program, _ = mill.post()
    segs = segments_xy(at_depth(program, -6.0))
    locus = rect(20.0 + R, 20.0 + R, 70.0 - R, 50.0 - R)
    grid = [(x, y) for x in np.arange(20.25, 70.0, 0.5) for y in np.arange(20.25, 50.0, 0.5)]
    reachable = [p for p in grid if inside(p, locus) or dist_to_polygon(p, locus) <= R - 1e-6]
    assert len(reachable) > 0.95 * len(grid)
    gaps = min_dist_to_segments(reachable, segs)
    assert float(gaps.max()) <= R + 1e-3


def test_pocket_rings_are_spaced_no_wider_than_the_stepover(mill):
    pocket(mill, stepover=2.5, stepdown=6.0, entry="plunge", arc_tolerance=0.0)
    program, _ = mill.post()
    xs = sorted({round(m.start[0], 4) for m in at_depth(program, -6.0) if not m.arc and abs(m.start[0] - m.end[0]) < 1e-9 and abs(m.start[1] - m.end[1]) > 1.0 and m.start[0] < 45.0})
    assert xs[0] == pytest.approx(20.0 + R, abs=1e-3)
    assert len(xs) >= 4
    assert all(b - a <= 2.5 + 1e-3 for a, b in zip(xs, xs[1:]))


@pytest.mark.parametrize("entry", ["helix", "ramp", "plunge"])
def test_a_pocket_steps_down_no_more_than_the_step_down_never_below_the_floor_and_never_rapids_into_stock(mill, entry):
    pocket(mill, entry=entry, stepdown=2.5)
    program, _ = mill.post()
    assert program.lowest() == pytest.approx(-6.0, abs=1e-6)
    levels = sorted({round(m.end[2], 6) for m in program.cutting() if abs(m.start[2] - m.end[2]) < 1e-9 and math.dist(m.start[:2], m.end[:2]) > 1.0}, reverse=True)
    assert levels[-1] == pytest.approx(-6.0, abs=1e-6)
    assert all(a - b <= 2.5 + 1e-6 for a, b in zip([0.0] + levels, levels))
    assert rapids_into_uncut_stock(program, 0.0) == []


def drill(mill, **params):
    base = {"cycle": "drill"}
    base.update(params)
    return mill.op("drill", 3, {"kind": "points", "points": [list(h) for h in HOLES]}, base, {"rpm": 3000, "vf_cut": 150, "vf_plunge": 150}, {"bottom": -8.0})


CYCLE = re.compile(r"^G(81|82|83|73)\b(.*)$")


def cycles(text):
    out = []
    for raw in text.splitlines():
        m = CYCLE.match(raw.strip())
        if m:
            words = {k: float(v) for k, v in re.findall(r"([XYZRQPF])(-?[\d.]+)", m.group(2))}
            out.append((int(m.group(1)), words))
    return out


def test_a_drill_cycle_goes_to_the_stated_depth_at_every_stated_point(mill):
    drill(mill)
    _, text = mill.post()
    found = cycles(text)
    assert sorted((w["X"], w["Y"]) for _, w in found) == sorted(HOLES)
    assert all(code == 81 and w["Z"] == -8.0 and w["R"] == 2.0 and w["F"] == 150.0 for code, w in found if "F" in w)
    assert all(w["Z"] == -8.0 for _, w in found)


def test_a_through_drill_adds_the_point_length_of_its_tip_angle(mill):
    drill(mill, through=True)
    _, text = mill.post()
    tip = 3.0 / math.tan(math.radians(118.0 / 2.0))
    assert {round(w["Z"], 3) for _, w in cycles(text)} == {round(-8.0 - tip, 3)}


def test_a_peck_cycle_carries_the_peck_depth(mill):
    drill(mill, cycle="peck", peck=2.5)
    _, text = mill.post()
    found = cycles(text)
    assert len(found) == len(HOLES) and all(code == 83 and w["Q"] == 2.5 and w["Z"] == -8.0 for code, w in found)


def test_a_peck_drill_expanded_for_a_controller_without_cycles_pecks_in_steps_no_deeper_than_the_peck(mill):
    drill(mill, cycle="peck", peck=2.5)
    program, _ = mill.post("grbl")
    assert program.unknown == []
    plunges = [m for m in program.cutting() if math.dist(m.start[:2], m.end[:2]) < 1e-9]
    assert plunges and all(m.end[2] < m.start[2] and m.feed == 150.0 for m in plunges)
    by_hole = {}
    for m in plunges:
        by_hole.setdefault((round(m.end[0], 3), round(m.end[1], 3)), []).append(m)
    assert sorted(by_hole) == sorted(HOLES)
    for moves in by_hole.values():
        assert min(m.end[2] for m in moves) == pytest.approx(-8.0, abs=1e-6)
        below_top = [m for m in moves if m.end[2] < 0.0]
        new_depth = 0.0
        for m in below_top:
            assert m.end[2] >= new_depth - 2.5 - 1e-6
            new_depth = min(new_depth, m.end[2])
        assert len(below_top) >= math.ceil(8.0 / 2.5)
    assert rapids_into_uncut_stock(program, 0.0) == []
    assert program.lowest() == pytest.approx(-8.0, abs=1e-6)
