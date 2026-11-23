import math

from tests.electronics.kit import board, label, nets, netlist, pad_nets, part, place, schematic, smd, wire, world

PADS = [smd(1, -2.0, 0.0, 1.0, 0.6), smd(2, 2.0, 0.0, 1.0, 0.6)]


def divider(doc):
    schematic(doc, part("R", 0, 0, value="10k"), part("R", 20, -20, value="10k"), part("LED", 60, -40), wire("R1.2", "R2.1"), wire("R2.2", "D1.2"), label("R1.1", "LOOP"), label("D1.1", "LOOP"))
    board(doc, (0, 0, 40, 30))
    return doc.post("/pcb/sync")


def test_footprints_placed_from_the_schematic_carry_the_library_pads_and_the_schematic_nets(doc):
    report = divider(doc)
    assert sorted(report["added"]) == ["D1", "R1", "R2"] and report["missing"] == []
    want = {}
    for n, pins in nets(doc.get("/ecad/netlist")).items():
        for p in pins:
            want[tuple(p.split("."))] = n
    placed = doc.get("/pcb")["parts"]
    for p in placed:
        lib = doc.get("/ecad/library/footprints/%s" % p["footprint"])["pads"]
        assert sorted((q["number"], q["pos"][0], q["pos"][1], q["size"][0], q["size"][1]) for q in lib) == sorted((q["number"], q["x"], q["y"], q["w"], q["h"]) for q in p["pads"])
    assert {k: v for k, v in pad_nets(doc).items()} == want
    assert {p["refdes"]: p["footprint"] for p in placed} == {"R1": "CHIP-0603", "R2": "CHIP-0603", "D1": "CHIP-0805"}


def test_every_placed_footprint_lies_inside_the_board_outline(doc):
    divider(doc)
    for p in doc.get("/pcb")["parts"]:
        for q in p["pads"]:
            x, y = world(p["x"], p["y"], (q["x"], q["y"]), p["rot"], p["side"])
            assert 0 < x - q["w"] / 2 and x + q["w"] / 2 < 40 and 0 < y - q["h"] / 2 and y + q["h"] / 2 < 30


def test_a_hand_routed_track_between_two_pads_removes_that_net_from_the_ratsnest(doc):
    board(doc)
    netlist(doc, {"N1": ["U1.2", "U2.1"], "N2": ["U1.1", "U2.2"]})
    place(doc, "U1", 10, 10, PADS)
    place(doc, "U2", 20, 10, PADS)
    before = doc.get("/pcb/ratsnest")["ratsnest"]
    assert sorted(r["net"] for r in before) == ["N1", "N2"]
    n1 = next(r for r in before if r["net"] == "N1")
    assert math.isclose(n1["length"], 6.0, abs_tol=1e-6)
    doc.post("/pcb/tracks", {"net": "N1", "layer": "F.Cu", "width": 0.3, "a": [12, 10], "b": [18, 10]})
    assert [r["net"] for r in doc.get("/pcb/ratsnest")["ratsnest"]] == ["N2"]


def test_a_track_that_stops_short_of_its_pad_leaves_the_net_unconnected(doc):
    board(doc)
    netlist(doc, {"N1": ["U1.2", "U2.1"]})
    place(doc, "U1", 10, 10, PADS)
    place(doc, "U2", 20, 10, PADS)
    doc.post("/pcb/tracks", {"net": "N1", "layer": "F.Cu", "width": 0.3, "a": [12, 10], "b": [16.5, 10]})
    assert [r["net"] for r in doc.get("/pcb/ratsnest")["ratsnest"]] == ["N1"]


def test_autorouting_every_net_brings_the_ratsnest_to_zero_and_the_tracks_join_each_nets_pads(doc):
    divider(doc)
    assert len(doc.get("/pcb/ratsnest")["ratsnest"]) == 3
    routed = doc.post("/pcb/route")
    assert routed["nets_routed"] == routed["nets_total"] == 3 and routed["failed"] == {}
    assert doc.get("/pcb/ratsnest")["ratsnest"] == []
    data = doc.get("/pcb")
    parent = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            k = parent[k]
        return k

    def join(a, b):
        parent[find(a)] = find(b)

    pads = []
    for p in data["parts"]:
        for q in p["pads"]:
            pads.append(((p["refdes"], q["number"]), world(p["x"], p["y"], (q["x"], q["y"]), p["rot"], p["side"]), q, q["net"]))
    ends = []
    for t in data["tracks"]:
        a, b = (round(t["a"][0], 6), round(t["a"][1], 6), t["layer"]), (round(t["b"][0], 6), round(t["b"][1], 6), t["layer"])
        join(a, b)
        ends += [(a, t["net"]), (b, t["net"])]
    for key, (x, y), q, net in pads:
        for end, tnet in ends:
            if abs(end[0] - x) <= q["w"] / 2 + 1e-9 and abs(end[1] - y) <= q["h"] / 2 + 1e-9 and end[2] == "F.Cu":
                assert tnet == net
                join(key, end)
    by_net = {}
    for key, _xy, _q, net in pads:
        by_net.setdefault(net, set()).add(find(key))
    assert all(len(roots) == 1 for roots in by_net.values())
    assert doc.get("/pcb/drc")["errors"] == 0


def test_moving_a_part_keeps_its_pad_nets_and_moves_its_ratsnest_end_by_the_same_amount(doc):
    board(doc)
    netlist(doc, {"N1": ["U1.2", "U2.1"]})
    place(doc, "U1", 10, 10, PADS)
    place(doc, "U2", 20, 10, PADS)
    nets_before = pad_nets(doc)
    doc.engine.patch(doc.url("/pcb/parts/U2"), {"x": 25.0, "y": 14.0})
    assert pad_nets(doc) == nets_before
    line = doc.get("/pcb/ratsnest")["ratsnest"][0]
    ends = {tuple(line["a"]), tuple(line["b"])}
    assert ends == {(12.0, 10.0), (23.0, 14.0)}
    assert math.isclose(line["length"], math.hypot(11.0, 4.0), abs_tol=1e-4)


def test_a_pad_of_a_rotated_part_lies_where_the_rotation_puts_it(doc):
    board(doc)
    netlist(doc, {"N1": ["U1.2", "U2.1"]})
    place(doc, "U1", 10, 10, PADS, rot=90.0)
    place(doc, "U2", 20, 20, PADS)
    line = doc.get("/pcb/ratsnest")["ratsnest"][0]
    assert {tuple(line["a"]), tuple(line["b"])} == {(10.0, 12.0), (18.0, 20.0)}
