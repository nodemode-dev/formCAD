def lamp_circuit(doc, open_lamp=False):
    for kind, x, ref in (("source", 0, "G1"), ("fuse", 40, "F1"), ("lamp", 80, "H1"), ("ground", 40, "PE1")):
        doc.post("/schem/devices", {"type": kind, "refdes": ref, "x": x, "y": 0 if kind != "ground" else -40})
    rows = [("W1", "G1", "+", "F1", "1"), ("W2", "F1", "2", "H1", "X1"), ("W4", "G1", "-", "PE1", "1")]
    if not open_lamp:
        rows.insert(2, ("W3", "H1", "X2", "PE1", "1"))
    for name, a, pa, b, pb in rows:
        doc.post("/schem/wires", {"wire": name, "from": {"device": a, "pin": pa}, "to": {"device": b, "pin": pb}, "gauge": "1.5", "colour": "BK"})


def test_wires_meeting_at_a_pin_share_one_number_and_separate_nodes_get_separate_numbers(doc):
    lamp_circuit(doc)
    doc.post("/schem/number", {"template": "{prefix}{seq}", "prefix": "N", "keep_manual": False})
    rows = {r["name"]: r for r in doc.get("/schem/wirelist")["rows"]}
    number = {n: rows[n]["number"] for n in ("W1", "W2", "W3", "W4")}
    assert number["W3"] == number["W4"]
    assert len({number["W1"], number["W2"], number["W3"]}) == 3
    assert all(v.startswith("N") for v in number.values())
    assert [p for p in doc.get("/schem/check")["problems"] if p["severity"] == "error"] == []


def test_the_wire_list_names_both_ends_of_every_wire_by_device_and_pin(doc):
    lamp_circuit(doc)
    rows = {r["name"]: {r["from"], r["to"]} for r in doc.get("/schem/wirelist")["rows"]}
    assert rows == {"W1": {"G1:+", "F1:1"}, "W2": {"F1:2", "H1:X1"}, "W3": {"H1:X2", "PE1"}, "W4": {"G1:-", "PE1"}}


def test_the_schematic_check_reports_a_device_pin_with_no_wire(doc):
    lamp_circuit(doc, open_lamp=True)
    problems = [p for p in doc.get("/schem/check")["problems"] if p["code"] == "open_pin"]
    assert len(problems) == 1 and "H1" in problems[0]["message"] and "X2" in problems[0]["message"]
    doc.post("/schem/wires", {"wire": "W3", "from": {"device": "H1", "pin": "X2"}, "to": {"device": "PE1", "pin": "1"}})
    assert [p for p in doc.get("/schem/check")["problems"] if p["code"] == "open_pin"] == []


def test_matching_the_schematic_to_harness_wires_finds_a_swapped_end_and_a_missing_wire(doc):
    lamp_circuit(doc)
    harness = [
        {"name": "W1", "from": "F1:1", "to": "G1:+", "gauge": "1.5", "colour": "BK"},
        {"name": "W2", "from": "F1:2", "to": "H1:X2", "gauge": "1.5", "colour": "BK"},
        {"name": "W3", "from": "H1:X2", "to": "PE1", "gauge": "1.5", "colour": "BK"},
    ]
    res = doc.post("/schem/compare", {"harness": harness})
    assert res["matched"] == 2
    assert [d["name"] for d in res["differences"]] == ["W2"] and res["differences"][0]["issues"][0]["field"] == "ends"
    assert res["only_schematic"] == ["W4"] and res["only_harness"] == [] and res["ok"] is False
