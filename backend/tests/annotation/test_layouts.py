import pytest

from tests.support import geometry

A4 = "ISO A4 (210.00 x 297.00 MM)"
A3 = "ISO A3 (297.00 x 420.00 MM)"


def new_sheet(doc, name, paper=A4, landscape=True):
    doc.post("/layouts", {"action": "new", "name": name})
    doc.put("/layouts/%s/pagesetup" % name, {"paper": paper, "orientation": "landscape" if landscape else "portrait"})
    doc.post("/space", {"tab": name})
    for vp in doc.get("/viewports", layout=name)["viewports"]:
        doc.command("erase", handles=[vp["h"]])


def viewport(doc, corners, scale, centre):
    state = doc.command("mview", corners=corners)
    assert not state["error"], state["error"]
    h = state["result"]["created"][0]
    doc.put("/viewports/%d" % h, {"scale": scale})
    doc.post("/viewports/%d/view" % h, {"center": centre, "height": (corners[1][1] - corners[0][1]) * _ratio(scale)})
    return h


def _ratio(scale):
    a, b = scale.split(":")
    return float(b) / float(a)


def items_of(layout, vp):
    for v in layout["viewports"]:
        if v["h"] == vp:
            return v["items"]
    raise AssertionError("viewport %s not in the layout" % vp)


@pytest.mark.parametrize("paper, landscape, size", [(A4, True, (297.0, 210.0)), (A4, False, (210.0, 297.0)), (A3, True, (420.0, 297.0))])
def test_a_new_layout_takes_the_paper_size_and_orientation_it_was_given(mm, paper, landscape, size):
    mm.post("/layouts", {"action": "new", "name": "Sheet"})
    ps = mm.put("/layouts/Sheet/pagesetup", {"paper": paper, "orientation": "landscape" if landscape else "portrait"})
    assert (ps["width"], ps["height"]) == size
    listed = [l for l in mm.get("/layouts")["layouts"] if l["name"] == "Sheet"]
    assert len(listed) == 1 and (listed[0]["width"], listed[0]["height"]) == size


def test_the_printable_area_of_a_layout_is_the_paper_less_its_margins(mm):
    mm.post("/layouts", {"action": "new", "name": "Sheet"})
    mm.put("/layouts/Sheet/pagesetup", {"paper": A4, "orientation": "landscape", "margins": [10, 5, 7, 12]})
    got = mm.get("/layouts/Sheet/pagesetup")
    assert got["sheet"] == [297.0, 210.0]
    assert got["printable"] == pytest.approx([10.0, 5.0, 290.0, 198.0])


def test_an_unknown_paper_is_refused_and_the_page_setup_is_unchanged(mm, engine):
    mm.post("/layouts", {"action": "new", "name": "Sheet"})
    mm.put("/layouts/Sheet/pagesetup", {"paper": A4})
    r = engine.raw("PUT", mm.url("/layouts/Sheet/pagesetup"), json={"paper": "Napkin"})
    assert r.status_code == 400 and "Napkin" in r.text
    assert mm.get("/layouts/Sheet/pagesetup")["paper"] == A4


@pytest.mark.parametrize("scale, factor", [("1:2", 0.5), ("1:1", 1.0), ("2:1", 2.0), ("1:5", 0.2)])
def test_a_viewport_at_a_scale_draws_model_lengths_times_that_scale_on_paper(mm, scale, factor):
    mm.type("LINE", "0,0", "100,0", "")
    line = mm.only("line")["handle"]
    new_sheet(mm, "Sheet")
    vp = viewport(mm, [[20, 20], [270, 190]], scale, [50, 0])
    info = [v for v in mm.get("/viewports", layout="Sheet")["viewports"] if v["h"] == vp][0]
    assert info["scaleText"] == scale
    item = [i for i in items_of(mm.get("/layouts/Sheet"), vp) if i["h"] == line][0]
    g = item["geom"]
    assert geometry.close(geometry.dist(g["p1"], g["p2"]), 100.0 * factor, 1e-9)
    mid = ((g["p1"][0] + g["p2"][0]) / 2.0, (g["p1"][1] + g["p2"][1]) / 2.0)
    assert geometry.same_point(mid, (145.0, 105.0))


def test_a_layer_frozen_in_one_viewport_stays_visible_in_another(mm):
    mm.type("-LAYER", "N", "HIDDEN", "")
    mm.type("LINE", "0,0", "100,0", "")
    kept = mm.only("line")["handle"]
    mm.command("chprop", handles=[kept], layer="HIDDEN")
    mm.type("CIRCLE", "50,20", "10")
    circle = mm.only("circle")["handle"]
    new_sheet(mm, "Sheet")
    left = viewport(mm, [[10, 10], [140, 200]], "1:1", [50, 10])
    right = viewport(mm, [[150, 10], [287, 200]], "1:1", [50, 10])
    state = mm.command("vplayer", option="freeze", layers=["HIDDEN"], viewports=[left])
    assert not state["error"], state["error"]
    layout = mm.get("/layouts/Sheet")
    assert {i["h"] for i in items_of(layout, left)} == {circle}
    assert {i["h"] for i in items_of(layout, right)} == {kept, circle}
    assert [v["frozen"] for v in layout["viewports"] if v["h"] == left][0] == ["HIDDEN"]


def test_thawing_the_layer_in_the_viewport_brings_its_objects_back(mm):
    mm.type("-LAYER", "N", "HIDDEN", "")
    mm.type("LINE", "0,0", "100,0", "")
    kept = mm.only("line")["handle"]
    mm.command("chprop", handles=[kept], layer="HIDDEN")
    new_sheet(mm, "Sheet")
    vp = viewport(mm, [[10, 10], [140, 200]], "1:1", [50, 0])
    mm.command("vplayer", option="freeze", layers=["HIDDEN"], viewports=[vp])
    assert items_of(mm.get("/layouts/Sheet"), vp) == []
    mm.command("vplayer", option="thaw", layers=["HIDDEN"], viewports=[vp])
    assert [i["h"] for i in items_of(mm.get("/layouts/Sheet"), vp)] == [kept]


def test_a_layout_saved_and_reopened_keeps_its_paper_and_viewport_scale(mm, docs, tmp_path):
    mm.type("LINE", "0,0", "100,0", "")
    new_sheet(mm, "Sheet")
    vp = viewport(mm, [[20, 20], [270, 190]], "1:2", [50, 0])
    path = tmp_path / "sheet.fcad"
    mm.save(path)
    again = docs.open(path)
    ps = again.get("/layouts/Sheet/pagesetup")
    assert (ps["paper"], ps["width"], ps["height"]) == (A4, 297.0, 210.0)
    vps = again.get("/viewports", layout="Sheet")["viewports"]
    assert [v["scaleText"] for v in vps if v["h"] == vp] == ["1:2"]
