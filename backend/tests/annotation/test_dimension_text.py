import pytest

from tests.annotation._read import dimension_texts, only_dimension_text


def aligned(doc, length):
    return doc.command("dimaligned", p13=[0, 0], p14=[length, 0], location=[length / 2.0, 10])["result"]["created"]


def override(doc, handle, **values):
    state = doc.command("dimoverride", handles=[handle], overrides=values, clear=True)
    assert not state["error"], state["error"]


def test_the_iso_style_of_a_millimetre_drawing_shows_a_comma_and_drops_trailing_zeros(mm, tmp_path):
    aligned(mm, 12.5)
    assert mm.var("DIMSTYLE") == "ISO-25"
    assert only_dimension_text(mm, tmp_path) == ["12,5"]


@pytest.mark.parametrize(
    "length, values, shown",
    [
        (12.3456, {"DIMDEC": 2, "DIMZIN": 0, "DIMDSEP": "."}, ["12.35"]),
        (12.3456, {"DIMDEC": 0, "DIMZIN": 0}, ["12"]),
        (12.0, {"DIMDEC": 3, "DIMZIN": 0, "DIMDSEP": "."}, ["12.000"]),
        (12.0, {"DIMDEC": 3, "DIMZIN": 8, "DIMDSEP": "."}, ["12"]),
        (12.3, {"DIMRND": 0.25, "DIMDEC": 2, "DIMZIN": 0, "DIMDSEP": "."}, ["12.25"]),
        (12.3, {"DIMLFAC": 2.0, "DIMDEC": 1, "DIMZIN": 0, "DIMDSEP": "."}, ["24.6"]),
        (12.3, {"DIMPOST": "<> mm", "DIMDEC": 1, "DIMDSEP": "."}, ["12.3 mm"]),
    ],
)
def test_precision_rounding_zero_suppression_and_suffix_change_the_text_as_their_variables_say(mm, tmp_path, length, values, shown):
    h = aligned(mm, length)
    override(mm, h, **values)
    assert only_dimension_text(mm, tmp_path) == shown


@pytest.mark.parametrize(
    "length, values, shown",
    [
        (12.375, {"DIMLUNIT": 5, "DIMDEC": 3, "DIMFRAC": 2}, ["12 3/8"]),
        (12.375, {"DIMLUNIT": 5, "DIMDEC": 3, "DIMFRAC": 0}, ["12", "3", "8"]),
        (100.0, {"DIMLUNIT": 4, "DIMDEC": 0}, ["8'-4\""]),
        (30.5, {"DIMLUNIT": 4, "DIMDEC": 1, "DIMFRAC": 2}, ["2'-6 1/2\""]),
    ],
)
def test_fractional_and_architectural_units_write_inches_as_fractions_and_feet_stacked_or_inline(engine, tmp_path, length, values, shown):
    doc = engine.new_doc(template="drawing-inch-ansi-b")
    try:
        h = aligned(doc, length)
        override(doc, h, **values)
        assert only_dimension_text(doc, tmp_path) == shown
    finally:
        doc.close()


def test_a_deviation_tolerance_adds_the_upper_and_lower_values_after_the_measurement(mm, tmp_path):
    h = aligned(mm, 50.0)
    override(mm, h, DIMTOL=1, DIMTP=0.1, DIMTM=0.2, DIMDEC=2, DIMTDEC=2, DIMZIN=0, DIMDSEP=".")
    assert only_dimension_text(mm, tmp_path) == ["50.00", "+0.10", "-0.20"]


def test_limits_show_the_largest_and_smallest_allowed_sizes_instead_of_the_measurement(mm, tmp_path):
    h = aligned(mm, 50.0)
    override(mm, h, DIMLIM=1, DIMTP=0.1, DIMTM=0.2, DIMDEC=2, DIMZIN=0, DIMDSEP=".")
    assert only_dimension_text(mm, tmp_path) == ["50.10", "49.80"]


def test_alternate_units_add_the_converted_value_in_brackets(mm, tmp_path):
    h = aligned(mm, 50.8)
    override(mm, h, DIMALT=1, DIMALTF=1 / 25.4, DIMALTD=2, DIMDEC=1, DIMZIN=0, DIMDSEP=".")
    assert only_dimension_text(mm, tmp_path) == ["50.8", "[2.00]"]


@pytest.mark.parametrize("text, shown", [("<> TYP", ["40 TYP"]), ("2X <>", ["2X 40"]), ("SEE NOTE", ["SEE NOTE"])])
def test_a_text_override_keeps_the_measurement_where_it_holds_the_brackets_and_replaces_it_where_it_does_not(mm, tmp_path, text, shown):
    h = aligned(mm, 40.0)
    state = mm.command("dimoverride", handles=[h], text=text)
    assert not state["error"], state["error"]
    assert only_dimension_text(mm, tmp_path) == shown
    assert mm.only("dimension")["measurement"] == pytest.approx(40.0)


def test_radius_diameter_and_angle_texts_carry_their_symbols(mm, tmp_path):
    mm.type("CIRCLE", "100,100", "12.5")
    circle = mm.only("circle")["handle"]
    mm.command("dimradius", handle=circle, location=[125, 110])
    mm.command("dimdiameter", handle=circle, location=[75, 90])
    mm.command("dimangular", vertex=[0, 0], p1=[10, 0], p2=[0, 10], location=[5, 5])
    shown = dimension_texts(mm, tmp_path)["by_value"]
    assert shown[12.5] == ["R12,5"]
    assert shown[25.0] == ["⌀25"]
    assert len(shown) == 3 and ["90°"] in shown.values()


def test_changing_the_style_after_placing_updates_the_text_of_dimensions_that_use_it(mm, tmp_path):
    aligned(mm, 12.5)
    state = mm.post("/command", {"command": "dimstyle", "args": {"action": "modify", "name": "ISO-25", "vars": {"DIMDEC": 3, "DIMZIN": 0}}})
    assert not state["error"], state["error"]
    mm.command("dimregen")
    assert only_dimension_text(mm, tmp_path) == ["12,500"]
