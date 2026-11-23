import pytest

from tests.support.engine import Refused


@pytest.mark.parametrize("template, insunits, measurement, limmax", [
    ("drawing-mm-a3", 4, 1, [420.0, 297.0]),
    ("drawing-inch-ansi-b", 1, 0, [17.0, 11.0]),
])
def test_a_new_drawing_from_a_template_has_its_units_and_sheet_limits(engine, template, insunits, measurement, limmax):
    doc = engine.new_doc(template=template)
    try:
        assert doc.var("INSUNITS") == insunits
        assert doc.var("MEASUREMENT") == measurement
        assert doc.var("LIMMAX")[:2] == limmax
        assert doc.summary["metric"] is (measurement == 1)
    finally:
        doc.close()


@pytest.mark.parametrize("name, value", [("IMAGEFRAME", 0), ("IMAGEFRAME", 2), ("PDFFRAME", 2), ("LTSCALE", 0.25)])
def test_a_variable_set_within_its_range_reads_back(doc, name, value):
    assert doc.set_var(name, value) == value
    assert doc.var(name) == value


@pytest.mark.parametrize("name, value", [("IMAGEFRAME", 3), ("PDFFRAME", -1), ("LTSCALE", 0), ("LTSCALE", -2.0), ("LTSCALE", "lots")])
def test_a_variable_set_outside_its_range_is_refused_and_keeps_its_value(doc, name, value):
    before = doc.var(name)
    with pytest.raises(Refused) as refused:
        doc.set_var(name, value)
    assert refused.value.status == 400 and name in refused.value.body
    assert doc.var(name) == before


def test_a_read_only_variable_is_refused_and_names_the_drawing(docs, tmp_path):
    doc = docs()
    doc.type("LINE", "0,0", "1,0", "")
    doc.save(tmp_path / "plan.fcad")
    assert "plan" in doc.var("DWGNAME")
    with pytest.raises(Refused) as refused:
        doc.set_var("DWGNAME", "other")
    assert refused.value.status == 400
    assert "plan" in doc.var("DWGNAME")


def test_a_drawing_variable_belongs_to_its_own_drawing(docs):
    first, second = docs(), docs()
    first.set_var("LTSCALE", 5.0)
    assert first.var("LTSCALE") == 5.0
    assert second.var("LTSCALE") == 1.0


def test_the_window_variable_route_and_the_document_variable_route_agree(engine, doc):
    engine.put("/api/sysvars/FILLETRAD", {"doc": doc.id, "value": 7.5})
    assert doc.var("FILLETRAD") == 7.5
    doc.set_var("FILLETRAD", 2.0)
    assert engine.get("/api/sysvars/FILLETRAD", doc=doc.id)["value"] == 2.0


def test_variable_names_are_not_case_sensitive(doc):
    doc.set_var("ltscale", 3.0)
    assert doc.var("LtScale") == 3.0


def test_an_unknown_variable_is_refused(doc):
    with pytest.raises(Refused) as refused:
        doc.var("NOSUCHVARIABLE")
    assert refused.value.status == 400
