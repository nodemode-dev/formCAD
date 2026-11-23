import pytest

DRAWS = {
    "line": ("LINE", "0,0", "10,0", "10,10", "0,10", "C"),
    "pline": ("PLINE", "0,0", "10,0", "A", "10,10", "L", "0,10", ""),
    "circle": ("CIRCLE", "3P", "0,0", "10,0", "0,10"),
    "arc": ("ARC", "10,0", "C", "0,0", "A", "90"),
    "rectang": ("RECTANG", "F", "2", "0,0", "20,10"),
    "polygon": ("POLYGON", "6", "0,0", "I", "10"),
    "ellipse": ("ELLIPSE", "0,0", "10,0", "3"),
    "spline": ("SPLINE", "0,0", "5,5", "10,0", "15,5", ""),
    "xline": ("XLINE", "0,0", "10,10", "10,-10", ""),
    "point": ("POINT", "4,4"),
    "donut": ("DONUT", "2", "4", "0,0", "10,0", ""),
    "hatch": ("HATCH", "45,45", ""),
}


@pytest.mark.parametrize("name", sorted(DRAWS))
def test_each_draw_command_is_one_undo_step_and_redo_brings_back_the_same_objects(doc, name):
    doc.type("RECTANG", "40,40", "60,60")
    before = doc.entities()
    doc.type(*DRAWS[name])
    assert doc.idle() and not doc.error()
    after = doc.entities()
    assert len(after) > len(before)
    doc.undo()
    assert doc.entities() == before
    doc.redo()
    assert doc.entities() == after
