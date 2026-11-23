import pytest

pytestmark = pytest.mark.kernel

L, W, H = 40.0, 20.0, 10.0


def size(view):
    x0, y0, x1, y1 = view["bounds"]
    return (round(x1 - x0, 6), round(y1 - y0, 6))


@pytest.fixture
def boxed(mm):
    state = mm.command("box", size=[L, W, H], corner=[0, 0, 0])
    assert not state["error"], state["error"]
    return mm


def base(doc, direction="front", scale="1:2", position=(120, 150)):
    view = doc.post("/drawviews", {"type": "base", "layout": "Layout1", "direction": direction, "scale": scale, "position": list(position)})
    assert view["state"]["status"] == "ok", view["state"]
    return view


@pytest.mark.parametrize("direction, outline", [("front", (L, H)), ("top", (L, W)), ("right", (W, H))])
def test_a_base_view_of_a_box_has_the_outline_of_the_face_it_looks_at_times_the_scale(boxed, direction, outline):
    view = base(boxed, direction, "1:2")
    assert size(view) == pytest.approx((outline[0] * 0.5, outline[1] * 0.5), abs=1e-6)


def test_views_projected_from_a_front_view_show_the_top_and_side_and_line_up_with_it(boxed):
    front = base(boxed, "front", "1:2")
    top = boxed.post("/drawviews", {"type": "projected", "parent": front["handle"], "rel": "top"})
    side = boxed.post("/drawviews", {"type": "projected", "parent": front["handle"], "rel": "right"})
    assert size(top) == pytest.approx((L * 0.5, W * 0.5), abs=1e-6)
    assert size(side) == pytest.approx((W * 0.5, H * 0.5), abs=1e-6)
    fx0, fy0, fx1, fy1 = front["bounds"]
    assert top["bounds"][0] == pytest.approx(fx0) and top["bounds"][2] == pytest.approx(fx1)
    assert top["bounds"][1] > fy1
    assert side["bounds"][1] == pytest.approx(fy0) and side["bounds"][3] == pytest.approx(fy1)
    assert side["bounds"][0] > fx1
    assert top["scaleText"] == side["scaleText"] == "1:2"


@pytest.mark.parametrize("scale, factor", [("1:1", 1.0), ("2:1", 2.0), ("1:4", 0.25)])
def test_the_view_scale_sets_the_size_of_the_outline_on_paper(boxed, scale, factor):
    view = base(boxed, "front", scale, position=(200, 150))
    assert size(view) == pytest.approx((L * factor, H * factor), abs=1e-6)


def test_changing_the_scale_of_a_view_resizes_its_outline(boxed):
    front = base(boxed, "front", "1:2")
    boxed.engine.patch(boxed.url("/drawviews/%d" % front["handle"]), {"changes": {"scale": "1:1"}})
    again = boxed.get("/drawviews/%d" % front["handle"])
    assert again["scaleText"] == "1:1"
    assert size(again) == pytest.approx((L, H), abs=1e-6)


def test_a_section_through_the_middle_of_a_box_shows_a_cut_face_of_its_cross_section(boxed):
    top = base(boxed, "top", "1:2")
    sec = boxed.post("/drawviews", {"type": "section", "parent": top["handle"], "line": [[0, -30], [0, 30]], "position": [250, 150]})
    assert sec["state"]["status"] == "ok" and sec["section"]["letter"] == "A"
    assert size(sec) == pytest.approx((W * 0.5, H * 0.5), abs=1e-6)
    faces = boxed.get("/drawviews/%d" % sec["handle"], cache=True)["cache"]["faces"]
    assert len(faces) == 1 and faces[0]["holes"] == []
    assert faces[0]["area"] == pytest.approx(W * H, rel=1e-9)


def test_section_hatching_fills_the_cut_face_at_the_view_scale(boxed):
    from tests.support import geometry

    top = base(boxed, "top", "1:2")
    sec = boxed.post("/drawviews", {"type": "section", "parent": top["handle"], "line": [[0, -30], [0, 30]], "position": [250, 150]})
    boxed.post("/space", {"tab": "Layout1"})
    state = boxed.command("sectionhatch", view=sec["handle"])
    assert not state["error"], state["error"]
    hatches = [e for e in boxed.entities("hatch") if e["handle"] in state["result"]["created"]]
    assert len(hatches) == 1
    ring = [v["p"] for v in hatches[0]["loops"][0]["vertices"]]
    assert geometry.area(ring) == pytest.approx(W * H * 0.25, rel=1e-9)
    x0, y0, x1, y1 = sec["bounds"]
    assert all(x0 - 1e-6 <= p[0] <= x1 + 1e-6 and y0 - 1e-6 <= p[1] <= y1 + 1e-6 for p in ring)


def test_a_section_through_a_hole_shows_the_cut_face_split_by_the_hole(boxed):
    state = boxed.command("cylinder", center=[20, 10, -1], radius=4, height=12)
    assert not state["error"], state["error"]
    pin = state["result"]["handle"]
    block = [e for e in boxed.entities("solidbody") if e["handle"] != pin][0]["handle"]
    state = boxed.command("subtract", **{"from": [block], "subtract": [pin]})
    assert not state["error"], state["error"]
    top = base(boxed, "top", "1:1", position=(120, 150))
    sec = boxed.post("/drawviews", {"type": "section", "parent": top["handle"], "line": [[0, -30], [0, 30]], "position": [250, 150]})
    faces = boxed.get("/drawviews/%d" % sec["handle"], cache=True)["cache"]["faces"]
    assert len(faces) == 2
    assert sum(f["area"] for f in faces) == pytest.approx((W - 8.0) * H, rel=1e-6)


def test_a_detail_view_shows_its_circular_region_at_its_own_scale(boxed):
    front = base(boxed, "front", "1:1", position=(120, 150))
    det = boxed.post("/drawviews", {"type": "detail", "parent": front["handle"], "center": [20, 5], "radius": 3, "scale": "2:1", "position": [300, 150]})
    assert det["state"]["status"] == "ok"
    assert det["scaleText"] == "2:1"
    assert size(det) == pytest.approx((2 * 3 * 2.0, 2 * 3 * 2.0), abs=1e-6)


def test_a_hole_seen_side_on_in_a_front_view_is_drawn_as_two_hidden_lines_at_its_diameter(boxed):
    state = boxed.command("cylinder", center=[20, 10, -1], radius=4, height=12)
    pin = state["result"]["handle"]
    block = [e for e in boxed.entities("solidbody") if e["handle"] != pin][0]["handle"]
    boxed.command("subtract", **{"from": [block], "subtract": [pin]})
    front = base(boxed, "front", "1:1", position=(120, 150))
    classes = boxed.get("/drawviews/%d" % front["handle"], cache=True)["cache"]["classes"]
    hidden = [s for k, v in classes.items() if k.endswith("_h") for s in v if s["t"] == "line"]
    upright = sorted(round(s["a"][0], 6) for s in hidden if abs(s["a"][0] - s["b"][0]) < 1e-9 and abs(abs(s["a"][1] - s["b"][1]) - H) < 1e-6)
    assert {-4.0, 4.0} <= set(upright)
    visible = [s for k, v in classes.items() if k.endswith("_v") for s in v]
    assert not any(s["t"] == "line" and abs(abs(s["a"][0]) - 4.0) < 1e-6 and abs(s["a"][0] - s["b"][0]) < 1e-9 for s in visible)
