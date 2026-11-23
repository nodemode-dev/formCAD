import math

import pytest

TIGHT = dict(rel=1e-9, abs=1e-9)


@pytest.fixture()
def solids(kernel):
    made = []

    def box(origin, size):
        out = kernel.call("primitive", {"kind": "box", "origin": origin, "dx": size[0], "dy": size[1], "dz": size[2]})
        made.append(out["id"])
        return out["id"]

    def cylinder(origin, radius, height):
        out = kernel.call("primitive", {"kind": "cylinder", "origin": origin, "radius": radius, "height": height})
        made.append(out["id"])
        return out["id"]

    def combine(op, base, tool):
        out = kernel.call("boolean", {"op": op, "base": base, "tools": [tool]})
        made.append(out["id"])
        return out["summary"], kernel.call("mass_properties", {"id": out["id"]})

    box.cylinder = cylinder
    box.combine = combine
    yield box
    kernel.call("shape_free", {"ids": made})


@pytest.mark.kernel
@pytest.mark.parametrize("op, volume, box", [
    ("fuse", 1000.0 + 1000.0 - 6 * 5 * 4, [0, 0, 0, 16, 15, 14]),
    ("cut", 1000.0 - 6 * 5 * 4, [0, 0, 0, 10, 10, 10]),
    ("common", 6 * 5 * 4, [6, 5, 4, 10, 10, 10]),
])
def test_two_overlapping_boxes_combine_to_the_inclusion_exclusion_volume(solids, op, volume, box):
    a = solids([0, 0, 0], [10, 10, 10])
    b = solids([6, 5, 4], [10, 10, 10])
    summary, props = solids.combine(op, a, b)
    assert props["volume"] == pytest.approx(volume, **TIGHT)
    assert summary["bbox"] == pytest.approx(box, abs=1e-6)
    assert summary["solids"] == 1 and summary["valid"] and summary["closed"]


@pytest.mark.kernel
def test_two_boxes_touching_face_to_face_fuse_into_one_box_with_six_faces(solids):
    a = solids([0, 0, 0], [10, 10, 10])
    b = solids([10, 0, 0], [10, 10, 10])
    summary, props = solids.combine("fuse", a, b)
    assert (summary["solids"], summary["faces"], summary["edges"], summary["vertices"]) == (1, 6, 12, 8)
    assert props["volume"] == pytest.approx(2000.0, **TIGHT)
    assert props["area"] == pytest.approx(2 * (200 + 200 + 100), **TIGHT)


@pytest.mark.kernel
def test_two_separate_boxes_fuse_into_two_solids_whose_volumes_add(solids):
    a = solids([0, 0, 0], [10, 10, 10])
    b = solids([30, 0, 0], [5, 10, 10])
    summary, props = solids.combine("fuse", a, b)
    assert summary["solids"] == 2 and summary["faces"] == 12
    assert props["volume"] == pytest.approx(1500.0, **TIGHT)
    assert props["centroid"] == pytest.approx([(1000 * 5 + 500 * 32.5) / 1500, 5.0, 5.0], abs=1e-9)


@pytest.mark.kernel
@pytest.mark.parametrize("where", [[30, 0, 0], [10, 0, 0], [10, 10, 10]])
def test_the_intersection_of_bodies_that_do_not_overlap_is_refused_as_empty(kernel, solids, where):
    a = solids([0, 0, 0], [10, 10, 10])
    b = solids(where, [10, 10, 10])
    with pytest.raises(kernel.KernelError, match="empty"):
        solids.combine("common", a, b)


@pytest.mark.kernel
def test_a_cylinder_drilled_through_a_box_removes_its_closed_form_volume_and_lines_the_bore(solids):
    a = solids([0, 0, 0], [10, 10, 10])
    drill = solids.cylinder([5, 5, -1], 2.0, 12.0)
    summary, props = solids.combine("cut", a, drill)
    assert props["volume"] == pytest.approx(1000.0 - math.pi * 4.0 * 10.0, **TIGHT)
    assert props["area"] == pytest.approx(600.0 - 2 * math.pi * 4.0 + 2 * math.pi * 2.0 * 10.0, **TIGHT)
    assert props["centroid"] == pytest.approx([5.0, 5.0, 5.0], abs=1e-9)
    assert summary["faces"] == 7 and summary["solids"] == 1 and summary["valid"]


@pytest.mark.kernel
@pytest.mark.parametrize("op, volume", [("add", 8000 + 6000 - 4000), ("subtract", 8000 - 4000), ("common", 4000)])
def test_combining_two_drawn_boxes_in_a_document_gives_the_inclusion_exclusion_volume(doc, op, volume):
    doc.set_var("INSUNITS", 4)
    main = doc.command("box", corner=[0, 0, 0], size=[20, 20, 20])["result"]["handle"]
    tool = doc.command("box", corner=[0, 0, 0], size=[10, 20, 30])["result"]["handle"]
    out = doc.post("/bodies/combine", {"op": op, "handles": [main, tool]})
    picked = doc.post("/bodies/massprops", {"handles": [out["handle"]]})
    assert picked["volume"] == pytest.approx(volume, rel=1e-9)
    assert out["summary"]["solids"] == 1 and out["summary"]["valid"]
