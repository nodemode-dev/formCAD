import os
import shutil

import numpy as np
import pytest

from tests.assembly.helpers import component, copy_fixture, copy_parts, flat, instances, matrix, pose, read_fcad, rot, transform_of
from tests.support.engine import Refused

COMPONENT_FIELDS = {"name", "id", "n", "label", "type", "ref", "embedded", "transform", "visible", "suppressed", "fixed", "config", "props", "sig", "cache", "search", "note"}


@pytest.fixture()
def demo(docs, fixtures, tmp_path):
    return docs.open(copy_fixture(fixtures, tmp_path, "assembly.fcad", "assembly"))


@pytest.fixture()
def built(engine, fixtures, tmp_path):
    copy_parts(fixtures, tmp_path / "parts")
    a = engine.new_doc("", "assembly")
    a.save(tmp_path / "top.fcad")
    a.post("/assembly/components", {"path": str(tmp_path / "parts" / "base.fcad"), "label": "Plate"})
    a.post("/assembly/components", {"path": str(tmp_path / "parts" / "pin.fcad"), "label": "Dowel", "transform": flat(pose(rot([0, 0, 1], 30.0), (25.0, 30.0, 10.0)))})
    yield a, tmp_path
    engine.raw("POST", a.url("/close"), json={"force": True})


def flat_bom(doc):
    return {r["part_number"]: r for r in doc.get("/assembly/bom", mode="flat")["rows"]}


def test_the_assembly_fixture_loads_to_its_stated_components_patterns_and_configurations(demo):
    listing = demo.get("/assembly")
    labels = {c["id"]: (c["label"], c["type"], c["status"]["status"]) for c in listing["components"]}
    assert labels == {"C1": ("Base", "part", "loaded"), "C2": ("Pin", "part", "loaded"), "C3": ("Clamp", "assembly", "loaded")}
    assert next(c for c in listing["components"] if c["id"] == "C1")["fixed"] is True
    assert {p["kind"]: p["seed"] for p in listing["patterns"]} == {"feature": "C2", "circular": "C3"}
    assert [c["name"] for c in listing["configs"]["configs"]] == ["Default", "Light", "Wide base"]


def test_the_feature_pattern_puts_one_pin_in_each_hole_of_the_base(demo):
    pins = [i for i in instances(demo).values() if i["cid"] == "C2" and i["depth"] == 0]
    sites = sorted((round(matrix(i["world"])[0, 3], 6), round(matrix(i["world"])[1, 3], 6)) for i in pins)
    assert sites == sorted([(25.0, 30.0), (75.0, 30.0), (50.0, 5.0), (50.0, 55.0)])


def test_the_circular_pattern_copy_is_the_seed_turned_half_a_turn_about_the_pattern_axis(demo):
    found = instances(demo)
    seed = matrix(found["C3"]["world"])
    turn = np.eye(4)
    turn[:3, :3] = rot([0, 0, 1], 180.0)
    turn[:3, 3] = np.array([50.0, 30.0, 0.0]) - turn[:3, :3] @ np.array([50.0, 30.0, 0.0])
    assert np.allclose(matrix(found["C3#1"]["world"]), turn @ seed, atol=1e-9)


def test_a_nested_component_world_transform_is_the_parent_times_its_own(demo):
    found = instances(demo)
    nested = [i for i in found.values() if i["depth"] == 1]
    assert len(nested) == 8
    for i in nested:
        parent = found[i["key"].rsplit("/", 1)[0]]
        assert np.allclose(matrix(i["world"]), matrix(parent["world"]) @ matrix(i["local"]), atol=1e-9)


def test_the_flat_bill_of_materials_counts_every_instance_through_the_levels(demo):
    rows = flat_bom(demo)
    assert {k: r["qty"] for k, r in rows.items()} == {"BP-100": 1, "DP-300": 4, "RD-410": 4, "CP-020": 4}
    assert sorted(r["find"] for r in rows.values()) == [1, 2, 4, 5]


def test_the_light_configuration_drops_the_clamp_and_default_brings_it_back(demo):
    demo.post("/assembly/configs/Light/activate")
    assert set(flat_bom(demo)) == {"BP-100", "DP-300"}
    demo.post("/assembly/configs/Default/activate")
    assert {k: r["qty"] for k, r in flat_bom(demo).items()} == {"BP-100": 1, "DP-300": 4, "RD-410": 4, "CP-020": 4}


