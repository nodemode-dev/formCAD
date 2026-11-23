import math

import pytest

from tests.solids import kit
from tests.support.dxf import Dxf

T = 2.0
R = 3.0
BASE = 50.0
WIDTH = 20.0
FLANGE = 30.0
END_EDGE = "e(F2:end:end|F2:seg0:ref)"
TIGHT = dict(rel=1e-9, abs=1e-6)


def allowance(angle_deg, radius, k, thickness):
    return math.radians(angle_deg) * (radius + k * thickness)


def plate(doc, k=0.4, thickness=T, radius=R):
    kit.metric(doc)
    kit.sketch(doc, "XY", ("LINE", "0,0", "%g,0" % BASE, ""))
    sketch = kit.tree(doc)["features"][-1]["id"]
    out = kit.add(doc, "base_flange", {"thickness": thickness, "radius": radius, "k_factor": k, "depth": WIDTH}, {"sketch": {"id": sketch}})
    assert out["state"]["status"] == "ok"
    return out["id"]


def flange(doc, **params):
    values = {"length": FLANGE, "position": "bend_outside", "length_ref": "tangent"}
    values.update(params)
    out = kit.add(doc, "edge_flange", values, {"edges": [{"key": END_EDGE}]})
    assert out["state"]["status"] == "ok"
    return out


def flat(doc):
    return doc.get("/sheetmetal/flat/props")


@pytest.mark.kernel
def test_a_base_flange_from_a_line_is_a_flat_plate_of_the_rule_thickness(doc):
    plate(doc)
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(BASE * WIDTH * T, **TIGHT)
    assert kit.extents(doc) == pytest.approx(([0.0, 0.0, 0.0], [BASE, T, WIDTH]), abs=1e-6)
    blank = flat(doc)
    assert blank["num_bends"] == 0 and blank["thickness"] == pytest.approx(T)
    assert blank["blank_area"] == pytest.approx(BASE * WIDTH, **TIGHT)


@pytest.mark.kernel
@pytest.mark.parametrize("k", [0.3, 0.44, 0.5])
def test_the_flat_length_of_a_plate_with_an_edge_flange_adds_the_k_factor_bend_allowance(doc, k):
    plate(doc, k=k)
    flange(doc)
    blank = flat(doc)
    length = BASE + allowance(90, R, k, T) + FLANGE
    assert blank["num_bends"] == 1
    assert blank["bbox_length"] == pytest.approx(length, **TIGHT)
    assert blank["bbox_width"] == pytest.approx(WIDTH, **TIGHT)
    assert blank["blank_area"] == pytest.approx(length * WIDTH, **TIGHT)


@pytest.mark.kernel
@pytest.mark.parametrize("angle", [45.0, 120.0])
def test_the_bend_allowance_grows_with_the_bend_angle(doc, angle):
    plate(doc)
    flange(doc, angle=angle)
    assert flat(doc)["bbox_length"] == pytest.approx(BASE + allowance(angle, R, 0.4, T) + FLANGE, **TIGHT)


@pytest.mark.kernel
@pytest.mark.parametrize("position, measured, base_straight, flange_straight", [
    ("bend_outside", "tangent", BASE, FLANGE),
    ("material_inside", "outside", BASE - R - T, FLANGE - R - T),
    ("material_outside", "inside", BASE - R, FLANGE - R),
])
def test_the_flange_position_and_length_datum_set_the_straight_lengths_in_the_flat(doc, position, measured, base_straight, flange_straight):
    plate(doc)
    flange(doc, position=position, length_ref=measured)
    assert flat(doc)["bbox_length"] == pytest.approx(base_straight + allowance(90, R, 0.4, T) + flange_straight, **TIGHT)


@pytest.mark.kernel
def test_the_folded_part_has_the_volume_of_two_straight_plates_and_a_quarter_ring(doc):
    plate(doc)
    flange(doc)
    ring = math.pi / 4 * ((R + T) ** 2 - R ** 2) * WIDTH
    assert kit.volume(doc) == pytest.approx((BASE + FLANGE) * T * WIDTH + ring, **TIGHT)
    lo, hi = kit.extents(doc)
    assert hi[0] - lo[0] == pytest.approx(BASE + R + T, abs=1e-6)
    assert hi[1] - lo[1] == pytest.approx(R + T + FLANGE, abs=1e-6)


@pytest.mark.kernel
def test_with_a_k_factor_of_one_half_the_flat_area_times_the_thickness_equals_the_folded_volume(doc):
    plate(doc, k=0.5)
    flange(doc)
    assert flat(doc)["blank_area"] * T == pytest.approx(kit.volume(doc), **TIGHT)


@pytest.mark.kernel
def test_the_flat_pattern_dxf_holds_the_blank_outline_and_one_bend_line_at_the_middle_of_the_bend(doc, tmp_path):
    plate(doc)
    flange(doc)
    out = doc.post("/sheetmetal/flat/export", {"path": str(tmp_path / "blank.dxf")})
    dxf = Dxf.read(out["path"])
    length = BASE + allowance(90, R, 0.4, T) + FLANGE
    outline = [e for e in dxf.entities("LWPOLYLINE") if e.layer == "OUTER"]
    assert len(outline) == 1
    xs = [p[0] for p in outline[0].points(10)]
    ys = [p[1] for p in outline[0].points(10)]
    assert max(xs) - min(xs) == pytest.approx(length, abs=1e-6)
    assert max(ys) - min(ys) == pytest.approx(WIDTH, abs=1e-6)
    bends = [e for e in dxf.entities("LINE") if e.layer.startswith("BEND_")]
    assert len(bends) == 1
    start, end = bends[0].point(10), bends[0].point(11)
    assert start[0] == pytest.approx(BASE + allowance(90, R, 0.4, T) / 2, abs=1e-6)
    assert end[0] == pytest.approx(start[0], abs=1e-9)
    assert abs(end[1] - start[1]) == pytest.approx(WIDTH, abs=1e-6)


@pytest.mark.kernel
def test_changing_the_plate_thickness_rebuilds_the_flange_and_its_flat_length(doc):
    root = plate(doc)
    flange(doc)
    doc.engine.patch(doc.url("/part/features/%s" % root), {"params": {"thickness": 1.0}})
    assert flat(doc)["bbox_length"] == pytest.approx(BASE + allowance(90, R, 0.4, 1.0) + FLANGE, **TIGHT)
    assert kit.volume(doc) == pytest.approx((BASE + FLANGE) * WIDTH + math.pi / 4 * ((R + 1) ** 2 - R ** 2) * WIDTH, **TIGHT)
