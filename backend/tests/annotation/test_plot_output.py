import pytest

from tests.annotation import _read as R

A4 = "ISO A4 (210.00 x 297.00 MM)"
A3 = "ISO A3 (297.00 x 420.00 MM)"
PT_PER_MM = 72.0 / 25.4


def drawing(doc):
    doc.type("LINE", "0,0", "100,0", "")
    doc.type("CIRCLE", "50,30", "10")


def page_request(**extra):
    req = {"paper": A4, "landscape": True, "scale": "1:1", "area": "extents", "compress": False, "margins": [0, 0, 0, 0]}
    req.update(extra)
    return req


@pytest.mark.parametrize("scale, length_mm", [("1:1", 100.0), ("1:2", 50.0), ("2:1", 200.0)])
def test_a_pdf_plot_of_model_space_draws_a_100_unit_line_at_the_scale_asked(engine, mm, scale, length_mm):
    drawing(mm)
    job, data = R.plot(engine, mm, "pdf", page_request(scale=scale))
    assert data.startswith(b"%PDF-")
    segs = R.pdf_segments(data)
    assert R.longest(segs) / PT_PER_MM == pytest.approx(length_mm, abs=0.01)


def test_a_pdf_plot_has_the_page_size_of_the_paper_in_points(engine, mm):
    drawing(mm)
    _job, data = R.plot(engine, mm, "pdf", page_request(paper=A3, landscape=False))
    boxes = R.pdf_media_boxes(data)
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes[0]
    assert ((x1 - x0) / PT_PER_MM, (y1 - y0) / PT_PER_MM) == pytest.approx((297.0, 420.0), abs=0.01)


def test_a_compressed_pdf_plot_renders_the_line_at_its_true_size_on_the_page(engine, mm):
    mm.type("LINE", "0,0", "100,0", "")
    _job, data = R.plot(engine, mm, "pdf", page_request(compress=True, lineweights=False, min_width=0.5))
    x0, y0, x1, y1 = R.ink_box_mm(data)
    assert x1 - x0 == pytest.approx(100.5, abs=0.3)
    assert y1 - y0 == pytest.approx(0.5, abs=0.3)
    assert (x0 + x1) / 2.0 == pytest.approx(297.0 / 2.0, abs=0.3)
    assert (y0 + y1) / 2.0 == pytest.approx(210.0 / 2.0, abs=0.3)


def test_an_svg_plot_on_paper_has_the_paper_size_in_millimetres_and_the_line_at_scale(engine, mm):
    drawing(mm)
    _job, data = R.plot(engine, mm, "plot", page_request(output="svg", scale="1:2"))
    root = R.svg_root(data)
    assert (R.svg_mm(root.get("width")), R.svg_mm(root.get("height"))) == pytest.approx((297.0, 210.0))
    assert [float(v) for v in root.get("viewBox").split()] == pytest.approx([0, 0, 297.0, 210.0])
    assert R.longest(R.svg_segments(data)) == pytest.approx(50.0, abs=0.01)


def test_svg_export_of_model_space_is_drawn_at_full_size_in_millimetres(engine, mm):
    drawing(mm)
    _job, data = R.plot(engine, mm, "svg", {"area": "extents"})
    root = R.svg_root(data)
    width = R.svg_mm(root.get("width"))
    assert width >= 100.0
    assert R.longest(R.svg_segments(data)) == pytest.approx(100.0, abs=0.01)


def test_an_inch_drawing_plotted_at_1_to_1_gives_25_4_mm_per_unit(engine, tmp_path):
    doc = engine.new_doc(template="drawing-inch-ansi-b")
    try:
        doc.type("LINE", "0,0", "4,0", "")
        _job, data = R.plot(engine, doc, "pdf", page_request(paper="ANSI B (11.00 x 17.00 Inches)"))
        assert R.longest(R.pdf_segments(data)) / PT_PER_MM == pytest.approx(4 * 25.4, abs=0.01)
    finally:
        doc.close()


def test_a_window_plot_leaves_out_what_lies_outside_the_window_and_an_extents_plot_keeps_it(engine, mm):
    drawing(mm)
    _job, whole = R.plot(engine, mm, "pdf", page_request(compress=True))
    _job, part = R.plot(engine, mm, "pdf", page_request(compress=True, area="window", window=[35, 15, 65, 45]))
    x0, y0, x1, y1 = R.ink_box_mm(whole)
    assert (x1 - x0, y1 - y0) == pytest.approx((100.25, 40.25), abs=0.3)
    x0, y0, x1, y1 = R.ink_box_mm(part)
    assert (x1 - x0, y1 - y0) == pytest.approx((20.25, 20.25), abs=0.3)


def test_an_extents_plot_with_fit_fills_the_printable_width(engine, mm):
    mm.type("LINE", "0,0", "100,0", "")
    mm.type("LINE", "0,0", "0,10", "")
    _job, data = R.plot(engine, mm, "pdf", {"paper": A4, "landscape": True, "area": "extents", "fit": True, "compress": False, "margins": [10, 10, 10, 10]})
    assert R.longest(R.pdf_segments(data)) / PT_PER_MM == pytest.approx(297.0 - 20.0, abs=0.05)


def test_a_layout_plot_uses_the_layout_paper_and_draws_model_lengths_at_the_viewport_scale(engine, mm):
    mm.type("LINE", "0,0", "100,0", "")
    mm.post("/layouts", {"action": "new", "name": "Sheet"})
    mm.put("/layouts/Sheet/pagesetup", {"paper": A4, "orientation": "landscape"})
    mm.post("/space", {"tab": "Sheet"})
    for vp in mm.get("/viewports", layout="Sheet")["viewports"]:
        mm.command("erase", handles=[vp["h"]])
    h = mm.command("mview", corners=[[20, 20], [270, 190]])["result"]["created"][0]
    mm.put("/viewports/%d" % h, {"scale": "1:2"})
    mm.post("/viewports/%d/view" % h, {"center": [50, 0], "height": 340})
    _job, data = R.plot(engine, mm, "pdf", {"layout": "Sheet", "compress": False})
    x0, y0, x1, y1 = R.pdf_media_boxes(data)[0]
    assert ((x1 - x0) / PT_PER_MM, (y1 - y0) / PT_PER_MM) == pytest.approx((297.0, 210.0), abs=0.01)
    lengths = sorted(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / PT_PER_MM for a, b in R.pdf_segments(data))
    assert any(abs(v - 50.0) < 0.01 for v in lengths)


def test_a_plot_with_an_unknown_paper_is_refused_with_a_reason(engine, mm):
    drawing(mm)
    r = engine.raw("POST", mm.url("/plot"), json={"kind": "pdf", "request": page_request(paper="Napkin")})
    body = r.json() if r.status_code < 400 else {"state": "error", "message": r.text}
    assert body.get("state") != "done"
    assert "Napkin" in (body.get("message") or "")
