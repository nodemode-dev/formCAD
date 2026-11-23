import hashlib
import itertools
import shutil

import pytest

_names = itertools.count(1)


@pytest.fixture()
def vault(engine, tmp_path):
    made = engine.post("/api/vault", {"name": "lane11-%d" % next(_names), "folder": str(tmp_path / "vault")})
    yield "/api/vault/%s" % made["id"]
    engine.raw("DELETE", "/api/vault/%s" % made["id"])


def checkin(engine, vault: str, path, message: str = "", **extra) -> dict:
    return engine.post(vault + "/checkin", dict(extra, path=str(path), message=message))


def checkout(engine, vault: str, doc: str, path, **extra):
    return engine.raw("POST", "%s/docs/%s/checkout" % (vault, doc), json=dict(extra, path=str(path)))


@pytest.fixture()
def two_versions(engine, doc, vault, tmp_path):
    work = tmp_path / "plate.fcad"
    doc.type("LINE", "0,0", "30,40", "")
    doc.save(work)
    first_bytes = work.read_bytes()
    first = checkin(engine, vault, work, "outline")
    doc.type("CIRCLE", "5,5", "3")
    doc.save(work)
    second = checkin(engine, vault, work, "add a hole")
    return {"doc": first["doc"], "first": first["version"], "second": second["version"], "first_bytes": first_bytes, "second_bytes": work.read_bytes()}


def test_two_check_ins_make_two_versions_with_their_notes_newest_first(engine, vault, two_versions):
    log = engine.get("%s/docs/%s/log" % (vault, two_versions["doc"]))["versions"]
    assert [v["id"] for v in log] == [two_versions["second"]["id"], two_versions["first"]["id"]]
    assert [v["message"] for v in log] == ["add a hole", "outline"]
    assert log[0]["parents"] == [log[1]["id"]] and log[1]["parents"] == []


def test_a_version_is_addressed_by_the_sha256_of_the_checked_in_file(two_versions):
    assert two_versions["first"]["sha256"] == hashlib.sha256(two_versions["first_bytes"]).hexdigest()
    assert two_versions["second"]["sha256"] == hashlib.sha256(two_versions["second_bytes"]).hexdigest()
    assert two_versions["first"]["sha256"] != two_versions["second"]["sha256"]


def test_restoring_the_first_version_gives_back_exactly_the_first_file(engine, docs, vault, two_versions, tmp_path):
    target = tmp_path / "restored.fcad"
    r = checkout(engine, vault, two_versions["doc"], target, version=two_versions["first"]["id"], lock=False, edit=False)
    assert r.status_code == 200
    assert target.read_bytes() == two_versions["first_bytes"]
    restored = docs.open(target)
    assert restored.kinds() == {"line": 1}


def test_a_checked_out_document_is_locked_against_a_second_check_out(engine, vault, two_versions, tmp_path):
    mine = checkout(engine, vault, two_versions["doc"], tmp_path / "ann.fcad", lock=True, author="ann")
    assert mine.status_code == 200 and mine.json()["locked"] is True
    theirs = checkout(engine, vault, two_versions["doc"], tmp_path / "bob.fcad", lock=True, author="bob")
    assert theirs.status_code == 409 and "ann" in theirs.json()["detail"]
    assert not (tmp_path / "bob.fcad").exists()
    locks = engine.get(vault + "/locks")["locks"]
    assert [(l["doc"], l["owner"]) for l in locks] == [(two_versions["doc"], "ann")]


def test_undoing_a_check_out_releases_the_lock(engine, vault, two_versions, tmp_path):
    held = tmp_path / "mine.fcad"
    checkout(engine, vault, two_versions["doc"], held, lock=True)
    assert len(engine.get(vault + "/locks")["locks"]) == 1
    engine.post(vault + "/undo-checkout", {"path": str(held)})
    assert engine.get(vault + "/locks")["locks"] == []
    again = checkout(engine, vault, two_versions["doc"], tmp_path / "bob.fcad", lock=True, author="bob")
    assert again.status_code == 200


def test_the_diff_between_two_versions_names_the_object_that_was_added(engine, vault, two_versions):
    diff = engine.get(vault + "/diff", a=two_versions["first"]["id"], b=two_versions["second"]["id"])
    assert diff["summary"]["added"] == 1 and diff["summary"]["removed"] == 0
    added = [i for i in diff["items"] if i["change"] == "added"]
    assert len(added) == 1 and "circle" in (added[0]["entity"] + added[0].get("name", "")).lower()


@pytest.mark.parametrize("name", ["vault/part.fcad", "scripts/plate.fcad", "lisp/bolt-pattern.fcad", "graph/plate-holes.fcad"])
def test_a_fixture_document_checks_in_and_comes_back_byte_identical(engine, vault, fixtures, tmp_path, name):
    work = tmp_path / "in.fcad"
    shutil.copy(fixtures / name, work)
    made = checkin(engine, vault, work, "as is")
    out = tmp_path / "out.fcad"
    checkout(engine, vault, made["doc"], out, lock=False, edit=False)
    assert out.read_bytes() == (fixtures / name).read_bytes()


def test_merging_two_branches_of_the_part_reports_the_one_conflict_and_merges_the_rest(engine, vault, fixtures, tmp_path):
    work = tmp_path / "part.fcad"
    shutil.copy(fixtures / "vault/part.fcad", work)
    base = checkin(engine, vault, work, "base")
    doc, base_id = base["doc"], base["version"]["id"]
    for branch in ("a", "b"):
        engine.post("%s/docs/%s/branches" % (vault, doc), {"name": branch, "frm": base_id})
    shutil.copy(fixtures / "vault/part-branch-a.fcad", work)
    ours = checkin(engine, vault, work, "A", branch="a")["version"]["id"]
    shutil.copy(fixtures / "vault/part-branch-b.fcad", work)
    theirs = checkin(engine, vault, work, "B", branch="b")["version"]["id"]
    merge = engine.post("%s/docs/%s/merge" % (vault, doc), {"source": "b", "branch": "a"})
    assert merge["status"] == "conflicts"
    assert [(c["entity"], c["path"], c["base"], c["ours"], c["theirs"]) for c in merge["conflicts"]] == [("table:features:F2", "params.depth1", 20, 24, 30)]
    engine.put("%s/docs/%s/merge" % (vault, doc), {"choices": {merge["conflicts"][0]["id"]: "theirs"}})
    done = engine.post("%s/docs/%s/merge/complete" % (vault, doc), {"message": "merge B into A"})
    merged = done["version"]
    assert merged["parents"] == [ours, theirs]
    diff = engine.get(vault + "/diff", a=base_id, b=merged["id"])
    changed = {(i["entity"], f["path"]): (f["a"], f["b"]) for i in diff["items"] for f in i["fields"]}
    assert changed == {
        ("table:features:F2", "params.depth1"): (20, 30),
        ("table:features:F4", "params.depth1"): (15, 18),
        ("table:features:F12", "params.radius"): (4.0, 3.0),
        ("table:features:F13", "params.distance"): (0.3, 0.4),
    }
