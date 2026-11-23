import math

from tests.support import geometry


def one_dim(doc):
    return doc.only("dimension")


def test_an_aligned_dimension_on_a_line_follows_the_line_when_the_line_alone_is_moved(mm):
    mm.type("LINE", "0,0", "30,40", "")
    line = mm.only("line")["handle"]
    mm.command("dimaligned", p13=[0, 0], p14=[30, 40], location=[-5, 5])
    state = mm.command("move", handles=[line], delta=[10, 5])
    assert not state["error"]
    d = one_dim(mm)
    assert geometry.same_point(d["p13"][:2], (10.0, 5.0))
    assert geometry.same_point(d["p14"][:2], (40.0, 45.0))
    assert geometry.close(d["measurement"], 50.0)


def test_stretching_the_end_of_a_dimensioned_line_changes_the_measured_length_to_the_new_length(mm):
    mm.type("LINE", "0,0", "30,40", "")
    line = mm.only("line")["handle"]
    mm.command("dimaligned", p13=[0, 0], p14=[30, 40], location=[-5, 5])
    state = mm.command("stretch", handles=[line], window=[[25, 35], [50, 50]], delta=[30, 40])
    assert not state["error"]
    end = mm.only("line")["end"]
    assert geometry.same_point(end[:2], (60.0, 80.0))
    assert geometry.close(one_dim(mm)["measurement"], 100.0)


def test_a_radius_dimension_follows_its_circle_when_the_circle_is_scaled_about_its_centre(mm):
    mm.type("CIRCLE", "50,50", "10")
    circle = mm.only("circle")["handle"]
    mm.command("dimradius", handle=circle, location=[65, 55])
    state = mm.command("scale", handles=[circle], base=[50, 50], factor=2.5)
    assert not state["error"], state["error"]
    assert geometry.close(mm.only("circle")["radius"], 25.0)
    assert geometry.close(one_dim(mm)["measurement"], 25.0)


def test_undoing_the_move_puts_the_associative_dimension_back_with_its_old_value(mm):
    mm.type("LINE", "0,0", "40,0", "")
    line = mm.only("line")["handle"]
    mm.command("dimlinear", p13=[0, 0], p14=[40, 0], location=[20, -10])
    mm.command("stretch", handles=[line], window=[[35, -2], [45, 2]], delta=[15, 0])
    assert geometry.close(one_dim(mm)["measurement"], 55.0)
    mm.undo()
    after = one_dim(mm)
    assert geometry.close(after["measurement"], 40.0)
    assert geometry.same_point(after["p14"][:2], (40.0, 0.0))


def test_a_dimension_that_was_disassociated_keeps_its_value_when_the_line_moves(mm):
    mm.type("LINE", "0,0", "30,40", "")
    line = mm.only("line")["handle"]
    h = mm.command("dimaligned", p13=[0, 0], p14=[30, 40], location=[-5, 5])["result"]["created"]
    mm.command("dimdisassociate", handles=[h])
    mm.command("stretch", handles=[line], window=[[25, 35], [50, 50]], delta=[30, 40])
    d = one_dim(mm)
    assert geometry.close(d["measurement"], 50.0)
    assert geometry.same_point(d["p14"][:2], (30.0, 40.0))


def test_an_angular_dimension_follows_when_one_of_its_lines_is_rotated(mm):
    mm.type("LINE", "0,0", "40,0", "")
    first = mm.entities("line")[-1]["handle"]
    mm.type("LINE", "0,0", "30,30", "")
    second = mm.entities("line")[-1]["handle"]
    mm.command("dimangular", handle=first, handle2=second, pick=[40, 0], pick2=[30, 30], location=[30, 10])
    state = mm.command("rotate", handles=[second], base=[0, 0], angle=15)
    assert not state["error"], state["error"]
    assert geometry.close(one_dim(mm)["measurement"], math.radians(60), 1e-9)
