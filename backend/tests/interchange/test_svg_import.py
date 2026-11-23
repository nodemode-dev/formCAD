import math

import pytest

from tests.interchange.common import metric, ok
from tests.support import geometry

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" %s>%s</svg>'


def imported(docs, tmp_path, attrs, body):
    path = tmp_path / "drawing.svg"
    path.write_text(HEAD % (attrs, body))
    doc = metric(docs())
    ok(doc, "import", path=str(path))
    return doc


def test_a_closed_path_of_lines_becomes_a_closed_polyline_with_the_same_area_and_perimeter(docs, tmp_path):
    doc = imported(docs, tmp_path, 'width="100mm" height="50mm" viewBox="0 0 100 50"', '<path d="M 10 10 L 60 10 L 60 40 L 10 40 Z"/>')
    pl = doc.only("lwpolyline")
    pts = [v["p"] for v in pl["vertices"]]
    assert pl["closed"] and len(pts) == 4
    assert geometry.area(pts) == pytest.approx(1500.0, abs=1e-9)
    assert geometry.path_length(pts, closed=True) == pytest.approx(160.0, abs=1e-9)
    assert geometry.bbox(pts) == pytest.approx((10.0, 10.0, 60.0, 40.0), abs=1e-9)


def test_a_circular_arc_path_becomes_a_bulged_segment_that_bows_toward_the_top_of_the_page(docs, tmp_path):
    doc = imported(docs, tmp_path, 'width="100mm" height="50mm" viewBox="0 0 100 50"', '<path d="M 10 20 A 10 10 0 0 1 30 20"/>')
    pl = doc.only("lwpolyline")
    a, b = pl["vertices"][0], pl["vertices"][1]
    arc = geometry.bulge_arc(a["p"], b["p"], a["bulge"])
    assert arc["radius"] == pytest.approx(10.0, abs=1e-9) and arc["length"] == pytest.approx(10 * math.pi, abs=1e-9)
    mid = ((a["p"][0] + b["p"][0]) / 2, (a["p"][1] + b["p"][1]) / 2)
    chord = (b["p"][0] - a["p"][0], b["p"][1] - a["p"][1])
    sag = (chord[1] * a["bulge"] / 2, -chord[0] * a["bulge"] / 2)
    apex = (mid[0] + sag[0], mid[1] + sag[1])
    assert apex == pytest.approx((20.0, 40.0), abs=1e-9)


@pytest.mark.parametrize("attrs,per_unit", [
    ('width="100mm" height="50mm" viewBox="0 0 100 50"', 1.0),
    ('width="10cm" height="5cm" viewBox="0 0 100 50"', 1.0),
    ('width="4in" height="2in" viewBox="0 0 100 50"', 25.4 * 4 / 100),
    ('width="384px" height="192px" viewBox="0 0 100 50"', 25.4 * 4 / 100),
    ('viewBox="0 0 100 50"', 25.4 / 96),
    ('', 25.4 / 96),
])
def test_svg_lengths_follow_the_page_units_with_96_pixels_to_the_inch(docs, tmp_path, attrs, per_unit):
    doc = imported(docs, tmp_path, attrs, '<line x1="0" y1="5" x2="50" y2="5"/><circle cx="30" cy="20" r="8"/>')
    line, circle = doc.only("line"), doc.only("circle")
    assert geometry.dist(line["start"], line["end"]) == pytest.approx(50 * per_unit, rel=1e-12)
    assert circle["radius"] == pytest.approx(8 * per_unit, rel=1e-12)


def test_group_transforms_scale_translate_and_rotate_the_geometry_they_hold(docs, tmp_path):
    body = ('<g transform="translate(10,0) scale(2)"><circle cx="5" cy="10" r="3"/></g>'
            '<g transform="rotate(90)"><line x1="0" y1="0" x2="10" y2="0"/></g>'
            '<g transform="scale(2,1)"><circle cx="10" cy="10" r="5"/></g>')
    doc = imported(docs, tmp_path, 'width="100mm" height="50mm" viewBox="0 0 100 50"', body)
    circle = doc.only("circle")
    assert circle["radius"] == pytest.approx(6.0, abs=1e-9)
    assert circle["center"][:2] == pytest.approx([20.0, 50.0 - 20.0], abs=1e-9)
    line = doc.only("line")
    assert abs(line["end"][0] - line["start"][0]) < 1e-9 and abs(line["end"][1] - line["start"][1]) == pytest.approx(10.0, abs=1e-9)
    ellipse = doc.only("ellipse")
    assert math.hypot(*ellipse["major"][:2]) == pytest.approx(10.0, abs=1e-9) and ellipse["ratio"] == pytest.approx(0.5, abs=1e-9)
    assert ellipse["center"][:2] == pytest.approx([20.0, 40.0], abs=1e-9)


def test_inkscape_layers_become_drawing_layers_holding_their_shapes(docs, tmp_path):
    ink = 'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="100mm" height="50mm" viewBox="0 0 100 50"'
    body = ('<g inkscape:groupmode="layer" inkscape:label="Outline"><path d="M 0 0 L 10 0 L 10 10 Z"/></g>'
            '<g inkscape:groupmode="layer" inkscape:label="Holes"><circle cx="5" cy="5" r="1"/></g>')
    doc = imported(docs, tmp_path, ink, body)
    assert doc.only("lwpolyline")["layer"] == "Outline" and doc.only("circle")["layer"] == "Holes"
    names = {r["name"] for r in doc.get("/layers")["layers"]}
    assert {"Outline", "Holes"} <= names
