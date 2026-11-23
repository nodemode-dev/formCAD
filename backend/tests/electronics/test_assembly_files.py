import csv
from pathlib import Path

from tests.electronics.kit import PARTS, output_board, part, schematic


def idf_sections(path) -> dict:
    out = {}
    current = None
    for raw in Path(path).read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(".END_"):
            current = None
            continue
        if line.startswith("."):
            current = line.split()[0][1:]
            out[current] = []
            continue
        if current:
            out[current].append(line.split())
    return out


def placements(sections) -> dict:
    rows = sections["PLACEMENT"]
    out = {}
    for k in range(0, len(rows), 2):
        package, number, ref = rows[k]
        x, y, offset, rot, side, status = rows[k + 1]
        out[ref] = {"package": package, "part": number, "x": float(x), "y": float(y), "offset": float(offset), "rot": float(rot), "side": side, "status": status}
    return out


def test_the_placement_file_lists_every_part_with_its_position_rotation_and_side(doc, tmp_path):
    output_board(doc)
    report = doc.post("/ecad/export/idf", {"out": str(tmp_path / "board")})
    got = placements(idf_sections(report["board"]))
    assert set(got) == set(PARTS)
    for ref, p in PARTS.items():
        row = got[ref]
        assert (row["x"], row["y"], row["rot"]) == (p["x"], p["y"], p["rot"])
        assert row["side"] == ("BOTTOM" if p["side"] == "bottom" else "TOP")
        assert row["package"] == p["footprint"] and row["part"] == p["value"]
        assert row["status"] == "PLACED"


def test_the_board_exchange_file_carries_the_thickness_and_the_closed_outline(doc, tmp_path):
    output_board(doc)
    sections = idf_sections(doc.post("/ecad/export/idf", {"out": str(tmp_path / "board")})["board"])
    outline = sections["BOARD_OUTLINE"]
    assert abs(float(outline[0][0]) - doc.get("/pcb")["board"]["thickness"]) < 1e-9
    loop = [(float(r[1]), float(r[2])) for r in outline[1:] if r[0] == "0"]
    assert loop[0] == loop[-1]
    area = sum(loop[k][0] * loop[k + 1][1] - loop[k + 1][0] * loop[k][1] for k in range(len(loop) - 1)) / 2
    assert abs(area - 40.0 * 30.0) < 1e-6
    holes = {(float(r[0]), float(r[1]), float(r[2])) for r in sections["DRILLED_HOLES"]}
    assert (3.2, 35.0, 5.0) in holes and (0.3, 15.0, 25.0) in holes


def test_the_bill_of_materials_groups_equal_parts_and_counts_them(doc, tmp_path):
    schematic(
        doc,
        part("R", 0, 0, value="10k"), part("R", 10, 0, value="10k"), part("R", 20, 0, value="1k"), part("R", 30, 0, value="10k"),
        part("C", 40, 0, value="100n"), part("LED", 50, 0, value="red"), part("R", 60, 0, value="10k", footprint="CHIP-1206"),
        {"op": "power_at", "pin": "R1.1", "net": "+5V"},
    )
    report = doc.post("/ecad/export/bom", {"path": str(tmp_path / "bom.csv")})
    rows = list(csv.DictReader(Path(report["path"]).open(encoding="utf-8")))
    got = {(r["value"], r["footprint"]): (int(r["qty"]), sorted(r["refs"].split())) for r in rows}
    assert got == {
        ("10k", "CHIP-0603"): (3, ["R1", "R2", "R4"]),
        ("1k", "CHIP-0603"): (1, ["R3"]),
        ("100n", "CHIP-0603"): (1, ["C1"]),
        ("red", "CHIP-0805"): (1, ["D1"]),
        ("10k", "CHIP-1206"): (1, ["R5"]),
    }
    assert sum(int(r["qty"]) for r in rows) == 7
