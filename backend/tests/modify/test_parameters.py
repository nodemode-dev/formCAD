import pytest

from tests.support import geometry
from tests.support.engine import Refused


def values(doc):
    return {p["name"]: p["value"] for p in doc.get("/parameters")["user"]}


@pytest.mark.parametrize("expr,expected", [
    ("2*3+1", 7.0),
    ("(2+3)*4 - sqrt(16)/2", 18.0),
    ("2^10", 1024.0),
    ("max(3, 8) + hypot(3, 4)", 13.0),
    ("cos(60)*10", 5.0),
])
def test_a_parameter_expression_evaluates_operators_and_functions(doc, expr, expected):
    made = doc.post("/parameters", {"name": "p", "expr": expr})
    assert geometry.close(made["value"], expected)


def test_lengths_with_units_inside_a_parameter_are_converted_to_drawing_units(doc):
    doc.set_var("INSUNITS", 4)
    made = doc.post("/parameters", {"name": "len", "expr": "1 in + 5 mm + 1 cm"})
    assert geometry.close(made["value"], 25.4 + 5 + 10)


def test_a_parameter_that_depends_on_another_updates_when_the_first_changes(doc):
    doc.post("/parameters", {"name": "w", "expr": "7"})
    doc.post("/parameters", {"name": "h", "expr": "w*2"})
    doc.post("/parameters", {"name": "area", "expr": "w*h"})
    assert values(doc) == {"w": 7.0, "h": 14.0, "area": 98.0}
    doc.put("/parameters/w", {"expr": "10"})
    assert values(doc) == {"w": 10.0, "h": 20.0, "area": 200.0}


def test_a_circular_reference_between_parameters_is_refused_and_nothing_changes(doc):
    doc.post("/parameters", {"name": "w", "expr": "10"})
    doc.post("/parameters", {"name": "h", "expr": "w*2"})
    with pytest.raises(Refused) as err:
        doc.put("/parameters/w", {"expr": "h+1"})
    assert err.value.status == 400 and "ircular" in err.value.body
    assert values(doc) == {"w": 10.0, "h": 20.0}



@pytest.mark.parametrize("expr,expected", [
    ("2+3*4", 14.0),
    ("sqrt(16)+2^3", 12.0),
    ("(1+2)*(3+4)/7", 3.0),
    ("sin(30)", 0.5),
    ("cvunit(1,inch,mm)", 25.4),
    ("cvunit(3,ft,in)", 36.0),
])
def test_the_calculator_evaluates_operators_functions_and_unit_conversions(engine, expr, expected):
    answer = engine.post("/api/calc", {"expression": expr})
    assert answer["ok"] and geometry.close(answer["value"], expected)


def test_the_calculator_reports_a_malformed_expression_instead_of_a_value(engine):
    answer = engine.post("/api/calc", {"expression": "2+*3"})
    assert answer["ok"] is False and answer["error"]


def test_cal_typed_on_the_command_line_prints_the_result(doc):
    answer = doc.type("CAL", "(10+5)*2")
    assert "30" in answer["output"]
