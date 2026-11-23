import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FIXTURES = REPO / "fixtures"
DATA = Path(os.environ.get("FORMCAD_TEST_DATA") or tempfile.mkdtemp(prefix="formcad-tests-"))
DATA.mkdir(parents=True, exist_ok=True)
os.environ["FORMCAD_DATA_DIR"] = str(DATA)
os.environ["FORMCAD_LIBRARY_DIR"] = str(DATA / "Projects")
os.environ.setdefault("FORMCAD_DIST", str(DATA / "no-frontend"))
os.environ.pop("FORMCAD_LOCKED", None)
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests.support.engine import HOST, Engine  # noqa: E402

WORKERS_REQUIRED = os.environ.get("FORMCAD_TEST_WORKERS") == "required"


def pytest_configure(config):
    config.addinivalue_line("markers", "kernel: needs the geometry kernel worker")
    config.addinivalue_line("markers", "mesher: needs the mesher worker")
    config.addinivalue_line("markers", "live: starts the real engine process")
    config.addinivalue_line("markers", "slow: takes more than ten seconds")


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def engine():
    from fastapi.testclient import TestClient

    from app.core import guard
    from app.main import app

    with TestClient(app, base_url=HOST) as client:
        yield Engine(client, guard.TOKEN)


@pytest.fixture()
def doc(engine):
    d = engine.new_doc()
    yield d
    engine.raw("POST", d.url("/close"), json={"force": True})


@pytest.fixture()
def docs(engine):
    made = []

    def make(name: str = ""):
        d = engine.new_doc(name)
        made.append(d)
        return d

    def opened(path):
        d = engine.open_doc(path)
        made.append(d)
        return d

    make.open = opened
    yield make
    for d in made:
        engine.raw("POST", d.url("/close"), json={"force": True})


def _missing(name: str, hint: str) -> None:
    message = "the %s worker is not installed (%s)" % (name, hint)
    if WORKERS_REQUIRED:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def kernel(engine):
    from app.services import kernel as service

    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if service.probe(force=True):
            return service
        if service.resolve() is None:
            break
        time.sleep(1.0)
    _missing("kernel", "./formCAD install-kernel")


@pytest.fixture(scope="session")
def mesher(engine):
    from app.services import mesher as service

    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if service.probe(force=True):
            return service
        if service.resolve() is None:
            break
        time.sleep(1.0)
    _missing("mesher", "./formCAD install-mesher")


@pytest.fixture(autouse=True)
def _worker_markers(request):
    if request.node.get_closest_marker("kernel"):
        request.getfixturevalue("kernel")
    if request.node.get_closest_marker("mesher"):
        request.getfixturevalue("mesher")
