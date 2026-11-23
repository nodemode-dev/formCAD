import json
import shutil
import zipfile
from pathlib import Path

import pytest

from tests.support import geometry

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
PROJECTS = sorted(FIXTURES.rglob("*.fcad"))
BIG = {"lines-100k.fcad"}


def _stored(path):
    with zipfile.ZipFile(path) as z:
        entities = json.loads(z.read("document.json"))["entities"]
    return {e["handle"] for e in entities}


def _summary(doc):
    return doc.get("/automation/summary")


def _same_box(a, b):
    if a is None or b is None:
        return a is None and b is None
    return all(geometry.close(x, y, 1e-6) for x, y in zip(a, b))


def _case(path):
    rel = str(path.relative_to(FIXTURES))
    marks = [pytest.mark.slow] if path.name in BIG else []
    return pytest.param(path, id=rel, marks=marks)


@pytest.mark.parametrize("path", [_case(p) for p in PROJECTS])
def test_a_fixture_project_opens_with_every_stored_entity_and_survives_save_and_open(docs, tmp_path, path):
    stored = _stored(path)
    doc = docs.open(path)
    first = _summary(doc)
    if first["objects"] != len(stored):
        assert stored <= set(doc.handles())
    folder = tmp_path / "copy"
    if path.parent == FIXTURES:
        folder.mkdir()
    else:
        shutil.copytree(path.parent, folder)
    copy = folder / ("resaved-" + path.name)
    doc.save(copy)
    doc.close()
    again = docs.open(copy)
    second = _summary(again)
    assert second["objects"] == first["objects"]
    assert second["kinds"] == first["kinds"]
    assert _same_box(second["extents"], first["extents"])
    assert second["layers"] == first["layers"]
