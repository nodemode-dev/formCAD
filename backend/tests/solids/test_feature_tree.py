import math

import pytest

from tests.solids import kit
from tests.support.engine import Refused

PI = math.pi
TIGHT = dict(rel=1e-9, abs=1e-6)
CORNER = 1 - PI / 4


def edit(doc, fid, **body):
    return doc.engine.patch(doc.url("/part/features/%s" % fid), body)


def suppress(doc, fid, flag=True):
    return doc.post("/part/features/%s/suppress" % fid, {"suppressed": flag})


def filleted_cube(doc, depth=20.0, radius=2.0):
    kit.metric(doc)
    base = kit.box(doc, 20, 20, depth)
    fillet = kit.add(doc, "fillet", {"radius": radius}, {"edges": [kit.edge_ref(0)]})
    return base, fillet["id"]


def order(doc):
    return [f["id"] for f in kit.tree(doc)["features"]]


@pytest.mark.kernel
def test_editing_the_depth_of_the_first_extrude_rebuilds_the_later_fillet_on_the_taller_edge(doc):
    base, fillet = filleted_cube(doc)
    assert kit.volume(doc) == pytest.approx(8000 - CORNER * 4 * 20, **TIGHT)
    out = edit(doc, base, params={"depth1": 30})
    assert out["state"]["status"] == "ok" and kit.status(doc, fillet) == "ok"
    assert kit.volume(doc) == pytest.approx(12000 - CORNER * 4 * 30, **TIGHT)


@pytest.mark.kernel
def test_a_hole_sketched_on_the_top_face_follows_that_face_when_the_extrude_depth_changes(doc):
    kit.metric(doc)
    base = kit.extrude(doc, kit.rectangle(doc, 0, 0, 20, 20), 10)
    kit.sketch(doc, None, ("POINT", "10,10"), face=kit.face_ref(base, "cap:end"))
    hole = kit.add(doc, "hole", {"diameter": 4, "end": "blind", "depth": 6}, {"sketch": {"id": kit.tree(doc)["features"][-1]["id"]}})
    assert kit.volume(doc) == pytest.approx(4000 - PI * 4 * 6, **TIGHT)
    assert kit.centroid(doc)[2] == pytest.approx((4000 * 5 - PI * 4 * 6 * 7) / (4000 - PI * 4 * 6), abs=1e-9)
    edit(doc, base, params={"depth1": 25})
    assert kit.status(doc, hole["id"]) == "ok"
    assert kit.volume(doc) == pytest.approx(10000 - PI * 4 * 6, **TIGHT)
    assert kit.centroid(doc)[2] == pytest.approx((10000 * 12.5 - PI * 4 * 6 * 22) / (10000 - PI * 4 * 6), abs=1e-9)


@pytest.mark.kernel
def test_suppressing_a_fillet_restores_the_sharp_cube_and_unsuppressing_rounds_it_again(doc):
    _base, fillet = filleted_cube(doc)
    suppress(doc, fillet)
    assert kit.feature(doc, fillet)["suppressed"] is True and kit.status(doc, fillet) == "suppressed"
    assert kit.volume(doc) == pytest.approx(8000.0, **TIGHT)
    suppress(doc, fillet, False)
    assert kit.status(doc, fillet) == "ok"
    assert kit.volume(doc) == pytest.approx(8000 - CORNER * 4 * 20, **TIGHT)


@pytest.mark.kernel
def test_moving_an_independent_fillet_after_a_new_boss_keeps_the_same_solid(doc):
    _base, fillet = filleted_cube(doc)
    boss = kit.extrude(doc, kit.rectangle(doc, 10, 10, 15, 15, offset=20), 5)
    before = kit.volume(doc)
    assert before == pytest.approx(8000 - CORNER * 4 * 20 + 125, **TIGHT)
    out = doc.post("/part/reorder", {"id": fillet, "after": boss})
    assert out["order"][-1] == fillet and order(doc)[-1] == fillet
    assert kit.volume(doc) == pytest.approx(before, **TIGHT)


