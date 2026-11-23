import json
import math

from tests.support import geometry


def _display(doc):
    return {item["h"]: item for item in json.loads(doc.engine.raw("GET", doc.url("/display")).text)["items"]}


def _make_tick(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("LINE", "0,0", "0,5", "")
    handles = doc.handles()
    doc.post("/blocks", {"name": "Tick", "handles": handles, "base": [0, 0, 0]})
    return handles


def test_a_block_defined_from_two_lines_lists_two_objects_and_no_references(doc):
    _make_tick(doc)
    listed = {b["name"]: b for b in doc.get("/blocks")["blocks"]}
    assert listed["Tick"]["objects"] == 2 and listed["Tick"]["references"] == 0


def test_an_inserted_block_is_drawn_scaled_rotated_and_moved_to_its_insertion_point(doc):
    _make_tick(doc)
    doc.type("-INSERT", "Tick", "100,50", "2", "2", "90")
    insert = doc.only("insert")
    assert insert["block"] == "Tick" and insert["position"][:2] == [100.0, 50.0]
    parts = _display(doc)[insert["handle"]]["geom"]["parts"]
    got = sorted(tuple(tuple(round(v, 9) for v in p[k]) for k in ("p1", "p2")) for p in parts)
    want = []
    for local in (((0, 0), (10, 0)), ((0, 0), (0, 5))):
        ends = []
        for x, y in local:
            rx, ry = geometry.rotate((2 * x, 2 * y), (0.0, 0.0), 90.0)
            ends.append((round(rx + 100, 9), round(ry + 50, 9)))
        want.append(tuple(ends))
    assert got == sorted(want)


def test_a_block_with_its_inserts_survives_save_and_open(docs, tmp_path):
    doc = docs()
    _make_tick(doc)
    doc.type("-INSERT", "Tick", "20,20", "1", "1", "0")
    doc.type("-INSERT", "Tick", "40,20", "3", "3", "45")
    path = tmp_path / "ticks.fcad"
    doc.save(path)
    doc.close()
    again = docs.open(path)
    listed = {b["name"]: b for b in again.get("/blocks")["blocks"]}
    assert listed["Tick"]["objects"] == 2 and listed["Tick"]["references"] == 2
    placed = sorted((tuple(e["position"][:2]), e["scale"][0], round(math.degrees(e["rotation"]), 9)) for e in again.entities("insert"))
    assert placed == [((20.0, 20.0), 1.0, 0.0), ((40.0, 20.0), 3.0, 45.0)]


def test_purging_an_unused_block_removes_it_and_a_used_block_stays(doc):
    _make_tick(doc)
    doc.type("CIRCLE", "0,0", "1")
    doc.post("/blocks", {"name": "Dot", "handles": [doc.only("circle")["handle"]], "base": [0, 0, 0]})
    doc.type("-INSERT", "Tick", "0,0", "1", "1", "0")
    doc.post("/blocks/purge", {"type": "blocks", "name": "*"})
    names = {b["name"] for b in doc.get("/blocks")["blocks"]}
    assert "Tick" in names and "Dot" not in names
