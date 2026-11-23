import math

import pytest

from tests.interchange.common import ACADVER, LAYERS, cmd, draw_sample, lw_vertices, metric, model_kinds, ok, polyline_length
from tests.support import geometry
from tests.support.dxf import Dxf

TOL = 1e-9


@pytest.fixture(scope="module")
def sample(engine, tmp_path_factory):
    doc = draw_sample(engine.new_doc())
    path = tmp_path_factory.mktemp("dxfw") / "sample.dxf"
    ok(doc, "export", path=str(path), version="R2018")
    yield Dxf.read(path)
    engine.raw("POST", doc.url("/close"), json={"force": True})


def model_space(dxf, kind=None):
    return [r for r in dxf.entities(kind) if r.text(67, "0") != "1"]


def test_the_written_file_holds_each_drawn_object_once_and_nothing_else_in_model_space(sample):
    kinds = {}
    for r in model_space(sample):
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    assert kinds == {"LINE": 5, "CIRCLE": 1, "ARC": 1, "LWPOLYLINE": 1, "ELLIPSE": 1, "TEXT": 1, "HATCH": 1, "DIMENSION": 1, "INSERT": 1}


def test_a_line_keeps_its_endpoints_and_a_circle_its_centre_and_radius(sample):
    line = [r for r in model_space(sample, "LINE") if r.layer == "Walls"]
    assert len(line) == 1
    assert geometry.same_point(line[0].point(10), (0, 0, 0), TOL) and geometry.same_point(line[0].point(11), (30, 40, 0), TOL)
    circle = model_space(sample, "CIRCLE")[0]
    assert geometry.same_point(circle.point(10), (100, 50, 0), TOL)
    assert circle.number(40) == pytest.approx(12.5, abs=TOL)


def test_a_three_point_arc_is_written_as_its_centre_radius_and_angles_in_degrees(sample):
    arc = model_space(sample, "ARC")[0]
    assert geometry.same_point(arc.point(10), (10, 100, 0), 1e-9)
    assert arc.number(40) == pytest.approx(10.0, abs=1e-9)
    assert arc.number(50) % 360 == pytest.approx(0.0, abs=1e-9)
    assert arc.number(51) == pytest.approx(180.0, abs=1e-9)


def test_a_polyline_arc_segment_keeps_its_bulge_on_the_vertex_that_starts_it(sample):
    pl = model_space(sample, "LWPOLYLINE")[0]
    verts = lw_vertices(pl)
    assert [(x, y) for x, y, _ in verts] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert [b for _, _, b in verts][:2] == [0.0, 1.0]
    assert int(pl.number(70)) & 1 == 0
    assert polyline_length(verts) == pytest.approx(10.0 + 5.0 * math.pi, abs=1e-9)


def test_an_ellipse_keeps_its_centre_major_axis_ratio_and_full_parameter_range(sample):
    e = model_space(sample, "ELLIPSE")[0]
    assert geometry.same_point(e.point(10), (50, 50, 0), TOL)
    assert geometry.same_point(e.point(11), (20, 0, 0), TOL)
    assert e.number(40) == pytest.approx(0.5, abs=TOL)
    assert e.number(41) == pytest.approx(0.0, abs=TOL) and e.number(42) == pytest.approx(2 * math.pi, abs=1e-9)


def test_text_keeps_its_content_height_and_insertion_point(sample):
    t = model_space(sample, "TEXT")[0]
    assert t.text(1) == "HELLO" and t.layer == "Notes"
    assert t.number(40) == pytest.approx(2.5, abs=TOL)
    assert geometry.same_point(t.point(10), (5, 5, 0), TOL)


def test_every_layer_is_in_the_layer_table_with_its_colour_and_objects_name_their_layer(sample):
    table = {r.text(2): int(r.number(62)) for r in sample.table("LAYER")}
    for name, colour in LAYERS.items():
        assert table.get(name) == colour
    by_kind = {r.kind: r.layer for r in model_space(sample) if r.kind != "LINE"}
    assert by_kind == {"CIRCLE": "Holes", "ARC": "Holes", "LWPOLYLINE": "Paths", "ELLIPSE": "Paths", "TEXT": "Notes", "HATCH": "Fill", "DIMENSION": "Dims", "INSERT": "Dims"}


def test_a_block_insert_names_a_written_block_that_holds_the_block_geometry(sample):
    ins = model_space(sample, "INSERT")[0]
    assert ins.text(2) == "PEG"
    assert geometry.same_point(ins.point(10), (300, 300, 0), TOL)
    inside, found = False, []
    for r in sample.sections["BLOCKS"]:
        if r.kind == "BLOCK":
            inside = r.text(2) == "PEG"
        elif r.kind == "ENDBLK":
            inside = False
        elif inside:
            found.append(r)
    assert [r.kind for r in found] == ["CIRCLE"]
    assert geometry.same_point(found[0].point(10), (0, 0, 0), TOL) and found[0].number(40) == pytest.approx(2.0, abs=TOL)


