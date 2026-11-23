import json

from tests.electronics.kit import board, label, output_board, pad_nets, part, schematic, wire


def design(doc):
    schematic(doc, part("R", 0, 0, value="10k"), part("R", 20, -20, value="4k7"), part("LED", 60, -40, value="red"), wire("R1.2", "R2.1"), wire("R2.2", "D1.2"), label("R1.1", "VIN"), label("D1.1", "VIN"))
    board(doc, (0, 0, 40, 30))
    doc.post("/pcb/sync")


def without_rev(d):
    return {k: v for k, v in d.items() if k != "rev"}


def test_a_netlist_written_to_a_file_and_read_into_a_new_board_gives_the_same_parts_and_pad_nets(docs, tmp_path):
    a = docs()
    design(a)
    path = tmp_path / "design.json"
    a.post("/ecad/export/netlist", {"path": str(path), "format": "json"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(c["ref"] for c in data["components"]) == ["D1", "R1", "R2"]
    b = docs()
    board(b, (0, 0, 40, 30))
    b.post("/pcb/netlist", {"nets": [{"name": n["name"], "pins": n["nodes"]} for n in data["nets"]], "parts": [{"refdes": c["ref"], "footprint": c["footprint"], "value": c["value"]} for c in data["components"]]})
    for p in a.get("/pcb")["parts"]:
        b.post("/pcb/parts", {k: p[k] for k in ("refdes", "footprint", "value", "x", "y", "rot", "side")} | {"pads": [{k: q[k] for k in ("number", "shape", "x", "y", "w", "h")} for q in p["pads"]]})
    assert pad_nets(b) == pad_nets(a)
    assert {p["refdes"]: (p["x"], p["y"], p["value"]) for p in b.get("/pcb")["parts"]} == {p["refdes"]: (p["x"], p["y"], p["value"]) for p in a.get("/pcb")["parts"]}
    assert b.get("/pcb/ratsnest") == a.get("/pcb/ratsnest")


def test_undo_of_schematic_edits_restores_the_sheet_and_netlist_exactly_and_redo_reapplies_them(doc):
    schematic(doc, part("R", 0, 0, value="1k"), part("R", 10, 0, value="1k"))
    before = (without_rev(doc.get("/ecad")), doc.get("/ecad/netlist"), doc.get("/ecad/sheets/S1/scene")["wires"])
    doc.post("/ecad/ops", wire("R1.1", "R2.1"))
    doc.post("/ecad/ops", {"op": "move_part", "part": "R2", "delta": [0, 2.54]})
    doc.post("/ecad/ops", {"op": "set_part", "part": "R1", "value": "2k2"})
    after = (without_rev(doc.get("/ecad")), doc.get("/ecad/netlist"), doc.get("/ecad/sheets/S1/scene")["wires"])
    assert after != before
    doc.undo(3)
    assert (without_rev(doc.get("/ecad")), doc.get("/ecad/netlist"), doc.get("/ecad/sheets/S1/scene")["wires"]) == before
    doc.redo(3)
    assert (without_rev(doc.get("/ecad")), doc.get("/ecad/netlist"), doc.get("/ecad/sheets/S1/scene")["wires"]) == after


def test_undo_of_board_edits_restores_the_board_exactly_and_redo_reapplies_them(doc):
    output_board(doc)
    before = doc.get("/pcb")
    doc.engine.patch(doc.url("/pcb/parts/U1"), {"x": 14.0, "y": 6.0, "rot": 45.0})
    doc.post("/pcb/tracks", {"net": "C", "layer": "B.Cu", "width": 0.25, "a": [21.5, 10.5], "b": [21.5, 20]})
    doc.post("/pcb/vias", {"net": "C", "x": 21.5, "y": 20.0})
    doc.delete("/pcb/parts/J1")
    after = doc.get("/pcb")
    doc.undo(4)
    assert doc.get("/pcb") == before
    doc.redo(4)
    assert doc.get("/pcb") == after


def test_saving_and_reopening_keeps_the_schematic_the_board_and_the_routing(docs, tmp_path):
    a = docs()
    design(a)
    a.post("/pcb/route")
    path = tmp_path / "design.fcad"
    a.save(path)
    b = docs.open(path)
    assert without_rev(b.get("/ecad")) == without_rev(a.get("/ecad"))
    assert b.get("/ecad/netlist") == a.get("/ecad/netlist")
    assert b.get("/pcb") == a.get("/pcb")
    assert b.get("/pcb/ratsnest")["ratsnest"] == []
