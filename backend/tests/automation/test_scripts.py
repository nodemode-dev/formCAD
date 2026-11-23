import os
import subprocess
import sys
import time

import pytest

from tests.support import geometry


def finish(doc, limit: float = 30.0) -> dict:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        state = doc.state()
        script = state.get("script")
        if (not script or script["state"] == "paused") and not state["active"]:
            return state
        time.sleep(0.05)
    raise AssertionError("the script did not finish: %s" % doc.state().get("script"))


def run_script(doc, path) -> dict:
    doc.type("SCRIPT", str(path))
    return finish(doc)


def corners(e) -> list:
    return sorted((round(v["p"][0], 9), round(v["p"][1], 9)) for v in e["vertices"])


def rect(x0, y0, x1, y1) -> list:
    return sorted([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def circles(doc) -> list:
    return sorted((round(c["center"][0], 9), round(c["center"][1], 9), round(c["radius"], 9)) for c in doc.entities("circle"))


def lines(doc) -> list:
    return sorted((tuple(round(v, 9) for v in l["start"][:2]), tuple(round(v, 9) for v in l["end"][:2])) for l in doc.entities("line"))


def drawing(doc) -> dict:
    return {
        "rects": sorted(corners(p) for p in doc.entities("lwpolyline")),
        "circles": circles(doc),
        "lines": lines(doc),
        "texts": sorted(t["text"] for t in doc.entities("text")),
    }


def test_the_plate_script_replays_to_the_plate_it_describes(docs, fixtures):
    d = docs()
    run_script(d, fixtures / "scripts/plate.scr")
    assert d.kinds() == {"lwpolyline": 2, "circle": 2, "text": 1}
    assert sorted(corners(p) for p in d.entities("lwpolyline")) == sorted([rect(0, 0, 200, 120), rect(-10, -10, 210, 130)])
    assert circles(d) == [(50.0, 60.0, 15.0), (100.0, 60.0, 5.0)]
    text = d.only("text")
    assert text["text"] == "PLATE A-1" and text["height"] == pytest.approx(8.0, abs=1e-9)


def test_the_plate_script_replay_matches_the_saved_plate_fixture(docs, fixtures):
    replayed = docs()
    run_script(replayed, fixtures / "scripts/plate.scr")
    saved = docs.open(fixtures / "scripts/plate.fcad")
    assert drawing(replayed) == drawing(saved)


def test_the_recorded_bracket_script_replays_to_its_four_objects(doc, fixtures):
    run_script(doc, fixtures / "scripts/bracket-sketch.scr")
    assert doc.kinds() == {"lwpolyline": 1, "circle": 2, "line": 1}
    assert corners(doc.only("lwpolyline")) == rect(0, 0, 120, 60)
    assert circles(doc) == [(30.0, 30.0, 10.0), (90.0, 50.0, 10.0)]
    assert lines(doc) == [((0.0, 50.0), (120.0, 50.0))]


def test_a_script_is_one_undo_step_per_command_and_undoing_all_of_them_empties_the_drawing(doc, fixtures):
    run_script(doc, fixtures / "scripts/bracket-sketch.scr")
    made = drawing(doc)
    doc.undo(5)
    assert doc.entities() == []
    doc.redo(5)
    assert drawing(doc) == made


def test_a_script_with_a_bad_line_stops_at_that_line_with_a_clear_error(doc, tmp_path):
    script = tmp_path / "bad.scr"
    script.write_text("CIRCLE 10,10 5\nFROBNICATE 1\nCIRCLE 50,50 5\n", encoding="utf-8")
    state = run_script(doc, script)
    assert circles(doc) == [(10.0, 10.0, 5.0)]
    assert state["script"]["state"] == "paused" and state["script"]["line"] == 2
    assert "Unknown command: FROBNICATE" in state["script"]["note"]
    assert "stopped at line 2" in " ".join(state["history"])


def test_a_macro_recorded_while_drawing_replays_to_the_same_objects_in_a_new_drawing(docs, tmp_path):
    first = docs()
    first.post("/command", {"command": "macrorecord", "args": {"name": "lane11"}})
    first.type("RECTANG", "0,0", "80,50")
    first.type("CIRCLE", "20,25", "6")
    first.type("LINE", "0,25", "80,25", "")
    first.type("MOVE")
    first.pick(handle=first.only("circle")["handle"], point=[20, 31])
    first.enter()
    first.type("0,0", "10,5")
    stopped = first.command("macrostop")["result"]
    assert stopped["steps"] > 0
    saved = tmp_path / "lane11.scr"
    first.command("macrosave", path=str(saved))
    assert saved.is_file()
    expected = drawing(first)
    assert expected["circles"] == [(30.0, 30.0, 6.0)]
    second = docs()
    run_script(second, saved)
    assert drawing(second) == expected
    third = docs()
    third.command("macroplay", path=str(saved))
    finish(third)
    assert drawing(third) == expected
    first.command("erase", all=True)
    assert first.entities() == []
    first.command("macroplay", path="last")
    finish(first)
    assert drawing(first) == expected


def test_a_command_alias_file_loads_its_aliases_and_never_turns_a_command_name_into_another_command(doc, fixtures):
    doc.command("aliasedit", action="load", path=str(fixtures / "scripts/shop.fcalias"))
    doc.type("RC", "0,0", "10,10")
    doc.type("CC", "5,5", "2")
    doc.type("LINE", "0,0", "10,0", "")
    assert doc.kinds() == {"lwpolyline": 1, "circle": 1, "line": 1}
    assert geometry.same_point(doc.only("line")["end"], (10, 0))


def engine_cli(repo, tmp_path, *args) -> subprocess.CompletedProcess:
    env = dict(os.environ, FORMCAD_DATA_DIR=str(tmp_path / "data"))
    return subprocess.run([sys.executable, str(repo / "backend/formcad_engine.py"), *args, "--settings-dir", str(tmp_path / "data")], capture_output=True, text=True, timeout=120, cwd=str(repo / "backend"), env=env)


@pytest.mark.slow
def test_the_bracket_python_macro_and_the_bracket_script_from_one_recording_make_the_same_drawing(docs, repo, fixtures, tmp_path):
    out = tmp_path / "bracket.fcad"
    done = engine_cli(repo, tmp_path, "run", "--new", "--python-macro", str(fixtures / "scripts/bracket-sketch.py"), "--save", str(out))
    assert done.returncode == 0, done.stderr
    by_macro = docs.open(out)
    by_script = docs()
    run_script(by_script, fixtures / "scripts/bracket-sketch.scr")
    assert drawing(by_macro) == drawing(by_script)


@pytest.mark.slow
def test_the_plate_python_macro_passes_its_own_checks_and_leaves_the_edited_plate(docs, repo, fixtures, tmp_path):
    out = tmp_path / "plate.fcad"
    done = engine_cli(repo, tmp_path, "run", "--new", "--python-macro", str(fixtures / "macros/plate.py"), "--save", str(out))
    assert done.returncode == 0, done.stderr
    d = docs.open(out)
    assert sorted(corners(p) for p in d.entities("lwpolyline")) == sorted([rect(0, 0, 120, 80), rect(0, 120, 120, 200)])
    assert circles(d) == sorted([(15.0, 25.0, 6.0), (105.0, 25.0, 6.0), (105.0, 65.0, 9.0), (-30.0, 65.0, 9.0)])
    assert lines(d) == [((60.0, -10.0), (60.0, 90.0))]
    assert [t["text"] for t in d.entities("text")] == ["PLATE 120 x 80"]


def test_a_python_macro_that_fails_its_own_check_exits_with_a_failure(repo, tmp_path):
    macro = tmp_path / "failing.py"
    macro.write_text("import formcad\ndoc = formcad.active_document()\ndoc.circle([0, 0], 5)\nassert len(doc.entities(kind='circle')) == 2\n", encoding="utf-8")
    done = engine_cli(repo, tmp_path, "run", "--new", "--python-macro", str(macro), "--save", str(tmp_path / "never.fcad"))
    assert done.returncode == 1
    assert not (tmp_path / "never.fcad").exists()
