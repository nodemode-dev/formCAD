import math

import pytest

from tests.solids import kit

PI = math.pi
TIGHT = dict(rel=1e-9, abs=1e-6)
INCH = 25.4


def last_id(doc):
    return kit.tree(doc)["features"][-1]["id"]


def cube(doc, size=20.0):
    kit.metric(doc)
    return kit.box(doc, size, size, size)


@pytest.mark.kernel
@pytest.mark.xfail(strict=True, reason="DEFECT: typing FEATEXTRUDE, the sketch name and a depth ends the command with no feature and no message, because the depth prompt result is checked for kind 'value' while a typed distance arrives as 'distance'; manual chapter 6 lists featextrude as the feature command that follows a sketch")
def test_typing_featextrude_with_a_sketch_and_a_depth_builds_the_extruded_solid(doc):
    kit.metric(doc)
    label = kit.rectangle(doc, 0, 0, 40, 20)
    doc.type("FEATEXTRUDE", label, "10")
    assert [f["type"] for f in kit.tree(doc)["features"]] == ["sketch", "extrude"]
    assert kit.volume(doc) == pytest.approx(8000.0, **TIGHT)


@pytest.mark.kernel
def test_a_sketched_rectangle_extruded_by_a_depth_is_a_box_of_that_size(doc):
    kit.metric(doc)
    fid = kit.extrude(doc, kit.rectangle(doc, 0, 0, 40, 20), 10)
    assert kit.status(doc, fid) == "ok"
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(8000.0, **TIGHT)
    assert props["area"] == pytest.approx(2 * (800 + 400 + 200), **TIGHT)
    assert props["centroid"] == pytest.approx([20.0, 10.0, 5.0], abs=1e-9)
    assert kit.extents(doc) == pytest.approx(([0.0, 0.0, 0.0], [40.0, 20.0, 10.0]), abs=1e-6)


@pytest.mark.kernel
def test_a_part_drawn_in_inches_reports_its_volume_in_cubic_millimetres_at_the_inch_scale(doc):
    kit.extrude(doc, kit.rectangle(doc, 0, 0, 2, 1), 0.5)
    props = kit.mass(doc)
    assert props["mm_per_unit"] == INCH
    assert props["doc"]["volume"] == pytest.approx(1.0, **TIGHT)
    assert props["volume"] == pytest.approx(INCH ** 3, **TIGHT)


@pytest.mark.kernel
@pytest.mark.parametrize("inner, outer, height", [(0.0, 8.0, 15.0), (5.0, 10.0, 20.0)])
def test_a_rectangle_revolved_about_the_sketch_y_axis_makes_a_cylinder_or_a_ring(doc, inner, outer, height):
    kit.metric(doc)
    out = doc.command("featrevolve", sketch=kit.rectangle(doc, inner, 0, outer, height))
    assert out["result"]["state"]["status"] == "ok"
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(PI * (outer ** 2 - inner ** 2) * height, **TIGHT)
    assert props["centroid"] == pytest.approx([0.0, height / 2, 0.0], abs=1e-9)


@pytest.mark.kernel
def test_a_through_hole_removes_a_cylinder_of_its_diameter_through_the_whole_part(doc):
    cube(doc)
    kit.sketch(doc, "XY", ("POINT", "10,10"), offset=20)
    hole = kit.add(doc, "hole", {"diameter": 6, "end": "through"}, {"sketch": {"id": last_id(doc)}})
    assert hole["state"]["status"] == "ok"
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(8000 - PI * 9 * 20, **TIGHT)
    assert props["area"] == pytest.approx(2400 - 2 * PI * 9 + 2 * PI * 3 * 20, **TIGHT)
    assert props["centroid"] == pytest.approx([10.0, 10.0, 10.0], abs=1e-9)


@pytest.mark.kernel
@pytest.mark.parametrize("radius", [1.0, 2.5])
def test_filleting_one_edge_of_a_cube_removes_the_closed_form_corner_volume(doc, radius):
    cube(doc)
    fillet = kit.add(doc, "fillet", {"radius": radius}, {"edges": [kit.edge_ref(0)]})
    assert fillet["state"]["status"] == "ok"
    assert kit.volume(doc) == pytest.approx(8000 - (1 - PI / 4) * radius ** 2 * 20, **TIGHT)


@pytest.mark.kernel
def test_chamfering_one_edge_of_a_cube_removes_a_triangular_prism(doc):
    cube(doc)
    kit.add(doc, "chamfer", {"distance": 3}, {"edges": [kit.edge_ref(0)]})
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(8000 - 3 * 3 / 2 * 20, **TIGHT)
    assert props["area"] == pytest.approx(2400 - 2 * 3 * 20 - 2 * 4.5 + 3 * math.sqrt(2) * 20, **TIGHT)


