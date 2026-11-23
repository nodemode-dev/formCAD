import pytest

from tests.interchange.common import cmd, metric, model, ok

KERNEL = {"step", "iges", "3dm", "stl", "obj", "ply", "3mf"}
EXTS = ["dxf", "svg", "step", "iges", "3dm", "stl", "obj", "ply", "3mf"]
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 2


def cases(exts):
    return [pytest.param(e, marks=pytest.mark.kernel) if e in KERNEL else e for e in exts]


@pytest.fixture()
def target(docs):
    doc = metric(docs())
    ok(doc, "line", points=[[0, 0], [30, 40]])
    ok(doc, "circle", center=[10, 10], radius=3)
    return doc


@pytest.fixture(scope="module")
def good(engine, tmp_path_factory):
    made = {}
    folder = tmp_path_factory.mktemp("good")

    def get(ext):
        if ext not in made:
            doc = metric(engine.new_doc())
            path = folder / ("good." + ext)
            if ext != "svg":
                ok(doc, "box", corner=[0, 0, 0], size=[10, 20, 30])
            if ext == "svg":
                path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100"><path d="M 10 10 L 90 10 L 90 90 Z"/></svg>')
            else:
                ok(doc, "export", path=str(path))
            engine.raw("POST", doc.url("/close"), json={"force": True})
            made[ext] = path.read_bytes()
        return made[ext]

    return get


def refused_and_unchanged(engine, target, path):
    before = (target.rev(), model(target))
    opened = [d["id"] for d in engine.docs()]
    out = cmd(target, "import", path=str(path))
    assert len(out["error"]) > 10
    assert (target.rev(), model(target)) == before
    r = engine.raw("POST", "/api/interchange/open", json={"path": str(path)})
    assert r.status_code == 400 and len(r.json()["detail"]) > 10
    assert [d["id"] for d in engine.docs()] == opened


@pytest.mark.parametrize("ext", cases(EXTS))
def test_an_empty_file_is_refused_with_a_message_and_the_open_drawing_is_unchanged(engine, target, tmp_path, ext):
    path = tmp_path / ("empty." + ext)
    path.write_bytes(b"")
    refused_and_unchanged(engine, target, path)


@pytest.mark.parametrize("ext", cases(EXTS))
def test_a_picture_saved_under_a_cad_extension_is_refused_and_the_open_drawing_is_unchanged(engine, target, tmp_path, ext):
    path = tmp_path / ("picture." + ext)
    path.write_bytes(PNG)
    refused_and_unchanged(engine, target, path)


@pytest.mark.parametrize("ext", cases(["svg", "step", "iges", "3dm", "stl", "obj", "ply", "3mf"]))
def test_a_file_cut_off_halfway_is_refused_and_the_open_drawing_is_unchanged(engine, target, good, tmp_path, ext):
    data = good(ext)
    path = tmp_path / ("cut." + ext)
    path.write_bytes(data[: len(data) // 2])
    refused_and_unchanged(engine, target, path)


def test_a_dxf_cut_off_inside_its_objects_is_read_in_repair_mode_and_says_so(docs, tmp_path):
    src = metric(docs())
    for i in range(5):
        ok(src, "line", points=[[i, 0], [i, 10]])
    full = tmp_path / "full.dxf"
    ok(src, "export", path=str(full))
    text = full.read_text()
    starts = [i for i in range(len(text)) if text.startswith("\n  0\nLINE\n", i)]
    assert len(starts) == 5
    cut = tmp_path / "cut.dxf"
    cut.write_text(text[: starts[3] + 1])
    target = metric(docs())
    out = ok(target, "import", path=str(cut))
    assert any("structure errors" in n and "repair" in n for n in out["report"]["notes"])
    originals = [tuple(e["start"]) for e in model(src)]
    assert all(e["kind"] == "line" and tuple(e["start"]) in originals for e in model(target))
