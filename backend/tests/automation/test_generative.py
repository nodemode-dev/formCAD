import base64
import time

import numpy as np
import pytest

DESIGN, PRESERVED, EMPTY = 0, 1, 2


@pytest.fixture()
def bracket(docs, fixtures):
    return docs.open(fixtures / "gen/bracket.fcad")


def voxels(doc, oid: str) -> tuple:
    v = doc.get("/gen/studies/S1/outcomes/%s/voxels" % oid)
    solid = np.frombuffer(base64.b64decode(v["solid_u8"]), np.uint8)
    cls = np.frombuffer(base64.b64decode(v["class_u8"]), np.uint8)
    return solid, cls


def check_outcome(doc, summary: dict, o: dict) -> None:
    solid, cls = voxels(doc, o["id"])
    grid = summary["grid"]
    assert solid.size == cls.size == grid["nx"] * grid["ny"] * grid["nz"]
    assert solid[cls == PRESERVED].all(), "a preserved cell is empty"
    assert not solid[cls == EMPTY].any(), "an obstacle cell is filled"
    filled = int(solid.sum())
    cell = grid["h"] ** 3
    assert o["voxel_mass_kg"] == pytest.approx(filled * cell * summary["material"]["rho_kg_mm3"], rel=1e-9)
    design = int((cls != EMPTY).sum())
    assert o["volume_fraction"] == pytest.approx(filled / design, rel=1e-9)
    assert o["mesh_volume_mm3"] == pytest.approx(filled * cell, rel=0.02)
    assert o["safety_factor"] == pytest.approx(summary["material"]["yield_mpa"] / o["peak_stress_mpa"], rel=1e-9)
    assert o["meets_safety_factor"] == (o["safety_factor"] >= summary["required_safety_factor"])


def test_every_stored_outcome_keeps_its_preserved_cells_avoids_its_obstacles_and_weighs_what_its_cells_weigh(bracket):
    summary = bracket.get("/gen/studies/S1/outcomes", thumbnails=False)
    assert [o["method"] for o in summary["outcomes"]] == ["additive", "milling3", "cutting", "casting"]
    for o in summary["outcomes"]:
        check_outcome(bracket, summary, o)


def test_every_stored_outcome_meets_the_required_safety_factor_and_is_lighter_than_the_block(bracket):
    summary = bracket.get("/gen/studies/S1/outcomes", thumbnails=False)
    block_kg = 90 * 30 * 60 * summary["material"]["rho_kg_mm3"]
    assert block_kg == pytest.approx(0.4374, rel=1e-9)
    for o in summary["outcomes"]:
        assert o["safety_factor"] >= 2.0 and o["meets_safety_factor"] is True
        assert o["peak_stress_mpa"] <= summary["stress_limit_mpa"]
        assert o["mass_kg"] < summary["baseline"]["mass_kg"] < block_kg


def test_a_fresh_short_run_keeps_the_regions_and_reports_its_safety_factor_honestly(bracket):
    started = bracket.post("/gen/studies/S1/run", {"options": {"methods": [{"method": "additive", "direction": "+z"}], "passes": 1, "iterations": 15}})
    job = started["job"]["job"]
    end = time.monotonic() + 120
    while True:
        view = bracket.get("/gen/jobs/%s" % job)["job"]
        if view["state"] in ("done", "failed", "cancelled") or time.monotonic() > end:
            break
        time.sleep(0.5)
    assert view["state"] == "done", view
    summary = bracket.get("/gen/studies/S1/outcomes", thumbnails=False)
    assert [o["method"] for o in summary["outcomes"]] == ["additive"]
    check_outcome(bracket, summary, summary["outcomes"][0])
