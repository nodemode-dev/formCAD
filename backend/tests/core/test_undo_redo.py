import pytest


def _state(doc):
    snap = doc.snapshot()
    return sorted(snap["entities"], key=lambda e: e["handle"]), snap["tables"], snap["header"]


def _setup(doc):
    doc.type("LINE", "0,0", "30,40", "")
    doc.type("CIRCLE", "50,50", "10")


def _line(doc):
    return doc.only("line")["handle"]


def _move(doc):
    doc.type("MOVE")
    doc.select(handles=[_line(doc)])
    doc.type("", "0,0", "5,7")


def _erase(doc):
    doc.type("ERASE")
    doc.select(handles=[_line(doc)])
    doc.type("")


def _draw_polyline(doc):
    doc.type("PLINE", "0,0", "10,0", "10,10", "C")


def _new_layer(doc):
    doc.put("/layers", {"ops": [{"op": "new", "name": "Hidden", "props": {"color": 4}, "current": True}]})


def _rename_layer(doc):
    doc.put("/layers", {"ops": [{"op": "new", "name": "Draft"}]})
    doc.put("/properties", {"handles": [_line(doc)], "changes": {"layer": "Draft"}})
    doc.put("/layers", {"ops": [{"op": "rename", "name": "Draft", "to": "Final"}]})


def _colour(doc):
    doc.put("/properties", {"handles": [_line(doc)], "changes": {"color": 1}})


def _header_variable(doc):
    doc.set_var("LTSCALE", 4.0)


def _block(doc):
    doc.post("/blocks", {"name": "Mark", "handles": [_line(doc)], "base": [0, 0, 0]})


CHANGES = {
    "move": (_move, 1),
    "erase": (_erase, 1),
    "draw_polyline": (_draw_polyline, 1),
    "new_layer": (_new_layer, 1),
    "rename_layer_after_moving_an_object_onto_it": (_rename_layer, 3),
    "colour_property": (_colour, 1),
    "header_variable": (_header_variable, 1),
    "block_definition": (_block, 1),
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_change_undoes_to_the_exact_document_and_redoes_to_the_exact_result(doc, change):
    act, steps = CHANGES[change]
    _setup(doc)
    before = _state(doc)
    act(doc)
    after = _state(doc)
    assert after != before
    undone = doc.undo(steps)
    assert len(undone["labels"]) == steps
    assert _state(doc) == before
    redone = doc.redo(steps)
    assert len(redone["labels"]) == steps
    assert _state(doc) == after


def test_undo_takes_back_one_command_at_a_time_in_reverse_order(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("CIRCLE", "0,0", "5")
    doc.type("PLINE", "0,0", "1,1", "")
    assert doc.kinds() == {"line": 1, "circle": 1, "lwpolyline": 1}
    doc.undo()
    assert doc.kinds() == {"line": 1, "circle": 1}
    doc.undo()
    assert doc.kinds() == {"line": 1}
    doc.redo(2)
    assert doc.kinds() == {"line": 1, "circle": 1, "lwpolyline": 1}


def test_a_new_change_after_undo_drops_the_redo_history(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("CIRCLE", "0,0", "5")
    doc.undo()
    doc.type("LINE", "0,5", "10,5", "")
    redone = doc.redo()
    assert redone["labels"] == []
    assert doc.kinds() == {"line": 2}


def test_undo_with_nothing_to_undo_says_so_and_changes_nothing(doc):
    before = _state(doc)
    answer = doc.undo()
    assert answer["labels"] == [] and "Nothing to undo." in answer["state"]["output"]
    assert _state(doc) == before
    again = doc.redo()
    assert again["labels"] == [] and "Nothing to redo." in again["state"]["output"]


def test_undoing_every_change_returns_the_drawing_to_unmodified(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.set_var("LTSCALE", 3.0)
    assert doc.state()["dirty"] is True
    doc.undo(2)
    assert doc.entities() == [] and doc.var("LTSCALE") == 1.0
    assert doc.state()["dirty"] is False


def test_an_undone_setting_stays_undone_after_save_and_open(docs, tmp_path):
    doc = docs()
    doc.type("LINE", "0,0", "10,0", "")
    doc.set_var("LTSCALE", 3.0)
    doc.undo()
    path = tmp_path / "undone.fcad"
    doc.save(path)
    doc.close()
    again = docs.open(path)
    assert again.var("LTSCALE") == 1.0
    assert len(again.entities("line")) == 1
