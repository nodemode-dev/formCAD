import pytest

from tests.electronics.drill_reader import Drill
from tests.electronics.kit import HOLE, J_PADS, PARTS, VIA, gerbers, near, output_board, world


def test_the_drill_reader_follows_units_zero_format_tools_and_slots():
    d = Drill("M48\nINCH,TZ\nT1C0.0394\n%\nT1\nX01Y02\nX.5Y.25G85X1.5Y.25\nM30\n")
    assert d.units == "in" and abs(d.tools[1] - 1.00076) < 1e-9
    assert near((d.hits[0].x, d.hits[0].y), (0.0001 * 25.4, 0.0002 * 25.4))
    assert near((d.hits[1].x, d.hits[1].y), (12.7, 6.35)) and near(d.hits[1].end, (38.1, 6.35))
    with pytest.raises(ValueError):
        Drill("M48\nMETRIC\n%\nT3\nX1.0Y1.0\nM30\n")


@pytest.fixture()
def drills(doc, tmp_path):
    output_board(doc)
    return {d.function(): d for d in gerbers(doc, tmp_path / "board")["drills"]}


def test_plated_and_unplated_holes_go_to_separate_drill_files(drills):
    assert set(drills) == {"Plated,1,2,PTH", "NonPlated,1,2,NPTH"}
    assert all(d.units == "mm" and d.ended for d in drills.values())


def test_the_plated_drill_file_has_every_through_hole_pad_and_via_at_its_place_with_its_tool(drills):
    d = drills["Plated,1,2,PTH"]
    j = PARTS["J1"]
    want = [(world(j["x"], j["y"], (q["x"], q["y"])), q["drill"]) for q in J_PADS] + [((VIA["x"], VIA["y"]), VIA["drill"])]
    assert len(d.hits) == len(want)
    for (x, y), dia in want:
        match = [h for h in d.hits if near((h.x, h.y), (x, y))]
        assert len(match) == 1 and abs(match[0].diameter - dia) < 1e-9
    assert sorted(d.tools.values()) == sorted({q["drill"] for q in J_PADS} | {VIA["drill"]})


def test_the_unplated_drill_file_has_the_mounting_hole_at_its_place_with_its_diameter(drills):
    d = drills["NonPlated,1,2,NPTH"]
    assert len(d.hits) == 1
    assert near((d.hits[0].x, d.hits[0].y), (HOLE["x"], HOLE["y"])) and abs(d.hits[0].diameter - HOLE["drill"]) < 1e-9


def test_the_drill_export_alone_writes_the_same_holes_as_the_gerber_export(doc, tmp_path):
    output_board(doc)
    both = {d.function(): sorted((round(h.x, 6), round(h.y, 6), h.diameter) for h in d.hits) for d in gerbers(doc, tmp_path / "a")["drills"]}
    report = doc.post("/ecad/export/drill", {"out": str(tmp_path / "b")})
    alone = {}
    for row in report["drills"]:
        d = Drill.read(row["file"])
        alone[d.function()] = sorted((round(h.x, 6), round(h.y, 6), h.diameter) for h in d.hits)
    assert alone == both
