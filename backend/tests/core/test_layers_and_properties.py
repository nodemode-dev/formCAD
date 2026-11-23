import json

import pytest

from tests.support.engine import Refused


def _layers(doc):
    return {r["name"]: r for r in doc.get("/layers")["layers"]}


def _ops(doc, *ops):
    return doc.put("/layers", {"ops": list(ops)})


def _shown(doc):
    payload = json.loads(doc.engine.raw("GET", doc.url("/display")).text)
    return {item["h"] for item in payload["items"]}


def _move_line(doc, handle):
    doc.type("MOVE")
    doc.select(handles=[handle])
    doc.type("", "0,0", "5,5")


def test_a_new_current_layer_receives_the_next_drawn_objects(doc):
    _ops(doc, {"op": "new", "name": "Walls", "props": {"color": 1}, "current": True})
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("CIRCLE", "0,0", "4")
    assert {e["layer"] for e in doc.entities()} == {"Walls"}
    assert doc.var("CLAYER") == "Walls"
    walls = _layers(doc)["Walls"]
    assert walls["current"] is True and walls["objects"] == 2 and walls["color"] == 1


def test_setting_the_current_layer_by_variable_and_by_the_layer_route_agree(doc):
    _ops(doc, {"op": "new", "name": "A"}, {"op": "new", "name": "B"})
    doc.set_var("CLAYER", "A")
    assert doc.get("/layers")["current"] == "A"
    _ops(doc, {"op": "current", "name": "B"})
    assert doc.var("CLAYER") == "B"
    doc.type("LINE", "0,0", "1,0", "")
    assert doc.only("line")["layer"] == "B"


def test_the_current_layer_cannot_be_set_to_a_layer_that_does_not_exist(doc):
    with pytest.raises(Refused) as refused:
        doc.set_var("CLAYER", "NoSuchLayer")
    assert refused.value.status == 400
    assert doc.var("CLAYER") == "0"


def test_renaming_a_layer_carries_its_objects_to_the_new_name(doc):
    _ops(doc, {"op": "new", "name": "Draft", "current": True})
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("LINE", "0,5", "10,5", "")
    _ops(doc, {"op": "rename", "name": "Draft", "to": "Final"})
    layers = _layers(doc)
    assert "Draft" not in layers and layers["Final"]["objects"] == 2
    assert {e["layer"] for e in doc.entities("line")} == {"Final"}
    assert doc.var("CLAYER") == "Final"


def test_objects_on_a_frozen_layer_are_not_drawn_and_return_when_thawed(doc):
    _ops(doc, {"op": "new", "name": "Cold"})
    doc.type("LINE", "0,0", "10,0", "")
    kept = doc.only("line")["handle"]
    _ops(doc, {"op": "current", "name": "Cold"})
    doc.type("CIRCLE", "0,0", "4")
    cold = doc.only("circle")["handle"]
    _ops(doc, {"op": "current", "name": "0"}, {"op": "set", "name": "Cold", "props": {"frozen": True}})
    assert _shown(doc) == {kept}
    _ops(doc, {"op": "set", "name": "Cold", "props": {"frozen": False}})
    assert _shown(doc) == {kept, cold}


def test_objects_on_a_locked_layer_do_not_move_while_others_do(doc):
    _ops(doc, {"op": "new", "name": "Fixed", "current": True})
    doc.type("LINE", "0,0", "10,0", "")
    locked = doc.only("line")["handle"]
    _ops(doc, {"op": "current", "name": "0"}, {"op": "set", "name": "Fixed", "props": {"locked": True}})
    doc.type("CIRCLE", "0,0", "4")
    free = doc.only("circle")["handle"]
    _move_line(doc, locked)
    assert doc.only("line")["start"][:2] == [0.0, 0.0]
    doc.type("MOVE")
    doc.select(handles=[free])
    doc.type("", "0,0", "5,5")
    assert doc.only("circle")["center"][:2] == [5.0, 5.0]


def test_a_property_change_skips_objects_on_a_locked_layer(doc):
    _ops(doc, {"op": "new", "name": "Fixed", "current": True})
    doc.type("LINE", "0,0", "10,0", "")
    _ops(doc, {"op": "current", "name": "0"})
    doc.type("LINE", "0,5", "10,5", "")
    lines = {e["layer"]: e["handle"] for e in doc.entities("line")}
    _ops(doc, {"op": "set", "name": "Fixed", "props": {"locked": True}})
    answer = doc.put("/properties", {"handles": list(lines.values()), "changes": {"color": 1}})
    assert answer["changed"] == 1 and answer["locked"] == 1
    colours = {e["layer"]: e["color"] for e in doc.entities("line")}
    assert colours == {"0": 1, "Fixed": 256}


def test_property_changes_set_colour_linetype_and_layer_of_an_object(doc):
    _ops(doc, {"op": "new", "name": "Other"})
    doc.type("LINE", "0,0", "10,0", "")
    handle = doc.only("line")["handle"]
    doc.put("/properties", {"handles": [handle], "changes": {"color": 3, "linetype": "DASHED", "layer": "Other", "ltscale": 2.0}})
    line = doc.only("line")
    assert (line["color"], line["linetype"], line["layer"], line["ltscale"]) == (3, "DASHED", "Other", 2.0)
    assert line["start"][:2] == [0.0, 0.0] and line["end"][:2] == [10.0, 0.0]


def test_the_current_linetype_and_colour_apply_to_new_objects(doc):
    doc.set_var("CELTYPE", "HIDDEN")
    doc.set_var("CECOLOR", 5)
    doc.type("LINE", "0,0", "10,0", "")
    line = doc.only("line")
    assert (line["linetype"], line["color"]) == ("HIDDEN", 5)


def test_a_linetype_that_is_not_loaded_cannot_be_made_current(doc):
    with pytest.raises(Refused) as refused:
        doc.set_var("CELTYPE", "NOT_A_LINETYPE")
    assert refused.value.status == 400
    assert doc.var("CELTYPE") == "ByLayer"


def test_new_objects_default_to_bylayer_colour_and_linetype(doc):
    _ops(doc, {"op": "new", "name": "Red", "props": {"color": 1}, "current": True})
    doc.type("LINE", "0,0", "10,0", "")
    line = doc.only("line")
    assert (line["color"], line["linetype"]) == (256, "ByLayer")
    payload = json.loads(doc.engine.raw("GET", doc.url("/display")).text)
    assert payload["items"][0]["color"] == [255, 0, 0]
