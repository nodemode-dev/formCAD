import math
from collections import Counter

import pytest

from tests.interchange.common import draw_sample, extents, layer_table, model, model_kinds, ok
from tests.support import geometry
from tests.support.dxf import Dxf

FIXTURES = ["mechanism-drawing-r2018.dxf", "survival-r12.dxf", "survival-r2000.dxf", "survival-r2004.dxf", "survival-r2007.dxf", "survival-r2010.dxf", "survival-r2013.dxf", "survival-r2018.dxf"]
ONE_TO_ONE = {"LINE": "line", "CIRCLE": "circle", "ARC": "arc", "POINT": "point", "TEXT": "text", "SOLID": "solid", "DIMENSION": "dimension", "ELLIPSE": "ellipse", "HATCH": "hatch", "MLINE": "mline", "RAY": "ray", "XLINE": "xline", "WIPEOUT": "wipeout", "POLYLINE": "polyline3d"}


def reader_extents(dxf):
    pts = []
    for r in dxf.entities("LINE"):
        pts += [r.point(10), r.point(11)]
    for r in dxf.entities("CIRCLE"):
        (x, y, _), rad = r.point(10), r.number(40)
        pts += [(x - rad, y - rad), (x + rad, y + rad)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.fixture(scope="module")
def opened(engine, fixtures):
    made = {}

    def get(name):
        if name not in made:
            path = fixtures / "dxf" / name
            made[name] = (engine.open_doc(path), Dxf.read(path))
        return made[name]

    yield get
    for doc, _ in made.values():
        engine.raw("POST", doc.url("/close"), json={"force": True})


@pytest.mark.parametrize("name", FIXTURES)
def test_a_dxf_fixture_opens_with_the_object_counts_an_independent_reader_finds(opened, name):
    doc, dxf = opened(name)
    ents = [e for e in doc.entities() if not e["owner"].startswith("block")]
    app = Counter(e["kind"] for e in ents)
    found = Counter(ONE_TO_ONE[r.kind] for r in dxf.entities() if r.kind in ONE_TO_ONE)
    assert sum(found.values()) > 100
    assert {k: app.get(k, 0) for k in found} == dict(found)


@pytest.mark.parametrize("name", FIXTURES)
def test_a_dxf_fixture_opens_with_the_extents_and_layers_an_independent_reader_finds(opened, name):
    doc, dxf = opened(name)
    ents = [e for e in doc.entities() if not e["owner"].startswith("block") and e["kind"] in ("line", "circle")]
    got, want = extents(ents), reader_extents(dxf)
    assert all(abs(a - b) <= 1e-9 * max(1.0, abs(b)) for a, b in zip(got, want))
    names = {n.casefold() for n in layer_table(doc)}
    assert {n.casefold() for n in dxf.layers()} <= names


@pytest.mark.parametrize("version", ["R2000", "R2007", "R2018"])
def test_a_drawing_written_to_dxf_and_opened_again_keeps_counts_extents_layers_and_units(docs, tmp_path, version):
    src = draw_sample(docs())
    path = tmp_path / ("round-%s.dxf" % version)
    ok(src, "export", path=str(path), version=version)
    back = docs.open(path)
    assert model_kinds(back) == model_kinds(src)
    assert all(abs(a - b) <= 1e-9 for a, b in zip(extents(model(back)), extents(model(src))))
    a, b = layer_table(src), layer_table(back)
    assert {n: a[n]["color"] for n in a} == {n: b[n]["color"] for n in a}
    assert back.var("INSUNITS") == 4


def test_a_drawing_imported_from_dxf_lands_beside_what_the_open_drawing_already_holds(docs, tmp_path):
    src = draw_sample(docs())
    path = tmp_path / "merge.dxf"
    ok(src, "export", path=str(path))
    target = docs()
    ok(target, "line", points=[[-50, -50], [-40, -40]])
    out = ok(target, "import", path=str(path))
    assert out["added"]["objects"] == len(model(src))
    want = model_kinds(src)
    want["line"] += 1
    assert model_kinds(target) == want
    assert set(layer_table(src)) <= set(layer_table(target))
    target.undo()
    assert model_kinds(target) == {"line": 1}


def test_a_hand_written_release_12_file_reads_as_exactly_its_line_circle_arc_and_layer(docs, tmp_path):
    rows = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
            "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "1", "0", "LAYER", "2", "PLATE", "70", "0", "62", "5", "6", "CONTINUOUS", "0", "ENDTAB", "0", "ENDSEC",
            "0", "SECTION", "2", "ENTITIES",
            "0", "LINE", "8", "PLATE", "10", "1.5", "20", "2.5", "30", "0", "11", "41.5", "21", "32.5", "31", "0",
            "0", "CIRCLE", "8", "PLATE", "10", "20", "20", "-7", "30", "0", "40", "3.25",
            "0", "ARC", "8", "PLATE", "10", "0", "20", "0", "30", "0", "40", "8", "50", "90", "51", "180",
            "0", "ENDSEC", "0", "EOF", ""]
    path = tmp_path / "hand.dxf"
    path.write_text("\n".join(rows))
    doc = docs.open(path)
    assert model_kinds(doc) == {"line": 1, "circle": 1, "arc": 1}
    line, circle, arc = doc.only("line"), doc.only("circle"), doc.only("arc")
    assert geometry.same_point(line["start"], (1.5, 2.5, 0)) and geometry.same_point(line["end"], (41.5, 32.5, 0))
    assert geometry.same_point(circle["center"], (20, -7, 0)) and circle["radius"] == pytest.approx(3.25, abs=1e-12)
    assert arc["radius"] == pytest.approx(8.0, abs=1e-12)
    assert arc["start_angle"] == pytest.approx(math.pi / 2, abs=1e-12) and arc["end_angle"] == pytest.approx(math.pi, abs=1e-12)
    assert {line["layer"], circle["layer"], arc["layer"]} == {"PLATE"}
    assert layer_table(doc)["PLATE"]["color"] == 5
    assert doc.var("INSUNITS") == 4