@pytest.mark.kernel
def test_moving_a_fillet_before_the_extrude_it_rounds_is_refused_and_the_order_stays(doc):
    base, fillet = filleted_cube(doc)
    was = order(doc)
    with pytest.raises(Refused) as refused:
        doc.post("/part/reorder", {"id": fillet, "after": None})
    assert refused.value.status == 400 and "depends on" in refused.value.body
    assert order(doc) == was
    assert kit.volume(doc) == pytest.approx(8000 - CORNER * 4 * 20, **TIGHT)


@pytest.mark.kernel
def test_a_fillet_too_large_for_its_edge_is_reported_and_the_part_keeps_its_last_good_solid(doc):
    _base, fillet = filleted_cube(doc)
    good = kit.volume(doc)
    bad = kit.add(doc, "fillet", {"radius": 50}, {"edges": [kit.edge_ref(3)]})
    assert bad["state"]["status"] == "error"
    assert "radius" in bad["state"]["message"]
    assert kit.status(doc, bad["id"]) == "error"
    assert kit.volume(doc) == pytest.approx(good, **TIGHT)
    assert kit.bodies(doc)[0]["summary"]["valid"]


@pytest.mark.kernel
def test_an_edit_that_breaks_a_feature_reports_it_and_fixing_the_edit_brings_the_feature_back(doc):
    _base, fillet = filleted_cube(doc)
    edit(doc, fillet, params={"radius": 40})
    assert kit.status(doc, fillet) == "error"
    assert kit.volume(doc) == pytest.approx(8000.0, **TIGHT)
    edit(doc, fillet, params={"radius": 3})
    assert kit.status(doc, fillet) == "ok"
    assert kit.volume(doc) == pytest.approx(8000 - CORNER * 9 * 20, **TIGHT)


@pytest.mark.kernel
def test_undo_removes_the_last_feature_and_redo_brings_back_the_same_solid(doc):
    _base, fillet = filleted_cube(doc)
    rounded = kit.mass(doc)["doc"]
    doc.undo()
    assert fillet not in order(doc)
    assert kit.volume(doc) == pytest.approx(8000.0, **TIGHT)
    doc.redo()
    assert order(doc)[-1] == fillet
    again = kit.mass(doc)["doc"]
    assert again["volume"] == pytest.approx(rounded["volume"], **TIGHT)
    assert again["centroid"] == pytest.approx(rounded["centroid"], abs=1e-9)


@pytest.mark.kernel
def test_rolling_back_before_the_fillet_shows_the_sharp_cube_and_rolling_forward_restores_it(doc):
    base, fillet = filleted_cube(doc)
    doc.post("/part/rollback", {"to": base})
    assert kit.feature(doc, fillet)["rolled"] is True
    assert kit.volume(doc) == pytest.approx(8000.0, **TIGHT)
    doc.post("/part/rollback", {"to": None})
    assert kit.volume(doc) == pytest.approx(8000 - CORNER * 4 * 20, **TIGHT)


@pytest.mark.kernel
def test_a_part_saved_and_opened_again_rebuilds_to_the_same_solid(doc, docs, tmp_path):
    _base, _fillet = filleted_cube(doc)
    kit.sketch(doc, "XY", ("POINT", "10,10"), offset=20)
    kit.add(doc, "hole", {"diameter": 5, "end": "through"}, {"sketch": {"id": kit.tree(doc)["features"][-1]["id"]}})
    before = kit.mass(doc)["doc"]
    doc.save(tmp_path / "part.fcad")
    again = docs.open(tmp_path / "part.fcad")
    assert [f["type"] for f in kit.tree(again)["features"]] == ["sketch", "extrude", "fillet", "sketch", "hole"]
    after = kit.mass(again)["doc"]
    assert after["volume"] == pytest.approx(before["volume"], **TIGHT)
    assert after["volume"] == pytest.approx(8000 - CORNER * 4 * 20 - PI * 6.25 * 20, **TIGHT)
    assert after["centroid"] == pytest.approx(before["centroid"], abs=1e-9)
