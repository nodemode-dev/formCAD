import stat

import pytest

from tests.interchange.common import cmd, metric, model_kinds, ok
from tests.support import geometry
from tests.support.dxf import Dxf


@pytest.fixture()
def dwg_settings(engine, data_dir):
    path = data_dir / "interchange.json"
    saved = path.read_bytes() if path.exists() else None
    engine.put("/api/interchange/dwg", {"enabled": False, "converter": ""})
    yield
    if saved is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(saved)


def script(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def fake_dwg(path):
    path.write_bytes(b"AC1015" + bytes(range(256)) * 4)
    return path


def test_with_dwg_support_off_the_status_says_so_and_a_dwg_open_is_refused_without_opening_a_document(engine, dwg_settings, tmp_path):
    status = engine.get("/api/interchange/dwg")
    assert status["enabled"] is False and status["usable"] is False
    assert "Turn it on" in status["message"]
    before = [d["id"] for d in engine.docs()]
    r = engine.raw("POST", "/api/interchange/open", json={"path": str(fake_dwg(tmp_path / "part.dwg"))})
    assert r.status_code == 400 and "converter" in r.json()["detail"]
    assert [d["id"] for d in engine.docs()] == before


def test_a_dwg_import_with_no_converter_is_refused_and_the_open_drawing_is_unchanged(engine, dwg_settings, doc, tmp_path):
    ok(doc, "line", points=[[0, 0], [5, 5]])
    rev = doc.rev()
    out = cmd(doc, "import", path=str(fake_dwg(tmp_path / "part.dwg")))
    assert "converter" in out["error"]
    assert doc.rev() == rev and model_kinds(doc) == {"line": 1}


def test_a_dwg_export_with_no_converter_is_refused_and_writes_no_file(dwg_settings, doc, tmp_path):
    ok(doc, "line", points=[[0, 0], [5, 5]])
    target = tmp_path / "out.dwg"
    out = cmd(doc, "export", path=str(target))
    assert "converter" in out["error"] and not target.exists()


def test_a_converter_with_an_unknown_program_name_is_refused_and_the_settings_stay_as_they_were(engine, dwg_settings):
    r = engine.raw("PUT", "/api/interchange/dwg", json={"enabled": True, "converter": "/usr/bin/cat"})
    assert r.status_code == 400 and "ODAFileConverter" in r.json()["detail"]
    status = engine.get("/api/interchange/dwg")
    assert status["enabled"] is False and status["converterPath"] == ""


def test_a_named_converter_that_is_not_on_disk_is_refused_with_its_path_when_a_dwg_is_opened(engine, dwg_settings, tmp_path):
    missing = str(tmp_path / "nowhere" / "dwg2dxf")
    status = engine.put("/api/interchange/dwg", {"enabled": True, "converter": missing})
    assert status["enabled"] is True and status["converterPath"] == missing and status["usable"] is False
    r = engine.raw("POST", "/api/interchange/open", json={"path": str(fake_dwg(tmp_path / "part.dwg"))})
    assert r.status_code == 400 and missing in r.json()["detail"]


@pytest.fixture()
def converter(engine, dwg_settings, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    source = fake_dwg(tmp_path / "given.dwg")
    known = tmp_path / "known.dxf"
    known.write_text("\n".join(["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
                                "0", "SECTION", "2", "ENTITIES",
                                "0", "LINE", "8", "0", "10", "0", "20", "0", "30", "0", "11", "12", "21", "5", "31", "0",
                                "0", "CIRCLE", "8", "0", "10", "40", "20", "40", "30", "0", "40", "7.5",
                                "0", "ENDSEC", "0", "EOF", ""]))
    read = script(bin_dir / "dwg2dxf", 'cmp -s "$4" "%s" || exit 3\n[ "$2" = "-o" ] || exit 4\ncp "%s" "$3"' % (source, known))
    script(bin_dir / "dxf2dwg", '[ "$3" = "r2000" ] || exit 4\ncp "$6" "$5"')
    status = engine.put("/api/interchange/dwg", {"enabled": True, "converter": str(read)})
    assert status["usable"] is True and status["converterKind"] == "libredwg" and status["writeVersions"] == ["R2000"]
    return source


def test_opening_a_dwg_hands_the_file_to_the_converter_and_opens_the_dxf_it_produces(docs, converter):
    doc = docs.open(converter)
    assert model_kinds(doc) == {"line": 1, "circle": 1}
    line, circle = doc.only("line"), doc.only("circle")
    assert geometry.same_point(line["end"], (12, 5, 0)) and circle["radius"] == pytest.approx(7.5, abs=1e-12)


def test_saving_as_dwg_hands_a_release_2000_dxf_of_the_drawing_to_the_converter(docs, converter, tmp_path):
    doc = metric(docs())
    ok(doc, "line", points=[[0, 0], [30, 40]])
    ok(doc, "circle", center=[100, 50], radius=12.5)
    target = tmp_path / "saved.dwg"
    out = ok(doc, "export", path=str(target))
    assert any("R2000" in n for n in out["notes"]["notes"])
    dxf = Dxf.read(target)
    assert dxf.variable("ACADVER") == "AC1015"
    assert geometry.same_point(dxf.entities("LINE")[0].point(11), (30, 40, 0)) and dxf.entities("CIRCLE")[0].number(40) == pytest.approx(12.5)


def test_a_converter_that_fails_stops_the_open_with_its_exit_code(engine, docs, converter, tmp_path):
    other = fake_dwg(tmp_path / "other.dwg")
    other.write_bytes(other.read_bytes() + b"different")
    before = [d["id"] for d in engine.docs()]
    r = engine.raw("POST", "/api/interchange/open", json={"path": str(other)})
    assert r.status_code == 400 and "code 3" in r.json()["detail"]
    assert [d["id"] for d in engine.docs()] == before
