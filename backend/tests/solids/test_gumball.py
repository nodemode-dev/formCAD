import math

import pytest

from tests.solids import kit
from tests.support.engine import Refused

TIGHT = dict(rel=1e-9, abs=1e-6)
SIZE = (10.0, 20.0, 30.0)
VOLUME = 6000.0


def drawn_box(doc):
    kit.metric(doc)
    return doc.command("box", corner=[0, 0, 0], size=list(SIZE))["result"]["handle"]


def apply(doc, handle, op, **extra):
    return doc.post("/gumball/apply", {"op": op, "handles": [handle], **extra})


def body(doc, handle):
    return [b for b in kit.bodies(doc) if b["handle"] == handle][0]


def picked(doc, handle):
    return doc.post("/bodies/massprops", {"handles": [handle]})["doc"]


@pytest.mark.kernel
def test_moving_a_body_by_a_vector_shifts_its_centroid_and_extents_by_that_vector(doc):
    h = drawn_box(doc)
    apply(doc, h, {"type": "move", "vector": [5, -6, 7]})
    props = picked(doc, h)
    assert props["volume"] == pytest.approx(VOLUME, **TIGHT)
    assert props["centroid"] == pytest.approx([10.0, 4.0, 22.0], abs=1e-9)
    assert body(doc, h)["summary"]["bbox"] == pytest.approx([5, -6, 7, 15, 14, 37], abs=1e-6)


@pytest.mark.kernel
def test_rotating_a_body_a_quarter_turn_about_the_z_axis_turns_its_centroid_and_swaps_its_spans(doc):
    h = drawn_box(doc)
    apply(doc, h, {"type": "rotate", "axis": [0, 0, 1], "degrees": 90, "origin": [0, 0, 0]})
    props = picked(doc, h)
    assert props["volume"] == pytest.approx(VOLUME, **TIGHT)
    assert props["centroid"] == pytest.approx([-10.0, 5.0, 15.0], abs=1e-9)
    assert body(doc, h)["summary"]["bbox"] == pytest.approx([-20, 0, 0, 0, 10, 30], abs=1e-6)


@pytest.mark.kernel
def test_rotating_about_the_gumball_centre_keeps_the_centroid_in_place(doc):
    h = drawn_box(doc)
    apply(doc, h, {"type": "rotate", "axis": "x", "degrees": 30})
    props = picked(doc, h)
    assert props["centroid"] == pytest.approx([5.0, 10.0, 15.0], abs=1e-9)
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    lo, hi = kit.extents(doc)
    assert hi[1] - lo[1] == pytest.approx(SIZE[1] * c + SIZE[2] * s, abs=1e-6)
    assert hi[2] - lo[2] == pytest.approx(SIZE[1] * s + SIZE[2] * c, abs=1e-6)


@pytest.mark.kernel
def test_scaling_a_body_by_two_about_the_origin_multiplies_volume_by_eight_and_doubles_the_centroid(doc):
    h = drawn_box(doc)
    apply(doc, h, {"type": "scale", "factor": 2, "origin": [0, 0, 0]})
    props = picked(doc, h)
    assert props["volume"] == pytest.approx(8 * VOLUME, **TIGHT)
    assert props["area"] == pytest.approx(4 * 2200.0, **TIGHT)
    assert props["centroid"] == pytest.approx([10.0, 20.0, 30.0], abs=1e-9)


@pytest.mark.kernel
def test_scaling_by_different_factors_per_axis_multiplies_the_volume_by_their_product(doc):
    h = drawn_box(doc)
    apply(doc, h, {"type": "scale", "factors": [1, 2, 3], "origin": [0, 0, 0]})
    assert picked(doc, h)["volume"] == pytest.approx(6 * VOLUME, rel=1e-7)
    assert body(doc, h)["summary"]["bbox"] == pytest.approx([0, 0, 0, 10, 40, 90], abs=1e-5)


@pytest.mark.kernel
def test_a_move_then_the_opposite_move_and_undo_both_return_the_body_to_where_it_was(doc):
    h = drawn_box(doc)
    apply(doc, h, {"type": "move", "vector": [3.25, 4.5, -8]})
    apply(doc, h, {"type": "move", "vector": [-3.25, -4.5, 8]})
    assert picked(doc, h)["centroid"] == pytest.approx([5.0, 10.0, 15.0], abs=1e-9)
    apply(doc, h, {"type": "rotate", "axis": [0, 0, 1], "degrees": 37, "origin": [0, 0, 0]})
    doc.undo()
    assert body(doc, h)["summary"]["bbox"] == pytest.approx([0, 0, 0, 10, 20, 30], abs=1e-6)


@pytest.mark.kernel
@pytest.mark.parametrize("op", [{"type": "scale", "factor": 0}, {"type": "scale", "factors": [1, -1, 1]}, {"type": "spin"}])
def test_a_scale_of_zero_or_a_negative_factor_or_an_unknown_operation_is_refused_and_the_body_is_unchanged(doc, op):
    h = drawn_box(doc)
    with pytest.raises(Refused) as refused:
        apply(doc, h, op)
    assert refused.value.status == 400
    assert picked(doc, h)["volume"] == pytest.approx(VOLUME, **TIGHT)
    assert body(doc, h)["summary"]["bbox"] == pytest.approx([0, 0, 0, 10, 20, 30], abs=1e-6)