def test_a_hatch_names_its_pattern_and_its_boundary_runs_through_the_rectangle_corners(sample):
    h = model_space(sample, "HATCH")[0]
    assert h.text(2) == "ANSI31" and int(h.number(70)) == 0
    assert int(h.number(91)) == 1
    pts = {(round(x, 9), round(y, 9)) for x, y in h.points(10)} | {(round(x, 9), round(y, 9)) for x, y in h.points(11)}
    assert {(200.0, 0.0), (260.0, 0.0), (260.0, 40.0), (200.0, 40.0)} <= pts


def test_a_linear_dimension_keeps_its_definition_points_and_its_picture_block(sample):
    d = model_space(sample, "DIMENSION")[0]
    assert geometry.same_point(d.point(13), (0, 0, 0), TOL) and geometry.same_point(d.point(14), (30, 0, 0), TOL)
    assert d.point(10)[1] == pytest.approx(-10.0, abs=TOL)
    assert int(d.number(70)) & 7 == 0
    assert d.text(2) in sample.blocks()


@pytest.mark.parametrize("code,name", [(4, "mm"), (1, "in"), (6, "m")])
def test_the_units_header_carries_the_drawing_units(doc, tmp_path, code, name):
    doc.set_var("INSUNITS", code)
    ok(doc, "line", points=[[0, 0], [1, 1]])
    path = tmp_path / ("units-%s.dxf" % name)
    ok(doc, "export", path=str(path))
    assert int(Dxf.read(path).variable("INSUNITS")) == code


@pytest.mark.parametrize("version", list(ACADVER))
def test_each_offered_dxf_version_is_written_with_its_version_code_and_its_geometry(engine, doc, tmp_path, version):
    assert version in engine.get("/api/interchange/formats")["versions"]
    metric(doc)
    ok(doc, "line", points=[[0, 0], [30, 40]])
    ok(doc, "circle", center=[100, 50], radius=12.5)
    ok(doc, "text", text="HELLO", point=[5, 5], height=2.5)
    path = tmp_path / ("v-%s.dxf" % version)
    ok(doc, "export", path=str(path), version=version)
    dxf = Dxf.read(path)
    assert dxf.variable("ACADVER") == ACADVER[version]
    line = dxf.entities("LINE")[0]
    assert geometry.same_point(line.point(11), (30, 40, 0), TOL)
    assert dxf.entities("CIRCLE")[0].number(40) == pytest.approx(12.5, abs=TOL)
    assert [t.text(1) for t in dxf.entities("TEXT") if t.text(67, "0") != "1"] == ["HELLO"]


def test_release_12_writes_an_ellipse_as_a_polyline_whose_vertices_lie_on_the_ellipse(doc, tmp_path):
    metric(doc)
    ok(doc, "ellipse", center=[50, 50], major=[20, 0], ratio=0.5)
    path = tmp_path / "ellipse-r12.dxf"
    ok(doc, "export", path=str(path), version="R12")
    dxf = Dxf.read(path)
    assert dxf.kinds().get("ELLIPSE") is None and dxf.kinds()["POLYLINE"] == 1
    verts = [v.point(10) for v in dxf.entities("VERTEX")]
    assert len(verts) >= 16
    for x, y, _ in verts:
        assert ((x - 50) / 20) ** 2 + ((y - 50) / 10) ** 2 == pytest.approx(1.0, abs=1e-9)


@pytest.mark.xfail(strict=True, reason="DEFECT: a release 12 export turns a polyline into a 3D polyline and drops the bulge, so a semicircular segment becomes a straight chord; release 12 polylines carry bulges (group 42 on VERTEX) and fixtures/dxf/SURVIVAL.md says R12 keeps the geometry R12 can hold")
def test_release_12_keeps_the_arc_segment_of_a_polyline(doc, tmp_path):
    metric(doc)
    ok(doc, "pline", vertices=[{"point": [0, 0], "bulge": 0}, {"point": [10, 0], "bulge": 1}, {"point": [10, 10]}])
    path = tmp_path / "bulge-r12.dxf"
    ok(doc, "export", path=str(path), version="R12")
    verts = [(v.number(10), v.number(20), v.number(42)) for v in Dxf.read(path).entities("VERTEX")]
    assert polyline_length(verts) == pytest.approx(10.0 + 5.0 * math.pi, rel=1e-3)


def test_an_unknown_dxf_version_is_refused_and_no_file_is_written(doc, tmp_path):
    ok(doc, "line", points=[[0, 0], [1, 1]])
    path = tmp_path / "bad-version.dxf"
    out = cmd(doc, "export", path=str(path), version="R1999")
    assert "R1999" in out["error"] and "R2018" in out["error"]
    assert not path.exists()


def test_a_binary_dxf_starts_with_the_binary_sentinel_and_reopens_with_the_same_objects(engine, docs, tmp_path):
    src = draw_sample(docs())
    path = tmp_path / "binary.dxf"
    ok(src, "export", path=str(path), binary=True)
    assert path.read_bytes()[:22] == bytes.fromhex("4175746f4341442042696e617279204458460d0a1a00")
    back = docs.open(path)
    assert model_kinds(back) == model_kinds(src)
