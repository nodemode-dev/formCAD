import json
import zipfile

import pytest

from tests.support import geometry
from tests.support.engine import Refused


def _draw_sample(doc):
    doc.put("/layers", {"ops": [{"op": "new", "name": "Walls", "props": {"color": 1}, "current": True}]})
    doc.type("LINE", "0,0", "30,40", "")
    doc.type("CIRCLE", "10,10", "7.5")
    doc.set_var("LTSCALE", 2.5)


def _content(doc):
    snap = doc.snapshot()
    return sorted(snap["entities"], key=lambda e: e["handle"]), snap["tables"], snap["header"]


def test_a_saved_drawing_closed_and_opened_again_has_the_same_entities_layers_and_header(engine, docs, tmp_path):
    doc = docs()
    _draw_sample(doc)
    before = _content(doc)
    path = tmp_path / "sample.fcad"
    doc.save(path)
    assert doc.close(force=False)["closed"] is True
    again = docs.open(path)
    assert _content(again) == before
    assert again.var("LTSCALE") == 2.5
    assert again.var("CLAYER") == "Walls"
    line = again.only("line")
    assert geometry.close(geometry.dist(line["start"], line["end"]), 50.0)
    assert again.summary["dirty"] is False and again.summary["name"] == "sample"


def test_save_under_a_new_name_writes_both_files_and_the_document_follows_the_new_name(docs, tmp_path):
    doc = docs()
    _draw_sample(doc)
    first, second = tmp_path / "first.fcad", tmp_path / "second.fcad"
    doc.save(first)
    doc.type("LINE", "100,0", "100,10", "")
    saved = doc.save(second)
    assert saved["name"] == "second" and saved["path"] == str(second)
    doc.type("LINE", "200,0", "200,10", "")
    doc.save()
    doc.close()
    assert len(docs.open(first).entities("line")) == 1
    assert len(docs.open(second).entities("line")) == 3


def test_an_untitled_drawing_cannot_be_saved_without_a_path(doc):
    doc.type("LINE", "0,0", "1,1", "")
    with pytest.raises(Refused) as refused:
        doc.save()
    assert refused.value.status == 400 and "path" in refused.value.body


def test_a_save_path_without_an_extension_gets_fcad_and_a_foreign_extension_is_refused(doc, tmp_path):
    doc.type("LINE", "0,0", "1,1", "")
    saved = doc.save(tmp_path / "plain")
    assert saved["path"] == str(tmp_path / "plain.fcad") and zipfile.is_zipfile(tmp_path / "plain.fcad")
    with pytest.raises(Refused) as refused:
        doc.save(tmp_path / "notes.txt")
    assert refused.value.status == 400 and not (tmp_path / "notes.txt").exists()


def test_saving_over_an_existing_file_of_another_kind_is_refused_and_leaves_it_alone(doc, tmp_path):
    victim = tmp_path / "precious.fcad"
    victim.write_text("not a drawing, my notes", encoding="utf-8")
    doc.type("LINE", "0,0", "1,1", "")
    with pytest.raises(Refused) as refused:
        doc.save(victim)
    assert refused.value.status == 400
    assert victim.read_text(encoding="utf-8") == "not a drawing, my notes"


def test_closing_a_drawing_with_unsaved_changes_is_refused_unless_forced(engine, doc):
    doc.type("LINE", "0,0", "1,1", "")
    answer = doc.close(force=False)
    assert answer == {"closed": False, "dirty": True}
    assert doc.id in [d["id"] for d in engine.docs()]
    assert doc.close(force=True)["closed"] is True
    assert doc.id not in [d["id"] for d in engine.docs()]
    assert engine.status_of("GET", doc.url("/snapshot")) == 404


def _good_bytes(engine, tmp_path):
    d = engine.new_doc()
    d.type("LINE", "0,0", "30,40", "")
    path = tmp_path / "good.fcad"
    d.save(path)
    d.close()
    return path.read_bytes()


def _rewrite(src, dest, drop=(), replace=None):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for item in zin.infolist():
            if item.filename in drop:
                continue
            data = zin.read(item.filename)
            if replace and item.filename in replace:
                data = replace[item.filename]
            zout.writestr(item, data)


DAMAGE = {
    "plain_text": lambda good, path: path.write_text("this is not a drawing"),
    "empty": lambda good, path: path.write_bytes(b""),
    "truncated_half": lambda good, path: path.write_bytes(good[: len(good) // 2]),
    "truncated_tail": lambda good, path: path.write_bytes(good[:-30]),
    "no_document": lambda good, path: (path.with_suffix(".src").write_bytes(good), _rewrite(path.with_suffix(".src"), path, drop=("document.json",))),
    "no_manifest": lambda good, path: (path.with_suffix(".src").write_bytes(good), _rewrite(path.with_suffix(".src"), path, drop=("manifest.json",))),
    "document_not_json": lambda good, path: (path.with_suffix(".src").write_bytes(good), _rewrite(path.with_suffix(".src"), path, replace={"document.json": b"{\"entities\": [1, 2"})),
    "foreign_manifest": lambda good, path: (path.with_suffix(".src").write_bytes(good), _rewrite(path.with_suffix(".src"), path, replace={"manifest.json": b"{\"format\": \"someone-else\", \"schema\": 1}"})),
    "newer_schema": lambda good, path: (path.with_suffix(".src").write_bytes(good), _rewrite(path.with_suffix(".src"), path, replace={"manifest.json": b"{\"format\": \"formcad\", \"schema\": 99}"})),
}


@pytest.mark.parametrize("damage", sorted(DAMAGE))
def test_a_damaged_project_file_is_refused_with_a_reason_and_open_drawings_are_unharmed(engine, doc, tmp_path, damage):
    doc.type("CIRCLE", "5,5", "3")
    before_docs = [d["id"] for d in engine.docs()]
    before = doc.snapshot()
    bad = tmp_path / ("bad-%s.fcad" % damage)
    DAMAGE[damage](_good_bytes(engine, tmp_path), bad)
    with pytest.raises(Refused) as refused:
        engine.open_doc(bad)
    assert refused.value.status == 400
    assert len(json.loads(refused.value.body)["detail"]) > 15
    assert [d["id"] for d in engine.docs()] == before_docs
    after = doc.snapshot()
    assert after["entities"] == before["entities"] and after["rev"] == before["rev"]
    assert doc.state()["dirty"] is True


def test_the_basic_fixture_opens_with_the_content_its_readme_states(docs, fixtures):
    doc = docs.open(fixtures / "doc-basic.fcad")
    layers = {r["name"]: r["color"] for r in doc.get("/layers")["layers"]}
    assert layers == {"0": 7, "Defpoints": 7, "Walls": 1, "Dims": 3}
    kinds = doc.kinds()
    assert kinds == {"line": 5, "circle": 2, "arc": 2, "lwpolyline": 2}
    assert all(e["layer"] == "Walls" for e in doc.entities("line"))
    circles = sorted((tuple(c["center"][:2]), c["radius"]) for c in doc.entities("circle"))
    assert circles == [((120.0, 70.0), 25.0), ((300.0, 70.0), 20.0)]
    assert all(c["layer"] == "Dims" for c in doc.entities("circle"))
    assert doc.var("MEASUREMENT") == 1
    assert doc.var("LIMMAX")[:2] == [420.0, 297.0]
