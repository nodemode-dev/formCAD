import math

import numpy as np
import pytest

from tests.assembly.helpers import axis, copy_parts, flat, plane, point, pose, rot, spot, transform_of, direction
from tests.support.engine import Refused

TOL = 1e-7
START = pose(rot([1, 2, 3], 37.0), (40.0, -20.0, 15.0))


@pytest.fixture()
def pair(engine, fixtures, tmp_path):
    parts = copy_parts(fixtures, tmp_path / "parts", ("base", "pin"))
    a = engine.new_doc("", "assembly")
    a.post("/assembly/components", {"path": str(parts / "base.fcad")})
    a.post("/assembly/components", {"path": str(parts / "pin.fcad"), "transform": flat(START)})
    yield a
    engine.raw("POST", a.url("/close"), json={"force": True})


def mate(doc, kind, refs, value=None, **opt):
    body = {"kind": kind, "refs": refs, "opt": opt}
    if value is not None:
        body["value"] = value
    return doc.post("/mates", body)


def dof(doc, cid="C2"):
    return doc.get("/mates/status")["components"][cid]["dof"]


def test_coincident_planes_put_the_part_face_in_the_base_face_plane(pair):
    mate(pair, "coincident", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))])
    m = transform_of(pair, "C2")
    n = direction(m, (0, 0, -1))
    assert np.linalg.norm(np.cross(n, (0, 0, 1))) < TOL
    assert abs(point(m, (0, 0, 0))[2] - 10.0) < TOL


def test_coincident_points_bring_the_two_points_together(pair):
    mate(pair, "coincident", [spot("C1", (25, 30, 10)), spot("C2", (0, 0, 28))])
    assert np.linalg.norm(point(transform_of(pair, "C2"), (0, 0, 28)) - (25, 30, 10)) < TOL


def test_concentric_axes_share_one_line(pair):
    mate(pair, "concentric", [axis("C1", (25, 30, 0), (0, 0, 1), 3.0), axis("C2", (0, 0, 0), (0, 0, 1), 3.0)])
    m = transform_of(pair, "C2")
    d = direction(m, (0, 0, 1))
    assert np.linalg.norm(np.cross(d, (0, 0, 1))) < TOL
    assert np.linalg.norm(np.cross(point(m, (0, 0, 0)) - (25, 30, 0), (0, 0, 1))) < TOL


@pytest.mark.parametrize("value", [15.0, 42.5])
def test_distance_between_planes_is_the_given_value(pair, value):
    mate(pair, "distance", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))], value)
    m = transform_of(pair, "C2")
    assert np.linalg.norm(np.cross(direction(m, (0, 0, -1)), (0, 0, 1))) < TOL
    assert abs(abs(point(m, (0, 0, 0))[2] - 10.0) - value) < TOL


def test_editing_a_distance_mate_moves_the_part_to_the_new_distance(pair):
    made = mate(pair, "distance", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))], 15.0)
    pair.engine.patch(pair.url("/mates/%s" % made["mate"]["name"]), {"value": 25.0})
    assert abs(abs(point(transform_of(pair, "C2"), (0, 0, 0))[2] - 10.0) - 25.0) < TOL


@pytest.mark.parametrize("degrees", [30.0, 75.0, 120.0])
def test_angle_between_planes_is_the_given_angle(pair, degrees):
    mate(pair, "angle", [plane("C1", (0, 0, 0), (1, 0, 0)), plane("C2", (0, 0, 0), (1, 0, 0))], degrees)
    n = direction(transform_of(pair, "C2"), (1, 0, 0))
    assert abs(math.degrees(math.acos(max(-1.0, min(1.0, float(n @ (1, 0, 0)))))) - degrees) < 1e-6


def test_parallel_axes_point_the_same_way(pair):
    mate(pair, "parallel", [axis("C1", (0, 0, 0), (0, 1, 0)), axis("C2", (0, 0, 0), (0, 0, 1))])
    d = direction(transform_of(pair, "C2"), (0, 0, 1))
    assert np.linalg.norm(np.cross(d, (0, 1, 0))) < TOL


def test_perpendicular_planes_have_normals_at_right_angles(pair):
    mate(pair, "perpendicular", [plane("C1", (0, 0, 0), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, 1))])
    assert abs(float(direction(transform_of(pair, "C2"), (0, 0, 1)) @ (0, 0, 1))) < TOL


def test_tangent_cylinder_lies_on_the_plane_at_its_radius(pair):
    mate(pair, "tangent", [plane("C1", (0, 0, 10), (0, 0, 1)), axis("C2", (0, 0, 14), (1, 0, 0), 3.0)])
    m = transform_of(pair, "C2")
    assert abs(float(direction(m, (1, 0, 0)) @ (0, 0, 1))) < TOL
    assert abs(abs(point(m, (0, 0, 14))[2] - 10.0) - 3.0) < TOL


def test_degrees_of_freedom_fall_from_six_to_three_to_one_to_zero(pair):
    assert dof(pair) == 6
    mate(pair, "coincident", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))])
    assert dof(pair) == 3
    mate(pair, "concentric", [axis("C1", (25, 30, 0), (0, 0, 1)), axis("C2", (0, 0, 0), (0, 0, 1))])
    assert dof(pair) == 1
    mate(pair, "angle", [plane("C1", (0, 0, 0), (1, 0, 0)), plane("C2", (0, 0, 0), (1, 0, 0)), axis("C1", (0, 0, 0), (0, 0, 1))], 20.0)
    status = pair.get("/mates/status")
    assert status["components"]["C2"]["dof"] == 0 and status["dof"] == 0 and status["state"] == "fully"


def test_a_fixed_part_has_no_degrees_of_freedom(pair):
    pair.engine.patch(pair.url("/assembly/components/C2"), {"fixed": True})
    assert dof(pair) == 0


def test_a_conflicting_mate_is_refused_and_nothing_moves(pair):
    mate(pair, "distance", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))], 10.0)
    before = transform_of(pair, "C2")
    with pytest.raises(Refused) as err:
        mate(pair, "distance", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))], 20.0)
    assert err.value.status == 409 and "explanation" in err.value.body
    assert np.array_equal(transform_of(pair, "C2"), before)
    assert len(pair.get("/mates")["mates"]) == 1


def test_suppressing_a_mate_frees_the_part_and_unsuppressing_restores_it(pair):
    made = mate(pair, "coincident", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))])
    name = made["mate"]["name"]
    pair.engine.patch(pair.url("/mates/%s" % name), {"suppressed": True})
    assert dof(pair) == 6
    pair.engine.patch(pair.url("/mates/%s" % name), {"suppressed": False})
    assert dof(pair) == 3


def test_deleting_a_mate_removes_it_and_returns_the_freedom(pair):
    made = mate(pair, "coincident", [plane("C1", (0, 0, 10), (0, 0, 1)), plane("C2", (0, 0, 0), (0, 0, -1))])
    pair.delete("/mates/%s" % made["mate"]["name"])
    assert pair.get("/mates")["mates"] == [] and dof(pair) == 6


def test_undo_of_a_mate_puts_the_part_back_and_redo_solves_it_again(pair):
    mate(pair, "coincident", [spot("C1", (25, 30, 10)), spot("C2", (0, 0, 28))])
    pair.undo()
    assert np.allclose(transform_of(pair, "C2"), START, atol=1e-12) and pair.get("/mates")["mates"] == []
    pair.redo()
    assert np.linalg.norm(point(transform_of(pair, "C2"), (0, 0, 28)) - (25, 30, 10)) < TOL
