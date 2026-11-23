from tests.electronics.kit import groups, label, nets, part, schematic, wire


def test_pins_joined_by_a_wire_share_one_net_and_unwired_pins_share_none(doc):
    schematic(doc, part("R", 0, 0), part("R", 10, 0), part("R", 20, 0), wire("R1.1", "R2.1"))
    nl = doc.get("/ecad/netlist")
    assert groups(nl) == {frozenset({"R1.1", "R2.1"})}
    open_pins = {"%s.%s" % (u["ref"], u["pin"]) for u in nl["unconnected"]}
    assert open_pins == {"R1.2", "R2.2", "R3.1", "R3.2"}


def test_pins_carrying_the_same_net_label_are_joined_and_the_net_takes_the_label_name(doc):
    schematic(doc, part("R", 0, 0), part("R", 10, 0), part("R", 20, 0), label("R1.2", "SENSE"), label("R3.1", "SENSE"), label("R2.2", "OTHER"))
    table = nets(doc.get("/ecad/netlist"))
    assert table["SENSE"] == frozenset({"R1.2", "R3.1"})
    assert all("R2.2" not in pins or name == "OTHER" for name, pins in table.items())
    assert "R2.2" not in table["SENSE"]


def test_the_netlist_lists_every_connection_of_a_divider_and_led_with_power_symbols(doc):
    schematic(
        doc,
        part("R", 0, 0, value="10k"), part("R", 20, -20, value="4k7"), part("R", 40, 0, value="1k"), part("LED", 60, -40),
        {"op": "power_at", "pin": "R1.1", "net": "+5V"}, {"op": "power_at", "pin": "R3.1", "net": "+5V"},
        {"op": "power_at", "pin": "R3.2", "net": "GND", "rotation": 180}, {"op": "power_at", "pin": "D1.1", "net": "GND", "rotation": 180},
        wire("R1.2", "R2.1"), wire("R2.2", "D1.2"),
    )
    nl = doc.get("/ecad/netlist")
    table = nets(nl)
    assert table["+5V"] == frozenset({"R1.1", "R3.1"})
    assert table["GND"] == frozenset({"R3.2", "D1.1"})
    assert groups(nl) == {frozenset({"R1.1", "R3.1"}), frozenset({"R3.2", "D1.1"}), frozenset({"R1.2", "R2.1"}), frozenset({"R2.2", "D1.2"})}
    assert nl["unconnected"] == []
    assert sorted(c["ref"] for c in nl["components"]) == ["D1", "R1", "R2", "R3"]
    assert {c["ref"]: c["value"] for c in nl["components"] if c["ref"] != "D1"} == {"R1": "10k", "R2": "4k7", "R3": "1k"}


def test_moving_a_part_off_its_wire_ends_breaks_the_net_and_moving_it_back_restores_it(doc):
    schematic(doc, part("R", 0, 0), part("R", 10, 0), wire("R1.1", "R2.1"))
    before = doc.get("/ecad/netlist")
    doc.post("/ecad/ops", {"op": "move_part", "part": "R2", "delta": [5.08, 0]})
    moved = doc.get("/ecad/netlist")
    assert not any({"R1.1", "R2.1"} <= g for g in groups(moved))
    assert {"%s.%s" % (u["ref"], u["pin"]) for u in moved["unconnected"]} == {"R1.2", "R2.1", "R2.2"}
    doc.post("/ecad/ops", {"op": "move_part", "part": "R2", "delta": [-5.08, 0]})
    assert doc.get("/ecad/netlist") == before


def test_a_global_label_joins_pins_across_sheets_but_a_local_label_stays_on_its_sheet(doc):
    schematic(doc, {"op": "add_sheet", "name": "Sub"})
    doc.post("/ecad/batch", {"ops": [
        {"op": "add_sheet_symbol", "child": "S2", "pos": [100, 100]},
        part("R", 0, 0), part("R", 10, 0), part("R", 0, 0, sheet="S2"),
        label("R1.1", "CLK", "global"), {"op": "add_label", "pin": "R3.1", "text": "CLK", "kind": "global", "sheet": "S2"},
        label("R1.2", "LOC"), label("R2.2", "LOC"), {"op": "add_label", "pin": "R3.2", "text": "LOC", "kind": "local", "sheet": "S2"},
    ]})
    found = groups(doc.get("/ecad/netlist"))
    assert frozenset({"R1.1", "R3.1"}) in found
    assert frozenset({"R1.2", "R2.2"}) in found
    assert not any("R3.2" in g and "R1.2" in g for g in found)


def test_a_wire_teed_into_the_middle_of_another_wire_with_a_junction_joins_all_three_pins(doc):
    schematic(doc, part("R", 0, 0), part("R", 20, 0), part("R", 10, 20), wire("R1.1", "R2.1"))
    pins = doc.get("/ecad/parts/R3/pins")["placements"][0]["pins"]
    low = next(p["pos"] for p in pins if p["number"] == "2")
    y = doc.get("/ecad/sheets/S1/scene")["wires"][0]["points"][0][1]
    doc.post("/ecad/batch", {"ops": [{"op": "add_wire", "points": [low, [low[0], y]]}, {"op": "add_junction", "pos": [low[0], y]}]})
    assert groups(doc.get("/ecad/netlist")) == {frozenset({"R1.1", "R2.1", "R3.2"})}
