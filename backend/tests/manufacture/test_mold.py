import pytest

pytestmark = pytest.mark.kernel


def test_core_and_cavity_of_a_box_fill_the_block_less_the_part(doc, kernel):
    doc.set_var("INSUNITS", 4)
    doc.command("box", corner=[-15, -10, -5], size=[30, 20, 10])
    doc.put("/mold/settings", {"margin": 10.0, "cavity_margin": 10.0, "core_margin": 10.0, "height": 0.0})
    res = doc.post("/mold/split", {"keep_block": True})
    sx, sy, sz = res["block_size"]
    assert (sx, sy) == pytest.approx((50.0, 40.0), abs=1e-6)
    block = sx * sy * sz
    part = 30 * 20 * 10
    core, cavity = res["pieces"]["core"]["volume"], res["pieces"]["cavity"]["volume"]
    assert res["pieces"]["block"]["volume"] == pytest.approx(block, rel=1e-6)
    assert core + cavity == pytest.approx(block - part, rel=1e-6)
    assert core == pytest.approx(cavity, rel=1e-6)
    assert res["ok"] and res["pieces"]["core"]["solids"] == 1 and res["pieces"]["cavity"]["solids"] == 1


def test_the_mold_fixture_splits_again_into_the_volumes_its_readme_states(docs, fixtures, kernel):
    doc = docs.open(fixtures / "mold" / "part.fcad")
    res = doc.post("/mold/split", {"keep_block": True})
    assert res["height"] == pytest.approx(0.0, abs=1e-9)
    assert res["pieces"]["block"]["volume"] == pytest.approx(160740.835, abs=0.01)
    assert res["pieces"]["core"]["volume"] == pytest.approx(70948.231, abs=0.01)
    assert res["pieces"]["cavity"]["volume"] == pytest.approx(70948.231, abs=0.01)
    assert len(res["shut_offs"]) == 2
    assert res["pieces"]["core"]["volume"] + res["pieces"]["cavity"]["volume"] + 18844.373 == pytest.approx(160740.835, abs=0.01)
