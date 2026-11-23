import math

import pytest

from tests.interchange.common import cmd, metric, ok

pytestmark = pytest.mark.kernel

BLOCK = 10 * 20 * 30
PIN = math.pi * 5 ** 2 * 40
PLATE = 40 * 30 * 10 - math.pi * 6 ** 2 * 10
REL = 1e-9


def bodies(doc):
    return [e for e in doc.entities() if e["kind"] == "solidbody"]


def mass(doc, e):
    return doc.get("/solids/%d/massprops" % e["handle"])


def box_and_pin(doc):
    metric(doc)
    ok(doc, "box", corner=[0, 0, 0], size=[10, 20, 30])
    ok(doc, "cylinder", center=[100, 0, 0], radius=5, height=40)
    return doc


@pytest.mark.parametrize("ext,schema", [("step", "ap203"), ("step", "ap214"), ("step", "ap242"), ("iges", "")])
def test_a_box_and_a_cylinder_read_back_with_their_volumes_faces_and_centroids(docs, tmp_path, ext, schema):
    src = box_and_pin(docs())
    path = tmp_path / ("solids-%s.%s" % (schema or "x", ext))
    ok(src, "export", path=str(path), options={"schema": schema} if schema else {})
    back = metric(docs())
    ok(back, "import", path=str(path))
    got = sorted(bodies(back), key=lambda e: e["summary"]["faces"])
    assert [(e["summary"]["faces"], e["summary"]["valid"], e["summary"]["closed"]) for e in got] == [(3, True, True), (6, True, True)]
    pin, box = mass(back, got[0]), mass(back, got[1])
    assert box["volume"] == pytest.approx(BLOCK, rel=REL) and pin["volume"] == pytest.approx(PIN, rel=1e-6)
    assert box["centroid"] == pytest.approx([5, 10, 15], abs=1e-9) and pin["centroid"] == pytest.approx([100, 0, 20], abs=1e-9)


def test_a_step_file_written_in_inches_says_so_and_reads_back_into_millimetres_at_full_size(docs, tmp_path):
    src = box_and_pin(docs())
    path = tmp_path / "inch.step"
    ok(src, "export", path=str(path), options={"unit": "in"})
    text = path.read_text()
    assert "INCH" in text.upper()
    back = metric(docs())
    out = ok(back, "import", path=str(path))
    assert any("25.4" in w for w in out["report"]["warnings"])
    vols = sorted(mass(back, e)["volume"] for e in bodies(back))
    assert vols == pytest.approx(sorted([BLOCK, PIN]), rel=1e-6)


def test_a_millimetre_step_file_read_into_an_inch_drawing_is_converted_to_inches(docs, tmp_path):
    src = box_and_pin(docs())
    path = tmp_path / "to-inch.step"
    ok(src, "export", path=str(path))
    back = docs()
    back.set_var("INSUNITS", 1)
    ok(back, "import", path=str(path))
    box = [e for e in bodies(back) if e["summary"]["faces"] == 6][0]
    props = mass(back, box)
    assert props["volume"] == pytest.approx(BLOCK / 25.4 ** 3, rel=1e-9)
    assert props["centroid"] == pytest.approx([5 / 25.4, 10 / 25.4, 15 / 25.4], abs=1e-9)


@pytest.mark.parametrize("schema,declared", [("ap203", "CONFIG_CONTROL_DESIGN"), ("ap214", "AUTOMOTIVE_DESIGN"), ("ap242", "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING")])
def test_an_assembly_written_to_step_declares_its_schema_and_keeps_names_colours_layers_paths_and_volumes(docs, fixtures, tmp_path, schema, declared):
    src = docs.open(fixtures / "interchange" / "assembly-colours.fcad")
    path = tmp_path / ("asm-%s.step" % schema)
    ok(src, "export", path=str(path), options={"schema": schema})
    header = path.read_text().split("ENDSEC;")[0]
    assert "FILE_SCHEMA" in header and declared in header
    back = metric(docs())
    ok(back, "import", path=str(path))

    def table(doc):
        return sorted((e["name"], e["layer"], tuple(round(c, 6) for c in e["rgb"]), tuple(e["source"].get("path") or []), round(mass(doc, e)["volume"], 6)) for e in bodies(doc))

    want = table(src)
    assert len(want) == 4 and all(row[2] for row in want)
    assert table(back) == want


