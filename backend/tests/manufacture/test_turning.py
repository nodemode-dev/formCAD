import json
import math
import re

import pytest

from tests.manufacture.helpers import Mill, box_triangles, open_mesh

PROFILE = {"units": "diameter", "pts": [[0, 0], [0, 20], [-20, 20], [-20, 30], [-45, 30], [-45, 38]]}
CUT = {"vc": 150, "fpr": 0.2, "max_rpm": 3000}
NOSE = 0.4


@pytest.fixture()
def lathe(docs, tmp_path):
    doc = open_mesh(docs, tmp_path, box_triangles((-20, -20, -60), (20, 20, 0)), "bar")
    m = Mill(doc, machine="lathe", stock={"kind": "cylinder", "diameter": 40, "length": 60})
    m.tool(1, "insert", 8.0, insert={"nose_radius": NOSE})
    m.tool(2, "groove", 3.0)
    m.tool(3, "thread", 8.0)
    return m


def finished_radius(z):
    if z > 0.0:
        return 0.0
    if z > -20.0:
        return 10.0
    if z > -45.0:
        return 15.0
    return None


def points(program, step=0.25):
    out = []
    for m in program.moves[1:]:
        n = max(1, int(math.dist(m.start, m.end) / step))
        out.extend(tuple(m.start[i] + (m.end[i] - m.start[i]) * k / n for i in range(3)) for k in range(n + 1))
    return out


@pytest.mark.parametrize("post", ["lathe_linuxcnc", "millturn_linuxcnc"])
def test_rough_turning_a_stepped_profile_never_goes_inside_the_finished_radius_and_leaves_only_the_allowance(lathe, post):
    oid = lathe.op("turn_rough", 1, None, dict(CUT, profile=json.dumps(PROFILE), doc=2.0, allowance=0.3, z_front=0.0))
    program, text = lathe.post(post, ops=[oid])
    assert program.unknown == [] and program.ended and "G7" in text
    for x, _, z in points(program):
        r = finished_radius(z)
        if r is not None:
            assert x / 2.0 >= r - 1e-3
    for lo, hi, r in ((-18.0, -1.0, 10.0), (-43.0, -22.0, 15.0)):
        inner = [x / 2.0 for x, _, z in points(program) if lo <= z <= hi]
        assert min(inner) >= r + 0.3 - 1e-3
        assert min(inner) <= r + 0.3 + NOSE + 1e-3


def test_rough_turning_removes_the_stock_in_radial_steps_no_deeper_than_the_depth_of_cut(lathe):
    oid = lathe.op("turn_rough", 1, None, dict(CUT, profile=json.dumps(PROFILE), doc=2.0, allowance=0.3, z_front=0.0))
    program, _ = lathe.post("lathe_linuxcnc", ops=[oid])
    axial = sorted({round(m.start[0] / 2.0, 4) for m in program.cutting() if abs(m.start[0] - m.end[0]) < 1e-9 and m.start[2] - m.end[2] > 5.0}, reverse=True)
    assert axial[0] >= 20.0 - 2.0 - 1e-6
    assert all(a - b <= 2.0 + 1e-6 for a, b in zip(axial, axial[1:]))


def test_facing_steps_down_by_the_depth_of_cut_to_the_finished_face_and_across_the_axis(lathe):
    oid = lathe.op("turn_face", 1, None, dict(CUT, z_target=0.0, z_front=1.5, doc=0.5))
    program, _ = lathe.post("lathe_linuxcnc", ops=[oid])
    passes = [m for m in program.cutting() if abs(m.start[2] - m.end[2]) < 1e-9]
    zs = sorted({round(m.end[2] - NOSE, 4) for m in passes}, reverse=True)
    assert zs == pytest.approx([1.0, 0.5, 0.0], abs=1e-6)
    assert min(m.end[2] for m in program.moves) >= 0.0 + NOSE - 1e-6
    assert all(min(m.start[0], m.end[0]) <= 0.0 + 1e-6 for m in passes)
    assert all(max(m.start[0], m.end[0]) / 2.0 >= 20.0 for m in passes)


def test_a_groove_stays_between_its_walls_never_below_its_bottom_and_finishes_to_the_drawn_size(lathe):
    oid = lathe.op("turn_groove", 2, None, dict(CUT, z_start=-30.0, width=5.0, bottom_diameter=24.0, allowance=0.1, peck=2.0))
    program, _ = lathe.post("lathe_linuxcnc", ops=[oid])
    half = 1.5
    cuts = program.cutting()
    for m in cuts:
        for p in (m.start, m.end):
            assert p[0] >= 24.0 - 1e-6
            assert -35.0 - 1e-6 <= p[2] - half and p[2] + half <= -30.0 + 1e-6
    floor = [m for m in cuts if abs(m.start[0] - 24.0) < 1e-6 and abs(m.end[0] - 24.0) < 1e-6]
    assert floor
    span = (min(min(m.start[2], m.end[2]) for m in floor) - half, max(max(m.start[2], m.end[2]) for m in floor) + half)
    assert span == pytest.approx((-35.0, -30.0), abs=1e-6)
    reached = {}
    for m in cuts:
        if abs(m.start[2] - m.end[2]) < 1e-9 and m.end[0] < m.start[0]:
            key = round(m.end[2], 4)
            before = min([40.0] + [x for z, x in reached.items() if abs(z - key) <= 0.5])
            assert (before - m.end[0]) / 2.0 <= 2.0 + 1e-6
            reached[key] = min(before, m.end[0])
    assert len(reached) >= 2


def test_threading_feeds_at_the_pitch_to_the_standard_depth_with_equal_chip_area_passes(lathe):
    pitch, major, n = 1.5, 20.0, 6
    oid = lathe.op("turn_thread", 3, None, {"major_diameter": major, "pitch": pitch, "z_start": -2.0, "z_end": -18.0, "passes": n, "spring_passes": 1, "vc": 100, "max_rpm": 2000})
    _, text = lathe.post("lathe_linuxcnc", ops=[oid])
    lines = [ln.strip() for ln in text.splitlines()]
    sync = [i for i, ln in enumerate(lines) if ln.startswith("G33")]
    assert len(sync) == n + 1
    depth = 0.6134 * pitch
    for k, i in enumerate(sync):
        words = dict((a, float(b)) for a, b in re.findall(r"([XZK])(-?[\d.]+)", lines[i]))
        assert words["K"] == pitch and words["Z"] == -18.0
        x = float(re.search(r"X(-?[\d.]+)", lines[i - 1]).group(1))
        want = depth * math.sqrt(min(k + 1, n) / n)
        assert (major - x) / 2.0 == pytest.approx(want, abs=1e-3)
    rpm = float(re.search(r"G97 S([\d.]+)", text).group(1))
    assert rpm == pytest.approx(1000.0 * 100 / (math.pi * major), abs=0.1)


def test_the_thread_depth_route_states_the_standard_depth_and_the_square_root_pass_schedule(engine):
    res = engine.post("/api/cam/turning/thread", {"pitch": 2.0, "passes": 4})
    assert res["depth"] == pytest.approx(0.6134 * 2.0, abs=1e-9)
    assert res["pass_depths"] == pytest.approx([0.6134 * 2.0 * math.sqrt(k / 4) for k in range(1, 5)], abs=1e-4)
