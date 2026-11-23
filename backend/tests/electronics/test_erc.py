import pytest

from tests.electronics.kit import label, part, schematic, symbol, wire


def drivers(doc):
    symbol(doc, "DRV", "1:Y:output")
    symbol(doc, "RCV", "1:A:input")


def found(erc, rule):
    return [v for v in erc["violations"] if v["rule"] == rule]


def test_a_clean_sheet_with_every_pin_wired_passes_the_electrical_rule_check(doc):
    drivers(doc)
    schematic(
        doc,
        part("R", 0, 0, value="10k"), part("R", 10, 0, value="10k"), wire("R1.1", "R2.1"), wire("R1.2", "R2.2"),
        part("DRV", 0, 30, footprint="SOT23-3"), part("RCV", 40, 30, footprint="SOT23-3"), wire("U1.1", "U2.1"),
    )
    erc = doc.get("/ecad/erc")
    assert erc["violations"] == []
    assert erc["summary"] == {"error": 0, "warning": 0}


def test_two_outputs_tied_together_are_reported_as_a_pin_conflict_error(doc):
    drivers(doc)
    schematic(doc, part("DRV", 0, 0, footprint="SOT23-3"), part("DRV", 40, 0, footprint="SOT23-3"), wire("U1.1", "U2.1"))
    erc = doc.get("/ecad/erc")
    conflicts = found(erc, "pin_conflict")
    assert len(conflicts) == 1
    assert conflicts[0]["severity"] == "error"
    assert sorted(conflicts[0]["refs"]) == ["U1", "U2"]
    assert erc["summary"]["error"] >= 1


def test_an_output_driving_an_input_is_not_a_conflict(doc):
    drivers(doc)
    schematic(doc, part("DRV", 0, 0, footprint="SOT23-3"), part("RCV", 40, 0, footprint="SOT23-3"), wire("U1.1", "U2.1"))
    assert found(doc.get("/ecad/erc"), "pin_conflict") == []


def test_an_input_with_nothing_driving_it_is_reported(doc):
    drivers(doc)
    schematic(doc, part("RCV", 0, 0, footprint="SOT23-3"), part("RCV", 40, 0, footprint="SOT23-3"), wire("U1.1", "U2.1"))
    undriven = found(doc.get("/ecad/erc"), "input_no_driver")
    assert len(undriven) == 1 and sorted(undriven[0]["refs"]) == ["U1", "U2"]


def test_two_differently_named_nets_joined_by_a_wire_are_reported(doc):
    schematic(doc, part("R", 0, 0, value="1k"), part("R", 10, 0, value="1k"), wire("R1.1", "R2.1"), wire("R1.2", "R2.2"), label("R1.1", "SDA"), label("R2.1", "SCL"))
    named = found(doc.get("/ecad/erc"), "multiple_names")
    assert len(named) == 1
    assert "SDA" in named[0]["message"] and "SCL" in named[0]["message"]


def test_each_unconnected_pin_is_reported_once_and_nothing_else_is(doc):
    schematic(doc, part("R", 0, 0, value="1k"), part("R", 10, 0, value="1k"), wire("R1.1", "R2.1"))
    erc = doc.get("/ecad/erc")
    assert sorted((v["rule"], v["refs"][0]) for v in erc["violations"]) == [("pin_not_connected", "R1"), ("pin_not_connected", "R2")]
    pins = {tuple(p["pos"]) for ref in ("R1", "R2") for p in doc.get("/ecad/parts/%s/pins" % ref)["placements"][0]["pins"] if p["number"] == "2"}
    assert {tuple(v["pos"]) for v in erc["violations"]} == pins
    assert erc["summary"]["error"] == 2


def test_a_no_connect_flag_on_a_pin_clears_its_unconnected_report(doc):
    schematic(doc, part("R", 0, 0, value="1k"), part("R", 10, 0, value="1k"), wire("R1.1", "R2.1"), {"op": "add_no_connect", "pin": "R1.2"})
    reported = [v["refs"][0] for v in found(doc.get("/ecad/erc"), "pin_not_connected")]
    assert reported == ["R2"]


@pytest.mark.parametrize("severity, errors, warnings", [("warning", 0, 2), ("ignore", 0, 0), ("error", 2, 0)])
def test_the_severity_set_for_a_rule_is_applied_to_its_findings(doc, severity, errors, warnings):
    schematic(doc, part("R", 0, 0, value="1k"), part("R", 10, 0, value="1k"), wire("R1.1", "R2.1"))
    doc.post("/ecad/erc/settings", {"rules": {"pin_not_connected": severity}})
    assert doc.get("/ecad/erc")["summary"] == {"error": errors, "warning": warnings}
