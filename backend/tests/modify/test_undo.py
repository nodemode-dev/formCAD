import pytest

from tests.modify.draw import close_rows, geometry_rows, line, pick, pline


def setup(doc):
    a = line(doc, "0,0", "20,0")
    b = line(doc, "10,-5", "10,10")
    p = pline(doc, "30,0", "40,0", "40,10", "30,10")
    return {"a": a, "b": b, "p": p}


def act_move(doc, h):
    doc.type("MOVE", "ALL", "", "0,0", "3,4")


def act_rotate(doc, h):
    doc.type("ROTATE", "ALL", "", "1,1", "37")


def act_scale(doc, h):
    doc.type("SCALE", "ALL", "", "0,0", "1.5")


def act_mirror(doc, h):
    doc.type("MIRROR", "ALL", "", "0,0", "1,2", "Y")


def act_offset(doc, h):
    doc.type("OFFSET", "2")
    pick(doc, h["p"], 35, 0)
    doc.type("35,-10", "")


def act_trim(doc, h):
    doc.type("TRIM")
    pick(doc, h["a"], 15, 0)
    doc.type("")


def act_fillet(doc, h):
    doc.type("FILLET", "R", "2")
    pick(doc, h["a"], 5, 0)
    pick(doc, h["b"], 10, 5)


def act_explode(doc, h):
    doc.type("EXPLODE", "#%x" % h["p"], "")


def act_array(doc, h):
    doc.type("ARRAYRECT", "#%x" % h["p"], "", "AS", "N", "COU", "2", "2", "")


ACTS = [act_move, act_rotate, act_scale, act_mirror, act_offset, act_trim, act_fillet, act_explode, act_array]


@pytest.mark.parametrize("act", ACTS, ids=[f.__name__[4:] for f in ACTS])
def test_each_modify_command_is_one_undo_step_and_redo_brings_the_result_back(doc, act):
    h = setup(doc)
    before = geometry_rows(doc)
    act(doc, h)
    assert doc.idle()
    after = geometry_rows(doc)
    assert not close_rows(after, before)
    doc.undo()
    assert close_rows(geometry_rows(doc), before, tol=0)
    doc.redo()
    assert close_rows(geometry_rows(doc), after, tol=0)
