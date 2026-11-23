import pytest

from tests.manufacture.helpers import Mill, box_triangles, open_mesh, rapids_into_uncut_stock
from tests.support.engine import Refused
from tests.support.gcode import Program

MILL_POSTS = ["linuxcnc", "grbl", "linuxcnc_5axis"]


def job(docs, tmp_path, slot=1):
    doc = open_mesh(docs, tmp_path, box_triangles((0, 0, -20), (100, 100, 0)), "block")
    m = Mill(doc, slot=slot)
    m.tool(1, "flat", 6.0)
    m.tool(3, "drill", 5.0)
    m.op("contour", 1, {"kind": "rect", "min": [20, 20], "max": [60, 50]}, {"side": "outside", "stepdown": 2.5}, heights={"bottom": -5.0})
    m.op("drill", 3, {"kind": "points", "points": [[80, 80], [80, 10]]}, {"cycle": "peck", "peck": 2.0}, {"rpm": 3000, "vf_cut": 120, "vf_plunge": 120}, {"bottom": -10.0})
    return m


@pytest.mark.parametrize("post", MILL_POSTS)
def test_every_milling_post_writes_the_same_profile_as_a_program_the_walker_reads_without_unknown_words(docs, tmp_path, post):
    m = job(docs, tmp_path)
    program, text = m.post(post)
    assert program.unknown == []
    assert program.units == "mm" and "G21" in text
    assert program.ended and not program.spindle_on
    profile, _ = m.post(post, ops=["O1"])
    assert rapids_into_uncut_stock(profile, 0.0) == []
    assert profile.extents() == pytest.approx((17.0, 15.5, 63.0, 53.0), abs=1e-3)
    assert profile.lowest() == pytest.approx(-5.0, abs=1e-9)
    straight = 2 * (40.0 + 30.0)
    corners = 2 * 3.14159265358979 * 3.0
    leads = 2 * (3.14159265358979 / 2.0) * 1.5
    flat = sum(mv.length for mv in profile.cutting() if abs(mv.start[2] - mv.end[2]) < 1e-9)
    assert flat == pytest.approx(2 * (straight + corners + leads), abs=0.05)


@pytest.mark.parametrize("post", MILL_POSTS)
def test_an_inch_program_writes_g20_and_every_coordinate_divided_by_25_4(docs, tmp_path, post):
    m = job(docs, tmp_path)
    mm, _ = m.post(post)
    inch, text = m.post(post, units="in")
    assert inch.units == "inch" and "G20" in text and "G21" not in text
    a, b = mm.extents(cutting_only=False), inch.extents(cutting_only=False)
    assert all(abs(x / 25.4 - y) < 1e-4 for x, y in zip(a, b))
    assert inch.lowest() == pytest.approx(mm.lowest() / 25.4, abs=1e-4)
    assert inch.cut_length() == pytest.approx(mm.cut_length() / 25.4, rel=1e-4)
    feeds_mm = sorted({mv.feed for mv in mm.cutting()})
    feeds_in = sorted({mv.feed for mv in inch.cutting()})
    assert feeds_in == pytest.approx([f / 25.4 for f in feeds_mm], abs=1e-3)


@pytest.mark.parametrize("post,slot,code", [("linuxcnc", 1, "G54"), ("linuxcnc", 2, "G55"), ("linuxcnc", 6, "G59"), ("linuxcnc", 7, "G59.1"), ("grbl", 3, "G56"), ("linuxcnc_5axis", 9, "G59.3")])
def test_the_setup_work_offset_slot_is_selected_before_the_first_move(docs, tmp_path, post, slot, code):
    m = job(docs, tmp_path, slot=slot)
    program, text = m.post(post)
    lines = [ln.strip() for ln in text.splitlines()]
    first_motion = min(mv.line for mv in program.moves)
    offsets = [i + 1 for i, ln in enumerate(lines) if ln in ("G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3")]
    assert offsets and all(lines[i - 1] == code for i in offsets)
    assert offsets[0] < first_motion


def test_a_post_without_the_ninth_work_offset_refuses_rather_than_writing_the_wrong_one(docs, tmp_path):
    m = job(docs, tmp_path, slot=7)
    with pytest.raises(Refused) as err:
        m.post("grbl")
    assert err.value.status == 400 and "7" in err.value.body


def test_an_exported_program_file_reads_back_as_the_previewed_program(docs, tmp_path, data_dir):
    m = job(docs, tmp_path)
    preview, _ = m.post("linuxcnc")
    out = data_dir / "lane9-export.ngc"
    res = m.doc.post("/cam/export", {"out": str(out), "post": "linuxcnc"})
    written = Program.read(res["path"])
    assert written.cut_length() == pytest.approx(preview.cut_length(), rel=1e-9)
    assert written.extents() == preview.extents() and written.lowest() == preview.lowest()
