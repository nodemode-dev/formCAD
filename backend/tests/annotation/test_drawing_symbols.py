import pytest

from tests.support import geometry


def made(doc, name, **args):
    state = doc.command(name, **args)
    assert not state["error"], state["error"]
    return state["result"]


def find(doc, kind, handle):
    hit = [e for e in doc.entities(kind) if e["handle"] == handle]
    assert len(hit) == 1
    return hit[0]


def test_a_tolerance_frame_keeps_its_characteristic_value_zone_modifier_and_datums(mm):
    h = made(mm, "gdtframe", point=[100, 100], char="position", tolerance="0.2", zone="diameter", modifier="M", datums=["A", "B", "C"])["created"]
    frame = mm.get("/drawann/frame/%d" % h)
    assert frame["name"] == "Position"
    assert frame["tolerance"] == "0.2" and frame["zone"] == "dia" and frame["modifier"] == "M"
    assert [d["ref"] for d in frame["datums"]] == ["A", "B", "C"]


def test_a_tolerance_frame_refuses_a_fourth_datum_reference(mm):
    state = mm.command("gdtframe", point=[0, 0], char="position", tolerance="0.1", datums=["A", "B", "C", "D"])
    assert "three datum" in state["error"]
    assert mm.entities("gdtframe") == []


def test_editing_a_tolerance_frame_changes_only_the_fields_given(mm):
    h = made(mm, "gdtframe", point=[100, 100], char="flatness", tolerance="0.05")["created"]
    made(mm, "gdtedit", handle=h, tolerance="0.02")
    frame = mm.get("/drawann/frame/%d" % h)
    assert frame["name"] == "Flatness" and frame["tolerance"] == "0.02"


def test_balloon_finish_mark_and_datum_symbol_keep_their_values_and_points(mm):
    b = made(mm, "balloon", point=[150, 150], tip=[140, 140], text="7")["created"]
    f = made(mm, "finishmark", point=[160, 100], value="Ra 1.6")["created"]
    d = made(mm, "datumsym", point=[170, 100], tip=[170, 90], letter="C")["created"]
    balloon, finish, datum = find(mm, "balloon", b), find(mm, "finishmark", f), find(mm, "datumsym", d)
    assert balloon["text"] == "7" and balloon["tip"][:2] == [140.0, 140.0] and balloon["position"][:2] == [150.0, 150.0]
    assert finish["value"] == "Ra 1.6" and finish["position"][:2] == [160.0, 100.0]
    assert datum["letter"] == "C" and datum["tip"][:2] == [170.0, 90.0]


def test_drawing_symbols_survive_save_and_reopen_unchanged(mm, docs, tmp_path):
    made(mm, "gdtframe", point=[100, 100], char="perpendicularity", tolerance="0.1", datums=["A"])
    made(mm, "balloon", point=[150, 150], tip=[140, 140], text="12")
    made(mm, "finishmark", point=[160, 100], value="Ra 0.8")
    made(mm, "centermark", center=[30, 30], radius=8)
    kinds = ("gdtframe", "balloon", "finishmark", "centermark")
    keep = ("char", "tolerance", "datums", "text", "tip", "value", "center", "radius", "position")
    before = {k: [{f: e.get(f) for f in keep} for e in mm.entities(k)] for k in kinds}
    path = tmp_path / "symbols.fcad"
    mm.save(path)
    again = docs.open(path)
    after = {k: [{f: e.get(f) for f in keep} for e in again.entities(k)] for k in kinds}
    assert after == before


def test_a_centre_mark_sits_on_the_centre_with_the_radius_given(mm):
    h = made(mm, "centermark", center=[30, 40], radius=8)["created"]
    mark = find(mm, "centermark", h)
    assert geometry.same_point(mark["center"][:2], (30.0, 40.0))
    assert geometry.close(mark["radius"], 8.0)


def test_a_leader_keeps_its_points_and_arrowhead(mm):
    out = made(mm, "leader", points=[[0, 0], [10, 10], [20, 10]], text="NOTE A")
    leader = mm.only("leader")
    assert [p[:2] for p in leader["points"]] == [[0.0, 0.0], [10.0, 10.0], [20.0, 10.0]]
    assert leader["arrowhead"] is True and out["spline"] is False


