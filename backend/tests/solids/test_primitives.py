import math

import pytest

PI = math.pi
TIGHT = dict(rel=1e-9, abs=1e-9)


def frustum_centroid(r1, r2, h):
    return h * (r1 * r1 + 2 * r1 * r2 + 3 * r2 * r2) / (4 * (r1 * r1 + r1 * r2 + r2 * r2))


def slant_area(r1, r2, h):
    return PI * (r1 + r2) * math.hypot(r1 - r2, h)


CASES = {
    "box": (
        {"kind": "box", "origin": [1.0, 2.0, 3.0], "dx": 10.0, "dy": 20.0, "dz": 30.0},
        10.0 * 20.0 * 30.0, 2 * (200.0 + 600.0 + 300.0), [6.0, 12.0, 18.0], [1.0, 2.0, 3.0, 11.0, 22.0, 33.0], (6, 12, 8)),
    "cylinder": (
        {"kind": "cylinder", "radius": 5.0, "height": 10.0},
        PI * 25.0 * 10.0, 2 * PI * 25.0 + 2 * PI * 5.0 * 10.0, [0.0, 0.0, 5.0], [-5.0, -5.0, 0.0, 5.0, 5.0, 10.0], (3, 3, 2)),
    "frustum": (
        {"kind": "cone", "radius1": 5.0, "radius2": 2.0, "height": 10.0},
        PI * 10.0 / 3.0 * (25.0 + 10.0 + 4.0), PI * 25.0 + PI * 4.0 + slant_area(5.0, 2.0, 10.0), [0.0, 0.0, frustum_centroid(5.0, 2.0, 10.0)], [-5.0, -5.0, 0.0, 5.0, 5.0, 10.0], (3, 3, 2)),
    "cone": (
        {"kind": "cone", "radius1": 5.0, "radius2": 0.0, "height": 12.0},
        PI * 25.0 * 12.0 / 3.0, PI * 25.0 + slant_area(5.0, 0.0, 12.0), [0.0, 0.0, 3.0], [-5.0, -5.0, 0.0, 5.0, 5.0, 12.0], (2, 3, 2)),
    "sphere": (
        {"kind": "sphere", "origin": [4.0, -3.0, 2.0], "radius": 5.0},
        4.0 / 3.0 * PI * 125.0, 4 * PI * 25.0, [4.0, -3.0, 2.0], [-1.0, -8.0, -3.0, 9.0, 2.0, 7.0], (1, 3, 2)),
    "torus": (
        {"kind": "torus", "major": 10.0, "minor": 2.0},
        2 * PI * PI * 10.0 * 4.0, 4 * PI * PI * 10.0 * 2.0, [0.0, 0.0, 0.0], [-12.0, -12.0, -2.0, 12.0, 12.0, 2.0], (1, 2, 1)),
}


@pytest.fixture()
def shapes(kernel):
    made = []

    def make(params):
        out = kernel.call("primitive", params)
        made.append(out["id"])
        return out

    yield make
    kernel.call("shape_free", {"ids": made})


@pytest.mark.kernel
@pytest.mark.parametrize("name", list(CASES))
def test_a_primitive_has_the_closed_form_volume_area_centroid_and_extents(kernel, shapes, name):
    params, volume, area, centre, box, _topology = CASES[name]
    made = shapes(params)
    props = kernel.call("mass_properties", {"id": made["id"]})
    assert props["volume"] == pytest.approx(volume, **TIGHT)
    assert props["area"] == pytest.approx(area, **TIGHT)
    assert props["centroid"] == pytest.approx(centre, abs=1e-9)
    exact = kernel.call("bounds", {"id": made["id"]})
    assert exact["min"] + exact["max"] == pytest.approx(box, abs=1e-6)
    assert made["summary"]["valid"] and made["summary"]["closed"] and made["summary"]["solids"] == 1


@pytest.mark.kernel
@pytest.mark.parametrize("name", list(CASES))
def test_a_primitive_has_the_faces_edges_and_vertices_of_its_shape(shapes, name):
    params, *_rest, topology = CASES[name]
    summary = shapes(params)["summary"]
    assert (summary["faces"], summary["edges"], summary["vertices"]) == topology


@pytest.mark.kernel
def test_a_box_built_on_a_tilted_axis_keeps_its_volume_and_its_centre_on_the_tilted_diagonal(kernel, shapes):
    made = shapes({"kind": "box", "origin": [0, 0, 0], "axis": [0, 0, 1], "xdir": [1, 1, 0], "dx": 10.0, "dy": 10.0, "dz": 4.0})
    props = kernel.call("mass_properties", {"id": made["id"]})
    assert props["volume"] == pytest.approx(400.0, **TIGHT)
    assert props["centroid"] == pytest.approx([0.0, 10.0 / math.sqrt(2.0), 2.0], abs=1e-9)


@pytest.mark.kernel
@pytest.mark.parametrize("params, said", [
    ({"kind": "box", "dx": 0.0, "dy": 1.0, "dz": 1.0}, "dx must be positive"),
    ({"kind": "box", "dx": 1.0, "dy": 1.0, "dz": -5.0}, "dz must be positive"),
    ({"kind": "cylinder", "radius": 0.0, "height": 5.0}, "radius must be positive"),
    ({"kind": "sphere", "radius": float("nan")}, "radius must be positive"),
    ({"kind": "cone", "radius1": 3.0, "radius2": 3.0, "height": 5.0}, "two different radii"),
    ({"kind": "torus", "major": 2.0, "minor": 3.0}, "tube radius must be smaller"),
])
def test_a_primitive_with_an_impossible_size_is_refused(kernel, params, said):
    before = set(kernel.call("shape_list")["ids"])
    with pytest.raises(kernel.KernelError, match=said):
        kernel.call("primitive", params)
    assert set(kernel.call("shape_list")["ids"]) == before


@pytest.mark.parametrize("command, args", [
    ("box", {"corner": [0, 0, 0], "size": [0, 10, 10]}),
    ("cylinder", {"center": [0, 0, 0], "radius": -2, "height": 10}),
    ("sphere", {"center": [0, 0, 0], "radius": 0}),
])
@pytest.mark.kernel
def test_the_primitive_commands_refuse_an_impossible_size_and_leave_the_drawing_empty(doc, command, args):
    from tests.support.engine import Refused

    try:
        out = doc.command(command, **args)
        refused = bool(out.get("error"))
    except Refused:
        refused = True
    assert refused
    assert doc.entities("solidbody") == []
