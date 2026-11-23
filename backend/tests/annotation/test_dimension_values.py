import math

import pytest

from tests.support import geometry


def made(doc, name, **args):
    state = doc.command(name, **args)
    assert not state["error"], state["error"]
    return state["result"]


def dim(doc, handle):
    found = [e for e in doc.entities("dimension") if e["handle"] == handle]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize(
    "orientation, expected",
    [("h", 30.0), ("v", 40.0)],
)
def test_a_linear_dimension_measures_the_horizontal_or_vertical_span_of_its_two_points(mm, orientation, expected):
    out = made(mm, "dimlinear", p13=[0, 0], p14=[30, 40], location=[-10, -10], orientation=orientation)
    assert geometry.close(out["measurement"], expected)
    assert geometry.close(dim(mm, out["created"])["measurement"], expected)


def test_a_linear_dimension_without_an_orientation_takes_it_from_where_the_dimension_line_is_placed(mm):
    above = made(mm, "dimlinear", p13=[0, 0], p14=[30, 40], location=[15, 60])
    beside = made(mm, "dimlinear", p13=[0, 0], p14=[30, 40], location=[60, 20])
    assert geometry.close(above["measurement"], 30.0)
    assert geometry.close(beside["measurement"], 40.0)


def test_a_rotated_linear_dimension_measures_the_projection_on_its_angle(mm):
    out = made(mm, "dimlinear", p13=[0, 0], p14=[30, 40], location=[15, 0], rotation=30)
    expected = 30.0 * math.cos(math.radians(30)) + 40.0 * math.sin(math.radians(30))
    assert geometry.close(out["measurement"], expected, 1e-9)


def test_an_aligned_dimension_measures_the_true_distance_between_its_points(mm):
    out = made(mm, "dimaligned", p13=[2, 3], p14=[2 + 30, 3 + 40], location=[0, 20])
    assert geometry.close(out["measurement"], 50.0)


def test_an_angular_dimension_between_two_lines_measures_the_angle_between_them(mm):
    mm.type("LINE", "0,0", "40,0", "")
    first = mm.entities("line")[-1]["handle"]
    mm.type("LINE", "0,0", "30,30", "")
    second = mm.entities("line")[-1]["handle"]
    out = made(mm, "dimangular", handle=first, handle2=second, pick=[40, 0], pick2=[30, 30], location=[30, 10])
    assert geometry.close(out["measurement"], math.pi / 4.0, 1e-9)


def test_a_three_point_angular_dimension_measures_the_angle_at_its_vertex(mm):
    a = (10.0, 0.0)
    b = (10.0 * math.cos(math.radians(130)), 10.0 * math.sin(math.radians(130)))
    out = made(mm, "dimangular", vertex=[0, 0], p1=list(a), p2=list(b), location=[0, 8])
    assert geometry.close(out["measurement"], math.radians(130), 1e-9)


def test_an_angular_dimension_on_an_arc_measures_its_included_angle(mm):
    mm.type("ARC", "C", "200,0", "210,0", "A", "75")
    arc = mm.only("arc")
    out = made(mm, "dimangular", handle=arc["handle"], location=[215, 10])
    assert geometry.close(out["measurement"], math.radians(75), 1e-9)


@pytest.mark.parametrize("command, factor", [("dimradius", 1.0), ("dimdiameter", 2.0)])
def test_radius_and_diameter_dimensions_measure_the_circle_they_were_placed_on(mm, command, factor):
    mm.type("CIRCLE", "100,100", "12.5")
    circle = mm.only("circle")["handle"]
    out = made(mm, command, handle=circle, location=[125, 110])
    assert geometry.close(out["measurement"], 12.5 * factor)


@pytest.mark.parametrize("kind, leader, expected", [("x", [37, 60], 37.0), ("y", [70, 22], 22.0)])
def test_an_ordinate_dimension_gives_the_x_or_y_of_its_feature_from_the_origin(mm, kind, leader, expected):
    out = made(mm, "dimordinate", feature=[37, 22], leader=leader, type=kind)
    assert geometry.close(out["measurement"], expected)


def test_continued_dimensions_chain_each_from_the_end_of_the_one_before(mm):
    made(mm, "dimlinear", p13=[0, 0], p14=[10, 0], location=[5, -10])
    chain = made(mm, "dimcontinue", points=[[25, 0], [45, 0]])
    values = [dim(mm, h)["measurement"] for h in chain["created"]]
    assert values == pytest.approx([15.0, 20.0], abs=1e-9)
    lines = [dim(mm, h)["def_point"][1] for h in chain["created"]]
    assert lines == pytest.approx([-10.0, -10.0], abs=1e-9)


def test_baseline_dimensions_all_measure_from_the_first_origin_and_stack_by_the_style_spacing(mm):
    made(mm, "dimlinear", p13=[0, 0], p14=[10, 0], location=[5, -10])
    spacing = float(mm.var("DIMDLI"))
    stack = made(mm, "dimbaseline", points=[[25, 0], [45, 0]])
    found = [dim(mm, h) for h in stack["created"]]
    assert [d["measurement"] for d in found] == pytest.approx([25.0, 45.0], abs=1e-9)
    assert [d["p13"][:2] for d in found] == [[0.0, 0.0], [0.0, 0.0]]
    assert [d["def_point"][1] for d in found] == pytest.approx([-10.0 - spacing, -10.0 - 2 * spacing], abs=1e-9)


def test_the_typed_dimlinear_prompts_place_the_same_dimension_as_the_programmatic_form(mm):
    mm.type("DIMLINEAR", "0,0", "30,40", "15,60")
    typed = mm.only("dimension")
    assert geometry.close(typed["measurement"], 30.0)
    assert typed["p13"][:2] == [0.0, 0.0] and typed["p14"][:2] == [30.0, 40.0]
    assert mm.idle()
