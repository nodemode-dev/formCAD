import math

import pytest

from tests.electronics.kit import board, flat_bbox, place, smd, tht

STACK = [{"kind": "copper", "name": "F.Cu", "thickness": 0.035}, {"kind": "core", "name": "Core", "thickness": 1.2}, {"kind": "copper", "name": "B.Cu", "thickness": 0.035}]
THICK = 0.035 + 1.2 + 0.035


def build(doc):
    board(doc, (0, 0, 50, 40), stackup=STACK)
    place(doc, "U1", 12, 15, [smd(1, -1, 0, 0.6, 0.6), smd(2, 1, 0, 0.6, 0.6)], body={"shape": "box", "size": [4, 3, 1.5], "pos": [0, 0], "z0": 0})
    place(doc, "R1", 30, 25, [smd(1, -1, 0, 0.6, 0.6), smd(2, 1, 0, 0.6, 0.6)], side="bottom", body={"shape": "box", "size": [2, 1, 0.5], "pos": [0, 0], "z0": 0})
    place(doc, "J1", 40, 10, [tht(1, 0, 0, 2.0, 1.0)], body={"shape": "box", "size": [3, 2, 6], "pos": [0, 0], "z0": 0}, rot=90)
    doc.post("/pcb/holes", {"x": 5, "y": 5, "drill": 3.0})


@pytest.mark.kernel
def test_the_board_body_is_the_outline_area_times_the_stackup_thickness_less_its_holes(doc):
    build(doc)
    s = doc.get("/ecad/board3d")
    assert math.isclose(s["thickness"], THICK, abs_tol=1e-9)
    want = THICK * (50 * 40 - math.pi * 1.5 ** 2 - math.pi * 0.5 ** 2)
    assert math.isclose(s["board_volume"], want, rel_tol=1e-6)
    box = flat_bbox(s["bbox"])
    assert all(math.isclose(a, b, abs_tol=1e-4) for a, b in zip(box, [0, 0, 0, 50, 40, THICK]))
    assert s["valid"] and s["closed"]
    assert math.isclose(s["component_volume"], 4 * 3 * 1.5 + 2 * 1 * 0.5 + 3 * 2 * 6, rel_tol=1e-6)


@pytest.mark.kernel
def test_component_bodies_sit_on_their_side_of_the_board_at_their_place(doc, tmp_path, kernel):
    build(doc)
    path = tmp_path / "board.step"
    doc.post("/ecad/export/step", {"out": str(path)})
    opened = kernel.call("open_step", {"path": str(path)})
    try:
        boxes = sorted(tuple(round(v, 4) for v in flat_bbox(b["summary"]["bbox"])) for b in opened["bodies"])
    finally:
        kernel.call("shape_free", {"ids": [b["id"] for b in opened["bodies"]]})
    want = sorted([
        (0.0, 0.0, 0.0, 50.0, 40.0, round(THICK, 4)),
        (10.0, 13.5, round(THICK, 4), 14.0, 16.5, round(THICK + 1.5, 4)),
        (29.0, 24.5, -0.5, 31.0, 25.5, 0.0),
        (39.0, 8.5, round(THICK, 4), 41.0, 11.5, round(THICK + 6, 4)),
    ])
    assert len(boxes) == 4
    for got, exp in zip(boxes, want):
        assert all(abs(a - b) <= 1e-3 for a, b in zip(got, exp)), (got, exp)