@pytest.mark.kernel
def test_shelling_a_cube_with_its_top_removed_leaves_the_outer_volume_minus_the_inner(doc):
    fid = cube(doc)
    shell = kit.add(doc, "shell", {"thickness": 2, "join": "intersection"}, {"faces": [kit.face_ref(fid, "cap:end")]})
    assert shell["state"]["status"] == "ok"
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(20 ** 3 - 16 * 16 * 18, **TIGHT)
    assert props["centroid"][2] == pytest.approx((8000 * 10 - 16 * 16 * 18 * 11) / (8000 - 16 * 16 * 18), abs=1e-9)


@pytest.mark.kernel
def test_drafting_the_four_sides_of_a_cube_turns_it_into_a_pyramid_frustum(doc):
    cube(doc)
    sides = []
    for i in range(6):
        key = doc.post("/part/refs", {"kind": "face", "index": i})["key"]
        if ":cap:" not in key:
            sides.append({"key": key})
    assert len(sides) == 4
    kit.add(doc, "draft", {"angle": 5, "pull": [0, 0, 1], "neutral": {"origin": [0, 0, 0], "normal": [0, 0, 1]}}, {"faces": sides})
    top = 20 - 2 * 20 * math.tan(math.radians(5))
    assert kit.volume(doc) == pytest.approx(20 / 3 * (400 + top * top + 20 * top), **TIGHT)
    lo, hi = kit.extents(doc)
    assert hi[2] - lo[2] == pytest.approx(20.0, abs=1e-6)


@pytest.mark.kernel
def test_a_linear_pattern_repeats_a_boss_at_its_spacing(doc):
    kit.metric(doc)
    kit.box(doc, 100, 20, 5)
    boss = kit.extrude(doc, kit.rectangle(doc, 0, 0, 10, 10, offset=5), 5)
    kit.add(doc, "pattern", {"pattern": "linear", "directions": [{"vector": [1, 0, 0], "count": 4, "spacing": 20}]}, {"seed": {"id": boss}})
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(10000 + 4 * 500, **TIGHT)
    xs = [5 + 20 * i for i in range(4)]
    assert props["centroid"][0] == pytest.approx((10000 * 50 + sum(500 * x for x in xs)) / 12000, abs=1e-9)


@pytest.mark.kernel
def test_a_circular_pattern_of_a_hole_cuts_six_equal_holes_around_the_axis(doc):
    kit.metric(doc)
    kit.extrude(doc, kit.sketch(doc, "XY", ("CIRCLE", "0,0", "30")), 10)
    kit.sketch(doc, "XY", ("POINT", "20,0"), offset=10)
    hole = kit.add(doc, "hole", {"diameter": 4, "end": "through"}, {"sketch": {"id": last_id(doc)}})
    kit.add(doc, "pattern", {"pattern": "circular", "op": "cut", "axis": {"origin": [0, 0, 0], "direction": [0, 0, 1]}, "count": 6, "angle": 360}, {"seed": {"id": hole["id"]}})
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(PI * 900 * 10 - 6 * PI * 4 * 10, **TIGHT)
    assert props["centroid"] == pytest.approx([0.0, 0.0, 5.0], abs=1e-9)


@pytest.mark.kernel
def test_mirroring_a_boss_across_a_plane_adds_its_twin_on_the_other_side(doc):
    kit.metric(doc)
    kit.box(doc, 100, 20, 5)
    boss = kit.extrude(doc, kit.rectangle(doc, 0, 0, 10, 10, offset=5), 5)
    kit.add(doc, "mirror", {"plane": {"origin": [50, 0, 0], "normal": [1, 0, 0]}}, {"seed": {"id": boss}})
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(10000 + 2 * 500, **TIGHT)
    assert props["centroid"][0] == pytest.approx(50.0, abs=1e-9)


@pytest.mark.kernel
def test_mirroring_the_whole_body_across_its_side_face_with_merge_doubles_it_into_one_body(doc):
    cube(doc)
    kit.add(doc, "mirror", {"mode": "body", "merge": True, "plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}})
    props = kit.mass(doc)["doc"]
    assert props["volume"] == pytest.approx(16000.0, **TIGHT)
    assert props["area"] == pytest.approx(2 * (800 + 800 + 400), **TIGHT)
    assert props["centroid"] == pytest.approx([0.0, 10.0, 10.0], abs=1e-9)
    assert kit.extents(doc) == pytest.approx(([-20.0, 0.0, 0.0], [20.0, 20.0, 20.0]), abs=1e-6)


@pytest.mark.kernel
@pytest.mark.xfail(strict=True, reason="DEFECT: a body mirror without Merge replaces the part body with its mirror image, so the original half disappears and the volume stays 8000; a mirror adds a reflected copy, and Merge only decides whether the copy is fused with the original, so the part should hold 16000 mm3 either way")
def test_mirroring_the_whole_body_without_merge_keeps_the_original_beside_its_mirror_image(doc):
    cube(doc)
    kit.add(doc, "mirror", {"mode": "body", "plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}})
    assert kit.volume(doc) == pytest.approx(16000.0, **TIGHT)
    assert kit.extents(doc) == pytest.approx(([-20.0, 0.0, 0.0], [20.0, 20.0, 20.0]), abs=1e-6)