def test_a_multileader_keeps_its_text_and_lands_at_its_last_leader_point(mm):
    out = made(mm, "mleader", points=[[0, 0], [10, 10]], text="M NOTE")
    ml = mm.only("mleader")
    assert ml["text"] == "M NOTE"
    assert ml["leaders"][0]["pts"] == [[0.0, 0.0], [10.0, 10.0]]
    assert geometry.same_point(out["landing"], (10.0, 10.0))


def test_a_parts_list_from_the_assembly_fixture_lists_each_part_number_with_its_flat_quantity(engine, fixtures):
    asm = engine.open_doc(fixtures / "assembly.fcad")
    try:
        out = made(asm, "bomtable", point=[0, 0], source={"self": True})
        rows = [[c["text"] for c in row] for row in asm.get("/table/%d" % out["created"])["cells"]]
    finally:
        asm.close()
    header = rows[1]
    body = [dict(zip(header, r)) for r in rows[2:]]
    assert {r["PART NUMBER"]: int(r["QTY"]) for r in body} == {"BP-100": 1, "DP-300": 4, "RD-410": 4, "CP-020": 4}
    assert {r["PART NUMBER"]: r["ITEM"] for r in body}["BP-100"] == "1"


def test_a_parts_list_given_rows_shows_them_in_order_under_its_title(mm):
    rows = [{"part_number": "A-1", "description": "Plate", "qty": 2}, {"part_number": "B-7", "description": "Screw", "qty": 8}]
    out = made(mm, "bomtable", point=[0, 0], rows=rows, title="PARTS")
    cells = [[c["text"] for c in row] for row in mm.get("/table/%d" % out["created"])["cells"]]
    assert cells[0][0] == "PARTS"
    body = [dict(zip(cells[1], r)) for r in cells[2:]]
    assert [(r["ITEM"], r["PART NUMBER"], r["QTY"]) for r in body] == [("1", "A-1", "2"), ("2", "B-7", "8")]


def test_revisions_take_letters_in_order_skipping_i_and_o(mm):
    letters = [made(mm, "revadd", description="change %d" % i, date="2026-01-%02d" % (i + 1))["revision"]["rev"] for i in range(15)]
    assert letters == list("ABCDEFGHJKLMNPQ")


def test_adding_a_revision_updates_the_revision_table_and_the_rev_field_of_the_title_block(mm):
    mm.post("/space", {"tab": "Layout1"})
    block = made(mm, "titleblock", point=[200, 10])["handle"]
    table = made(mm, "revtable", point=[200, 200])["created"]
    made(mm, "revadd", description="first issue", date="2026-01-02")
    made(mm, "revadd", description="second issue", date="2026-02-03")
    rows = [[c["text"] for c in r] for r in mm.get("/table/%d" % table)["cells"]]
    assert rows[2][:3] == ["A", "first issue", "2026-01-02"]
    assert rows[3][:3] == ["B", "second issue", "2026-02-03"]
    attrs = {a["tag"]: a["value"] for a in find(mm, "insert", block)["attributes"]}
    assert attrs["REV"] == "B"


def test_a_title_block_is_filled_from_the_document_properties(mm):
    mm.post("/space", {"tab": "Layout1"})
    mm.put("/drawann/properties", {"title": "GEAR HOUSING", "idno": "GH-001"})
    block = made(mm, "titleblock", point=[200, 10])["handle"]
    attrs = {a["tag"]: a["value"] for a in find(mm, "insert", block)["attributes"]}
    assert attrs["TITLE"] == "GEAR HOUSING" and attrs["IDNO"] == "GH-001"


@pytest.mark.parametrize("args, words", [({"tolerance": "-0.1", "char": "position"}, "negative"), ({"tolerance": "0.1", "char": "nonsense"}, "")])
def test_a_tolerance_frame_with_a_bad_value_is_refused(mm, args, words):
    state = mm.command("gdtframe", point=[0, 0], **args)
    assert state["error"] and words in state["error"]
    assert mm.entities("gdtframe") == []
