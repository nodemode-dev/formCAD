import math

import pytest

from tests.support import geometry


def text_box(doc, handle):
    for item in doc.get("/display")["items"]:
        if item["h"] == handle:
            assert item["geom"]["type"] == "text"
            return item["geom"]["box"]
    raise AssertionError("no display item for %s" % handle)


def width_of(box):
    return geometry.dist(box[0], box[1])


def height_of(box):
    return geometry.dist(box[1], box[2])


def place(doc, **args):
    state = doc.command("text", **args)
    assert not state["error"], state["error"]
    return state["result"]["handle"]


def test_single_line_text_keeps_its_content_height_and_rotation(mm):
    h = place(mm, text="FLANGE 12", point=[10, 20], height=5, rotation=30)
    e = mm.only("text")
    assert e["handle"] == h and e["text"] == "FLANGE 12"
    assert geometry.close(e["height"], 5.0)
    assert geometry.close(e["rotation"], math.radians(30))
    box = text_box(mm, h)
    assert geometry.same_point(box[0], (10.0, 20.0))
    edge = math.atan2(box[1][1] - box[0][1], box[1][0] - box[0][0])
    assert geometry.close(edge, math.radians(30), 1e-9)
    assert geometry.close(height_of(box), 5.0, 1e-9)


def test_the_reported_extents_of_text_grow_with_its_characters(mm):
    short = place(mm, text="AB", point=[0, 0], height=4)
    long = place(mm, text="ABABAB", point=[0, 20], height=4)
    w1, w2 = width_of(text_box(mm, short)), width_of(text_box(mm, long))
    assert w1 > 0 and w2 > 2.5 * w1


def test_the_extents_of_text_scale_with_its_height(mm):
    small = place(mm, text="SCALE", point=[0, 0], height=2)
    large = place(mm, text="SCALE", point=[0, 20], height=6)
    assert geometry.close(width_of(text_box(mm, large)), 3.0 * width_of(text_box(mm, small)), 1e-9)


@pytest.mark.parametrize(
    "justify, anchor",
    [("MC", lambda b: ((b[0][0] + b[2][0]) / 2.0, (b[0][1] + b[2][1]) / 2.0)), ("R", lambda b: b[1]), ("TL", lambda b: b[3]), ("C", lambda b: ((b[0][0] + b[1][0]) / 2.0, b[0][1]))],
)
def test_justified_text_puts_the_named_point_of_its_box_at_the_given_point(mm, justify, anchor):
    h = place(mm, text="JUSTIFY ME", point=[40, 50], height=5, justify=justify)
    assert geometry.same_point(anchor(text_box(mm, h)), (40.0, 50.0))


def test_typed_text_lands_with_the_typed_height_rotation_and_content(mm):
    mm.type("TEXT", "5,5", "3.5", "90", "TYPED NOTE", "")
    e = mm.only("text")
    assert e["text"] == "TYPED NOTE"
    assert geometry.close(e["height"], 3.5)
    assert geometry.close(e["rotation"], math.pi / 2.0)
    assert geometry.same_point(e["position"][:2], (5.0, 5.0))
    assert mm.idle()


def test_paragraph_text_keeps_its_lines_and_its_box_grows_with_each_line(mm):
    one = mm.command("mtext", text="first line", point=[0, 100], height=2.5, width=40)["result"]["handle"]
    two = mm.command("mtext", text="first line\nsecond line", point=[0, 50], height=2.5, width=40)["result"]["handle"]
    read = mm.get("/mtext/%d" % two)
    assert read["contents"] == "first line\\Psecond line"
    assert read["props"]["height"] == 2.5 and read["props"]["width"] == 40.0
    b1, b2 = text_box(mm, one), text_box(mm, two)
    assert geometry.close(width_of(b1), 40.0) and geometry.close(width_of(b2), 40.0)
    assert height_of(b2) > 1.5 * height_of(b1)
    assert geometry.same_point(b2[3], (0.0, 50.0))


def test_paragraph_text_wraps_a_long_line_inside_its_width(mm):
    words = " ".join(["word"] * 40)
    h = mm.command("mtext", text=words, point=[0, 0], height=2.5, width=30)["result"]["handle"]
    single = mm.command("mtext", text="word", point=[0, 100], height=2.5, width=30)["result"]["handle"]
    box = text_box(mm, h)
    assert geometry.close(width_of(box), 30.0)
    assert height_of(box) > 4 * height_of(text_box(mm, single))


def test_find_and_replace_changes_only_the_whole_word_matches_in_the_right_case(mm):
    place(mm, text="Room 101 room", point=[0, 0], height=3)
    place(mm, text="Bathroom", point=[0, 10], height=3)
    place(mm, text="ROOM", point=[0, 20], height=3)
    out = mm.command("find", text="Room", replace="Hall", match_case=True, whole_word=True)["result"]
    assert out["hits"] == 1
    assert sorted(e["text"] for e in mm.entities("text")) == sorted(["Hall 101 room", "Bathroom", "ROOM"])


def test_find_without_a_replacement_counts_and_selects_but_changes_nothing(mm):
    a = place(mm, text="pump pump", point=[0, 0], height=3)
    place(mm, text="valve", point=[0, 10], height=3)
    c = place(mm, text="PUMP", point=[0, 20], height=3)
    out = mm.command("find", text="pump")["result"]
    assert out["total"] == 3
    assert sorted(out["selected"]) == sorted([a, c])
    assert sorted(e["text"] for e in mm.entities("text")) == sorted(["pump pump", "valve", "PUMP"])


def test_undo_of_a_replacement_brings_the_old_text_back(mm):
    place(mm, text="old part", point=[0, 0], height=3)
    mm.command("find", text="old", replace="new")
    assert mm.only("text")["text"] == "new part"
    mm.undo()
    assert mm.only("text")["text"] == "old part"
