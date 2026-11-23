import pytest

from tests.modify.draw import circle, ent, ends, line, tag
from tests.support import geometry


def three(doc):
    return line(doc, "1,1", "4,1"), line(doc, "3,3", "12,3"), circle(doc, "50,50", 2)


def remaining(doc):
    return sorted(doc.handles())


@pytest.mark.parametrize("how,picks,kept", [
    ("W", ["0,0", "10,10"], ("b", "c")),
    ("C", ["0,0", "10,10"], ("c",)),
    ("F", ["3.5,0", "3.5,5", ""], ("c",)),
    ("F", ["2,0", "2,5", ""], ("b", "c")),
])
def test_window_takes_only_objects_fully_inside_while_crossing_and_fence_take_those_they_touch(doc, how, picks, kept):
    a, b, c = three(doc)
    names = {"a": a, "b": b, "c": c}
    doc.type("ERASE", how, *picks, "")
    assert remaining(doc) == sorted(names[k] for k in kept)


def test_selection_by_handle_takes_exactly_the_named_objects(doc):
    a, b, c = three(doc)
    doc.type("ERASE", "%s,%s" % (tag(a), tag(c)), "")
    assert remaining(doc) == [b]


def test_previous_reuses_the_last_selection_set(doc):
    a, b, c = three(doc)
    doc.type("MOVE", "%s,%s" % (tag(a), tag(c)), "", "0,0", "1,0")
    doc.type("MOVE", "P", "", "0,0", "0,1")
    assert geometry.same_point(ends(ent(doc, a))[0], (2, 2))
    assert geometry.same_point(ent(doc, c)["center"], (51, 51))
    assert geometry.same_point(ends(ent(doc, b))[0], (3, 3))


def test_all_with_remove_excludes_the_removed_object(doc):
    a, b, c = three(doc)
    doc.type("ERASE", "ALL", "R", tag(b), "")
    assert remaining(doc) == [b]


def layer_with(doc, name, draw):
    doc.put("/layers", {"ops": [{"op": "new", "name": name, "current": True}]})
    h = draw()
    doc.put("/layers", {"ops": [{"op": "current", "name": "0"}]})
    return h


def test_objects_on_a_locked_layer_are_not_moved_by_a_move_of_everything(doc):
    free = line(doc, "0,0", "10,0")
    held = layer_with(doc, "HELD", lambda: line(doc, "0,5", "10,5"))
    doc.put("/layers", {"ops": [{"op": "set", "name": "HELD", "props": {"locked": True}}]})
    doc.type("MOVE", "ALL", "", "0,0", "7,7")
    assert geometry.same_point(ends(ent(doc, free))[0], (7, 7))
    assert ends(ent(doc, held)) == ((0.0, 5.0), (10.0, 5.0))


def test_objects_on_a_frozen_layer_survive_erase_all_and_return_when_thawed(doc):
    line(doc, "0,0", "10,0")
    cold = layer_with(doc, "COLD", lambda: circle(doc, "5,5", 3))
    doc.put("/layers", {"ops": [{"op": "set", "name": "COLD", "props": {"frozen": True}}]})
    doc.type("ERASE", "ALL", "")
    doc.put("/layers", {"ops": [{"op": "set", "name": "COLD", "props": {"frozen": False}}]})
    assert remaining(doc) == [cold]
    assert geometry.close(ent(doc, cold)["radius"], 3.0)


def test_quick_select_by_layer_and_kind_feeds_the_next_command(doc):
    line(doc, "0,0", "10,0")
    keep_circle = circle(doc, "20,0", 1)
    on_a = layer_with(doc, "A", lambda: (circle(doc, "30,0", 1), line(doc, "0,9", "9,9")))
    doc.command("qselect", kind="circle", property="layer", operator="=", value="A")
    assert doc.state()["selection"] == [on_a[0]]
    doc.type("ERASE")
    assert on_a[0] not in doc.handles()
    assert keep_circle in doc.handles() and on_a[1] in doc.handles()
