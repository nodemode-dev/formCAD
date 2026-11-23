import pytest


@pytest.fixture
def mm(engine):
    made = engine.new_doc(template="drawing-mm-a3")
    yield made
    try:
        made.close()
    except Exception:
        pass
