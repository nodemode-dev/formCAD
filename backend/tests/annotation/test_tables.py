import pytest


def make(doc, **args):
    state = doc.command("table", **args)
    assert not state["error"], state["error"]
    return state["result"]


def cell(table, ref):
    col = ord(ref[0]) - ord("A")
    row = int(ref[1:]) - 1
    return table["cells"][row][col]


def test_a_table_has_the_data_rows_and_columns_asked_for_below_its_title_and_header(mm):
    out = make(mm, cols=4, rows=3, point=[0, 0])
    t = mm.get("/table/%d" % out["handle"])
    assert (t["rows"], t["cols"]) == (3 + 2, 4)
    assert len(t["cells"]) == 5 and all(len(r) == 4 for r in t["cells"])
    assert t["title"] and t["header"]


def test_cell_text_given_at_creation_is_kept_in_the_named_cells(mm):
    out = make(mm, cols=3, rows=2, point=[0, 0], cells=[["A2", "Part"], ["B2", "Qty"], ["A3", "Bolt M6"], ["B3", "12"]])
    t = mm.get("/table/%d" % out["handle"])
    assert [cell(t, r)["text"] for r in ("A2", "B2", "A3", "B3")] == ["Part", "Qty", "Bolt M6", "12"]
    assert cell(t, "C3")["text"] == ""


@pytest.mark.parametrize("formula, expected", [("=SUM(B3:B5)", 15.0), ("=AVERAGE(B3:B5)", 5.0), ("=MAX(B3:B5)", 9.0), ("=MIN(B3:B5)-B3", 0.0), ("=COUNT(B3:B5)", 3.0)])
def test_a_formula_cell_computes_its_function_over_the_range(mm, formula, expected):
    out = make(mm, cols=2, rows=4, point=[0, 0], cells=[["B3", "2"], ["B4", "4"], ["B5", "9"], ["B6", formula]])
    got = cell(mm.get("/table/%d" % out["handle"]), "B6")
    assert got["formula"] == formula
    assert got["value"] == pytest.approx(expected)
    assert float(got["text"]) == pytest.approx(expected)


def test_changing_a_cell_in_the_range_recalculates_the_sum(mm):
    out = make(mm, cols=2, rows=4, point=[0, 0], cells=[["B3", "2"], ["B4", "4"], ["B5", "9"], ["B6", "=SUM(B3:B5)"]])
    t = mm.put("/table/%d" % out["handle"], {"cells": [{"cell": "B4", "text": "40"}]})
    assert cell(t, "B6")["value"] == pytest.approx(51.0)
    mm.undo()
    assert cell(mm.get("/table/%d" % out["handle"]), "B6")["value"] == pytest.approx(15.0)


def test_inserting_a_row_inside_the_summed_range_widens_the_range_and_counts_the_new_cell(mm):
    out = make(mm, cols=2, rows=4, point=[0, 0], cells=[["B3", "2"], ["B4", "4"], ["B5", "9"], ["B6", "=SUM(B3:B5)"]])
    h = out["handle"]
    mm.put("/table/%d" % h, {"ops": [{"op": "insertrow", "index": 3}]})
    t = mm.put("/table/%d" % h, {"cells": [{"cell": "B4", "text": "10"}]})
    total = cell(t, "B7")
    assert total["value"] == pytest.approx(25.0)
    assert total["formula"] == "=SUM(B3:B6)"


def test_a_formula_that_refers_to_itself_is_reported_and_not_given_a_number(mm):
    out = make(mm, cols=2, rows=2, point=[0, 0], cells=[["B3", "5"], ["B4", "=B4+B3"]])
    got = cell(mm.get("/table/%d" % out["handle"]), "B4")
    assert got["value"] is None
    assert got["text"] != "" and not got["text"].replace(".", "").isdigit()