ASSEMBLY = {"Block": ("PARTS", "Machine", BLOCK, 0), "Pin": ("PARTS", "Machine", PIN, 2), "Plate": ("BASE", "Base", PLATE, 1)}


@pytest.mark.parametrize("name", ["assembly-colours-ap203.step", "assembly-colours-ap214.step", "assembly-colours-ap242.step", "assembly-colours-inch.step"])
def test_the_coloured_assembly_fixtures_import_to_their_stated_bodies(docs, fixtures, name):
    doc = metric(docs())
    ok(doc, "import", path=str(fixtures / "interchange" / name))
    found = {e["name"]: e for e in bodies(doc)}
    assert sorted(found) == ["Block", "Pin", "Plate", "Vase"]
    for body, (lay, asm, vol, channel) in ASSEMBLY.items():
        e = found[body]
        assert (e["layer"], e["source"]["path"]) == (lay, [asm])
        assert e["rgb"].index(max(e["rgb"])) == channel
        assert mass(doc, e)["volume"] == pytest.approx(vol, rel=1e-6)
    assert found["Vase"]["layer"] == "FREEFORM" and found["Vase"]["source"]["path"] == ["Base"]
    assert all(e["summary"]["valid"] and e["summary"]["closed"] for e in found.values())
    assert mass(doc, found["Pin"])["centroid"][0] - mass(doc, found["Block"])["centroid"][0] == pytest.approx(95.0, abs=1e-6)


def test_the_bracket_fixture_imports_as_one_named_coloured_solid_of_its_stated_volume(docs, fixtures):
    doc = metric(docs())
    ok(doc, "import", path=str(fixtures / "bracket.step"))
    (e,) = bodies(doc)
    assert e["name"] == "L bracket" and e["summary"]["faces"] == 11 and e["summary"]["valid"] and e["summary"]["closed"]
    assert e["rgb"] == pytest.approx([0.62, 0.66, 0.72], abs=1e-6)
    assert mass(doc, e)["volume"] == pytest.approx(46383.0, rel=1e-6)


@pytest.mark.parametrize("name", ["part-pmi.step", "part-pmi-inch.step"])
def test_the_pmi_plate_fixtures_import_one_plate_with_its_nine_pmi_items(docs, fixtures, name):
    doc = metric(docs())
    out = ok(doc, "import", path=str(fixtures / "interchange" / name))
    (e,) = bodies(doc)
    assert e["name"] == "Plate" and e["summary"]["valid"] and e["summary"]["closed"]
    assert mass(doc, e)["volume"] == pytest.approx(PLATE, rel=1e-6)
    assert out["added"]["pmi"] == 9


def test_the_clamp_assembly_fixture_imports_its_thirteen_component_instances_as_valid_solids(docs, fixtures):
    doc = metric(docs())
    out = ok(doc, "import", path=str(fixtures / "interchange" / "assembly-clamp.step"))
    found = bodies(doc)
    assert out["added"]["objects"] == 13 and len(found) == 13
    assert all(e["summary"]["valid"] and e["summary"]["closed"] and mass(doc, e)["volume"] > 0 for e in found)
    assert all(e["source"].get("path") for e in found)


@pytest.mark.parametrize("name,volumes", [("assembly-colours.iges", None), ("part-pmi.iges", [PLATE])])
def test_the_iges_fixtures_import_to_valid_closed_solids_of_the_stated_volumes(docs, fixtures, name, volumes):
    doc = metric(docs())
    out = cmd(doc, "import", path=str(fixtures / "interchange" / name))
    assert not out["error"]
    found = bodies(doc)
    assert all(e["summary"]["valid"] and e["summary"]["closed"] for e in found)
    vols = sorted(mass(doc, e)["volume"] for e in found)
    if volumes is None:
        assert len(vols) == 4
        assert [v for v in vols if abs(v - BLOCK) < 1e-6 * BLOCK] and [v for v in vols if abs(v - PIN) < 1e-6 * PIN] and [v for v in vols if abs(v - PLATE) < 1e-6 * PLATE]
    else:
        assert vols == pytest.approx(volumes, rel=1e-6)
