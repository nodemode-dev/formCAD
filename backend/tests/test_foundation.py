import math

import pytest

from tests.support import geometry
from tests.support.dxf import Dxf
from tests.support.gcode import Program


def test_a_line_typed_on_the_command_line_lands_in_the_document(doc):
    doc.type("LINE", "0,0", "30,40", "")
    line = doc.only("line")
    assert geometry.close(geometry.dist(line["start"], line["end"]), 50.0)
    assert doc.idle()


def test_undo_removes_the_line_and_redo_brings_the_same_line_back(doc):
    doc.type("LINE", "0,0", "30,40", "")
    before = doc.only("line")
    doc.undo()
    assert doc.entities() == []
    doc.redo()
    after = doc.only("line")
    assert after["start"] == before["start"] and after["end"] == before["end"]


def test_a_request_without_the_session_key_is_refused(engine, doc):
    assert engine.status_of("GET", doc.url("/snapshot"), token=None) in (401, 403)
    assert engine.status_of("GET", doc.url("/snapshot"), token="not-the-key") in (401, 403)
    assert engine.status_of("GET", doc.url("/snapshot")) == 200


def test_a_circle_by_centre_and_radius_has_the_typed_radius(doc):
    doc.type("CIRCLE", "10,10", "7.5")
    circle = doc.only("circle")
    assert geometry.close(circle["radius"], 7.5)
    assert geometry.same_point(circle["center"], (10.0, 10.0))


@pytest.mark.kernel
def test_the_kernel_builds_a_box_with_the_faces_edges_and_extents_of_a_box(kernel):
    made = kernel.call("primitive", {"kind": "box", "dx": 10.0, "dy": 20.0, "dz": 30.0})
    try:
        summary = made["summary"]
        assert (summary["solids"], summary["faces"], summary["edges"], summary["vertices"]) == (1, 6, 12, 8)
        assert summary["valid"] and summary["closed"]
        flat = [float(v) for part in summary["bbox"] for v in (part if isinstance(part, (list, tuple)) else [part])]
        spans = sorted(round(flat[i + 3] - flat[i], 6) for i in range(3))
        assert spans == [10.0, 20.0, 30.0]
    finally:
        kernel.call("shape_free", {"id": made["id"]})


def test_the_geometry_helpers_agree_with_closed_forms():
    square = [(0, 0), (4, 0), (4, 3), (0, 3)]
    assert geometry.area(square) == 12.0
    assert geometry.path_length(square, closed=True) == 14.0
    assert geometry.centroid(square) == (2.0, 1.5)
    cube = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    assert geometry.close(geometry.mesh_volume(cube, faces), 1.0)
    assert geometry.close(geometry.mesh_area(cube, faces), 6.0)


def test_the_dxf_reader_finds_entities_layers_and_header_values():
    text = "\n".join(["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC", "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "0", "LAYER", "2", "WALLS", "0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES", "0", "LINE", "8", "WALLS", "10", "0", "20", "0", "11", "3", "21", "4", "0", "ENDSEC", "0", "EOF", ""])
    dxf = Dxf(text)
    line = dxf.entities("LINE")[0]
    assert line.layer == "WALLS" and line.point(10) == (0.0, 0.0, 0.0) and line.point(11) == (3.0, 4.0, 0.0)
    assert dxf.layers() == ["WALLS"] and dxf.variable("INSUNITS") == "4" and dxf.kinds() == {"LINE": 1}


def test_the_gcode_walker_follows_modal_motion_and_arcs():
    program = Program("G21 G90\nG0 Z5\nG0 X0 Y0\nM3 S12000\nG1 Z-2 F100\nG1 X10 F300\nG2 X20 Y0 I5 J0\nG0 Z5\nM5\nM30\n")
    assert program.units == "mm" and program.ended and program.lowest() == -2.0
    arc = [m for m in program.moves if m.arc][0]
    assert geometry.close(arc.radius, 5.0) and geometry.close(arc.length, math.pi * 5.0)
    assert geometry.close(program.cut_length(), 7.0 + 10.0 + math.pi * 5.0)
    assert program.arcs_are_consistent()
