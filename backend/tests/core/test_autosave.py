import pytest


def _autosave_files(data_dir):
    return {p.name: p for p in (data_dir / "Autosave").glob("*.sv$")}


def test_autosave_now_writes_a_dirty_drawing_to_a_file_that_opens_with_its_content(engine, docs, data_dir):
    doc = docs("AutosaveMe")
    doc.type("LINE", "0,0", "30,40", "")
    doc.type("CIRCLE", "5,5", "2")
    before = set(_autosave_files(data_dir))
    assert engine.post("/api/docs/autosave/now")["saved"] >= 1
    written = [p for n, p in _autosave_files(data_dir).items() if n not in before and n.startswith("AutosaveMe_")]
    assert len(written) == 1
    copy = docs.open(written[0])
    assert copy.kinds() == {"line": 1, "circle": 1}
    assert sorted(e["handle"] for e in copy.entities()) == sorted(doc.handles())


def test_a_drawing_without_changes_is_not_autosaved(engine, docs, data_dir):
    docs("UntouchedDrawing")
    engine.post("/api/docs/autosave/now")
    assert not [n for n in _autosave_files(data_dir) if n.startswith("UntouchedDrawing_")]


def test_saving_a_drawing_removes_its_autosave_file(engine, docs, data_dir, tmp_path):
    doc = docs("SavedLater")
    doc.type("LINE", "0,0", "1,0", "")
    engine.post("/api/docs/autosave/now")
    assert [n for n in _autosave_files(data_dir) if n.startswith("SavedLater_")]
    doc.save(tmp_path / "SavedLater.fcad")
    assert not [n for n in _autosave_files(data_dir) if n.startswith("SavedLater_")]


def test_the_recovery_list_does_not_offer_the_running_sessions_own_autosaves(engine, docs):
    doc = docs("StillOpen")
    doc.type("LINE", "0,0", "1,0", "")
    engine.post("/api/docs/autosave/now")
    assert not [i for i in engine.get("/api/docs/recovery")["items"] if i["title"] == "StillOpen"]


@pytest.mark.parametrize("name", ["../session.token", "/etc/passwd", "..%2Fsession.token", "x_1-a_1.sv$/../../session.token"])
def test_recovery_refuses_names_that_are_not_listed_autosave_files(engine, data_dir, name):
    token_before = (data_dir / "session.token").read_text()
    reply = engine.raw("POST", "/api/docs/recovery/open", json={"file": name})
    assert reply.status_code == 404 and "not available" in reply.json()["detail"]
    assert engine.post("/api/docs/recovery/discard", {"file": name})["discarded"] is False
    assert (data_dir / "session.token").read_text() == token_before
