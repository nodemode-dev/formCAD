import math
import re

import numpy as np
import pytest

from tests.manufacture.helpers import dist_to_polygon, inside, min_dist_to_segments, rect, sample_points
from tests.support.gcode import Program


def levels(program):
    return sorted({round(m.end[2], 3) for m in program.cutting() if abs(m.start[2] - m.end[2]) < 1e-9})


@pytest.fixture()
def pocket_part(docs, fixtures):
    return docs.open(fixtures / "cam" / "pocket-part.fcad")


@pytest.mark.kernel
def test_the_pocket_part_program_regenerates_with_the_committed_extents_cut_length_and_depths(kernel, pocket_part, fixtures):
    expected = Program.read(fixtures / "cam" / "pocket-part.ngc")
    got = Program(pocket_part.post("/cam/preview", {"post": "linuxcnc"})["text"])
    assert got.unknown == [] and got.ended
    assert got.extents() == pytest.approx(expected.extents(), abs=1e-3)
    assert got.lowest() == pytest.approx(expected.lowest(), abs=1e-3)
    assert got.cut_length() == pytest.approx(expected.cut_length(), rel=1e-3)
    assert levels(got) == levels(expected)
    assert got.tools == expected.tools


@pytest.mark.kernel
def test_the_pocket_part_program_drills_its_four_holes_through_the_block_10_mm_from_the_corners(kernel, pocket_part):
    text = pocket_part.post("/cam/preview", {"post": "linuxcnc"})["text"]
    holes = [dict((k, float(v)) for k, v in re.findall(r"([XYZ])(-?[\d.]+)", ln)) for ln in text.splitlines() if re.match(r"^G8[13]\b|^G73\b", ln.strip())]
    assert sorted((h["X"], h["Y"]) for h in holes) == sorted([(10.0, 10.0), (90.0, 10.0), (10.0, 70.0), (90.0, 70.0)])
    tip = 3.0 / math.tan(math.radians(59.0))
    assert all(h["Z"] == pytest.approx(-20.0 - tip, abs=1e-3) for h in holes)


@pytest.mark.kernel
def test_the_pocket_part_pocket_floor_is_8_mm_deep_and_the_outline_cuts_the_full_20_mm_at_one_tool_radius(kernel, pocket_part):
    ops = {op["label"]: op["id"] for op in pocket_part.get("/cam")["ops"]}
    clear = Program(pocket_part.post("/cam/preview", {"post": "linuxcnc", "ops": [ops["Clear pocket"]]})["text"])
    assert clear.lowest() == pytest.approx(-8.0, abs=1e-3)
    outline = Program(pocket_part.post("/cam/preview", {"post": "linuxcnc", "ops": [ops["Cut outline"]]})["text"])
    assert outline.lowest() == pytest.approx(-20.0, abs=1e-3)
    block = rect(0.0, 0.0, 100.0, 80.0)
    wall = [m for m in outline.cutting() if abs(m.start[2] + 20.0) < 1e-6 and abs(m.end[2] + 20.0) < 1e-6 and not (m.arc and m.radius < 2.9)]
    pts = sample_points(wall)
    assert len(pts) > 20
    assert all(dist_to_polygon(p, block) >= 3.0 - 1e-3 and not inside(p, block) for p in pts)
    assert sum(1 for p in pts if abs(dist_to_polygon(p, block) - 3.0) < 1e-3) > 0.9 * len(pts)


SHEETS = [("laser", "P1", "cut_grbl_laser", ".nc", "M4"), ("plasma", "P2", "cut_linuxcnc_plasma", ".ngc", "M3"), ("waterjet", "P3", "cut_linuxcnc_waterjet", ".ngc", "M3")]


@pytest.mark.parametrize("name,process,post,ext,on", SHEETS)
@pytest.mark.parametrize("sheet", [1, 2])
def test_each_sheet_set_cutting_program_regenerates_with_the_committed_geometry_and_pierce_count(docs, fixtures, data_dir, name, process, post, ext, on, sheet):
    expected_path = fixtures / "cam" / "sheet-set" / ("sheet-set-%s-%d%s" % (name, sheet, ext))
    doc = docs.open(fixtures / "cam" / "sheet-set" / "sheet-set.fcad")
    out = data_dir / ("lane9-sheet-%s-%d%s" % (name, sheet, ext))
    res = doc.post("/cam/nests/N1/export", {"process": process, "post": post, "path": str(out), "sheet": sheet})
    assert [f["sheet"] for f in res["files"]] == [sheet]
    got_text = open(res["files"][0]["path"], encoding="utf-8").read()
    want_text = expected_path.read_text(encoding="utf-8")
    got, want = Program(got_text), Program(want_text)
    assert got.unknown == [] and got.ended and not got.spindle_on
    assert got.extents() == pytest.approx(want.extents(), abs=1e-3)
    assert got.cut_length() == pytest.approx(want.cut_length(), rel=1e-4)
    pierces = lambda t: sum(1 for ln in t.splitlines() if ln.strip().startswith(on))
    assert pierces(got_text) == pierces(want_text)


def test_the_sheet_set_nest_places_all_31_parts_on_two_sheets_inside_the_margin_without_overlap(docs, fixtures):
    doc = docs.open(fixtures / "cam" / "sheet-set" / "sheet-set.fcad")
    total = 0
    for sheet in (1, 2):
        shapes = doc.get("/cam/nests/N1/shapes", sheet=sheet)
        assert (shapes["width"], shapes["height"]) == (500.0, 400.0)
        outers = [[tuple(p) for p in next(l for l in part["loops"] if l["outer"])["pts"]] for part in shapes["parts"]]
        total += len(outers)
        for poly in outers:
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            assert min(xs) >= 5.0 - 0.01 and min(ys) >= 5.0 - 0.01 and max(xs) <= 495.0 + 0.01 and max(ys) <= 395.0 + 0.01
        assert_apart(outers, 2.0)
    assert total == 31


def assert_apart(polys, gap):
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            a, b = polys[i], polys[j]
            ax0, ay0, ax1, ay1 = min(p[0] for p in a), min(p[1] for p in a), max(p[0] for p in a), max(p[1] for p in a)
            bx0, by0, bx1, by1 = min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b), max(p[1] for p in b)
            if ax1 + gap < bx0 or bx1 + gap < ax0 or ay1 + gap < by0 or by1 + gap < ay0:
                continue
            assert not inside(a[0], b) and not inside(b[0], a)
            sb = np.asarray([(b[k][0], b[k][1], b[(k + 1) % len(b)][0], b[(k + 1) % len(b)][1]) for k in range(len(b))])
            sa = np.asarray([(a[k][0], a[k][1], a[(k + 1) % len(a)][0], a[(k + 1) % len(a)][1]) for k in range(len(a))])
            d = min(float(min_dist_to_segments(a, sb).min()), float(min_dist_to_segments(b, sa).min()))
            assert d >= gap - 0.01
