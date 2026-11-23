import math

import pytest

from tests.meshsim import helpers as h

pytestmark = pytest.mark.kernel

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def test_mass_properties_of_a_box_match_closed_form_for_a_given_density(doc):
    h.metric(doc)
    a, b, c, rho = 10.0, 20.0, 30.0, 2.5
    body = h.box(doc, [a, b, c], [1, 2, 3])
    p = doc.get("/solids/%d/massprops" % body, density=rho)
    m = rho * a * b * c
    assert p["volume"] == pytest.approx(a * b * c, rel=1e-9)
    assert p["mass"] == pytest.approx(m, rel=1e-9)
    assert p["area"] == pytest.approx(2 * (a * b + b * c + a * c), rel=1e-9)
    assert p["centroid"] == pytest.approx([1 + a / 2, 2 + b / 2, 3 + c / 2], abs=1e-9)
    expected = sorted([m * (b * b + c * c) / 12, m * (a * a + c * c) / 12, m * (a * a + b * b) / 12])
    assert sorted(p["principal"]) == pytest.approx(expected, rel=1e-9)


def test_mass_properties_of_a_cylinder_match_closed_form(doc):
    h.metric(doc)
    r, height, rho = 4.0, 12.0, 7.85e-3
    body = h.handle_of(doc.command("cylinder", center=[0, 0, 0], radius=r, height=height))
    p = doc.get("/solids/%d/massprops" % body, density=rho)
    m = rho * math.pi * r * r * height
    assert p["volume"] == pytest.approx(math.pi * r * r * height, rel=1e-9)
    assert p["centroid"] == pytest.approx([0, 0, height / 2], abs=1e-9)
    axial = m * r * r / 2
    transverse = m * (3 * r * r + height * height) / 12
    assert sorted(p["principal"]) == pytest.approx(sorted([axial, transverse, transverse]), rel=1e-9)


@pytest.mark.parametrize("shift, overlap", [((4, 3, 2), 6 * 7 * 8), ((9, 9, 9), 1.0), ((0, 0, 5), 500.0)])
def test_interference_between_two_overlapping_boxes_equals_their_overlap_volume(kernel, shift, overlap):
    a = kernel.call("primitive", {"kind": "box", "dx": 10.0, "dy": 10.0, "dz": 10.0})
    b = kernel.call("primitive", {"kind": "box", "dx": 10.0, "dy": 10.0, "dz": 10.0})
    try:
        moved = [1, 0, 0, shift[0], 0, 1, 0, shift[1], 0, 0, 1, shift[2]]
        got = kernel.call("asm_interference", {"items": [{"key": "a", "id": a["id"], "matrix": IDENTITY}, {"key": "b", "id": b["id"], "matrix": moved}], "fuzzy": 0.001, "min_volume": 1e-3, "skip": []})
        assert len(got["interferences"]) == 1
        hit = got["interferences"][0]
        assert hit["volume"] == pytest.approx(overlap, rel=1e-9)
        assert hit["centre"] == pytest.approx([(10 + s) / 2 for s in shift], abs=1e-9)
    finally:
        kernel.call("shape_free", {"id": a["id"]})
        kernel.call("shape_free", {"id": b["id"]})


def test_boxes_that_only_touch_or_stand_apart_report_no_interference(kernel):
    a = kernel.call("primitive", {"kind": "box", "dx": 10.0, "dy": 10.0, "dz": 10.0})
    b = kernel.call("primitive", {"kind": "box", "dx": 10.0, "dy": 10.0, "dz": 10.0})
    try:
        for dx in (10.0, 12.0):
            moved = [1, 0, 0, dx, 0, 1, 0, 0, 0, 0, 1, 0]
            got = kernel.call("asm_interference", {"items": [{"key": "a", "id": a["id"], "matrix": IDENTITY}, {"key": "b", "id": b["id"], "matrix": moved}], "fuzzy": 0.001, "min_volume": 1e-3, "skip": []})
            assert got["interferences"] == []
    finally:
        kernel.call("shape_free", {"id": a["id"]})
        kernel.call("shape_free", {"id": b["id"]})


def test_draft_analysis_of_a_cone_reads_the_half_angle_on_its_side_and_ninety_on_its_caps(doc):
    h.metric(doc)
    r1, r2, height = 10.0, 5.0, 10.0
    cone = h.handle_of(doc.command("cone", center=[0, 0, 0], radius=r1, top_radius=r2, height=height))
    stats = doc.command("draftanalysis", handles=[cone], pull="z")["result"]["stats"]
    assert stats["median"] == pytest.approx(math.degrees(math.atan((r1 - r2) / height)), abs=1e-3)
    assert stats["max"] == pytest.approx(90.0, abs=1e-6)
    assert stats["min"] == pytest.approx(-90.0, abs=1e-6)


def test_draft_analysis_of_a_box_reads_zero_on_the_walls_parallel_to_the_pull(doc):
    h.metric(doc)
    box = h.box(doc, [10, 20, 30])
    stats = doc.command("draftanalysis", handles=[box], pull="x")["result"]["stats"]
    assert stats["median"] == pytest.approx(0.0, abs=1e-9)
    assert (stats["min"], stats["max"]) == pytest.approx((-90.0, 90.0), abs=1e-6)


def test_wall_thickness_of_a_plate_reads_the_plate_thickness(doc):
    h.metric(doc)
    t = 3.0
    plate = h.box(doc, [40, 40, t])
    stats = doc.command("wallthickness", handles=[plate])["result"]["stats"]
    assert stats["min"] == pytest.approx(t, abs=1e-6)
    assert stats["max"] == pytest.approx(40.0, abs=1e-6)


def test_wall_thickness_of_a_hollow_tube_reads_the_wall_between_its_radii(doc):
    h.metric(doc)
    outer, inner, height = 10.0, 8.0, 30.0
    a = h.handle_of(doc.command("cylinder", center=[0, 0, 0], radius=outer, height=height))
    b = h.handle_of(doc.command("cylinder", center=[0, 0, 0], radius=inner, height=height))
    reply = doc.command("boolop", op="cut", base=a, tools=[b])
    assert not reply.get("error"), reply.get("error")
    tube = doc.only("solidbody")["handle"]
    stats = doc.command("wallthickness", handles=[tube])["result"]["stats"]
    assert stats["min"] == pytest.approx(outer - inner, rel=1e-3)
    assert stats["median"] == pytest.approx(outer - inner, rel=1e-3)
