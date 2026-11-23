import pytest

from tests.support import geometry


@pytest.mark.parametrize("word", ["Diameter", "D", "d", "diam", "_D"])
def test_a_keyword_is_accepted_in_full_by_its_short_form_and_by_a_prefix(doc, word):
    doc.type("CIRCLE", "0,0", word, "20")
    assert geometry.close(doc.only("circle")["radius"], 10.0)


def test_enter_at_the_command_prompt_repeats_the_last_command(doc):
    doc.type("CIRCLE", "0,0", "5")
    doc.enter()
    state = doc.state()
    assert state["active"] and state["command"] == "CIRCLE"
    doc.type("20,0", "3")
    radii = sorted(c["radius"] for c in doc.entities("circle"))
    assert radii == [3.0, 5.0]


@pytest.mark.parametrize(
    "partial",
    [
        ("LINE", "0,0"),
        ("CIRCLE", "5,5"),
        ("CIRCLE", "3P", "0,0", "10,0"),
        ("ARC", "0,0", "5,5"),
        ("RECTANG", "0,0"),
        ("POLYGON", "6", "0,0"),
        ("ELLIPSE", "0,0", "10,0"),
        ("PLINE", "0,0"),
    ],
)
def test_cancel_in_the_middle_of_a_command_leaves_the_document_unchanged(doc, partial):
    doc.type("LINE", "100,100", "120,100", "")
    before = doc.entities()
    doc.type(*partial)
    assert doc.state()["active"]
    doc.cancel()
    assert doc.idle()
    assert doc.entities() == before


def test_an_unknown_command_reports_an_error_and_changes_nothing(doc):
    doc.type("LINE", "0,0", "10,0", "")
    before = doc.snapshot()
    doc.type("FROBNICATE")
    assert doc.error() == "Unknown command: FROBNICATE"
    assert doc.idle()
    after = doc.snapshot()
    assert after["entities"] == before["entities"] and after["rev"] == before["rev"]


def test_invalid_input_at_a_prompt_is_refused_and_the_same_prompt_waits(doc):
    doc.type("CIRCLE", "0,0")
    prompt = doc.state()["prompt"]
    doc.type("banana")
    assert doc.error()
    assert doc.state()["prompt"] == prompt
    doc.type("4")
    assert geometry.close(doc.only("circle")["radius"], 4.0)


@pytest.mark.parametrize(
    "alias, inputs, kind",
    [
        ("L", ("0,0", "5,0", ""), "line"),
        ("C", ("0,0", "5"), "circle"),
        ("REC", ("0,0", "5,5"), "lwpolyline"),
        ("PL", ("0,0", "5,0", "5,5", ""), "lwpolyline"),
        ("A", ("0,0", "5,5", "10,0"), "arc"),
    ],
)
def test_built_in_aliases_start_their_commands(doc, alias, inputs, kind):
    doc.type(alias, *inputs)
    assert doc.kinds() == {kind: 1}


def test_an_alias_file_maps_a_new_word_and_skips_external_programs(engine, doc, tmp_path):
    path = tmp_path / "mine.fcalias"
    path.write_text("; aliases\nZQC, *CIRCLE\nZQX, notepad\n", encoding="utf-8")
    try:
        loaded = engine.post("/api/aliases/load", {"path": str(path)})
        assert loaded["count"] == 1
        assert any("ZQX" in w for w in loaded["warnings"])
        doc.type("ZQC", "1,2", "3")
        circle = doc.only("circle")
        assert geometry.same_point(circle["center"], (1.0, 2.0)) and geometry.close(circle["radius"], 3.0)
        doc.type("ZQX")
        assert doc.error() == "Unknown command: ZQX"
    finally:
        engine.post("/api/aliases/clear")
    doc.type("ZQC")
    assert doc.error() == "Unknown command: ZQC"
