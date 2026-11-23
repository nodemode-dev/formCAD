import math

import pytest

from tests.electronics.kit import board, netlist, place, smd, tht

RULES = {"clearance": 0.2, "track_width": 0.25, "drill": 0.4, "annular_ring": 0.15, "hole_to_hole": 0.5, "edge_clearance": 0.5, "via_dia": 0.8, "via_drill": 0.4}


def track(doc, net, a, b, width=0.3, layer="F.Cu"):
    return doc.post("/pcb/tracks", {"net": net, "layer": layer, "width": width, "a": list(a), "b": list(b)})


def kinds(result):
    return sorted(v["type"] for v in result["violations"] if v["severity"] == "error")


def clean(doc):
    board(doc, (0, 0, 30, 20), RULES)
    netlist(doc, {"A": ["U1.1", "U2.1"], "B": ["U1.2", "U2.2"]})
    pads = [smd(1, 0.0, 1.0, 1.0, 0.8), smd(2, 0.0, -1.0, 1.0, 0.8)]
    place(doc, "U1", 8, 10, pads)
    place(doc, "U2", 22, 10, pads)
    track(doc, "A", (8, 11), (22, 11))
    track(doc, "B", (8, 9), (22, 9))
    doc.post("/pcb/holes", {"x": 4, "y": 4, "drill": 3.0})
    doc.post("/pcb/vias", {"net": "A", "x": 15, "y": 15, "dia": 0.8, "drill": 0.4})
    track(doc, "A", (15, 11), (15, 15))


def test_a_routed_board_that_keeps_every_rule_passes_the_design_rule_check(doc):
    clean(doc)
    result = doc.get("/pcb/drc")
    assert result["violations"] == []
    assert result["passed"] is True and result["errors"] == 0


def test_two_tracks_of_different_nets_closer_than_the_clearance_are_reported_with_the_gap(doc):
    clean(doc)
    track(doc, "A", (8, 3), (20, 3))
    track(doc, "B", (8, 3.45), (20, 3.45))
    result = doc.get("/pcb/drc")
    hits = [v for v in result["violations"] if v["type"] == "clearance"]
    assert len(hits) == 1
    assert math.isclose(hits[0]["value"], 0.45 - 0.3, abs_tol=1e-4)
    assert math.isclose(hits[0]["limit"], 0.2, abs_tol=1e-9)
    assert result["passed"] is False


def test_tracks_of_different_nets_at_exactly_the_clearance_are_allowed(doc):
    clean(doc)
    track(doc, "A", (8, 3), (20, 3))
    track(doc, "B", (8, 3.5), (20, 3.5))
    assert doc.get("/pcb/drc")["violations"] == []


def test_overlapping_copper_of_different_nets_is_reported_as_a_short(doc):
    clean(doc)
    track(doc, "A", (8, 3), (20, 3))
    track(doc, "B", (12, 1), (12, 6))
    assert "short" in kinds(doc.get("/pcb/drc"))


def test_tracks_of_the_same_net_may_touch(doc):
    clean(doc)
    track(doc, "A", (8, 3), (20, 3))
    track(doc, "A", (12, 3), (12, 6))
    assert [v for v in doc.get("/pcb/drc")["violations"] if v["type"] in ("short", "clearance")] == []


def test_a_track_narrower_than_the_minimum_width_is_reported_with_its_width(doc):
    clean(doc)
    made = track(doc, "A", (8, 3), (20, 3), width=0.2)
    hits = [v for v in doc.get("/pcb/drc")["violations"] if v["type"] == "track_width"]
    assert len(hits) == 1 and hits[0]["items"] == [made["id"]]
    assert math.isclose(hits[0]["value"], 0.2, abs_tol=1e-9) and math.isclose(hits[0]["limit"], 0.25, abs_tol=1e-9)


@pytest.mark.parametrize("what", ["hole", "via", "pad"])
def test_a_hole_smaller_than_the_minimum_drill_is_reported(doc, what):
    clean(doc)
    if what == "hole":
        doc.post("/pcb/holes", {"x": 26, "y": 4, "drill": 0.3})
    elif what == "via":
        doc.post("/pcb/vias", {"net": "B", "x": 26, "y": 4, "dia": 0.8, "drill": 0.3})
    else:
        place(doc, "J1", 26, 4, [tht(1, 0, 0, 1.0, 0.3)])
    hits = [v for v in doc.get("/pcb/drc")["violations"] if v["type"] == "drill"]
    assert len(hits) == 1
    assert math.isclose(hits[0]["value"], 0.3, abs_tol=1e-9) and math.isclose(hits[0]["limit"], 0.4, abs_tol=1e-9)
    assert hits[0]["at"] == [26, 4]


def test_a_via_whose_copper_ring_is_thinner_than_the_annular_ring_rule_is_reported(doc):
    clean(doc)
    doc.post("/pcb/vias", {"net": "B", "x": 26, "y": 4, "dia": 0.6, "drill": 0.4})
    hits = [v for v in doc.get("/pcb/drc")["violations"] if v["type"] == "annular_ring"]
    assert len(hits) == 1 and math.isclose(hits[0]["value"], 0.1, abs_tol=1e-9)


def test_copper_closer_to_the_board_edge_than_the_edge_rule_is_reported(doc):
    clean(doc)
    track(doc, "A", (5, 0.6), (12, 0.6))
    hits = [v for v in doc.get("/pcb/drc")["violations"] if v["type"] == "edge_clearance"]
    assert len(hits) == 1 and math.isclose(hits[0]["value"], 0.6 - 0.15, abs_tol=1e-4)


def test_an_unrouted_net_fails_the_check_as_unconnected(doc):
    clean(doc)
    doc.delete("/pcb/nets/B/copper")
    result = doc.get("/pcb/drc")
    assert kinds(result) == ["unconnected"]
    assert sorted(result["violations"][0]["items"]) == ["U1.2", "U2.2"]


def test_two_holes_closer_edge_to_edge_than_the_hole_spacing_rule_are_reported_with_the_gap(doc):
    clean(doc)
    doc.post("/pcb/holes", {"x": 24, "y": 4, "drill": 1.0})
    doc.post("/pcb/holes", {"x": 25.3, "y": 4, "drill": 1.0})
    hits = [v for v in doc.get("/pcb/drc")["violations"] if v["type"] == "hole_to_hole"]
    assert len(hits) == 1 and math.isclose(hits[0]["value"], 1.3 - 1.0, abs_tol=1e-6)


def test_choosing_a_rule_profile_applies_the_clearance_that_profile_states(doc):
    clean(doc)
    doc.put("/pcb/rules", {"profile": "generic"})
    profiles = doc.get("/pcb/rules")["profiles"]
    loose = profiles["generic"]["values"]["clearance"]["value"]
    tight_id, tight = min(((k, p["values"]["clearance"]["value"]) for k, p in profiles.items()), key=lambda kv: kv[1])
    assert tight < loose
    gap = (tight + loose) / 2
    track(doc, "A", (8, 3), (20, 3), width=0.3)
    track(doc, "B", (8, 3 + 0.3 + gap), (20, 3 + 0.3 + gap), width=0.3)
    assert [v["type"] for v in doc.get("/pcb/drc")["violations"]] == ["clearance"]
    doc.put("/pcb/rules", {"profile": tight_id})
    assert [v for v in doc.get("/pcb/drc")["violations"] if v["type"] == "clearance"] == []
    assert all(v["source"] for p in profiles.values() for v in p["values"].values() if not v["fallback"])
