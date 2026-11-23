import math
from collections import Counter

import pytest

from tests.interchange.common import layer, layer_table, metric, nurbs_samples, ok

pytestmark = pytest.mark.kernel


def curves_by_layer(doc, name):
    return [e for e in doc.entities() if e["layer"] == name]


@pytest.fixture()
def curves_back(docs, tmp_path):
    src = metric(docs())
    layer(src, "Walls")
    ok(src, "line", points=[[0, 0], [30, 40]])
    layer(src, "Holes")
    ok(src, "circle", center=[100, 50], radius=12.5)
    ok(src, "arc", points=[[0, 100], [10, 110], [20, 100]])
    path = tmp_path / "curves.3dm"
    ok(src, "export", path=str(path))
    back = metric(docs())
    out = ok(back, "import", path=str(path))
    return back, out


def test_a_line_circle_and_arc_come_back_from_3dm_as_three_objects_on_their_layers_with_layer_colours(curves_back):
    back, out = curves_back
    assert out["added"]["objects"] == 3
    assert len(curves_by_layer(back, "Walls")) == 1 and len(curves_by_layer(back, "Holes")) == 2
    table = layer_table(back)
    assert table["Walls"]["color"] in (1, "#FF0000") and table["Holes"]["color"] in (3, "#00FF00")


def samples(e, count=41):
    if e["kind"] == "nurbscurve":
        return nurbs_samples(e, count)
    c, r = e["center"], e["radius"]
    a0, a1 = (e.get("start_angle", 0.0), e.get("end_angle", 2 * math.pi)) if e["kind"] == "arc" else (0.0, 2 * math.pi)
    a1 = a1 if a1 > a0 else a1 + 2 * math.pi
    return [(c[0] + r * math.cos(a0 + (a1 - a0) * i / (count - 1)), c[1] + r * math.sin(a0 + (a1 - a0) * i / (count - 1)), 0.0) for i in range(count)]


def test_a_circle_and_an_arc_read_back_from_3dm_lie_exactly_on_their_circles(curves_back):
    back, _ = curves_back
    found = {}
    for e in curves_by_layer(back, "Holes"):
        pts = samples(e)
        found["circle" if math.dist(pts[0], pts[-1]) < 1e-9 else "arc"] = pts
    circle, arc = found["circle"], found["arc"]
    for x, y, _ in circle:
        assert math.hypot(x - 100, y - 50) == pytest.approx(12.5, abs=1e-9)
    for x, y, _ in arc:
        assert math.hypot(x - 10, y - 100) == pytest.approx(10.0, abs=1e-9) and y >= 100 - 1e-9
    assert {tuple(round(c, 9) + 0.0 for c in arc[0][:2]), tuple(round(c, 9) + 0.0 for c in arc[-1][:2])} == {(20.0, 100.0), (0.0, 100.0)}


def test_a_line_read_back_from_3dm_keeps_its_two_endpoints(curves_back):
    back, _ = curves_back
    (e,) = curves_by_layer(back, "Walls")
    if e["kind"] == "line":
        ends = [e["start"], e["end"]]
    elif e["kind"] == "nurbscurve":
        pts = nurbs_samples(e)
        ends = [pts[0], pts[-1]]
    else:
        ends = [e["points"][0], e["points"][-1]]
    ends = sorted(tuple(round(float(c), 9) for c in p[:2]) for p in ends)
    assert ends == [(0.0, 0.0), (30.0, 40.0)]


def test_a_box_and_a_cylinder_written_to_3dm_open_again_as_closed_solids_with_the_same_volume_and_faces(docs, tmp_path):
    src = metric(docs())
    ok(src, "box", corner=[0, 0, 0], size=[10, 20, 30])
    ok(src, "cylinder", center=[100, 0, 0], radius=5, height=40)
    path = tmp_path / "solids.3dm"
    ok(src, "export", path=str(path))
    back = metric(docs())
    ok(back, "import", path=str(path))
    got = sorted((e for e in back.entities() if e["kind"] == "solidbody"), key=lambda e: e["summary"]["faces"])
    assert [(e["summary"]["faces"], e["summary"]["closed"], e["summary"]["valid"]) for e in got] == [(3, True, True), (6, True, True)]
    vols = [back.get("/solids/%d/massprops" % e["handle"])["volume"] for e in got]
    assert vols == pytest.approx([math.pi * 25 * 40, 6000.0], rel=1e-6)


def test_the_3dm_fixture_drawing_exported_and_read_back_keeps_its_seven_objects_meshes_and_layers(docs, fixtures, tmp_path):
    src = docs.open(fixtures / "z2-3dm-mesh.fcad")
    path = tmp_path / "z2.3dm"
    ok(src, "export", path=str(path))
    back = metric(docs())
    out = ok(back, "import", path=str(path))
    assert out["added"]["objects"] == 7
    ents = {e["name"]: e for e in back.entities()}
    assert Counter(e["kind"] for e in ents.values()) == {"solidbody": 3, "meshbody": 3, "nurbscurve": 1}
    assert (ents["Box mesh"]["summary"]["triangles"], ents["Box mesh"]["summary"]["closed"]) == (12, True)
    assert ents["Box mesh"]["summary"]["volume"] == pytest.approx(24000.0, rel=1e-6)
    assert (ents["Sphere mesh"]["summary"]["triangles"], ents["Sphere mesh"]["summary"]["closed"]) == (3664, True)
    assert (ents["soup"]["summary"]["naked_edges"], ents["soup"]["summary"]["naked_loops"]) == (4, 1)
    assert all(ents[n]["summary"]["faces"] == 1 for n in ("Surface A", "Surface B", "Blend A-B"))
    assert (ents["Curve"]["layer"], ents["Curve"]["degree"]) == ("Curves3dm", 3)
    assert ents["Box mesh"]["layer"] == ents["Sphere mesh"]["layer"] == "Meshes"
