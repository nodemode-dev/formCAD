import numpy as np
import pytest

from tests.meshsim import helpers as h

SIDE = 10.0


def cube(doc, segments=1):
    h.metric(doc)
    return h.handle_of(doc.command("subdbox", size=[SIDE] * 3, segments=[segments] * 3))


def limit(doc, handle, level):
    got = doc.post("/subd/%d/limit" % handle, {"level": level})
    return np.array(got["vertices"], dtype=float), np.array(got["quads"], dtype=int)


def quad_volume(v, quads):
    total = 0.0
    for a, b, c, d in quads:
        for t in ((a, b, c), (a, c, d)):
            p, q, r = v[list(t)]
            total += np.dot(p, np.cross(q, r)) / 6.0
    return abs(total)


def test_a_cube_cage_subdivides_to_a_smaller_rounded_shape_whose_volume_converges(doc):
    form = cube(doc)
    vols = [quad_volume(*limit(doc, form, level)) for level in (1, 2, 3, 4)]
    assert all(v < SIDE ** 3 for v in vols)
    gaps = [abs(vols[k + 1] - vols[k]) for k in range(3)]
    assert gaps[1] < 0.5 * gaps[0] and gaps[2] < 0.5 * gaps[1]


def test_the_limit_of_a_cube_cage_keeps_the_cube_symmetry_and_stays_inside_the_cage(doc):
    form = cube(doc)
    v, _q = limit(doc, form, 3)
    centre = np.full(3, SIDE / 2)
    assert np.allclose(v.mean(axis=0), centre, atol=1e-9)
    assert np.all(v > 0.0) and np.all(v < SIDE)
    spans = v.max(axis=0) - v.min(axis=0)
    assert np.allclose(spans, spans[0], atol=1e-9)
    assert np.all(spans < SIDE)


def test_creasing_every_edge_of_a_cube_cage_keeps_the_limit_a_sharp_cube(doc):
    form = cube(doc)
    edges = doc.get("/subd/%d" % form)["edges"]
    reply = doc.command("subdcrease", handle=form, edges=edges, weight=10)
    assert not reply.get("error"), reply.get("error")
    v, q = limit(doc, h.handle_of(reply), 3)
    assert quad_volume(v, q) == pytest.approx(SIDE ** 3, rel=1e-9)
    assert v.min(axis=0) == pytest.approx([0, 0, 0], abs=1e-9)
    assert v.max(axis=0) == pytest.approx([SIDE] * 3, abs=1e-9)


def test_a_creased_edge_loop_stays_in_its_plane_while_the_uncreased_side_rounds_off(doc):
    form = cube(doc)
    cage = doc.get("/subd/%d" % form)
    pts = np.array(cage["v"], dtype=float)
    bottom = [e for e in cage["edges"] if pts[e[0]][2] == 0 and pts[e[1]][2] == 0]
    assert len(bottom) == 4
    plain, _q = limit(doc, form, 3)
    reply = doc.command("subdcrease", handle=form, edges=bottom, weight=10)
    assert not reply.get("error"), reply.get("error")
    v, _q = limit(doc, h.handle_of(reply), 3)
    on_plane = np.abs(v[:, 2]) < 1e-9
    assert on_plane.sum() >= 8
    assert v[:, 2].min() > -1e-9
    assert plain[:, 2].min() > 0.05 * SIDE
    assert v[:, 2].max() < SIDE - 0.05 * SIDE


@pytest.mark.kernel
def test_a_converted_form_is_a_closed_solid_with_the_volume_of_its_limit_surface(doc):
    form = cube(doc, 2)
    reply = doc.command("subdconvert", handle=form)
    assert not reply.get("error"), reply.get("error")
    solid = h.handle_of(reply)
    props = doc.get("/solids/%d/massprops" % solid)
    assert props["closed"] and props["valid"]
    v, q = limit(doc, form, 4)
    assert props["volume"] == pytest.approx(quad_volume(v, q), rel=5e-3)
    assert props["centroid"] == pytest.approx([SIDE / 2] * 3, abs=1e-6)
