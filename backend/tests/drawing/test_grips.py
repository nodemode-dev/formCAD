from tests.support import geometry


def grip(doc, handle, gid, to, mode="stretch"):
    return doc.post("/grip", {"handle": handle, "grip": gid, "mode": mode, "to": list(to)})


def grip_at(doc, handle, kind):
    sets = doc.get("/grips", handles=str(handle))["sets"]
    return [g for g in sets[0]["grips"] if g["kind"] == kind]


def test_dragging_a_line_end_grip_moves_only_that_end(doc):
    doc.type("LINE", "0,0", "10,0", "")
    line = doc.only("line")
    end = [g for g in grip_at(doc, line["handle"], "end") if geometry.same_point(g["p"], (10, 0))][0]
    grip(doc, line["handle"], end["id"], (12, 5))
    moved = doc.only("line")
    assert geometry.same_point(moved["start"], (0, 0)) and geometry.same_point(moved["end"], (12, 5))


def test_dragging_a_circle_quadrant_grip_changes_only_the_radius(doc):
    doc.type("CIRCLE", "2,3", "5")
    circle = doc.only("circle")
    quads = grip_at(doc, circle["handle"], "quadrant")
    assert sorted((round(q["p"][0], 9), round(q["p"][1], 9)) for q in quads) == [(-3, 3), (2, -2), (2, 8), (7, 3)]
    top = [q for q in quads if geometry.same_point(q["p"], (2, 8))][0]
    grip(doc, circle["handle"], top["id"], (2, 11))
    after = doc.only("circle")
    assert geometry.same_point(after["center"], (2, 3)) and geometry.close(after["radius"], 8.0)


def test_a_grip_edit_is_one_undo_step_that_restores_the_object(doc):
    doc.type("CIRCLE", "2,3", "5")
    before = doc.only("circle")
    centre = grip_at(doc, before["handle"], "center")[0]
    grip(doc, before["handle"], centre["id"], (10, 10))
    assert geometry.same_point(doc.only("circle")["center"], (10, 10))
    doc.undo()
    assert doc.only("circle") == before