def test_the_saved_assembly_file_follows_the_schema(built):
    a, folder = built
    a.save()
    manifest, document = read_fcad(folder / "top.fcad")
    assert manifest["kind"] == "assembly"
    head = document["header"]["ASSEMBLY"]
    assert head["schema"] == 1 and head["next"] == 3
    comps = {c["id"]: c for c in document["tables"]["components"]}
    assert set(comps) == {"C1", "C2"}
    for cid, c in comps.items():
        assert COMPONENT_FIELDS <= set(c) and c["name"] == cid and c["n"] == int(cid[1:])
        m = matrix(c["transform"])
        assert np.allclose(m[3], (0, 0, 0, 1)) and np.allclose(m[:3, :3] @ m[:3, :3].T, np.eye(3), atol=1e-9)
        assert np.linalg.det(m[:3, :3]) == pytest.approx(1.0, abs=1e-9)
    assert comps["C1"]["ref"]["path"] == "parts/base.fcad" and comps["C2"]["ref"]["path"] == "parts/pin.fcad"
    assert comps["C1"]["fixed"] is True and comps["C2"]["fixed"] is False
    assert np.allclose(matrix(comps["C2"]["transform"])[:3, 3], (25, 30, 10))


def test_a_scaling_transform_is_refused_and_the_component_stays_put(built):
    a, _ = built
    before = transform_of(a, "C2")
    with pytest.raises(Refused) as err:
        a.post("/assembly/components/C2/transform", {"matrix": [2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]})
    assert err.value.status == 400
    assert np.array_equal(transform_of(a, "C2"), before)


def test_a_linear_pattern_places_copies_at_the_spacing_and_counts_in_the_bom(built):
    a, _ = built
    a.post("/assembly/patterns", {"kind": "linear", "seed": "C2", "params": {"dir1": [1, 0, 0], "spacing1": 20.0, "count1": 3}})
    found = instances(a)
    seed = matrix(found["C2"]["world"])
    for k in (1, 2):
        expect = seed.copy()
        expect[0, 3] += 20.0 * k
        assert np.allclose(matrix(found["C2#%d" % k]["world"]), expect, atol=1e-9)
    assert "C2#3" not in found
    assert flat_bom(a)["DP-300"]["qty"] == 3


def test_replacing_a_part_keeps_its_transform_and_name(built):
    a, folder = built
    before = component(a, "C2")
    a.post("/assembly/components/C2/replace", {"path": str(folder / "parts" / "rod.fcad")})
    after = component(a, "C2")
    assert after["ref"]["path"] == "parts/rod.fcad" and after["label"] == "Dowel"
    assert after["transform"] == before["transform"]
    assert "RD-410" in flat_bom(a) and "DP-300" not in flat_bom(a)


def test_save_and_reopen_keeps_components_transforms_patterns_and_mates(built, docs):
    a, folder = built
    a.post("/assembly/patterns", {"kind": "circular", "seed": "C2", "params": {"axis_origin": [50, 30, 0], "axis_dir": [0, 0, 1], "count": 4, "angle": 360.0}})
    a.post("/mates", {"kind": "distance", "refs": [{"comp": "C1", "geom": {"kind": "plane", "p": [0, 0, 10], "d": [0, 0, 1]}}, {"comp": "C2", "geom": {"kind": "plane", "p": [0, 0, 0], "d": [0, 0, -1]}}], "value": 4.0})
    before = instances(a)
    a.save()
    b = docs.open(folder / "top.fcad")
    after = instances(b)
    assert set(after) == set(before) and len(after) == 5
    for key, inst in before.items():
        assert np.allclose(matrix(after[key]["world"]), matrix(inst["world"]), atol=1e-12)
        assert after[key]["status"] == "loaded"
    mates = b.get("/mates")["mates"]
    assert [(m["kind"], m["value"]) for m in mates] == [("distance", 4.0)]
    assert b.get("/mates/status")["components"]["C2"]["dof"] == 3


def test_a_missing_part_file_is_reported_and_the_rest_still_loads(built, docs):
    a, folder = built
    a.save()
    os.remove(folder / "parts" / "pin.fcad")
    b = docs.open(folder / "top.fcad")
    status = {c["id"]: c["status"] for c in b.get("/assembly")["components"]}
    assert status["C2"]["status"] == "missing" and status["C2"]["reason"] == "notfound"
    assert status["C2"]["stale"] is True and status["C2"]["source"] == "cache"
    assert status["C1"]["status"] == "loaded"
    assert b.get("/assembly")["counts"]["missing"] == 1


def test_a_part_moved_into_a_search_folder_is_found_there(built, docs):
    a, folder = built
    a.save()
    (folder / "library").mkdir()
    shutil.move(folder / "parts" / "pin.fcad", folder / "library" / "pin.fcad")
    b = docs.open(folder / "top.fcad")
    b.engine.put(b.url("/assembly/settings"), {"search_folders": ["library"]})
    status = next(c for c in b.post("/assembly/refresh")["components"] if c["id"] == "C2")["status"]
    assert status["status"] == "loaded" and status["found_by"] == "search_folders"


def test_an_assembly_cannot_be_inserted_into_itself(built):
    a, folder = built
    a.save()
    with pytest.raises(Refused) as err:
        a.post("/assembly/components", {"path": str(folder / "top.fcad")})
    assert err.value.status == 400
    assert len(a.get("/assembly")["components"]) == 2
