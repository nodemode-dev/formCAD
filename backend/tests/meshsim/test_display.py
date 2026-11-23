import math
import struct

import numpy as np
import pytest

from tests.meshsim import helpers as h

pytestmark = pytest.mark.kernel

RADIUS = 10.0
HEIGHT = 20.0


def body_mesh(path):
    raw = open(path, "rb").read()
    head = struct.unpack_from("<18I", raw, 0)
    assert head[16] == len(raw)
    nv, nt = head[2], head[3]
    pos = np.frombuffer(raw, "<f4", nv * 3, head[8]).reshape(-1, 3).astype(float)
    idx = np.frombuffer(raw, "<u4", nt * 3, head[10]).reshape(-1, 3)
    return pos, idx


def scene_bodies(doc, detail=1.0):
    raw = doc.get("/scene", since=0, detail=detail).content
    head = struct.unpack_from("<13IfII", raw, 0)
    assert head[3] == len(raw)
    count, table = head[5], head[8]
    out = {}
    for i in range(count):
        rec = struct.unpack_from("<18I6f8I", raw, table + 128 * i)
        handle, nv, nt, pos_at, idx_at = rec[0], rec[4], rec[5], rec[10], rec[12]
        pos = np.frombuffer(raw, "<f4", nv * 3, pos_at).reshape(-1, 3).astype(float)
        idx = np.frombuffer(raw, "<u4", nt * 3, idx_at).reshape(-1, 3)
        out[handle] = (pos, idx)
    return out


def volume_of(pos, idx):
    t = pos[idx]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)


def tessellate(kernel, tmp_path, kind, linear):
    made = kernel.call("primitive", {"kind": kind, "radius": RADIUS, "height": HEIGHT})
    path = tmp_path / ("%s-%g.mesh" % (kind, linear))
    try:
        kernel.call("tessellate", {"id": made["id"], "linear": linear, "angular": 1.0, "path": str(path)})
    finally:
        kernel.call("shape_free", {"id": made["id"]})
    return body_mesh(path)


def radial(kind, p):
    return np.linalg.norm(p, axis=-1) if kind == "sphere" else np.hypot(p[..., 0], p[..., 1])


def chord_error(kind, pos, idx):
    tri = pos[idx]
    on = np.all(np.abs(radial(kind, tri) - RADIUS) < 1e-4, axis=1)
    if kind == "cylinder":
        on &= np.ptp(tri[:, :, 2], axis=1) > 1e-6
    tri = tri[on]
    samples = np.concatenate([tri.mean(axis=1), 0.5 * (tri[:, 0] + tri[:, 1]), 0.5 * (tri[:, 1] + tri[:, 2]), 0.5 * (tri[:, 2] + tri[:, 0])])
    return float((RADIUS - radial(kind, samples)).max())


EXACT = {"sphere": 4.0 / 3.0 * math.pi * RADIUS ** 3, "cylinder": math.pi * RADIUS ** 2 * HEIGHT}


@pytest.mark.parametrize("kind", ["sphere", "cylinder"])
@pytest.mark.parametrize("linear", [0.2, 0.05, 0.02])
def test_the_chord_error_of_a_tessellated_round_body_stays_within_the_tolerance_asked_for(kernel, tmp_path, kind, linear):
    pos, idx = tessellate(kernel, tmp_path, kind, linear)
    assert np.all(radial(kind, pos[np.abs(radial(kind, pos) - RADIUS) < 1e-3]) <= RADIUS + 1e-5)
    assert 0.0 < chord_error(kind, pos, idx) <= linear


@pytest.mark.parametrize("kind", ["sphere", "cylinder"])
def test_a_finer_tessellation_gives_more_triangles_and_a_volume_closer_to_closed_form(kernel, tmp_path, kind):
    rows = []
    for linear in (0.2, 0.05, 0.0125):
        pos, idx = tessellate(kernel, tmp_path, kind, linear)
        rows.append((len(idx), abs(volume_of(pos, idx) - EXACT[kind])))
    assert rows[0][0] < rows[1][0] < rows[2][0]
    assert rows[0][1] > rows[1][1] > rows[2][1]
    assert rows[2][1] < 2e-3 * EXACT[kind]


def test_the_display_mesh_of_a_sphere_is_closed_on_the_surface_and_close_to_its_volume(doc):
    h.metric(doc)
    s = h.handle_of(doc.command("sphere", center=[5, 6, 7], radius=RADIUS))
    pos, idx = scene_bodies(doc)[s]
    centred = pos - np.array([5.0, 6.0, 7.0])
    assert np.abs(np.linalg.norm(centred, axis=1) - RADIUS).max() < 1e-5 * RADIUS * 10
    tris = [tuple(tuple(v) for v in pos[t]) for t in idx]
    assert h.open_edges(tris) == 0
    v = volume_of(centred, idx)
    assert v < EXACT["sphere"] and v == pytest.approx(EXACT["sphere"], rel=1e-2)


def test_the_display_mesh_of_a_moved_box_has_the_box_extents_and_volume(doc):
    h.metric(doc)
    b = h.box(doc, [10, 20, 30], [1, 2, 3])
    pos, idx = scene_bodies(doc)[b]
    assert pos.min(axis=0) == pytest.approx([1, 2, 3], abs=1e-5)
    assert pos.max(axis=0) == pytest.approx([11, 22, 33], abs=1e-5)
    assert volume_of(pos, idx) == pytest.approx(6000.0, rel=1e-6)
