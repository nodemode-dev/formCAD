import math

import pytest

from tests.interchange import meshfiles
from tests.interchange.common import metric, ok
from tests.support import geometry

pytestmark = pytest.mark.kernel

FORMATS = [("stl", ""), ("stl", "ascii"), ("obj", ""), ("ply", ""), ("ply", "ascii"), ("3mf", "")]
IDS = ["stl-binary", "stl-ascii", "obj", "ply-binary", "ply-ascii", "3mf"]


def box(docs, tmp_path, ext, version):
    src = metric(docs())
    ok(src, "box", corner=[0, 0, 0], size=[10, 20, 30])
    path = tmp_path / ("box-%s.%s" % (version or "default", ext))
    out = ok(src, "export", path=str(path), version=version)
    return path, out


@pytest.mark.parametrize("ext,version", FORMATS, ids=IDS)
def test_a_box_written_as_a_mesh_file_is_closed_outward_facing_and_holds_its_exact_volume(docs, tmp_path, ext, version):
    path, out = box(docs, tmp_path, ext, version)
    if ext == "stl":
        _, form = meshfiles.read_stl(path)
        assert form == (version or "binary")
    if ext == "ply":
        _, form = meshfiles.read_ply(path)
        assert form == ("ascii" if version else "binary_little_endian")
    mesh = meshfiles.read_any(path)
    assert len(mesh.triangles) == out["notes"]["extra"]["mesh"]["triangles"]
    solid = mesh.welded()
    assert solid.closed()
    assert solid.signed_volume() == pytest.approx(6000.0, rel=1e-9)
    assert geometry.mesh_volume(solid.vertices, solid.triangles) == pytest.approx(6000.0, rel=1e-9)
    assert solid.bbox() == pytest.approx((0, 0, 0, 10, 20, 30), abs=1e-6)


@pytest.mark.parametrize("ext,version", FORMATS, ids=IDS)
def test_a_cylinder_written_as_a_mesh_file_is_closed_and_within_one_percent_below_its_true_volume(docs, tmp_path, ext, version):
    src = metric(docs())
    ok(src, "cylinder", center=[0, 0, 0], radius=5, height=40)
    path = tmp_path / ("cyl.%s" % ext)
    ok(src, "export", path=str(path), version=version)
    solid = meshfiles.read_any(path).welded()
    true = math.pi * 25 * 40
    assert solid.closed()
    assert 0.99 * true < solid.signed_volume() <= true * (1 + 1e-9)


@pytest.mark.parametrize("ext,version", FORMATS, ids=IDS)
def test_a_mesh_file_imported_again_keeps_its_triangle_count_closedness_and_volume(docs, tmp_path, ext, version):
    path, _ = box(docs, tmp_path, ext, version)
    expected = meshfiles.read_any(path).welded()
    back = metric(docs())
    ok(back, "import", path=str(path))
    (mesh,) = [e for e in back.entities() if e["kind"] == "meshbody"]
    summary = mesh["summary"]
    assert summary["triangles"] == len(expected.triangles)
    assert summary["closed"] and summary["naked_edges"] == 0
    assert summary["volume"] == pytest.approx(expected.signed_volume(), rel=1e-9)


@pytest.mark.parametrize("ext", ["stl", "obj"])
def test_importing_a_unitless_mesh_format_warns_that_the_file_carries_no_unit(docs, tmp_path, ext):
    path, _ = box(docs, tmp_path, ext, "")
    back = metric(docs())
    out = ok(back, "import", path=str(path))
    assert any("unit" in w.lower() for w in out["report"]["warnings"])


@pytest.mark.xfail(strict=True, reason="DEFECT: exporting STL or OBJ gives no warning that the format carries no unit; docs/MANUAL.md chapter 4 says mesh formats that carry no unit (STL, OBJ) produce a warning on every import and export")
@pytest.mark.parametrize("ext", ["stl", "obj"])
def test_exporting_a_unitless_mesh_format_warns_that_the_file_carries_no_unit(docs, tmp_path, ext):
    _, out = box(docs, tmp_path, ext, "")
    assert any("unit" in w.lower() for w in out["notes"]["warnings"])


def test_a_3mf_from_an_inch_drawing_is_written_in_true_size_and_an_inch_3mf_imports_at_25_4_times(docs, tmp_path):
    src = docs()
    src.set_var("INSUNITS", 1)
    ok(src, "box", corner=[0, 0, 0], size=[1, 2, 3])
    plain, inch = tmp_path / "plain.3mf", tmp_path / "inch.3mf"
    ok(src, "export", path=str(plain))
    ok(src, "export", path=str(inch), options={"unit": "in"})
    objects, unit = meshfiles.read_3mf(plain)
    assert unit == "millimeter" and objects[0][1].welded().signed_volume() == pytest.approx(6.0 * 25.4 ** 3, rel=1e-6)
    objects, unit = meshfiles.read_3mf(inch)
    assert unit == "inch" and objects[0][1].welded().signed_volume() == pytest.approx(6.0, rel=1e-6)
    back = metric(docs())
    out = ok(back, "import", path=str(inch))
    assert any("25.4" in w for w in out["report"]["warnings"])
    (mesh,) = [e for e in back.entities() if e["kind"] == "meshbody"]
    assert mesh["summary"]["volume"] == pytest.approx(6.0 * 25.4 ** 3, rel=1e-6)
    assert mesh["summary"]["bbox"] == pytest.approx([0, 0, 0, 25.4, 50.8, 76.2], abs=1e-4)


def test_the_scanned_stl_fixture_imports_with_the_triangle_count_and_open_edges_an_independent_parser_finds(docs, fixtures):
    path = fixtures / "mesh" / "scan-box-hole.stl"
    raw, form = meshfiles.read_stl(path)
    assert form == "binary" and len(raw.triangles) == 7678
    doc = metric(docs())
    ok(doc, "import", path=str(path))
    (mesh,) = [e for e in doc.entities() if e["kind"] == "meshbody"]
    assert mesh["summary"]["triangles"] == len(raw.triangles)
    assert not mesh["summary"]["closed"]
    assert (mesh["summary"]["naked_edges"], mesh["summary"]["naked_loops"], mesh["summary"]["nonmanifold_edges"]) == (1625, 287, 15)
    assert mesh["summary"]["bbox"] == pytest.approx(list(raw.bbox()), abs=1e-5)
